"""
담당: 김준기, 오동규

A축(자원 압력) 지표 산출 — 동일·인접 격자 내 조업 이벤트 재방문 간격과
조업 이벤트 밀도 기반 혼잡가중압력을 계산한다.

참고: BlueScore 프로젝트 기획서(2026-08-11) 4번 "문제 해결 방안" -
① BlueScore 산출 - A축(자원 압력, 가중치 65%):
    "동일·인접 격자 내 조업 이벤트 발생 간격(같은 해역을 얼마나 짧은 주기로
    반복 조업하는가) + 조업 이벤트 밀도 기반 혼잡 가중 압력(이미 조업이
    집중된 해역에 추가적인 압력을 가하는가)"

산출 절차:
    1. 각 조업 이벤트의 위경도를 고정 크기 격자(grid cell)로 매핑한다.
    2. 재방문간격: 선박별로, 동일/인접(체비쇼프 거리 1 이내) 격자에서
       발생한 직전 이벤트와의 시간 간격을 구하고 평균낸다. 간격이 짧을수록
       압력이 높다는 방향으로 점수화한다(반비례 변환).
    3. 혼잡가중압력: 전체 이벤트를 격자별로 집계해 밀도(이벤트 수)를 구하고,
       선박이 조업한 격자들의 평균 밀도를 구한다.
    4. 두 raw 값을 선박 단위로 집계해 반환한다.

주의:
    - 이 모듈은 유사 선박군 내 백분위 정규화 이전의 원값(raw value) 산출까지만
      담당한다. 절대 점수가 아니며, 점수조립 단계에서 유사 선박군 내 상대값으로
      다시 정규화되어야 한다.
    - 격자 크기(GRID_CELL_SIZE_DEG), 재방문압력 변환 계수, 두 구성요소 결합
      가중치는 전부 팀에서 아직 확정하지 않은 잠정값이며 검증 후 교체해야 한다.
      두 구성요소는 스케일이 서로 다르므로(revisit_pressure_raw는 시간 기반
      반비례 값, congestion_density_raw는 이벤트 개수), 결합 raw 값
      (axis_a_pressure_raw)을 그대로 쓰기보다 점수조립 단계에서 각 raw 값을
      그룹 내 백분위로 개별 정규화한 뒤 합치는 방식으로 대체될 수 있다.
    - 혼잡가중압력은 "자원이 실제로 풍부해서 몰린 경우"와 "단순히 접근이 편한
      지형이라 몰린 경우"를 구분하지 못한다 (기획서 리스크 ⑥번). 추후 CPUE 등
      자원 밀도 대리지표로 보정이 필요하다.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
from shapely.geometry import Point

# 격자 한 변의 크기 (도 단위, 위경도 기준) — 잠정값, 검증 필요
GRID_CELL_SIZE_DEG = 0.05

# "인접 격자"로 볼 체비쇼프 거리(칸 수). 1이면 자기 자신 + 상하좌우/대각선 8방향
ADJACENT_GRID_CHEBYSHEV_DISTANCE = 1

# 재방문간격(시간) -> 압력 점수 변환식의 파라미터.
#   revisit_pressure = REVISIT_PRESSURE_SCALE_HOURS / (interval_hours + REVISIT_INTERVAL_EPSILON_HOURS)
# interval이 REVISIT_PRESSURE_SCALE_HOURS(시간)일 때 압력이 대략 1.0이 되도록
# 스케일링한 잠정값. 0시간 나눗셈 방지를 위해 EPSILON을 더한다.
REVISIT_PRESSURE_SCALE_HOURS = 24.0
REVISIT_INTERVAL_EPSILON_HOURS = 1.0

# A축 raw 값 결합 시 재방문압력/혼잡압력 가중치 — 잠정값
AXIS_A_REVISIT_WEIGHT = 0.5
AXIS_A_CONGESTION_WEIGHT = 0.5

GridCell = Tuple[int, int]


@dataclass
class SkippedEvent:
    """좌표/시각 결측 등으로 계산에서 제외된 이벤트."""

    event_id: Optional[str]
    reason: str


@dataclass
class VesselAxisAResult:
    """선박 한 척에 대한 A축 raw 산출 결과."""

    vessel_id: str
    used_event_count: int
    skipped_events: List[SkippedEvent] = field(default_factory=list)
    avg_revisit_interval_hours: Optional[float] = None
    revisit_pressure_raw: float = 0.0
    congestion_density_raw: float = 0.0
    axis_a_pressure_raw: float = 0.0


def _parse_start_datetime(event: dict) -> Optional[datetime]:
    start = event.get("start")
    if not start:
        return None
    try:
        return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None


def _grid_cell_for_point(latitude: float, longitude: float, cell_size_deg: float) -> GridCell:
    """위경도를 (row, col) 격자 인덱스로 변환."""
    return (int(latitude // cell_size_deg), int(longitude // cell_size_deg))


def _neighbor_cells(
    cell: GridCell, chebyshev_distance: int = ADJACENT_GRID_CHEBYSHEV_DISTANCE
) -> List[GridCell]:
    """주어진 격자와 그 인접 격자(자기 자신 포함) 목록."""
    row, col = cell
    d = chebyshev_distance
    return [(row + dr, col + dc) for dr in range(-d, d + 1) for dc in range(-d, d + 1)]


def _prepare_events(
    events: List[dict], cell_size_deg: float
) -> Tuple[gpd.GeoDataFrame, Dict[str, List[SkippedEvent]]]:
    """
    이벤트 리스트를 (유효 이벤트를 담은 GeoDataFrame, 선박별 스킵 이벤트 목록)으로 분리한다.

    geopandas.GeoDataFrame으로 좌표를 담아 격자 인덱스(gridCell 컬럼)를 계산한다.
    """
    valid_rows = []
    skipped: Dict[str, List[SkippedEvent]] = {}

    for event in events:
        vessel_id = event.get("vesselId")
        lat = event.get("latitude")
        lon = event.get("longitude")
        start_dt = _parse_start_datetime(event)

        reason = None
        if lat is None or lon is None:
            reason = "missing_coordinates"
        elif start_dt is None:
            reason = "missing_or_invalid_start"

        if reason:
            skipped.setdefault(vessel_id, []).append(
                SkippedEvent(event_id=event.get("eventId"), reason=reason)
            )
            continue

        valid_rows.append(
            {
                "eventId": event.get("eventId"),
                "vesselId": vessel_id,
                "startDatetime": start_dt,
                "geometry": Point(lon, lat),
            }
        )

    if not valid_rows:
        empty = gpd.GeoDataFrame(columns=["eventId", "vesselId", "startDatetime", "geometry", "gridCell"])
        return empty, skipped

    gdf = gpd.GeoDataFrame(valid_rows, geometry="geometry", crs="EPSG:4326")
    gdf["gridCell"] = [_grid_cell_for_point(geom.y, geom.x, cell_size_deg) for geom in gdf.geometry]
    return gdf, skipped


def _compute_revisit_intervals_hours(vessel_events_sorted: List[dict]) -> List[float]:
    """
    선박 한 척의 시간순 정렬된 이벤트들에 대해, 동일/인접 격자에서의 직전
    방문과의 시간 간격(시간 단위) 목록을 반환한다.

    vessel_events_sorted: [{"startDatetime": datetime, "gridCell": (row, col)}, ...]
        (startDatetime 오름차순으로 정렬되어 있어야 한다)
    """
    last_visit: Dict[GridCell, datetime] = {}
    intervals: List[float] = []

    for event in vessel_events_sorted:
        cell = event["gridCell"]
        start_dt = event["startDatetime"]

        candidate_times = [
            last_visit[neighbor] for neighbor in _neighbor_cells(cell) if neighbor in last_visit
        ]
        if candidate_times:
            most_recent = max(candidate_times)
            interval_hours = (start_dt - most_recent).total_seconds() / 3600.0
            if interval_hours >= 0:
                intervals.append(interval_hours)

        if cell not in last_visit or start_dt > last_visit[cell]:
            last_visit[cell] = start_dt

    return intervals


def revisit_pressure_from_interval(
    avg_interval_hours: Optional[float],
    scale_hours: float = REVISIT_PRESSURE_SCALE_HOURS,
    epsilon_hours: float = REVISIT_INTERVAL_EPSILON_HOURS,
) -> float:
    """평균 재방문간격(시간)을 압력 점수로 변환한다. 간격이 짧을수록 값이 크다.

    재방문 이력이 없으면(avg_interval_hours가 None) 0.0을 반환한다.
    """
    if avg_interval_hours is None:
        return 0.0
    if avg_interval_hours < 0:
        raise ValueError("avg_interval_hours는 0 이상이어야 합니다.")
    return scale_hours / (avg_interval_hours + epsilon_hours)


def compute_axis_a_pressure(
    events: List[dict],
    cell_size_deg: float = GRID_CELL_SIZE_DEG,
    revisit_weight: float = AXIS_A_REVISIT_WEIGHT,
    congestion_weight: float = AXIS_A_CONGESTION_WEIGHT,
) -> Dict[str, VesselAxisAResult]:
    """
    조업 이벤트 리스트로부터 선박별 A축(자원 압력) raw 값을 산출한다.

    Args:
        events: data/gfw_client.py의 normalized event 형태 딕셔너리 리스트
            (eventId, vesselId, start, latitude, longitude 등). 여러 선박의
            이벤트가 섞여 있어야 혼잡가중압력을 제대로 계산할 수 있다.
        cell_size_deg: 격자 한 변의 크기 (도 단위)
        revisit_weight: 결합 raw 값에서 재방문압력에 부여할 가중치
        congestion_weight: 결합 raw 값에서 혼잡압력에 부여할 가중치

    Returns:
        {vessel_id: VesselAxisAResult} 딕셔너리.
    """
    if cell_size_deg <= 0:
        raise ValueError("cell_size_deg는 0보다 커야 합니다.")

    gdf, skipped_by_vessel = _prepare_events(events, cell_size_deg)

    vessel_ids = set(gdf["vesselId"]) if not gdf.empty else set()
    vessel_ids |= set(skipped_by_vessel.keys())
    vessel_ids.discard(None)

    density_by_cell = Counter(gdf["gridCell"]) if not gdf.empty else Counter()

    results: Dict[str, VesselAxisAResult] = {}

    for vessel_id in vessel_ids:
        vessel_gdf = gdf[gdf["vesselId"] == vessel_id] if not gdf.empty else gdf
        vessel_events_sorted = sorted(
            (
                {"startDatetime": row.startDatetime, "gridCell": row.gridCell}
                for row in vessel_gdf.itertuples()
            ),
            key=lambda e: e["startDatetime"],
        )

        intervals = _compute_revisit_intervals_hours(vessel_events_sorted)
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        revisit_raw = revisit_pressure_from_interval(avg_interval)

        if vessel_events_sorted:
            congestion_raw = sum(
                density_by_cell[e["gridCell"]] for e in vessel_events_sorted
            ) / len(vessel_events_sorted)
        else:
            congestion_raw = 0.0

        combined_raw = revisit_weight * revisit_raw + congestion_weight * congestion_raw

        results[vessel_id] = VesselAxisAResult(
            vessel_id=vessel_id,
            used_event_count=len(vessel_events_sorted),
            skipped_events=skipped_by_vessel.get(vessel_id, []),
            avg_revisit_interval_hours=avg_interval,
            revisit_pressure_raw=revisit_raw,
            congestion_density_raw=congestion_raw,
            axis_a_pressure_raw=combined_raw,
        )

    return results
