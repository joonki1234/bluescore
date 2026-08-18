"""

BlueScore 대시보드 화면 계층.

    app.py          진입점 · 페이지 네비게이션
    ui/theme.py     색 토큰 · CSS · 포맷 헬퍼
    ui/api_client.py  FastAPI HTTP 클라이언트
    ui/adapter.py     API 응답의 화면 키 변환
    ui/components.py 두 화면이 공유하는 컴포넌트
    ui/fisher.py    어업인 화면
    ui/bank.py      심사역(금융기관) 화면

화면 코드에서는 점수를 직접 계산하지 않는다. 반드시 adapter를 통한다 —
어업인 화면과 심사역 화면의 숫자가 어긋나면 "제3자가 관측한 동일한 점수"라는
서비스 전제가 무너지기 때문이다.
"""
