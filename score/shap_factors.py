"""
담당: 김준기, 오동규

A축·B축 raw 값을 요인별로 분해한다 — "요인 기여도(SHAP)" 계산의 실제 구현.

배경: `explain/TODO.md`의 설계 원칙("기여도 계산은 score/가, 문장화만
explain/이 한다")에 따라, LLM이 숫자를 만들 여지를 없애려면 계산은 여기
score/에 있어야 한다. `requirements.txt`에 `shap` 패키지가 있었지만
2026-08-18 이전까지 리포 어디에도 `import shap`가 없었고, 화면의
`shapFactors`는 `data/mock/generate_dashboard_mock.py`가 손으로 써넣은
예시 숫자였다 — 이 모듈이 그 자리를 실제 계산으로 채운다.

**범위 제한 (중요)**: 이 모듈은 raw 단위 기여도까지만 계산한다. raw 값을
화면에 쓰는 "점수(포인트)" 단위로 바꾸는 환산 정책(B축이라면
`tradeoff_coefficients.FUEL_PERCENT_PER_AXIS_B_POINT` 같은 것)은 아직 팀
결정이 없어 여기서 만들지 않는다. `explain/contract.ShapFactor`로의 배선,
`services/`로의 연결도 이번 범위 밖이다 — `score/scripts/run_real_axis_a.py`/
`run_real_axis_b.py`가 "된다"만 증명하고 화면 배선은 안 한 것과 같은 패턴.
증명은 `score/scripts/run_shap_factors.py` 참고.

**(2026-08-18 추가) 예외 — A축은 raw가 아니라 "상대적 비중(%)"으로
`services/real_scoring.py`에 실제 연결됐다** — `axis_a_factor_shares()`
참고. A축은 raw→점수 환산이 원래 안 되지만(유사군 백분위라 개별 요인 하나만
떼서 "몇 점"으로 못 바꿈), "전체 A축 raw 압력에서 이 요인이 차지하는
비중(%)"은 유사군 분포 없이도 정직하게 계산 가능해서, 이 프레이밍으로
`api/schemas.ShapFactorSchema.value`에 바로 넣을 수 있게 했다. B축은 여전히
연결 안 됨(위 설명대로 SHAP이 "점수"가 아니라 "기준선 조건"만 설명하는
의미론적 제약 때문).

A축과 B축은 계산 방식이 다르다:
    - A축(`axis_a_factor_contributions`): `axis_a_pressure.py`의
      `axis_a_pressure_raw`는 트리 모델이 아니라 명시적 가중합+상호작용항
      수식(`revisit_weight*revisit_raw + congestion_weight*congestion_raw +
      interaction_weight*(revisit_raw*congestion_raw)`)이라, 근사 없이 세
      항으로 정확히 분해된다. 진짜 Shapley value 계산이 필요 없다 — `shap`
      라이브러리를 쓰지 않는다.
    - B축(`axis_b_baseline_factor_contributions`): `axis_b_baseline.py`의
      `fit_baseline_model()`이 만드는 `LGBMRegressor`(트리 모델)에는
      `shap.TreeExplainer`가 표준적으로 맞는다. **단, 이 SHAP 값이 설명하는
      건 "기대(expected_fuel_kg) 연료소비량이 왜 이렇게 예측됐는지"(톤수·
      해황·어업종 같은 조건들의 기여)이지, "왜 이 선박의 B축 효율이 좋다/
      나쁘다"가 아니다.** 효율(잔차)은 `estimated_fuel_kg - expected_fuel_kg`라는
      단순 뺄셈이라 그 자체로 이미 설명이 끝나 있다 — SHAP이 필요한 건 그중
      `expected_fuel_kg`(기준선)가 어떤 조건들 때문에 그 값으로 잡혔는지
      뿐이다. 이걸 "왜 점수가 이렇다"는 의미로 쓰면 안 된다.
"""

from typing import Dict, List

import shap

from score.axis_a_pressure import (
    AXIS_A_CONGESTION_WEIGHT,
    AXIS_A_INTERACTION_WEIGHT,
    AXIS_A_REVISIT_WEIGHT,
    VesselAxisAResult,
)
from score.axis_b_baseline import (
    CATEGORICAL_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    LGBMRegressor,
    _rows_to_feature_dataframe,
)

# B축 LightGBM 피처 컬럼명 -> 화면용 한글 라벨.
FEATURE_LABELS: Dict[str, str] = {
    "tonnageGt": "톤수",
    "seaSurfaceTempC": "수온",
    "windSpeedMs": "풍속",
    "currentSpeedMs": "유속",
    "durationHours": "조업시간",
    "gearType": "어구 종류",
    "seaArea": "해역",
    "season": "계절",
}


def axis_a_factor_contributions(
    result: VesselAxisAResult,
    revisit_weight: float = AXIS_A_REVISIT_WEIGHT,
    congestion_weight: float = AXIS_A_CONGESTION_WEIGHT,
    interaction_weight: float = AXIS_A_INTERACTION_WEIGHT,
) -> List[dict]:
    """A축 raw 압력값을 재방문압력/혼잡압력/상호작용항 세 요인으로 정확히 분해한다.

    세 항의 raw_contribution 합은 `result.axis_a_pressure_raw`와 정확히
    같다(부동소수점 오차 범위 내) — `compute_axis_a_pressure()`가 이
    가중치들로 결합한 값을 그대로 세 항으로 되돌리는 것뿐이라 근사가 없다.
    """
    revisit_contribution = revisit_weight * result.revisit_interval_raw
    congestion_contribution = congestion_weight * result.crowding_pressure_raw
    interaction_contribution = interaction_weight * result.interaction_raw

    return [
        {"label": "재방문압력", "raw_contribution": revisit_contribution, "axis": "a"},
        {"label": "혼잡압력", "raw_contribution": congestion_contribution, "axis": "a"},
        {"label": "재방문×혼잡 상호작용", "raw_contribution": interaction_contribution, "axis": "a"},
    ]


def axis_a_factor_shares(
    result: VesselAxisAResult,
    revisit_weight: float = AXIS_A_REVISIT_WEIGHT,
    congestion_weight: float = AXIS_A_CONGESTION_WEIGHT,
    interaction_weight: float = AXIS_A_INTERACTION_WEIGHT,
) -> List[dict]:
    """`axis_a_factor_contributions()`의 raw 기여도를, 세 항의 절댓값 합
    대비 상대적 비중(%, 부호 유지)으로 바꾼다.

    `api/schemas.ShapFactorSchema.value`에 바로 넣을 수 있도록 키 이름도
    `raw_contribution`이 아니라 `value`로 낸다. 세 항이 전부 0이면(재방문·
    혼잡 raw가 둘 다 0인 선박) 0으로 나누기를 피해 셋 다 `value=0.0`으로
    반환한다.
    """
    contributions = axis_a_factor_contributions(
        result, revisit_weight, congestion_weight, interaction_weight
    )
    total_magnitude = sum(abs(c["raw_contribution"]) for c in contributions)

    return [
        {
            "label": c["label"],
            "value": (c["raw_contribution"] / total_magnitude * 100) if total_magnitude else 0.0,
            "axis": "a",
        }
        for c in contributions
    ]


def axis_b_baseline_factor_contributions(model: LGBMRegressor, row: dict) -> List[dict]:
    """B축 LightGBM 기준선(expected_fuel_kg) 예측을 피처별 SHAP 기여도(kg)로 분해한다.

    **주의**: 이건 "기준선이 왜 이 값으로 예측됐는지"(조건 설명)이지 "왜 이
    선박의 B축 효율이 좋다/나쁘다"(모듈 docstring 참고)가 아니다. 효율은
    `estimated_fuel_kg - expected_fuel_kg`로 이미 설명되며, 이 함수는 그중
    `expected_fuel_kg` 쪽만 분해한다.

    row는 하나의 이벤트 딕셔너리다(`axis_b_baseline.py`가 요구하는 피처
    컬럼을 포함해야 한다 — `NUMERIC_FEATURE_COLUMNS`/
    `CATEGORICAL_FEATURE_COLUMNS`).
    """
    feature_df = _rows_to_feature_dataframe([row])
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(feature_df)

    # 회귀 모델의 shap_values는 (n_samples, n_features) 형태 — 샘플이
    # 하나뿐이니 그 행만 쓴다.
    row_values = shap_values[0]

    feature_columns = NUMERIC_FEATURE_COLUMNS + CATEGORICAL_FEATURE_COLUMNS

    return [
        {
            "label": FEATURE_LABELS.get(column, column),
            "raw_contribution_kg": float(row_values[i]),
            "axis": "b",
        }
        for i, column in enumerate(feature_columns)
    ]


def axis_b_baseline_expected_value(model: LGBMRegressor, row: dict) -> float:
    """`axis_b_baseline_factor_contributions()`의 SHAP 값과 짝을 이루는
    기준(base) 값 — 가법성 불변식(모든 기여도 합 + 이 값 == 예측값) 검증에
    쓰인다."""
    feature_df = _rows_to_feature_dataframe([row])
    explainer = shap.TreeExplainer(model)
    base_value = explainer.expected_value
    return float(base_value[0]) if hasattr(base_value, "__len__") else float(base_value)
