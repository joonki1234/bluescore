# 담당: 최지희

# BlueScore UI 최소 요구사항 동결본

> 동결일: 2026-08-17  
> 범위: API·DB·모델 연결을 시작하기 위해 필요한 화면 흐름과 데이터 항목만 고정한다.
> 색상·간격·모바일 배치 등 시각 디자인은 API 연결 후 다시 다듬는다.

## 공통 원칙

- 어업인과 금융기관은 동일한 `scoreRunId`의 점수와 리포트를 본다.
- 화면은 점수·금리·해시를 직접 계산하지 않고 API 응답만 표시한다.
- 모든 결과에는 `dataSnapshotId`, `modelVersion`, `scoringRuleVersion`,
  `rateTableVersion`, `sourceType`이 포함된다.
- `sourceType`은 `real`, `estimated`, `demo` 중 하나다. A축만 실산출된 경우
  총점을 추정하지 않고 상태를 `partial`로 반환한다.
- 시연용 가명 선박은 실제 선박으로 오인되지 않도록 `demo` 배지를 표시한다.
- 원본 항적·개인정보·이의제기 본문은 온체인에 기록하지 않는다.

## 페르소나 1 — B구간에서 A구간으로 개선

1. `VESSEL_A`의 현재 점수, B구간, 점수 근거를 확인한다.
2. 개선팁을 확인한다.
3. 연속 조업 횟수와 평균 항해속도를 바꾼다.
4. 동일한 `scoreRunId`를 기준으로 개선 후 점수와 A구간 진입을 확인한다.
5. 시뮬레이션은 저장된 점수를 바꾸지 않으며 예상 결과로만 표시한다.

필수 응답: 현재/예상 점수, A·B축, 유사군, 현재/예상 우대구간, 개선 행동,
축 간 상충효과, 산출 버전, 데이터 출처 유형.

## 페르소나 2 — C구간 이의제기와 금융기관 심사

1. `VESSEL_B`의 C구간, 요인별 상세 설명과 데이터 출처를 확인한다.
2. 어업인이 해당 `scoreRunId`에 이의제기를 제출한다.
3. 금융기관은 전체 이의제기 목록에서 건을 선택하고 동일 점수·리포트를 확인한다.
4. 심사역이 승인 또는 보류와 사유를 저장한다.
5. 확정 리포트 payload의 해시를 커밋하고 Record ID로 기록을 조회한다.

필수 상태 전이: `submitted → approved | held`. 실제 온체인 연결 전 로컬 원장으로
실행한 기록은 `ledgerMode=local`과 `sourceType=demo`로 명확히 구분한다.

## API 경계

- `GET /vessels`, `GET /vessels/{id}/score`
- `POST /vessels/{id}/simulate`, `GET /vessels/{id}/explanation`
- `POST /appeals`, `GET /appeals`, `GET /appeals/{id}`
- `POST /appeals/{id}/review`
- `POST /reports/{scoreRunId}/commit`, `GET /chain/records/{recordId}`

응답 계약의 단일 원본은 `api/schemas.py`, 시연 입력의 단일 원본은
`fixtures/personas.json`으로 한다.
