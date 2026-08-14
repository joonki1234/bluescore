# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

BlueScore는 어선의 조업 데이터를 기반으로 두 축(A축: 자원 압력, B축: 운항 효율)의 지표를
산출하고, 이를 신용점수(BlueScore)로 통합하는 Python 프로젝트다. 핵심 로직 일부가
구현되어 있으며, 나머지는 각 모듈의 `TODO.md`에 남은 작업으로 진행 중이다.

- `data/gfw_client.py` — Global Fishing Watch (GFW) API v3 클라이언트 (Vessels Search,
  Events 엔드포인트, GET+kebab-case 20척 배치 방식). 원본은
  `~/Downloads/bluescore-demo/server.js` (Node/Express)이며 Python(requests)으로 이식했다.
  이 외에도 `data/`에는 국내 선박제원정보(MOF), TAC 할당승인정보, 해양기상, 해양수산부
  AIS 위치정보 통계, 어업별어선 등 공공데이터 클라이언트/로더가 추가돼 있다(김태윤 담당,
  현황은 `data/TODO.md` 참고).
- `score/axis_a_pressure.py` — A축(자원 압력) raw 값 산출: 재방문 간격 + 혼잡가중압력
  (self-exclusion + 상호작용항 반영 완료). GFW 이벤트만 있으면 바로 실행 가능.
- `score/axis_b_physics.py` — Coello et al. (2015) 계수 기반 물리식 연료 소비 추정.
  톤수 매칭된 선박만 커버.
- `score/axis_b_baseline.py` — B축(운항 효율) raw 값 산출: LightGBM 기준선 대비 잔차.
  파이프라인 코드는 구현 완료했으나, 해양기상 미부착·어업종 매핑표 부재로 아직 실데이터로
  돌리지는 못하는 상태.
- `chain/` — 아직 코드 없이 `TODO.md`만 있는 상태 (온체인 증적, `score/` 결과물 대기 중).
- `explain/` — SHAP 기여도 연계, LLM 프롬프트/strict JSON 파싱/폴백 문구, 프로바이더 중립
  구조, `ui/adapter.py` 연결까지 대부분 구현 완료(최지희 담당, 테스트 27개). 남은 일은
  `explain/TODO.md` 참고(실제 LLM 키 검증, SHAP 라벨 정합 등).
- `app.py` — Streamlit 앱 진입점(어업인/금융기관 화면 분리, `ui/` 모듈 사용). 지금은
  `ui/adapter.py`가 `data/mock/dashboard_mock.json`을 읽어 화면을 채우고, `score/`가
  실산출 가능해지면 그쪽으로 자동 전환되는 구조다(최지희 담당).
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
   - 빈 값(`None`/누락)은 값을 `null`로 넣지 않고 제외한다 — dict 키뿐 아니라
     리스트 요소도 마찬가지다(재귀적으로 적용).
   - 구분자는 공백 없는 압축형(`","`, `":"`)을 쓴다.
   - (2026-08-14 추가: `chain/hashing.py`와 `ui/adapter.py`의 `score_hash()`가
     이 규칙을 각자 구현했는데 리스트 None 처리·구분자가 서로 달라 해시가
     갈리는 게 발견돼 통일했다. 위 네 항목은 그 이후 명확히 정리한 버전이다.
     `chain/test_hash_matches_ui_adapter.py`가 두 구현의 일치를 계속 지켜본다.)
6. **congestion_density_raw는 자기 자신 이벤트를 제외**하고, revisit_interval_raw와
   가중합이 아니라 상호작용(interaction)항을 포함해 결합한다 (2026-08-13, 오동규·김준기
   결정, `score/axis_a_pressure.py`에 반영 완료). "이미 혼잡한 곳을 반복 착취"하는 경우를
   단순 가중합보다 더 크게 반영하기 위함이며, 결합 가중치 자체는 여전히 미확정이다.
7. **GFW `regions.mpa` 필드 존재 확인 완료** (김태윤, 2026-08-14 실제 라이브 호출로 검증 —
   리스트 형태로 실존, 표본 70,747건 중 14.7%에 실값 있음). 보호구역 침범 판정 데이터
   소스로 사용 가능하다는 전제가 확정되었다.

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

추가로, GAP 이벤트 자체가 실측 91만 건 중 140건(0.015%)으로 극히 희소해 GAP 비율을
리스크 지표로 쓰는 것이 유의미한지 자체도 판단2 회의에서 함께 재검토가 필요하다
(단순히 임계값만 정하면 되는 문제가 아닐 수 있음).
