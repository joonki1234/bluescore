"""공용 B축 입력을 분석용 JSONL 파일로 선택적으로 내보낸다.

API와 production B축 계산은 `score.real_axis_b_input.build_axis_b_rows()`를
메모리에서 직접 호출하므로 `axis_b_input.jsonl`은 런타임 필수 파일이 아니다.

실행:
    python -m data_new.process.build_axis_b_input
"""

from __future__ import annotations

import json
from pathlib import Path

from score.real_axis_b_input import build_axis_b_rows


PROCESSED = Path(__file__).resolve().parent.parent / "processed"
OUT_PATH = PROCESSED / "axis_b_input.jsonl"


def run(output_path: Path = OUT_PATH) -> None:
    rows = build_axis_b_rows()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = len(rows)
    with_tonnage = sum(row["tonnageGt"] is not None for row in rows)
    with_gear = sum(row["gearType"] is not None for row in rows)
    print(f"이벤트 {total}건 -> {output_path}")
    print(f"tonnageGt 있음: {with_tonnage}/{total} ({with_tonnage / total * 100:.1f}%)")
    print(f"gearType 있음: {with_gear}/{total} ({with_gear / total * 100:.1f}%)")


if __name__ == "__main__":
    run()
