# BlueScore

어선의 조업 데이터로 지속가능성 점수를 산출하고, 그 점수만큼 대출 금리 구간을 낮춰
제안하는 해양 ESG 금융 서비스.

## 대시보드 실행

`bluescore/` 폴더 안에서 실행한다.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-ui.txt
streamlit run app.py
```

## REST API 실행

```bash
uvicorn api.main:app --reload
```

API 문서는 실행 후 `/docs`, 상태 확인은 `/health`에서 본다. 업무 상태는 기본적으로
`instance/bluescore_demo.db`에 저장되며, 다른 경로를 쓰려면 `BLUESCORE_DB_PATH`를
설정한다. 시연 상태를 초기화하려면 다음 명령을 사용한다.

```bash
python -m storage.seed_demo
```

대시보드는 `streamlit`과 `plotly`만 있으면 전부 동작한다. geopandas·lightgbm은
`score/` 실산출용이라 화면만 볼 때는 설치하지 않아도 된다 (geopandas는 설치가 무겁다).
파이프라인까지 돌리려면 `pip install -r requirements.txt`.

가상환경은 필수가 아니지만, 전역에 설치하면 다른 프로젝트와 버전이 얽힐 수 있어
권장한다. `.venv/`는 `.gitignore`에 있어 커밋되지 않는다.

| 화면 | 주소 | 보는 사람 |
| --- | --- | --- |
| 어업인 | `/` | 내 점수, 왜 이 점수인지, 무엇을 바꾸면 되는지 |
| 금융기관 | `/bank` | 산출 근거, 자격 요건, 데이터 출처, 해시, 승인·보류 |

두 화면은 **같은 숫자**를 쓴다. 계산은 전부 `ui/adapter.py`를 거치며, 화면 코드에서는
직접 계산하지 않는다.

## 구조

```
app.py                  진입점 · 페이지 네비게이션
ui/adapter.py           유일한 계산 창구 (score/·explain/ 호출 + mock 폴백)
ui/fisher.py            어업인 화면
ui/bank.py              금융기관 화면
ui/components.py        두 화면이 공유하는 컴포넌트
ui/theme.py             색 토큰 · CSS · 포맷 헬퍼
score/                  A축·B축 raw 값 산출
explain/                SHAP 결과 문장화·검증·폴백
chain/                  해시·로컬 원장·Hardhat/web3 온체인 구현
data/                   외부 데이터 클라이언트
data/mock/              대시보드용 임시 데이터 + 생성기
fixtures/               결정론적 시연 페르소나 입력
api/                    Pydantic 응답 계약·FastAPI 엔드포인트
services/               점수 어댑터·이의제기/심사/커밋 업무 흐름
storage/                SQLite 스키마·저장소·시연 seed/reset
```

## 현재 상태

현재 Streamlit 대시보드는 `data/mock/dashboard_mock.json`을 직접 읽으며, 6단계에서
FastAPI 응답으로 교체합니다. FastAPI의 `sourceType=real` 경로는 버전 고정 GFW
스냅샷으로 A축까지 실산출합니다. B축 실데이터 검증 전에는 BlueScore를 추정하지 않고
`partial` 상태로 반환합니다. 시연 화면은 결정론적 `demo` fixture를 사용합니다.

mock을 다시 만들려면:

```bash
python data/mock/generate_dashboard_mock.py
```

## 테스트

```bash
pytest score/ data/
```
