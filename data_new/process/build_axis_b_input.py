"""B축(LightGBM 기준선) 입력 생성 — score/axis_b_baseline.py가 기대하는
flat 이벤트 행(vesselId/tonnageGt/averageSpeedKnots/durationHours/
seaSurfaceTempC/windSpeedMs/currentSpeedMs/gearType/seaArea/season)으로
events_with_weather.jsonl + final_vessel_matches.jsonl을 합친다.

TODO.md 47번(B축 연결 스크립트 없음) 대응. score/ 필드명 계약은
data_new/SCHEMA_DRAFT.md, score/axis_b_baseline.py의
REQUIRED_PHYSICS_FIELDS/NUMERIC_FEATURE_COLUMNS/CATEGORICAL_FEATURE_COLUMNS
참고.

⚠ 매칭 실패 선박은 tonnageGt=None으로 그대로 내보낸다 — 걸러내지 않는다.
score/axis_b_baseline.py._prepare_valid_rows가 REQUIRED_PHYSICS_FIELDS
결측 행을 스킵사유와 함께 이미 처리하므로 여기서 중복 구현하지 않는다.

⚠ 해양기상 필드 단위가 미확인 상태(README.md 한계 목록)다 — 여기서는
값만 그대로 옮기고 단위 검증은 하지 않는다. 확인 전까지 seaSurfaceTempC
등 절대값을 신뢰하지 말 것.

⚠ gearType/seaArea는 TAC 경유 매칭에서만 나온다(MOF는 세부 어업방법 정보가
없음) — tier3에서 top 후보 출처가 tac이어도 assemble_matches.py가 만드는
축약 tac 딕셔너리엔 gearTypeNamesTac/portNamesTac이 안 들어있어서, 여기서
vesselNoTac으로 tac_vessels_normalized.jsonl을 다시 조회해 채운다.

사용법:
    python build_axis_b_input.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
EVENTS_PATH = PROCESSED / "events_with_weather.jsonl"
MATCHES_PATH = PROCESSED / "final_vessel_matches.jsonl"
TAC_VESSELS_PATH = PROCESSED / "tac_vessels_normalized.jsonl"
OUT_PATH = PROCESSED / "axis_b_input.jsonl"

# 원본 필드명 -> score/ 계약 필드명. 단위 미확인(위 docstring 경고 참고).
WEATHER_FIELD_MAP = {
    "weather_WATER_TEMPER": "seaSurfaceTempC",
    "weather_WIND_SPEED": "windSpeedMs",
    "weather_SURFACE_CURR_SPEED": "currentSpeedMs",
}

SEASON_BY_MONTH = {
    3: "봄", 4: "봄", 5: "봄",
    6: "여름", 7: "여름", 8: "여름",
    9: "가을", 10: "가을", 11: "가을",
    12: "겨울", 1: "겨울", 2: "겨울",
}


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _to_float(value) -> float | None:
    if value in (None, "", "미제공"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_vessel_features(match: dict | None, tac_by_no: dict) -> tuple:
    """(tonnageGt, gearType, seaArea) — 매칭 없으면 전부 None."""
    if not match:
        return None, None, None

    tonnage = gear = sea_area = None

    tac = match.get("tac")
    if tac:
        vessel_no = tac.get("vesselNoTac")
        full = tac_by_no.get(vessel_no) if vessel_no else None
        source = full or tac
        tonnage = _to_float(source.get("tonnageGtTac"))
        gear_list = source.get("gearTypeNamesTac")
        if gear_list:
            gear = gear_list[0]
        port_list = source.get("portNamesTac")
        if port_list:
            sea_area = port_list[0]

    if tonnage is None:
        mof = match.get("mof")
        if mof:
            tonnage = _to_float(mof.get("tonnageGtMof"))

    return tonnage, gear, sea_area


def _season(start_iso: str) -> str | None:
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return SEASON_BY_MONTH.get(dt.month)


def run() -> None:
    matches = {m["gfwVesselId"]: m for m in _load_jsonl(MATCHES_PATH)}
    tac_by_no = {t["vesselNoTac"]: t for t in _load_jsonl(TAC_VESSELS_PATH)}

    n_events = 0
    n_with_tonnage = 0
    n_with_gear = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        with EVENTS_PATH.open(encoding="utf-8") as f:
            for line in f:
                event = json.loads(line)
                n_events += 1
                match = matches.get(event["vesselId"])
                tonnage, gear, sea_area = _extract_vessel_features(match, tac_by_no)
                if tonnage is not None:
                    n_with_tonnage += 1
                if gear is not None:
                    n_with_gear += 1

                row = {
                    "eventId": event["eventId"],
                    "vesselId": event["vesselId"],
                    "tonnageGt": tonnage,
                    "averageSpeedKnots": event.get("averageSpeedKnots"),
                    "durationHours": event.get("durationHours"),
                    "gearType": gear,
                    "seaArea": sea_area,
                    "season": _season(event.get("start")),
                }
                for raw_field, out_field in WEATHER_FIELD_MAP.items():
                    row[out_field] = _to_float(event.get(raw_field))

                out.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"이벤트 {n_events}건 -> {OUT_PATH}")
    print(f"tonnageGt 있음: {n_with_tonnage}/{n_events} ({n_with_tonnage / n_events * 100:.1f}%)")
    print(f"gearType 있음:  {n_with_gear}/{n_events} ({n_with_gear / n_events * 100:.1f}%)")


if __name__ == "__main__":
    run()
