"""
담당: 최지희

LLM 응답의 Strict JSON 파싱과 숫자 검증.

두 가지를 한다.

1. **구조 검증** — 응답이 `LLM_OUTPUT_SCHEMA` 모양인지 확인한다. 프로바이더가
   구조화 출력을 강제하더라도 여기서 한 번 더 본다. 스키마 강제는 프로바이더
   기능이고, 프로바이더는 교체되기 때문이다.
2. **숫자 검증** — 응답 문장에 입력에 없던 수치가 섞였는지 본다. 섞였으면
   그 응답은 버리고 폴백으로 강등한다.

숫자 검증이 이 모듈의 존재 이유다. 기획서 (8-3)의 "숫자를 창작하지 않도록"은
프롬프트만으로는 보장되지 않는다. 프롬프트는 부탁이고, 이건 검사다. 발표
Q&A에서 "AI가 지어낸 거 아니냐"는 질문에 코드로 답할 수 있는 자리이기도 하다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from explain.contract import AXIS_CODES, ExplainInput, Recommendation

# 문장에서 숫자를 뽑는 패턴. 부호와 소수점을 포함한다.
_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")

# 부동소수점 비교 허용 오차. 72.6 vs 72.60 같은 표기 차이를 흡수한다.
_TOLERANCE = 0.05

# 검증 없이 허용하는 숫자.
#   0~12  : 개수·순서·월 표현 ("두 가지", "3회", "6개월")
#   2020~2030 : 연도
# 이 범위 밖의 숫자는 반드시 입력에 있어야 한다.
_ALWAYS_ALLOWED_MAX_SMALL_INT = 12
_YEAR_RANGE = (2020, 2030)


class RenderError(ValueError):
    """응답이 검증을 통과하지 못했다. 호출부는 폴백으로 강등해야 한다."""


def _allowed_numbers(data: ExplainInput) -> List[float]:
    """
    응답에 등장해도 되는 숫자 집합.

    입력 값 자체와, 소수점 첫째 자리로 반올림한 값·정수로 반올림한 값을 함께
    허용한다. 모델이 "8.0%"를 "8%"로 쓰는 것은 창작이 아니라 표기이기 때문이다.
    """
    allowed: List[float] = []
    for value in data.numeric_values():
        allowed.append(value)
        allowed.append(round(value, 1))
        allowed.append(float(round(value)))
    return allowed


def _is_allowed(number: float, allowed: List[float]) -> bool:
    if number.is_integer():
        as_int = int(number)
        if 0 <= as_int <= _ALWAYS_ALLOWED_MAX_SMALL_INT:
            return True
        if _YEAR_RANGE[0] <= as_int <= _YEAR_RANGE[1]:
            return True
    return any(abs(number - candidate) <= _TOLERANCE for candidate in allowed)


def find_invented_numbers(text: str, data: ExplainInput) -> List[float]:
    """
    문장에서 입력에 없는 숫자를 찾는다.

    Returns:
        창작된 것으로 보이는 숫자 목록. 비어 있으면 통과.
    """
    allowed = _allowed_numbers(data)
    invented: List[float] = []
    for match in _NUMBER_PATTERN.findall(text):
        number = float(match)
        if not _is_allowed(number, allowed) and number not in invented:
            invented.append(number)
    return invented


def parse_json(raw: str) -> Dict[str, Any]:
    """
    LLM 응답 문자열을 JSON으로 파싱한다.

    구조화 출력을 쓰면 보통 순수 JSON이 오지만, 프로바이더에 따라 코드펜스로
    감싸 오는 경우가 있어 한 번 벗겨낸다.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RenderError(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RenderError(f"최상위가 객체가 아닙니다: {type(parsed).__name__}")
    return parsed


def _validate_recommendations(raw: Any) -> List[Recommendation]:
    if not isinstance(raw, list):
        raise RenderError("recommendations가 배열이 아닙니다.")

    recommendations: List[Recommendation] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RenderError(f"recommendations[{index}]가 객체가 아닙니다.")
        action = item.get("action")
        axis = item.get("axis")
        if not isinstance(action, str) or not action.strip():
            raise RenderError(f"recommendations[{index}].action이 비어 있습니다.")
        if axis not in AXIS_CODES:
            raise RenderError(
                f"recommendations[{index}].axis가 {AXIS_CODES} 중 하나가 아닙니다: {axis!r}"
            )
        recommendations.append(Recommendation(action=action.strip(), axis=axis))

    return recommendations


def parse_and_validate(
    raw: str, data: ExplainInput
) -> Tuple[str, List[Recommendation]]:
    """
    응답을 파싱하고 구조·숫자를 모두 검증한다.

    Returns:
        (summary, recommendations)

    Raises:
        RenderError: 구조가 어긋나거나 창작된 숫자가 섞였을 때.
    """
    parsed = parse_json(raw)

    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise RenderError("summary가 비어 있습니다.")
    summary = summary.strip()

    recommendations = _validate_recommendations(parsed.get("recommendations"))
    if not recommendations:
        raise RenderError("recommendations가 비어 있습니다.")

    # 숫자 검증은 요약과 개선 제안 전체를 대상으로 한다.
    combined = " ".join([summary] + [r.action for r in recommendations])
    invented = find_invented_numbers(combined, data)
    if invented:
        raise RenderError(
            "입력에 없는 수치가 포함되어 있습니다: "
            + ", ".join(f"{n:g}" for n in invented)
        )

    return summary, recommendations


def safe_parse(
    raw: str, data: ExplainInput
) -> Tuple[Optional[str], List[Recommendation], Optional[str]]:
    """
    예외를 던지지 않는 파싱.

    Returns:
        (summary, recommendations, error). 성공하면 error가 None이고,
        실패하면 summary는 None·recommendations는 빈 리스트다.
    """
    try:
        summary, recommendations = parse_and_validate(raw, data)
    except RenderError as exc:
        return None, [], str(exc)
    return summary, recommendations, None


def parse_and_validate_text(raw: str, data: ExplainInput, field: str) -> str:
    """
    단일 문장 필드만 있는 응답(질의응답·이의제기 응답·상세 리포트)을 검증한다.

    구조 검증과 숫자 검증 둘 다 `parse_and_validate`와 같은 규칙을 쓴다 —
    스키마만 다르고 "숫자를 창작하지 않는다"는 계약은 동일하게 강제된다.
    """
    parsed = parse_json(raw)

    text = parsed.get(field)
    if not isinstance(text, str) or not text.strip():
        raise RenderError(f"{field}가 비어 있습니다.")
    text = text.strip()

    invented = find_invented_numbers(text, data)
    if invented:
        raise RenderError(
            "입력에 없는 수치가 포함되어 있습니다: "
            + ", ".join(f"{n:g}" for n in invented)
        )

    return text


def safe_parse_text(
    raw: str, data: ExplainInput, field: str
) -> Tuple[Optional[str], Optional[str]]:
    """예외를 던지지 않는 단일 문장 파싱. Returns: (text, error)."""
    try:
        text = parse_and_validate_text(raw, data, field)
    except RenderError as exc:
        return None, str(exc)
    return text, None
