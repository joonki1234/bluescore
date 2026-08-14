"""
담당: 최지희

설명 계층의 공개 진입점.

    from explain import explain, ExplainInput
    result = explain(data)
    result.summary            # 요약 문장
    result.recommendations    # 개선 코칭
    result.source             # "llm:openai" 또는 "fallback:<사유>"

호출부(ui/adapter.py)는 이 함수 하나만 알면 된다. 어떤 LLM을 쓰는지,
호출이 실패했는지, 폴백으로 떨어졌는지는 `source`에 담겨 돌아온다.

**절대 예외를 던지지 않는다.** 설명이 없다고 화면이 비면 안 되기 때문에,
어떤 실패든 템플릿 폴백으로 흡수하고 그 사유를 `source`에 남긴다.
"""

from __future__ import annotations

import logging
from typing import Optional

from explain import fallback, prompt, render
from explain.contract import LLM_OUTPUT_SCHEMA, ExplainInput, ExplainOutput
from explain.provider import (
    LLMProvider,
    ProviderError,
    ProviderUnavailable,
    get_provider,
)

logger = logging.getLogger(__name__)

SCHEMA_NAME = "bluescore_explanation"


def explain(
    data: ExplainInput,
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
) -> ExplainOutput:
    """
    계산 결과를 어업인이 읽을 수 있는 설명으로 바꾼다.

    Args:
        data: 점수·SHAP 기여도 등 계산 결과
        provider: 직접 주입할 프로바이더 (테스트용). 없으면 환경변수로 결정
        use_llm: False면 LLM을 아예 호출하지 않고 템플릿만 쓴다

    Returns:
        항상 유효한 ExplainOutput. 실패해도 폴백이 채워진다.
    """
    if not use_llm:
        return fallback.build(data, "llm_disabled")

    try:
        llm = provider or get_provider()
    except ProviderUnavailable as exc:
        logger.info("프로바이더를 만들 수 없어 폴백합니다: %s", exc)
        return fallback.build(data, "provider_unavailable")

    if not llm.is_available():
        logger.info("프로바이더 %s를 사용할 수 없어 폴백합니다.", llm.name)
        return fallback.build(data, f"{llm.name}_unavailable")

    try:
        raw = llm.generate_json(
            system_prompt=prompt.SYSTEM_PROMPT,
            user_prompt=prompt.build_user_prompt(data),
            schema=LLM_OUTPUT_SCHEMA,
            schema_name=SCHEMA_NAME,
        )
    except ProviderUnavailable as exc:
        logger.info("프로바이더 %s 사용 불가: %s", llm.name, exc)
        return fallback.build(data, f"{llm.name}_unavailable")
    except ProviderError as exc:
        logger.warning("프로바이더 %s 호출 실패: %s", llm.name, exc)
        return fallback.build(data, f"{llm.name}_error")

    summary, recommendations, error = render.safe_parse(raw, data)
    if error is not None:
        # 검증 실패는 조용히 넘기지 않는다. 특히 숫자 창작은 프롬프트를
        # 고쳐야 하는 신호라 로그에 남긴다.
        logger.warning("응답 검증 실패, 폴백합니다: %s", error)
        return fallback.build(data, "validation_failed")

    return ExplainOutput(
        summary=summary,
        shap_factors=list(data.shap_factors),
        recommendations=recommendations,
        source=f"llm:{llm.name}",
    )
