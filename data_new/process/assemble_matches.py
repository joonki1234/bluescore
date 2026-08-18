"""매칭 4단계 — 3단계(GFW<->TAC 한글 직접비교) 결과를 최종 판정으로 정리한다.

조인키 설계(PROCESS_LOG.md 12번) 4단계. 예전엔 1단계(TAC<->어선원부
어선번호 연결)·2단계(GFW<->어선원부 콜사인, 0.1%)도 같이 종합했으나,
어선원부를 후보풀에서 아예 빼고 GFW-TAC 매칭만 쓰기로 정리하면서
(match_fuzzy_name.py 참고, 2026-08-18) 이 두 단계도 함께 폐기했다.

3단계가 이미 verified/held_multi/no_korean/unmatched로 판정을 끝내놓기
때문에 여기서 별도 임계값 판단은 안 한다 — verified만 최종 매칭으로
쓰고 나머지(held_multi도 포함, "이름 같은 배가 여러 척이라 어느 쪽
톤수를 써야 할지 근거가 없음")는 전부 매칭실패로 취급한다.

사용법:
    python assemble_matches.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
FUZZY_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"
OUT_PATH = PROCESSED / "final_vessel_matches.jsonl"


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run() -> None:
    gfw_vessels = {v["vesselId"]: v for v in _load_jsonl(GFW_VESSELS_PATH)}
    fuzzy_results = {r["gfwVesselId"]: r for r in _load_jsonl(FUZZY_PATH)}

    counts = {"verified": 0, "unmatched": 0}
    results = []

    for vessel_id, gfw in gfw_vessels.items():
        result = {
            "gfwVesselId": vessel_id,
            "gfwName": gfw["selfReportedName"] or gfw["registryName"],
            "matchTier": None,
            "matchConfidence": None,
            "tac": None,
            "mof": None,
        }

        c3 = fuzzy_results.get(vessel_id)

        if c3 and c3["category"] == "verified":
            cand = c3["candidate"]
            result["matchTier"] = "verified"
            result["matchConfidence"] = "high"
            result["distKm"] = c3["distKm"]
            result["tac"] = {"vesselNoTac": cand["key"], "nameTac": cand["name"], "tonnageGtTac": cand["tonnage"]}
            counts["verified"] += 1
        else:
            result["matchTier"] = "unmatched"
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
