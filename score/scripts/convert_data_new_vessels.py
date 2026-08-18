"""Export the tracked vessel snapshots to the legacy gzip format."""

import gzip
import json
from pathlib import Path

from score.real_vessel_input import (
    DEFAULT_GFW_VESSELS_PATH,
    DEFAULT_MATCHES_PATH,
    convert_row,
    load_gear_types,
    load_real_vessel_records,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IN_PATH = DEFAULT_MATCHES_PATH
GEAR_PATH = DEFAULT_GFW_VESSELS_PATH
OUT_PATH = PROJECT_ROOT / "data_new" / "processed" / "vessels_for_score.jsonl.gz"


def main() -> None:
    records = load_real_vessel_records(IN_PATH, GEAR_PATH)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_PATH, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    total = len(records)
    with_tonnage = sum(record["tonnage"] is not None for record in records)
    with_gear = sum(bool(record["fishingType"]) for record in records)
    print(f"[output] {OUT_PATH}")
    print(
        f"  총 {total}척, 톤수 정보 {with_tonnage}척({100 * with_tonnage / total:.1f}%), "
        f"gear 정보 {with_gear}척({100 * with_gear / total:.1f}%)"
    )


if __name__ == "__main__":
    main()
