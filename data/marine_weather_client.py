"""
담당: 김준기, 오동규

국립해양측위정보원_해양기상 정보 서비스 (공공데이터포털, data.go.kr/data/15033708) 클라이언트.

매뉴얼(OPEN API 매뉴얼, 2026-08-14 확보) 기준 엔드포인트 2종을 제공한다:
    - 최신 기상정보(openWeatherNow.do): 관측지점의 현재 시점 값
    - 날짜별 기상정보(openWeatherDate.do): 검색기준날짜(date 파라미터) 시점의 값
      — score/axis_b_baseline.py의 LightGBM 피처(seaSurfaceTempC 등)는 GFW
      조업 이벤트 "당시" 시점의 해황이 필요하므로, 이 엔드포인트가 필수다.
둘 다 풍향·풍속·수온·기온·습도·기압·유향·유속을 조회한다. data/gfw_client.py와
동일하게 requests 기반 함수형 스타일로 작성했다.

매뉴얼 원문(비고): "전송방식: post, get / 캐릭터셋: UTF-8 / 파라미터 대소문자
구분 / 요청주소는 변경될 수 있음 / 데이터 수신·센서 이상 등으로 값이 없을 수 있음."

주의 (명칭 혼동 방지):
    이 API의 "mmsi" 파라미터는 해양기상 관측지점 코드다. GFW 등에서 쓰는 선박
    식별자 MMSI(Maritime Mobile Service Identity)와는 완전히 다른 개념이므로, 이
    모듈의 함수/변수명은 항상 station_code로 표기하고 mmsi라는 이름을 쓰지 않는다.
    실제 HTTP 요청 파라미터를 만들 때만 매뉴얼에 맞춰 "mmsi" 키를 사용한다.

주의 (서비스키, 2026-08-14 정정):
    이 서비스는 data.go.kr 게이트웨이가 아니라 국립해양측위정보원 자체 신청
    시스템(마이페이지 없이 별도 "서비스신청" 폼)에서 키를 발급한다 — 그래서
    data.go.kr 표준 Encoding/Decoding 키 두 종류가 아니라 신청 즉시 발급되는
    UUID 형태의 키 하나뿐이다(예: "C2061283-A758-47EE-A923-...", 36자). 이중
    인코딩 문제는 해당 없음 — 발급받은 값을 그대로 MARINE_WEATHER_API_KEY에 넣는다.

확정된 사항 (2026-08-14 실제 호출로 검증):
    - date 파라미터 형식: YYYYMMDD (예: "20260813")
    - 응답 최상위 구조: {"result": {"status": "OK", "message": "", "recordset": [...]}}
    - 실제 필드명: _normalize_weather_record()의 docstring 참고. 수치 필드는
      문자열로 오고("3.6" 등), 결측은 "데이터없음" 같은 마커가 아니라 JSON null.
"""

import math
import os
from typing import Iterable, List, Optional, Union

import requests
from dotenv import load_dotenv

from data.marine_weather_stations import MARINE_WEATHER_STATIONS, MarineWeatherStation

load_dotenv()

MARINE_WEATHER_API_KEY = os.getenv("MARINE_WEATHER_API_KEY")

BASE_HOST = "http://marineweather.nmpnt.go.kr:8001"
LATEST_WEATHER_URL = f"{BASE_HOST}/openWeatherNow.do"
WEATHER_BY_DATE_URL = f"{BASE_HOST}/openWeatherDate.do"

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
    openWeatherNow.do/openWeatherDate.do 응답 JSON에서 관측지점별 레코드
    리스트를 뽑아낸다.

    2026-08-14 실제 응답으로 확인된 구조(두 엔드포인트 동일):
        {"result": {"status": "OK", "message": "", "recordset": [ {...}, ... ]}}
    """
    if not isinstance(body, dict):
        return []
    recordset = ((body.get("result") or {}).get("recordset"))
    if recordset is None:
        return []
    return recordset if isinstance(recordset, list) else [recordset]


def _to_float(value):
    """응답의 수치 필드는 문자열로 오고(예: "3.6"), 결측은 JSON null로 온다."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_weather_record(record: dict) -> dict:
    """레코드 딕셔너리를 내부 표준 형태로 정규화한다.

    2026-08-14 실제 응답으로 필드명 확정(recordset의 원소 하나):
        DATETIME(YYYYMMDDHHMMSS), MMAF_CODE, MMAF_NM(기관명), MMSI_CODE,
        MMSI_NM(관측지점명), WIND_DIRECT, WIND_SPEED, SURFACE_CURR_DRC,
        SURFACE_CURR_SPEED, WAVE_DRC, WAVE_HEIGTH(원문 철자 그대로 "HEIGTH"),
        AIR_TEMPERATURE, HUMIDITY, AIR_PRESSURE, WATER_TEMPER, SALINITY,
        HORIZON_VISIBL, TIDE_SPEED, TIDE_DIRECT, TIDE_TENDENCY, LATITUDE,
        LONGITUDE(관측지점 정밀 좌표 — data/marine_weather_stations.py의
        추정 좌표보다 이 응답 값이 더 정확하므로, 필요하면 이 값으로
        갱신을 검토할 것).

    결측은 "데이터없음"/"미제공" 같은 마커 문자열이 아니라 JSON null로 온다
    (모듈 상단 MISSING_VALUE_MARKERS는 실제로는 안 쓰이는 것으로 확인됨 —
    그래도 혹시 다른 필드에서 나올 수 있어 방어적으로 남겨둔다).
    """
    record = _replace_missing_markers(record)

    return {
        "stationCode": record.get("MMSI_CODE"),
        "stationName": record.get("MMSI_NM"),
        "agencyCode": record.get("MMAF_CODE"),
        "agencyName": record.get("MMAF_NM"),
        "observedAt": record.get("DATETIME"),  # YYYYMMDDHHMMSS 문자열
        "latitude": _to_float(record.get("LATITUDE")),
        "longitude": _to_float(record.get("LONGITUDE")),
        "windDirectionDeg": _to_float(record.get("WIND_DIRECT")),
        "windSpeedMs": _to_float(record.get("WIND_SPEED")),
        "seaSurfaceTempC": _to_float(record.get("WATER_TEMPER")),
        "airTempC": _to_float(record.get("AIR_TEMPERATURE")),
        "humidityPercent": _to_float(record.get("HUMIDITY")),
        "pressureHpa": _to_float(record.get("AIR_PRESSURE")),
        "currentDirectionDeg": _to_float(record.get("SURFACE_CURR_DRC")),
        "currentSpeedMs": _to_float(record.get("SURFACE_CURR_SPEED")),
        "waveDirectionDeg": _to_float(record.get("WAVE_DRC")),
        "waveHeightM": _to_float(record.get("WAVE_HEIGTH")),
        "salinity": _to_float(record.get("SALINITY")),
        "visibilityM": _to_float(record.get("HORIZON_VISIBL")),
        "tideSpeed": _to_float(record.get("TIDE_SPEED")),
        "tideDirectionDeg": _to_float(record.get("TIDE_DIRECT")),
        "tideTendency": record.get("TIDE_TENDENCY"),
        "raw": record,
    }


def _normalize_station_codes(station_codes: Union[str, Iterable[str]]) -> List[str]:
    if isinstance(station_codes, str):
        return [station_codes.strip()] if station_codes.strip() else []
    return [str(code).strip() for code in station_codes if str(code).strip()]


def _call_weather_endpoint(url: str, params: dict) -> List[dict]:
    """get_latest_weather()/get_weather_by_date()가 공유하는 호출부.
    요청을 보내고, 정규화된 레코드 리스트를 반환한다."""
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

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
    station_code_list = _normalize_station_codes(station_codes)
    if not station_code_list:
        raise ValueError("station_codes는 비어 있을 수 없습니다.")
    agency_code = (agency_code or "").strip()
    if not agency_code:
        raise ValueError("agency_code는 비어 있을 수 없습니다.")

    params = _auth_params()
    params["mmaf"] = agency_code
    params["mmsi"] = ",".join(station_code_list)
    params["dataType"] = data_type

    return _call_weather_endpoint(LATEST_WEATHER_URL, params)


def get_weather_by_date(
    date: str,
    station_codes: Union[str, Iterable[str]],
    agency_code: str,
    data_type: int = DATA_TYPE_EXPLICIT_MISSING,
) -> List[dict]:
    """
    특정 검색기준날짜의 해양기상 정보를 조회한다 (openWeatherDate.do).

    GFW 조업 이벤트 "당시" 시점의 해황(수온·풍속·유속 등)이 필요한
    score/axis_b_baseline.py의 LightGBM 피처용으로, get_latest_weather()와
    달리 과거 시점을 조회할 수 있다.

    Args:
        date: 매뉴얼상 "date"(검색기준날짜) 파라미터. 형식(YYYYMMDD 등)이 매뉴얼에
            명시돼 있지 않아 아직 미확정 — 활용신청 승인 후 소규모 호출로
            형식을 먼저 확정할 것 (모듈 docstring의 TODO 참고). 확정 전까지는
            호출자가 검증된 형식으로 넘겨야 한다.
        station_codes: get_latest_weather()와 동일 (관측지점 코드, "mmsi" 파라미터).
        agency_code: get_latest_weather()와 동일 (기관코드, "mmaf" 파라미터).
        data_type: get_latest_weather()와 동일.

    Returns:
        정규화된 관측지점별 해당 날짜 해양기상 딕셔너리 리스트.
    """
    date = (date or "").strip()
    if not date:
        raise ValueError("date는 비어 있을 수 없습니다.")

    station_code_list = _normalize_station_codes(station_codes)
    if not station_code_list:
        raise ValueError("station_codes는 비어 있을 수 없습니다.")
    agency_code = (agency_code or "").strip()
    if not agency_code:
        raise ValueError("agency_code는 비어 있을 수 없습니다.")

    params = _auth_params()
    params["date"] = date
    params["mmaf"] = agency_code
    params["mmsi"] = ",".join(station_code_list)
    params["dataType"] = data_type

    return _call_weather_endpoint(WEATHER_BY_DATE_URL, params)


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


def get_weather_near_at(
    latitude: float,
    longitude: float,
    date: str,
    data_type: int = DATA_TYPE_EXPLICIT_MISSING,
) -> Optional[dict]:
    """
    주어진 위경도에서 가장 가까운 관측지점을 찾아, 그 지점의 특정 날짜 해양기상
    정보를 반환한다.

    find_nearest_station()과 get_weather_by_date()를 합친 편의 함수다 —
    GFW 조업 이벤트(위치+시각)에 해황 피처를 붙일 때 이 함수를 쓰면 된다.
    해당 지점/날짜의 데이터가 없으면 None을 반환한다.
    """
    nearest_station = find_nearest_station(latitude, longitude)
    records = get_weather_by_date(
        date=date,
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
