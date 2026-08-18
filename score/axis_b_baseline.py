"""
담당: 김준기, 오동규

B축(운항 효율) LightGBM 기준선 파이프라인 — "비슷한 조건이면 보통 이만큼
연료를 쓴다"는 기준선을 학습하고, 물리식 추정치(estimated proxy)와의 차이(잔차)를
B축 원값으로 산출한다.

참고: BlueScore 프로젝트 기획서(2026-08-11)
  - 4번 "문제 해결 방안" ① BlueScore 산출 - B축(운항 효율, 가중치 35%):
    "AI가 '어구·톤수·해역·계절이 이 조건이면 보통 연료를 이만큼 쓴다'는
    기준선을 학습하고, 실제 소비와의 차이를 점수화"
  - 7번 MVP 설계서: "B축 산출 - 물리식 연료·CO2 추정 → LightGBM 기준선 학습 → 잔차"
  - 8-3번 AI 모델: "LightGBM (기준선 회귀) - 입력: 선박 제원(톤수·길이), 어업종,
    해역, 계절, 해황(수온·풍속·유속), 이벤트별 평균속도·이동거리·지속시간 /
    출력: 기대 연료 소비량. 실제 - 기대 = 잔차가 B축 원값"

산출 절차:
    1. score/axis_b_physics.py의 estimate_fuel_consumption()으로 "추정(estimated
       proxy)" 연료소비량을 물리식으로 근사한다 (실측 연료 데이터가 없기 때문).
    2. LightGBM 회귀 모델이 선박 제원·어업종·해역·계절·해황·항해 특징으로부터
       "기대(기준선)" 연료소비량을 학습한다.
    3. 잔차 = 추정(물리식) - 기대(LightGBM) = B축 원값(raw value).
       잔차가 음수면(추정치보다 기대치가 큼) 기대보다 적게 썼다는 뜻으로,
       운항 효율이 좋다는 신호다.
    4. 이벤트 단위 잔차를 선박 단위로 평균내 반환한다.

주의:
    - 이 모듈은 유사 선박군 내 백분위 정규화 이전의 원값(raw value) 산출까지만
      담당한다. 점수조립 단계에서 유사 선박군 내 상대값/개선률로 다시
      정규화되어야 한다.
    - 별도의 학습/검증(holdout) 분리를 하지 않는다. 지금은 전체 데이터로 학습한
      기준선에 대해 잔차를 구하는 단순한 방식이며, 데이터 양이 늘어나면
      train/holdout 분리나 교차검증 도입을 검토해야 한다.
    - LightGBM 하이퍼파라미터(NUM_LEAVES, MIN_CHILD_SAMPLES 등)는 실데이터가
      없는 지금 단계에서 수십 건짜리 더미 데이터로도 학습이 되도록 낮게 잡은
      잠정값이다. 실데이터 확보 후 재튜닝이 필요하다.
    - 입력 피처(NUMERIC_FEATURE_COLUMNS, CATEGORICAL_FEATURE_COLUMNS)는 기획서에
      나열된 후보를 전부 반영한 것이며, 실제 어떤 피처를 쓸 수 있는지는
      데이터팀(김태윤) 확인 후 확정해야 한다.
    - [해결됨, 2026-08-18] estimated_fuel_kg는 실측 연료 데이터가 없어 물리식
      추정치로 대체한 값인데, 그 물리식이 정확히 tonnageGt/averageSpeedKnots/
      durationHours만의 매끈한 함수(잡음 없음)다. averageSpeedKnots를
      LightGBM 기준선 입력에도 그대로 두면, 모델이 "기대"를 사실상 그 물리식
      자체로 근사해버려 잔차(residual_raw)가 진짜 운항 효율 차이가 아니라
      LightGBM의 곡선 근사 오차(노이즈)에 가까워지는 문제가 있었다. (데모:
      톤수·속도만 다른 20척으로 확인한 잔차가 -21.8%~+8.2%로 뚜렷한 패턴 없이
      흩어짐 — 2026-08-13.)
      판단 기준: 기대치(baseline) 입력에는 "그 배가 어쩔 수 없이 처한 조건"만
      남기고, "그 배가 스스로 선택한 조업 방식"은 뺀다 — 그래야 그 선택의
      결과가 잔차에 남는다. tonnageGt(배 크기)·durationHours(조업에 걸리는
      시간, 어장 규모에 좌우됨)·해황·어업종·해역·계절은 조건이라 남기고,
      averageSpeedKnots(속도 선택)는 뺀다.
      **totalDistanceKm도 같이 빼야 한다** — totalDistanceKm ≈
      averageSpeedKnots × durationHours × 1.852라서, durationHours가 이미
      피처에 있는 상태로 totalDistanceKm만 남기면 속도가 (거리 ÷ 기간)으로
      뒷문으로 다시 들어온다. 둘 다 NUMERIC_FEATURE_COLUMNS에서 뺐다.
      기획서 원문은 평균속도도 입력에 포함하도록 명시하지만, 물리식 잔차
      구조상 그러면 순환성이 생겨 신호가 노이즈가 되므로 이 변경이 맞다는
      결론(오동규 확인, 2026-08-18). `test_axis_b_baseline.py`의
      `TestResidualCapturesSpeedSignal`이 조건이 같고 속도만 다른 선박들에서
      잔차가 실제로 속도와 함께 단조증가하는지 검증한다.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
from lightgbm import LGBMRegressor

from score.axis_b_physics import estimate_fuel_consumption

# LightGBM 하이퍼파라미터 — 잠정값. 실데이터 확보 전까지는 소규모(수십 건)
# 더미 데이터로도 학습이 되도록 num_leaves/min_child_samples를 낮게 잡았다.
# 실데이터가 들어오면 재튜닝 필요.
LGBM_N_ESTIMATORS = 50
LGBM_LEARNING_RATE = 0.1
LGBM_NUM_LEAVES = 7
LGBM_MIN_CHILD_SAMPLES = 2
LGBM_RANDOM_STATE = 42
LGBM_VERBOSITY = -1

# LightGBM 입력 피처 컬럼. 기획서 원문 후보 중 averageSpeedKnots/totalDistanceKm은
# 뺐다 — 물리식 추정치(estimated_fuel_kg)도 이 값들의 함수라, 기준선 입력에
# 그대로 두면 "기대"가 물리식을 베껴버려 잔차가 노이즈가 된다. 모듈 docstring의
# [해결됨, 2026-08-18] 항목 참고.
NUMERIC_FEATURE_COLUMNS = [
    "tonnageGt",
    "seaSurfaceTempC",
    "windSpeedMs",
    "currentSpeedMs",
    "durationHours",
]
CATEGORICAL_FEATURE_COLUMNS = ["gearType", "seaArea", "season"]

# "추정(estimated proxy) 연료소비량"을 물리식으로 계산하는 데 필수인 필드.
# 하나라도 없으면(None) 해당 행은 학습/추론에서 제외한다.
REQUIRED_PHYSICS_FIELDS = ["tonnageGt", "averageSpeedKnots", "durationHours"]


@dataclass
class SkippedRow:
    """필수 피처 결측 또는 물리식 계산 실패로 제외된 행."""

    vessel_id: Optional[str]
    reason: str


@dataclass
class VesselAxisBResult:
    """선박 한 척에 대한 B축 raw 산출 결과 (해당 선박의 유효 이벤트 평균)."""

    vessel_id: str
    used_row_count: int
    skipped_rows: List[SkippedRow] = field(default_factory=list)
    estimated_fuel_kg: float = 0.0
    expected_fuel_kg: float = 0.0
    residual_raw: float = 0.0


def compute_estimated_fuel_kg(row: dict) -> float:
    """score/axis_b_physics.py의 물리식을 재사용해 '추정(estimated proxy)' 연료소비량(kg)을 구한다.

    row에는 tonnageGt, averageSpeedKnots, durationHours가 모두 있어야 한다.
    """
    return estimate_fuel_consumption(
        tonnage_gt=row["tonnageGt"],
        speed_kn=row["averageSpeedKnots"],
        operating_hours=row["durationHours"],
    )


def compute_residual(estimated_fuel_kg: float, expected_fuel_kg: float) -> float:
    """B축 원값(잔차) = 추정(물리식) - 기대(LightGBM 기준선)."""
    return estimated_fuel_kg - expected_fuel_kg


def _prepare_valid_rows(rows: List[dict]) -> Tuple[List[Tuple[dict, float]], Dict[str, List[SkippedRow]]]:
    """
    행 리스트를 (유효 행+추정연료 튜플 목록, 선박별 스킵 행 목록)으로 분리한다.

    필수 피처가 없거나 물리식 계산이 실패(ValueError)하면 스킵 사유를 명시적으로 남긴다.
    """
    valid_entries: List[Tuple[dict, float]] = []
    skipped: Dict[str, List[SkippedRow]] = {}

    for row in rows:
        vessel_id = row.get("vesselId")
        missing = [f for f in REQUIRED_PHYSICS_FIELDS if row.get(f) is None]

        if missing:
            skipped.setdefault(vessel_id, []).append(
                SkippedRow(vessel_id=vessel_id, reason=f"missing_required_feature:{','.join(missing)}")
            )
            continue

        try:
            estimated_fuel_kg = compute_estimated_fuel_kg(row)
        except ValueError as exc:
            skipped.setdefault(vessel_id, []).append(
                SkippedRow(vessel_id=vessel_id, reason=f"invalid_physics_input:{exc}")
            )
            continue

        valid_entries.append((row, estimated_fuel_kg))

    return valid_entries, skipped


def _rows_to_feature_dataframe(rows: List[dict]) -> pd.DataFrame:
    """행 리스트를 LightGBM 입력용 DataFrame으로 변환한다 (범주형 컬럼은 category dtype)."""
    feature_columns = NUMERIC_FEATURE_COLUMNS + CATEGORICAL_FEATURE_COLUMNS
    df = pd.DataFrame(rows)

    for column in feature_columns:
        if column not in df.columns:
            df[column] = None

    df = df[feature_columns].copy()
    for column in CATEGORICAL_FEATURE_COLUMNS:
        df[column] = df[column].astype("category")

    return df


def fit_baseline_model(
    rows: List[dict],
    n_estimators: int = LGBM_N_ESTIMATORS,
    learning_rate: float = LGBM_LEARNING_RATE,
    num_leaves: int = LGBM_NUM_LEAVES,
    min_child_samples: int = LGBM_MIN_CHILD_SAMPLES,
    random_state: int = LGBM_RANDOM_STATE,
) -> Tuple[LGBMRegressor, List[SkippedRow]]:
    """
    행 리스트로부터 LightGBM 기준선 회귀 모델을 학습한다.

    타깃(추정 연료소비량)은 각 행의 물리식 추정치(compute_estimated_fuel_kg)로 계산한다.
    필수 피처가 없는 행은 학습에서 제외되고 skipped 목록으로 반환된다.

    Returns:
        (학습된 모델, 스킵된 행 목록)
    """
    valid_entries, skipped_by_vessel = _prepare_valid_rows(rows)
    if not valid_entries:
        raise ValueError("학습 가능한 유효 데이터가 없습니다 (모든 행이 스킵되었습니다).")

    feature_df = _rows_to_feature_dataframe([row for row, _ in valid_entries])
    target = [estimated_fuel_kg for _, estimated_fuel_kg in valid_entries]

    model = LGBMRegressor(
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        min_child_samples=min_child_samples,
        random_state=random_state,
        verbosity=LGBM_VERBOSITY,
    )
    model.fit(feature_df, target, categorical_feature=CATEGORICAL_FEATURE_COLUMNS)

    skipped_flat = [skipped_row for rows_for_vessel in skipped_by_vessel.values() for skipped_row in rows_for_vessel]
    return model, skipped_flat


def predict_expected_fuel_kg(model: LGBMRegressor, rows: List[dict]) -> List[float]:
    """학습된 모델로 행 리스트에 대한 기대 연료소비량(kg)을 예측한다."""
    feature_df = _rows_to_feature_dataframe(rows)
    return list(model.predict(feature_df))


def compute_axis_b_efficiency(rows: List[dict], model: LGBMRegressor) -> Dict[str, VesselAxisBResult]:
    """
    행 리스트 + 학습된 기준선 모델로부터 선박별 B축(운항 효율) raw 값을 산출한다.

    추정(물리식) 연료소비량 계산 -> LightGBM 기대 연료소비량 예측 -> 잔차 계산까지
    한 번에 처리하고, 같은 선박의 여러 이벤트는 평균내 선박 단위 결과로 반환한다.

    Args:
        rows: 이벤트+선박 특징 딕셔너리 리스트 (vesselId, tonnageGt,
            averageSpeedKnots, durationHours 등). fit_baseline_model()에 쓰인
            학습 데이터와 같은 컬럼 구조를 따라야 한다.
        model: fit_baseline_model()로 학습된 LGBMRegressor.

    Returns:
        {vessel_id: VesselAxisBResult} 딕셔너리.
    """
    valid_entries, skipped_by_vessel = _prepare_valid_rows(rows)

    vessel_ids = {row.get("vesselId") for row, _ in valid_entries}
    vessel_ids |= set(skipped_by_vessel.keys())
    vessel_ids.discard(None)

    if valid_entries:
        expected_values = predict_expected_fuel_kg(model, [row for row, _ in valid_entries])
    else:
        expected_values = []

    per_vessel_pairs: Dict[str, List[Tuple[float, float]]] = {}
    for (row, estimated_fuel_kg), expected_fuel_kg in zip(valid_entries, expected_values):
        vessel_id = row.get("vesselId")
        per_vessel_pairs.setdefault(vessel_id, []).append((estimated_fuel_kg, expected_fuel_kg))

    results: Dict[str, VesselAxisBResult] = {}

    for vessel_id in vessel_ids:
        pairs = per_vessel_pairs.get(vessel_id, [])

        if pairs:
            avg_estimated = sum(estimated for estimated, _ in pairs) / len(pairs)
            avg_expected = sum(expected for _, expected in pairs) / len(pairs)
            residual = compute_residual(avg_estimated, avg_expected)
        else:
            avg_estimated = avg_expected = residual = 0.0

        results[vessel_id] = VesselAxisBResult(
            vessel_id=vessel_id,
            used_row_count=len(pairs),
            skipped_rows=skipped_by_vessel.get(vessel_id, []),
            estimated_fuel_kg=avg_estimated,
            expected_fuel_kg=avg_expected,
            residual_raw=residual,
        )

    return results
