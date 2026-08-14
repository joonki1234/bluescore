"""
담당: 김준기, 오동규

ui/adapter.py의 "개선 시뮬레이터" 트레이드오프 계수를, 추측이 아니라 이미 있는
물리식/거리 근사에서 실제로 끌어낸다.

배경: `ui/adapter.py`에 있던 4개 계수(AXIS_A_GAIN_PER_REVISIT_STEP,
AXIS_B_COST_PER_REVISIT_STEP, AXIS_B_GAIN_PER_KNOT, AXIS_A_COST_PER_KNOT)는
전부 "근거 없는 잠정값"이라고 표시돼 있었다(2026-08-14, `TODO(score/ 김준기·
오동규)` 주석). 이 중 B축 관련 두 개는 `axis_b_physics.py`의 Coello et al.
(2015) 연료식이 연속함수(속도의 3제곱 법칙)이므로 차분으로 실제 값을 구할 수
있다 — 아래 `axis_b_points_per_knot`, `axis_b_points_per_revisit_step`.

**중요한 발견**: 실제로 계산해보면 속도 1노트 감속의 효과가 원래 잠정값(3.2점)
보다 훨씬 크고(현재 속도에 따라 26~77점, 아래 함수 docstring 예시 참고), 게다가
고정 상수가 아니라 현재 속도에 크게 좌우된다(3제곱 법칙이라 느린 배일수록 1노트
감속 효과가 비율상 더 크다). 즉 "선박마다 같은 상수 1개"로 근사하는 지금
`ui/adapter.py`의 설계 자체가 이 물리식과 잘 안 맞는다 — 상수를 새 숫자로
바꾸는 것보다, 시뮬레이터가 선박별 톤수/속도로 이 함수를 그때그때 호출하는
쪽이 맞을 수 있다. 이건 ui/ 담당(최지희)과 상의해서 배선을 바꿀지 정할 문제라
여기서는 함수만 준비해둔다.

A축 관련 두 개(AXIS_A_GAIN_PER_REVISIT_STEP, AXIS_A_COST_PER_KNOT)는 **같은
방식으로 못 끌어낸다**:
    - `axis_a_pressure_raw_delta_for_revisit_step`: 재방문 raw 압력값 자체의
      변화량은 `axis_a_pressure.py`의 공식으로 계산할 수 있다. 하지만 raw ->
      점수 변환(`score_assembly.raw_to_score`)은 유사 선박군 전체 분포를 알아야
      나오는 백분위라서, raw 변화량 하나만으로 "점수 몇 점"인지는 못 구한다.
      그래서 이 함수는 점수가 아니라 raw 변화량만 참고용으로 준다.
    - AXIS_A_COST_PER_KNOT(속도를 낮추면 해상 체류가 길어져 A축이 깎인다는
      가정)은 현재 코드베이스 어디에도 "속도 -> 재방문/체류 시간" 관계를 계산할
      공식이 없다. 근거 없이 숫자를 만드는 대신, 모델이 아직 없다는 사실 자체를
      명시한다. 실제 계수가 필요해질 때까지는 0에 가깝게 두는 쪽이, 근거 없는
      비영값보다 낫다.
"""

from score.axis_a_pressure import GRID_CELL_SIZE_DEG, revisit_pressure_from_interval
from score.axis_b_physics import DEFAULT_DESIGN_SPEED_KN, estimate_fuel_consumption

# ui/adapter.py의 FUEL_PERCENT_PER_AXIS_B_POINT와 값을 맞춘 잠정값 —
# "B축 1점당 기대 대비 연료 %p" 환산 비율. 이 비율 자체도 팀 확정 전 잠정값이다.
FUEL_PERCENT_PER_AXIS_B_POINT = 0.55

# "재방문 1스텝 감소"를 몇 개 격자를 벗어난 이동으로 볼지 — 잠정 가정.
# axis_a_pressure.ADJACENT_GRID_CHEBYSHEV_DISTANCE(1, 인접 8칸까지는 "재방문"으로
# 침)를 벗어나는 이동으로 보고 2칸으로 잡았다. 실측 근거는 없어 팀 확인 필요.
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
    """
    속도를 현재보다 1노트 낮췄을 때 B축 점수가 얼마나 오르는지, Coello 물리식의
    실제 3제곱 관계(추력 ~ 속도^3)에서 차분으로 구한다.

    고정 상수가 아니라 tonnage_gt/current_speed_kn에 따라 값이 달라진다 —
    예: tonnage_gt=50, operating_hours=5로 계산하면 current_speed_kn=8일 때
    약 60점, 20일 때 약 26점이 나온다(느린 배일수록 1노트 감속의 상대적
    효과가 크다).
    """
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
