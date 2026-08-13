# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

BlueScore는 어선의 조업 데이터를 기반으로 두 축(A축: 자원 압력, B축: 운항 효율)의 지표를
산출하고, 이를 신용점수(BlueScore)로 통합하는 Python 프로젝트다. 핵심 로직 일부가
구현되어 있으며, 나머지는 각 모듈의 `TODO.md`에 남은 작업으로 진행 중이다.

- `data/gfw_client.py` — Global Fishing Watch (GFW) API v3 클라이언트 (Vessels Search,
  Events 엔드포인트). 원본은 `~/Downloads/bluescore-demo/server.js` (Node/Express)이며
  Python(requests)으로 이식했다.
- `score/axis_a_pressure.py` — A축(자원 압력) raw 값 산출: 재방문 간격 + 혼잡가중압력.
- `score/axis_b_physics.py` — Coello et al. (2015) 계수 기반 물리식 연료 소비 추정.
- `score/axis_b_baseline.py` — B축(운항 효율) raw 값 산출: LightGBM 기준선 대비 잔차.
- `chain/`, `explain/` — 아직 코드 없이 `TODO.md`만 있는 상태 (온체인 증적 / SHAP·LLM 설명).
- `app.py`, `requirements.txt`는 파일은 있으나 `app.py`는 비어 있다 (`requirements.txt`에는
  fastapi, streamlit, lightgbm, shap, pandas, geopandas, python-dotenv, requests, plotly,
  pytest가 명시되어 있음).
- `conftest.py`(루트)는 내용 없이, pytest가 리포지토리 루트를 `sys.path`에 넣어
  `score/`, `data/` 등에 `__init__.py` 없이도 `from score.xxx import ...` 절대 임포트가
  테스트에서 동작하도록 하기 위한 용도다.
- 아직 lint/CI 설정(`pyproject.toml`, `setup.py`, CI config 등)은 없다. 테스트는 `pytest`로
  실행한다 (예: `pytest score/`).

각 모듈 하단의 raw 값(예: `axis_a_pressure_raw`, `axis_b_residual_raw`)은 절대 점수가
아니라, 점수조립 단계에서 유사 선박군 내 상대값(백분위 등)으로 다시 정규화되어야 하는
중간 산출값이다.

When substantial code is added to this repo, this file should be updated with real
build/lint/test commands and an accurate architecture overview.

## File ownership convention

Ownership by folder/area is tracked in `ROLES.md`. When creating a new file, check `ROLES.md`
for the owner(s) of that folder/area and add a `담당: {이름}` line near the top of the file
(as a comment in the file's comment syntax, e.g. inside the module docstring for `.py` files
or as a heading line for `.md` files). Keep `ROLES.md` and this convention in sync if
ownership changes.

## 확정된 규칙

팀 논의를 거쳐 확정되어 앞으로 바뀌지 않는 규칙들이다. 새 데이터나 새 기능이 추가되어도
아래 결론 자체는 뒤집지 않는다.

1. **지도 표현 방식**: 점선 보간 + 이벤트 지점 강조로 확정. GFW가 연속 항적이 아니라
   이산(discrete) 이벤트만 제공하기 때문이며, 데이터가 더 확보되어도 이 결론은 바뀌지
   않는다.
2. **A축 재방문 간격**: 이벤트 횟수가 아니라 시간(시간 단위 간격) 기준으로 계산한다
   (`score/axis_a_pressure.py`의 `_compute_revisit_intervals_hours` 참고).
3. **혼잡압력 비교 대상**: 유사 선박군(톤수대 × 어업종 × 해역 × 계절) 기준을 그대로
   사용한다.
4. **블록체인(`chain/`) 담당**: 김준기 + 오동규 유지 (`ROLES.md`와 동일).
5. **해시 규칙** (`chain/`의 SHA-256 해시 생성 대상 JSON에 적용):
   - JSON은 `sort_keys=True`로 직렬화한다.
   - 소수점이 있는 값은 둘째 자리까지 반올림한 뒤 문자열로 변환한다.
   - 빈 값(`None`/누락)은 값을 `null`로 넣지 않고 키 자체를 제외한다.

## 미확정 항목 (하드코딩 금지)

아래 5개 파라미터는 아직 팀에서 확정하지 않았다. 김태윤의 데이터 실사 결과가 나온 뒤
회의로 정한다. 코드에서 이 값들이 필요한 곳은 하드코딩하지 말고, `TODO` 주석과 임시값
(플레이스홀더)으로 표시해 나중에 쉽게 찾아 교체할 수 있게 한다
(예: `score/axis_a_pressure.py`의 `GRID_CELL_SIZE_DEG`처럼 상수 + 잠정값 주석 형태).

- 격자 크기 (grid cell size)
- 재방문 기간 (며칠 이내를 "재방문"으로 볼지)
- 유사군 최소 표본 기준 (유사 선박군으로 인정할 최소 표본 수)
- GAP 비율 임계값
- 매칭 신뢰도 임계값 (선박 식별자 매칭 exact/fuzzy 판정 기준)
