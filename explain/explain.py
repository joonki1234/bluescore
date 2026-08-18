"""

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
from typing import List, Optional

from explain import fallback, prompt, render, tip_cache
from explain.contract import (
    LLM_OUTPUT_SCHEMA,
    OBJECTION_OUTPUT_SCHEMA,
    QA_OUTPUT_SCHEMA,
    REPORT_OUTPUT_SCHEMA,
    TIP_OUTPUT_SCHEMA,
    ExplainInput,
    ExplainOutput,
    ReportOutput,
    TextOutput,
)
from explain.provider import (
    LLMProvider,
    Prompts,
    ProviderError,
    ProviderUnavailable,
    get_provider,
)

logger = logging.getLogger(__name__)

# 흐름 이름. `BLUESCORE_LLM_PROVIDER__<이름>` 환경변수로 흐름마다 다른
# 프로바이더를 걸 때의 키가 된다 (`provider.resolve_provider_name` 참고).
FLOW_EXPLAIN = "explain"
FLOW_QA = "qa"
FLOW_OBJECTION = "objection"
FLOW_REPORT = "report"
FLOW_TIP = "tip"

SCHEMA_NAME = "bluescore_explanation"
QA_SCHEMA_NAME = "bluescore_qa"
OBJECTION_SCHEMA_NAME = "bluescore_objection_response"
REPORT_SCHEMA_NAME = "bluescore_detailed_report"
TIP_SCHEMA_NAME = "bluescore_improvement_tip"


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
        llm = provider or get_provider(flow=FLOW_EXPLAIN)
    except ProviderUnavailable as exc:
        logger.info("프로바이더를 만들 수 없어 폴백합니다: %s", exc)
        return fallback.build(data, "provider_unavailable")

    if not llm.is_available():
        logger.info("프로바이더 %s를 사용할 수 없어 폴백합니다.", llm.name)
        return fallback.build(data, f"{llm.name}_unavailable")

    try:
        raw = llm.generate_json(
            prompts=prompt.explain_prompts(data),
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


def _generate_text(
    data: ExplainInput,
    *,
    flow: str,
    prompts: Prompts,
    schema: dict,
    schema_name: str,
    field: str,
    fallback_text: str,
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    check_forbidden_advice: bool = False,
) -> TextOutput:
    """
    문장 하나만 생성하는 흐름(질의응답·이의제기 응답·상세 리포트)의 공통 뼈대.

    `explain()`과 같은 원칙을 따른다 — 어떤 실패든 절대 예외를 던지지 않고
    `fallback_text`로 흡수하며, 사유는 `source`에 남는다.
    """
    if not use_llm:
        return TextOutput(text=fallback_text, source="fallback:llm_disabled")

    try:
        llm = provider or get_provider(flow=flow)
    except ProviderUnavailable as exc:
        logger.info("프로바이더를 만들 수 없어 폴백합니다: %s", exc)
        return TextOutput(text=fallback_text, source="fallback:provider_unavailable")

    if not llm.is_available():
        logger.info("프로바이더 %s를 사용할 수 없어 폴백합니다.", llm.name)
        return TextOutput(text=fallback_text, source=f"fallback:{llm.name}_unavailable")

    try:
        raw = llm.generate_json(
            prompts=prompts,
            schema=schema,
            schema_name=schema_name,
        )
    except ProviderUnavailable as exc:
        logger.info("프로바이더 %s 사용 불가: %s", llm.name, exc)
        return TextOutput(text=fallback_text, source=f"fallback:{llm.name}_unavailable")
    except ProviderError as exc:
        logger.warning("프로바이더 %s 호출 실패: %s", llm.name, exc)
        return TextOutput(text=fallback_text, source=f"fallback:{llm.name}_error")

    text, error = render.safe_parse_text(
        raw, data, field, check_forbidden_advice=check_forbidden_advice
    )
    if error is not None:
        logger.warning("응답 검증 실패, 폴백합니다: %s", error)
        return TextOutput(text=fallback_text, source="fallback:validation_failed")

    return TextOutput(text=text, source=f"llm:{llm.name}")


def answer_question(
    data: ExplainInput, question: str, provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
) -> TextOutput:
    """어업인의 자유 질문에 답한다. `explain()`과 같은 LLM 프로바이더를 재사용한다."""
    return _generate_text(
        data,
        flow=FLOW_QA,
        prompts=prompt.qa_prompts(data, question),
        schema=QA_OUTPUT_SCHEMA,
        schema_name=QA_SCHEMA_NAME,
        field="answer",
        fallback_text=fallback.build_qa_fallback(data, question),
        provider=provider,
        use_llm=use_llm,
    )


def respond_to_objection(
    data: ExplainInput, reason: str, detail: str, provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
) -> TextOutput:
    """이의제기에 대한 답변 초안을 만든다. 심사역이 검토 후 전달한다."""
    return _generate_text(
        data,
        flow=FLOW_OBJECTION,
        prompts=prompt.objection_prompts(data, reason, detail),
        schema=OBJECTION_OUTPUT_SCHEMA,
        schema_name=OBJECTION_SCHEMA_NAME,
        field="response",
        fallback_text=fallback.build_objection_fallback(data, reason, detail),
        provider=provider,
        use_llm=use_llm,
    )


def generate_detailed_report(
    data: ExplainInput, provider: Optional[LLMProvider] = None, use_llm: bool = True
) -> ReportOutput:
    """
    요인별 실측값(factor_metrics)을 근거로 요인마다 한 항목씩 설명을 만든다.

    `_generate_text`와 흐름은 같지만 결과가 문장 하나가 아니라 라벨→문장
    매핑이라 별도로 둔다. 실패는 전부 폴백으로 흡수하며 예외를 던지지 않는다.
    """
    fallback_items = fallback.build_report_fallback(data)

    if not use_llm:
        return ReportOutput(items=fallback_items, source="fallback:llm_disabled")

    try:
        llm = provider or get_provider(flow=FLOW_REPORT)
    except ProviderUnavailable as exc:
        logger.info("프로바이더를 만들 수 없어 폴백합니다: %s", exc)
        return ReportOutput(items=fallback_items, source="fallback:provider_unavailable")

    if not llm.is_available():
        logger.info("프로바이더 %s를 사용할 수 없어 폴백합니다.", llm.name)
        return ReportOutput(items=fallback_items, source=f"fallback:{llm.name}_unavailable")

    try:
        raw = llm.generate_json(
            prompts=prompt.report_prompts(data),
            schema=REPORT_OUTPUT_SCHEMA,
            schema_name=REPORT_SCHEMA_NAME,
        )
    except ProviderUnavailable as exc:
        logger.info("프로바이더 %s 사용 불가: %s", llm.name, exc)
        return ReportOutput(items=fallback_items, source=f"fallback:{llm.name}_unavailable")
    except ProviderError as exc:
        logger.warning("프로바이더 %s 호출 실패: %s", llm.name, exc)
        return ReportOutput(items=fallback_items, source=f"fallback:{llm.name}_error")

    items, error = render.safe_parse_report_items(raw, data)
    if error is not None:
        logger.warning("상세 리포트 검증 실패, 폴백합니다: %s", error)
        return ReportOutput(items=fallback_items, source="fallback:validation_failed")

    # 모델이 일부 요인을 빠뜨려도 화면에 구멍이 나지 않도록 폴백 문장으로 채운다.
    merged = dict(fallback_items)
    merged.update(items)
    return ReportOutput(items=merged, source=f"llm:{llm.name}")


def generate_improvement_tip(
    data: ExplainInput,
    plan_label: str,
    actions: List[str],
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    use_cache: bool = True,
) -> TextOutput:
    """
    개선 조합 하나를 실제 조업에서 어떻게 실천하는지 알려주는 팁.

    점수 변화·금리 변화 같은 수치는 `score/`(지금은 `ui/adapter.simulate`)가
    계산해 카드에 이미 표시된다. 여기서 만드는 것은 **행동 설명뿐**이며,
    프롬프트가 숫자 사용을 금지하고 `render.safe_parse_text`의 숫자 검증이
    그물 역할을 한다.

    사전 생성 캐시를 먼저 본다. 카드가 두 장이라 화면 한 번에 호출이 두 번
    나가는데 앨런은 호출당 6초쯤 걸려서, 캐시가 없으면 시뮬레이터 탭이 14초
    멈춘다. 캐시는 `use_llm`과 무관하게 쓴다 — 이미 만들어 둔 문장을 읽는
    것은 LLM 호출이 아니고, LLM을 꺼둔 환경에서도 템플릿보다 나은 문장을
    보여주는 편이 낫기 때문이다. 템플릿만 보고 싶으면 `use_cache=False`.

    Args:
        use_cache: False면 사전 생성 캐시를 무시하고 매번 생성한다.
    """
    if use_cache:
        cached = tip_cache.lookup(plan_label, actions)
        if cached is not None:
            return cached

    return _generate_text(
        data,
        flow=FLOW_TIP,
        prompts=prompt.improvement_tip_prompts(data, plan_label, actions),
        schema=TIP_OUTPUT_SCHEMA,
        schema_name=TIP_SCHEMA_NAME,
        field="tip",
        fallback_text=fallback.build_improvement_tip_fallback(actions),
        provider=provider,
        use_llm=use_llm,
        # 팁만 조언 내용을 검사한다. "다른 어장으로 옮기라"는 말이 섞이면
        # 연료를 더 태워 B축이 깎여서, 점수를 올리려는 사람에게 정반대다.
        check_forbidden_advice=True,
    )
