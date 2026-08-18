# data_new 완료 체크리스트

담당: 김태윤

> 전체 구조·설계 근거·최종 수치·한계는 `README.md` 참고. 여기는 진행
> 체크리스트만.

## 현재 서비스 통합 상태

- production은 추적 파일 `final_vessel_matches.jsonl`,
  `gfw_vessels_normalized.jsonl`, `events_with_weather.jsonl.gz`를 직접 읽는다.
- `tac_vessels_normalized.jsonl`은 Git에서 추적하지만 매칭 재생성·검증용이며
  production 서비스 입력은 아니다.
- B축 입력은 `score/real_axis_b_input.py`에서 공용 선박 입력을 재사용한다.
- `data_new/process/build_axis_b_input.py`는 같은 공용 함수를 호출하는 선택적
  분석용 exporter로 유지한다 — production 경로가 아니다.
- 현재 건수는 선박 5,323척, 톤수 712척(13.4%), fishingType 2,682척, 둘 다
  368척이다.

## 완료 — 계획·설계

- [x] 도메인 지식 정리, 기획서 대조 확인
- [x] 데이터 스키마 초안, 외부 계약(score/chain/explain/ui 요구 필드) 확정
- [x] 수집 원칙 설계, 소스 후보 실측 확인(GFW/TAC/해양기상 등)
- [x] 모집단 범위 확정 — flag=KOR AND 한국 EEZ 내 FISHING 이벤트

## 완료 — 수집·가공

- [x] 수집 스크립트 작성(GFW 이벤트/선박, 해양기상) 및 검증
- [x] TAC 정적 파일 배치·구조검증
- [x] GFW 이벤트/선박 정규화, TAC 정규화
- [x] 해양기상 부착
- [x] 전체 파이프라인 end-to-end 재실행 검증, `README.md` 작성

## 완료 — 실규모 수집

- [x] GFW 이벤트·선박 본수집 완료 — 검증 게이트 통과
- [x] 해양기상 실규모 수집 완료
- [x] process/ 파이프라인 전체 실규모 재실행 완료

## 완료 — 매칭 재설계

- [x] 로마자 유사도 → 한글 직접비교로 전체 교체 — 구조적 오탐 제거
- [x] 어선원부 후보풀에서 제외 — 신뢰도 낮은 구식 자료
- [x] TAC 쪽 유일성 강제(5단계 추가) — 중복배정 오류 제거
- [x] GFW `registryInfo` 있는 선박 후보풀에서 제외 — 원양선 오매칭 제거
