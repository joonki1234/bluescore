"""
담당: 최지희

이스트소프트 앨런(Alan) 프로바이더.

접근 방식
--------
앨런은 KDT 교육용으로 공개된 GET 엔드포인트 하나만 제공한다.

    GET /api/v1/question?content=<프롬프트>&client_id=<키>   ->  {"answer": "..."}

POST는 없고(404), 구조화 출력(JSON Schema 강제)도 없다. 그래서 두 가지를
여기서 떠안는다.

1. **JSON 형식 지시** — 스키마를 프롬프트 끝에 형태 예시로 붙인다. 앨런이
   그것을 지킨다는 보장은 없지만 `render.py`가 어차피 다시 검증하므로,
   지키지 못하면 조용히 틀린 값이 나가는 게 아니라 폴백으로 떨어진다.
2. **프롬프트 길이** — 프롬프트가 URL 쿼리에 실리므로 길이 한도가 있다.
   실측 결과 URL 7,273바이트는 통과하고 8,308바이트는 414가 났다. 원본
   프롬프트(참고 사실 블록 포함)는 이 한도를 넘기 때문에 이 프로바이더는
   `wants_compact_prompt = True`로 압축본을 받는다.

키 로테이션
----------
키 하나당 호출 쿼터가 있다(실측: 성공 호출 약 100회 후 401). 그래서 키를
여러 개 받아 순서대로 쓰고, 401이 나면 그 키를 소진 처리하고 **같은 요청을
다음 키로 즉시 재시도**한다. 마지막 키까지 마르면 `ProviderUnavailable`을
던지고, `alan+openai` 체인이 OpenAI로 넘긴다.

소진 상태는 프로세스 메모리에만 둔다. 앱을 재시작하면 죽은 키를 한 번씩 다시
찔러보게 되지만 401은 즉시 돌아오고 쿼터도 먹지 않아서, 파일로 영속화해
얻는 것보다 잃는 코드가 많다.

    ALAN_API_KEY=키1,키2      콤마로 여러 개. 하나만 써도 그대로 동작한다.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Set

from explain.provider import LLMProvider, Prompts, ProviderError, ProviderUnavailable

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "ALAN_API_KEY"
ENDPOINT = "https://kdt-api-function.azurewebsites.net/api/v1/question"

# 네트워크가 느릴 때 화면이 오래 멈추지 않도록. 초과하면 체인이 OpenAI로 넘긴다.
REQUEST_TIMEOUT_SECONDS = 25.0

# 요청 URL 길이 상한. 실측으로 7,273B는 통과, 8,308B는 414였다. 정확한 경계는
# 그 사이 어딘가인데, 넘기면 조용한 실패가 아니라 414라서 안전한 쪽에 붙인다.
MAX_URL_BYTES = 7_200

# 쿼터가 마른 키. 프로세스 전역이다 — `get_provider()`가 호출마다 새 인스턴스를
# 만들기 때문에 인스턴스에 두면 매번 잊어버린다.
_EXHAUSTED_KEYS: Set[str] = set()


def api_keys() -> List[str]:
    """`.env`의 콤마 구분 키 목록. 빈 항목과 공백은 버린다."""
    raw = os.getenv(API_KEY_ENV_VAR, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def live_keys() -> List[str]:
    """아직 쿼터가 남아 있는 키만."""
    return [k for k in api_keys() if k not in _EXHAUSTED_KEYS]


def reset_exhausted_keys() -> None:
    """소진 표시를 지운다. 테스트와 수동 복구용."""
    _EXHAUSTED_KEYS.clear()


class _QuotaExhausted(Exception):
    """내부 신호. 이 키는 말랐으니 다음 키로 넘어가라."""


def _shape_hint(schema: Dict[str, Any]) -> Any:
    """
    JSON Schema를 사람이 읽을 수 있는 형태 예시로 바꾼다.

    스키마를 그대로 붙이면 프롬프트가 길어지는데(URL 한도가 빠듯하다) 앨런이
    스키마 문법을 지켜주는 것도 아니다. 필요한 것은 "어떤 키에 무엇을 넣는가"
    뿐이라 모양만 남긴다.
    """
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        return {key: _shape_hint(value) for key, value in props.items()}
    if kind == "array":
        return [_shape_hint(schema.get("items", {}))]
    enum = schema.get("enum")
    if enum:
        return " 또는 ".join(str(e) for e in enum)
    return "문장"


def _json_instruction(schema: Dict[str, Any]) -> str:
    shape = json.dumps(_shape_hint(schema), ensure_ascii=False)
    return (
        "\n\n출력 형식: 아래 JSON 객체 하나만 출력하세요. "
        "인사말·설명·코드펜스 없이 JSON만 출력합니다.\n" + shape + "\n"
    )


def _build_url(content: str, client_id: str) -> str:
    return ENDPOINT + "?" + urllib.parse.urlencode(
        {"content": content, "client_id": client_id}
    )


class AlanProvider(LLMProvider):
    name = "alan"

    # URL 길이 한도 때문에 원본 프롬프트를 실을 수 없다.
    wants_compact_prompt = True

    def is_available(self) -> bool:
        return bool(live_keys())

    def generate_json(
        self,
        prompts: Prompts,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        keys = live_keys()
        if not keys:
            detail = (
                "모든 키의 사용량이 소진됐습니다."
                if api_keys()
                else f"{API_KEY_ENV_VAR}가 설정되어 있지 않습니다."
            )
            raise ProviderUnavailable(f"앨런을 호출할 수 없습니다 — {detail}")

        system_prompt, user_prompt = prompts.resolve(compact=True)
        content = f"{system_prompt}\n\n{user_prompt}{_json_instruction(schema)}"

        # 길이 초과는 키를 바꿔도 똑같이 실패한다. 로테이션에 들어가기 전에 막고,
        # 프롬프트를 고쳐야 하는 신호이므로 사유를 분명히 남긴다.
        url_bytes = len(_build_url(content, keys[0]).encode("utf-8"))
        if url_bytes > MAX_URL_BYTES:
            raise ProviderError(
                f"프롬프트가 앨런 URL 한도를 넘습니다 "
                f"({url_bytes}B > {MAX_URL_BYTES}B, 스키마 {schema_name}). "
                "압축 프롬프트를 줄여야 합니다."
            )

        last_error = ""
        for client_id in keys:
            try:
                return self._ask(content, client_id)
            except _QuotaExhausted:
                _EXHAUSTED_KEYS.add(client_id)
                last_error = "사용량 초과"
                logger.info(
                    "앨런 키 소진(...%s), 다음 키로 넘어갑니다. 남은 키 %d개",
                    client_id[-4:], len(live_keys()),
                )
                continue

        raise ProviderUnavailable(f"앨런 키를 모두 소진했습니다 — {last_error}")

    def _ask(self, content: str, client_id: str) -> str:
        """
        키 하나로 한 번 호출한다.

        Raises:
            _QuotaExhausted: 401. 호출부가 다음 키로 넘어간다.
            ProviderError: 그 외 실패. 키를 바꿔도 소용없으므로 로테이션하지 않는다.
        """
        try:
            with urllib.request.urlopen(
                _build_url(content, client_id), timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                # 앨런은 권한 없음과 사용량 초과를 같은 401로 돌려준다. 키를
                # `.env`에 넣어둔 이상 실제로는 대부분 사용량 초과다.
                raise _QuotaExhausted from exc
            if exc.code == 414:
                raise ProviderError(
                    "앨런이 URL 길이 초과(414)로 거부했습니다. "
                    f"{MAX_URL_BYTES}B 가드를 낮춰야 합니다."
                ) from exc
            raise ProviderError(f"앨런 호출 실패: HTTP {exc.code}") from exc
        except Exception as exc:  # 타임아웃·DNS·연결 실패
            raise ProviderError(f"앨런 호출 실패: {type(exc).__name__}: {exc}") from exc

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError("앨런 응답에 answer가 비어 있습니다.")
        return answer
