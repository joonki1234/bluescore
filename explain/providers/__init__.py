"""
담당: 최지희

LLM 프로바이더 구현.

    openai_provider.py  기본값. 구조화 출력을 지원하고 프롬프트 길이 제약이 없다.
    alan_provider.py    이스트소프트 앨런. GET 한 방 엔드포인트라 URL 길이
                        한도(약 7KB)와 키당 호출 쿼터가 있어, 압축 프롬프트와
                        키 로테이션을 스스로 떠안는다.

둘을 섞어 쓰는 방법은 `provider.py`의 `ChainProvider`와 흐름별 환경변수
설명을 참고한다.

새 프로바이더를 추가하려면 `LLMProvider`를 구현하고 `provider.py`의
`_register_builtins()`에 등록하면 된다.
"""
