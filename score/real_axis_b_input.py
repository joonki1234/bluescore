"""실제 스냅샷을 B축 기준선의 이벤트 입력 형태로 변환한다.

선박 메타데이터는 A축과 동일하게 `score.real_vessel_input`에서 가져온다.
날씨 단위와 해역·계절 변환은 기존 B축 규칙을 유지한다.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Dict, List, Optional

from score.peer_grouping import gear_type_key, region_key, season_key
from score.real_vessel_input import (
    DEFAULT_GFW_VESSELS_PATH,
    DEFAULT_MATCHES_PATH,
    load_real_vessel_records,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"

# 해양기상 원본의 결측 마커다.
MISSING_WEATHER_MARKER = "미제공"


def _to_float(value) -> Optional[float]:
    """문자열·숫자를 float로 바꾸고 결측이나 변환 실패는 None으로 둔다."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == MISSING_WEATHER_MARKER:
            return None
        value = stripped
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_vessel_feature_index(
    matches_path: Path = DEFAULT_MATCHES_PATH,
    gfw_vessels_path: Path = DEFAULT_GFW_VESSELS_PATH,
) -> Dict[str, dict]:
    """공용 선박 레코드를 B축의 톤수·어업종 조회 인덱스로 바꾼다."""
    return {
        vessel["vesselId"]: {
            "tonnageGt": vessel.get("tonnage"),
            "gearType": gear_type_key(vessel.get("fishingType")),
        }
        for vessel in load_real_vessel_records(matches_path, gfw_vessels_path)
    }


def load_vessel_tonnage_index(
    matches_path: Path = DEFAULT_MATCHES_PATH,
    gfw_vessels_path: Path = DEFAULT_GFW_VESSELS_PATH,
) -> Dict[str, Optional[float]]:
    """기존 호출부를 위한 톤수 전용 호환 인덱스다."""
    return {
        vessel_id: features["tonnageGt"]
        for vessel_id, features in load_vessel_feature_index(
            matches_path, gfw_vessels_path
        ).items()
    }


def _load_events(events_path: Path) -> List[dict]:
    with gzip.open(events_path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _sea_area_label(latitude, longitude) -> Optional[str]:
    """LightGBM 범주형 피처에 맞게 해역 격자를 문자열로 바꾼다."""
    key = region_key(latitude, longitude)
    if key is None:
        return None
    row, col = key
    return f"{row}_{col}"


def _event_to_axis_b_row(event: dict, vessel_features: Optional[dict]) -> dict:
    """이벤트와 공용 선박 특징을 B축 입력 row로 변환한다."""
    vessel_features = vessel_features or {}
    latitude = event.get("latitude")
    longitude = event.get("longitude")

    return {
        "vesselId": event.get("vesselId"),
        "tonnageGt": vessel_features.get("tonnageGt"),
        "averageSpeedKnots": event.get("averageSpeedKnots"),
        "durationHours": event.get("durationHours"),
        "totalDistanceKm": event.get("totalDistanceKm"),
        "windSpeedMs": _to_float(event.get("weather_WIND_SPEED")),
        "seaSurfaceTempC": _to_float(event.get("weather_WATER_TEMPER")),
        "currentSpeedMs": _to_float(event.get("weather_SURFACE_CURR_SPEED")),
        "seaArea": _sea_area_label(latitude, longitude),
        "season": season_key(event.get("start")),
        "gearType": vessel_features.get("gearType"),
    }


def build_axis_b_rows(
    events_path: Path = DEFAULT_EVENTS_PATH,
    matches_path: Path = DEFAULT_MATCHES_PATH,
    gfw_vessels_path: Path = DEFAULT_GFW_VESSELS_PATH,
) -> List[dict]:
    """추적 중인 이벤트와 공용 선박 스냅샷으로 B축 입력을 만든다."""
    vessel_feature_index = load_vessel_feature_index(matches_path, gfw_vessels_path)
    events = _load_events(events_path)
    return [
        _event_to_axis_b_row(
            event,
            vessel_feature_index.get(event.get("vesselId")),
        )
        for event in events
    ]
