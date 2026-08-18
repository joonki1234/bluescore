"""매칭 3단계 — GFW 선박과 TAC를 한글 직접비교로 매칭한다.

GFW 자기신고 영문명을 사람이 미리 한글로 변환해둔 후보
(`gfw_korean_name_candidates.csv`)와 TAC 한글 원문을 대조한다. 로마자
유사도 대신 한글 원문끼리 비교하는 이유: 로마자로 바꾸면 서로 다른
실제 이름인데 끝부분이 겹쳐 점수가 높게 나오는 구조적 오탐이 있다
(예: EUNSEONGHO가 은성호 대신 금성호로 매칭되는 식). 검증 과정 전체
기록은 `data_new/matching_redesign_proposal/README.md`.

어선원부·MOF는 후보풀에 안 쓴다 — 어선원부는 전체 등록대장이 아니라
2006년 처리배치 일부(1,379행, 전부 현행여부='N')라 TAC 대비 신뢰도가
낮고, MOF는 이름검색이 어선보다 상선 위주로 편향돼 있다.

매칭 규칙 5단계:
1. 한글 직접비교(exact match만, fuzzy 유사도는 안 씀)
2. 숫자 하드필터 — 자릿수 상관없이 GFW·후보 양쪽에 다 숫자가 보이는데
   값이 다르면 배제
3. "제N호" 정규화 — TAC 원문은 "제707태근호"처럼 선단
   일련번호를 이름에 그대로 갖고 있는데 GFW 쪽 한글변환은 숫자를
   분리해서 뺐으므로, 비교 시 pool 쪽에서도 이 접두어를 한 번 더 뗀다
4. 카카오 지오코딩 거리 확인 — 후보가 몇 개든(1개든 2개+든) GFW
   조업위치와 후보 항구 거리를 반드시 확인해야 한다. 확인할 수 있고
   ≤150km면 verified. 거리를 확인 못 하면(지오코딩 실패) 후보가
   이름만으로 유일해도 "모른다"를 "가깝다"로 오판하지 않도록
   확정하지 않는다.
5. TAC 쪽 유일성 강제 — 1~4단계는 GFW 선박마다 독립적으로 판정하기
   때문에, "한성호"처럼 흔하고 숫자 없는 이름은 서로 다른 GFW 선박
   여러 척이 TAC의 같은 배(등록번호 1개) 하나를 동시에 주장할 수
   있다. 4단계까지 끝낸 뒤 TAC 등록번호별로 다시 묶어, 같은 TAC 배를
   여러 GFW 선박이 주장하면 조업위치가 가장 가까운 하나만 verified로
   남기고 나머지는 held_multi로 되돌린다(동률이면 전부 되돌림 — 4단계와
   동일한 원칙).

GFW `registryInfo`(공식 등록정보)가 있는 선박은 대부분 원양 대형선단
소속이라 근해/연안 모집단과 성격이 달라 후보풀 비교 전에 제외한다.
한글 후보가 없는 GFW 벡터(범용 영문명 등)도 비교 대상 자체가 없어
바로 매칭실패로 낸다.

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
EVENTS_PATH = PROCESSED / "gfw_events_normalized.jsonl"
KOREAN_CSV_PATH = Path(__file__).resolve().parent.parent / "gfw_korean_name_candidates.csv"
OUT_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"

LOC_VERIFIED_KM = 150.0  # 근해어업 조업범위 감안한 보수적 값 — 법·데이터 근거 없음, matching_redesign_proposal/README.md "왜 150km인가" 참고


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
    신호는 자릿수와 무관하게 신뢰할 수 있다."""
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
    pool = [{"source": "tac", "name": t["nameTac"], "key": t["vesselNoTac"], "tonnage": t["tonnageGtTac"], "ports": t.get("portNamesTac") or []} for t in _load_jsonl(TAC_PATH)]
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
    둔갑해버린다."""
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

        if gfw.get("hasRegistryMatch"):
            # 공식 registryInfo가 있는 선박은 대부분 원양 대형선단 소속이라
            # 근해/연안 모집단과 성격이 다르다 — 후보풀 비교 없이 바로 제외.
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

    # 5단계: TAC 쪽 유일성 강제 — 같은 TAC 배를 여러 GFW 선박이 동시에
    # verified로 주장하면 가장 가까운 하나만 남긴다.
    by_tac_key = defaultdict(list)
    for r in results:
        if r["category"] == "verified":
            by_tac_key[(r["candidate"]["source"], r["candidate"]["key"])].append(r)

    for claimants in by_tac_key.values():
        if len(claimants) == 1:
            continue
        claimants.sort(key=lambda r: r["distKm"])
        nearest, runner_up = claimants[0], claimants[1]
        tied = runner_up["distKm"] - nearest["distKm"] <= 0.05
        losers = claimants if tied else claimants[1:]
        for r in losers:
            r["category"] = "held_multi"
            r["candidate"] = None
            r["distKm"] = None
            counts["verified"] -= 1
            counts["held_multi"] += 1

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
