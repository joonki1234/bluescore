"""
담당: 최지희

이스트소프트 앨런(Alan) 프로바이더 — **미구현 스텁**.

왜 비어 있나
-----------
앨런은 셀프서비스 API가 공개돼 있지 않다. 소개 페이지(estsoft.ai/bu_agentic_ai)와
서비스 사이트(myalan.ai)를 모두 확인했으나 엔드포인트·인증 방식·요금이 어디에도
없고, 요금제도 Free/Pro 두 가지뿐이라 API 티어가 없다. 접근하려면
`alan.biz@estsoft.com` 으로 B2B 문의를 거쳐야 한다.

2026-08-14 기준 운영진 회신이 없어, 우선 OpenAI로 붙여 두고 이 파일은
스텁으로 남긴다. 화면과 `explain.py`는 프로바이더 인터페이스만 알기 때문에
여기만 채우면 나머지는 그대로 동작한다.

참고: `alan.app`은 이름만 같은 미국 회사(Alan AI Group)의 음성 어시스턴트
플랫폼이며 이스트소프트 앨런과 무관하다. 그쪽 문서를 보고 구현하면 안 된다.

채울 때 할 일
------------
1. `is_available()` — 인증 정보(API 키 등)가 설정됐는지 확인
2. `generate_json()` — 요청 전송, 응답에서 본문 추출
3. 앨런이 구조화 출력을 지원하지 않으면 JSON 형식을 프롬프트로 지시하기만
   하면 된다. `render.py`가 어차피 파싱과 검증을 다시 한다.
4. `explain/test_explain.py`에 앨런 프로바이더 테스트 추가

TODO(최지희): 운영진 회신 후 구현. 회신이 계속 없으면 OpenAI 유지.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from explain.provider import LLMProvider, ProviderUnavailable

# 접근 정보를 받으면 여기에 채운다.
API_KEY_ENV_VAR = "ALAN_API_KEY"


class AlanProvider(LLMProvider):
    name = "alan"

    def is_available(self) -> bool:
        # 미구현이므로 키가 있어도 사용 불가. 구현 시 키 확인으로 교체한다.
        return False

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> str:
        detail = (
            "API 키는 설정돼 있으나 클라이언트가 아직 구현되지 않았습니다."
            if os.getenv(API_KEY_ENV_VAR)
            else "이스트소프트 B2B 문의(alan.biz@estsoft.com) 회신 대기 중입니다."
        )
        raise ProviderUnavailable(f"앨런 프로바이더 미구현 — {detail}")
