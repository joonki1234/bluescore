"""어선원부 정규화 — 원본(CP949 CSV)을 조인용으로 정리.

⚠ 이 소스 자체의 한계(PROCESS_LOG.md 9번): 전체 1,379행이 전부
현행여부='N'이고 등록처리일자가 2006년에 몰려있어 "현재 전체 등록대장"이
아니라 특정 처리배치로 보임 — 매칭에 쓸 수는 있지만 전체 모집단 커버용은
아니다. 매칭되면 보너스, 안 되면 원래 그런 소스임.

raw/는 읽기만 한다. processed/에 새로 쓰며 재실행 시 덮어써도 무방.

사용법:
    python normalize_vessel_registry.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "vessel_registry"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "vessel_registry_normalized.jsonl"


def run() -> None:
    files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() == ".csv"]
    if not files:
        raise SystemExit(f"어선원부 원본 파일이 없습니다: {RAW_DIR}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    seen_vessel_no = set()
    duplicates = []
    n = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for f in files:
            with f.open(encoding="cp949", newline="") as fp:
                for row in csv.DictReader(fp):
                    vessel_no = row["어선번호"].strip()
                    if not vessel_no:
                        continue
                    if vessel_no in seen_vessel_no:
                        duplicates.append(vessel_no)
                    seen_vessel_no.add(vessel_no)

                    rec = {
                        "vesselNoRegistry": vessel_no,
                        "nameRegistry": row["어선명"].strip(),
                        "callsignRegistry": row["호출부호명"].strip() or None,
                        "enginePowerRegistry": row["엔진마력"].strip() or None,
                        "tonnageGtRegistry": row["전체톤수"].strip() or None,
                        "currentFlag": row["현행여부"].strip(),
                        "portNameRegistry": row["항구명"].strip() or None,
                    }
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1

    print(f"어선원부 {n}행 정규화 완료")
    if duplicates:
        print(f"주의: 어선번호 중복 {len(duplicates)}건 - {duplicates[:10]}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
