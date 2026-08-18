"""TAC 할당 승인 정보 정규화 — 원본(CP949 CSV, 배분 건별)을 어선번호
단위로 집계한다. 한 어선이 여러 어종에 할당받으면 TAC 원본엔 여러 행으로
나오므로, 매칭(조인)에 쓰기 좋게 어선번호 단위로 묶는다.

raw/는 읽기만 한다. processed/에 새로 쓰며 재실행 시 덮어써도 무방(원본에서
결정론적으로 재생성 가능).

사용법:
    python normalize_tac.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "tac"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "tac_vessels_normalized.jsonl"


def run() -> None:
    files = list(RAW_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(f"TAC 원본 파일이 없습니다: {RAW_DIR}")

    by_vessel_no = {}
    inconsistent = set()
    n_rows = 0
    for f in files:
        with f.open(encoding="cp949", newline="") as fp:
            for row in csv.DictReader(fp):
                n_rows += 1
                vessel_no = row["어선 번호"].strip()
                if not vessel_no:
                    continue
                tonnage = row["선박 톤수"].strip()
                power = row["선박 마력"].strip()

                if vessel_no not in by_vessel_no:
                    by_vessel_no[vessel_no] = {
                        "vesselNoTac": vessel_no,
                        "nameTac": row["어선 명"].strip(),
                        "tonnageGtTac": tonnage,
                        "enginePowerTac": power,
                        "gearTypeNamesTac": set(),
                        "licenseNumbersTac": set(),
                        "portNamesTac": set(),
                    }
                elif by_vessel_no[vessel_no]["tonnageGtTac"] != tonnage or by_vessel_no[vessel_no]["enginePowerTac"] != power:
                    inconsistent.add(vessel_no)

                by_vessel_no[vessel_no]["gearTypeNamesTac"].add(row["할당 어업 종류 명"].strip())
                by_vessel_no[vessel_no]["licenseNumbersTac"].add(row["어업 허가 번호"].strip())
                port = row["양육 항구 명"].strip()
                if port:
                    by_vessel_no[vessel_no]["portNamesTac"].add(port)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for rec in by_vessel_no.values():
            rec["gearTypeNamesTac"] = sorted(rec["gearTypeNamesTac"])
            rec["licenseNumbersTac"] = sorted(rec["licenseNumbersTac"])
            rec["portNamesTac"] = sorted(rec["portNamesTac"])
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"TAC 원본 {n_rows}행 -> 어선 {len(by_vessel_no)}척으로 집계")
    if inconsistent:
        print(f"주의: 같은 어선번호인데 톤수/마력이 행마다 다른 경우 {len(inconsistent)}건 - {sorted(inconsistent)[:10]}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
