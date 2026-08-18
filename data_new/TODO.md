# data_new TODO

> 상세 진행 기록(왜 그렇게 정했는지)은 `PROCESS_LOG.md` 참고. 전체
> 구조·실행법은 `README.md` 참고. 여기는 체크리스트만.

## 현재 서비스 통합 상태 (2026-08-19)

- production은 추적 파일 `final_vessel_matches.jsonl`,
  `gfw_vessels_normalized.jsonl`, `events_with_weather.jsonl.gz`를 직접 읽는다.
- `tac_vessels_normalized.jsonl`은 현재 Git에서 추적하지만 매칭 재생성·검증용이며
  production 서비스 입력은 아니다.
- B축 입력은 `score/real_axis_b_input.py`에서 공용 선박 입력을 재사용한다.
  `gearType`은 구체적인 GFW fishingType을 결정론적 대표값으로 연결하며 147,441개
  이벤트에 존재한다. 제외 규칙은 CARGO/PASSENGER/CARRIER와 FISHING/OTHER/NA/
  INCONCLUSIVE/GEAR/FIXED_GEAR/TROLLERS/OTHER_PURSE_SEINES/OTHER_SEINES다.
- 현재 건수는 선박 5,323척, 톤수 712척(13.4%, TAC 유일성 강제 + 원양선
  registryInfo 제외 반영 후 최종값 — `README.md`·`matching_redesign_proposal/
  README.md` 참고), fishingType 2,682척, 둘 다 368척이다.
  아래의 다른 건수와 파일 부재 설명은 당시 조사 기록으로 보존한다.

## 완료 — 1~6번(계획·설계 단계)

- [x] 도메인 지식 정리 (수산업 제도·어법·AIS·선박공학·해양환경·수산자원관리)
- [x] 기획서(2026-08-11) 대조 확인
- [x] 데이터 정의(스키마) 초안 — `SCHEMA_DRAFT.md`
- [x] score/chain/explain/ui 요구 필드명 = 외부 계약으로 확정
- [x] 수집 원칙(방법론) 설계 — 12개 항목 확정
- [x] 소스 후보 탐색 + sanity call — GFW/MOF/TAC/어업별어선/어선원부/해양기상 전부 실측 확인
- [x] 조인 키(식별자) 설계 — GFW vesselId 허브, 4단계 매칭 전략
- [x] 모집단 범위 확정 — flag=KOR AND 한국 EEZ 내 FISHING이벤트, 근해/연안·양식업은 태그로 보류

## 완료 — 7번(본수집)

- [x] 수집 스크립트 4개(`collect/gfw_events.py`/`gfw_vessels.py`/`mof.py`/`marine_weather.py`) + 소량 실검증
- [x] 정적 파일 3종(TAC/어업별어선/어선원부) `raw/`에 배치 + 구조검증(`collect/static_files_check.py`)
- [x] 버그 4개 발견·수정(HTTP 201 미처리, 네트워크 재시도 누락, 콘솔 인코딩 크래시, 인증키 메타노출)

## 완료 — 8번(가공/매칭 파이프라인)

- [x] GFW 이벤트/선박 정규화 — durationHours 100% null 발견·수정(start/end로 직접계산), registry/selfReported 출처 분리
- [x] TAC/어선원부/MOF/어항정보 정규화
- [x] 매칭 1~4단계(정확일치→콜사인→이름fuzzy(톤수+해역보너스)→최종조립) — 10척 표본 70% 매칭
- [x] 근해/연안·양식업 태그 — MR 공식 통계코드 체계로 매핑표 구성, 2,562척 실행
- [x] 해양기상 부착 — 날짜별 재수집 필요성 발견, 시계열 응답구조 파악, 2,295건 부착

## 완료 — 9번(검증 게이트 + 문서화)

- [x] 전체 파이프라인 end-to-end 재실행 검증(수집 제외, 가공 스크립트 전부)
- [x] `README.md` 작성 — 폴더구조·실행순서·현재상태·한계 정리
- [x] `PROCESS_LOG.md` 섹션 번호 정합성 정리

## 진행중 — 10번(실규모 본수집)

- [x] GFW 이벤트 본수집 완료 — 2026-04-01~08-14, 한국 EEZ, FISHING, 276,562건, 검증 게이트 통과
- [x] 이벤트 탐색적 분석(`analysis/explore_events.py`) — 선박당 분포·월별·공간밀집·mpa비율·duration이상치, PROCESS_LOG.md 30번
- [x] 선박 탐색적 분석(`analysis/explore_vessels.py`) — registryInfo율·flag분포·이름없음661척·speed/distance이상치, PROCESS_LOG.md 34번
- [x] 매칭 탐색적 분석(`analysis/explore_matches.py`) — fuzzyScore분포·구제후보909척·톤수이상치140979GT·태그별매칭률, PROCESS_LOG.md 37번
- [x] GFW 선박 상세조회 완료 — 5,323/5,323척, 실패 0, 검증 게이트 통과, PROCESS_LOG.md 32번
- [x] 해양기상 실규모 수집 완료 — 2026-04-01~08-14, 13개 지방청, 검증 게이트 통과
- [x] MOF 실규모 수집 완료 — 4,662건(병렬화 15동시, 실패 0), 검증 게이트 통과, PROCESS_LOG.md 33번
- [x] process/ 파이프라인 전체 실규모 재실행 완료(정규화→매칭 1~4→태깅→기상부착), 버그 2개 수정, PROCESS_LOG.md 35번

## 남음 — 실규모 데이터 확보 후

- [x] **매칭 정밀도 재평가 완료(49번)** — 사람 라벨링(80쌍, 층화 랜덤추출) 결과 실제 정밀도는 **약 75%**(0.95+ 구간 92.9%, 임계값 올릴수록 정밀도도 올라감). 48번의 11~22% 경고는 MOF 경유 매칭에 편향된 표본이었던 것으로 결론(48번 자체는 "MOF 경유 매칭만 위험"으로 범위 한정해서 여전히 유효)
- [ ] **[실행 가능]** 44번 숫자접두어 신호로 unmatched 134척 타겟 구제 + 기존 매칭 중 번호불일치 78척 재검토 — 49번에서 강하게 확인됨(번호일치 95~100% 정밀도, 번호불일치 0%, n은 작지만 일관됨). 회의에서 반영 여부만 결정하면 됨
- [ ] MOF 경유 매칭(191척, tier3의 6.6%)만 낮은 정밀도로 별도 취급할지 검토 — 48번 결론 범위 한정판
- [x] 톤수(GT) 이상치 수정 완료 — MOF 후보에 `vsslKnd`(91/92=어선만) 필터 적용, 재실행 후 max 140,979→7,765GT로 정상화(39·41번). 매칭 106척 감소(2,984→2,878, 오매칭 제거 대가)
- [x] totalDistanceKm 이상치(772.99km) 원인 규명 완료 — 4.5일짜리 실제 장기 조업이벤트, 속도×시간 물리적으로 일관됨, 이상치 아님(42번)
- [x] 3월 이벤트 780건 원인 규명 완료 — GFW API가 조회기간과 이벤트 구간이 겹치기만 해도 포함시킴(경계매칭 아님), eventId 중복제거로 이미 안전하게 처리되고 있음 확인(43번)
- [ ] 해역신호용 어항정보 확장 — 실효성 정량 확인 결과 예상보다 심각(TAC 항구명의 5.1%만 커버, locationBonus 실작동 9.9%뿐). 단순 리스트 확장보다 TAC `portNamesTac`의 항구명/행정구역명 혼재 문제부터 정리 필요(46번)
- [x] score/ 필드명 계약 검증 완료(47번) — **47번 당시에는 B축 연결 스크립트가 없었으나 현재 해결됨.** A축은 공용 선박 입력, B축은 `score/real_axis_b_input.py`가 필드 변환을 담당한다. 당시 발견한 날씨 단위 미확인 사항은 8번 모델·정책 검증 대상으로 유지한다.
- [x] (위 발견에 따라) events_with_weather.jsonl.gz + final_vessel_matches.jsonl을 B축 요구 형태로 합치는 스크립트.
      **완료(2026-08-18, 오동규)**: `score/real_axis_b_input.py` + 검증 스크립트
      `score/scripts/run_real_axis_b.py`. 실제 이 폴더 산출물(275,782개 이벤트,
      5,314척)로 B축 파이프라인이 실제로 도는 것까지 확인함(2,310척 실산출).
      `population_tags.jsonl`이 아직 없다는 것 확인하고 그것과 무관하게
      진행함 — `gearType`은 이번엔 비워둠(`None`), `seaArea`/`season`은
      `score/peer_grouping.py`의 `region_key()`/`season_key()`를 이벤트 자체의
      위경도·시각으로 재계산해 채움(태그 파일 안 기다림). 상세는
      `score/TODO.md`의 같은 항목 참고. **김태윤 확인 필요한 것**: 톤수
      (`tac.tonnageGtTac`/`mof.tonnageGtMof` 중 있는 값 사용, 둘 다 있는 행은
      0건 실측 확인함)와 날씨 필드 매핑(단위는 정황상 m/s·°C로 추정만 하고
      진행 — `score/real_axis_b_input.py` 모듈 docstring 참고).

      **(2026-08-18 병합 당시 기록 — 현재 해결됨) 같은 목적의 스크립트가 두 개가 됐다** —
      김태윤이 거의 같은 시각에 독립적으로 `data_new/process/
      build_axis_b_input.py`를 만들어서 git merge 충돌이 났다(`score/scripts/
      run_real_axis_b.py`에서, 서로 다른 두 스크립트를 각자 참조하고 있었음).
      정리한 내용:
      - `build_axis_b_input.py`가 `gearTypeNamesTac`이 `final_vessel_matches.jsonl`의
        축약 `tac` 딕셔너리엔 없다는 것까지 이미 정확히 찾아내서
        `tac_vessels_normalized.jsonl`을 `vesselNoTac`으로 재조회해 복구하는
        방식으로 해결해뒀음 — 오동규가 직접 실행해보려 했지만
        **`tac_vessels_normalized.jsonl`이 `.gitignore`로 제외돼 있어서
        (`data_new/processed/`는 3개 파일만 예외) 지금 이 환경에서는 파일이
        없어서 실행 자체가 안 됨**(`FileNotFoundError` 직접 확인).
      - 부수적으로 하나 더: 당시 이 스크립트는 확장자 `.gz`가 빠진 비압축
        파일명을 찾았는데, 실제 커밋된 파일명은 `events_with_weather.jsonl.gz`라
        `tac_vessels_normalized.jsonl`이 채워져도 이 부분은 한 번 더 고쳐야 할
        것으로 보임.
      - 일단 `run_real_axis_b.py`는 실제로 지금 돌아가는 `score/real_axis_b_input.py`
        쪽(HEAD)으로 충돌 해결함 — `build_axis_b_input.py`를 못 쓰는 게 아니라
        지금 당장 재현이 안 돼서다.
      - **부탁드리는 것**: `tac_vessels_normalized.jsonl`을 다른 두 파일처럼
        `data_new/processed/`에 공개해주시면, 그 gearType 복구 로직을
        `score/real_axis_b_input.py`에 그대로 반영해서 `gearType`을 채우겠음.
        `seaArea`도 이 스크립트는 TAC 항구명(`portNamesTac`)으로 채우는데,
        `data_new/README.md`에 이미 적힌 "TAC 항구정보 커버리지 5.1%뿐" 한계가
        마음에 걸려서 오동규는 지금 방식(위경도 격자)을 당분간 유지하고
        싶음 — 파일 받은 뒤 실측치 보고 다시 얘기하면 좋겠음.

      **담당 논의 결과(2026-08-18, 오동규·김태윤)**: score팀(오동규·김준기)이 `score/` 쪽에
      작성. 근거: 이 스크립트는 `data_new/processed/`의 기존 파일을 원본 그대로
      읽어서 score가 원하는 이름으로 새로 변환/병합하는 것뿐이라, 어느 쪽에
      둬도 `data_new/process/`의 기존 코드·필드명은 안 건드림(같은 패턴:
      `data/vessel_spec_client.py`가 MOF 원본 필드명을 그대로 받아 자체
      정규화, `services/real_scoring.py`가 GFW 원본 필드명을 그대로 읽어 A축
      계산 — 둘 다 원본 소스는 안 바꾸고 받는 쪽에서 번역함). 최종 형태(score/
      요구 스키마)를 score팀이 제일 잘 알아서 score팀이 짜기로 함.
      **단, 필드 매핑표(원본 필드 -> score/ 필드, 특히 날씨 단위·gearType 근거)는
      김태윤이 확인**하기로 함 — 원본 구조는 데이터팀이 제일 잘 앎.
      진행 상황은 `score/TODO.md`에 기록.

      **현재 정리(2026-08-19)**: `tac_vessels_normalized.jsonl`은 Git에서 추적
      중이다. 다만 production은 이 파일이나 `axis_b_input.jsonl`을 읽지 않고,
      공용 GFW fishingType과 압축 이벤트 스냅샷을 메모리에서 직접 변환한다.
      `data_new/process/build_axis_b_input.py`는 같은 공용 함수를 호출하는 선택적
      분석용 exporter로만 남겼다. `attach_weather.py`의 기본 출력도 현재 추적
      파일명인 `events_with_weather.jsonl.gz`로 통일했다.
