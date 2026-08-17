"""
담당: 최지희

설명 계층 테스트.

가장 중요한 것은 **숫자 검증**이다. "AI는 숫자를 만들지 않는다"가 프롬프트의
부탁이 아니라 코드로 강제되는지 확인한다.

실행: pytest explain/
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from explain import fallback, render
from explain.contract import ExplainInput, ExplainOutput, FactorMetric, ShapFactor
from explain.explain import answer_question, explain, generate_detailed_report, respond_to_objection
from explain.provider import LLMProvider, ProviderError, ProviderUnavailable


def make_input(**overrides: Any) -> ExplainInput:
    defaults: Dict[str, Any] = {
        "vessel_id": "VESSEL_A",
        "vessel_label": "근해통발 · 29톤 · 남해",
        "fleet_label": "근해통발 · 20–30톤 · 남해 · 하계",
        "blue_score": 72.6,
        "axis_a_score": 81.0,
        "axis_b_score": 57.0,
        "peer_count": 42,
        "top_percent": 17,
        "fuel_delta_percent": 8.0,
        "shap_factors": [
            ShapFactor("동일 격자 재방문 간격", 6.2, "a"),
            ShapFactor("혼잡 어장 회피", 3.1, "a"),
            ShapFactor("조업 시간당 연료", -3.6, "b"),
            ShapFactor("항해 속도", -5.4, "b"),
        ],
        "factor_metrics": [
            FactorMetric("동일 격자 재방문 간격", "a", 18.4, 14.2, "시간"),
            FactorMetric("항해 속도", "b", 10.4, 9.1, "노트"),
        ],
    }
    defaults.update(overrides)
    return ExplainInput(**defaults)


class StubProvider(LLMProvider):
    """지정한 문자열을 그대로 반환하거나 예외를 던지는 테스트용 프로바이더."""

    name = "stub"

    def __init__(self, response: str = "", error: Exception = None, available: bool = True):
        self._response = response
        self._error = error
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def generate_json(self, system_prompt, user_prompt, schema, schema_name) -> str:
        if self._error is not None:
            raise self._error
        return self._response


def valid_response(summary: str = "", recommendations: List[Dict[str, str]] = None) -> str:
    return json.dumps(
        {
            "summary": summary or "같은 어장을 연속으로 긁지 않는 편이라 자원 압력 점수가 높습니다.",
            "recommendations": recommendations
            or [{"action": "평균 항해 속도를 1노트 낮춰 보세요", "axis": "b"}],
        },
        ensure_ascii=False,
    )


# ─── 숫자 검증 ───────────────────────────────────────────────────────────────
def test_입력에_있는_숫자는_통과한다():
    data = make_input()
    text = "BlueScore는 72.6점이고 42척 중 상위 17%입니다. 연료를 8% 더 씁니다."
    assert render.find_invented_numbers(text, data) == []


def test_입력에_없는_숫자는_잡힌다():
    data = make_input()
    text = "비슷한 배들보다 연료를 23% 더 씁니다."
    assert render.find_invented_numbers(text, data) == [23.0]


def test_표기_차이는_창작이_아니다():
    """8.0을 8로 쓰거나 72.6을 73으로 반올림하는 것은 허용한다."""
    data = make_input()
    text = "연료를 8% 더 쓰고, 점수는 73점입니다."
    assert render.find_invented_numbers(text, data) == []


def test_작은_정수와_연도는_허용한다():
    """'두 축', '3회', '2027년' 같은 표현까지 막으면 문장을 쓸 수 없다."""
    data = make_input()
    text = "점수는 2개 축으로 나뉘고, 6개월 기준입니다. 2027년에 제도가 바뀝니다."
    assert render.find_invented_numbers(text, data) == []


def test_기여도_값도_허용_집합에_들어간다():
    data = make_input()
    text = "동일 격자 재방문 간격이 6.2만큼 점수를 올렸습니다."
    assert render.find_invented_numbers(text, data) == []


def test_음수_기여도의_절댓값도_허용한다():
    """'항해 속도가 5.4점 깎았습니다'처럼 부호를 떼고 쓰는 것은 자연스럽다."""
    data = make_input()
    text = "항해 속도가 5.4점을 깎았습니다."
    assert render.find_invented_numbers(text, data) == []


def test_창작된_숫자가_있으면_파싱이_실패한다():
    data = make_input()
    raw = valid_response(summary="비슷한 배들보다 연료를 99% 더 씁니다.")
    with pytest.raises(render.RenderError, match="입력에 없는 수치"):
        render.parse_and_validate(raw, data)


def test_개선제안의_숫자도_검증한다():
    """요약뿐 아니라 개선 코칭 문장도 대상이다."""
    data = make_input()
    raw = valid_response(
        recommendations=[{"action": "속도를 47노트 낮추세요", "axis": "b"}]
    )
    with pytest.raises(render.RenderError, match="입력에 없는 수치"):
        render.parse_and_validate(raw, data)


# ─── 구조 검증 ───────────────────────────────────────────────────────────────
def test_정상_응답을_파싱한다():
    data = make_input()
    summary, recommendations = render.parse_and_validate(valid_response(), data)
    assert summary
    assert len(recommendations) == 1
    assert recommendations[0].axis == "b"


def test_코드펜스로_감싼_응답도_파싱한다():
    data = make_input()
    raw = "```json\n" + valid_response() + "\n```"
    summary, _ = render.parse_and_validate(raw, data)
    assert summary


def test_깨진_JSON은_실패한다():
    data = make_input()
    with pytest.raises(render.RenderError, match="JSON 파싱 실패"):
        render.parse_and_validate("{not json", data)


def test_빈_요약은_실패한다():
    data = make_input()
    raw = json.dumps({"summary": "   ", "recommendations": []}, ensure_ascii=False)
    with pytest.raises(render.RenderError, match="summary"):
        render.parse_and_validate(raw, data)


def test_알_수_없는_축_코드는_실패한다():
    data = make_input()
    raw = valid_response(recommendations=[{"action": "무언가 하세요", "axis": "c"}])
    with pytest.raises(render.RenderError, match="axis"):
        render.parse_and_validate(raw, data)


def test_개선제안이_비면_실패한다():
    data = make_input()
    raw = json.dumps({"summary": "요약입니다.", "recommendations": []}, ensure_ascii=False)
    with pytest.raises(render.RenderError, match="recommendations"):
        render.parse_and_validate(raw, data)


# ─── 폴백 ────────────────────────────────────────────────────────────────────
def test_폴백은_LLM_없이_결과를_만든다():
    result = fallback.build(make_input(), "test")
    assert result.summary
    assert result.recommendations
    assert result.is_fallback


def test_폴백_요약은_창작된_숫자를_쓰지_않는다():
    """템플릿도 검증을 통과해야 한다 — 같은 규칙을 스스로 지키는지 확인."""
    data = make_input()
    result = fallback.build(data, "test")
    combined = " ".join([result.summary] + [r.action for r in result.recommendations])
    assert render.find_invented_numbers(combined, data) == []


def test_깎은_요인이_없으면_유지_제안을_만든다():
    """이미 잘하는 배에게 억지 개선 지시를 만들지 않는다."""
    data = make_input(
        shap_factors=[
            ShapFactor("재방문 간격 확보", 7.4, "a"),
            ShapFactor("경제속도 준수", 4.8, "b"),
        ]
    )
    result = fallback.build(data, "test")
    assert result.recommendations
    assert any("유지" in r.action for r in result.recommendations)


def test_연료를_덜_쓰면_문장이_달라진다():
    data = make_input(fuel_delta_percent=-6.0)
    result = fallback.build(data, "test")
    assert "적게" in result.summary


# ─── 진입점 ──────────────────────────────────────────────────────────────────
def test_LLM_비활성화시_폴백한다():
    result = explain(make_input(), use_llm=False)
    assert result.source == "fallback:llm_disabled"


def test_프로바이더가_없으면_폴백한다():
    result = explain(make_input(), provider=StubProvider(available=False))
    assert result.source == "fallback:stub_unavailable"


def test_호출_실패시_폴백한다():
    result = explain(make_input(), provider=StubProvider(error=ProviderError("boom")))
    assert result.source == "fallback:stub_error"


def test_미구현_프로바이더는_unavailable로_폴백한다():
    result = explain(
        make_input(), provider=StubProvider(error=ProviderUnavailable("미구현"))
    )
    assert result.source == "fallback:stub_unavailable"


def test_검증_실패시_폴백한다():
    """LLM이 숫자를 지어내면 그 응답은 버려진다."""
    bad = valid_response(summary="연료를 99% 더 씁니다.")
    result = explain(make_input(), provider=StubProvider(response=bad))
    assert result.source == "fallback:validation_failed"
    assert "99" not in result.summary


def test_정상_응답은_그대로_쓴다():
    result = explain(make_input(), provider=StubProvider(response=valid_response()))
    assert result.source == "llm:stub"
    assert not result.is_fallback


def test_shap_기여도는_LLM을_거치지_않는다():
    """계산 결과는 그대로 통과해야 한다."""
    data = make_input()
    result = explain(data, provider=StubProvider(response=valid_response()))
    assert result.shap_factors == data.shap_factors


def test_어떤_경우에도_예외를_던지지_않는다():
    """화면이 비지 않게 하는 것이 이 계층의 계약이다."""
    for provider in [
        StubProvider(response="깨진 응답"),
        StubProvider(error=ProviderError("네트워크 오류")),
        StubProvider(available=False),
        StubProvider(response=""),
    ]:
        result = explain(make_input(), provider=provider)
        assert isinstance(result, ExplainOutput)
        assert result.summary
        assert result.recommendations


# ─── 직렬화 ──────────────────────────────────────────────────────────────────
# ─── 질의응답 / 이의제기 응답 / 상세 리포트 ────────────────────────────────────
def test_QA_LLM_없으면_폴백한다():
    result = answer_question(make_input(), "왜 점수가 깎였나요?", provider=StubProvider(available=False))
    assert result.is_fallback
    assert result.text


def test_QA_정상_응답은_그대로_쓴다():
    raw = json.dumps({"answer": "항해 속도가 빨라 연료를 더 씁니다."}, ensure_ascii=False)
    result = answer_question(make_input(), "왜 점수가 깎였나요?", provider=StubProvider(response=raw))
    assert result.source == "llm:stub"
    assert "항해 속도" in result.text


def test_QA_창작된_숫자는_폴백한다():
    raw = json.dumps({"answer": "연료를 99% 더 씁니다."}, ensure_ascii=False)
    result = answer_question(make_input(), "질문", provider=StubProvider(response=raw))
    assert result.source == "fallback:validation_failed"


def test_이의제기_응답_LLM_없으면_폴백한다():
    result = respond_to_objection(
        make_input(), "데이터 매칭 오류", "어업종이 다르게 매칭됐습니다.",
        provider=StubProvider(available=False),
    )
    assert result.is_fallback
    assert "데이터 매칭 오류" in result.text


def test_이의제기_응답_정상_응답은_그대로_쓴다():
    raw = json.dumps({"response": "말씀하신 매칭 오류 가능성을 확인 중입니다."}, ensure_ascii=False)
    result = respond_to_objection(
        make_input(), "데이터 매칭 오류", "상세", provider=StubProvider(response=raw)
    )
    assert result.source == "llm:stub"


def test_상세리포트_LLM_없으면_factor_metrics로_폴백한다():
    result = generate_detailed_report(make_input(), provider=StubProvider(available=False))
    assert result.is_fallback
    assert "동일 격자 재방문 간격" in result.text


def test_상세리포트_정상_응답은_그대로_쓴다():
    raw = json.dumps(
        {"report": "동일 격자 재방문 간격이 유사군 평균보다 길어 자원 압력이 낮습니다."},
        ensure_ascii=False,
    )
    result = generate_detailed_report(make_input(), provider=StubProvider(response=raw))
    assert result.source == "llm:stub"


def test_어떤_경우에도_텍스트_생성_함수는_예외를_던지지_않는다():
    for provider in [
        StubProvider(response="깨진 응답"),
        StubProvider(error=ProviderError("네트워크 오류")),
        StubProvider(available=False),
    ]:
        for fn, args in [
            (answer_question, ("질문",)),
            (respond_to_objection, ("사유", "상세")),
            (generate_detailed_report, ()),
        ]:
            result = fn(make_input(), *args, provider=provider)
            assert result.text


def test_mock_스키마와_같은_키로_직렬화된다():
    """data/mock/README_mock_data 제안.md 5번의 키 이름을 따른다."""
    result = fallback.build(make_input(), "test")
    payload = result.as_dict()
    assert set(payload) == {"summary", "shapFactors", "recommendations", "source"}
    assert set(payload["shapFactors"][0]) == {"label", "value", "axis"}
    assert set(payload["recommendations"][0]) == {"action", "axis"}
