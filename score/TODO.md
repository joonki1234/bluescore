## 담당: 김준기, 오동규

# score TODO

## 현재 production 상태 (2026-08-19)

- A축과 B축은 같은 추적 선박 입력을 사용하며 서비스는 파생
  `vessels_for_score.jsonl.gz`/`axis_b_input.jsonl`을 요구하지 않는다.
- 구체적인 GFW fishingType을 B축 `gearType`에 연결했다. 현재 서비스 입력은
  선박 5,323척, 톤수 1,234척, fishingType 2,682척, 둘 다 665척이다.
- 실산출 상태는 success 289척, partial 3,395척, insufficientSample 1,630척,
  matchingFailed 9척이다. 아래 864척·807척 등의 값은 중간 스냅샷 결과다.
- 모델·정책 파라미터 검증은 `MODEL_POLICY_VALIDATION.md`와 검증 CLI로 완료했다.
  production 상수는 변경하지 않았으며 날씨 단위·출력식·시뮬레이션 계수는
  `unverified`, A/B 가중치와 금리표는 `policyDecision`으로 분류했다.
- 데이터 스냅샷과 Streamlit 어업인·금융기관 화면은 2026-08-19 기준 완성본으로
  동결한다. 아래 과거 조사 항목은 현재 production 수정 작업이 아니다.

## 진행 현황 정리 (2026-08-18 기록)

score/ 자체 구현은 A축·유사군·점수조립·금리매핑·트레이드오프까지 전부 코드+테스트
완료 상태고, chain/도 Hardhat 실배포+Python 연동까지 end-to-end 확인 끝났다
(`chain/TODO.md` 참고). B축 LightGBM 순환성 문제도 해결됨(아래 항목).

**2026-08-15 시점에 "최지희님과 조율 필요"로 묶었던 4개 배선 항목은 그 사이
최지희님의 API/서비스 계층 작업(`services/`, `api/` 신설)으로 3개가 이미 실제로
연결돼 있었고, 남은 1개(트레이드오프 계수)도 오동규가 2026-08-18에 배선
완료했다** — `services/scoring.py`가 최지희님 소유 파일이라 이 배선은 **최지희
확인 완료(2026-08-18)**(오늘 추가된 A축 격자 크기·재방문 스케일 변경분 포함,
상세는 아래 트레이드오프 계수 항목). 나머지 배선
3개(raw_to_score·rate_mapping, score_hash, scoring_backend mock→실산출)는
`services/real_scoring.py`·`services/scoring.py`·`services/workflow.py`에서
이미 호출되고 있는 것을 확인함(오동규, 2026-08-17 앱 실행 확인).

**현재 score/ 구현과 검증은 완료됐다. 아래 목록은 데이터 동결 이전의 조사 기록과
외부 근거·정책 결정이 필요한 보류 항목이며, 현재 production 수정 범위가 아니다.**

**동결 범위 밖 또는 외부 결정 필요**
- AIS 위치정보 통계를 A축에 **얼마나/어떻게** 결합할지(조회 가능하게 만드는
  것까지는 2026-08-18 완료, 아래 항목 참고 — 결합 설계는 아직 팀 논의 필요)
- 선박제원 매칭 품질 이슈 — 확정 매칭 663건 중 90.5%(600건)가 비어선으로 확인됨
  (`data/BlueScore_지희님질문_매칭품질_20260814.md`,
  `data/BlueScore_모집단뒤집기_조사_20260818.md` 참고)
- 국내→GFW 어업종 매핑표(19종) — 담당 미정 (`data/TODO.md` 참고)
- ~~CLAUDE.md "미확정 항목" 3개~~ — **2026-08-18 전부 확정됨**(해커톤 제출
  시한 압박으로 팀 결정): 유사군 최소 표본 10척, 매칭 신뢰도 0.8(기존값 확정),
  GAP 비율 임계값은 이번 버전 미포함. CLAUDE.md 확정된 규칙 9~11번 참고.
- 기관출력 단위(HP/PS) 확인 (`data/TODO.md` 참고)
- GT→설치출력 회귀계수·SFOC 원출처 — 이번 조사로는 못 찾음, 새 단서 없이는
  더 진행 불가 (아래 항목)
- `AXIS_A_COST_PER_KNOT`(`services/scoring.py`) 미검증 계수 — **(2026-08-18
  조사 완료, 코드 변경은 안 함)** `score/scripts/analyze_speed_revisit_correlation.py`
  로 data_new/ 실측 4,177척 기준 평균속도 vs 평균재방문간격 상관분석 —
  Pearson r=+0.0009, p=0.95로 통계적으로 무관계 확인. 0으로 낮춰봤으나
  `ui/test_simulator_surface.py::test_peak_is_interior_not_at_either_edge`가
  깨짐 — 이 계수가 실은 "B축이 세제곱 법칙 때문에 아주 조금만 느려져도
  상한(97점)에 포화되는" 구조에서, 그 이후 계속 느려질 때 점수가 떨어지게
  만드는 유일한 장치였음(없으면 상한 포화 구간 전체가 동점 평평한 고원이
  돼 구간 최저점도 최고점과 동점이 됨). **추가로 확인된 것**: 지금도 진짜
  최고점은 "중간"이 아니라 구간 최저(7.4kn)에서 겨우 +0.2점 떨어진
  7.6~7.7kn 지점 — ③번 시연 구성("최고점은 중간")이 생각보다 아슬아슬하게
  성립 중. **결론(팀 논의 완료)**: 계수는 0.8 그대로 유지하되, 실측 검증된
  물리 계수가 아니라 "시뮬레이터가 극단값에서 비현실적으로 안 보이게 하는
  설계적 안전장치"라고 정직하게 라벨링하는 쪽으로 정리. 근본 원인(B축 조기
  포화)은 A축 계수로 덮는 임시방편이라, 시뮬레이터 속도 구간 설계
  (`SIM_SPEED_DELTA_DOWN` 등, `services/scoring.py`) 자체를 재검토하는
  게 더 근본적인 해법일 수 있음 — 최지희님 판단 필요, 화면 문구
  갱신 여부도 함께.

---

- [x] **A축 raw 결합에 z-score 정규화 적용** — **완료(오동규)**: `score/axis_a_pressure.py`의
      `compute_axis_a_pressure()`가 `revisit_interval_raw`(실측 중앙값 0.88)와
      `crowding_pressure_raw`(격자 내 다른 배 이벤트 카운트, 실측 중앙값
      371.83 — 약 400배 차이)를 그대로 가중합하고 있었는데, 이 단위 불균형
      때문에 `AXIS_A_REVISIT_WEIGHT=0.5`/`AXIS_A_CONGESTION_WEIGHT=0.5`가
      이름만 50:50이지 실제로는 재방문압력의 평균 기여비중이 1.08%로
      거의 묻혀 있었다(실측 확인).
      - **적용 방법**: 두 raw 값을 population(같은 호출에 넘긴 이벤트 전체
        중 `used_event_count > 0`인 선박) 기준 z-score로 정규화한 뒤 결합.
        상호작용항도 정규화된 값끼리 곱하도록 바꿨다(`interaction_zscore =
        revisit_zscore * crowding_zscore`). `revisit_interval_raw`/
        `crowding_pressure_raw`/`interaction_raw` 필드는 원래 raw 값 그대로
        유지하고(화면·진단 스크립트가 원래 단위로 보여줄 수 있어야 하므로),
        결합에는 새로 추가한 `revisit_zscore`/`crowding_zscore`/
        `interaction_zscore` 필드만 쓴다.
      - **왜 z-score를 택했나**: min-max 정규화(실측 22.31%), 유사군 내
        백분위 정규화(실측 47.81%, 이론적으로 가장 정확)와 비교 시뮬레이션한
        결과, z-score(실측 40.45%)가 구현 난이도 대비 개선 폭이 제일
        좋았다. 유사군 백분위 방식은 결합 단계에서 유사군 정보가 필요해
        지금 구조(유사군은 점수조립 단계에서만 있음) 변경이 필요한데, 시간
        여유를 고려해 우선순위에서 밀렸다 — **향후 개선 후보로 남겨둠**.
      - **실데이터로 확인한 개선**: 재방문압력 평균 기여비중이 1.08% →
        약 38.75%(실제 구현으로 5,314척 전체 재계산, 시뮬레이션값 40.45%와
        비슷한 수준)로 개선됨.
      - **연쇄 수정**: `score/shap_factors.py`의 `axis_a_factor_contributions()`가
        기존에 raw 필드로 가중합을 재현하고 있었는데, 결합이 z-score
        기반으로 바뀌었으니 이것도 zscore 필드를 쓰도록 고쳤다(안 고쳤으면
        세 항의 합이 `axis_a_pressure_raw`와 안 맞아 가법성 불변식 테스트가
        깨짐). 실데이터로 가법성도 재확인함(합계 +0.9718 = axis_a_pressure_raw
        +0.9718).
      - **`axis_a_pressure_raw`의 절대 크기 자체가 완전히 달라짐**(raw 결합
        시절엔 수백 단위, 이제는 z-score 단위라 대략 -3~+5 범위). 전체
        소비처(`grep -rn "axis_a_pressure_raw"`)를 확인한 결과
        `score/score_assembly.py::raw_to_score()`와
        `services/real_scoring.py`는 전부 상대 순위(백분위)만 쓰므로 문제
        없음. `score/tradeoff_coefficients.py`의
        `axis_a_pressure_raw_delta_for_revisit_step()`은 이름은 비슷하지만
        별개 함수(`revisit_pressure_from_interval()`만 직접 씀, 이 결합
        로직과 무관 — 게다가 아직 아무 데도 안 쓰이는 미배선 함수)라 영향
        없음.
      - 테스트: `score/test_axis_a_pressure.py`에 z-score 관련 테스트 3개
        추가(population 평균 0/표준편차 1 확인, 표준편차 0일 때 0으로
        나누기 없이 0.0 처리, 이벤트 없는 선박은 z-score도 0). 기존
        `test_interaction_term_amplifies_when_both_signals_high`는 raw
        기준 비교라 새 결합 방식과 안 맞아 실패했었는데, self-exclusion
        설계(확정된 규칙 6번) 때문에 "혼자 반복 방문"만으로는 재방문·혼잡
        둘 다 population 평균보다 높게(z-score 양수) 나오지 않는다는 걸
        발견해(자기 몫이 혼잡압력에서 빠지므로) — 실제로 재방문·혼잡 둘 다
        높은 선박을 만들려면 비슷하게 자주 오는 다른 배가 여러 척 더
        있어야 한다는 걸 반영해 테스트 시나리오를 다시 만듦.
        `score/test_shap_factors.py`의 `_make_axis_a_result()` 헬퍼도
        zscore 필드를 채우도록 수정(raw 필드는 일부러 `-999.0`으로 채워서
        실수로 raw 필드를 쓰면 테스트가 바로 깨지게 함).
      - `pytest -q` 307 passed(env 서브프로세스 테스트 1개만 무관하게
        실패), `python -m score.scripts.run_real_axis_a`·
        `python -m score.scripts.run_shap_factors` 둘 다 실데이터로
        에러 없이 재확인.

- [x] **요인 기여도(SHAP) 실제 계산 구현** — **완료(2026-08-18, 오동규)**:
      `score/shap_factors.py` 신설. 그동안 `requirements.txt`에 `shap`
      패키지만 있고 실제로 쓰는 코드는 없어서, 화면의 `shapFactors`는 전부
      `data/mock/generate_dashboard_mock.py`가 손으로 써넣은 예시 숫자였다 —
      이걸 실제 계산으로 채웠다.
      - **A축** `axis_a_factor_contributions()`: `axis_a_pressure_raw`가
        가중합+상호작용항 수식이라 `shap` 라이브러리 없이 세 항(재방문압력/
        혼잡압력/상호작용)으로 정확히 분해. 합이 `axis_a_pressure_raw`와
        정확히 일치함을 실측(91.4만 건 스냅샷)으로도 확인
        (328.5901 = 328.5901).
      - **B축** `axis_b_baseline_factor_contributions()`: `shap.TreeExplainer`로
        LightGBM 기준선(`expected_fuel_kg`) 예측의 피처별 기여도(kg)를
        분해. **중요한 제약 — 이건 "기준선이 왜 이 값인지"(조건 설명)이지
        "왜 이 선박의 B축 효율이 좋다/나쁘다"가 아니다.** 효율(잔차)은
        `estimated_fuel_kg - expected_fuel_kg`라는 단순 뺄셈으로 이미
        설명이 끝나 있음 — 함수 docstring에 명시해서 나중에 오용 안 되게
        해둠. SHAP 가법성(모든 피처 기여도 합 + 기준값 = 모델 예측값)도
        실측으로 확인.
      - **실행 중 실제 버그 발견·수정**: `axis_b_baseline._rows_to_feature_dataframe()`가
        행이 1개뿐이고 그 값이 None인 수치형 컬럼을 pandas가 object dtype으로
        추론해버리는 함정이 있었음(단일행 시 다른 float 값과 섞어볼 게 없어서).
        `model.predict()`는 이 상태로도 통과하지만, `shap.TreeExplainer`가
        쓰는 LightGBM의 `pred_contrib=True` 경로는 object dtype을 거부해서
        `ValueError: pandas dtypes must be int, float or bool`로 실데이터
        검증 중 실제로 죽었음 — `pd.to_numeric(..., errors="coerce")`로
        수치형 컬럼을 행 개수와 무관하게 항상 float dtype으로 강제해서 해결.
        `axis_b_baseline.py`의 다른 소비처(`predict_expected_fuel_kg`,
        `compute_axis_b_efficiency`)에도 잠재돼 있던 취약점이라 이번 수정으로
        같이 해소됨. 회귀 테스트 추가(`test_axis_b_baseline.py::TestRowsToFeatureDataframe`).
      - 테스트 6개(`score/test_shap_factors.py`) + 회귀 테스트 1개, 검증
        스크립트 `score/scripts/run_shap_factors.py`로 실데이터 확인,
        `pytest -q` 328 passed(SHAP 관련 전부 통과 — 별개로 실패하는 1개는
        `api/test_api.py`의 env 서브프로세스 테스트로 Windows 소켓 프로바이더
        OS 이슈이며 이번 작업과 무관).
      - **다음 단계(범위 밖, 팀 논의 필요)**: raw 값을 화면 "점수(포인트)"
        단위로 바꾸는 환산 정책, `explain/contract.ShapFactor`로의 배선,
        `services/`(최지희) 연결.

      **(2026-08-18 후속) A축만 `services/real_scoring.py`에 실제 연결
      완료(오동규, 최지희 확인 필요)**: 위 "raw→포인트 환산" 문제를 A축은
      다르게 풀었다 — 개별 요인의 절대 "점수"는 유사군 분포 없이 못 구하지만,
      "전체 A축 raw 압력에서 이 요인이 차지하는 상대적 비중(%)"은 유사군
      없이도 정직하게 계산된다는 걸 이용해서 `axis_a_factor_shares()`를
      새로 추가(`score/shap_factors.py`). `RealAxisAResult.shap_factors`
      필드 신설 → `_result_from_context()`에서 `axis_result`가 있으면
      status(insufficientSample 포함)와 무관하게 채움(raw 분해 자체가 유사군
      표본과 무관하니까) → `services/scoring.py::_build_real_score`가
      `ShapFactorSchema`로 감싸 `ScoreResponse.shap_factors`에 실제로 담음
      (지금까지 이 인자가 아예 빠져 있어서 실산출 경로는 조용히 항상
      빈 리스트였음). **B축은 여전히 미연결** — SHAP이 "점수"가 아니라
      "기준선 조건"만 설명한다는 의미론적 제약은 그대로 유효하기 때문
      (`axis_b_baseline_factor_contributions()` docstring 참고).
      실측 확인: `RealAxisAAdapter`로 실제 3척 조회 — 3개 요인·`axis="a"`만·
      절댓값 합 100.00%로 정확히 나옴. 테스트 4개 추가
      (`score/test_shap_factors.py`의 `TestAxisAFactorShares` +
      `services/test_real_scoring.py`), `pytest -q` 334 passed(env
      서브프로세스 테스트 1개만 무관하게 실패). `explain/`(LLM 문장화) 연결은
      여전히 범위 밖 — 실산출 경로가 아직 `explain/explain()`을 안 써서
      (B축 `unavailable`이라 완전한 설명을 못 만듦) 별도 작업 필요.

      **(2026-08-18 후속 — B축 SHAP 코드 자체를 들어냄, 팀 결정)**: 위에서
      만들었던 `axis_b_baseline_factor_contributions()`/
      `axis_b_baseline_expected_value()`(테스트로 검증까지 마쳤던 것)를
      완전히 삭제했다. 이유를 대화로 다시 짚어본 결과 — 잔차(B축 raw)를
      만드는 진짜 원인(속도)이 순환성 방지를 위해 애초에 LightGBM 기준선
      모델 입력에서 빠져있어서, SHAP이 그 원인을 구조적으로 찾아낼 수
      없다는 게 명확해졌다. 즉 "기준선이 왜 이 값인지"는 설명해도 "왜
      점수가 이렇다"는 절대 설명 못 하는데, 아무도 이 함수를 호출할
      계획이 없으니(B축은 이 방식으로 설명 안 하기로 함) 오해 소지만
      남기고 쓰이지 않을 코드를 유지할 이유가 없다고 판단함. 같이 정리한
      것: `requirements.txt`의 `shap` 의존성 제거(A축은 라이브러리 없이
      수식 직접 분해라 애초에 필요 없었음), `score/test_shap_factors.py`의
      B축 테스트 4개 제거, `score/scripts/run_shap_factors.py`의 B축
      섹션 제거. **`axis_b_baseline.py`의 dtype 버그 수정(`pd.to_numeric`)과
      그 회귀 테스트는 SHAP과 무관하게 유효한 일반 견고성 수정이라 그대로
      유지함.** 필요해지면 이전 커밋(`4536b08c`)에서 복원 가능. B축 설명은
      대신 "자기 속도 vs 유사군 평균 속도" 같은 단순 비교로 가는 쪽으로
      방향만 잡아둠(구현은 미착수).

- [x] **A축 격자 크기·재방문 스케일 확정** — **완료(2026-08-18, 오동규, 최지희 요청
      회의)**: `GRID_CELL_SIZE_DEG` 0.05→**0.1도**, `REVISIT_PRESSURE_SCALE_HOURS`
      24→**60시간**으로 확정. CLAUDE.md 확정된 규칙 8번에 근거 전문 기록함
      (data_new/ 실측 275,782건으로 격자 후보 0.02~1.0도 비교 — 0.1도가
      과소분할/과잉병합 사이 균형점, 60시간은 그 격자 기준 실측 재방문 간격
      중앙값). `REGION_GRID_SIZE_DEG`(peer_grouping.py, 유사군 해역 근사용)는
      별개 항목이라 이번 결정에서 제외 — 여전히 잠정값.

      **코드 반영 완료(2026-08-18)**: `score/axis_a_pressure.py`의 두 상수·주석·
      모듈 docstring 갱신. 하위 파급 확인 결과:
      - `pytest score/test_axis_a_pressure.py score/test_tradeoff_coefficients.py
        api/test_api.py storage/test_workflow.py ui/test_simulator_surface.py -q`
        전부 통과, 전체 `pytest -q`도 254 passed·1 skipped로 기존과 동일(회귀 없음).
      - **시뮬레이터 데모 값은 실제로 안 바뀜** — 이유를 실측으로 확인함:
        `axis_b_points_per_revisit_step`은 격자가 2배(0.05→0.1도)가 되면서
        반환값도 약 2배로 커지는 게 맞다(예: VESSEL_A 조건 톤수 50GT·속도
        10.4kn 기준 21.02→42.03). 하지만 `services/scoring.py.simulate()`에서
        이 값이 쓰이는 `axis_b`는 같은 호출에서 `axis_b_points_per_knot`발
        속도 이득 항이 워낙 커서(계산해보면 사전클램프 값이 169.2→148.2로,
        둘 다 `AXIS_SCORE_CEIL=97.0`을 초과) 상한 클램프에 걸려 결과적으로
        기존과 동일한 97.0으로 수렴함 — `test_persona_one_reaches_a_band`의
        89.7이 그대로 유지되는 게 우연이 아니라 이 클램핑 때문임을 확인.
        다만 이건 "이 페르소나 조건에서는 안 보인다"는 것이지 계수 자체가
        안 바뀐 건 아니므로, 상한에 안 걸리는 다른 시나리오에서는 재방문
        비용이 실제로 2배 커진다는 점은 최지희님께 공유 필요.
      - `REVISIT_PRESSURE_SCALE_HOURS`는 현재 `services/scoring.py`가 아예
        참조하지 않는다(`axis_a_pressure_raw_delta_for_revisit_step`을 쓰는
        곳이 코드베이스 전체에 아직 없음 — 정의만 있고 미배선 상태) — 그래서
        이 상수 변경은 지금 시점엔 시연 화면에 어떤 영향도 없음. `axis_a_pressure.py`
        자체의 raw 계산(재방문압력)에는 반영됨(테스트로 확인).
      - `python -m score.scripts.run_real_axis_a`(실제 GFW raw 91만 건)로
        재실행 확인 — 정상 동작(9,723척 계산, 표본 60척짜리 유사군에서
        A축 점수 55.0 산출). 스크립트 자체에 이번 상수와 무관한 기존
        인코딩 버그(`sys.stdout.reconfigure` 누락으로 한글 출력 시
        `UnicodeEncodeError`)가 있어 `run_real_axis_b.py`와 같은 방식으로
        같이 고침. `python -m score.scripts.run_real_axis_b`도 재실행해
        B축은 이번 변경과 무관하게 동일한 결과(2,310척)임을 재확인함
        (B축은 `REGION_GRID_SIZE_DEG` 기반 `region_key()`를 쓰지
        `GRID_CELL_SIZE_DEG`를 쓰지 않음).

- [x] **B축 입력 병합 스크립트** — **완료(2026-08-18)**: `score/real_axis_b_input.py`
      (`build_axis_b_rows()`)로 구현, `score/scripts/run_real_axis_b.py`로 실제
      data_new/ 산출물(275,782개 이벤트, 5,314척)에 대고 `fit_baseline_model()` →
      `compute_axis_b_efficiency()`까지 에러 없이 도는 것 확인함 — 2,310척이
      실제 산출됨(나머지는 필수 3종 결측으로 자동 skip, 128,320건).
      `services/real_scoring.py`의 `RealAxisAAdapter` 패턴과 달리 상태 캐싱 없는
      단순 함수로 구현(데이터 규모가 A축 GFW 원본보다 작아 lru_cache 없이도
      충분히 빠름). 테스트 16개(`score/test_real_axis_b_input.py`, 실제 커밋된
      data_new/ 파일로 검증). **실행 중 실제 버그 하나 발견·수정**: `seaArea`를
      `region_key()`의 `(row, col)` 튜플 그대로 LightGBM 범주형 피처에 넣었더니,
      학습↔예측 카테고리 왕복 과정에서 numpy가 같은 길이 튜플들을 2차원 배열로
      오인해 리스트로 망가뜨려(`.tolist()`) `TypeError: unhashable type: 'list'`로
      예측 단계가 죽었음 — `"{row}_{col}"` 문자열로 바꿔서 해결
      (`_sea_area_label()`). **김태윤님 확인 필요한 것**: 아래 필드 매핑표
      (특히 톤수·날씨 단위). (`data_new/events_with_weather.jsonl.gz` +
      `final_vessel_matches.jsonl` + `population_tags.jsonl`을 `axis_b_baseline.py`가
      요구하는 평평한 필드로 변환) — **담당 논의 결과(2026-08-18, 오동규·김태윤)**:
      score팀(오동규·김준기)이 작성하기로 함. 데이터팀 원본 파일·필드명은 안
      건드리고(같은 패턴: `data/vessel_spec_client.py`, `services/real_scoring.py`),
      받는 쪽에서 새로 변환만 한다는 게 근거. **필드 매핑표는 김태윤님이 확인**
      (원본 구조는 데이터팀이 가장 잘 앎). 상세 배경·결정 근거는
      `data_new/TODO.md` 해당 항목 참고. 처리해야 할 것:
      - 톤수: `tac.tonnageGtTac`/`mof.tonnageGtMof`(문자열, 중첩)를 `tonnageGt`
        (float, 평평한 구조)로. 둘 다 있으면 우선순위 또는 충돌표시 필요
        (아직 미정 — 김태윤님과 확인).
      - 날씨: `weather_WATER_TEMPER`/`weather_WIND_SPEED`/`weather_SURFACE_CURR_SPEED`
        (문자열, "미제공" 결측 표기) -> `seaSurfaceTempC`/`windSpeedMs`/
        `currentSpeedMs`(float). **단위는 여전히 공식 확인은 안 됐지만, 풍속만
        정황 근거로 m/s로 가정하고 진행하기로 함**(2026-08-18 갱신) — 근거:
        (1) 한국 기상청·해양수산부가 풍속 단위로 m/s를 공식 표준으로 쓰는 게
        잘 알려진 관행, (2) 실제 샘플값과 대조도 됨(`AIR_PRESSURE: "1012"`가
        표준대기압 1013hPa 근처, `AIR_TEMPERATURE: "14.5"`가 4월 초 한국
        연안 기온으로 섭씨 기준 타당 — 화씨였다면 영하 9.7도라 말이 안 됨).
        다만 이건 이 API 문서를 직접 확인한 게 아니라 일반 관행으로 추론한
        것이라 "확인"이 아니라 "추정"으로 코드에 명시할 것.
        **`currentSpeedMs`(유속, `SURFACE_CURR_SPEED`)는 단위 추정 근거조차
        없음 — 완전 미확인 상태로 별도 표시.** 확보했었다는 정식 API
        매뉴얼도 리포에 안 남아있어 재확인 불가, `.env`의
        `MARINE_WEATHER_API_KEY`도 비어있어 라이브 재확인도 지금은 불가.
        나중에 매뉴얼 재확보나 키 발급 후 확정.
      - `seaArea`/`season`: **해결됨(2026-08-18)** — 데이터팀 태그를 안 기다리고
        `score/peer_grouping.py`의 `region_key(latitude, longitude)`/
        `season_key(start)`를 그대로 재사용하기로 함. 이벤트 자체의
        위경도·시작시각만 있으면 계산되고 `events_with_weather.jsonl.gz`에
        이미 다 있어서 즉시 채울 수 있음.
      - `gearType`: **(2026-08-18 결정) 영문(GFW) 표기로 통일** — 태윤님이
        국내 어업종↔GFW 영문 체계 통합 작업을 진행 중. 완료되면 A축(`score/
        scripts/convert_data_new_vessels.py`)과 B축이 같은 영문 taxonomy를
        쓰게 된다 — 지금 `build_axis_b_input.py`가 쓰는 TAC 한글 원본
        (`gearTypeNamesTac`)은 이 통합 결과로 교체 예정. A축 쪽에서 이미
        확인한 참고사항(아래): GFW 영문 gear 값의 44%가 FISHING/NA 같은
        뭉뚱그려진 라벨이라 그대로 그룹핑에 쓰면 유사군이 과도하게 쪼개짐
        (A축 실산출 73%→32%로 급락 실측) — B축은 카테고리 피처로만 쓰여
        같은 문제(표본 부족)는 없지만, 뭉뚱그려진 라벨 자체의 정보량이
        적다는 점은 동일하게 감안할 것.
        (아래는 이 결정 이전의 검토 기록 — 보존)
        후보 3가지만
        기록해둠: (a) `population_tags.jsonl`의 `licenseTag`/`locationTag`
        (근해/연안/원양/양식 등, 뭉뚱그려진 수준)를 그대로 쓰기,
        (b) `data/gear_type_mapping_draft.py`(TAC 19종 매핑 초안)까지 동원해
        세분화, (c) 일단 비워두고(`None`) 톤수·날씨·seaArea·season만 먼저
        연결(`axis_b_baseline.py`는 `gearType`이 없어도 에러 없이 도는 걸
        확인함, 다만 LightGBM이 그 피처를 못 씀).
        **(2026-08-18 추가 조사)** `final_vessel_matches.jsonl`을 직접 열어보니
        TAC 매칭 2,279척 중 `tac.gearTypeNamesTac`가 채워진 건 **1척뿐**이었다
        — 김태윤님이 참고자료로 준 "19개 업종, 상위 7개 200척+" 분포는 이 파일
        기준이 아니라 TAC 원본 전체 기준으로 보임. 원인은 김태윤님이 독립적으로
        같은 시점에 만든 `data_new/process/build_axis_b_input.py`의 주석에 이미
        나와 있었다 — `final_vessel_matches.jsonl`의 `tac` 딕셔너리가 "축약형"이라
        `gearTypeNamesTac`을 안 담고 있고, `vesselNoTac`으로
        `tac_vessels_normalized.jsonl`을 다시 조회해야 복구된다는 것. **다만 이
        파일이 지금 리포에 커밋돼 있지 않아(`.gitignore`로 제외됨,
        `final_vessel_matches.jsonl`/`events_with_weather.jsonl.gz`/
        `gfw_vessels_normalized.jsonl` 3개만 예외) `build_axis_b_input.py`는
        지금 이 환경에서 실행 자체가 안 됨**(`FileNotFoundError`로 직접 확인).
        `tac_vessels_normalized.jsonl`이 공개되면, 이 파일의 gearType 복구
        로직을 `score/real_axis_b_input.py`에 그대로 가져와 반영하면 됨 —
        그때 (a)/(b)/(c) 중 정할 필요 없이 원문 그대로(세분화된 19종) 쓰는
        쪽으로 사실상 답이 나온 셈(표본도 충분하다는 김태윤님 확인 참고, 다만
        그 확인도 TAC 원본 기준이라 실제 매칭된 부분집합에서 표본이 충분한지는
        파일이 나온 뒤 재확인 필요).
        **seaArea 설계 관련 참고**: `build_axis_b_input.py`는 `seaArea`를
        위경도 격자가 아니라 TAC `portNamesTac`(항구명 문자열)로 채우는데,
        `data_new/README.md`에 이미 "TAC 항구정보 커버리지 5.1%뿐"이라는 한계가
        기록돼 있어(다른 용도지만 같은 원본 데이터) 항구명 기반은 결측이 많을
        수 있음 — `region_key()` 격자 기반(현재 방식)을 유지하는 쪽을 오동규는
        더 선호하지만, 이것도 `tac_vessels_normalized.jsonl` 공개 후 실측치
        보고 다시 판단.
      - 결측/미매칭 선박 처리: **해결됨(2026-08-18)** — 병합 스크립트에서 따로
        걸러내지 않고, 없는 필드는 그냥 `None`으로 내려보내 `axis_b_baseline.py`의
        기존 로직(필수 3종 중 하나라도 없으면 `SkippedRow`로 자동 skip, 그 외
        선택 항목은 pandas/LightGBM이 결측치로 처리)에 맡기기로 함. 매칭 자체가
        안 된 선박은 `tonnageGt`가 없을 수밖에 없어 이 로직으로 자동으로
        걸러짐 — 병합 스크립트에서 중복 판단할 필요 없음.
      아직 착수 전.

---

- [x] A축(재방문간격, 혼잡가중압력) 계산 함수 (기획서: 축 A - 자원 지속가능성 지표 산출)
      — `axis_a_pressure.py`. self-exclusion + revisit×congestion 상호작용항까지 반영,
      GFW 이벤트만 있으면 바로 실행 가능.
- [x] B축 물리식 연료추정 (기획서: 축 B - 에너지 효율 지표 산출, Coello et al. 2015 기반)
      — `axis_b_physics.py`. 톤수 매칭된 선박만 커버(매칭률에 따라 대상 확대 예정).
- [~] Coello et al. (2015) 계수 검증 — 2026-08-14 오동규가 원문(같은 저자 박사논문)
      대조. **부하율 공식은 확인·수정 완료**: `LF = 0.9 × (Vi/Vd)³` (Eq. 2.3, p.22,
      0.9는 "설계속도=주기관 최대연속정격의 90%" 해상마진) → `SEA_MARGIN_FACTOR`로
      반영, 기존의 별도 고정 부하율(0.75) 곱셈 구조는 제거. **반면 `POWER_COEFF_A/B`
      (GT→설치출력 회귀식)와 `SFOC_G_PER_KWH`는 Coello 논문에 아예 없는 숫자임을
      확인**함(원문은 GT 회귀가 아니라 실제 선박 등록부 값을 씀, SFOC은 자체 수치
      없이 외부문헌 인용만 지시). Whall et al.(2002)·Parker & Tyedmers(2015)·
      ICES(1980)·IMO GHG Study도 찾아봤으나 이 두 상수의 실제 출처는 못 찾음 —
      **여전히 출처 불명의 대표값**, 원출처 재탐색이나 팀 논의 필요.
      **(2026-08-18 추가 시도) 문헌 탐색 대신 실측 재적합(calibration) 시도**
      — `score/scripts/fit_power_regression.py`. TAC 원본(`data/raw/`)의 실제
      한국 어선 톤수-마력 쌍(1,993~2,140척, 어선번호 기준 중복제거)으로
      `POWER_COEFF_A/B`를 직접 로그-로그 회귀. 결과: a=215.6, b=0.287
      (기존 a=5.46, b=0.70과 크게 다름 — 톤수대별 추정출력이 기존값의
      4.4~15배). **다만 R²=0.383으로 설명력이 약함** — kW/GT 비율 자체가
      선박마다 2.97~187.1(63배 폭)로 흩어져 있어, 톤수 하나로 설치출력을
      예측하는 물리식 구조 자체의 한계로 보임. "할당 어업 종류 명"(19종)별로
      나눠 재회귀해봤으나 16개 중 5개만 R² 개선(연안복합어업 0.603,
      쌍끌이대형기선저인망어업 0.597, 기타통발어업 0.590 등 — 표본도
      23~439척으로 제각각), 나머지는 톤수-마력 관계가 거의 없음
      (근해채낚기어업 R²=0.027 등). **결론: 이 실측 재적합값도 아직
      프로덕션에 넣을 만큼 신뢰도가 높지 않아 적용 보류.** "출처불명 문헌값
      대신 실측 검증값을 쓴다"는 방향 자체는 유효하나, 톤수만으로는 부족하고
      추가 변수(어업종 세분화·선령 등)나 다른 함수형태가 필요할 수 있음 —
      팀 논의 대상으로 남김.
- [~] LightGBM 파이프라인 (기획서: 스코어링 모델 - A/B축 지표를 통합한 신용점수 예측)
      — `axis_b_baseline.py`에 `fit_baseline_model` 등 코드는 구현 완료. 단 실데이터로
      아직 못 돌림: 해양기상 데이터가 이벤트에 미부착, 국내↔GFW 어업종 매핑표 부재.
      **(2026-08-18 해결) 순환성 문제**: 물리식 추정치(estimated_fuel_kg)가
      tonnageGt/averageSpeedKnots/durationHours만의 함수인데 LightGBM 기준선도
      같은 변수를 그대로 받아 잔차가 노이즈가 되는 문제 — `averageSpeedKnots`와
      (속도×기간으로 계산되는) `totalDistanceKm`을 `NUMERIC_FEATURE_COLUMNS`에서
      제외해 해결. 판단 기준: 기대치 입력에는 "배가 어쩔 수 없이 처한 조건"만
      남기고 "배가 스스로 선택한 조업 방식(속도)"은 뺀다. 조건이 같고 속도만
      다른 선박들에서 잔차가 속도와 함께 단조증가하는지 테스트로 확인함
      (`TestResidualCapturesSpeedSignal`, 2개). 기획서 원문은 평균속도도 입력
      후보로 명시하지만 이 결론이 우선한다는 걸 팀에 공유 필요.
- [x] 유사선박군 그룹핑 (기획서: 표본 확보 전략 - 유사 선형/어법 기준 그룹 구성)
      — `peer_grouping.py`. 톤수대×어업종×해역×계절 키로 그룹핑. 해역은 GFW에
      정식 해역 필드가 없어 넓은 격자로 근사(REGION_GRID_SIZE_DEG, 잠정값),
      계절은 상반기/하반기로 근사. 톤수대 폭도 잠정값. 테스트 22개.
- [x] 표본 20척 미만 판정 (기획서: 표본 확보 전략 - 소표본 예외 처리 기준)
      — `peer_grouping.py`의 `PeerGroup.has_sufficient_sample()` +
      `score_assembly.py`의 `score_status_for_group()`
      (`insufficientSample` 상태, mock 스펙과 이름 통일). 기준값(20척)은 잠정값.
- [x] 점수조립(raw → 유사군 백분위 점수) — `score_assembly.py`의 `raw_to_score()`.
      원래 화면이 안 비도록 `ui/adapter.py`가 임시로 들고 있던 로직을 score/로
      옮겨왔다. **`ui/adapter.py`가 이 함수를 쓰도록 바꾸는 배선 작업은 아직 안
      했음 — ui/ 담당(최지희)과 조율 필요.** 테스트 7개.
- [x] 금리구간 A/B/C/D 매핑 (기획서: 스코어 활용 - 신용점수 기반 금리 등급 산정)
      — `rate_mapping.py`. 구간 경계값(78/68/55)·bp는 `ui/bank.py` 목업과 동일한
      잠정값(placeholder)이며, 은행 사전 승인 정책 확정 후 교체 필요. 테스트 12개.
- [x] `ui/adapter.py`의 "개선 시뮬레이터" 트레이드오프 계수 근거 마련
      (`TODO(score/ 김준기·오동규)` 주석으로 지목됐던 4개 잠정값 대응)
      — `tradeoff_coefficients.py`. B축 관련 2개(속도↔B축, 재방문↔B축)는
      `axis_b_physics.py`의 실제 Coello 물리식(속도 3제곱 법칙)에서 차분으로
      계산 — 고정 상수가 아니라 선박 톤수/현재속도에 따라 달라짐(예: tonnage=50,
      operating_hours=5 기준 속도 8kn일 때 약 60점/kn, 20kn일 때 약 26점/kn —
      기존 잠정값 3.2보다 훨씬 크고 속도 의존적임).
      **(2026-08-18 배선 완료)** B축 관련 2개(`axis_b_points_per_knot`,
      `axis_b_points_per_revisit_step`)를 `services/scoring.py`의
      `ScoringService.simulate()`에 실제로 연결함 — 고정 상수
      `AXIS_B_GAIN_PER_KNOT`/`AXIS_B_COST_PER_REVISIT_STEP`은 제거하고, 선박별
      톤수(데모 fixture는 톤수가 없어 `DEMO_FALLBACK_TONNAGE_GT=50.0` 임시값 사용,
      근거 없음)·현재속도 기준으로 매 호출마다 계산. `services/scoring.py`는
      최지희님 소유 파일이라 오동규가 작업 — **최지희 확인 완료(2026-08-18)**,
      같은 날짜에 추가된 A축 격자 크기·재방문 스케일 확정값 변경분도 포함해서 확인받음.
      부작용 확인: `explain/TODO.md` 시연 구성 ③번("최고점은 중간에 있고 끝에서는
      떨어진다")이 실제로 성립하게 됨(VESSEL_A 기준 최고점이 구간 끝이 아니라
      8.6kn에서 나옴, 기존엔 구간 끝이 최고점이었음). 다만 고속 구간 일부에서
      "반작용이 있는 점수가 없는 점수보다 미세하게 높은" 역전이 생기는데, 원인은
      B축 계수가 커지며 바닥값(4.0) 클램프 구간이 넓어졌고 그 구간에서 A축의
      `AXIS_A_COST_PER_KNOT`(위에서 이미 "근거 공식 없음"이라고 밝힌 미검증
      계수)가 그대로 드러나기 때문 — A축 계수는 이번 작업 범위 밖이라 안 건드림,
      `ui/test_simulator_surface.py`의 `TestTradeoffIsVisibleInTheSurface`에
      회귀 테스트로 남겨둠 (**2026-08-18 후속 조사·결론은 위쪽 "팀 논의 필요"
      섹션의 `AXIS_A_COST_PER_KNOT` 항목 참고**). A축 관련 나머지는 아래 문단과 동일.
      A축 관련 1개(재방문→A축)는 raw 압력값 변화량만 계산 가능
      (`axis_a_pressure_raw_delta_for_revisit_step`) — 백분위 변환은 유사군
      분포가 있어야 해서 "점수"로는 못 뽑음. 나머지 1개(속도→A축 비용)는
      코드베이스에 속도-재방문 연결 공식이 아예 없어 못 끌어냄 — 근거 없이
      숫자를 만드는 대신 미모델링 상태임을 명시함, 0에 가깝게 두는 걸 권장.
      테스트 9개.
- [~] AIS 위치정보 통계를 A축 혼잡가중압력에 반영 (`data/ais_location_stats_loader.py`
      참고, 기획서상 "혼잡 가중 압력의 기준값") — 2026-08-15 오동규가 착수 전
      조사만 하고 보류했던 것을 **2026-08-18 실제로 풀었다**. 막혔던 지점
      (연도·월이 안 겹침, 해구↔격자 공간 단위가 다름)을 제안대로 해결:
      `score/ais_congestion_baseline.py` 신설 — 연도·월을 버리고
      **(해구, 시간대)** 평균 통행량으로 집계(`build_congestion_baseline_by_hour`),
      AIS 해구 경계좌표(사각형)로 GFW 이벤트 위경도를 직접 포함판정
      (`find_grid_for_point`)해 공간조인. **실측 검증**: data_new/ 실제
      이벤트 표본 2만 건 중 **95.9%가 AIS 해구 커버리지 안에 들어옴** —
      막연히 "안 될 것 같다"던 문제가 실제로는 잘 풀림. 테스트 10개(합성
      데이터 + 실제 커밋된 AIS 파일로 통합검증).
      **여기까지만 함**: `axis_a_pressure.py`의 `congestion_density_raw` 계산식
      자체를 이 기준값으로 어떻게 보정할지(대체/가중평균/이상치 처리 등)는
      검증 안 된 설계 결정이라 이번엔 결합하지 않음 — "조회 가능하게 만드는
      것"까지가 오늘 범위, 실제 결합은 다음 단계.
- [x] 실제 데이터로 A축 실산출 검증 (`explain/TODO.md` P0-3 "실산출 1척" 대응)
      — `scripts/run_real_axis_a.py`. 실제 수집 데이터(`data/raw/gfw_events_
      2026-01-01_2026-08-13.jsonl.gz`, 91.4만 건 + `gfw_vessels_enriched.jsonl.gz`,
      3.1만 척)로 `compute_axis_a_pressure` → `build_peer_groups` →
      `raw_to_score`까지 전체 파이프라인이 실제로 동작함을 확인(9,723척 계산,
      42초). 예시 선박 1척이 유사군 137척(기준 20척 이상) 중 백분위 48.9점으로
      실산출됨. **화면(`ui/adapter.scoring_backend()`) 배선 전환은 최지희님
      담당 — 여기서는 "된다"만 증명, 배선은 안 건드림.**
      주의: 대부분 선박의 톤수 매칭이 아직 안 끝나서(tonnage_band=None인 채로
      그룹핑됨) 정식 실행 전 매칭 완료를 기다리는 게 맞다.
      **현재** `scripts/run_real_axis_a.py`는 위 레거시 파일이 아니라
      `load_real_vessel_records()`의 추적 스냅샷을 직접 사용한다.
- [x] **(2026-08-18) `services/real_scoring.py`의 A축 실산출을 `data_new/`로
      전환** — 구 `data/`(31,605척, 확정매칭 순도 9.5%) 대신 `data_new/`
      (EEZ 제한 5,323척, 사람 라벨링 실측 정밀도 약 75%)를 쓰도록
      `DEFAULT_EVENTS_PATH`/`DEFAULT_VESSELS_PATH`를 교체(최지희님 파일이라
      확인 후 진행). 이벤트는 `data_new/processed/events_with_weather.jsonl.gz`
      필드가 그대로 맞아서 변환 없이 바로 씀. 선박은
      `scripts/convert_data_new_vessels.py`로 `final_vessel_matches.jsonl`의
      중첩·문자열 톤수(`tac.tonnageGtTac`/`mof.tonnageGtMof`)를 평판화(테스트
      6개). `services/metadata.py`의 `REAL_DATA_SNAPSHOT_ID`도 실제 데이터
      출처와 맞게 갱신(최지희님 파일, 라벨이 실제와 안 맞으면 재현성 계약이
      깨져서 같이 고침).
      **이전 결과(gearType 미반영 시점)**: 5,323척 중 `partial`(A축 실산출됨)
      3,887척(73%), `insufficientSample` 1,427척(27%), `matchingFailed` 9척.
      **(2026-08-18 후속) `gfw_vessels_normalized.jsonl` 공개돼 fishingType
      반영함** — `load_gear_types()`가 GFW `combinedGearTypes`를 읽어 채움.
      단, **실측으로 큰 트레이드오프를 발견**: 뭉뚱그려진 라벨(FISHING/NA 등,
      전체 44%)까지 그대로 그룹 키로 쓰면 유사군이 과도하게 쪼개져서 A축
      실산출이 73%→32%로 급락함. 자기모순 라벨(CARGO 등)과 함께 뭉뚱그려진
      라벨도 제외(=None 취급, 구체적 gear만 그룹핑에 씀)하도록 수정해서
      42.6%(2,269척)까지 회복. **여전히 gearType 미사용(73%)보다는 낮음** —
      팀 논의 결과 현재 버전(구체적 gear만)으로 일단 유지, 태윤님이 국내
      어업종↔GFW 영문 통합 작업을 별도로 진행 중이라 그 결과 나오면
      재검토 예정. 테스트 7개 추가(자기모순/뭉뚱그림 라벨 제외 검증 포함).
- [x] **(2026-08-18) B축 실산출을 API에 연결** — `score/real_axis_b_scoring.py`
      신설(B축 이벤트 입력→학습→추론을 캐싱해 API에서 쓸 수 있게 함).
      `services/real_scoring.py`(최지희님 파일)에 B축 결과를 연결해 A축과
      같은 유사 선박군으로 백분위 변환, `services/scoring.py`에서 A+B
      가중합(0.65/0.35)으로 BlueScore·금리구간까지 완성(최지희님 확인 후
      진행). **이전 결과**: 5,323척 중 864척(16.2%)이 A축+B축 모두 실산출돼
      `success` 상태로 BlueScore·금리구간까지 나옴(나머지는 이전처럼 A축만
      `partial` 또는 표본부족/매칭실패 — B축 연결이 기존 A축 단독 경로를
      깨지 않음, 예외로 안전하게 흡수). 한계는 응답 `message`에 항상 명시
      (해양기상 단위 추정, 유속 단위 미확인, gearType 커버리지 등).
      `services/metadata.py`의 `model_version`도 선박별 B축 포함 여부에 따라
      동적으로 갈리도록 고침(`REAL_MODEL_VERSION_WITH_B` 추가).

      **연결 중 실제로 겪은 캐싱 버그**: `services/workflow.py.get_score()`가
      `sourceType=real`에는 캐시 신선도 체크가 아예 없었다(데모만 체크) —
      `score_run_id`가 `real-axis-a-{vesselId}-20260813`처럼 고정 문자열이라
      SQLite에 한 번 캐싱되면 코드를 고쳐도 영원히 옛날 응답이 나오는 걸
      실제로 겪음(오늘 세션에서 data_new 전환 이후 첫 캐시가 이미 껴 있어서
      B축 연결 직후에도 옛 modelVersion이 계속 나왔음). `_is_current_real_score()`
      추가해서 `data_snapshot_id`/`model_version`이 지금 코드가 낼 수 있는
      값과 다르면 캐시를 버리고 재계산하도록 고침 — 앞으로 데이터/모델
      버전을 올리는 변경이 있으면 이 체크가 자동으로 캐시를 무효화한다.
- [x] **(2026-08-18) 매칭 오탐 필터(숫자접두어 불일치) 적용** — 태윤님이 올린
      `data_new/matching_redesign_proposal/`(한글비교 매칭 재설계 제안) 검토 중,
      제안서가 인용한 PROCESS_LOG 49번 근거("번호 일치 시 정밀도 95~100%,
      불일치 시 0%")가 실제 라이브 코드(`data_new/process/assemble_matches.py`)엔
      반영이 안 돼 있던 걸 발견. 제안 A(현행 유지)/B(숫자필터만 추가)/C(한글
      비교로 전체 교체, 커버리지 54.1%→17.2~27.3%) 중 B를 선택 — C는 정밀도
      98%+가 사람 검증 0건인 추정치라 마감 임박 시점에 들이기엔 위험 판단.
      이미 커밋된 `final_vessel_matches.jsonl`(5,323척)로 먼저 시뮬레이션해
      확인: tier3_fuzzy_name 2,878척 중 매칭명 텍스트 확인 가능한 2,311척
      (tac/mof 출처, vessel_registry 출처 567척은 로컬에 매칭명 텍스트가 없어
      검증 불가) 안에서 GFW 자기신고명과 매칭명의 숫자(선단 번호)가 둘 다
      있는데 서로 다른 경우 77건 확인(예: `26 NAM GANG HO`↔`203남광호`,
      fuzzyScore 0.833으로 이미 고신뢰 판정돼 있었음). `assemble_matches.py`에
      `_numeric_mismatch()` 필터를 추가해 향후 재실행에도 반영되게 하고
      (2026-08-18, 김준기, 태윤님 원본 raw 데이터가 로컬에 없어 파이프라인
      처음부터 재실행해 전체 재검증은 못 함 — 태윤님 재실행 결과가 이 설명과
      크게 다르면 확인 필요), 같은 로직으로 이미 커밋된
      `final_vessel_matches.jsonl`에도 직접 78건(런타임 재확인 시 1건 추가
      포착)을 `unmatched`로 강등 적용 후 `convert_data_new_vessels.py`로
      `vessels_for_score.jsonl.gz` 재생성함. **결과**: A축 실산출 61.0%→61.4%
      (사실상 동일), BlueScore 완전 산출 16.2%(864척)→15.2%(807척)로 소폭
      감소 — 확인된 오탐 제거의 정상적인 대가. `ui/real_preview.py`·
      `services/scoring.py`·`services/real_scoring.py`의 하드코딩된 커버리지
      수치 주석도 갱신함. **이 값도 현재 TAC 한글 직접비교 스냅샷 이전 결과이며,
      현재 완전 산출은 289척이다.** 제안 C(한글비교 전체 교체)는 이번 제출 범위에서는
      보류 — 다음 라운드에 사람 검증 거쳐 재논의.
