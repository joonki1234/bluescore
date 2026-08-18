"""
담당: 김준기, 오동규

`data_new/processed/final_vessel_matches.jsonl`(김태윤 작업물)을
`services/real_scoring.py`가 기대하는 평판화된 선박 레코드(vesselId/tonnage/
fishingType)로 변환한다.

톤수 우선순위: tac.tonnageGtTac > mof.tonnageGtMof (둘 다 문자열이라 float로
변환, 파싱 실패/누락은 None).

fishingType은 지금 빈 리스트로 둔다 — data_new의 공개분(`final_vessel_matches.jsonl`)
에는 GFW 자체 gear 정보가 없다(원본 raw/gfw/vessels, 그 정규화 결과인
gfw_vessels_normalized.jsonl 둘 다 이번 공개에는 없음). fishingType이 없어도
score/peer_grouping.gear_type_key(None)이 None을 반환해 톤수·해역·계절만으로
그룹핑되므로 실행 자체는 막히지 않는다 — 나중에 GFW 자체 gear 정보가 추가
공개되면 이 스크립트를 그만큼만 보강하면 된다.

이벤트 파일은 별도 변환이 필요 없다 — `data_new/processed/events_with_weather.jsonl.gz`가
`eventId/vesselId/start/latitude/longitude` 등 score/axis_a_pressure.py가
요구하는 필드를 이미 그대로 갖고 있다.

출력: data_new/processed/vessels_for_score.jsonl.gz
"""

import gzip
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IN_PATH = PROJECT_ROOT / "data_new" / "processed" / "final_vessel_matches.jsonl"
OUT_PATH = PROJECT_ROOT / "data_new" / "processed" / "vessels_for_score.jsonl.gz"


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def convert_row(row: dict) -> dict:
    """final_vessel_matches.jsonl의 한 행을 score/ 계약 형태로 변환한다."""
    tac = row.get("tac") or {}
    mof = row.get("mof") or {}

    tonnage = _to_float(tac.get("tonnageGtTac"))
    if tonnage is None:
        tonnage = _to_float(mof.get("tonnageGtMof"))

    return {
        "vesselId": row["gfwVesselId"],
        "name": row.get("gfwName"),
        "tonnage": tonnage,
        "fishingType": [],
        "matchTier": row.get("matchTier"),
        "matchConfidence": row.get("matchConfidence"),
        "fuzzyScore": row.get("fuzzyScore"),
        "fuzzySource": row.get("fuzzySource"),
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with_tonnage = 0
    with open(IN_PATH, encoding="utf-8") as f_in, gzip.open(OUT_PATH, "wt", encoding="utf-8") as f_out:
        for line in f_in:
            row = json.loads(line)
            converted = convert_row(row)
            if converted["tonnage"] is not None:
                with_tonnage += 1
            f_out.write(json.dumps(converted, ensure_ascii=False) + "\n")
            total += 1

    print(f"[output] {OUT_PATH}")
    print(f"  총 {total}척, 톤수 확보 {with_tonnage}척 ({100 * with_tonnage / total:.1f}%)")


if __name__ == "__main__":
    main()
