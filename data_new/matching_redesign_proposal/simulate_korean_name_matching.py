"""한글 직접비교 매칭 재설계 시뮬레이션 (이 폴더의 README.md 근거).

로마자 유사도 대신, 사람이 GFW 영문명을 직접 한글로 변환한 후보
(`gfw_korean_name_candidates.csv`)를 TAC/어선원부 원문 한글과 직접
비교하면 정밀도가 얼마나 오르는지(대신 커버리지를 얼마나 잃는지)
확인한다. **아직 실제 파이프라인(data_new/process/match_fuzzy_name.py,
assemble_matches.py)에 반영 안 됨** — 팀 결정(README.md 참고) 전까지는
이 스크립트가 유일한 산출 경로다.

핵심 설계:
- 이름비교는 exact match만 쓴다(fuzzy 0.85+는 검증 사례 19/19가
  "제N호"류 내부번호 소실 버그로 오매칭이라 폐기 — 제안서 발견 3 참고)
- 숫자접두어(2~4자리) 하드필터는 기존 그대로(사람 라벨링 검증됨)
- 동률 후보는 최근접 항구 거리로 소프트 타이브레이크:
  ≤50km면 verified, 50~150km면 held(낮은신뢰도), 그 외/위치정보
  없으면 held_multi(모호, 계산 불가)
- (source,key) 동일한 후보는 데이터중복으로 보고 dedup
- pool 쪽 이름에서 "제<숫자>" 접두어를 비교 전용으로 한 번 더 뗀다
  (`_strip_je_number`) — GFW 한글변환은 숫자를 통째로 분리해서 뺐는데
  TAC/어선원부 원문은 "제707태근호"처럼 번호를 이름에 그대로 갖고 있어
  안 떼면 exact match가 실패했음(교차분석으로 935건 중 124건 확인,
  README.md 발견 4)
- 후보 2개+(동률)인 벡터는 독립적으로 안 풀고 전부 모아서 한번에 푼다
  (README.md 발견 5): (a) gearType 대충매핑(9개 키워드)으로 먼저 후보를
  거르고, (b) 그래도 안 좁혀지면 같은 후보를 다투는 GFW벡터들끼리
  연결요소를 묶어 헝가리안 알고리즘(`scipy.optimize.linear_sum_assignment`)
  으로 전역 최적배정 — "이 후보는 다른 GFW벡터가 이미 더 그럴듯하게
  차지했다"를 고려 못 하던 기존의 벡터별 독립판단 한계를 보완한다.
  비용은 거리(km), 숫자힌트(자릿수 제한 없이 아무 숫자나 일치하면
  보너스) — 실측으로 봤을 때 이걸로도 완전히는 안 풀림(대충매핑
  176척, 전역할당 178척 정도, 상당수 중복) — 보조 신호일 뿐 결정적이진
  않다.

한 척씩 old(현재 라이브)/new(이 시뮬레이션) 판정을 나란히 놓은 파일도
같이 낸다(`output/korean_matching_comparison.jsonl`) — 팀원이 숫자만
보고 판단하지 않고, 실제 사례를 직접 열어 필터링·스팟체크해보고
판단할 수 있게 하기 위함.

사용법:
    python simulate_korean_name_matching.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "process"))

from geocode_kr import geocode as geocode_sigungu  # noqa: E402
from match_fuzzy_name import (  # noqa: E402
    EVENTS_PATH,
    GFW_VESSELS_PATH,
    PORTS_PATH,
    REGISTRY_PATH,
    TAC_PATH,
    _haversine_km,
    _load_jsonl,
    _normalize,
    _romanize,
    _similarity,
    _vessel_centroids,
)


def _digit_prefix(normalized: str) -> str:
    """정규화된 문자열에서 선두 2~4자리 숫자열을 뽑는다(사람 라벨링 49번
    검증 범위). match_fuzzy_name.py의 동명 함수는 아직 이 세션의 미커밋
    수정에만 있어서(라이브 파이프라인엔 없음) — 이 제안이 라이브 코드의
    미커밋 상태에 의존하지 않도록 여기 그대로 복제해둔다."""
    m = re.match(r"^\D*?(\d{2,4})", normalized)
    return m.group(1) if m else ""


def _any_digit(normalized: str) -> str:
    """자릿수 제한 없이 아무 숫자열이나 하나(하드필터 아니라 헝가리안
    배정의 소프트 힌트 전용 — 1자리도 씀, 검증범위 밖이라 결정적으론
    안 쓰고 비용을 살짝 낮추는 정도로만)."""
    m = re.search(r"(\d+)", normalized)
    return m.group(1) if m else ""


# TAC 어업종류(한글) -> GFW gear 카테고리 대충 매핑(9개 키워드, 정식 검증
# 안 됨 — README.md 발견 5 참고). 어선원부는 gearType 필드 자체가 없어서
# 이 매핑은 TAC 후보에만 적용된다.
GEAR_KEYWORD_MAP = [
    ("저인망", "TRAWLERS"), ("트롤", "TRAWLERS"),
    ("자망", "SET_GILLNETS"),
    ("연승", "SET_LONGLINES"),
    ("통발", "POTS_AND_TRAPS"),
    ("형망", "DREDGE_FISHING"),
    ("선망", "PURSE_SEINES"),
    ("권현망", "SEINERS"),
    ("채낚기", "POLE_AND_LINE"),
]
GEAR_GENERIC_LABELS = {"FISHING", "NA", "INCONCLUSIVE"}


def _guess_gfw_gear(tac_gears: list) -> set:
    out = set()
    for g in tac_gears or []:
        for kw, cat in GEAR_KEYWORD_MAP:
            if kw in g:
                out.add(cat)
    return out


KOREAN_CSV_PATH = Path(__file__).resolve().parent / "gfw_korean_name_candidates.csv"
OLD_MATCHES_PATH = Path(__file__).resolve().parent.parent / "processed" / "final_vessel_matches.jsonl"
COMPARISON_OUT_PATH = Path(__file__).resolve().parent / "output" / "korean_matching_comparison.jsonl"
ROMAN_FALLBACK_THRESHOLD = 0.85  # 한글후보 자체가 없는 벡터에만 씀
LOC_VERIFIED_KM = 50.0
LOC_HELD_CAP_KM = 150.0
ASSIGNMENT_SENTINEL = 1e6  # 헝가리안 비용행렬에서 "후보 아님"을 나타내는 값
ASSIGNMENT_NO_LOC_COST = 300.0  # 위치정보 없는 쌍의 기본비용(멀다고 간주)
ASSIGNMENT_DIGIT_BONUS = 60.0  # 숫자힌트 일치시 비용 할인(소프트, 확정 아님)

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
    숫자일치는 이미 별도 하드필터(_digit_prefix)로 확인하니, 여기서
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
        pool.append({"source": "tac", "name": t["nameTac"], "key": t["vesselNoTac"], "ports": t.get("portNamesTac") or [], "gear": _guess_gfw_gear(t.get("gearTypeNamesTac"))})
    for r in _load_jsonl(REGISTRY_PATH):
        # 어선원부는 gearType 필드 자체가 없음(빈 집합 = "모른다", 필터에서 안 걸림)
        pool.append({"source": "vessel_registry", "name": r["nameRegistry"], "key": r["vesselNoRegistry"], "ports": [r["portNameRegistry"]] if r.get("portNameRegistry") else [], "gear": set()})
    for p in pool:
        p["base"] = _strip_ho(p["name"])
        p["compareBase"] = _strip_je_number(p["base"])
        p["digitPrefix"] = _digit_prefix(_normalize(p["name"]))
        p["anyDigit"] = _any_digit(_normalize(p["name"]))
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


def run() -> list:
    """GFW 선박 1척당 1행. `category`가 이번 시뮬레이션 판정,
    `old`가 현재 라이브 판정(비교용)."""
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)
    pool = _build_pool()
    ports = {p["portName"]: (p["latitude"], p["longitude"]) for p in _load_jsonl(PORTS_PATH)}
    centroids = _vessel_centroids(_load_jsonl(EVENTS_PATH))
    gfw_korean = _load_korean_candidates()
    old_matches = _load_old_matches()

    rows = []
    pending = []  # 후보 2개+인 벡터들 — 나중에 _resolve_pending()에서 한번에 처리

    for gfw in gfw_vessels:
        vessel_id = gfw["vesselId"]
        name = gfw["selfReportedName"] or gfw["registryName"]
        old = old_matches.get(vessel_id)
        row = {"gfwVesselId": vessel_id, "gfwName": name, "old": old}

        if not name:
            rows.append({**row, "category": "no_name", "matchedName": None, "distKm": None, "candidateCount": 0})
            continue

        norm = _normalize(name)
        digit = _digit_prefix(norm)
        centroid = centroids.get(vessel_id)
        korean_cands = gfw_korean.get(vessel_id, [])

        if not korean_cands:
            # 한글변환 후보가 없는 벡터(범용영문명 등) — 로마자 fallback만 시도.
            best = None
            best_name = None
            for p in pool:
                if digit and p["digitPrefix"] and digit != p["digitPrefix"]:
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
            if digit and p["digitPrefix"] and digit != p["digitPrefix"]:
                continue
            if p["base"] in korean_cands or p["compareBase"] in korean_cands:  # exact만(fuzzy는 폐기, 발견 3) + "제N호" 정규화(발견 4)
                dist = _nearest_port_km(ports, centroid, p["ports"])
                passing.append({"source": p["source"], "key": p["key"], "name": p["name"], "distKm": dist, "gear": p["gear"], "anyDigit": p["anyDigit"]})

        if not passing:
            rows.append({**row, "category": "unmatched", "matchedName": None, "distKm": None, "candidateCount": 0, "koreanCandidates": korean_cands})
            continue

        distinct_vessels = {(c["source"], c["key"]) for c in passing}
        if len(distinct_vessels) == 1:
            rows.append({**row, "category": "verified", "matchedName": passing[0]["name"], "distKm": passing[0]["distKm"], "candidateCount": len(distinct_vessels)})
            continue

        # 벡터 단독 최근접 타이브레이크부터 먼저 시도 — 이미 이걸로 풀리는
        # 건(가까운 후보가 유일함) 그대로 확정한다. gearType/헝가리안은
        # 이 단독판단으로도 진짜 안 풀리는 것에만 쓴다 — 안 그러면
        # 전역최적화가 이미 명확했던 개별 매칭까지 흔들어버림(실측으로 확인,
        # 계산가능 32.2%->25.5%로 되레 후퇴했었음).
        resolved = _try_resolve_by_nearest(passing)
        if resolved is not None:
            category, matched_name, dist = resolved
            rows.append({**row, "category": category, "matchedName": matched_name, "distKm": dist, "candidateCount": len(distinct_vessels)})
            continue

        # 그래도 안 풀림 — 전부 모아서 나중에 한번에 푼다(gearType 필터
        # -> 헝가리안 전역할당, README.md 발견 5).
        gfw_gear = {g for g in (gfw.get("combinedGearTypes") or []) if g not in GEAR_GENERIC_LABELS}
        gfw_any_digit = _any_digit(norm)
        pending.append({
            "row": row, "vesselId": vessel_id, "passing": passing,
            "gfwGear": gfw_gear, "gfwAnyDigit": gfw_any_digit, "centroid": centroid,
        })

    _resolve_pending(pending, ports, rows)
    return rows


def _resolve_pending(pending: list, ports: dict, rows: list) -> None:
    """동률 후보 벡터들을 한번에 처리. 1) gearType으로 먼저 거르고,
    2) 그래도 남으면 같은 후보를 다투는 벡터들끼리 묶어 헝가리안
    전역할당(거리+숫자힌트 비용)으로 풀어본다."""
    # 1) gearType 필터
    for item in pending:
        orig_passing = item["passing"]
        gfw_gear = item["gfwGear"]
        if gfw_gear:
            filtered = [
                p for p in orig_passing
                if not (p["gear"] and not (p["gear"] & gfw_gear))
            ]
            # 전부 걸러지면(=매핑이 의심스러운 경우) gearType 자체를 무시하고 원래대로.
            item["passing"] = filtered if filtered else orig_passing

    still_ambiguous = []
    for item in pending:
        distinct = {(p["source"], p["key"]) for p in item["passing"]}
        if len(distinct) == 1:
            p = item["passing"][0]
            rows.append({**item["row"], "category": "verified", "matchedName": p["name"], "distKm": p["distKm"], "candidateCount": 1, "resolvedBy": "gearType"})
        else:
            still_ambiguous.append(item)

    # 2) 남은 것들 — 같은 (source,key) 후보를 다투는 벡터끼리 연결요소로 묶기
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for item in still_ambiguous:
        gnode = ("G", item["vesselId"])
        parent.setdefault(gnode, gnode)
        for p in item["passing"]:
            cnode = ("C", p["source"], p["key"])
            parent.setdefault(cnode, cnode)
            union(gnode, cnode)

    groups = defaultdict(lambda: {"items": [], "cands": {}})
    for item in still_ambiguous:
        root = find(("G", item["vesselId"]))
        groups[root]["items"].append(item)
        for p in item["passing"]:
            groups[root]["cands"][(p["source"], p["key"])] = p

    for group in groups.values():
        items = group["items"]
        cand_keys = list(group["cands"].keys())
        if len(items) == 1:
            # 경쟁자 없음 — 헝가리안 의미 없음. gearType으로 후보가 좁혀졌을
            # 수 있으니 최근접 재시도 후에도 안 풀리면 held_multi로 확정.
            item = items[0]
            resolved = _try_resolve_by_nearest(item["passing"])
            if resolved is not None:
                category, matched_name, dist = resolved
                distinct = {(p["source"], p["key"]) for p in item["passing"]}
                rows.append({**item["row"], "category": category, "matchedName": matched_name, "distKm": dist, "candidateCount": len(distinct), "resolvedBy": "gearType"})
            else:
                _finalize_by_nearest(item, rows)
            continue

        n, m = len(items), len(cand_keys)
        cost = np.full((n, m), ASSIGNMENT_SENTINEL)
        dist_matrix = np.full((n, m), None, dtype=object)
        real_cands_per_item = [{(p["source"], p["key"]) for p in it["passing"]} for it in items]

        for i, item in enumerate(items):
            for j, key in enumerate(cand_keys):
                if key not in real_cands_per_item[i]:
                    continue
                p = group["cands"][key]
                d = p["distKm"]
                base_cost = d if d is not None else ASSIGNMENT_NO_LOC_COST
                bonus = ASSIGNMENT_DIGIT_BONUS if (item["gfwAnyDigit"] and p["anyDigit"] and item["gfwAnyDigit"] == p["anyDigit"]) else 0.0
                cost[i, j] = base_cost - bonus
                dist_matrix[i, j] = d

        row_ind, col_ind = linear_sum_assignment(cost)
        assigned = {}
        for i, j in zip(row_ind, col_ind):
            if cost[i, j] < ASSIGNMENT_SENTINEL:
                assigned[i] = (cand_keys[j], dist_matrix[i, j], group["cands"][cand_keys[j]]["name"])

        for i, item in enumerate(items):
            if i not in assigned:
                _finalize_by_nearest(item, rows)
                continue
            _, d, matched_name = assigned[i]
            if d is not None and d <= LOC_VERIFIED_KM:
                rows.append({**item["row"], "category": "verified", "matchedName": matched_name, "distKm": d, "candidateCount": len(items), "resolvedBy": "assignment"})
            elif d is not None and d <= LOC_HELD_CAP_KM:
                rows.append({**item["row"], "category": "held_위치애매", "matchedName": matched_name, "distKm": d, "candidateCount": len(items), "resolvedBy": "assignment"})
            else:
                rows.append({**item["row"], "category": "held_multi_동명이선", "matchedName": None, "distKm": None, "candidateCount": len(items), "candidateNames": [p["name"] for p in item["passing"]]})


def _try_resolve_by_nearest(passing: list) -> tuple | None:
    """동률 후보 중 유일하게 최근접인 게 있으면 (category, matchedName, distKm),
    없으면 None. 벡터 단독 판단 — 다른 벡터가 그 후보를 원하는지는 안 봄."""
    with_dist = [p for p in passing if p["distKm"] is not None]
    if not with_dist:
        return None
    with_dist.sort(key=lambda x: x["distKm"])
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


def _finalize_by_nearest(item: dict, rows: list) -> None:
    """경쟁자 없는(전역할당 대상 아닌, 그리고 이미 단독판단으로도 안 풀린)
    벡터의 최종 처리 — 여기 오는 건 정의상 _try_resolve_by_nearest가 이미
    실패한 것들이라 held_multi로 확정."""
    passing = item["passing"]
    distinct = {(p["source"], p["key"]) for p in passing}
    rows.append({**item["row"], "category": "held_multi_동명이선", "matchedName": None, "distKm": None, "candidateCount": len(distinct), "candidateNames": [p["name"] for p in passing]})


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
