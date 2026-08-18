"""한글 직접비교 매칭 재설계 시뮬레이션 (MATCHING_REDESIGN_PROPOSAL.md 근거).

로마자 유사도 대신, 사람이 GFW 영문명을 직접 한글로 변환한 후보
(`gfw_korean_name_candidates.csv`)를 TAC/어선원부 원문 한글과 직접
비교하면 정밀도가 얼마나 오르는지(대신 커버리지를 얼마나 잃는지)
확인한다. **아직 실제 파이프라인(process/match_fuzzy_name.py,
assemble_matches.py)에 반영 안 됨** — 팀 결정(제안서 참고) 전까지는
이 스크립트가 유일한 산출 경로다.

핵심 설계:
- 이름비교는 exact match만 쓴다(fuzzy 0.85+는 검증 사례 19/19가
  "제N호"류 내부번호 소실 버그로 오매칭이라 폐기 — 제안서 발견 3 참고)
- 숫자접두어(2~4자리) 하드필터는 기존 그대로(사람 라벨링 검증됨)
- 동률 후보는 최근접 항구 거리로 소프트 타이브레이크:
  ≤50km면 verified, 50~150km면 held(낮은신뢰도), 그 외/위치정보
  없으면 held_multi(모호, 계산 불가)
- (source,key) 동일한 후보는 데이터중복으로 보고 dedup

사용법:
    python simulate_korean_name_matching.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "process"))

from geocode_kr import geocode as geocode_sigungu  # noqa: E402
from match_fuzzy_name import (  # noqa: E402
    EVENTS_PATH,
    GFW_VESSELS_PATH,
    PORTS_PATH,
    REGISTRY_PATH,
    TAC_PATH,
    _digit_prefix,
    _haversine_km,
    _load_jsonl,
    _normalize,
    _romanize,
    _similarity,
    _vessel_centroids,
)

KOREAN_CSV_PATH = Path(__file__).resolve().parent.parent / "gfw_korean_name_candidates.csv"
ROMAN_FALLBACK_THRESHOLD = 0.85  # 한글후보 자체가 없는 벡터에만 씀
LOC_VERIFIED_KM = 50.0
LOC_HELD_CAP_KM = 150.0

# 참고용 — 현재 라이브에 커밋된 로마자매칭(FUZZY_NAME_THRESHOLD=0.8) 실측치.
# assemble_matches.py를 재실행해서 얻은 값이며 여기서 재계산하지 않는다.
BASELINE_TIER2_CALLSIGN = 3
BASELINE_TIER3_FUZZY = 2878
BASELINE_UNMATCHED = 2442
BASELINE_PRECISION = 0.75  # PROCESS_LOG.md 49번, 사람 라벨링 80쌍


def _strip_ho(name: str) -> str:
    name = (name or "").strip()
    return name[:-1] if name.endswith("호") else name


def _load_korean_candidates() -> dict:
    out = {}
    with KOREAN_CSV_PATH.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cands = [c.strip() for c in row["koreanNameCandidates"].split("|") if c.strip()]
            out[row["vesselId"]] = cands
    return out


def _build_pool() -> list:
    pool = []
    for t in _load_jsonl(TAC_PATH):
        pool.append({"source": "tac", "name": t["nameTac"], "key": t["vesselNoTac"], "ports": t.get("portNamesTac") or []})
    for r in _load_jsonl(REGISTRY_PATH):
        pool.append({"source": "vessel_registry", "name": r["nameRegistry"], "key": r["vesselNoRegistry"], "ports": [r["portNameRegistry"]] if r.get("portNameRegistry") else []})
    for p in pool:
        p["base"] = _strip_ho(p["name"])
        p["digitPrefix"] = _digit_prefix(_normalize(p["name"]))
        p["romanized"] = _normalize(_romanize(p["name"]))
    return pool


def _nearest_port_km(ports: dict, centroid, port_names) -> float | None:
    if not centroid:
        return None
    best = None
    for port_name in port_names:
        coord = ports.get(port_name) or geocode_sigungu(port_name)
        if not coord:
            continue
        d = _haversine_km(centroid[0], centroid[1], coord[0], coord[1])
        if best is None or d < best:
            best = d
    return best


def run() -> Counter:
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)
    pool = _build_pool()
    ports = {p["portName"]: (p["latitude"], p["longitude"]) for p in _load_jsonl(PORTS_PATH)}
    centroids = _vessel_centroids(_load_jsonl(EVENTS_PATH))
    gfw_korean = _load_korean_candidates()

    counts = Counter()

    for gfw in gfw_vessels:
        name = gfw["selfReportedName"] or gfw["registryName"]
        if not name:
            counts["no_name"] += 1
            continue

        norm = _normalize(name)
        digit = _digit_prefix(norm)
        centroid = centroids.get(gfw["vesselId"])
        korean_cands = gfw_korean.get(gfw["vesselId"], [])

        if not korean_cands:
            # 한글변환 후보가 없는 벡터(범용영문명 등) — 로마자 fallback만 시도.
            best = None
            for p in pool:
                if digit and p["digitPrefix"] and digit != p["digitPrefix"]:
                    continue
                s = _similarity(norm, p["romanized"])
                if best is None or s > best:
                    best = s
            if best is not None and best >= ROMAN_FALLBACK_THRESHOLD:
                counts["held_로마자fallback"] += 1
            else:
                counts["unmatched"] += 1
            continue

        passing = []
        for p in pool:
            if digit and p["digitPrefix"] and digit != p["digitPrefix"]:
                continue
            if p["base"] in korean_cands:  # exact만, fuzzy는 폐기(제안서 발견 3)
                dist = _nearest_port_km(ports, centroid, p["ports"])
                passing.append({"source": p["source"], "key": p["key"], "distKm": dist})

        if not passing:
            counts["unmatched"] += 1
            continue

        distinct_vessels = {(c["source"], c["key"]) for c in passing}
        if len(distinct_vessels) == 1:
            counts["verified"] += 1
            continue

        with_dist = [c for c in passing if c["distKm"] is not None]
        if with_dist:
            with_dist.sort(key=lambda x: x["distKm"])
            nearest = with_dist[0]
            second = with_dist[1]["distKm"] if len(with_dist) > 1 else None
            unique_nearest = second is None or abs(second - nearest["distKm"]) > 0.05
            if unique_nearest and nearest["distKm"] <= LOC_VERIFIED_KM:
                counts["verified"] += 1
                continue
            if unique_nearest and nearest["distKm"] <= LOC_HELD_CAP_KM:
                counts["held_위치애매"] += 1
                continue

        counts["held_multi_동명이선"] += 1

    return counts


def main() -> None:
    counts = run()
    total = sum(counts.values())

    print(f"=== 한글직접비교 시뮬레이션 결과 (GFW {total}척) ===\n")
    for k, v in counts.most_common():
        print(f"  {k:24} {v:5}척 ({v / total * 100:.1f}%)")

    verified = counts["verified"]
    held_usable = counts["held_위치애매"]
    print(f"\n계산가능(verified+held_위치애매): {verified + held_usable}척 ({(verified + held_usable) / total * 100:.1f}%)")

    print("\n=== 기존(현재 라이브 커밋본, FUZZY_NAME_THRESHOLD=0.8) 참고치 ===")
    baseline_matched = BASELINE_TIER2_CALLSIGN + BASELINE_TIER3_FUZZY
    print(f"  matched  {baseline_matched:5}척 ({baseline_matched / total * 100:.1f}%), 정밀도 실측 ~{BASELINE_PRECISION * 100:.0f}%")
    print(f"  unmatched {BASELINE_UNMATCHED:5}척 ({BASELINE_UNMATCHED / total * 100:.1f}%)")
    print(f"  추정 진짜정답 ≈{round(baseline_matched * BASELINE_PRECISION)}척 / 추정 오탐 ≈{round(baseline_matched * (1 - BASELINE_PRECISION))}척")


if __name__ == "__main__":
    main()
