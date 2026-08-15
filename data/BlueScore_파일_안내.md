# 담당: 김태윤

# data 폴더 파일 안내

> `data/`에 파일이 많아져서 뭐가 뭔지 구별하기 어려워 정리했습니다. 폴더 구조는 그대로 두고(옮기면 import가 깨질 위험이 있어서), 파일별로 뭐 하는 건지만 정리한 목록입니다.

## 1. 외부 API에서 데이터 가져오는 "클라이언트"

한 번 호출해서 데이터를 받아오는 역할만 함. 대량 수집은 아래 2번 스크립트들이 이걸 반복 호출해서 함.

| 파일 | 어떤 데이터 |
|---|---|
| `gfw_client.py` | Global Fishing Watch — 선박 목록, 조업이벤트 |
| `vessel_spec_client.py` | 국내 선박제원정보(공공데이터포털) — 콜사인/이름으로 톤수·길이 조회 |
| `marine_weather_client.py` | 해양기상(국립해양측위정보원) — 관측지점별 풍향·수온 등 |
| `ais_stats_client.py` | 연안AIS 통계 — 아직 막혀있음(키 등록 문제, `BlueScore_팀공유_현황.md` 5번 참고) |
| `http_retry.py` | 위 클라이언트들이 공통으로 쓰는 재시도(429/5xx 에러) 로직 — 이 파일 자체는 호출 안 함 |
| `snapshot_utils.py` | 스냅샷 파일(날짜/타임스탬프가 이름에 붙는 파일들) 중 가장 최근 것을 자동으로 찾아주는 공통 함수. 다른 스크립트들이 입력 파일 경로를 하드코딩하지 않도록 씀 |

## 2. 대량 수집·매칭 스크립트 (직접 실행하는 것들)

실제로 `python data/xxx.py`로 돌리는 파일들. 수집(원본 그대로 받기)과 가공(판단이 들어가는 것)을 분리해뒀습니다.

| 파일 | 단계 | 하는 일 |
|---|---|---|
| `collect_vessel_spec_candidates.py` | 수집 | GFW 선박마다 국내 선박제원 후보를 찾아서 저장만 함 (판단 없음) |
| `match_vessel_spec.py` | 가공 | 위 후보 중 진짜 같은 배가 뭔지 판정 (IMO/콜사인/이름 유사도) |
| `build_enriched_vessel_population.py` | 가공 | 위 매칭 결과를 GFW 선박 목록에 합쳐서 `gfw_vessels_enriched.jsonl.gz` 만듦 — **score팀이 실제로 쓰는 최종 파일** |
| `match_tac_vessels.py` | 가공 | TAC 데이터(마력 정보)를 GFW 선박과 이름으로 매칭 |
| `merge_tac_into_enriched.py` | 가공 | 위 TAC 매칭 확정본을 `gfw_vessels_enriched.jsonl.gz`에 합침 |
| `collect_event_weather.py` | 수집 | 조업이벤트 위치·날짜 기준으로 해양기상 원본을 받아서 저장만 함 |
| `attach_event_weather.py` | 가공 | 위 해양기상 원본을 실제 조업이벤트에 붙임 → `gfw_events_with_weather.jsonl.gz` |
| `build_matching_overview.py` | 진단용 | MOF·TAC(경로A/B) 매칭 결과를 필터링 없이 GFW 선박 9,468척 전부에 옆으로 이어붙인 통합 뷰. `gfw_vessels_enriched.jsonl.gz`와 달리 신뢰도 상관없이 다 담겨있음 → `gfw_matching_overview__*.csv`(엑셀로 바로 열기용) |
| `aggregate_tac_by_gear_type.py`(2026-08-15 추가) | 가공 | TAC를 개별매칭 대신 **업종 단위로 집계**해서 GFW gear type에 평균 톤수·마력을 붙임 → `tac_gear_type_aggregates.json`. ⚠ `gear_type_mapping_draft.py` 초안에 92.2% 의존 — 팀 확정 전 잠정치 |
| `build_master_registry.py`(2026-08-15 추가) | 진단용 | GFW/MOF/TAC개별/TAC업종집계를 재수집 없이 "선박 하나=한 줄"로 통합 → `master_vessel_registry__*.jsonl.gz` |
| `filter_self_contradicting_labels.py`(2026-08-15 추가) | 진단용 | GFW가 스스로 CARGO/PASSENGER/CARRIER라고 신고한 배가 FISHING으로 분류된 경우를 찾음(25척) → `gfw_self_contradicting_vessel_ids__*.json`. 삭제 아니라 플래그용 |
| `population_funnel_report.py`(2026-08-15 추가) | 진단용 | 국적등록→어업선박분류→활동확인→최종모집단 각 단계 이탈률을 실행할 때마다 자동 확인 |

## 3. 파일 그대로 읽는 "로더" (API 아님, 이미 받아둔 파일 파싱만)

| 파일 | 읽는 파일 |
|---|---|
| `ais_location_stats_loader.py` | 해양수산부 AIS 위치정보 통계 (TXT, 77만 행) |
| `fishery_vessel_stats_loader.py` | 어업별어선 통계 (CSV, 업종별 마력 보정값) |
| `tac_status_loader.py` | TAC 어종별 소진현황 (XLSX) |

## 4. 도메인 판단이 들어간 초안

| 파일 | 내용 |
|---|---|
| `gear_type_mapping_draft.py` | 국내 어업종 19개 ↔ GFW gear type 대응표 — **팀 확정 전 초안** |

## 5. 테스트

`test_*.py`는 전부 대응하는 파일 하나씩 검증하는 pytest 파일입니다 (`test_vessel_spec_client.py` → `vessel_spec_client.py` 검증, 이런 식). 파일명만 보면 뭘 테스트하는지 바로 알 수 있게 1:1로 지었습니다.

## 6. 문서 (.md)

| 파일 | 용도 |
|---|---|
| `BlueScore_팀공유_현황.md` | 팀 전체 공유용 — 지속 업데이트되는 메인 현황판 |
| `BlueScore_데이터파이프라인_현황.md` | 위 내용을 그림(다이어그램)으로 요약한 버전 |
| `BlueScore_발표대비_데이터실측치.md` | 발표 Q&A 문서에 채워 넣을 실제 데이터 숫자 |
| `BlueScore_파일_안내.md` | 이 문서 |
| `TODO.md` | 제 작업 체크리스트 |
| `rules_common.md` | 데이터 수집 공통 규칙(재시도 정책 등) |
| `tac_needs_human_review_45.md` | TAC 매칭 중 사람이 최종 확인해야 하는 45척 목록 |
| `BlueScore_TAC매칭_임계값_실측분석.md` | 이름 유사도 임계값을 튜닝해도 TAC 매칭 정밀도가 왜 안 오르는지 실측 분석 |
| `personal_notes.md` | 제 개인 작업 메모 |

## 7. 폴더

- **`data/raw/`** — 실제로 수집·가공된 원본/중간/최종 데이터 파일들(.jsonl.gz, .csv, .xlsx 등)이 여기 다 들어있습니다. 위 스크립트들의 입출력 경로가 전부 여기입니다.
- **`data/mock/`** — 프론트/화면 작업용 샘플 데이터(`app.py`, `ui/`가 씀). 실제 수집 데이터 기반으로 만들었지만 개발·테스트용입니다.

## 처음 보는 사람이 헷갈리기 쉬운 것

- **`match_vessel_spec.py`** (국내 선박제원 매칭) vs **`match_tac_vessels.py`** (TAC 매칭) — 이름이 비슷하지만 서로 다른 데이터 소스를 매칭하는 별개 스크립트입니다.
- **`build_enriched_vessel_population.py`** vs **`merge_tac_into_enriched.py`** — 둘 다 `gfw_vessels_enriched.jsonl.gz`를 만지지만, 앞의 것이 먼저 파일을 새로 만들고(선박제원 매칭 반영), 뒤의 것이 거기에 TAC 결과를 추가로 병합합니다. **순서: build → merge**
- **`collect_*.py`(수집) vs 판단이 들어간 스크립트(가공)** — 이름에 `collect_`가 붙은 건 전부 "받아서 저장만" 하고 판단을 안 합니다. `rules_common.md` 1번 규칙 때문에 의도적으로 나눠놨습니다.
- **`gfw_vessels_enriched.jsonl.gz`(필터링됨) vs `gfw_matching_overview__*.csv`(필터링 안 됨)** — 전자는 신뢰도 통과한 매칭만 담은 "최종 사용본"(score팀이 씀), 후자는 등급 상관없이 전부 담은 "진단용"입니다. 목적이 다릅니다.
