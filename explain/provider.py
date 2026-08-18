"""

LLM 프로바이더 추상과 레지스트리.

화면과 `explain.py`는 이 인터페이스만 안다. 어떤 LLM을 쓰는지는 환경변수로
바뀌고, 나머지 코드는 그대로다.

프로바이더 배치
--------------
기본은 OpenAI이고, 흐름(explain·qa·objection·report·tip)마다 따로 덮어쓸 수
있다. 앨런은 URL 길이 한도와 호출 쿼터가 있어 흐름 전체를 맡기지 않고
`alan+openai` 체인으로 붙인다 — 앨런이 답하다가 쿼터가 마르면 OpenAI가
이어받고, 둘 다 죽으면 `explain.py`가 템플릿으로 강등한다.

    BLUESCORE_LLM_PROVIDER=openai              기본값
    BLUESCORE_LLM_PROVIDER__TIP=alan+openai    흐름별 덮어쓰기

흐름별 변수가 없으면 기본값으로 떨어지므로, 아무것도 걸지 않으면 지금까지와
똑같이 전부 OpenAI로 나간다.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """프로바이더 호출 실패. 호출부는 폴백으로 강등한다."""


class ProviderUnavailable(ProviderError):
    """
    설정이 안 됐거나 쓸 수 없어 아예 호출할 수 없다.

    호출 실패(ProviderError)와 구분하는 이유는 화면에 다른 사유를 보여주기
    위해서다 — "API 키 없음"과 "호출 실패"는 사용자가 할 일이 다르다.
    """


@dataclass(frozen=True)
class Prompts:
    """
    한 번의 생성에 쓰는 프롬프트 한 벌.

    원본과 압축본을 함께 들고 다닌다. 앨런은 프롬프트를 URL 쿼리에 실어야 해서
    약 7KB 한도가 걸리는데, 참고 사실 블록이 들어간 원본은 그 한도를 넘는다.
    그렇다고 호출 전에 압축본 하나만 만들어 넘기면 앨런이 쿼터로 죽어 OpenAI가
    이어받을 때 OpenAI까지 참고 사실을 잃는다. 그래서 **고르는 쪽을 프로바이더로
    미룬다** — 각자 자기가 감당할 수 있는 것을 가져간다.
    """

    system: str
    user: str
    compact_system: str = ""
    compact_user: str = ""

    def resolve(self, compact: bool) -> Tuple[str, str]:
        """압축본을 원하면 압축본을, 없으면 원본을 돌려준다."""
        if compact and self.compact_user:
            return (self.compact_system or self.system, self.compact_user)
        return (self.system, self.user)


class LLMProvider(ABC):
    """설명 문장을 생성하는 LLM 프로바이더."""

    #: 화면·로그에 표시할 이름
    name: str = "unknown"

    #: 프롬프트 길이 제약이 있어 압축본을 받아야 하는가 (앨런의 URL 한도).
    wants_compact_prompt: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """지금 호출할 수 있는 상태인가 (키·의존 패키지 확인)."""

    @abstractmethod
    def generate_json(
        self,
        prompts: Prompts,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        """
        스키마를 만족하는 JSON 문자열을 생성한다.

        구조 강제는 프로바이더가 할 수 있으면 하고, 못 해도 된다 —
        `render.py`가 어차피 다시 검증한다.

        Raises:
            ProviderUnavailable: 키 없음 / 패키지 없음 / 쿼터 소진
            ProviderError: 호출 실패
        """


class ChainProvider(LLMProvider):
    """
    앞에서부터 시도하고 실패하면 다음으로 넘기는 체인.

    쓰는 이유는 앨런의 호출 쿼터다. 앨런 키가 마르면 화면이 템플릿 문장으로
    떨어지는데, 발표 중에 그러면 곤란하다. 그 사이에 OpenAI를 한 겹 넣어
    "앨런이 답할 수 있으면 앨런, 아니면 OpenAI, 그것도 아니면 템플릿"이 되게
    한다.

    `name`이 프로퍼티인 것이 중요하다. `explain.py`가 호출이 **끝난 뒤**
    `llm.name`을 읽어 `source`에 넣기 때문에, 실제로 답한 백엔드 이름이
    그대로 화면 출처 표시(`llm:alan` / `llm:openai`)가 된다. 발표 중 어느
    문장을 누가 썼는지 숨기지 않기 위한 것이다.
    """

    def __init__(self, backends: Sequence[LLMProvider]) -> None:
        if not backends:
            raise ValueError("체인에는 최소 하나의 프로바이더가 필요합니다.")
        self._backends: List[LLMProvider] = list(backends)
        self._last_used: Optional[LLMProvider] = None

    @property  # type: ignore[override]
    def name(self) -> str:
        if self._last_used is not None:
            return self._last_used.name
        return "+".join(b.name for b in self._backends)

    def is_available(self) -> bool:
        return any(b.is_available() for b in self._backends)

    def generate_json(
        self,
        prompts: Prompts,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        self._last_used = None
        last_error: Optional[ProviderError] = None

        for backend in self._backends:
            if not backend.is_available():
                logger.info("체인: %s를 건너뜁니다 (사용 불가).", backend.name)
                continue
            try:
                raw = backend.generate_json(prompts, schema, schema_name)
            except ProviderError as exc:
                # 사용 불가든 호출 실패든 체인에서는 똑같이 "다음으로 넘긴다".
                # 사유는 마지막 것만 들고 가서, 전부 실패했을 때 보고한다.
                logger.info("체인: %s 실패, 다음으로 넘어갑니다 — %s", backend.name, exc)
                last_error = exc
                continue
            self._last_used = backend
            return raw

        raise ProviderUnavailable(
            "체인의 모든 프로바이더가 실패했습니다"
            + (f" — 마지막 사유: {last_error}" if last_error else "")
        )


# ─── 레지스트리 ──────────────────────────────────────────────────────────────
_REGISTRY: Dict[str, Callable[[], LLMProvider]] = {}

DEFAULT_PROVIDER = "openai"
PROVIDER_ENV_VAR = "BLUESCORE_LLM_PROVIDER"

#: 흐름별 덮어쓰기 환경변수 이름. `BLUESCORE_LLM_PROVIDER__TIP` 형태다.
FLOW_ENV_PREFIX = f"{PROVIDER_ENV_VAR}__"


def register(name: str, factory: Callable[[], LLMProvider]) -> None:
    _REGISTRY[name] = factory


def available_providers() -> list:
    return sorted(_REGISTRY)


def flow_env_var(flow: str) -> str:
    """흐름 이름 → 환경변수 이름. `tip` → `BLUESCORE_LLM_PROVIDER__TIP`."""
    return f"{FLOW_ENV_PREFIX}{flow.upper()}"


def resolve_provider_name(flow: str = "") -> str:
    """
    이 흐름이 쓸 프로바이더 이름.

    흐름별 변수 → 전역 변수 → 기본값 순으로 본다. 빈 값은 설정하지 않은 것과
    같게 취급한다 — `.env`에 키만 써두고 값을 비워두는 일이 흔하기 때문이다.
    """
    if flow:
        scoped = os.getenv(flow_env_var(flow), "").strip()
        if scoped:
            return scoped
    return os.getenv(PROVIDER_ENV_VAR, "").strip() or DEFAULT_PROVIDER


def get_provider(name: str = "", flow: str = "") -> LLMProvider:
    """
    프로바이더를 만든다.

    Args:
        name: 직접 지정. 주면 환경변수를 보지 않는다.
        flow: 흐름 이름(`explain`·`qa`·`objection`·`report`·`tip`).
              흐름별 환경변수를 먼저 보게 한다.
    """
    resolved = name or resolve_provider_name(flow)
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
    register("alan+openai", lambda: ChainProvider([AlanProvider(), OpenAIProvider()]))


_register_builtins()
