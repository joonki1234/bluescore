# pytest가 리포지토리 루트를 sys.path에 포함시키도록 하는 빈 conftest.py.
# score/, data/ 등에 __init__.py가 없어도 `from score.xxx import ...` 형태의
# 절대 임포트가 테스트에서 동작하게 하기 위함.
