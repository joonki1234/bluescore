"""
담당: 김준기, 오동규

해양수산부 AIS 위치정보 통계(`data/ais_location_stats_loader.py`, 김태윤 로더)를
A축 혼잡가중압력의 "기준값"으로 실제로 쓸 수 있게 가공한다.

배경 (`score/TODO.md` 참고): 이 통계는 2019-10-01~2020-03-31 기간뿐인데,
A축 산출에 쓰는 GFW 이벤트는 2026년(그리고 data_new/는 2026-04~08월)이라
(해구, 날짜, 시간) 키로는 연도는 물론 월도 안 겹쳐서 직접 조회가 불가능하다
(`build_vessel_count_index()`가 만드는 인덱스가 정확히 이 문제에 부딪힌다).

해결: 연도뿐 아니라 월도 버리고 **(해구, 시간대)** 평균 통행량으로 집계한다 —
"이 해역은 보통 이 시간대에 이 정도 붐빈다"는 시간대 패턴만 쓴다(요일·계절
패턴까지는 표본이 6개월치뿐이라 무리해서 우기지 않는다). 공간 조인은 AIS
"해구"(사각 격자, 실측 0.5도 x 0.5도)와 GFW 이벤트 위경도 사이를 직접
포함관계로 잇는다 — axis_a_pressure.py의 GRID_CELL_SIZE_DEG(0.1도)와는
격자 크기·목적이 다른 별도 체계다.

이 모듈은 "기준값을 실제로 조회 가능한 형태로 만드는 것"까지만 한다.
axis_a_pressure.py의 congestion_density_raw 계산식 자체를 이 기준값으로
보정할지·어떻게 섞을지는 아직 검증 전이라(신뢰구간·이상치 처리 등) 여기서
강제로 결합하지 않는다 — 다음 단계로 남겨둔다.
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
