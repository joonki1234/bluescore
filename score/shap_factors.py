"""A축 raw 값을 재방문·혼잡·상호작용 기여도로 분해한다.

A축은 명시적 가중합이므로 Shapley 근사 없이 세 항으로 정확히 분해할 수 있다.
`axis_a_factor_shares()`는 각 기여도를 절댓값 합 대비 비중으로 변환한다.

B축은 효율 잔차의 원인인 속도가 순환성 방지를 위해 기준선 입력에서 빠져 있어
SHAP으로 설명할 수 없으므로 이 모듈에서 다루지 않는다.
"""

from typing import List

from score.axis_a_pressure import (
    AXIS_A_CONGESTION_WEIGHT,
    AXIS_A_INTERACTION_WEIGHT,
    AXIS_A_REVISIT_WEIGHT,
    VesselAxisAResult,
)


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
    결합에 실제로 쓰인 게 z-score 정규화된 값이라(`axis_a_pressure.py`
    참고), 여기서도 `revisit_interval_raw`가 아니라 `revisit_zscore`
    필드를 쓴다 — raw 필드를 쓰면 이 합이 `axis_a_pressure_raw`와
    안 맞는다.
    """
    revisit_contribution = revisit_weight * result.revisit_zscore
    congestion_contribution = congestion_weight * result.crowding_zscore
    interaction_contribution = interaction_weight * result.interaction_zscore

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
