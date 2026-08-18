"""한글 직접비교 매칭 재설계 시뮬레이션.

라이브 파이프라인에 반영된 매칭 로직을 검증하고 기존 결과와 비교한다.
실제 매칭 산출은 `data_new/process/match_fuzzy_name.py`가 담당한다.

핵심 설계(자세한 배경은 README.md 참고):
- 이름비교는 exact match만 쓴다(로마자 유사도 fuzzy는 구조적 오탐이 있어 안 씀)
- 숫자 하드필터: 자릿수 상관없이 GFW·후보 양쪽에 다 숫자가 보이는데
  값이 다르면 배제(`_any_digit`)
- pool 쪽 이름에서 "제<숫자>" 접두어를 비교 전용으로 한 번 더 뗀다
  (`_strip_je_number`) — GFW 한글변환은 숫자를 통째로 분리해서 뺐는데
  TAC/어선원부 원문은 "제707태근호"처럼 번호를 이름에 그대로 갖고 있어
  안 떼면 exact match가 실패한다
- 동률 후보는 카카오 지오코딩 거리로 판단: 후보 전원의 위치를 알고
  유일하게 ≤150km면 verified, 그 외/위치정보 없으면 held_multi(모호,
  계산 불가) — "모른다"를 "가깝다"로 오판하지 않는다
- (source,key) 동일한 후보는 데이터중복으로 보고 dedup

한 척씩 old(현재 라이브)/new(이 시뮬레이션) 판정을 나란히 놓은
`output/korean_matching_comparison.jsonl`도 생성해 사례별 검토를 지원한다.

사용법:
    python simulate_korean_name_matching.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "process"))

from geocode_kakao import geocode_kakao  # noqa: E402 — data_new/process/에서 옮겨옴, sys.path로 찾음
from match_fuzzy_name import (  # noqa: E402
    EVENTS_PATH,
    GFW_VESSELS_PATH,
    REGISTRY_PATH,
    TAC_PATH,
    _haversine_km,
    _load_jsonl,
    _normalize,
    _romanize,
    _similarity,
    _vessel_centroids,
)


def _any_digit(normalized: str) -> str:
    """이름에 보이는 숫자 하나(자릿수 제한 없음, 1자리 포함).

    원래는 2~4자리만 하드필터로 썼다(사람 라벨링 49번이 검증한 범위가
    거기까지라서 — "일치하면 신뢰"라는 긍정신호로 쓸 땐 1자리는 "제1호"
    류가 너무 흔해 우연히 겹칠 위험이 컸음). 근데 발견 8·9에서 실측
    확인한 건 그거랑 다른 얘기다: "불일치하면 배제"라는 부정신호로 쓸 땐
    자릿수가 몇이든 상관없다 — "제8해상호"의 8이든 "제505대풍호"의
    505든, GFW가 신고한 숫자랑 눈으로 봐도 다르면 그냥 다른 배다.
    그래서 2~4자리 하드필터와 1자리 예외처리를 따로 유지할 이유가
    없어 이거 하나로 통일함(양쪽 다 뭐든 숫자가 보이는데 값이 다르면
    배제)."""
    m = re.search(r"(\d+)", normalized)
    return m.group(1) if m else ""


KOREAN_CSV_PATH = Path(__file__).resolve().parent.parent / "gfw_korean_name_candidates.csv"  # data_new/ 최상위로 이동됨(채택 후)
OLD_MATCHES_PATH = Path(__file__).resolve().parent.parent / "processed" / "final_vessel_matches.jsonl"
COMPARISON_OUT_PATH = Path(__file__).resolve().parent / "output" / "korean_matching_comparison.jsonl"
ROMAN_FALLBACK_THRESHOLD = 0.85  # 한글후보 자체가 없는 벡터에만 씀
LOC_VERIFIED_KM = 150.0  # 근해어업은 등록항에서 150km까지도 나가 조업함(사용자 확인, 2026-08-18)
LOC_HELD_CAP_KM = 150.0

# 참고용 — 현재 라이브에 커밋된 로마자매칭(FUZZY_NAME_THRESHOLD=0.8) 실측치.
# assemble_matches.py를 재실행해서 얻은 값이며 여기서 재계산하지 않는다.
BASELINE_TIER2_CALLSIGN = 3
BASELINE_TIER3_FUZZY = 2878
BASELINE_UNMATCHED = 2442
BASELINE_PRECISION = 0.75  # PROCESS_LOG.md 49번, 사람 라벨링 80쌍


def _load_old_matches() -> dict:
    """현재 라이브 커밋본(final_vessel_matches.jsonl)을 gfwVesselId로 색인.
    old/new 나란히 비교용 — 재실행하지 않고 커밋된 그대로 읽는다."""
    out = {}
    if not OLD_MATCHES_PATH.exists():
        return out
    for row in _load_jsonl(OLD_MATCHES_PATH):
        tac = row.get("tac") or {}
        out[row["gfwVesselId"]] = {
            "matchTier": row.get("matchTier"),
            "matchedName": tac.get("nameTac"),
            "fuzzyScore": row.get("fuzzyScore"),
        }
    return out


def _strip_ho(name: str) -> str:
    name = (name or "").strip()
    return name[:-1] if name.endswith("호") else name


def _strip_je_number(base: str) -> str:
    """"제707태근" -> "태근". GFW 쪽 한글변환은 숫자를 통째로 분리해서
    뺐는데(letterPart_호제외 컬럼), TAC/어선원부 원문은 "제N호" 선단
    일련번호를 이름에 그대로 갖고 있어 exact match가 실패하던 버그
    (교차분석에서 확인: old확신/new실패 935척 중 124척이 이 패턴).
    숫자일치는 이미 별도 하드필터(_any_digit)로 확인하니, 여기서
    또 떼도 변별력 손실 없음 — 비교 전용 정규화일 뿐 표시용 원본
    이름(matchedName)은 그대로 둔다."""
    return re.sub(r"^제\d+", "", base)


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
        p["compareBase"] = _strip_je_number(p["base"])
        # compareBase("제N호" 뗀 것)가 아니라 base(원문에서 호만 뗀 것)에서
        # 뽑아야 함 — compareBase는 "제8해상"->"해상"처럼 그 숫자 자체를
        # 지워버려서 anyDigit이 항상 빈 값이 됨(발견 8). 숫자는 원래
        # ASCII라 _normalize(한글 다 지움) 없이 base 원문에 바로 찾는다.
        p["anyDigit"] = _any_digit(p["base"])
        p["romanized"] = _normalize(_romanize(p["name"]))
    return pool


def _nearest_port_km(centroid, port_names) -> float | None:
    if not centroid:
        return None
    best = None
    for port_name in port_names:
        coord = geocode_kakao(port_name)
        if not coord:
            continue
        d = _haversine_km(centroid[0], centroid[1], coord[0], coord[1])
        if best is None or d < best:
            best = d
    return best


def run() -> list:
    """GFW 선박 1척당 1행. `category`가 이번 시뮬레이션 판정,
    `old`가 현재 라이브 판정(비교용)."""
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)
    pool = _build_pool()
    centroids = _vessel_centroids(_load_jsonl(EVENTS_PATH))
    gfw_korean = _load_korean_candidates()
    old_matches = _load_old_matches()

    rows = []

    for gfw in gfw_vessels:
        vessel_id = gfw["vesselId"]
        name = gfw["selfReportedName"] or gfw["registryName"]
        old = old_matches.get(vessel_id)
        row = {"gfwVesselId": vessel_id, "gfwName": name, "old": old}

        if not name:
            rows.append({**row, "category": "no_name", "matchedName": None, "distKm": None, "candidateCount": 0})
            continue

        norm = _normalize(name)
        gfw_any_digit = _any_digit(norm)
        centroid = centroids.get(vessel_id)
        korean_cands = gfw_korean.get(vessel_id, [])

        if not korean_cands:
            # 한글변환 후보가 없는 벡터(범용영문명 등) — 로마자 fallback만 시도.
            best = None
            best_name = None
            for p in pool:
                if gfw_any_digit and p["anyDigit"] and gfw_any_digit != p["anyDigit"]:
                    continue
                s = _similarity(norm, p["romanized"])
                if best is None or s > best:
                    best, best_name = s, p["name"]
            if best is not None and best >= ROMAN_FALLBACK_THRESHOLD:
                rows.append({**row, "category": "held_로마자fallback", "matchedName": best_name, "romanScore": round(best, 3), "distKm": None, "candidateCount": 1})
            else:
                rows.append({**row, "category": "unmatched", "matchedName": None, "distKm": None, "candidateCount": 0})
            continue

        passing = []
        for p in pool:
            # 발견 8·9: 자릿수 상관없이 양쪽 다 숫자가 보이는데 값이
            # 다르면 반대증거로 배제("102HAE SANG"vs"제8해상호",
            # "NO.2JAESUNGHO"vs"제22재성호" 둘 다 이 한 줄로 걸러짐).
            if gfw_any_digit and p["anyDigit"] and gfw_any_digit != p["anyDigit"]:
                continue
            if p["base"] in korean_cands or p["compareBase"] in korean_cands:  # exact만(fuzzy는 폐기, 발견 3) + "제N호" 정규화(발견 4)
                dist = _nearest_port_km(centroid, p["ports"])
                passing.append({"source": p["source"], "key": p["key"], "name": p["name"], "distKm": dist})

        if not passing:
            rows.append({**row, "category": "unmatched", "matchedName": None, "distKm": None, "candidateCount": 0, "koreanCandidates": korean_cands})
            continue

        distinct_vessels = {(c["source"], c["key"]) for c in passing}
        if len(distinct_vessels) == 1:
            # 버그 수정(2026-08-18): 후보가 애초에 1개뿐(경쟁자 없음)이라고
            # 거리 체크 없이 무조건 verified로 확정하면 안 됨 — 375km짜리도
            # verified로 새는 사례를 사용자가 직접 찾아냄. 다른 경로처럼
            # 거리 신뢰도 기준을 여기도 적용한다.
            p = passing[0]
            d = p["distKm"]
            if d is not None and d > LOC_HELD_CAP_KM:
                rows.append({**row, "category": "held_multi_동명이선", "matchedName": None, "distKm": None, "candidateCount": 1, "candidateNames": [p["name"]]})
            else:
                category = "verified" if (d is not None and d <= LOC_VERIFIED_KM) else "held_위치애매"
                rows.append({**row, "category": category, "matchedName": p["name"], "distKm": d, "candidateCount": 1})
            continue

        # 동률(후보 2개+) — 벡터 단독 최근접 타이브레이크로 풀어본다.
        resolved = _try_resolve_by_nearest(passing)
        if resolved is not None:
            category, matched_name, dist = resolved
            rows.append({**row, "category": category, "matchedName": matched_name, "distKm": dist, "candidateCount": len(distinct_vessels)})
        else:
            rows.append({**row, "category": "held_multi_동명이선", "matchedName": None, "distKm": None, "candidateCount": len(distinct_vessels), "candidateNames": [p["name"] for p in passing]})

    return rows


def _try_resolve_by_nearest(passing: list) -> tuple | None:
    """동률 후보 중 유일하게 최근접인 게 있으면 (category, matchedName, distKm),
    없으면 None. 벡터 단독 판단 — 다른 벡터가 그 후보를 원하는지는 안 봄.

    버그 수정(2026-08-18): 후보 중 하나라도 지오코딩 실패로 거리를 못
    구했으면 여기서 확정하지 않는다 — "거리 모름"을 "후보 아님"으로
    취급해서, 지오코딩 안 된 후보가 조용히 비교에서 빠지고 지오코딩된
    후보 1개만 "유일한 최근접"으로 둔갑하는 사례를 실측으로 확인함
    (동률 2,150척 중 336척, 15.6%가 이 패턴 — TAC 항구명 지오코딩
    성공률 66.2%, 어선원부는 18.7%뿐이라 흔하게 발생함). 후보 전원의
    거리를 알 때만 "진짜 유일하게 가깝다"고 판단한다."""
    if any(p["distKm"] is None for p in passing):
        return None
    with_dist = sorted(passing, key=lambda x: x["distKm"])
    nearest = with_dist[0]
    second = with_dist[1]["distKm"] if len(with_dist) > 1 else None
    unique_nearest = second is None or abs(second - nearest["distKm"]) > 0.05
    if not unique_nearest:
        return None
    if nearest["distKm"] <= LOC_VERIFIED_KM:
        return ("verified", nearest["name"], nearest["distKm"])
    if nearest["distKm"] <= LOC_HELD_CAP_KM:
        return ("held_위치애매", nearest["name"], nearest["distKm"])
    return None


def main() -> None:
    rows = run()
    counts = Counter(r["category"] for r in rows)
    total = len(rows)

    COMPARISON_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COMPARISON_OUT_PATH.open("w", encoding="utf-8") as out:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"척별 old/new 비교 파일 -> {COMPARISON_OUT_PATH}")
    print("(카테고리로 필터링해서 직접 스팟체크해보세요: grep 'held_multi_동명이선' ... 등)\n")

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
