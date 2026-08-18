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
- **`data_new/`(2026-08-18~)** — 김태윤이 처음부터 다시 짠 데이터 파이프라인.
  `data/`(구, flag=KOR AND shiptypes=FISHING, 31,605척, 확정매칭 순도 9.5%) 대신
  EEZ 제한 모집단(5,323척, 사람 라벨링 실측 정밀도 약 75%)을 쓴다.
  `services/real_scoring.py`의 A축 실산출이 이미 이쪽으로 전환됐고(2026-08-18),
  **팀 결정으로 앞으로는 `data_new/` 기준으로만 작업한다** — `data/`(구)를 실제로
  사용했을 때의 문제(90.5% 비어선 등, `data/TODO.md`·`data/BlueScore_*.md` 참고)는
  더 이상 고려 대상이 아니며, `data/`(구)의 원본·중간산출물은 필요 없어지면 정리
  대상이다(단, `data/`는 김태윤 담당이라 실제 삭제는 담당자 확인 후 진행). 상세는
  `data_new/README.md`·`data_new/PROCESS_LOG.md`.
- `score/axis_a_pressure.py` — A축(자원 압력) raw 값 산출: 재방문 간격 + 혼잡가중압력
  (self-exclusion + 상호작용항 반영 완료). GFW 이벤트만 있으면 바로 실행 가능.
- `score/axis_b_physics.py` — Coello et al. (2015) 계수 기반 물리식 연료 소비 추정.
  톤수 매칭된 선박만 커버.
- `score/axis_b_baseline.py` — B축(운항 효율) raw 값 산출: LightGBM 기준선 대비 잔차.
  파이프라인 코드는 구현 완료했으나, 해양기상 미부착·어업종 매핑표 부재로 아직 실데이터로
  돌리지는 못하는 상태.
- `chain/` — SHA-256, 로컬 원장, Hardhat 컨트랙트, web3 연동 구현 완료. REST API는
  현재 `ledgerMode=local`로 연결돼 있고 실제 RPC 전환은 후속 단계다.
- `explain/` — SHAP 기여도 연계, LLM 프롬프트/strict JSON 파싱/폴백 문구, 프로바이더 중립
  구조, `ui/adapter.py` 연결까지 대부분 구현 완료(최지희 담당, 테스트 27개). 남은 일은
  `explain/TODO.md` 참고(실제 LLM 키 검증, SHAP 라벨 정합 등).
- `app.py` — Streamlit 앱 진입점(어업인/금융기관 화면 분리, `ui/` 모듈 사용). 지금은
  `ui/adapter.py`가 `data/mock/dashboard_mock.json`을 읽어 화면을 채우고, `score/`가
  실산출 가능해지면 그쪽으로 자동 전환되는 구조다(최지희 담당).
- `api/` — Pydantic 공개 계약과 FastAPI 엔드포인트. 모든 결과가 데이터·모델·산식·
  금리표 버전과 `sourceType`을 포함한다.
- `services/` — 결정론적 시연 점수, 실제 GFW A축 어댑터, 이의제기→심사→해시 기록
  업무 흐름. 실데이터 B축은 검증 대기라 총점을 추정하지 않고 `partial`로 반환한다.
- `storage/` — SQLite 스키마·저장소·seed/reset. 원천 이벤트는 저장하지 않고 점수·
  리포트·이의제기·심사·체인 메타데이터만 저장한다.
- `conftest.py`(루트)는 내용 없이, pytest가 리포지토리 루트를 `sys.path`에 넣어
  `score/`, `data/` 등에 `__init__.py` 없이도 `from score.xxx import ...` 절대 임포트가
  테스트에서 동작하도록 하기 위한 용도다.
- 아직 lint/CI 설정(`pyproject.toml`, `setup.py`, CI config 등)은 없다. 테스트는 `pytest`로
  실행한다 (예: `pytest score/`).

각 모듈 하단의 raw 값(예: `axis_a_pressure_raw`, `axis_b_residual_raw`)은 절대 점수가
아니라, 점수조립 단계에서 유사 선박군 내 상대값(백분위 등)으로 다시 정규화되어야 하는
중간 산출값이다.

주요 실행/검증 명령:

```bash
streamlit run app.py
uvicorn api.main:app --reload
python -m storage.seed_demo
pytest -q
```

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
8. **A축 격자 크기(`GRID_CELL_SIZE_DEG`) = 0.1도, 재방문압력 스케일
   (`REVISIT_PRESSURE_SCALE_HOURS`) = 60시간으로 확정** (2026-08-18, 오동규,
   최지희 요청사항 회의 결과). 근거: data_new/ 실측 이벤트(275,782건, 5,314척)로
   `score/axis_a_pressure.py`의 `compute_axis_a_pressure()`를 격자 크기
   0.02~1.0도 후보별로 직접 돌려 재방문 검출률·간격 분포·격자당 평균 이벤트
   수를 비교함 — 0.25도부터 검출률이 91%대에서 포화되고 격자당 이벤트가
   급증(0.25도 531건 → 1.0도 5,408건)해 "재방문"의 의미가 흐려지는 반면,
   0.1도는 검출률 90.0%·격자당 111건으로 과소분할(0.02도, 격자당 7.9건 —
   한 항적이 여러 격자로 쪼개짐)과 과잉병합 사이 균형점이었다. 스케일값
   60시간은 이 격자 기준 실측 재방문 간격의 중앙값(59.1시간)에 맞춘 것 —
   기존 잠정값 24시간은 실측 중앙값의 1/3도 안 돼 대부분의 선박이 압력
   0.1~0.3대에 몰려 변별력이 거의 없었다.
   **주의**: 이건 A축 raw 압력 계산용 격자(`GRID_CELL_SIZE_DEG`)에 대한
   결정이고, 유사 선박군 "해역" 근사용 격자(`REGION_GRID_SIZE_DEG`,
   `score/peer_grouping.py`, 현재 1.0도)는 목적이 달라 이번 결정에
   포함되지 않았다 — 여전히 잠정값이다.

9. **유사군 최소 표본 기준 = 10척으로 확정** (2026-08-18, 해커톤 제출 시한
   압박 속 팀 결정 — `score/peer_grouping.py`의 `MIN_PEER_GROUP_SAMPLE_SIZE`).
   data_new/ 실측(1,079개 그룹, 중앙값 2척) 기준 20척은 커버리지 42.6%,
   10척은 61.0%였다. 격자 크기 때와 달리 명확한 "무릎점"이 없는 순수
   트레이드오프였고, "통계적으로 최소 방어 가능한 하한(10척=10% 해상도)"과
   "실산출 커버리지"를 절충했다. `services/real_scoring.py`도 하드코딩된
   `20`을 지우고 이 상수를 import하도록 맞춤. 근본 원인(그룹 과세분화)은
   gearType 처리 방식과 얽혀 있어 이후 개선 여지가 큼(`score/TODO.md` 참고).
10. **매칭 신뢰도 임계값 = 0.8로 확정** (2026-08-18) — `data_new/process/
    assemble_matches.py`의 `FUZZY_NAME_THRESHOLD`. 이미 사람이 직접 라벨링한
    80쌍(층화 랜덤추출)으로 실측 정밀도 약 75%까지 검증된 값이고
    (`data_new/PROCESS_LOG.md` 49번), 지금 쓰는 `final_vessel_matches.jsonl`도
    이 값으로 이미 생성돼 커밋돼 있어 사실상 재론 불필요 — 3개 파라미터 중
    가장 튼튼한 실측 근거를 갖고 있었다.
11. **GAP 비율 임계값 = 이번 버전에 미포함(결정: 안 함)** (2026-08-18) —
    GAP 이벤트가 실측 91만 건 중 140건(0.015%)으로 극히 희소하고, 코드
    전체(`score/`, `services/`, `api/`) 어디에도 GAP 비율을 실제로 쓰는
    소비처가 없었다(확인 완료). 해커톤 시한 안에 검증 안 된 임계값으로 새
    기능을 급조하는 대신, 이번 제출 범위에서는 GAP 지표 자체를 포함하지
    않기로 결정. 향후 재검토 시 이 항목부터 다시 연다.
12. **(10번 재론·교체) 매칭을 로마자 유사도(0.8 임계값)에서 한글
    직접비교로 교체** (2026-08-18, 김태윤) — 10번에서 "재론 불필요"라고
    했던 그 결정을 실제로 다시 열어서 뒤집었다. 계기: GFW 영문명
    4,662척 전체를 사람이 직접 한글로 재변환한 데이터가 새로 생겨서,
    로마자 대신 한글 원문끼리 직접 비교가 가능해짐 — 검증해보니 로마자
    유사도의 구조적 오탐("-성호"류, 서로 다른 이름인데 로마자로 바꾸면
    끝부분이 겹쳐서 점수가 높게 나옴)을 없앨 수 있었다(전체 검증 과정은
    `data_new/matching_redesign_proposal/README.md`). matched
    2,881척(54.1%, 추정 오탐 ~720척) → verified 1,234척(23.2%, 추정
    오탐 거의 0)으로 커버리지는 줄고 정밀도는 크게 오름 — 오탐 하나가
    B축 점수를 그 배 단위로 완전히 틀어지게 만들 수 있어 커버리지보다
    정밀도를 우선함. `data_new/process/match_fuzzy_name.py`·
    `assemble_matches.py`에 반영·재실행 완료, `final_vessel_matches.jsonl`도
    이 결과로 갱신됨. 카카오맵 API 키 필요(`.env`의 `KAKAO_API_KEY`).
    이후(같은 날) 어선원부를 후보풀에서 완전히 빼고 GFW-TAC 매칭만
    쓰기로 정리(1,262→1,234척, PROCESS_LOG.md 52번) — 어선원부 관련
    수집·정규화·1·2단계 매칭 스크립트 전부 삭제. 같은 날 마지막으로,
    사람 스팟체크에서 verified의 63.8%가 같은 TAC 배를 여러 GFW
    선박이 동시에 주장하는 중복배정이었던 게 발견돼(예: TAC "한성호"
    1척이 GFW 9척에 매칭) TAC 쪽 유일성을 강제하는 5단계를 추가함
    (1,234→713척, 13.4%, PROCESS_LOG.md 53번) — 지금 이 수치가 최종.

## 미확정 항목 (하드코딩 금지)

격자 크기·재방문 기간(2026-08-18 확정, 8번)에 이어 유사군 최소 표본·매칭
신뢰도·GAP 비율도 2026-08-18에 전부 정리됐다(9~11번). 이 섹션은 이제 비어
있다 — 앞으로 새로 생기는 미확정 파라미터가 있으면 여기에 추가한다.
