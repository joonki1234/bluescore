"""
담당: 최지희

설명 계층 — SHAP 기여도를 어업인이 읽을 수 있는 문장으로 바꾼다.

    contract.py   입력/출력 계약 (dataclass + JSON 스키마)
    facts.py      고정 사실 테이블 (RAG 대신)
    prompt.py     프롬프트 조립
    provider.py   LLM 프로바이더 추상 + 레지스트리
    providers/    프로바이더 구현 (openai / alan)
    render.py     Strict JSON 파싱 + 숫자 검증
    fallback.py   LLM 실패 시 템플릿 문구
    explain.py    공개 진입점

LLM은 계산 결과를 문장으로 바꾸기만 하고 숫자를 새로 만들지 않는다 —
`render.py`가 입력에 없는 수치가 섞이면 폴백으로 강등한다. `fallback.py`가
템플릿으로 같은 스키마를 만들어 API 키가 없거나 호출이 실패해도 화면이
비지 않는다. RAG 대신 `facts.py`의 고정 사실 테이블을 쓰는 이유는, 법령
텍스트를 검색해 넣으면 LLM이 조항을 틀리게 말할 위험이 있고 금융·규제
맥락에서 그건 훨씬 나쁜 실패이기 때문이다.
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
