"""매칭 4단계 — 1~3단계 결과를 종합해 GFW 선박별 최종 매칭 판정을 만든다.

조인키 설계(PROCESS_LOG.md 12번) 4단계. 우선순위: 2단계(콜사인 정확일치,
고신뢰) > 3단계(이름 fuzzy, 임계값 이상이면 중신뢰) > 매칭실패(억지로
안 붙임, score/·ui/adapter.py의 기존 matchingFailed 처리와 일관).

매칭되면 TAC/어선원부 양쪽에 그 후보가 1단계(어선번호 정확일치)로도
연결돼 있는지 확인해 최대한 많은 원천의 톤수·마력을 같이 붙인다.

⚠ `FUZZY_NAME_THRESHOLD`는 잠정값이다 — GFW 10척 표본에서 강한 매칭이
0.8 이상, 약한/애매한 매칭이 0.72 이하로 갈리는 걸 보고 그 사이값을
잡은 것뿐이며, 본수집 후 훨씬 큰 표본의 점수 분포로 재조정해야 한다.

사용법:
    python assemble_matches.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
CALLSIGN_MATCH_PATH = PROCESSED / "gfw_vessel_registry_matched.jsonl"
FUZZY_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"
TAC_REGISTRY_LINK_PATH = PROCESSED / "tac_vessel_registry_matched.jsonl"
OUT_PATH = PROCESSED / "final_vessel_matches.jsonl"

# 잠정값 — 위 docstring 참고, 본수집 후 재조정 필요.
FUZZY_NAME_THRESHOLD = 0.8


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _total_score(candidate: dict) -> float:
    return candidate["nameScore"] + candidate["tonnageBonus"] + candidate.get("locationBonus", 0.0)


# 2026-08-18(김준기, 태윤님 확인 필요): PROCESS_LOG.md 49번 검증("번호 일치 시
# 정밀도 95~100%, 불일치 시 0%")이 CLAUDE.md 10번의 근거로 이미 인용됐는데
# _total_score에는 실제로 반영돼 있지 않았다. 이미 커밋된 final_vessel_matches.jsonl
# (2,878 tier3_fuzzy_name 중 이름 텍스트 확인 가능한 2,311척)로 시뮬레이션한
# 결과, "26 NAM GANG HO" ↔ "203남광호"처럼 fuzzyScore 0.8~0.92로 높게 나왔는데도
# 선단 번호가 명백히 다른 오매칭 77건(3.3%)을 확인했다. 원본 raw 입력
# (fuzzy_name_candidates.jsonl 등)이 로컬에 없어 이 필터를 넣은 채로 파이프라인을
# 처음부터 재실행해 전체 재검증은 못 했다 — 태윤님이 다음에 재실행할 때 카운트가
# 이 설명과 크게 어긋나면 알려주시길.
def _digit_prefix(name: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", (name or "").upper())
    m = re.match(r"^\D*?(\d{2,4})", normalized)
    return m.group(1) if m else ""


def _numeric_mismatch(gfw_name: str, candidate_name: str) -> bool:
    """둘 다 숫자(선단 번호 등)를 갖고 있는데 서로 다르면 오매칭으로 본다.
    둘 중 하나라도 숫자가 없으면(판정 근거 없음) 통과시킨다 — 과잉 거부 방지."""
    gfw_digit = _digit_prefix(gfw_name)
    candidate_digit = _digit_prefix(candidate_name)
    return bool(gfw_digit and candidate_digit and gfw_digit != candidate_digit)


def run() -> None:
    gfw_vessels = {v["vesselId"]: v for v in _load_jsonl(GFW_VESSELS_PATH)}
    callsign_matches = _load_jsonl(CALLSIGN_MATCH_PATH)
    fuzzy_candidates = {r["gfwVesselId"]: r for r in _load_jsonl(FUZZY_PATH)}

    # 1단계(TAC<->어선원부) 연결을 어선번호 기준으로 찾기 쉽게 색인
    tac_registry_by_registry_no = {}
    for link in _load_jsonl(TAC_REGISTRY_LINK_PATH):
        for cand in link["registryCandidates"]:
            tac_registry_by_registry_no[cand["vesselNoRegistry"]] = link["tac"]

    callsign_by_gfw_id = {c["gfwVesselId"]: c for c in callsign_matches}

    counts = {"tier2_callsign": 0, "tier3_fuzzy": 0, "unmatched": 0}
    results = []

    for vessel_id, gfw in gfw_vessels.items():
        result = {
            "gfwVesselId": vessel_id,
            "gfwName": gfw["selfReportedName"] or gfw["registryName"],
            "matchTier": None,
            "matchConfidence": None,
            "registryVesselNo": None,
            "tac": None,
            "mof": None,
        }

        c2 = callsign_by_gfw_id.get(vessel_id)
        c3 = fuzzy_candidates.get(vessel_id)
        top3 = c3["candidates"][0] if c3 and c3["candidates"] else None

        numeric_mismatch = bool(top3) and _numeric_mismatch(result["gfwName"], top3["name"])

        if c2:
            result["matchTier"] = "tier2_callsign_exact"
            result["matchConfidence"] = "high"
            result["registryVesselNo"] = c2["registryVesselNo"]
            result["tac"] = tac_registry_by_registry_no.get(c2["registryVesselNo"])
            counts["tier2_callsign"] += 1
        elif top3 and _total_score(top3) >= FUZZY_NAME_THRESHOLD and not numeric_mismatch:
            result["matchTier"] = "tier3_fuzzy_name"
            result["matchConfidence"] = "medium"
            result["fuzzyScore"] = round(_total_score(top3), 3)
            result["fuzzySource"] = top3["source"]
            if top3["source"] == "tac":
                result["tac"] = {"vesselNoTac": top3["key"], "nameTac": top3["name"], "tonnageGtTac": top3["tonnage"]}
            elif top3["source"] == "vessel_registry":
                result["registryVesselNo"] = top3["key"]
                result["tac"] = tac_registry_by_registry_no.get(top3["key"])
            elif top3["source"] == "mof":
                # MOF는 TAC/어선원부와 다른 별도 출처 — 어선번호 체계가 아니라
                # MOF 자체 식별자(선박번호/콜사인)라 registryVesselNo에 안 넣는다.
                result["mof"] = {"mofKey": top3["key"], "nameMof": top3["name"], "tonnageGtMof": top3["tonnage"]}
            counts["tier3_fuzzy"] += 1
        else:
            result["matchTier"] = "unmatched"
            result["matchConfidence"] = None
            if top3:
                result["bestRejectedCandidate"] = {"name": top3["name"], "score": round(_total_score(top3), 3)}
                if numeric_mismatch:
                    result["bestRejectedCandidate"]["rejectedReason"] = "numericPrefixMismatch"
            counts["unmatched"] += 1

        results.append(result)

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(results)
    print(f"GFW 선박 {total}척 최종 판정 (임계값={FUZZY_NAME_THRESHOLD}, 잠정값):")
    for k, v in counts.items():
        print(f"  {k}: {v}척 ({v / total * 100:.1f}%)")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
