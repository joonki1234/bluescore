"""
담당: 최지희

설명 계층 — SHAP 기여도를 어업인이 읽을 수 있는 문장으로 바꾼다.

    contract.py   입력/출력 계약 (dataclass + JSON 스키마)
    facts.py      고정 사실 테이블 (RAG 대신)
    prompt.py     프롬프트 조립
    provider.py   LLM 프로바이더 추상 + 레지스트리
    providers/    프로바이더 구현 (anthropic / alan)
    render.py     Strict JSON 파싱 + 숫자 검증
    fallback.py   LLM 실패 시 템플릿 문구
    explain.py    공개 진입점

설계 원칙
--------
1. **LLM은 숫자를 만들지 않는다.** 계산 결과를 프롬프트에 주입하고 문장 생성만
   맡긴다. 응답에 입력에 없던 수치가 섞이면 `render.py`가 폴백으로 강등한다.
2. **LLM 없이도 동작한다.** `fallback.py`가 템플릿으로 같은 스키마를 만든다.
   API 키가 없거나 호출이 실패해도 화면이 비지 않는다.
3. **프로바이더는 교체 가능하다.** 앨런 API 연락이 오면
   `providers/alan.py` 하나만 채우면 되고 나머지는 건드리지 않는다.

RAG를 쓰지 않는 이유
------------------
입력(SHAP 값, 축 점수, 유사군 위치)이 전부 이미 계산된 숫자라, LLM이 할 일은
검색이 아니라 문장화다. 법령 텍스트를 검색해 넣으면 LLM이 조항을 틀리게 말할
수 있고, 금융·규제 맥락에서 그건 훨씬 나쁜 실패다. 법령 지식이 실제로 필요한
자리는 `facts.py`의 고정 사실 테이블로 덮는다.
"""

from explain.contract import ExplainInput, ExplainOutput, Recommendation, ShapFactor
from explain.explain import explain

__all__ = [
    "ExplainInput",
    "ExplainOutput",
    "Recommendation",
    "ShapFactor",
    "explain",
]
