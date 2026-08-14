"""
담당: 김태윤

Global Fishing Watch (GFW) API v3 클라이언트.

원본: ~/Downloads/bluescore-demo/server.js (Node.js/Express)의
/api/vessels/search, /api/events 라우트 로직을 requests 기반 Python으로 이식.

2026-08-13 재작성 (호출 방식 재검증):
    이전 버전은 검증 없이 짜인 부분이 있어 실제 GFW API와 어긋났다. 아래
    호출 방식은 개인 임시 작업 폴더(현재는 삭제됨)에서 실제 API 호출로
    검증된 내용을 "지식"으로만 참고해 다시 짠 것이다 (그 폴더의 코드/설정/
    환경변수는 가져오지 않음 — 이 프로젝트의 기존 관례를 그대로 따름, 예:
    GFW_API_KEY). 자세한 검증 과정은 `data/rules_common.md`의 "부록: GFW
    전용 규칙" 참고.

    - Vessels Search는 `query`가 아니라 `where` 파라미터를 써야 한다.
      `query=flag='KOR'`는 자유 텍스트 토큰 검색으로 처리되어
      `FLAGKOR`로 정규화되고, flag가 KOR이 아닌 선박까지 섞여 나온다
      (200 응답이지만 오답). `where=flag='KOR'`만 정확한 조건 필터링이다.
    - Vessels Search는 `offset`이 아니라 `since` 커서 토큰으로
      페이지네이션한다 (offset을 보내면 422). limit 최대값은 50.
    - Events는 POST가 아니라 GET이며, 날짜 파라미터는 camelCase가 아니라
      kebab-case(`start-date`/`end-date`)의 URL 쿼리 파라미터다.
    - Events는 이벤트 타입 5종(FISHING/PORT_VISIT/ENCOUNTER/LOITERING/GAP)
      데이터셋을 `datasets[0..4]`로 한 번에 동시 요청할 수 있다 — 하나씩
      나눠 호출할 필요 없다.
    - Events는 `offset`/응답의 `nextOffset`으로 페이지네이션한다.
    - Events는 `vessels[]` 배열로 선박을 최대 20개까지 한 호출에 배치할
      수 있다 (21개부터 422) — 대량 수집 시 get_events_batch() 사용.
    - 429/500/502/503/524는 재시도 대상(최대 3회, 2s/4s/8s 백오프),
      401 등 인증/요청 오류는 즉시 실패 처리한다 (재시도해도 같은 결과).

    _normalize_vessel()/_normalize_event()가 반환하는 필드명은
    score/axis_a_pressure.py 등 다른 모듈이 입력 계약으로 문서화해
    참조하므로 바꾸지 않는다. get_events()는 호출자가 limit/offset을
    신경 쓸 필요 없이 내부적으로 끝까지 페이지를 순회해 해당 기간의
    전체 이벤트를 모아 반환한다.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

GFW_API_KEY = os.getenv("GFW_API_KEY")

BASE_URL = "https://gateway.api.globalfishingwatch.org/v3"

VESSEL_IDENTITY_DATASET = "public-global-vessel-identity:latest"

# 이벤트 타입 5종 — 한 번의 Events 호출에 datasets[0..4]로 동시 요청한다.
EVENT_DATASETS = [
    "public-global-fishing-events:latest",
    "public-global-port-visits-events:latest",
    "public-global-encounters-events:latest",
    "public-global-loitering-events:latest",
    "public-global-gaps-events:latest",
]

REQUEST_TIMEOUT_SECONDS = 30

VESSEL_SEARCH_PAGE_LIMIT = 50  # 확정 최대값 (51 이상 422)
EVENTS_PAGE_LIMIT = 1000  # 확인된 동작 한도

# 커서/오프셋이 서버 쪽 이상으로 진행되지 않는 경우(API 버그, 응답 anomaly
# 등)에도 무한루프에 빠지지 않도록 두는 안전장치 — 정상적인 최대 규모
# 조회(예: flag='KOR' 89,897건 / 50 = 1,798페이지)보다 넉넉히 여유를 둔 값.
MAX_PAGINATION_PAGES = 20000

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 524}
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [2, 4, 8]


class GfwApiError(Exception):
    """GFW API가 에러 응답(4xx/5xx)을 반환했을 때 발생시키는 예외."""

    def __init__(self, message: str, status_code: int, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _auth_headers() -> dict:
    if not GFW_API_KEY:
        raise RuntimeError(
            "Missing GFW_API_KEY in environment. .env.example을 .env로 복사하고 GFW_API_KEY를 설정하세요."
        )
    return {
        "Authorization": f"Bearer {GFW_API_KEY}",
        "Accept": "application/json",
    }


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """429/500/502/503/524와 네트워크 오류만 재시도(최대 3회, 2s/4s/8s
    백오프)한다. 401 등 인증/요청 자체가 잘못된 응답은 즉시 그대로 반환한다
    — 재시도해도 같은 결과이기 때문이다.
    """
    response = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except requests.exceptions.RequestException as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise GfwApiError(
                f"Network error calling Global Fishing Watch API: {exc}", status_code=0
            ) from exc

        if response.ok or response.status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_RETRIES:
            return response
        time.sleep(RETRY_BACKOFF_SECONDS[attempt])

    return response


def _as_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_lat_lon_from_position(pos) -> dict:
    if not pos:
        return {"latitude": None, "longitude": None}

    # pos.get("lat", pos.get("latitude"))처럼 default 인자로 fallback을
    # 넣으면 "lat" 키가 아예 없을 때만 동작한다 — 키는 있는데 값이
    # None인 경우(일부 응답에서 실제로 나타남)엔 "latitude" 쪽에 진짜
    # 값이 있어도 무시된다. 그래서 명시적으로 None 체크를 한다.
    lat = pos.get("lat")
    if lat is None:
        lat = pos.get("latitude")
    lon = pos.get("lon")
    if lon is None:
        lon = pos.get("longitude")

    coordinates = pos.get("coordinates")
    if (lat is None or lon is None) and isinstance(coordinates, list) and len(coordinates) >= 2:
        lon, lat = coordinates[0], coordinates[1]

    return {"latitude": _as_number(lat), "longitude": _as_number(lon)}


def _extract_geartype_names(geartypes) -> list:
    """combinedSourcesInfo/registryInfo의 geartypes 필드에서 이름만 뽑는다.
    combinedSourcesInfo 쪽은 [{"name": "...", "source": ..., "yearFrom": ..., "yearTo": ...}, ...]
    형태고, registryInfo 쪽은 ["TRAWLERS", ...]처럼 문자열 리스트라 형태가 다르다.
    """
    if not isinstance(geartypes, list):
        return []
    names = []
    for g in geartypes:
        if isinstance(g, dict):
            name = g.get("name")
        else:
            name = g
        if name and name not in names:
            names.append(name)
    return names


def _normalize_vessel(entry: dict) -> dict:
    """search_vessels 결과 엔트리를 내부 표준 형태로 정규화.

    톤수/길이/어업종(gear)은 GFW 응답에 있으면 그대로 뽑아 채운다 —
    registryInfo(공식 등록부 매칭, 커버리지 낮음)에 tonnageGt/lengthM이
    있고, combinedSourcesInfo(GFW 자체 추정, 커버리지 더 넓음)에
    shiptypes/geartypes가 있다. 둘 다 없으면 None으로 두고, 이후 매칭
    단계에서 국내 선박제원정보로 채운다 — GFW 쪽 데이터가 뼈대이고,
    빈 값만 국내 데이터로 보충하는 방향.
    """
    raw = entry.get("raw", entry) or {}
    registry_info_list = raw.get("registryInfo")
    self_reported_list = raw.get("selfReportedInfo")
    combined_sources_list = raw.get("combinedSourcesInfo")
    registry_info = registry_info_list[0] if isinstance(registry_info_list, list) and registry_info_list else None
    self_reported_info = self_reported_list[0] if isinstance(self_reported_list, list) and self_reported_list else None
    combined_sources_info = (
        combined_sources_list[0] if isinstance(combined_sources_list, list) and combined_sources_list else None
    )

    gfw_id = raw.get("id") or (registry_info or {}).get("id") or (self_reported_info or {}).get("id")
    ssvid = raw.get("ssvid") or (registry_info or {}).get("ssvid") or (self_reported_info or {}).get("ssvid")
    imo = raw.get("imo") or (registry_info or {}).get("imo") or (self_reported_info or {}).get("imo")
    call_sign = (
        raw.get("callsign")
        or (registry_info or {}).get("callsign")
        or (self_reported_info or {}).get("callsign")
    )
    name = (
        raw.get("shipname")
        or raw.get("nShipname")
        or raw.get("vesselName")
        or (self_reported_info or {}).get("shipname")
    )

    tonnage = _as_number((registry_info or {}).get("tonnageGt"))
    length = _as_number((registry_info or {}).get("lengthM"))

    # GFW엔 width(선폭) 필드 자체가 없음 — 국내 선박제원정보(shdth)에서만 채울 수 있음.
    width = None

    fishing_type = _extract_geartype_names((combined_sources_info or {}).get("geartypes")) or _extract_geartype_names(
        (registry_info or {}).get("geartypes")
    )

    return {
        "vesselId": gfw_id,
        "mmsi": ssvid,
        "imo": imo,
        "callSign": call_sign,
        "name": name,
        "tonnage": tonnage,
        "length": length,
        "width": width,
        "fishingType": fishing_type or None,
        "raw": raw,
    }


def _normalize_event(event_entry: dict) -> dict:
    """get_events 결과 엔트리를 내부 표준 형태로 정규화."""
    raw = event_entry or {}
    position = raw.get("position") or raw.get("geometry") or raw.get("location") or {}
    lat_lon = _get_lat_lon_from_position(position)

    start = raw.get("start")
    end = raw.get("end")
    duration_hours = None
    if start and end:
        try:
            s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            duration_hours = max(0.0, (e - s).total_seconds() / 3600)
        except ValueError:
            duration_hours = None

    fishing = raw.get("eventDetails", {}).get("fishing") if isinstance(raw.get("eventDetails"), dict) else None
    fishing = fishing or raw.get("fishing") or {}

    # `or`로 fallback을 연결하면 실제 값이 0(정지 상태의 평균속도, 아주
    # 짧은 이벤트의 이동거리 0km 등)일 때 falsy로 취급돼 fallback 값으로
    # 조용히 덮어써진다 — None일 때만 fallback하도록 명시적으로 분기한다.
    average_speed_knots = (fishing or {}).get("averageSpeedKnots") if isinstance(fishing, dict) else None
    if average_speed_knots is None:
        average_speed_knots = raw.get("avg_speed")

    total_distance_km = (fishing or {}).get("totalDistanceKm") if isinstance(fishing, dict) else None
    if total_distance_km is None:
        total_distance_km = raw.get("distance_km")

    regions = raw.get("regions") or {}
    mpa_related = bool(
        raw.get("mpa")
        or raw.get("protected_area")
        or raw.get("mpas")
        or raw.get("protectedAreas")
        or (isinstance(regions.get("mpa"), list) and len(regions.get("mpa")) > 0)
    )

    # 2026-08-14 실제 호출로 확인(단건 라이브 테스트): 이벤트 원본에
    # "type" 필드가 최상위에 그대로 있음(예: "port_visit"). GAP 이벤트는
    # 5개 데이터셋 중 gaps 데이터셋에서 오며 type="gap"로 내려온다 —
    # data/mock/README_mock_data 제안.md 3번의 eventType/isGap 제안을
    # 그대로 반영한다.
    event_type = raw.get("type")

    return {
        "eventId": raw.get("id"),
        "vesselId": (raw.get("vessel") or {}).get("id") or raw.get("vesselId"),
        "eventType": event_type,
        "start": start,
        "end": end,
        "latitude": lat_lon["latitude"],
        "longitude": lat_lon["longitude"],
        "durationHours": duration_hours,
        "averageSpeedKnots": _as_number(average_speed_knots),
        "totalDistanceKm": _as_number(total_distance_km),
        "mpaRelated": mpa_related,
        "isGap": event_type == "gap",
        "raw": raw,
    }


def search_vessels(where: str) -> list:
    """
    GFW Vessels Search API 호출: GET /v3/vessels/search.

    where: SQL 유사 조건식 문자열 (예: "flag='KOR' AND
        combinedSourcesInfo.shiptypes.name='FISHING'"). 자유 텍스트
        검색(`query` 파라미터)이 아니라 정확한 조건 필터링을 위해
        반드시 `where` 파라미터로 보낸다.

    limit=50(GFW 확정 최대값)으로 `since` 커서 토큰을 이용해 끝까지
    페이지를 순회하여, 조건에 맞는 전체 결과를 모아서 반환한다.
    """
    where = (where or "").strip()
    if not where:
        raise ValueError("where는 비어 있을 수 없습니다.")

    all_entries = []
    since_token = None
    page_count = 0

    while True:
        page_count += 1
        if page_count > MAX_PAGINATION_PAGES:
            raise GfwApiError(
                f"Vessels Search pagination exceeded {MAX_PAGINATION_PAGES} pages — "
                "since 토큰이 진행되지 않는 것으로 보입니다 (API 이상 동작 의심).",
                status_code=None,
                details={"where": where, "collected_so_far": len(all_entries)},
            )

        params = {
            "where": where,
            "datasets[0]": VESSEL_IDENTITY_DATASET,
            "limit": VESSEL_SEARCH_PAGE_LIMIT,
        }
        if since_token:
            params["since"] = since_token

        response = _request_with_retry(
            "GET", f"{BASE_URL}/vessels/search", params=params, headers=_auth_headers()
        )

        try:
            body = response.json()
        except ValueError:
            body = None

        if not response.ok:
            raise GfwApiError(
                "Global Fishing Watch API returned an error.",
                status_code=response.status_code,
                details=body,
            )

        entries = (body or {}).get("entries")
        if not isinstance(entries, list):
            raise GfwApiError(
                "Unexpected response from Global Fishing Watch API.",
                status_code=502,
                details="Missing entries array.",
            )

        all_entries.extend(entries)

        since_token = (body or {}).get("since")
        if len(entries) < VESSEL_SEARCH_PAGE_LIMIT or not since_token:
            break

    results = []
    for index, entry in enumerate(all_entries):
        if not entry:
            continue
        registry_info_list = entry.get("registryInfo")
        self_reported_list = entry.get("selfReportedInfo")
        registry_info = registry_info_list[0] if isinstance(registry_info_list, list) and registry_info_list else None
        self_reported_info = self_reported_list[0] if isinstance(self_reported_list, list) and self_reported_list else None

        def get_field(field_name, registry_info=registry_info, self_reported_info=self_reported_info, entry=entry):
            return entry.get(field_name) or (registry_info or {}).get(field_name) or (self_reported_info or {}).get(field_name)

        gfw_id = entry.get("id") or (registry_info or {}).get("id") or (self_reported_info or {}).get("id")

        results.append(
            {
                "id": gfw_id or get_field("vesselId") or get_field("ssvid") or f"result-{index}",
                "gfwId": gfw_id,
                "vesselName": get_field("shipname") or get_field("ship_name") or get_field("nShipname") or "",
                "imo": get_field("imo"),
                "ssvid": get_field("ssvid"),
                "nationality": get_field("flag"),
                "dataset": entry.get("dataset"),
                "registryInfo": registry_info,
                "selfReportedInfo": self_reported_info,
                "raw": entry,
                "normalized": _normalize_vessel(entry),
            }
        )

    return results


# Events API가 한 호출에 받는 vessels[] 최대 개수 (21개부터 422).
EVENTS_BATCH_SIZE = 20


def _fetch_event_entries(vessel_ids: list, start_date: str, end_date: str) -> list:
    """
    vessel_ids(최대 EVENTS_BATCH_SIZE개)에 대해 GET /v3/events를
    이벤트 타입 5종 동시 요청 + offset 페이지네이션으로 끝까지 순회해
    원본 entry 리스트를 반환한다. get_events()/get_events_batch()가
    공유하는 내부 호출부.
    """
    all_entries = []
    offset = 0
    page_count = 0

    while True:
        page_count += 1
        if page_count > MAX_PAGINATION_PAGES:
            raise GfwApiError(
                f"Events pagination exceeded {MAX_PAGINATION_PAGES} pages — "
                "offset이 진행되지 않는 것으로 보입니다 (API 이상 동작 의심).",
                status_code=None,
                details={"vessel_ids": vessel_ids, "collected_so_far": len(all_entries)},
            )

        params = {
            "start-date": start_date,
            "end-date": end_date,
            "limit": EVENTS_PAGE_LIMIT,
            "offset": offset,
        }
        for i, vid in enumerate(vessel_ids):
            params[f"vessels[{i}]"] = vid
        for i, dataset in enumerate(EVENT_DATASETS):
            params[f"datasets[{i}]"] = dataset

        response = _request_with_retry(
            "GET", f"{BASE_URL}/events", params=params, headers=_auth_headers()
        )

        try:
            body = response.json()
        except ValueError:
            body = None

        if not response.ok:
            raise GfwApiError(
                "Global Fishing Watch Events API returned an error.",
                status_code=response.status_code,
                details=body,
            )

        entries = (body or {}).get("entries")
        if not isinstance(entries, list):
            raise GfwApiError(
                "Unexpected response from Global Fishing Watch Events API.",
                status_code=502,
                details="Missing entries array.",
            )

        all_entries.extend(entries)

        next_offset = (body or {}).get("nextOffset")
        if len(entries) < EVENTS_PAGE_LIMIT or next_offset is None:
            break
        offset = next_offset

    return all_entries


def _build_events_result(entries: list) -> dict:
    """원본 entry 리스트를 (원본에 가까운 events, 정규화된 normalizedEvents)로
    변환한다. get_events()/get_events_batch()가 공유하는 내부 변환부.
    """
    events = []
    for event_entry in entries:
        if not event_entry:
            continue
        event_details = {
            "fishing": event_entry.get("fishing"),
            "encounter": event_entry.get("encounter"),
            "gap": event_entry.get("gap"),
            "loitering": event_entry.get("loitering"),
            "port_visit": event_entry.get("port_visit"),
        }
        events.append(
            {
                "id": event_entry.get("id"),
                "type": event_entry.get("type"),
                "start": event_entry.get("start"),
                "end": event_entry.get("end"),
                "vesselId": (event_entry.get("vessel") or {}).get("id"),
                "vesselName": (event_entry.get("vessel") or {}).get("name"),
                "flag": (event_entry.get("vessel") or {}).get("flag"),
                "position": event_entry.get("position"),
                "eventDetails": event_details,
                "raw": event_entry,
            }
        )

    normalized_events = [_normalize_event(e) for e in entries if e]

    return {
        "count": len(events),
        "events": events,
        "normalizedEvents": normalized_events,
    }


def get_events(vessel_id: str, start_date: str, end_date: str) -> dict:
    """
    GFW Events API 호출: GET /v3/events (선박 1척).

    vessel_id 한 척에 대해 이벤트 타입 5종(FISHING/PORT_VISIT/ENCOUNTER/
    LOITERING/GAP)을 한 번에 요청하고, offset 기반 페이지네이션으로
    끝까지 순회해 start_date~end_date 기간의 전체 이벤트를 모아 반환한다.

    start_date, end_date는 "YYYY-MM-DD" 형식 문자열이며, GFW로 보내는
    URL 쿼리 파라미터는 kebab-case(start-date/end-date)여야 한다.

    선박 여러 척을 한꺼번에 수집할 때는 이 함수를 반복 호출하지 말고
    get_events_batch()를 쓴다 — 훨씬 적은 API 호출로 끝난다.
    """
    vessel_id = (vessel_id or "").strip()
    start_date = (start_date or "").strip()
    end_date = (end_date or "").strip()

    if not vessel_id:
        raise ValueError("vessel_id는 비어 있을 수 없습니다.")
    if not start_date or not end_date:
        raise ValueError("start_date와 end_date는 모두 필요합니다.")

    entries = _fetch_event_entries([vessel_id], start_date, end_date)
    result = _build_events_result(entries)
    result["resolvedVesselId"] = vessel_id
    return result


def get_events_batch(
    vessel_ids: list, start_date: str, end_date: str, max_workers: int = 1
) -> dict:
    """
    GFW Events API 호출: GET /v3/events (선박 여러 척, 배치).

    vessel_ids를 EVENTS_BATCH_SIZE(20)척씩 묶어서 호출한다 — 선박마다
    get_events()를 따로 부르는 것보다 호출 횟수가 최대 20배 적다
    (예: 32,105척 -> 1척씩이면 32,105회, 배치면 1,606회).

    max_workers > 1이면 배치들을 스레드로 동시에 처리한다 (기본값 1 =
    순차 처리). 대량 수집 시 시간을 더 줄이고 싶을 때만 올린다 — GFW
    쪽에 동시 요청 수 제한이 문서화돼 있지 않지만, 429가 뜨면 재시도
    로직이 자동으로 대응한다.

    반환값은 get_events()와 같은 형태이되, resolvedVesselId 대신
    resolvedVesselIds(요청한 vessel_ids 그대로)를 담는다.
    """
    vessel_ids = [v for v in (vessel_ids or []) if v]
    if not vessel_ids:
        raise ValueError("vessel_ids는 비어 있을 수 없습니다.")
    start_date = (start_date or "").strip()
    end_date = (end_date or "").strip()
    if not start_date or not end_date:
        raise ValueError("start_date와 end_date는 모두 필요합니다.")

    batches = [
        vessel_ids[i : i + EVENTS_BATCH_SIZE]
        for i in range(0, len(vessel_ids), EVENTS_BATCH_SIZE)
    ]

    all_entries = []
    if max_workers <= 1:
        for batch in batches:
            all_entries.extend(_fetch_event_entries(batch, start_date, end_date))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for entries in executor.map(
                lambda batch: _fetch_event_entries(batch, start_date, end_date), batches
            ):
                all_entries.extend(entries)

    result = _build_events_result(all_entries)
    result["resolvedVesselIds"] = vessel_ids
    return result
