"""
담당: 최지희

OpenAI 프로바이더 — 기본값이자 앨런의 강등 대상.

앨런은 URL 길이 한도와 호출 쿼터가 있어 흐름 전체를 맡기지 않고, 흐름별로
`alan+openai` 체인을 걸어 앨런이 답하지 못할 때 이 프로바이더가 이어받는다
(`provider.py`의 `ChainProvider` 참고).

환경변수
--------
    OPENAI_API_KEY        필수
    BLUESCORE_LLM_MODEL   선택. 기본 "gpt-4o-mini"
    OPENAI_BASE_URL       선택. 프록시·호환 엔드포인트를 쓸 때

구조화 출력
----------
Chat Completions의 `response_format`에 JSON Schema를 걸어 응답 모양을
강제한다. strict 모드는 모든 객체에 `additionalProperties: false`가 있고
모든 속성이 `required`에 들어 있어야 하는데, `contract.LLM_OUTPUT_SCHEMA`가
그 조건을 만족하도록 작성돼 있다.

그래도 `render.py`가 다시 검증한다. 스키마 강제는 구조만 보장하지 내용은
보장하지 않고 — 특히 **숫자를 지어내는 것은 스키마로 막히지 않는다**.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from explain.provider import LLMProvider, Prompts, ProviderError, ProviderUnavailable

# 기본 모델. 짧은 한국어 문장 생성이라 소형 모델로 충분하다.
# 바꾸려면 코드가 아니라 BLUESCORE_LLM_MODEL 환경변수로 바꾼다.
DEFAULT_MODEL = "gpt-4o-mini"

# 문장 2~3개 + 개선 제안 3개면 충분한 길이
MAX_OUTPUT_TOKENS = 900

# 설명 문구는 매번 크게 흔들리지 않는 편이 낫다. 같은 점수에 매번 다른 말이
# 나오면 어업인이 혼란스럽고, 시연에서도 재현이 안 된다.
TEMPERATURE = 0.3

# 네트워크가 느릴 때 화면이 오래 멈추지 않도록. 초과하면 폴백으로 넘어간다.
REQUEST_TIMEOUT_SECONDS = 20.0


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        self._model = os.getenv("BLUESCORE_LLM_MODEL", DEFAULT_MODEL)

    def is_available(self) -> bool:
        if not os.getenv("OPENAI_API_KEY"):
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise ProviderUnavailable(
                "openai 패키지가 설치되어 있지 않습니다. pip install openai"
            ) from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderUnavailable("OPENAI_API_KEY가 설정되어 있지 않습니다.")

        kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": REQUEST_TIMEOUT_SECONDS}
        base_url = os.getenv("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    def generate_json(
        self,
        prompts: Prompts,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        client = self._client()

        # 압축본은 앨런의 URL 한도 때문에 있는 것이고, OpenAI는 그 제약이 없다.
        # 체인에서 앨런이 죽어 여기로 넘어와도 참고 사실 블록이 살아 있는 원본을
        # 쓴다 — 강등됐다고 근거까지 줄어들면 안 된다.
        system_prompt, user_prompt = prompts.resolve(compact=False)

        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=TEMPERATURE,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:  # SDK 예외 계층이 버전마다 달라 넓게 잡는다
            raise ProviderError(f"OpenAI 호출 실패: {exc}") from exc

        if not response.choices:
            raise ProviderError("응답에 choices가 없습니다.")

        choice = response.choices[0]

        # 길이 초과로 잘린 응답은 JSON이 깨져 있다. 파싱 실패로 흘려보내지 말고
        # 여기서 사유를 분명히 해 둔다.
        if choice.finish_reason == "length":
            raise ProviderError(
                f"응답이 최대 길이({MAX_OUTPUT_TOKENS} 토큰)에서 잘렸습니다."
            )

        content = choice.message.content
        if not content:
            # strict 스키마를 만족하는 응답을 만들지 못하면 refusal이 온다.
            refusal = getattr(choice.message, "refusal", None)
            if refusal:
                raise ProviderError(f"모델이 응답을 거부했습니다: {refusal}")
            raise ProviderError("응답 본문이 비어 있습니다.")

        return content
