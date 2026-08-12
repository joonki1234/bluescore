"""
Coello et al. (2015) 계수를 기반으로 한 물리식(bottom-up) 연료 소비 추정.

참고 문헌:
    Coello, J., Williams, I. D., Hudson, D. A., & Kemp, S. (2015).
    An AIS-based approach to calculate atmospheric emissions from the
    UK fishing fleet. Atmospheric Environment.

추정 절차:
    1. 톤수(GT)로부터 주기관 설계출력을 알로메트릭 회귀식으로 추정한다.
       P_installed(kW) = a * GT^b
    2. 실제 항해속도와 설계속도의 비율에 프로펠러 법칙(저항 ~ V^3)을 적용해
       속도에 따른 소요출력 비율을 구한다.
    3. 주기관 부하율(load factor)을 곱해 실제 사용 출력을 산정한다.
    4. 비연료소비율(SFOC)과 조업시간을 곱해 연료 소비량(kg)을 계산한다.

주의:
    POWER_COEFF_A, POWER_COEFF_B, SFOC_G_PER_KWH 는 Coello et al. (2015)의
    구조를 따른 대표값이며, 정확한 어법/선형별 계수는 논문 원문 표를
    확인하여 교체해야 한다.
"""

# 주기관 설계출력 추정식 P(kW) = a * GT^b 의 회귀계수 (Coello et al. 2015 방식, 대표값 — 검증 필요)
POWER_COEFF_A = 5.4600
POWER_COEFF_B = 0.7000

# 주기관 비연료소비율 (g/kWh), 중형 디젤 어선기관 대표값 — 검증 필요
SFOC_G_PER_KWH = 190.0

# 주기관 부하율 (고정값)
MAIN_ENGINE_LOAD_FACTOR = 0.75

# 프로펠러 법칙(속도-출력 3제곱 관계) 정규화를 위한 설계속도 기본값 (kn) — 선종에 맞게 조정 필요
DEFAULT_DESIGN_SPEED_KN = 10.0


def estimate_installed_power_kw(
    tonnage_gt: float,
    a: float = POWER_COEFF_A,
    b: float = POWER_COEFF_B,
) -> float:
    """톤수(GT) 기반 주기관 설계출력 추정: P(kW) = a * GT^b."""
    if tonnage_gt <= 0:
        raise ValueError("tonnage_gt는 0보다 커야 합니다.")
    return a * (tonnage_gt**b)


def estimate_fuel_consumption(
    tonnage_gt: float,
    speed_kn: float,
    operating_hours: float,
    design_speed_kn: float = DEFAULT_DESIGN_SPEED_KN,
    sfoc_g_per_kwh: float = SFOC_G_PER_KWH,
    load_factor: float = MAIN_ENGINE_LOAD_FACTOR,
) -> float:
    """
    Coello et al. (2015) 계수 기반 물리식 연료 소비 추정.

    Args:
        tonnage_gt: 총톤수 (GT)
        speed_kn: 항해속도 (kn)
        operating_hours: 조업(가동)시간 (h)
        design_speed_kn: 프로펠러 법칙 정규화용 설계속도 (kn)
        sfoc_g_per_kwh: 비연료소비율 (g/kWh)
        load_factor: 주기관 부하율 (기본 0.75)

    Returns:
        추정 연료 소비량 (kg)
    """
    if speed_kn < 0:
        raise ValueError("speed_kn은 0 이상이어야 합니다.")
    if operating_hours < 0:
        raise ValueError("operating_hours는 0 이상이어야 합니다.")
    if design_speed_kn <= 0:
        raise ValueError("design_speed_kn은 0보다 커야 합니다.")

    installed_power_kw = estimate_installed_power_kw(tonnage_gt)
    speed_load_ratio = (speed_kn / design_speed_kn) ** 3
    actual_power_kw = installed_power_kw * speed_load_ratio * load_factor

    fuel_consumption_kg = (actual_power_kw * sfoc_g_per_kwh * operating_hours) / 1000.0
    return fuel_consumption_kg
