"""어항 정보 정규화 — 항구명 -> 위경도 조회표.

매칭 3단계(PROCESS_LOG.md 12번)의 "활동해역(항구 인근)" 신호에 쓴다.
TAC의 "양육 항구 명", 어선원부의 "항구명"을 이 표로 좌표를 찾아, GFW
이벤트 실제 위치와의 거리를 매칭 신호로 쓸 수 있게 한다.

⚠ 커버리지 한계: 이 데이터셋은 113개 항구뿐(전국 어항 전체가 아님,
아마 국가어항 위주로 보임 — 확인 안 됨) — TAC/어선원부의 항구명이 여기
없으면 해역신호는 그냥 계산 안 됨(원칙1: 없으면 없는 대로, 억지로 안 채움).

raw/는 읽기만 한다. processed/에 새로 쓰며 재실행 시 덮어써도 무방.

사용법:
    python normalize_ports.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "ports"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "ports_normalized.jsonl"


def run() -> None:
    files = list(RAW_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(f"어항정보 원본 파일이 없습니다: {RAW_DIR}")

    n = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for f in files:
            with f.open(encoding="cp949", newline="") as fp:
                for row in csv.DictReader(fp):
                    name = row["어항명"].strip()
                    lat, lon = row["위도"].strip(), row["경도"].strip()
                    if not name or not lat or not lon:
                        continue
                    out.write(
                        json.dumps(
                            {"portName": name, "latitude": float(lat), "longitude": float(lon)},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    n += 1

    print(f"어항 {n}개 정규화 완료 -> {OUT_PATH}")


if __name__ == "__main__":
    run()
