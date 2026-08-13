"""
담당: 김준기, 오동규

국립해양측위정보원_해양기상 정보 서비스 (공공데이터포털, data.go.kr/data/15033708) 클라이언트.

매뉴얼 기준 최신 기상정보 엔드포인트(openWeatherNow.do)를 호출해 관측지점의
풍향·풍속·수온·기온·습도·기압·유향·유속을 조회한다. data/gfw_client.py와 동일하게
requests 기반 함수형 스타일로 작성했다.

주의 (명칭 혼동 방지):
    이 API의 "mmsi" 파라미터는 해양기상 관측지점 코드다. GFW 등에서 쓰는 선박
    식별자 MMSI(Maritime Mobile Service Identity)와는 완전히 다른 개념이므로, 이
    모듈의 함수/변수명은 항상 station_code로 표기하고 mmsi라는 이름을 쓰지 않는다.
    실제 HTTP 요청 파라미터를 만들 때만 매뉴얼에 맞춰 "mmsi" 키를 사용한다.

주의 (공공데이터포털 서비스키):
    .env의 MARINE_WEATHER_API_KEY에는 공공데이터포털에서 발급한 "Decoding" 인증키를
    넣어야 한다. requests의 params=...는 값을 자동으로 URL 인코딩하므로, 이미
    인코딩된 키를 넣으면 이중 인코딩되어 인증 오류가 날 수 있다.

TODO(김준기, 오동규): 아래는 매뉴얼의 엔드포인트/파라미터 정의까지는 반영했지만,
    실제 응답 JSON의 필드명(풍향/풍속/수온/기온/습도/기압/유향/유속 등 키 이름)과
    최상위 구조(items 배열 위치 등)는 아직 실제 응답 샘플로 검증하지 못했다.
    _normalize_weather_record()와 _extract_records()의 TODO 주석을 실제 응답을
    받은 뒤 채워야 한다.
"""

import math
import os
from typing import Iterable, List, Optional, Union

import requests
from dotenv import load_dotenv

from data.marine_weather_stations import MARINE_WEATHER_STATIONS, MarineWeatherStation

load_dotenv()

MARINE_WEATHER_API_KEY = os.getenv("MARINE_WEATHER_API_KEY")

BASE_URL = "http://marineweather.nmpnt.go.kr:8001/openWeatherNow.do"

RESULT_TYPE = "json"
# dataType=2: 결측치를 값 생략 없이 "데이터없음"/"미제공" 등으로 명시적으로 받는 옵션 (매뉴얼 기준)
DATA_TYPE_EXPLICIT_MISSING = 2

REQUEST_TIMEOUT_SECONDS = 30

# 응답에서 결측을 나타내는 마커 문자열 -> None으로 치환한다.
MISSING_VALUE_MARKERS = {"데이터없음", "미제공"}


class MarineWeatherApiError(Exception):
    """해양기상 정보 API가 에러(HTTP 에러 또는 비정상 응답)를 반환했을 때 발생시키는 예외."""

    def __init__(self, message: str, status_code: int, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _auth_params() -> dict:
    if not MARINE_WEATHER_API_KEY:
        raise RuntimeError(
            "Missing MARINE_WEATHER_API_KEY in environment. "
            ".env.example을 .env로 복사하고 MARINE_WEATHER_API_KEY(Decoding 키)를 설정하세요."
        )
    return {"serviceKey": MARINE_WEATHER_API_KEY, "resultType": RESULT_TYPE}


def _replace_missing_markers(value):
    """MISSING_VALUE_MARKERS에 해당하는 문자열 값을 None으로 재귀적으로 치환한다."""
    if isinstance(value, str):
        return None if value.strip() in MISSING_VALUE_MARKERS else value
    if isinstance(value, dict):
        return {key: _replace_missing_markers(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_replace_missing_markers(v) for v in value]
    return value


def _extract_records(body) -> List[dict]:
    """
    openWeatherNow.do 응답 JSON에서 관측지점별 레코드 리스트를 뽑아낸다.

    TODO(김준기, 오동규): 실제 응답 샘플을 받으면 최상위 구조(예: response.body.items.item
    형태인지, 단순 배열인지)를 확인해 이 함수를 실제 구조에 맞게 단순화할 것. 지금은
    구조를 모르는 상태이므로 흔한 공공 API 응답 형태 몇 가지를 방어적으로 시도한다.
    """
    if body is None:
        return []
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        items = (((body.get("response") or {}).get("body") or {}).get("items") or {}).get("item")
        if items is not None:
            return items if isinstance(items, list) else [items]
        for key in ("result", "results", "list", "data"):
            if isinstance(body.get(key), list):
                return body[key]
        return [body]
    return []


def _normalize_weather_record(record: dict) -> dict:
    """레코드 딕셔너리를 내부 표준 형태로 정규화하고 결측 마커를 None으로 치환한다.

    TODO(김준기, 오동규): 실제 필드명 확정 후 아래 매핑을 교체할 것. 지금은 흔히 쓰이는
    필드명(풍향/풍속/수온/기온/습도/기압/유향/유속)을 추정해 넣어둔 잠정값이며, 매핑되지
    않는 키는 raw에 원본 그대로 보존된다.
    """
    record = _replace_missing_markers(record)

    return {
        "stationCode": record.get("mmsi") or record.get("station_code") or record.get("stationCode"),
        "agencyCode": record.get("mmaf") or record.get("agency_code") or record.get("agencyCode"),
        "observedAt": record.get("obsDt") or record.get("obs_time") or record.get("observedAt"),
        "windDirectionDeg": record.get("windDir") or record.get("wind_direction"),
        "windSpeedMs": record.get("windSpd") or record.get("wind_speed"),
        "seaSurfaceTempC": record.get("waterTemp") or record.get("sea_temp"),
        "airTempC": record.get("airTemp") or record.get("air_temp"),
        "humidityPercent": record.get("humidity"),
        "pressureHpa": record.get("pressure") or record.get("air_pressure"),
        "currentDirectionDeg": record.get("currentDir") or record.get("current_direction"),
        "currentSpeedMs": record.get("currentSpd") or record.get("current_speed"),
        "raw": record,
    }


def get_latest_weather(
    station_codes: Union[str, Iterable[str]],
    agency_code: str,
    data_type: int = DATA_TYPE_EXPLICIT_MISSING,
) -> List[dict]:
    """
    관측지점 코드(들)로 최신 해양기상 정보를 조회한다 (openWeatherNow.do).

    Args:
        station_codes: 매뉴얼상 "mmsi" 파라미터에 해당하는 관측지점 코드. 문자열 하나
            또는 여러 개(list/tuple)를 넘기면 콤마로 이어붙여 한 번에 요청한다.
            선박 MMSI가 아니라 관측지점 코드이므로 이름을 station_code로 구분한다.
        agency_code: 매뉴얼상 "mmaf" 파라미터에 해당하는 기관코드.
        data_type: dataType 파라미터. 기본값 2는 결측치를 명시적으로("데이터없음"/
            "미제공" 등) 내려받기 위한 매뉴얼 지정값.

    Returns:
        정규화된 관측지점별 최신 해양기상 딕셔너리 리스트.
    """
    if isinstance(station_codes, str):
        station_code_list = [station_codes.strip()] if station_codes.strip() else []
    else:
        station_code_list = [str(code).strip() for code in station_codes if str(code).strip()]

    if not station_code_list:
        raise ValueError("station_codes는 비어 있을 수 없습니다.")
    agency_code = (agency_code or "").strip()
    if not agency_code:
        raise ValueError("agency_code는 비어 있을 수 없습니다.")

    params = _auth_params()
    params["mmaf"] = agency_code
    params["mmsi"] = ",".join(station_code_list)
    params["dataType"] = data_type

    response = requests.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    try:
        body = response.json()
    except ValueError:
        body = None

    if not response.ok:
        raise MarineWeatherApiError(
            "Marine weather API returned an HTTP error.",
            status_code=response.status_code,
            details=body if body is not None else response.text,
        )

    records = _extract_records(body)
    return [_normalize_weather_record(record) for record in records]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 대권거리(km)를 하버사인 공식으로 계산한다."""
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def find_nearest_station(latitude: float, longitude: float) -> MarineWeatherStation:
    """
    주어진 위경도에서 가장 가까운 해양기상 관측지점을 찾는다.

    data/marine_weather_stations.py의 MARINE_WEATHER_STATIONS 중 좌표(latitude/
    longitude)가 채워진 지점만 대상으로 하버사인 거리로 최근접 지점을 계산한다.
    좌표가 아직 None인 지점(매뉴얼 확인 필요)은 대상에서 제외된다.
    """
    candidates = [
        station
        for station in MARINE_WEATHER_STATIONS
        if station.latitude is not None and station.longitude is not None
    ]
    if not candidates:
        raise ValueError(
            "좌표가 채워진 관측지점이 없습니다. "
            "data/marine_weather_stations.py의 MARINE_WEATHER_STATIONS 좌표를 확인하세요."
        )

    return min(
        candidates,
        key=lambda station: _haversine_km(latitude, longitude, station.latitude, station.longitude),
    )


def get_latest_weather_near(
    latitude: float,
    longitude: float,
    data_type: int = DATA_TYPE_EXPLICIT_MISSING,
) -> Optional[dict]:
    """
    주어진 위경도에서 가장 가까운 관측지점을 찾아 그 지점의 최신 해양기상 정보를 반환한다.

    find_nearest_station()과 get_latest_weather()를 합친 편의 함수다. 해당 지점의
    데이터가 없으면 None을 반환한다.
    """
    nearest_station = find_nearest_station(latitude, longitude)
    records = get_latest_weather(
        station_codes=nearest_station.station_code,
        agency_code=nearest_station.agency_code,
        data_type=data_type,
    )
    if not records:
        return None

    result = records[0]
    result["nearestStation"] = {
        "stationCode": nearest_station.station_code,
        "stationName": nearest_station.station_name,
        "agencyCode": nearest_station.agency_code,
        "distanceKm": _haversine_km(
            latitude, longitude, nearest_station.latitude, nearest_station.longitude
        ),
    }
    return result
