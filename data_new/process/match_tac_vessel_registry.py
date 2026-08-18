"""매칭 1단계 — TAC ↔ 어선원부, 어선번호(14자리) 정확일치.

조인키 설계(PROCESS_LOG.md 12번) 1단계 구현. 두 소스 다 정규화된 결과
(processed/*.jsonl)를 입력으로 쓴다 — raw는 안 건드림.

어선원부 쪽 어선번호 중복(345건, PROCESS_LOG.md 참고)은 무엇이 맞는지
지금 판단할 근거가 없어 **전부 후보로 보존**한다 — 하나를 임의로 골라
버리지 않는다(원칙1). 매칭 결과에 후보가 여러 개면 그대로 리스트로 남긴다.

사용법:
    python match_tac_vessel_registry.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
TAC_PATH = PROCESSED / "tac_vessels_normalized.jsonl"
REGISTRY_PATH = PROCESSED / "vessel_registry_normalized.jsonl"
OUT_PATH = PROCESSED / "tac_vessel_registry_matched.jsonl"


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run() -> None:
    tac_vessels = _load_jsonl(TAC_PATH)
    registry_rows = _load_jsonl(REGISTRY_PATH)

    registry_by_no = defaultdict(list)
    for row in registry_rows:
        registry_by_no[row["vesselNoRegistry"]].append(row)

    matched = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for tac in tac_vessels:
            candidates = registry_by_no.get(tac["vesselNoTac"], [])
            if not candidates:
                continue
            matched += 1
            out.write(
                json.dumps(
                    {"tac": tac, "registryCandidates": candidates, "candidateCount": len(candidates)},
                    ensure_ascii=False,
                )
                + "\n"
            )

    matched_registry_nos = {tac["vesselNoTac"] for tac in tac_vessels} & set(registry_by_no.keys())
    print(f"TAC {len(tac_vessels)}척 중 어선원부 매칭 {matched}척 ({matched / len(tac_vessels) * 100:.1f}%)")
    print(f"어선원부 {len(registry_by_no)}개 어선번호 중 {len(matched_registry_nos)}개가 TAC와 연결됨")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
