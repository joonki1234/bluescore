"""
담당: 최지희

프로바이더 라우팅·앨런 키 로테이션·강등 체인 테스트.

여기서 지키려는 것은 세 가지다.

1. **키가 마르면 다음 키로 넘어간다.** 앨런은 키당 호출 쿼터가 있어서
   (실측: 성공 호출 약 100회 후 401) 발표 도중 마를 수 있다.
2. **앨런이 다 마르면 OpenAI가 이어받는다.** 화면이 템플릿 문장으로
   떨어지는 것은 마지막 수단이어야 한다.
3. **압축 프롬프트가 앨런 URL 한도 안에 있다.** 넘으면 414라 조용한 실패가
   아니라 전량 폴백이 된다. 프롬프트를 손볼 때 이 테스트가 그물이 된다.

실행: pytest explain/test_provider.py
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any, Dict, List

import pytest

from explain import prompt
from explain.contract import (
    LLM_OUTPUT_SCHEMA,
    OBJECTION_OUTPUT_SCHEMA,
    QA_OUTPUT_SCHEMA,
    REPORT_OUTPUT_SCHEMA,
    TIP_OUTPUT_SCHEMA,
)
from explain.explain import explain
from explain.provider import (
    ChainProvider,
    LLMProvider,
    Prompts,
    ProviderError,
    ProviderUnavailable,
    get_provider,
    resolve_provider_name,
)
from explain.providers import alan_provider
from explain.providers.alan_provider import AlanProvider
from explain.test_explain import StubProvider, make_input, valid_response

KEY_A = "11111111-1111-1111-1111-111111111111"
KEY_B = "22222222-2222-2222-2222-222222222222"

TIP_JSON = json.dumps({"tip": "같은 자리를 연달아 훑지 말고 하루 걸러 가 보세요. "
                              "이동할 때는 엔진을 무리하게 밀지 마세요."}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def clean_key_state(monkeypatch):
    """키 소진 표시는 프로세스 전역이라 테스트마다 지운다."""
    alan_provider.reset_exhausted_keys()
    monkeypatch.delenv("ALAN_API_KEY", raising=False)
    yield
    alan_provider.reset_exhausted_keys()


class FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


def fake_urlopen(script: Dict[str, Any], calls: List[str]):
    """
    client_id별 응답을 미리 정해두는 가짜 urlopen.

    값이 예외면 던지고, 아니면 `{"answer": 값}`으로 돌려준다.
    """
    def _open(url, timeout=None):  # noqa: ARG001
        client_id = url.split("client_id=")[1].split("&")[0]
        calls.append(client_id)
        outcome = script[client_id]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse({"answer": outcome})

    return _open


def tip_prompts() -> Prompts:
    return prompt.improvement_tip_prompts(
        make_input(), "가장 쉬운 개선", ["어장을 오갈 때의 평균 항해 속도를 낮춘다"]
    )


# ─── 키 목록 파싱 ────────────────────────────────────────────────────────────
def test_키를_콤마로_여러_개_받는다(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", f" {KEY_A} , {KEY_B} , ")
    assert alan_provider.api_keys() == [KEY_A, KEY_B]


def test_키가_없으면_사용_불가(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", "")
    assert AlanProvider().is_available() is False


# ─── 키 로테이션 ─────────────────────────────────────────────────────────────
def test_첫_키가_소진되면_다음_키로_넘어간다(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", f"{KEY_A},{KEY_B}")
    calls: List[str] = []
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        fake_urlopen({KEY_A: http_error(401), KEY_B: TIP_JSON}, calls),
    )

    raw = AlanProvider().generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")

    assert json.loads(raw)["tip"]
    assert calls == [KEY_A, KEY_B], "같은 요청을 다음 키로 재시도해야 한다"
    assert alan_provider.live_keys() == [KEY_B], "소진된 키는 목록에서 빠진다"


def test_소진된_키는_다음_호출에서_아예_건너뛴다(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", f"{KEY_A},{KEY_B}")
    calls: List[str] = []
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        fake_urlopen({KEY_A: http_error(401), KEY_B: TIP_JSON}, calls),
    )
    provider = AlanProvider()
    provider.generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")
    calls.clear()

    provider.generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")

    assert calls == [KEY_B], "이미 마른 키를 매번 다시 찌르지 않는다"


def test_모든_키가_소진되면_사용_불가로_던진다(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", f"{KEY_A},{KEY_B}")
    calls: List[str] = []
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        fake_urlopen({KEY_A: http_error(401), KEY_B: http_error(401)}, calls),
    )

    with pytest.raises(ProviderUnavailable):
        AlanProvider().generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")
    assert alan_provider.live_keys() == []


def test_401이_아닌_실패는_키를_소진_처리하지_않는다(monkeypatch):
    """500은 서버 문제지 키 문제가 아니다. 여기서 키를 버리면 쿼터를 낭비한다."""
    monkeypatch.setenv("ALAN_API_KEY", f"{KEY_A},{KEY_B}")
    calls: List[str] = []
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        fake_urlopen({KEY_A: http_error(500), KEY_B: TIP_JSON}, calls),
    )

    with pytest.raises(ProviderError) as exc:
        AlanProvider().generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")

    assert not isinstance(exc.value, ProviderUnavailable)
    assert calls == [KEY_A], "다음 키로 넘기지 않는다"
    assert alan_provider.live_keys() == [KEY_A, KEY_B]


def test_응답에_answer가_없으면_호출_실패(monkeypatch):
    monkeypatch.setenv("ALAN_API_KEY", KEY_A)
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        lambda url, timeout=None: FakeResponse({"message": "오류"}),
    )
    with pytest.raises(ProviderError):
        AlanProvider().generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")


# ─── URL 길이 가드 ───────────────────────────────────────────────────────────
def test_프롬프트가_길면_호출_전에_막는다(monkeypatch):
    """414는 키를 바꿔도 똑같이 난다. 네트워크를 타기 전에 잡아야 한다."""
    monkeypatch.setenv("ALAN_API_KEY", f"{KEY_A},{KEY_B}")
    calls: List[str] = []
    monkeypatch.setattr(
        alan_provider.urllib.request, "urlopen",
        fake_urlopen({KEY_A: TIP_JSON, KEY_B: TIP_JSON}, calls),
    )
    huge = Prompts(system="s", user="u", compact_system="s", compact_user="가" * 5000)

    with pytest.raises(ProviderError, match="URL 한도"):
        AlanProvider().generate_json(huge, TIP_OUTPUT_SCHEMA, "tip")
    assert calls == [], "네트워크를 타지 않는다"


@pytest.mark.parametrize(
    "prompts",
    [
        pytest.param(prompt.explain_prompts(make_input()), id="explain"),
        pytest.param(prompt.qa_prompts(make_input(), "왜 점수가 낮나요?"), id="qa"),
        pytest.param(prompt.objection_prompts(make_input(), "데이터 오류", "출항한 적 없습니다"), id="objection"),
        pytest.param(prompt.report_prompts(make_input()), id="report"),
        pytest.param(
            prompt.improvement_tip_prompts(make_input(), "가장 쉬운 개선", ["평균 항해 속도를 낮춘다"]),
            id="tip",
        ),
    ],
)
def test_압축_프롬프트가_앨런_URL_한도_안에_있다(prompts):
    """
    프롬프트를 늘리다 한도를 넘기면 앨런이 414로 전량 거부한다. 화면에는
    "폴백"으로만 보여서 원인을 찾기 어렵다 — 그래서 여기서 미리 막는다.
    """
    system_prompt, user_prompt = prompts.resolve(compact=True)
    content = f"{system_prompt}\n\n{user_prompt}"
    url = alan_provider._build_url(content, KEY_A)
    assert len(url.encode("utf-8")) <= alan_provider.MAX_URL_BYTES


def test_원본_프롬프트는_한도를_넘는다():
    """압축본이 왜 필요한지 못 박아 둔다. 이게 깨지면 압축을 걷어내도 된다."""
    system_prompt, user_prompt = prompt.explain_prompts(make_input()).resolve(compact=False)
    url = alan_provider._build_url(f"{system_prompt}\n\n{user_prompt}", KEY_A)
    assert len(url.encode("utf-8")) > alan_provider.MAX_URL_BYTES


# ─── 프롬프트 선택 ───────────────────────────────────────────────────────────
def test_앨런은_압축본_OpenAI는_원본을_받는다():
    prompts = prompt.explain_prompts(make_input())
    compact_system, compact_user = prompts.resolve(compact=True)
    full_system, full_user = prompts.resolve(compact=False)

    assert "참고 사실" in full_user, "원본에는 참고 사실 블록이 있다"
    assert "참고 사실" not in compact_user, "압축본은 참고 사실 블록을 뺀다"
    assert len(compact_system) < len(full_system)


def test_압축본이_없으면_원본으로_떨어진다():
    prompts = Prompts(system="s", user="u")
    assert prompts.resolve(compact=True) == ("s", "u")


# ─── 강등 체인 ───────────────────────────────────────────────────────────────
def test_체인은_앞이_실패하면_뒤가_이어받는다():
    dead = StubProvider(error=ProviderUnavailable("소진"))
    dead.name = "alan"
    alive = StubProvider(response=TIP_JSON)
    alive.name = "openai"
    chain = ChainProvider([dead, alive])

    raw = chain.generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")

    assert raw == TIP_JSON
    assert chain.name == "openai", "출처 표시는 실제로 답한 쪽이어야 한다"


def test_체인_이름은_호출_전에는_구성을_보여준다():
    first = StubProvider(response="{}")
    first.name = "alan"
    second = StubProvider(response="{}")
    second.name = "openai"
    assert ChainProvider([first, second]).name == "alan+openai"


def test_체인은_사용_불가한_백엔드를_건너뛴다():
    unavailable = StubProvider(response="쓰이면 안 됨", available=False)
    unavailable.name = "alan"
    alive = StubProvider(response=TIP_JSON)
    alive.name = "openai"

    chain = ChainProvider([unavailable, alive])
    assert chain.is_available() is True
    assert chain.generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip") == TIP_JSON


def test_체인이_전부_실패하면_사용_불가로_던진다():
    a = StubProvider(error=ProviderError("호출 실패"))
    a.name = "alan"
    b = StubProvider(error=ProviderError("호출 실패"))
    b.name = "openai"

    with pytest.raises(ProviderUnavailable):
        ChainProvider([a, b]).generate_json(tip_prompts(), TIP_OUTPUT_SCHEMA, "tip")


def test_앨런이_마르면_설명은_OpenAI_출처로_돌아온다():
    """화면 `source` 규약까지 통째로 확인한다 — 강등돼도 템플릿이 아니어야 한다."""
    dead = StubProvider(error=ProviderUnavailable("키 전부 소진"))
    dead.name = "alan"
    alive = StubProvider(response=valid_response())
    alive.name = "openai"

    result = explain(make_input(), provider=ChainProvider([dead, alive]))

    assert result.source == "llm:openai"
    assert result.is_fallback is False


def test_체인이_전부_죽으면_템플릿_폴백():
    dead_a = StubProvider(error=ProviderUnavailable("소진"))
    dead_a.name = "alan"
    dead_b = StubProvider(error=ProviderError("호출 실패"))
    dead_b.name = "openai"

    result = explain(make_input(), provider=ChainProvider([dead_a, dead_b]))

    assert result.is_fallback is True
    assert result.summary


# ─── 흐름별 라우팅 ───────────────────────────────────────────────────────────
def test_흐름별_환경변수가_전역보다_우선한다(monkeypatch):
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER__TIP", "alan+openai")

    assert resolve_provider_name("tip") == "alan+openai"
    assert resolve_provider_name("qa") == "openai"
    assert resolve_provider_name("") == "openai"


def test_흐름별_변수가_없으면_전역으로_떨어진다(monkeypatch):
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER", "openai")
    monkeypatch.delenv("BLUESCORE_LLM_PROVIDER__TIP", raising=False)
    assert resolve_provider_name("tip") == "openai"


def test_빈_값은_설정하지_않은_것으로_본다(monkeypatch):
    """`.env`에 키만 써두고 값을 비워두는 일이 흔하다."""
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER", "")
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER__TIP", "  ")
    assert resolve_provider_name("tip") == "openai"


def test_체인_프로바이더가_레지스트리에_등록돼_있다():
    assert isinstance(get_provider("alan+openai"), ChainProvider)


def test_모르는_프로바이더는_사용_불가로_던진다(monkeypatch):
    monkeypatch.setenv("BLUESCORE_LLM_PROVIDER__TIP", "gemini")
    with pytest.raises(ProviderUnavailable, match="알 수 없는 프로바이더"):
        get_provider(flow="tip")
