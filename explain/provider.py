"""
담당: 최지희

LLM 프로바이더 추상과 레지스트리.

화면과 `explain.py`는 이 인터페이스만 안다. 어떤 LLM을 쓰는지는
`BLUESCORE_LLM_PROVIDER` 환경변수 하나로 바뀌고, 나머지 코드는 그대로다.

**앨런 API를 아직 못 쓰는 상태이므로 기본 프로바이더는 OpenAI다.**
운영진에게서 앨런 API 접근 정보를 받으면 `providers/alan.py`를 채우고
환경변수만 `alan`으로 바꾸면 된다. 그 외에는 아무것도 손대지 않는다.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict


class ProviderError(RuntimeError):
    """프로바이더 호출 실패. 호출부는 폴백으로 강등한다."""


class ProviderUnavailable(ProviderError):
    """
    설정이 안 됐거나 미구현이라 아예 호출할 수 없다.

    호출 실패(ProviderError)와 구분하는 이유는 화면에 다른 사유를 보여주기
    위해서다 — "API 키 없음"과 "호출 실패"는 사용자가 할 일이 다르다.
    """


class LLMProvider(ABC):
    """설명 문장을 생성하는 LLM 프로바이더."""

    #: 화면·로그에 표시할 이름
    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """지금 호출할 수 있는 상태인가 (키·의존 패키지 확인)."""

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        """
        스키마를 만족하는 JSON 문자열을 생성한다.

        구조 강제는 프로바이더가 할 수 있으면 하고, 못 해도 된다 —
        `render.py`가 어차피 다시 검증한다.

        Raises:
            ProviderUnavailable: 키 없음 / 패키지 없음 / 미구현
            ProviderError: 호출 실패
        """


# ─── 레지스트리 ──────────────────────────────────────────────────────────────
_REGISTRY: Dict[str, Callable[[], LLMProvider]] = {}

DEFAULT_PROVIDER = "openai"
PROVIDER_ENV_VAR = "BLUESCORE_LLM_PROVIDER"


def register(name: str, factory: Callable[[], LLMProvider]) -> None:
    _REGISTRY[name] = factory


def available_providers() -> list:
    return sorted(_REGISTRY)


def get_provider(name: str = "") -> LLMProvider:
    """
    프로바이더를 만든다.

    이름을 주지 않으면 `BLUESCORE_LLM_PROVIDER` 환경변수를 보고, 그것도
    없으면 기본값(openai)을 쓴다.
    """
    resolved = name or os.getenv(PROVIDER_ENV_VAR, DEFAULT_PROVIDER)
    factory = _REGISTRY.get(resolved)
    if factory is None:
        raise ProviderUnavailable(
            f"알 수 없는 프로바이더: {resolved!r} "
            f"(사용 가능: {', '.join(available_providers())})"
        )
    return factory()


def _register_builtins() -> None:
    """
    내장 프로바이더 등록.

    임포트를 함수 안에서 하는 이유는 순환 임포트를 피하고, 프로바이더 모듈이
    무거운 SDK를 모듈 로드 시점에 끌어오지 않게 하기 위해서다.
    """
    from explain.providers.alan_provider import AlanProvider
    from explain.providers.openai_provider import OpenAIProvider

    register("openai", OpenAIProvider)
    register("alan", AlanProvider)


_register_builtins()
