"""개선 시뮬레이터의 트레이드오프 계수를 물리식과 거리 근사로 계산한다.

B축 계수는 속도의 3제곱 법칙을 사용하므로 선박별 톤수와 현재 속도에 따라
계산해야 한다. A축 raw 변화량은 구할 수 있지만 점수 변환에는 유사군 분포가
필요하다. 속도와 A축 압력의 관계식은 아직 없어 별도 계수를 만들지 않는다.
"""

from score.axis_a_pressure import GRID_CELL_SIZE_DEG, revisit_pressure_from_interval
from score.axis_b_physics import DEFAULT_DESIGN_SPEED_KN, estimate_fuel_consumption

# ui/adapter.py와 맞춘 B축 1점당 기대 대비 연료 %p 잠정값.
FUEL_PERCENT_PER_AXIS_B_POINT = 0.55

# 인접 8칸을 벗어나는 이동을 재방문 1스텝 감소로 간주한 잠정값.
REVISIT_STEP_GRID_HOPS = 2.0

# 대표 조업(가동) 시간(h) — 이벤트 1건 평균 지속시간 근사. 실측 평균으로 교체 가능.
DEFAULT_OPERATING_HOURS = 5.0

KM_PER_DEGREE_LATITUDE = 111.32  # 위도 1도의 거리(km), 지구 반경 기준 상수
KM_PER_KNOT_HOUR = 1.852  # 1노트 = 시속 1.852km


def axis_b_points_per_knot(
    tonnage_gt: float,
    current_speed_kn: float,
    design_speed_kn: float = DEFAULT_DESIGN_SPEED_KN,
    operating_hours: float = DEFAULT_OPERATING_HOURS,
    fuel_percent_per_axis_b_point: float = FUEL_PERCENT_PER_AXIS_B_POINT,
) -> float:
    """1노트 감속 시 B축 점수 변화를 속도의 3제곱 관계로 계산한다."""
    if current_speed_kn <= 1.0:
        raise ValueError("current_speed_kn은 1보다 커야 1노트 감속을 계산할 수 있습니다.")
    baseline_fuel = estimate_fuel_consumption(tonnage_gt, current_speed_kn, operating_hours, design_speed_kn)
    reduced_fuel = estimate_fuel_consumption(
        tonnage_gt, current_speed_kn - 1.0, operating_hours, design_speed_kn
    )
    fuel_percent_saved = (baseline_fuel - reduced_fuel) / baseline_fuel * 100
    return round(fuel_percent_saved / fuel_percent_per_axis_b_point, 2)


def axis_b_points_per_revisit_step(
    tonnage_gt: float,
    current_speed_kn: float,
    design_speed_kn: float = DEFAULT_DESIGN_SPEED_KN,
    operating_hours: float = DEFAULT_OPERATING_HOURS,
    grid_cell_size_deg: float = GRID_CELL_SIZE_DEG,
    revisit_step_grid_hops: float = REVISIT_STEP_GRID_HOPS,
    fuel_percent_per_axis_b_point: float = FUEL_PERCENT_PER_AXIS_B_POINT,
) -> float:
    """
    재방문을 1회 줄이는 대신 다른 어장으로 옮길 때, 그 이동거리(격자 크기 기반
    근사)만큼 추가로 드는 연료를 B축 점수 하락폭으로 환산한다.
    """
    baseline_fuel = estimate_fuel_consumption(tonnage_gt, current_speed_kn, operating_hours, design_speed_kn)
    extra_distance_km = grid_cell_size_deg * revisit_step_grid_hops * KM_PER_DEGREE_LATITUDE
    extra_hours = extra_distance_km / (current_speed_kn * KM_PER_KNOT_HOUR)
    extra_fuel = estimate_fuel_consumption(tonnage_gt, current_speed_kn, extra_hours, design_speed_kn)
    fuel_percent_extra = extra_fuel / baseline_fuel * 100
    return round(fuel_percent_extra / fuel_percent_per_axis_b_point, 2)


def axis_a_pressure_raw_delta_for_revisit_step(period_hours: float, revisit_count: int) -> float:
    """
    재방문 횟수를 1회 줄였을 때 revisit_interval_raw(자원 압력)가 얼마나
    줄어드는지 계산한다. 평가 기간(period_hours) 동안 재방문이 균등한 간격으로
    일어난다고 가정한다.

    주의: 반환값은 "점수"가 아니라 raw 압력값 변화량이다. score_assembly의
    백분위 변환은 유사 선박군 전체 분포가 있어야 계산되므로, 이 값만으로
    최종 점수 변화폭을 구할 수는 없다 — 방향과 상대적 크기 참고용이다.
    """
    if revisit_count <= 1:
        raise ValueError("revisit_count는 1보다 커야 1회 감소를 계산할 수 있습니다.")
    if period_hours <= 0:
        raise ValueError("period_hours는 0보다 커야 합니다.")
    interval_before = period_hours / revisit_count
    interval_after = period_hours / (revisit_count - 1)
    pressure_before = revisit_pressure_from_interval(interval_before)
    pressure_after = revisit_pressure_from_interval(interval_after)
    return round(pressure_before - pressure_after, 4)
