"""
담당: 김준기, 오동규

해양수산부 AIS 위치정보 통계를 A축 혼잡가중압력의 "기준값"으로 조회 가능하게
가공한다.

이 통계는 2019-10~2020-03 기간뿐이라 A축에 쓰는 2026년 GFW 이벤트와 연도·월이
겹치지 않는다 — 그래서 연도·월은 버리고 (해구, 시간대) 평균 통행량으로만
집계한다. 공간 조인은 AIS 해구(0.5도x0.5도 격자)와 GFW 좌표를 포함관계로
직접 잇는다 — axis_a_pressure.py의 GRID_CELL_SIZE_DEG(0.1도)와는 별개 체계다.
기준값을 congestion_density_raw에 어떻게 결합할지는 아직 미정.
"""

from typing import Dict, List, Optional, Tuple

from data.ais_location_stats_loader import build_grid_boundary_lookup

GridHourKey = Tuple[int, int]


def build_congestion_baseline_by_hour(rows: List[dict]) -> Dict[GridHourKey, float]:
    """(seaGridId, hour) -> 평균 척수 인덱스를 만든다. 날짜(연도·월)는 버린다."""
    sums: Dict[GridHourKey, float] = {}
    counts: Dict[GridHourKey, int] = {}

    for row in rows:
        key = (row["seaGridId"], row["hour"])
        count = row.get("vesselCount")
        if count is None:
            continue
        sums[key] = sums.get(key, 0.0) + count
        counts[key] = counts.get(key, 0) + 1

    return {key: sums[key] / counts[key] for key in sums}


def find_grid_for_point(
    latitude: float, longitude: float, boundary_lookup: Dict[int, dict]
) -> Optional[int]:
    """위경도가 어느 AIS 해구(사각 격자) 안에 들어가는지 찾는다.

    격자가 400개뿐이라 선형 탐색으로도 충분하다(실시간 대량 조회가 필요해지면
    공간 인덱스로 바꿀 것). topLeft가 북서쪽(위도 높음·경도 낮음), bottomRight가
    남동쪽이라고 가정한다(로더 docstring·실측 샘플과 일치).
    """
    for grid_id, boundary in boundary_lookup.items():
        top_left_lon = boundary["topLeftLon"]
        top_left_lat = boundary["topLeftLat"]
        bottom_right_lon = boundary["bottomRightLon"]
        bottom_right_lat = boundary["bottomRightLat"]
        if (
            top_left_lon <= longitude <= bottom_right_lon
            and bottom_right_lat <= latitude <= top_left_lat
        ):
            return grid_id
    return None


def congestion_baseline_for_point(
    latitude: float,
    longitude: float,
    hour: int,
    baseline_by_hour: Dict[GridHourKey, float],
    boundary_lookup: Dict[int, dict],
) -> Optional[float]:
    """위경도·시각(hour)에 대응하는 AIS 기준 혼잡도(평균 척수)를 조회한다.

    해당 위치가 AIS 격자 커버리지 밖이거나, 그 해구·시간대 표본이 없으면
    None을 반환한다(억지로 값을 만들지 않음 — "모르면 모른다" 원칙).
    """
    grid_id = find_grid_for_point(latitude, longitude, boundary_lookup)
    if grid_id is None:
        return None
    return baseline_by_hour.get((grid_id, hour))


__all__ = [
    "build_congestion_baseline_by_hour",
    "find_grid_for_point",
    "congestion_baseline_for_point",
    "build_grid_boundary_lookup",
]
