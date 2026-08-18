"""정적 파일 소스(TAC/어업별어선/어선원부) 검증 + 수신 메타데이터.

이 셋은 API가 막혀있어(TAC는 공공기관 전용 확인됨, PROCESS_LOG.md 7번) 사용자가
data.go.kr에서 내려받은 파일을 그대로 raw/에 둔 것 — 별도 수집 스크립트가
없어 검증게이트를 못 거쳤다(PROCESS_LOG.md 15번 review). 이 스크립트가
그 구멍을 메운다: 컬럼 수가 우리가 기록해둔 값과 같은지 확인하고, "우리가
언제 이 파일을 확인했는지"를 메타데이터로 남긴다(정부측 파일명 날짜와는
별개 — 원칙8 "요청 파라미터/수신 시각 별도 기록"의 연장).

사용법:
    python static_files_check.py
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"

# PROCESS_LOG.md 7·8·9번에 실측 기록해둔 컬럼 수 — 여기서 재확인한다.
SOURCES = [
    {
        "dir": RAW / "tac",
        "glob": "*.csv",
        "encoding": "cp949",
        "expected_columns": 28,
        "note": "TAC 할당 승인 정보",
    },
    {
        "dir": RAW / "fishery_stats",
        "glob": "*.csv",
        "encoding": "cp949",
        "expected_columns": 14,
        "note": "어업별어선(MR) 업종별 집계",
    },
    {
        "dir": RAW / "vessel_registry",
        "glob": "*.CSV",
        "encoding": "cp949",
        "expected_columns": 37,
        "note": "어선원부",
    },
]


def check() -> None:
    problems = []
    for src in SOURCES:
        files = list(src["dir"].glob(src["glob"]))
        if not files:
            problems.append(f"파일 없음: {src['dir']}")
            continue
        for f in files:
            with f.open(encoding=src["encoding"], newline="") as fp:
                header = next(csv.reader(fp))
            n = len(header)
            ok = n == src["expected_columns"]
            print(f"{f.name}: 컬럼 {n}개 (기대 {src['expected_columns']}개) -> {'OK' if ok else '불일치'}")
            if not ok:
                problems.append(f"컬럼 수 불일치: {f} ({n} != {src['expected_columns']})")

            meta_path = f.with_suffix(f.suffix + ".received_meta.json")
            if not meta_path.exists():
                meta_path.write_text(
                    json.dumps(
                        {
                            "source_note": src["note"],
                            "original_filename": f.name,
                            "encoding_confirmed": src["encoding"],
                            "column_count_confirmed": n,
                            "received_by_us_at": datetime.now(timezone.utc).isoformat(),
                            "acquisition_method": "사용자가 data.go.kr에서 수동 다운로드 후 전달 (API 미제공/제한)",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"  -> {meta_path.name} 생성")

    if problems:
        print("\n검증 게이트 위반:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\n검증 게이트 통과.")


if __name__ == "__main__":
    check()
