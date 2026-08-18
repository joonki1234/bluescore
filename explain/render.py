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
from explain.recommendation_rules import is_allowed

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


# 개선 팁에 나오면 안 되는 조언.
#
# 자원 압력(A축)의 해법은 "같은 자리를 다시 찾기까지 간격을 두라"이지
# "다른 어장으로 옮겨라"가 아니다. 어장을 옮기면 연료를 더 태워 운항
# 효율(B축)이 깎이므로, 점수를 올리려는 사람에게 정반대 조언이 된다.
#
# 프롬프트에 금지 문구를 넣어도 앨런과 OpenAI 둘 다 계속 새어 나왔다.
# 숫자 검증과 같은 이유로 여기서 검사한다 — 프롬프트는 부탁이고 이건 검사다.
# 어미가 활용되므로 어간만 잡는다 ("옮기세요" / "옮겨 보세요" 둘 다).
_FORBIDDEN_TIP_PATTERNS = (
    re.compile(r"다른\s*어장"),
    re.compile(r"어장을?\s*옮[기겨]"),
    re.compile(r"어장을?\s*바[꾸꿔]"),
    re.compile(r"새로운\s*어장"),
)


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


def find_forbidden_advice(text: str) -> List[str]:
    """
    개선 팁에 섞이면 안 되는 조언을 찾는다.

    Returns:
        걸린 문구 목록. 비어 있으면 통과.
    """
    found: List[str] = []
    for pattern in _FORBIDDEN_TIP_PATTERNS:
        match = pattern.search(text)
        if match and match.group(0) not in found:
            found.append(match.group(0))
    return found


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


def _validate_recommendations(raw: Any, data: ExplainInput) -> List[Recommendation]:
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
        recommendation = Recommendation(action=action.strip(), axis=axis)
        invented = find_invented_numbers(recommendation.action, data)
        if invented:
            raise RenderError(
                "입력에 없는 수치가 포함되어 있습니다: "
                + ", ".join(f"{n:g}" for n in invented)
            )
        if not is_allowed(data, recommendation):
            raise RenderError(
                f"recommendations[{index}]가 allowedRecommendations 규칙에 없습니다."
            )
        recommendations.append(recommendation)

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

    recommendations = _validate_recommendations(parsed.get("recommendations"), data)
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


def parse_and_validate_text(
    raw: str, data: ExplainInput, field: str, *, check_forbidden_advice: bool = False
) -> str:
    """
    단일 문장 필드만 있는 응답(질의응답·이의제기 응답·상세 리포트)을 검증한다.

    구조 검증과 숫자 검증 둘 다 `parse_and_validate`와 같은 규칙을 쓴다 —
    스키마만 다르고 "숫자를 창작하지 않는다"는 계약은 동일하게 강제된다.

    Args:
        check_forbidden_advice: 개선 팁 전용. 점수를 되레 깎는 조언이
            섞였는지 함께 본다 (`_FORBIDDEN_TIP_PATTERNS` 참고).
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

    if check_forbidden_advice:
        forbidden = find_forbidden_advice(text)
        if forbidden:
            raise RenderError(
                "점수를 깎는 조언이 포함되어 있습니다: " + ", ".join(forbidden)
            )

    return text


def safe_parse_text(
    raw: str, data: ExplainInput, field: str, *, check_forbidden_advice: bool = False
) -> Tuple[Optional[str], Optional[str]]:
    """예외를 던지지 않는 단일 문장 파싱. Returns: (text, error)."""
    try:
        text = parse_and_validate_text(
            raw, data, field, check_forbidden_advice=check_forbidden_advice
        )
    except RenderError as exc:
        return None, str(exc)
    return text, None


def parse_and_validate_report_items(raw: str, data: ExplainInput) -> Dict[str, str]:
    """
    요인별 상세 리포트 응답을 `{요인 라벨: 설명 문장}`으로 검증해 돌려준다.

    라벨은 입력에 있는 요인만 받는다 — 모델이 없는 요인을 지어내면 화면이
    계산에 없는 항목을 근거처럼 보여주게 된다. 숫자 검증은 문장마다 건다.
    """
    parsed = parse_json(raw)

    items = parsed.get("items")
    if not isinstance(items, list) or not items:
        raise RenderError("items가 비어 있습니다.")

    known = {m.label for m in data.factor_metrics}
    out: Dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise RenderError("items 원소가 객체가 아닙니다.")
        label, sentence = item.get("label"), item.get("sentence")
        if not isinstance(label, str) or not isinstance(sentence, str):
            raise RenderError("label 또는 sentence가 문자열이 아닙니다.")
        label, sentence = label.strip(), sentence.strip()
        if label not in known:
            raise RenderError(f"입력에 없는 요인입니다: {label}")
        if not sentence:
            raise RenderError(f"{label}의 설명이 비어 있습니다.")
        invented = find_invented_numbers(sentence, data)
        if invented:
            raise RenderError(
                f"{label} 설명에 입력에 없는 수치가 있습니다: "
                + ", ".join(f"{n:g}" for n in invented)
            )
        out[label] = sentence

    if not out:
        raise RenderError("유효한 요인 설명이 없습니다.")
    return out


def safe_parse_report_items(
    raw: str, data: ExplainInput
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """예외를 던지지 않는 요인별 리포트 파싱. Returns: (items, error)."""
    try:
        return parse_and_validate_report_items(raw, data), None
    except RenderError as exc:
        return None, str(exc)
