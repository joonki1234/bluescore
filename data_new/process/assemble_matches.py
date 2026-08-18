"""매칭 4단계 — 1~3단계 결과를 종합해 GFW 선박별 최종 매칭 판정을 만든다.

조인키 설계(PROCESS_LOG.md 12번) 4단계. 우선순위: 2단계(콜사인 정확일치,
고신뢰) > 3단계(한글 직접비교로 verified된 것) > 매칭실패(억지로 안
붙임, score/·ui/adapter.py의 기존 matchingFailed 처리와 일관).

3단계(match_fuzzy_name.py)가 이미 verified/held_multi/no_korean/unmatched로
판정을 끝내놓기 때문에 여기서 별도 임계값 판단은 안 한다 — verified만
tier3로 승격하고 나머지(held_multi도 포함, "이름 같은 배가 여러 척이라
어느 쪽 톤수를 써야 할지 근거가 없음")는 전부 매칭실패로 취급한다.

매칭되면 TAC/어선원부 양쪽에 그 후보가 1단계(어선번호 정확일치)로도
연결돼 있는지 확인해 최대한 많은 원천의 톤수·마력을 같이 붙인다.

사용법:
    python assemble_matches.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
CALLSIGN_MATCH_PATH = PROCESSED / "gfw_vessel_registry_matched.jsonl"
FUZZY_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"
TAC_REGISTRY_LINK_PATH = PROCESSED / "tac_vessel_registry_matched.jsonl"
OUT_PATH = PROCESSED / "final_vessel_matches.jsonl"


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run() -> None:
    gfw_vessels = {v["vesselId"]: v for v in _load_jsonl(GFW_VESSELS_PATH)}
    callsign_matches = _load_jsonl(CALLSIGN_MATCH_PATH)
    fuzzy_results = {r["gfwVesselId"]: r for r in _load_jsonl(FUZZY_PATH)}

    # 1단계(TAC<->어선원부) 연결을 어선번호 기준으로 찾기 쉽게 색인
    tac_registry_by_registry_no = {}
    for link in _load_jsonl(TAC_REGISTRY_LINK_PATH):
        for cand in link["registryCandidates"]:
            tac_registry_by_registry_no[cand["vesselNoRegistry"]] = link["tac"]

    callsign_by_gfw_id = {c["gfwVesselId"]: c for c in callsign_matches}

    counts = {"tier2_callsign": 0, "tier3_korean_exact": 0, "unmatched": 0}
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
        c3 = fuzzy_results.get(vessel_id)

        if c2:
            result["matchTier"] = "tier2_callsign_exact"
            result["matchConfidence"] = "high"
            result["registryVesselNo"] = c2["registryVesselNo"]
            result["tac"] = tac_registry_by_registry_no.get(c2["registryVesselNo"])
            counts["tier2_callsign"] += 1
        elif c3 and c3["category"] == "verified":
            cand = c3["candidate"]
            result["matchTier"] = "tier3_korean_exact"
            result["matchConfidence"] = "high"
            result["distKm"] = c3["distKm"]
            if cand["source"] == "tac":
                result["tac"] = {"vesselNoTac": cand["key"], "nameTac": cand["name"], "tonnageGtTac": cand["tonnage"]}
            elif cand["source"] == "vessel_registry":
                result["registryVesselNo"] = cand["key"]
                result["tac"] = tac_registry_by_registry_no.get(cand["key"])
            counts["tier3_korean_exact"] += 1
        else:
            result["matchTier"] = "unmatched"
            result["matchConfidence"] = None
            if c3:
                result["unmatchedReason"] = c3["category"]  # held_multi/no_korean/unmatched
            counts["unmatched"] += 1

        results.append(result)

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(results)
    print(f"GFW 선박 {total}척 최종 판정:")
    for k, v in counts.items():
        print(f"  {k}: {v}척 ({v / total * 100:.1f}%)")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
