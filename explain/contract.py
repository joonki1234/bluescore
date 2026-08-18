"""

설명 계층의 입력/출력 계약.

여기 정의된 출력 형태는 `data/mock/README_mock_data 제안.md` 5번의
`summary` / `shapFactors` / `recommendations` 구조를 그대로 따른다. 화면과
mock이 같은 키를 보고 있어야 프론트가 실제 LLM 연결 전에도 개발할 수 있다.

**LLM이 생성하는 것은 `summary`와 `recommendations[].action` 문장뿐이다.**
`shapFactors`는 계산 결과이므로 LLM을 거치지 않고 그대로 통과시킨다. 숫자를
만들어낼 여지를 구조적으로 없애기 위한 것이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# LLM 응답에 허용되는 축 코드
AXIS_CODES = ("a", "b")

# 라벨 문자열에 박혀 있는 숫자를 뽑는 패턴. "근해통발 · 29톤 · 남해"의 29,
# "20–30톤"의 20과 30처럼 화면에도 그대로 보이는 값들이다.
_LABEL_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


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
class FactorMetric:
    """요인 하나의 선박 자신 값 vs 유사군 평균값. 계산 결과이며 LLM을 거치지 않는다."""

    label: str
    axis: str  # "a" | "b"
    self_value: float
    peer_average: float
    unit: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "axis": self.axis,
            "selfValue": self.self_value,
            "peerAverage": self.peer_average,
            "unit": self.unit,
        }


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
    factor_metrics: List[FactorMetric] = field(default_factory=list)
    season: Optional[str] = None  # facts.py의 금어기 조회 키
    gear_type: Optional[str] = None

    def numeric_values(self) -> List[float]:
        """
        응답에 등장해도 되는 숫자들. 숫자 검증의 허용 집합이 된다.

        점수·기여도 같은 계산값뿐 아니라 **라벨 안에 박힌 숫자도 넣는다.**
        선박 라벨이 "근해통발 · 29톤 · 남해"인데 29가 허용 집합에 없으면,
        모델이 자기 배 톤수를 그대로 옮겨 적었을 뿐인데 `render.py`가
        수치 창작으로 보고 폴백시킨다. 실제로 앨런 프로바이더를 붙이며
        이 경우가 드러났다 — 화면에 이미 보이는 숫자를 문장에서 금지할
        이유가 없다.
        """
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
        for metric in self.factor_metrics:
            values.append(metric.self_value)
            values.append(metric.peer_average)
        for label in (self.vessel_label, self.fleet_label):
            for match in _LABEL_NUMBER_PATTERN.findall(label or ""):
                values.append(float(match))
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


@dataclass(frozen=True)
class TextOutput:
    """
    질의응답 / 이의제기 응답처럼 문장 하나만 생성하는 흐름의 결과.

    `ExplainOutput`과 같은 `source` 규약을 쓴다 — "llm:<provider>" 또는
    "fallback:<사유>". 화면은 이 값으로 LLM 생성인지 템플릿인지 표시한다.
    """

    text: str
    source: str

    @property
    def is_fallback(self) -> bool:
        return self.source.startswith("fallback")

    def as_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "source": self.source}


@dataclass(frozen=True)
class ReportOutput:
    """
    요인별 상세 리포트의 결과.

    `items`는 `{요인 라벨: 설명 문장}`이다. 한 덩어리 문자열이 아니라 라벨로
    묶여 있어야 화면이 요인별 실측값 옆에 해당 문장을 붙일 수 있다 — 줄글
    한 문단으로는 어느 문장이 어느 수치를 설명하는지 독자가 맞춰야 했다.
    """

    items: Dict[str, str]
    source: str

    @property
    def is_fallback(self) -> bool:
        return self.source.startswith("fallback")

    def as_dict(self) -> Dict[str, Any]:
        return {"items": dict(self.items), "source": self.source}


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

# 단일 문장 필드만 받는 흐름 공통 스키마 모양. 필드 이름만 다르다.
QA_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": (
                "어업인의 질문에 대한 답변. 주어진 계산 결과와 참고 사실에 있는 "
                "내용만 근거로 삼는다. 없는 내용은 모른다고 답한다."
            ),
        },
    },
    "required": ["answer"],
    "additionalProperties": False,
}

OBJECTION_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "response": {
            "type": "string",
            "description": (
                "이의제기에 대한 초안 답변. 심사역이 검토 후 수정하거나 그대로 "
                "전달할 수 있는 초안이다. 단정적으로 결론짓지 않는다."
            ),
        },
    },
    "required": ["response"],
    "additionalProperties": False,
}

# 상세 리포트는 요인마다 한 항목씩 돌려받는다. 한 덩어리 줄글로 받으면 화면이
# 그것을 그대로 문단으로 뿌릴 수밖에 없어 읽히지 않았다. 구조는 문자열을 나중에
# 쪼개서 만드는 것이 아니라 생성 단계에서 정한다.
REPORT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "요인별 설명. 주어진 요인 하나당 정확히 한 항목.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "설명 대상 요인의 라벨. 주어진 라벨을 그대로 쓴다.",
                    },
                    "sentence": {
                        "type": "string",
                        "description": (
                            "그 요인 하나에 대한 1~2문장 설명. 주어진 실측값(선박 자신 "
                            "값·유사군 평균값) 외의 수치를 쓰지 않는다."
                        ),
                    },
                },
                "required": ["label", "sentence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

TIP_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tip": {
            "type": "string",
            "description": (
                "개선 조합을 실제 조업에서 어떻게 실천하는지 알려주는 두 문장. "
                "숫자(점수·속도·퍼센트·금리)를 포함하지 않는다 — 수치는 화면이 "
                "따로 표시하므로 여기서는 행동만 설명한다."
            ),
        },
    },
    "required": ["tip"],
    "additionalProperties": False,
}
