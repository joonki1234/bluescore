"""
담당: 최지희

설명 계층의 입력/출력 계약.

여기 정의된 출력 형태는 `data/mock/README_mock_data 제안.md` 5번의
`summary` / `shapFactors` / `recommendations` 구조를 그대로 따른다. 화면과
mock이 같은 키를 보고 있어야 프론트가 실제 LLM 연결 전에도 개발할 수 있다.

**LLM이 생성하는 것은 `summary`와 `recommendations[].action` 문장뿐이다.**
`shapFactors`는 계산 결과이므로 LLM을 거치지 않고 그대로 통과시킨다. 숫자를
만들어낼 여지를 구조적으로 없애기 위한 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# LLM 응답에 허용되는 축 코드
AXIS_CODES = ("a", "b")


@dataclass(frozen=True)
class ShapFactor:
    """요인 하나의 기여도. 계산 결과이며 LLM을 거치지 않는다."""

    label: str
    value: float
    axis: str  # "a" | "b"

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "value": self.value, "axis": self.axis}


@dataclass(frozen=True)
class Recommendation:
    """개선 코칭 한 줄."""

    action: str
    axis: str

    def as_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "axis": self.axis}


@dataclass(frozen=True)
class ExplainInput:
    """
    설명 생성에 필요한 계산 결과 일체.

    여기 담긴 숫자만이 응답에 등장할 수 있다 (`render.py`의 숫자 검증 참고).
    """

    vessel_id: str
    vessel_label: str  # "근해통발 · 29톤 · 남해"
    fleet_label: str  # "근해통발 · 20–30톤 · 남해 · 하계"
    blue_score: float
    axis_a_score: float
    axis_b_score: float
    peer_count: int
    top_percent: int
    fuel_delta_percent: float
    shap_factors: List[ShapFactor] = field(default_factory=list)
    season: Optional[str] = None  # facts.py의 금어기 조회 키
    gear_type: Optional[str] = None

    def numeric_values(self) -> List[float]:
        """응답에 등장해도 되는 숫자들. 숫자 검증의 허용 집합이 된다."""
        values: List[float] = [
            self.blue_score,
            self.axis_a_score,
            self.axis_b_score,
            float(self.peer_count),
            float(self.top_percent),
            self.fuel_delta_percent,
            abs(self.fuel_delta_percent),
        ]
        for factor in self.shap_factors:
            values.append(factor.value)
            values.append(abs(factor.value))
        return values

    def top_positive(self, limit: int = 2) -> List[ShapFactor]:
        return sorted(
            (f for f in self.shap_factors if f.value > 0),
            key=lambda f: -f.value,
        )[:limit]

    def top_negative(self, limit: int = 2) -> List[ShapFactor]:
        return sorted(
            (f for f in self.shap_factors if f.value < 0),
            key=lambda f: f.value,
        )[:limit]


@dataclass(frozen=True)
class ExplainOutput:
    """
    설명 생성 결과.

    `source`는 이 결과가 어디서 나왔는지 알려준다 — 화면 하단에 표시해
    시연 중 무엇이 LLM 생성이고 무엇이 템플릿인지 숨기지 않기 위한 것이다.
        "llm:<provider>"  LLM이 생성
        "fallback:<사유>"  템플릿 폴백
    """

    summary: str
    shap_factors: List[ShapFactor]
    recommendations: List[Recommendation]
    source: str

    @property
    def is_fallback(self) -> bool:
        return self.source.startswith("fallback")

    def as_dict(self) -> Dict[str, Any]:
        """mock JSON과 같은 camelCase 형태로 직렬화한다."""
        return {
            "summary": self.summary,
            "shapFactors": [f.as_dict() for f in self.shap_factors],
            "recommendations": [r.as_dict() for r in self.recommendations],
            "source": self.source,
        }


# ─── LLM 응답 스키마 ─────────────────────────────────────────────────────────
# LLM은 문장만 만든다. shapFactors는 계산 결과라 여기 없다.
LLM_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "어업인에게 보여줄 2~3문장 요약. 잘한 점 먼저, 개선할 점 다음. "
                "잔차·백분위 같은 전문용어를 쓰지 않는다."
            ),
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "어업인이 실제로 할 수 있는 구체적 행동 한 줄",
                    },
                    "axis": {
                        "type": "string",
                        "enum": list(AXIS_CODES),
                        "description": "a=자원 압력, b=운항 효율",
                    },
                },
                "required": ["action", "axis"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}
