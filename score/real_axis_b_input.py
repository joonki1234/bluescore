"""
담당: 김준기, 오동규

`data_new/`의 실제 산출물(`events_with_weather.jsonl.gz`,
`final_vessel_matches.jsonl`)을 `score/axis_b_baseline.py`가 요구하는
평평한 row 형태로 변환한다. 원본 파일·필드명은 바꾸지 않고 읽어서 score/가
원하는 이름으로만 새로 변환한다.

필드 처리 메모:
    - `tonnageGt`: `tac.tonnageGtTac` 또는 `mof.tonnageGtMof` 중 있는 쪽을
      쓴다 (실측상 둘 다 채워진 행은 없어 우선순위 로직 불필요).
    - `windSpeedMs`/`seaSurfaceTempC`/`currentSpeedMs`: 원본 필드명과 정황
      근거로 단위를 m/s·섭씨로 추정한 것이며 **공식 확인은 아니다**
      (특히 currentSpeedMs는 단위 추정 근거조차 없음). 확인되면 교체할 것.
    - `seaArea`/`season`: `score/peer_grouping.py`의
      `region_key()`/`season_key()`를 재사용해 즉시 채운다(`_sea_area_label()`
      참고 — region_key()의 튜플 반환값을 문자열로 바꿔서 쓴다).
    - `gearType`: 이번 배치에서는 `None`으로 둔다.
    - 매칭 안 된 선박·날씨 없는 이벤트는 걸러내지 않는다 —
      `axis_b_baseline.py`의 `_prepare_valid_rows()`가 필수 필드 결측을
      알아서 skip한다.

`"미제공"`(해양기상 결측 마커)과 빈 문자열은 `None`으로, 그 외 문자열은
float로 변환한다. 변환 실패도 `None`으로 처리한다.
"""

import gzip
import json
from pathlib import Path
from typing import Dict, List, Optional

from score.peer_grouping import region_key, season_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"
DEFAULT_MATCHES_PATH = PROJECT_ROOT / "data_new" / "processed" / "final_vessel_matches.jsonl"

# 해양기상 원본의 결측 마커 — "미제공"은 값을 안 준다는 뜻이지 0이 아니다.
MISSING_WEATHER_MARKER = "미제공"


def _to_float(value) -> Optional[float]:
    """문자열/숫자/None을 float 또는 None으로 정규화한다.

    "미제공"·빈 문자열·변환 실패는 전부 None으로 취급한다 — 값을 지어내지 않는다.
    """
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


def load_vessel_tonnage_index(matches_path: Path = DEFAULT_MATCHES_PATH) -> Dict[str, Optional[float]]:
    """`final_vessel_matches.jsonl`을 읽어 gfwVesselId -> 톤수(GT) 조회 테이블을 만든다.

    `tac.tonnageGtTac`가 있으면 그 값, 없고 `mof.tonnageGtMof`가 있으면 그 값,
    둘 다 없으면 None.
    """
    index: Dict[str, Optional[float]] = {}
    with matches_path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            vessel_id = record.get("gfwVesselId")
            if vessel_id is None:
                continue

            tac = record.get("tac")
            mof = record.get("mof")
            if tac:
                index[vessel_id] = _to_float(tac.get("tonnageGtTac"))
            elif mof:
                index[vessel_id] = _to_float(mof.get("tonnageGtMof"))
            else:
                index[vessel_id] = None
    return index


def _load_events(events_path: Path) -> List[dict]:
    with gzip.open(events_path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _sea_area_label(latitude, longitude) -> Optional[str]:
    """region_key()의 (row, col) 튜플을 문자열로 바꾼다.

    튜플을 그대로 범주형 피처로 쓰면, LightGBM이 카테고리를 numpy 배열로
    저장하는 과정에서 같은 길이의 튜플들이 2차원 배열로 해석돼 리스트로
    바뀌어버려 예측 단계에서 `TypeError: unhashable type: 'list'`가 난다.
    """
    key = region_key(latitude, longitude)
    if key is None:
        return None
    row, col = key
    return f"{row}_{col}"


def _event_to_axis_b_row(event: dict, tonnage_gt: Optional[float]) -> dict:
    """이벤트 1건 + 조회된 톤수를 axis_b_baseline.py가 요구하는 row로 변환한다."""
    latitude = event.get("latitude")
    longitude = event.get("longitude")
    start = event.get("start")

    return {
        "vesselId": event.get("vesselId"),
        "tonnageGt": tonnage_gt,
        "averageSpeedKnots": event.get("averageSpeedKnots"),
        "durationHours": event.get("durationHours"),
        "totalDistanceKm": event.get("totalDistanceKm"),
        "windSpeedMs": _to_float(event.get("weather_WIND_SPEED")),
        "seaSurfaceTempC": _to_float(event.get("weather_WATER_TEMPER")),
        "currentSpeedMs": _to_float(event.get("weather_SURFACE_CURR_SPEED")),
        "seaArea": _sea_area_label(latitude, longitude),
        "season": season_key(start),
        "gearType": None,
    }


def build_axis_b_rows(
    events_path: Path = DEFAULT_EVENTS_PATH,
    matches_path: Path = DEFAULT_MATCHES_PATH,
) -> List[dict]:
    """`events_with_weather.jsonl.gz` + `final_vessel_matches.jsonl`을 조인해서
    `axis_b_baseline.py`(`fit_baseline_model`/`compute_axis_b_efficiency`)에
    바로 넣을 수 있는 row 리스트를 만든다.

    매칭 안 된 선박·날씨 없는 이벤트도 걸러내지 않고 그대로 낸다 — 모듈
    docstring의 "매칭 안 된 선박·날씨 없는 이벤트" 항목 참고.
    """
    tonnage_index = load_vessel_tonnage_index(matches_path)
    events = _load_events(events_path)
    return [
        _event_to_axis_b_row(event, tonnage_index.get(event.get("vesselId")))
        for event in events
    ]
