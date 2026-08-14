"""
담당: 최지희

LLM 프로바이더 구현.

    openai_provider.py  기본. 앨런 API를 쓸 수 없어 우선 채택했다.
    alan_provider.py    이스트소프트 앨런. 접근 정보 확보 후 채운다.

새 프로바이더를 추가하려면 `LLMProvider`를 구현하고 `provider.py`의
`_register_builtins()`에 등록하면 된다.
"""
