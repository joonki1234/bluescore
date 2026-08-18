# DECISION_HISTORY.md

코드 주석에 흩어져 있던 의사결정 히스토리(날짜·담당자·논의/결정/확인 서술)를
제출 전 정리하면서 이 문서로 옮겼다. 코드에는 지금도 유효한 핵심 이유만
간결하게 남기고, "누가 언제 무엇을 논의/확인했는지"에 대한 전체 맥락은
여기서 원문 그대로 보존한다.

파일별로 원래 있던 순서대로 나열한다.

## score/axis_b_baseline.py

> [해결됨, 2026-08-18] estimated_fuel_kg는 실측 연료 데이터가 없어 물리식
> 추정치로 대체한 값인데, 그 물리식이 정확히 tonnageGt/averageSpeedKnots/
> durationHours만의 매끈한 함수(잡음 없음)다. averageSpeedKnots를
> LightGBM 기준선 입력에도 그대로 두면, 모델이 "기대"를 사실상 그 물리식
> 자체로 근사해버려 잔차(residual_raw)가 진짜 운항 효율 차이가 아니라
> LightGBM의 곡선 근사 오차(노이즈)에 가까워지는 문제가 있었다. (데모:
> 톤수·속도만 다른 20척으로 확인한 잔차가 -21.8%~+8.2%로 뚜렷한 패턴 없이
> 흩어짐 — 2026-08-13.)
>
> 기획서 원문은 평균속도도 입력에 포함하도록 명시하지만, 물리식 잔차
> 구조상 그러면 순환성이 생겨 신호가 노이즈가 되므로 이 변경이 맞다는
> 결론(오동규 확인, 2026-08-18).

> LightGBM 입력 피처 컬럼. 기획서 원문 후보 중 averageSpeedKnots/totalDistanceKm은
> 뺐다 — 물리식 추정치(estimated_fuel_kg)도 이 값들의 함수라, 기준선 입력에
> 그대로 두면 "기대"가 물리식을 베껴버려 잔차가 노이즈가 된다. 모듈 docstring의
> [해결됨, 2026-08-18] 항목 참고.

> 행이 하나뿐이고 그 값이 None인 수치형 컬럼은, pandas가 다른 float 값과
> 섞어볼 게 없어 dtype을 object로 추론해버린다(고전적인 단일행 함정). 이
> 상태로는 `model.predict()`는 그냥 통과하지만, `shap.TreeExplainer`가
> 쓰는 LightGBM의 `pred_contrib=True` 경로는 object dtype을 거부한다
> (2026-08-18, `score/shap_factors.py` 실데이터 검증 중 실제로 겪음—
> `ValueError: pandas dtypes must be int, float or bool`). 그래서 수치형
> 컬럼은 행 개수와 무관하게 항상 `pd.to_numeric()`으로 float dtype을
> 명시적으로 강제한다(None은 NaN이 된다).

## score/real_axis_b_input.py

> 그대로 읽어서 score/가 원하는 이름으로 새로 변환만 한다
> (`data/vessel_spec_client.py`가 MOF 원본 필드를 그대로 받아 자체 정규화하는
> 것, `services/real_scoring.py`가 GFW 원본 필드를 그대로 읽어 A축을 계산하는
> 것과 같은 패턴 — 2026-08-18 오동규·김태윤 논의 결론).

> 필드별 처리 방침 (전부 2026-08-18 오동규·김태윤 논의로 확정 — `score/TODO.md`
> "B축 입력 병합 스크립트" 항목에 논의 경과 전체 기록):
>     - `tonnageGt`: ... **실측 확인함(2026-08-18): `tac`와 `mof`가 동시에
>       채워진 행은 0건**이라 우선순위/충돌 로직은 필요 없다.

> `seaArea`/`season`: 데이터팀 태그(`population_tags.jsonl`, 2026-08-18
> 기준 아직 생성 안 됨)를 기다리지 않고...

> 튜플은 `"{row}_{col}"` 문자열로 바꿔서 쓴다** — 튜플을 그대로 LightGBM
> 범주형 피처에 넣으면 학습↔예측 사이 카테고리 왕복 과정에서 numpy가
> 같은 길이의 튜플들을 2차원 배열로 오인해 리스트로 망가뜨리는 바람에
> 예측 단계에서 `TypeError: unhashable type: 'list'`가 난다(2026-08-18
> 실행 중 실제로 발견, `_sea_area_label()` 참고).

> `_sea_area_label()` 함수 docstring: "2026-08-18 실행 중 발견: 튜플을
> LightGBM 범주형 피처 값으로 그대로 쓰면 안 된다 — ... `TypeError:
> unhashable type: 'list'`로 죽는다(실제로 겪음). 문자열로 바꾸면 이
> 문제가 없다."

## score/axis_a_pressure.py

>                               + interaction_weight * revisit_raw * congestion_raw
>        (2026-08-13, 오동규·김준기 논의로 결정 — 혼잡한 해역을 반복 착취하는
>        것이 한산한 해역을 반복 방문하는 것보다 자원에 더 큰 압력을 준다는
>        판단에 따름.)

>     - 격자 크기(GRID_CELL_SIZE_DEG=0.1도)와 재방문압력 변환 스케일
>       (REVISIT_PRESSURE_SCALE_HOURS=60시간)은 2026-08-18 확정됐다(CLAUDE.md
>       "확정된 규칙" 8번 참고 — data_new/ 실측 275,782건으로 격자 후보
>       0.02~1.0도를 비교해 근거를 마련함).

> # 격자 한 변의 크기 (도 단위, 위경도 기준) — 확정값(2026-08-18, CLAUDE.md
> # 확정된 규칙 8번). data_new/ 실측 275,782건으로 0.02~1.0도 후보를 비교해...

> # 확정값(2026-08-18, CLAUDE.md 확정된 규칙 8번) — GRID_CELL_SIZE_DEG=0.1도
> # 기준 실측 재방문 간격 중앙값(59.1시간)에 맞춤...

## score/axis_b_physics.py

> 2026-08-14 검증 결과 (오동규): 아래 세 상수 중 부하율 공식만 Coello 원문(같은
> 저자 박사논문 기준, Eq. 2.3, p.22: LF = 0.9 * (Vi/Vd)^3, Vi=순간속도,
> Vd=설계속도, 0.9는 "설계속도는 주기관 최대연속정격의 90%에서 낸다"는 10%
> 해상마진 가정)에서 실제로 확인했다. ...

> 2026-08-15 추가 확인: git blame으로 이 파일의 첫 커밋(00705245)까지 거슬러가봤는데,
> 그 시점부터 이미 지금과 같은 숫자·"검증 필요" 문구가 같이 있었다 — 나중에 출처가
> 누락된 게 아니라 처음부터 대표값으로 들어간 것이라 커밋 이력으로는 더 추적할 게
> 없다. 다만 `SFOC_G_PER_KWH=190.0`은 일반적인 중속 디젤 선박엔진의 SFOC 범위
> (약 155~225 g/kWh)에는 들어가는 값이라 — 특정 논문에서 온 숫자는 아니지만 터무니
> 없는 값도 아니다. `POWER_COEFF_A/B`는 이런 정황조차 못 찾았다.

> # 주기관 설계출력 추정식 P(kW) = a * GT^b 의 회귀계수 — 출처 불명의 대표값, 검증 필요
> # (Coello et al. 2015 원문에는 없음 — 2026-08-14 확인, 위 모듈 독스트링 참고)

> # 주기관 비연료소비율 (g/kWh) — 출처 불명의 대표값, 검증 필요
> # (Coello et al. 2015 원문에는 없음 — 2026-08-14 확인, 위 모듈 독스트링 참고)

## score/scripts/convert_data_new_vessels.py

> 톤수 우선순위: tac.tonnageGtTac > mof.tonnageGtMof (둘 다 문자열이라 float로
> 변환, 파싱 실패/누락은 None). 실측 확인 결과 이 둘이 동시에 채워진 행은
> 0건이라(2026-08-18) 실제로는 우선순위가 발동하지 않는다 — 다만 나중에
> 데이터가 바뀌어 둘 다 채워지는 경우가 생기면 이 우선순위가 조용히 MOF 값을
> 버린다는 점은 알아둘 것.

> fishingType은 (2026-08-18) `data_new/processed/gfw_vessels_normalized.jsonl`
> (GFW 자체 gear 정보, `combinedGearTypes`)이 공개돼서 이제 채운다.

> **(2026-08-18 실측으로 발견)** 처음엔 이것도 그냥 남겨뒀는데, 유사군 그룹핑에
> gearType을 추가한 결과를 실제로 돌려보니 A축 실산출 비율이 73%(3,887/5,323)
> →32%(1,684/5,323)로 급락했다 — 전체의 44%가 이 뭉뚱그려진 라벨이라, 그룹이
> 톤수×**gear**×해역×계절로 과도하게 쪼개지면서 최소표본(20척) 미달 그룹이
> 급증한 것.

## chain/commit_score_result.py

> **(2026-08-18 현황 정리)**
> - `verify_score_result()`는 여전히 아무도 안 씀 — 다만 죽은 코드가 아니라
>   **아직 안 만들어진 기능(해시 위조 검증 API/UI, 최지희님이 처음에 "가장
>   임팩트 있는 한 장면"으로 꼽았던 것)이 생기면 바로 쓰일 자리**다.

> ledger 인자는 `chain.ledger.HashLedger`(인메모리)든 `OnChainHashLedger`
> (2026-08-14 추가, 실제 컨트랙트 호출)든 상관없다.

## score/score_assembly.py

> 지금까지는 이 조립 단계가 score/에 없어서, 화면이 비지 않도록 ui/adapter.py의
> `_raw_to_score()`가 최지희님 쪽에서 임시로 이 로직을 대신 구현해 쓰고 있었다
> (2026-08-14 확인, ui/adapter.py 주석에 "score/의 실산출을 붙일 때 이 함수를
> 쓴다"고 명시돼 있음).

## score/tradeoff_coefficients.py

> 배경: `ui/adapter.py`에 있던 4개 계수(AXIS_A_GAIN_PER_REVISIT_STEP,
> AXIS_B_COST_PER_REVISIT_STEP, AXIS_B_GAIN_PER_KNOT, AXIS_A_COST_PER_KNOT)는
> 전부 "근거 없는 잠정값"이라고 표시돼 있었다(2026-08-14, `TODO(score/ 김준기·
> 오동규)` 주석).

## services/metadata.py

> # 2026-08-18: data_new/(김태윤) 스냅샷으로 전환 — services/real_scoring.py의
> # DEFAULT_EVENTS_PATH/DEFAULT_VESSELS_PATH 참고.

> # 2026-08-18 B축 연결(score/real_axis_b_scoring.py) — 선박별로 B축 실산출
> # 여부가 갈려서(톤수 매칭 커버리지 43.4%뿐) model_version도 응답마다 달라야
> # 한다.

## api/test_api.py

> # 2026-08-18: score/tradeoff_coefficients.py 실제 계수로 교체되며 78.0->89.7로
> # 바뀜(밴드 B->A 전환은 그대로 유지) — services/scoring.py 커밋 메시지 참고.

## chain/hashing.py

> 2026-08-17: 화면의 중복 해시 구현은 제거했다. 이제 WorkflowService가 이 함수만
> 호출하고 UI는 커밋·조회 API의 결과 해시를 표시한다.

## chain/ledger.py

> `OnChainHashLedger` (2026-08-14 추가): `chain/hardhat/`에 배포된

> 없는 컴퓨터도 있을 수 있어(2026-08-14 기준 이 코드를 작성한 컴퓨터가 그렇다),
> 생성자에서 네트워크에 바로 접속하지는 않는다

## chain/test_onchain_ledger.py

>       안 되면 스스로 skip한다. 실제로 이 경로가 도는지는 Node가 있는 컴퓨터
>       (예: 김준기님)에서 확인이 필요하다.

## storage/test_workflow.py

> # 2026-08-18: score/tradeoff_coefficients.py 실제 계수로 교체되며 78.0->89.7로
> # 바뀜(밴드 B->A 전환은 그대로 유지) — services/scoring.py 커밋 메시지 참고.

## 정리 2차 — 오류해결/경위 요약 (원문 대신 요약만 보존)

아래는 코드에서 완전히 삭제하고 요약만 남긴 것들이다(위 항목들과 달리 원문
전체를 옮기지 않음 — 재현에 필요한 세부는 아니라고 판단).

- **data_new/process/assemble_matches.py** (`_total_score` 근처): 매칭 오탐
  필터(선단 번호 접두어 불일치 검사)가 CLAUDE.md 10번 근거로 인용된 검증
  (PROCESS_LOG.md 49번)에 비해 실제 코드에는 반영이 안 돼 있던 걸 발견,
  시뮬레이션으로 오매칭 77건(3.3%) 확인 후 반영함. 원본 raw 입력 부재로
  전체 재검증은 못 했음 — 파이프라인 재실행 시 오매칭 카운트 재확인 필요.
- **services/metadata.py** (`REAL_DATA_SNAPSHOT_ID` 근처): 매칭 필터·SHAP
  연결 변경 때 스냅샷 버전 문자열을 안 올려 SQLite 캐시가 옛 응답(빈
  shapFactors 등)을 계속 반환한 사고가 실제로 있었음 — 데이터 내용이
  바뀌면 경로가 그대로여도 항상 버전을 올려야 한다는 걸 재확인.
- **ui/components.py** (`real_vessel_meta_card` 근처): 실산출 화면이 숫자만
  나열하는 느낌이라 SHAP 요인 기여도 시각화를 추가함, `axis_breakdown()`의
  카운트업+채움 패턴을 재사용.
