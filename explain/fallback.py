"""
담당: 최지희

LLM 없이 설명을 만드는 템플릿 폴백.

**이 모듈이 설명 계층의 바닥이다.** API 키가 없든, 호출이 실패하든, 응답이
검증을 통과하지 못하든 화면에는 항상 문장이 나온다. 발표 당일 API가 죽어도
데모가 멈추지 않게 하려는 것이고, 그래서 `explain/`에서 가장 먼저 만들었다.

템플릿은 계산 결과를 문장 틀에 끼워 넣기만 한다. 숫자를 만들어낼 여지가
없으므로 검증도 필요 없다.
"""

from __future__ import annotations

from typing import Dict, List

from explain.contract import ExplainInput, ExplainOutput, Recommendation, ShapFactor

# 요인 라벨 → 개선 행동 문구. 라벨은 score/의 SHAP 출력과 맞춰야 한다.
# TODO(score/): SHAP 요인 라벨이 확정되면 이 표를 실제 라벨로 맞출 것.
_ACTION_BY_LABEL = {
    "항해 속도": "평균 항해 속도를 1노트 정도 낮춰 보세요",
    "조업 시간당 연료": "조업 중 공회전과 대기 시간을 줄여 보세요",
    "표류·대기 시간 비중": "어장 도착 전 대기 시간을 줄여 보세요",
    "동일 격자 재방문 간격": "같은 어장을 연속으로 조업하는 횟수를 한 번 줄여 보세요",
    "혼잡 어장 회피": "배가 몰리는 시간대를 피해 조업해 보세요",
    "조업 시간 배분": "조업과 항해 시간 배분을 고르게 가져가 보세요",
    "어장 이동 거리": "가까운 어장 위주로 동선을 짜 보세요",
    "입출항 규칙성": "입출항 시각을 일정하게 유지해 보세요",
    "해황 보정(유속·풍속)": "해황이 급변하는 구간은 미리 피해 보세요",
    "경제속도 준수": "지금의 경제속도 운항을 유지하세요",
    "재방문 간격 확보": "지금처럼 재방문 간격을 넉넉히 유지하세요",
    "혼잡 해역 회피": "지금처럼 혼잡한 해역을 피해 조업하세요",
}

_GENERIC_ACTION = "이 항목의 조업 패턴을 조금씩 조정해 보세요"


def _has_batchim(word: str) -> bool:
    """한글 낱말이 받침으로 끝나는가. 조사 선택에 쓴다."""
    if not word:
        return False
    last = word.strip()[-1]
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def _particle(word: str, with_batchim: str, without_batchim: str) -> str:
    """
    받침 유무에 맞는 조사를 고른다.

    '항해 속도이(가)' 같은 표기를 피하기 위한 것이다. 요인 라벨이 score/에서
    오는 값이라 문장을 미리 고정할 수 없어 런타임에 고른다.
    """
    return with_batchim if _has_batchim(word) else without_batchim


def _fuel_sentence(fuel_delta_percent: float) -> str:
    if fuel_delta_percent > 0:
        return f"다만 연료를 기대치보다 {fuel_delta_percent:g}% 더 씁니다."
    if fuel_delta_percent < 0:
        return f"연료도 기대치보다 {abs(fuel_delta_percent):g}% 적게 씁니다."
    return "연료 소비는 기대치와 비슷합니다."


def build_summary(data: ExplainInput) -> str:
    """계산 결과만으로 요약 문장을 만든다."""
    parts: List[str] = []

    positives = data.top_positive(limit=1)
    if positives:
        label = positives[0].label
        parts.append(f"{label}{_particle(label, '이', '가')} 점수를 가장 많이 올렸습니다.")
    else:
        parts.append("점수를 크게 끌어올린 항목은 아직 없습니다.")

    parts.append(
        f"비슷한 배 {data.peer_count}척 가운데 상위 {data.top_percent}%입니다."
    )
    parts.append(_fuel_sentence(data.fuel_delta_percent))

    negatives = data.top_negative(limit=1)
    if negatives:
        label = negatives[0].label
        parts.append(f"{label}{_particle(label, '이', '가')} 점수를 가장 많이 깎았습니다.")

    return " ".join(parts)


def build_recommendations(data: ExplainInput, limit: int = 3) -> List[Recommendation]:
    """
    점수를 깎은 요인부터 개선 행동을 만든다.

    깎은 요인이 부족하면 올린 요인을 '유지하세요' 쪽으로 채운다 — 이미 잘하는
    배에게 억지로 개선 지시를 만들어내지 않기 위한 것이다.
    """
    recommendations: List[Recommendation] = []

    for factor in data.top_negative(limit=limit):
        recommendations.append(
            Recommendation(
                action=_ACTION_BY_LABEL.get(factor.label, _GENERIC_ACTION),
                axis=factor.axis,
            )
        )

    if not recommendations:
        for factor in data.top_positive(limit=limit):
            recommendations.append(
                Recommendation(
                    action=_ACTION_BY_LABEL.get(
                        factor.label, "지금의 조업 패턴을 그대로 유지하세요"
                    ),
                    axis=factor.axis,
                )
            )

    return recommendations[:limit]


def build(data: ExplainInput, reason: str) -> ExplainOutput:
    """
    폴백 결과를 만든다.

    Args:
        data: 계산 결과
        reason: 왜 폴백했는지 (화면에 표시된다). 예: "api_key_missing"
    """
    return ExplainOutput(
        summary=build_summary(data),
        shap_factors=list(data.shap_factors),
        recommendations=build_recommendations(data),
        source=f"fallback:{reason}",
    )


def build_qa_fallback(data: ExplainInput, question: str) -> str:
    """
    LLM 없이 질문에 답한다.

    자유 질문에 정확히 답할 수는 없으므로, 리포트 요약을 그대로 안내하고
    담당자 확인이 필요하다는 것을 알린다 — 지어내지 않는 것이 우선이다.
    """
    return (
        f"지금은 AI 답변을 생성할 수 없어 자동으로 답변드리기 어렵습니다. "
        f"참고로 현재 리포트 요약은 다음과 같습니다 — {build_summary(data)} "
        f"'{question.strip()}'에 대한 구체적인 답이 필요하시면 점수리포트의 "
        f"요인별 설명을 확인하시거나 담당자에게 문의해 주세요."
    )


def build_objection_fallback(data: ExplainInput, reason: str, detail: str) -> str:
    """
    LLM 없이 이의제기 접수만 확인한다.

    답을 지어내는 대신 "심사역이 검토한다"는 사실만 안내한다 — 이의제기의
    최종 판단은 어차피 AI가 아니라 심사역이 하기 때문에, 폴백이라도
    서비스 전제를 벗어나지 않는다.
    """
    return (
        f"'{reason}' 사유로 접수된 이의제기입니다. 지금은 AI 초안을 생성할 수 "
        "없어, 담당 심사역이 데이터 출처와 산출 근거를 직접 검토한 뒤 답변을 "
        "안내해 드릴 예정입니다."
    )


def build_report_fallback(data: ExplainInput) -> Dict[str, str]:
    """
    LLM 없이 요인별 설명을 `{요인 라벨: 문장}`으로 만든다.

    `factor_metrics`(선박 자신 값 vs 유사군 평균)를 계산 결과 그대로 문장
    틀에 끼워 넣는다 — 숫자를 만들어낼 여지가 없어 검증이 필요 없다.
    """
    out: Dict[str, str] = {}
    for metric in data.factor_metrics:
        axis_name = "자원 압력" if metric.axis == "a" else "운항 효율"
        diff = metric.self_value - metric.peer_average
        direction = "높습니다" if diff > 0 else "낮습니다" if diff < 0 else "비슷합니다"
        out[metric.label] = (
            f"{axis_name} 요인입니다. 귀 선박이 {metric.self_value:g}{metric.unit}, "
            f"유사 선박군 평균은 {metric.peer_average:g}{metric.unit}로 평균보다 {direction}."
        )
    return out


def build_improvement_tip_fallback(actions: List[str]) -> str:
    """
    LLM 없이 개선 조합의 실행 팁을 만든다.

    계산이 정한 변경 방향(`actions`)을 그대로 이어 붙일 뿐이라 숫자를 만들어낼
    여지가 없다. LLM 팁과 마찬가지로 수치는 넣지 않는다.
    """
    if not actions:
        return "지금 조업 방식을 그대로 유지하면 됩니다."
    joined = ", ".join(actions)
    return f"{joined}. 한 번에 다 바꾸기보다 다음 출항에서 한 가지씩 시도해 보세요."


def merge_partial(
    data: ExplainInput,
    summary: str,
    recommendations: List[Recommendation],
    reason: str,
) -> ExplainOutput:
    """
    LLM 응답이 일부만 쓸 만할 때, 빈 자리를 템플릿으로 메운다.

    요약은 통과했는데 개선 코칭이 비었거나 그 반대인 경우를 위한 것이다.
    통째로 버리는 것보다 낫다.
    """
    shap_factors: List[ShapFactor] = list(data.shap_factors)
    return ExplainOutput(
        summary=summary or build_summary(data),
        shap_factors=shap_factors,
        recommendations=recommendations or build_recommendations(data),
        source=f"fallback:{reason}",
    )
