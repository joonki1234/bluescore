"""담당: 최지희

LLM이 선택할 수 있는 개선 문구의 화이트리스트.

모델은 행동을 새로 발명하지 않고, 점수 산출 요인에 연결된 아래 문구 중에서만
고른다. 코드·축·문구를 한 레코드로 묶어 프롬프트와 사후 검증이 같은 표를 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from explain.contract import ExplainInput, Recommendation


@dataclass(frozen=True)
class RecommendationRule:
    factor_code: str
    factor_label: str
    axis: str
    action: str


RULES: Dict[str, RecommendationRule] = {
    "항해 속도": RecommendationRule(
        "B_SPEED", "항해 속도", "b", "평균 항해 속도를 1노트 낮춰 보세요"
    ),
    "조업 시간당 연료": RecommendationRule(
        "B_FUEL_HOUR", "조업 시간당 연료", "b", "조업 중 공회전과 대기 시간을 줄여 보세요"
    ),
    "표류·대기 시간 비중": RecommendationRule(
        "B_IDLE_SHARE", "표류·대기 시간 비중", "b", "어장 도착 전 대기 시간을 줄여 보세요"
    ),
    "동일 격자 재방문 간격": RecommendationRule(
        "A_REVISIT", "동일 격자 재방문 간격", "a", "같은 어장을 연속으로 조업하는 횟수를 한 번 줄여 보세요"
    ),
    "혼잡 어장 회피": RecommendationRule(
        "A_CONGESTION", "혼잡 어장 회피", "a", "배가 몰리는 시간대를 피해 조업해 보세요"
    ),
    "조업 시간 배분": RecommendationRule(
        "A_TIME_MIX", "조업 시간 배분", "a", "조업과 항해 시간 배분을 고르게 가져가 보세요"
    ),
    "어장 이동 거리": RecommendationRule(
        "A_ROUTE", "어장 이동 거리", "a", "같은 어장을 다시 찾기까지 충분한 간격을 두세요"
    ),
    "입출항 규칙성": RecommendationRule(
        "A_PORT_PATTERN", "입출항 규칙성", "a", "입출항 시각을 일정하게 유지해 보세요"
    ),
    "해황 보정(유속·풍속)": RecommendationRule(
        "B_WEATHER", "해황 보정(유속·풍속)", "b", "해황이 급변하는 구간은 미리 피해 보세요"
    ),
    "경제속도 준수": RecommendationRule(
        "B_ECO_SPEED", "경제속도 준수", "b", "지금의 경제속도 운항을 유지하세요"
    ),
    "재방문 간격 확보": RecommendationRule(
        "A_REVISIT_KEEP", "재방문 간격 확보", "a", "지금처럼 재방문 간격을 넉넉히 유지하세요"
    ),
    "혼잡 해역 회피": RecommendationRule(
        "A_CONGESTION_KEEP", "혼잡 해역 회피", "a", "지금처럼 혼잡한 해역을 피해 조업하세요"
    ),
}


def allowed_rules(data: ExplainInput, limit: int = 3) -> List[RecommendationRule]:
    """감점 요인을 우선하고, 감점 요인이 없으면 가점 요인의 유지 규칙을 반환한다."""
    factors = data.top_negative(limit=limit) or data.top_positive(limit=limit)
    return [RULES[f.label] for f in factors if f.label in RULES][:limit]


def allowed_recommendations(data: ExplainInput, limit: int = 3) -> List[Recommendation]:
    return [Recommendation(action=rule.action, axis=rule.axis) for rule in allowed_rules(data, limit)]


def is_allowed(data: ExplainInput, recommendation: Recommendation) -> bool:
    return any(
        recommendation.action == rule.action and recommendation.axis == rule.axis
        for rule in allowed_rules(data)
    )
