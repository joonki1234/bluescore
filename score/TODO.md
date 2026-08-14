## 담당: 김준기, 오동규

# score TODO

- [x] A축(재방문간격, 혼잡가중압력) 계산 함수 (기획서: 축 A - 자원 지속가능성 지표 산출)
      — `axis_a_pressure.py`. self-exclusion + revisit×congestion 상호작용항까지 반영,
      GFW 이벤트만 있으면 바로 실행 가능.
- [x] B축 물리식 연료추정 (기획서: 축 B - 에너지 효율 지표 산출, Coello et al. 2015 기반)
      — `axis_b_physics.py`. 톤수 매칭된 선박만 커버(매칭률에 따라 대상 확대 예정).
- [~] LightGBM 파이프라인 (기획서: 스코어링 모델 - A/B축 지표를 통합한 신용점수 예측)
      — `axis_b_baseline.py`에 `fit_baseline_model` 등 코드는 구현 완료. 단 실데이터로
      아직 못 돌림: 해양기상 데이터가 이벤트에 미부착, 국내↔GFW 어업종 매핑표 부재.
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
