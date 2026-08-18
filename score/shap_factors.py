"""
담당: 김준기, 오동규

A축 raw 값을 요인별로 분해한다 — "요인 기여도(SHAP)" 계산의 실제 구현.

배경: `explain/TODO.md`의 설계 원칙("기여도 계산은 score/가, 문장화만
explain/이 한다")에 따라, LLM이 숫자를 만들 여지를 없애려면 계산은 여기
score/에 있어야 한다. 2026-08-18 이전까지 화면의 `shapFactors`는
`data/mock/generate_dashboard_mock.py`가 손으로 써넣은 예시 숫자였다 — 이
모듈이 그 자리를 실제 계산으로 채운다.

`axis_a_pressure_raw`는 트리 모델이 아니라 명시적 가중합+상호작용항 수식
(`revisit_weight*revisit_raw + congestion_weight*congestion_raw +
interaction_weight*(revisit_raw*congestion_raw)`)이라, 근사 없이 세 항으로
정확히 분해된다 — 진짜 Shapley value 계산(`shap` 라이브러리)이 필요 없다.

`axis_a_factor_shares()`는 `services/real_scoring.py`(A축 실산출 경로)에
실제로 연결돼 있다 — `axis_a_factor_contributions()`의 raw 기여도를 "전체
A축 raw 압력에서 이 요인이 차지하는 상대적 비중(%)"으로 바꿔서, 유사군
분포 없이도 정직하게 `api/schemas.ShapFactorSchema.value`에 넣을 수 있게
한 것이다(개별 요인의 절대 "점수"는 유사군 백분위 특성상 유사군 분포 없이
못 구한다).

**B축은 이 모듈에서 다루지 않기로 팀에서 결정했다(2026-08-18)**. B축
효율(잔차 = estimated_fuel_kg - expected_fuel_kg)은 LightGBM 기준선
모델(`expected_fuel_kg`)에 `shap.TreeExplainer`를 붙여 한 번 시도해봤으나,
그건 "기대 연료소비량이 왜 이렇게 예측됐는지"(조건 설명)만 알려줄 뿐 "왜
이 선박의 효율이 좋다/나쁘다"는 설명하지 못한다는 게 드러났다 — 잔차를
만드는 진짜 원인(속도)이 순환성 방지를 위해 애초에 모델 입력에서 빠져있기
때문에, SHAP이 그 원인을 찾아낼 방법이 구조적으로 없다. 이 결과를 B축
점수의 설명으로 오인하면 사실과 다른 이유를 보여주게 되므로, 만들어뒀던
`axis_b_baseline_factor_contributions()`(테스트로 검증까지 마쳤던 것)를
통째로 들어냈다 — 필요해지면 이 커밋(`4536b08c`) 이전 이력에서 복원할 수
있다. B축은 대신 "자기 속도 vs 유사군 평균 속도" 같은 단순 비교로 설명하는
쪽이 유사군 분포도 필요 없고 실제 원인(속도)을 직접 보여줘서 더 낫다는
방향으로 정리됐다(구현은 별도 작업).
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
