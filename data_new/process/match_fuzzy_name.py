"""매칭 3단계 — GFW 선박과 TAC/어선원부를 한글 직접비교로 매칭한다.

기존엔 GFW 자기신고 로마자명을 로마자로 변환한 TAC/어선원부 이름과
유사도(SequenceMatcher)로 비교했다. 사람이 GFW 영문명 4,662척 전체를
직접 한글로 재변환한 데이터(`gfw_korean_name_candidates.csv`)가 생기면서
로마자 대신 한글 원문끼리 직접 비교할 수 있게 됐고, 검증 결과(사람
스팟체크로 발견한 여러 버그 수정 포함) 로마자 유사도의 구조적 오탐
("-성호"류, 서로 다른 이름인데 로마자로 바꾸면 끝부분이 겹쳐서 점수가
높게 나옴)을 없앨 수 있다고 확인돼 이 방식으로 교체함(2026-08-18,
`data_new/matching_redesign_proposal/README.md`에 검증 과정 전체 기록).

매칭 규칙 4단계:
1. 한글 직접비교(exact match만, fuzzy 유사도는 안 씀)
2. 숫자 하드필터 — 자릿수 상관없이 GFW·후보 양쪽에 다 숫자가 보이는데
   값이 다르면 배제
3. "제N호" 정규화 — TAC/어선원부 원문은 "제707태근호"처럼 선단
   일련번호를 이름에 그대로 갖고 있는데 GFW 쪽 한글변환은 숫자를
   분리해서 뺐으므로, 비교 시 pool 쪽에서도 이 접두어를 한 번 더 뗀다
4. 카카오 지오코딩 거리 확인 — 이름이 동률(후보 2개+)이면 GFW
   조업위치와 후보 항구 거리로 판단. 후보 전원의 위치를 확인할 수
   있고 유일하게 ≤150km면 verified(근해어업은 등록항에서 150km까지도
   나가 조업). 후보 중 하나라도 위치를 확인 못 하면 "모른다"를
   "가깝다"로 오판하지 않도록 확정하지 않는다.

한글 후보가 없는 GFW 벡터(범용 영문명 등, ~17%)는 비교 대상 자체가
없어 바로 매칭실패로 낸다 — 로마자 유사도 fallback은 검증 결과
오탐이 많아 안 쓴다.

사용법:
    python match_fuzzy_name.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from geocode_kakao import geocode_kakao

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
TAC_PATH = PROCESSED / "tac_vessels_normalized.jsonl"
REGISTRY_PATH = PROCESSED / "vessel_registry_normalized.jsonl"
EVENTS_PATH = PROCESSED / "gfw_events_normalized.jsonl"
KOREAN_CSV_PATH = Path(__file__).resolve().parent.parent / "gfw_korean_name_candidates.csv"
OUT_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"

LOC_VERIFIED_KM = 150.0  # 근해어업은 등록항에서 150km까지도 나가 조업(사용자 확인, 2026-08-18)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _vessel_centroids(events: list) -> dict:
    """GFW vesselId별 조업이벤트 평균 위경도(활동해역 대표점)."""
    by_vessel = defaultdict(list)
    for e in events:
        if e["latitude"] is not None and e["longitude"] is not None:
            by_vessel[e["vesselId"]].append((e["latitude"], e["longitude"]))
    return {
        vid: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        for vid, pts in by_vessel.items()
    }


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _any_digit(s: str) -> str:
    """이름에 보이는 숫자 하나(자릿수 제한 없음). 불일치하면 다른 배라는
    신호는 자릿수와 무관하게 신뢰할 수 있다(사람 스팟체크로 검증)."""
    m = re.search(r"(\d+)", s)
    return m.group(1) if m else ""


def _strip_ho(name: str) -> str:
    name = (name or "").strip()
    return name[:-1] if name.endswith("호") else name


def _strip_je_number(base: str) -> str:
    """"제707태근" -> "태근". GFW 쪽 한글변환은 숫자를 통째로 분리해서
    뺐는데(letterPart_호제외 컬럼), TAC/어선원부 원문은 "제N호" 선단
    일련번호를 이름에 그대로 갖고 있어 exact match가 실패한다. 숫자
    일치는 별도 하드필터(_any_digit)로 이미 확인하니 여기서 또 떼도
    변별력 손실 없음 — 비교 전용 정규화일 뿐 표시용 원본 이름은
    그대로 둔다."""
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
        pool.append({"source": "tac", "name": t["nameTac"], "key": t["vesselNoTac"], "tonnage": t["tonnageGtTac"], "ports": t.get("portNamesTac") or []})
    for r in _load_jsonl(REGISTRY_PATH):
        pool.append({"source": "vessel_registry", "name": r["nameRegistry"], "key": r["vesselNoRegistry"], "tonnage": r["tonnageGtRegistry"], "ports": [r["portNameRegistry"]] if r.get("portNameRegistry") else []})
    for p in pool:
        p["base"] = _strip_ho(p["name"])
        p["compareBase"] = _strip_je_number(p["base"])
        # 숫자는 ASCII라 _normalize(한글 다 지움) 없이 base 원문에 바로 찾는다.
        # compareBase("제N호" 뗀 것)에서 찾으면 그 숫자 자체가 지워져 있어 안 됨.
        p["anyDigit"] = _any_digit(p["base"])
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


def _try_resolve_by_nearest(passing: list):
    """동률 후보 중 유일하게 최근접인 게 있으면 그 후보, 없으면 None.
    후보 중 하나라도 지오코딩 실패로 거리를 못 구했으면 확정하지 않는다
    — "거리 모름"을 "후보 아님"으로 취급하면 지오코딩 안 된 후보가
    조용히 비교에서 빠지고 지오코딩된 후보 1개만 "유일한 최근접"으로
    둔갑하는 문제가 있었다(사람 스팟체크로 발견)."""
    if any(p["distKm"] is None for p in passing):
        return None
    nearest = min(passing, key=lambda x: x["distKm"])
    others = [p["distKm"] for p in passing if p is not nearest]
    if others and min(others) - nearest["distKm"] <= 0.05:
        return None  # 동률(공동 최근접) — 못 정함
    if nearest["distKm"] <= LOC_VERIFIED_KM:
        return nearest
    return None


def run() -> None:
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)
    pool = _build_pool()
    centroids = _vessel_centroids(_load_jsonl(EVENTS_PATH))
    gfw_korean = _load_korean_candidates()

    counts = {"verified": 0, "held_multi": 0, "no_korean": 0, "unmatched": 0}
    results = []

    for gfw in gfw_vessels:
        vessel_id = gfw["vesselId"]
        name = gfw["selfReportedName"] or gfw["registryName"]
        result = {"gfwVesselId": vessel_id, "gfwName": name, "category": None, "candidate": None, "distKm": None}

        if not name:
            result["category"] = "unmatched"
            counts["unmatched"] += 1
            results.append(result)
            continue

        norm = _normalize(name)
        gfw_any_digit = _any_digit(norm)
        centroid = centroids.get(vessel_id)
        korean_cands = gfw_korean.get(vessel_id, [])

        if not korean_cands:
            result["category"] = "no_korean"
            counts["no_korean"] += 1
            results.append(result)
            continue

        passing = []
        for p in pool:
            if gfw_any_digit and p["anyDigit"] and gfw_any_digit != p["anyDigit"]:
                continue
            if p["base"] in korean_cands or p["compareBase"] in korean_cands:
                dist = _nearest_port_km(centroid, p["ports"])
                passing.append({"source": p["source"], "key": p["key"], "name": p["name"], "tonnage": p["tonnage"], "distKm": dist})

        if not passing:
            result["category"] = "unmatched"
            counts["unmatched"] += 1
            results.append(result)
            continue

        distinct = {(c["source"], c["key"]) for c in passing}
        winner = None
        if len(distinct) == 1:
            p = passing[0]
            if p["distKm"] is not None and p["distKm"] <= LOC_VERIFIED_KM:
                winner = p
        else:
            winner = _try_resolve_by_nearest(passing)

        if winner is not None:
            result["category"] = "verified"
            result["candidate"] = {"source": winner["source"], "key": winner["key"], "name": winner["name"], "tonnage": winner["tonnage"]}
            result["distKm"] = winner["distKm"]
            counts["verified"] += 1
        else:
            result["category"] = "held_multi"
            counts["held_multi"] += 1

        results.append(result)

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(results)
    print(f"GFW {total}척 한글 직접비교 매칭 결과:")
    for k, v in counts.items():
        print(f"  {k}: {v}척 ({v / total * 100:.1f}%)")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
