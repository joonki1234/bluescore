"""
담당: 김태윤

Global Fishing Watch (GFW) API v3 클라이언트.

원본: ~/Downloads/bluescore-demo/server.js (Node.js/Express)의
/api/vessels/search, /api/events 라우트 로직을 requests 기반 Python으로 이식.

주의 (Events API 422 방지):
    GFW Events API에 보내는 요청 본문의 날짜 필드는 반드시 camelCase인
    startDate / endDate 여야 한다. 과거 버전에서 start_date / end_date
    (snake_case)로 보냈다가 GFW가 다음과 같이 422를 반환한 적이 있다.
        {"title": "property", "detail": "property start_date should not exist"}
        {"title": "property", "detail": "property end_date should not exist"}
    따라서 이 클라이언트는 항상 startDate / endDate 키만 사용한다.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

GFW_API_KEY = os.getenv("GFW_API_KEY")

BASE_URL = "https://gateway.api.globalfishingwatch.org/v3"
VESSEL_IDENTITY_DATASET = "public-global-vessel-identity:latest"
FISHING_EVENTS_DATASET = "public-global-fishing-events:latest"

REQUEST_TIMEOUT_SECONDS = 30


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

    lat = pos.get("lat", pos.get("latitude"))
    lon = pos.get("lon", pos.get("longitude"))

    coordinates = pos.get("coordinates")
    if (lat is None or lon is None) and isinstance(coordinates, list) and len(coordinates) >= 2:
        lon, lat = coordinates[0], coordinates[1]

    return {"latitude": _as_number(lat), "longitude": _as_number(lon)}


def _normalize_vessel(entry: dict) -> dict:
    """search_vessels 결과 엔트리를 내부 표준 형태로 정규화."""
    raw = entry.get("raw", entry) or {}
    registry_info_list = raw.get("registryInfo")
    self_reported_list = raw.get("selfReportedInfo")
    registry_info = registry_info_list[0] if isinstance(registry_info_list, list) and registry_info_list else None
    self_reported_info = self_reported_list[0] if isinstance(self_reported_list, list) and self_reported_list else None

    gfw_id = raw.get("id") or (registry_info or {}).get("id") or (self_reported_info or {}).get("id")
    ssvid = raw.get("ssvid") or (registry_info or {}).get("ssvid") or (self_reported_info or {}).get("ssvid")
    imo = raw.get("imo") or (registry_info or {}).get("imo") or (self_reported_info or {}).get("imo")
    name = (
        raw.get("shipname")
        or raw.get("nShipname")
        or raw.get("vesselName")
        or (self_reported_info or {}).get("shipname")
    )

    return {
        "vesselId": gfw_id,
        "mmsi": ssvid,
        "imo": imo,
        "name": name,
        "tonnage": None,
        "length": None,
        "width": None,
        "fishingType": None,
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
            from datetime import datetime

            s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            duration_hours = max(0.0, (e - s).total_seconds() / 3600)
        except ValueError:
            duration_hours = None

    fishing = raw.get("eventDetails", {}).get("fishing") if isinstance(raw.get("eventDetails"), dict) else None
    fishing = fishing or raw.get("fishing") or {}
    average_speed_knots = (
        (fishing or {}).get("averageSpeedKnots")
        if isinstance(fishing, dict)
        else None
    ) or raw.get("avg_speed")
    total_distance_km = (
        (fishing or {}).get("totalDistanceKm")
        if isinstance(fishing, dict)
        else None
    ) or raw.get("distance_km")

    regions = raw.get("regions") or {}
    mpa_related = bool(
        raw.get("mpa")
        or raw.get("protected_area")
        or raw.get("mpas")
        or raw.get("protectedAreas")
        or (isinstance(regions.get("mpa"), list) and len(regions.get("mpa")) > 0)
    )

    return {
        "eventId": raw.get("id"),
        "vesselId": (raw.get("vessel") or {}).get("id") or raw.get("vesselId"),
        "start": start,
        "end": end,
        "latitude": lat_lon["latitude"],
        "longitude": lat_lon["longitude"],
        "durationHours": duration_hours,
        "averageSpeedKnots": _as_number(average_speed_knots),
        "totalDistanceKm": _as_number(total_distance_km),
        "mpaRelated": mpa_related,
        "raw": raw,
    }


def search_vessels(query: str) -> list:
    """GFW Vessels Search API 호출: GET /v3/vessels/search."""
    query = (query or "").strip()
    if not query:
        raise ValueError("query는 비어 있을 수 없습니다.")

    response = requests.get(
        f"{BASE_URL}/vessels/search",
        params={"query": query, "datasets[0]": VESSEL_IDENTITY_DATASET},
        headers=_auth_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
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

    results = []
    for index, entry in enumerate(entries):
        if not entry:
            continue
        registry_info_list = entry.get("registryInfo")
        self_reported_list = entry.get("selfReportedInfo")
        registry_info = registry_info_list[0] if isinstance(registry_info_list, list) and registry_info_list else None
        self_reported_info = self_reported_list[0] if isinstance(self_reported_list, list) and self_reported_list else None

        def get_field(field_name):
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


def get_events(vessel_id: str, start_date: str, end_date: str, limit: int = 100, offset: int = 0) -> dict:
    """
    GFW Events API 호출: POST /v3/events.

    start_date, end_date는 "YYYY-MM-DD" 형식 문자열이며, GFW로 보내는 JSON
    본문에는 반드시 camelCase 키(startDate, endDate)로 실어 보낸다.
    """
    vessel_id = (vessel_id or "").strip()
    start_date = (start_date or "").strip()
    end_date = (end_date or "").strip()

    if not vessel_id:
        raise ValueError("vessel_id는 비어 있을 수 없습니다.")
    if not start_date or not end_date:
        raise ValueError("start_date와 end_date는 모두 필요합니다.")

    request_body = {
        "datasets": [FISHING_EVENTS_DATASET],
        "vessels": [vessel_id],
        "startDate": start_date,
        "endDate": end_date,
    }

    headers = _auth_headers()
    headers["Content-Type"] = "application/json"

    response = requests.post(
        f"{BASE_URL}/events",
        params={"limit": limit, "offset": offset},
        json=request_body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
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
        "resolvedVesselId": vessel_id,
        "normalizedEvents": normalized_events,
    }
