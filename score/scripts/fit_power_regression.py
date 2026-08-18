"""
담당: 김준기, 오동규

TAC(할당승인정보) 원본의 실제 톤수-마력 쌍으로, score/axis_b_physics.py의
POWER_COEFF_A/B(GT -> 설치출력 kW 회귀식)를 직접 재적합(calibration)해본다.

배경: Coello et al. (2015) 논문 원문을 오동규가 직접 대조했는데
POWER_COEFF_A/B(5.46, 0.70)는 그 논문에 나오는 값이 아니었다(원문은 GT 회귀가
아니라 실제 선박 등록부 값을 씀) — Whall et al./Parker & Tyedmers/ICES/IMO
GHG Study도 뒤졌지만 출처를 못 찾았다. "어디서 왔는지 모르는 외국 문헌 값"을
계속 찾는 대신, 우리가 이미 갖고 있는 한국 어선 실측 데이터(TAC 원본의
선박 톤수/선박 마력)로 회귀식 자체를 다시 적합해서 "우리 모집단으로 검증한
계수"로 바꾼다.

물리식(axis_b_physics.py)은 P(kW) = a * GT^b 형태 -> log(P) = log(a) + b*log(GT)
로 선형화해서 최소자승 회귀.

⚠ 단위 주의: TAC "선박 마력"이 PS인지 HP인지 아직 공식 확인 전이다
(`data/TODO.md` "기관출력 단위 확인" 항목 참고). 1 PS ≈ 0.9863 HP로 차이가
작아(<1.4%) 회귀계수 자체의 크기(order of magnitude)에는 영향이 거의 없지만,
단위가 확정되기 전까지 여기서 나온 계수도 "PS 또는 HP 기준 잠정치"로만
취급해야 한다.

실행:
    python -m score.scripts.fit_power_regression
"""

import csv
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAC_CSV_PATH = PROJECT_ROOT / "data" / "raw" / "해양수산부_수산정보_TAC 할당 승인 정보_20251105.csv"

# kW로 환산하기 위한 마력 -> kW 계수. PS/HP 둘 다 대략 0.7355~0.7457(kW/hp)로
# 큰 차이가 없어 PS 기준(0.7355)을 잠정 사용 — 단위 확정 후 재검토.
KW_PER_HP = 0.7355


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        v = float(str(value).strip())
        return v if v > 0 else None
    except ValueError:
        return None


def load_tonnage_power_pairs(path: Path = TAC_CSV_PATH) -> list:
    """TAC 원본을 어선 번호 기준으로 중복 제거해 (톤수GT, 마력kW) 쌍 목록을 만든다.

    한 선박이 여러 할당(행)을 가질 수 있어 어선 번호로 먼저 dedupe한다
    (aggregate_tac_by_gear_type.py와 동일한 원칙).
    """
    by_vessel = load_tonnage_power_by_gear(path)
    return [pair for pairs in by_vessel.values() for pair in pairs]


def load_tonnage_power_by_gear(path: Path = TAC_CSV_PATH) -> dict:
    """TAC 원본을 "할당 어업 종류 명"(19개 국내 어업종) 기준으로 나눠
    {어업종: [(톤수GT, 마력kW), ...]}를 만든다. 어선 번호로 먼저 dedupe —
    단, 한 선박이 서로 다른 어업종으로 여러 번 잡히면(복수 허가) 어업종별로는
    별도 표본으로 남긴다(같은 어업종 안에서만 dedupe).
    """
    seen_per_gear = {}
    with open(path, encoding="cp949", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vessel_no = (row.get("어선 번호") or "").strip()
            gear = (row.get("할당 어업 종류 명") or "").strip()
            if not vessel_no or not gear:
                continue
            tonnage = _to_float(row.get("선박 톤수"))
            power_hp = _to_float(row.get("선박 마력"))
            if tonnage is None or power_hp is None:
                continue
            seen_per_gear.setdefault(gear, {})[vessel_no] = (tonnage, power_hp * KW_PER_HP)

    return {gear: list(vessels.values()) for gear, vessels in seen_per_gear.items()}


def fit_power_law(pairs: list) -> dict:
    """log(P) = log(a) + b*log(GT) 최소자승 회귀. (a, b, R^2, n) 반환."""
    tonnages = np.array([t for t, _ in pairs])
    powers_kw = np.array([p for _, p in pairs])

    log_tonnage = np.log(tonnages)
    log_power = np.log(powers_kw)

    b, log_a = np.polyfit(log_tonnage, log_power, 1)
    a = np.exp(log_a)

    predicted = log_a + b * log_tonnage
    residuals = log_power - predicted
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((log_power - np.mean(log_power)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return {"a": float(a), "b": float(b), "r_squared": float(r_squared), "n": len(pairs)}


def main() -> None:
    pairs = load_tonnage_power_pairs()
    print(f"[1/2] TAC 원본에서 톤수-마력 쌍 {len(pairs):,}건 확보 (어선 번호 기준 중복제거)")

    fit = fit_power_law(pairs)
    print("\n[2/2] 회귀 결과: P(kW) = a * GT^b")
    print(f"  a = {fit['a']:.4f}")
    print(f"  b = {fit['b']:.4f}")
    print(f"  R^2 = {fit['r_squared']:.4f}  (표본 {fit['n']:,}건)")

    print("\n=== 현재 axis_b_physics.py 값과 비교 ===")
    print("  POWER_COEFF_A = 5.4600 (Coello 원문에 없는 출처불명 값)")
    print("  POWER_COEFF_B = 0.7000 (Coello 원문에 없는 출처불명 값)")
    print(f"  실측 재적합값 = a={fit['a']:.4f}, b={fit['b']:.4f}")

    # 참고용: 대표 톤수 몇 개에서 기존 값과 실측 재적합값의 추정출력이 얼마나
    # 다른지 보여준다.
    print("\n=== 톤수별 추정 설치출력(kW) 비교 ===")
    for gt in (10, 30, 50, 100, 200):
        old_kw = 5.46 * (gt**0.70)
        new_kw = fit["a"] * (gt ** fit["b"])
        print(f"  GT={gt:>4}: 기존값 {old_kw:7.1f}kW  vs  실측재적합 {new_kw:7.1f}kW  "
              f"(비율 {new_kw / old_kw:.2f}x)")

    print("\n=== 어업종(할당 어업 종류 명)별 재회귀 — 톤수 하나로 부족했던 설명력이 나아지는지 ===")
    by_gear = load_tonnage_power_by_gear()
    MIN_SAMPLE_FOR_FIT = 20
    results_by_gear = []
    for gear, pairs in sorted(by_gear.items(), key=lambda kv: -len(kv[1])):
        if len(pairs) < MIN_SAMPLE_FOR_FIT:
            continue
        gear_fit = fit_power_law(pairs)
        results_by_gear.append((gear, gear_fit))

    print(f"{'어업종':<16} {'표본':>6} {'a':>10} {'b':>8} {'R^2':>8}")
    for gear, gear_fit in results_by_gear:
        print(f"{gear:<16} {gear_fit['n']:>6} {gear_fit['a']:>10.2f} {gear_fit['b']:>8.3f} {gear_fit['r_squared']:>8.3f}")

    skipped = sum(len(pairs) for gear, pairs in by_gear.items() if len(pairs) < MIN_SAMPLE_FOR_FIT)
    print(f"\n(표본 {MIN_SAMPLE_FOR_FIT}척 미만이라 회귀 건너뛴 어업종의 선박 수 합계: {skipped}척)")

    overall_r2 = fit["r_squared"]
    better = sum(1 for _, gf in results_by_gear if gf["r_squared"] > overall_r2)
    print(f"\n전체 통합 회귀 R^2={overall_r2:.3f} 대비, 어업종별 회귀 중 {better}/{len(results_by_gear)}개가 R^2 더 높음")


if __name__ == "__main__":
    main()
