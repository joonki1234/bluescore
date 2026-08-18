## 담당: 김준기, 오동규

# score TODO

## 진행 현황 정리 (2026-08-18 갱신)

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

**지금 오동규·김준기 단독으로 더 진행할 수 있는 항목은 없고, 남은 건 전부
아래 팀 논의 필요 목록뿐이다.**

**팀 논의 필요 (최지희 제외)**
- AIS 위치정보 통계를 A축에 어떻게 반영할지 (아래 항목, 제안만 해둔 상태)
- 선박제원 매칭 품질 이슈 — 확정 매칭 663건 중 90.5%(600건)가 비어선으로 확인됨
  (`data/BlueScore_지희님질문_매칭품질_20260814.md`,
  `data/BlueScore_모집단뒤집기_조사_20260818.md` 참고)
- 국내→GFW 어업종 매핑표(19종) — 담당 미정 (`data/TODO.md` 참고)
- CLAUDE.md "미확정 항목" 3개 (유사군 최소 표본, GAP 비율 임계값, 매칭 신뢰도
  임계값) — 격자 크기·재방문 기간은 2026-08-18 확정됨(아래 항목, CLAUDE.md
  확정된 규칙 8번 참고)
- 기관출력 단위(HP/PS) 확인 (`data/TODO.md` 참고)
- GT→설치출력 회귀계수·SFOC 원출처 — 이번 조사로는 못 찾음, 새 단서 없이는
  더 진행 불가 (아래 항목)
- `AXIS_A_COST_PER_KNOT`(`services/scoring.py`) 미검증 계수 부작용 — 트레이드오프
  계수 배선 항목 참고

---

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
      회귀 테스트로 남겨둠. A축 관련 나머지는 아래 문단과 동일.
      A축 관련 1개(재방문→A축)는 raw 압력값 변화량만 계산 가능
      (`axis_a_pressure_raw_delta_for_revisit_step`) — 백분위 변환은 유사군
      분포가 있어야 해서 "점수"로는 못 뽑음. 나머지 1개(속도→A축 비용)는
      코드베이스에 속도-재방문 연결 공식이 아예 없어 못 끌어냄 — 근거 없이
      숫자를 만드는 대신 미모델링 상태임을 명시함, 0에 가깝게 두는 걸 권장.
      테스트 9개.
- [ ] AIS 위치정보 통계를 A축 혼잡가중압력에 반영 (`data/ais_location_stats_loader.py`
      참고, 기획서상 "혼잡 가중 압력의 기준값") — 2026-08-15 오동규가 착수 전
      조사만 하고 보류. **막힌 지점**: 이 통계 데이터는 2019-10-01~2020-03-31
      기간뿐인데, 실제 A축 산출에 쓰는 GFW 이벤트는 2026년 데이터다 — 로더의
      `build_vessel_count_index()`가 쓰는 `(해구, 날짜, 시간)` 키로는 정확한
      날짜 매칭이 원천적으로 불가능하다(연도 자체가 안 겹침). 공간 단위도
      AIS는 "해구", A축은 0.05도 격자라 경계좌표로 공간조인이 별도로 필요함.
      제안(미확정, 팀 논의 필요): 연도를 버리고 (해구, 시간대) 또는 (해구, 월,
      시간대) 평균 통행량으로 집계해 "이 해역은 보통 이 시간대에 이 정도
      붐빈다"는 계절/시간대 패턴으로만 쓰는 방식 — `GRID_CELL_SIZE_DEG`처럼
      잠정값+TODO로 남겨두고 반영.
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
      **결과(gearType 미반영 시점)**: 5,323척 중 `partial`(A축 실산출됨)
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
