"""
담당: 김준기, 오동규

물리식(bottom-up) 연료 소비 추정.

참고 문헌:
    Coello, J., Williams, I. D., Hudson, D. A., & Kemp, S. (2015).
    An AIS-based approach to calculate atmospheric emissions from the
    UK fishing fleet. Atmospheric Environment.

2026-08-14 검증 결과 (오동규): 아래 세 상수 중 부하율 공식만 Coello 원문(같은
저자 박사논문 기준, Eq. 2.3, p.22: LF = 0.9 * (Vi/Vd)^3, Vi=순간속도,
Vd=설계속도, 0.9는 "설계속도는 주기관 최대연속정격의 90%에서 낸다"는 10%
해상마진 가정)에서 실제로 확인했다. 반면 POWER_COEFF_A/B(GT→설치출력 회귀식)와
SFOC_G_PER_KWH는 **Coello 논문에 없는 숫자**임을 확인했다 — 이 논문은 설치출력을
회귀식이 아니라 실제 영국 선박 등록부 값을 그대로 썼고, SFOC도 자체 수치를
제시하지 않고 Whall et al.(2002)/Trozzi et al.(2016) 등 외부 문헌을 인용하라고만
되어 있다. Whall et al.(2002), Parker & Tyedmers(2015) 리뷰, ICES(1980), IMO GHG
Study 등 유력 후보도 더 찾아봤지만 이 두 상수의 실제 출처는 이번 조사로는
확인하지 못했다 — 즉 지금 값(5.46 / 0.70 / 190.0)은 출처 불명의 대표값이다.
정확한 값이 필요해지면 원출처부터 다시 찾아야 한다.

2026-08-15 추가 확인: git blame으로 이 파일의 첫 커밋(00705245)까지 거슬러가봤는데,
그 시점부터 이미 지금과 같은 숫자·"검증 필요" 문구가 같이 있었다 — 나중에 출처가
누락된 게 아니라 처음부터 대표값으로 들어간 것이라 커밋 이력으로는 더 추적할 게
없다. 다만 `SFOC_G_PER_KWH=190.0`은 일반적인 중속 디젤 선박엔진의 SFOC 범위
(약 155~225 g/kWh)에는 들어가는 값이라 — 특정 논문에서 온 숫자는 아니지만 터무니
없는 값도 아니다. `POWER_COEFF_A/B`는 이런 정황조차 못 찾았다.

추정 절차:
    1. 톤수(GT)로부터 주기관 설계출력을 알로메트릭 회귀식으로 추정한다.
       P_installed(kW) = a * GT^b  ← a, b 출처 불명 (위 검증 결과 참고)
    2. 실제 항해속도와 설계속도의 비율에 프로펠러 법칙(저항 ~ V^3)과 해상마진을
       적용해 속도에 따른 소요출력 비율을 구한다 — Coello Eq. 2.3 확인됨.
    3. 비연료소비율(SFOC)과 조업시간을 곱해 연료 소비량(kg)을 계산한다.
       ← SFOC 수치 출처 불명 (위 검증 결과 참고)
"""

# 주기관 설계출력 추정식 P(kW) = a * GT^b 의 회귀계수 — 출처 불명의 대표값, 검증 필요
# (Coello et al. 2015 원문에는 없음 — 2026-08-14 확인, 위 모듈 독스트링 참고)
POWER_COEFF_A = 5.4600
POWER_COEFF_B = 0.7000

# 주기관 비연료소비율 (g/kWh) — 출처 불명의 대표값, 검증 필요
# (Coello et al. 2015 원문에는 없음 — 2026-08-14 확인, 위 모듈 독스트링 참고)
SFOC_G_PER_KWH = 190.0

# 해상마진(sea margin) — Coello et al. (2015, 저자 박사논문 Eq. 2.3, p.22)에서 확인:
# "설계속도는 주기관 최대연속정격(MCR)의 90%에서 낸다"는 가정. 부하율 공식
# LF = SEA_MARGIN_FACTOR * (speed/design_speed)^3 에 그대로 쓰인다.
SEA_MARGIN_FACTOR = 0.90

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
    sea_margin_factor: float = SEA_MARGIN_FACTOR,
) -> float:
    """
    물리식 연료 소비 추정.

    Args:
        tonnage_gt: 총톤수 (GT)
        speed_kn: 항해속도 (kn)
        operating_hours: 조업(가동)시간 (h)
        design_speed_kn: 프로펠러 법칙 정규화용 설계속도 (kn)
        sfoc_g_per_kwh: 비연료소비율 (g/kWh)
        sea_margin_factor: 해상마진 (기본 0.90, Coello Eq. 2.3 확인됨)

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
    load_factor = sea_margin_factor * (speed_kn / design_speed_kn) ** 3
    actual_power_kw = installed_power_kw * load_factor

    fuel_consumption_kg = (actual_power_kw * sfoc_g_per_kwh * operating_hours) / 1000.0
    return fuel_consumption_kg
