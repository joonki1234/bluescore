# BlueScore

어선의 조업 데이터로 지속가능성 점수를 산출하고, 그 점수만큼 대출 금리 구간을 낮춰
제안하는 해양 ESG 금융 서비스.

## 실행

`bluescore/` 폴더 안에서 실행한다.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m storage.seed_demo
```

터미널 두 개에서 API를 먼저 띄우고 화면을 실행한다.

```bash
# 터미널 1
python -m uvicorn api.main:app --reload --port 8000

# 터미널 2
BLUESCORE_API_URL=http://127.0.0.1:8000 python -m streamlit run app.py
```

API 문서는 실행 후 `/docs`, 상태 확인은 `/health`에서 본다. 업무 상태는 기본적으로
`instance/bluescore_demo.db`에 저장되며, 다른 경로를 쓰려면 `BLUESCORE_DB_PATH`를
설정한다. 시연 상태를 초기화하려면 다음 명령을 사용한다.

```bash
python -m storage.seed_demo
```

Streamlit은 점수나 상태를 직접 만들지 않고 FastAPI REST 응답만 사용한다. UI만
별도 환경에 설치할 때는 `requirements-ui.txt`를 쓰되, API 서버 환경에는
`requirements.txt` 전체가 필요하다.

가상환경은 필수가 아니지만, 전역에 설치하면 다른 프로젝트와 버전이 얽힐 수 있어
권장한다. `.venv/`는 `.gitignore`에 있어 커밋되지 않는다.

| 화면 | 주소 | 보는 사람 |
| --- | --- | --- |
| 어업인 | `/` | 내 점수, 왜 이 점수인지, 무엇을 바꾸면 되는지 |
| 금융기관 | `/bank` | 산출 근거, 자격 요건, 데이터 출처, 해시, 승인·보류 |

두 화면은 SQLite의 같은 `scoreRunId`와 설명 캐시를 본다. 계산과 업무 상태는
FastAPI 뒤 서비스가 담당하고 `ui/adapter.py`는 API 클라이언트 역할만 한다.

## 구조

```
app.py                  진입점 · 페이지 네비게이션
ui/api_client.py        HTTP 전송·오류 변환
ui/adapter.py           API 응답을 기존 화면 키로 변환
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

Streamlit 대시보드는 FastAPI 응답만 읽으며, 이의제기·심사·설명 캐시·체인 메타데이터는
SQLite에 저장한다. FastAPI의 `sourceType=real` 경로는 버전 고정 GFW
스냅샷으로 A축까지 실산출합니다. B축 실데이터 검증 전에는 BlueScore를 추정하지 않고
`partial` 상태로 반환합니다. 시연 화면은 결정론적 `demo` fixture를 사용합니다.

## LLM 설명 사전 생성

`.env` 또는 환경변수에 `OPENAI_API_KEY`를 넣은 개발 환경에서 한 번 실행한다.

```bash
python -m storage.precompute_explanations
```

요약·요인 상세·개선 팁은 허용 행동과 숫자 검증을 통과한 뒤 `score_runs.report_json`에
저장된다. 발표 화면은 이 캐시를 읽으며 런타임 LLM 호출은 기본적으로 꺼져 있다.
외부 호출 없이 템플릿 캐시만 만들려면 `--fallback-only`를 붙인다.

## 로컬 온체인 모드

```bash
# 터미널 1
cd chain/hardhat && npm ci && npx hardhat node

# 터미널 2
cd chain/hardhat
npx hardhat ignition deploy ignition/modules/HashRegistry.js --network localhost

# 터미널 3 · bluescore/
BLUESCORE_CHAIN_MODE=onchain \
BLUESCORE_CHAIN_RPC_URL=http://127.0.0.1:8545 \
BLUESCORE_HASH_REGISTRY_ADDRESS=0x5FbDB2315678afecb367f032d93F642f64180aa3 \
python -m uvicorn api.main:app --reload --port 8000
```

승인 또는 보류 뒤 커밋하면 트랜잭션 해시·블록번호·컨트랙트 주소가
`chain_commits`에 저장되고 금융기관 화면에서 Record ID로 조회된다. 변조 검증 UI와
원본 항적의 온체인 저장은 범위에서 제외한다.

mock을 다시 만들려면:

```bash
python data/mock/generate_dashboard_mock.py
```

## 테스트

```bash
python -m pytest -q
python -m chain.verify_api_onchain  # Hardhat 노드·배포 후
```
