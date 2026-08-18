# 담당: 김태윤 (초안 — 대화로 확정 중)

# BlueScore 데이터 정의 초안 (v0)

> 근거: score/·chain/·explain/·ui/ 코드가 실제로 읽는 필드 + 기획서(2026-08-11) 8-3.
> data/(구) 폴더의 실측 수치·판단은 참고하지 않음 — 소스·조인키·모집단은 전부 재검토 대상.

## 1. 엔티티 4개 (잠정)

### Vessel (선박 마스터)
| 필드 | 용도 | 소스 후보(미확정) |
|---|---|---|
| vesselId | 전 엔티티 조인키 | GFW? |
| name | ui 화면 표시(어업인 "내 배") | 선박제원? |
| tonnageGt | B축 물리식 필수, peer_grouping 톤수대 | 해양수산부 선박제원정보 |
| enginePowerPs_or_Hp | B축 물리식 대안 입력 후보, 단위 미확정(PS/HP) | 어업별어선(업종평균) / TAC(업종보정) — 개별값은 공개데이터에 없음(기획서 8-3 명시) |
| gearType | peer_grouping, LightGBM 범주형 feature | GFW 자기신고 vs 국내 업종명 — 대응표 필요 |
| lengthM, widthM | 현재 score 코드 미사용, 확보되면 보류 | 선박제원 |

### FishingEvent (조업이벤트)

**중요**: score/ 계약 필드(vesselId, latitude, longitude, averageSpeedKnots,
durationHours 등 flat 구조)와 GFW 원본 응답 구조가 다르다 — GFW 공식 파이썬
클라이언트 소스코드(`gfw-api-python-client`, response 모델)로 확인함
(2026-08-17). 원본은 이벤트 타입별로 하위 객체가 다르고 중첩돼 있다:

| score/ 계약 필드(flat) | GFW 원본 실제 위치(중첩) |
|---|---|
| eventId | `id` |
| vesselId | `vessel.id` |
| type | `type` (값 6종: ENCOUNTER/FISHING/GAP/GAP_START/LOITERING/PORT/PORT_VISIT — 5종 아님, 재확인됨) |
| start | `start` (동일, flat) |
| latitude, longitude | `position.lat`, `position.lon` |
| averageSpeedKnots, totalDistanceKm, durationHours | 이벤트 타입별 하위 객체에 각각 존재 — FISHING은 `fishing.averageSpeedKnots`/`fishing.totalDistanceKm`/`fishing.averageDurationHours`, GAP은 `gap.durationHours`, PORT_VISIT은 `port_visit.durationHrs`(철자 다름). **모든 타입 공통의 단일 durationHours 필드는 원본에 없음** |
| regions.mpa | `regions.mpa`(리스트) — 동일 경로, `regions`에 eez/rfmo/fao/highSeas 등도 같이 있음(새로 발견) |

**설계 결정**: raw 저장은 이 중첩 구조 그대로 한다(원칙1). score/가 기대하는
flat 계약 형태로 바꾸는 **정규화 단계를 가공(processing) 단계에 새로 만든다**
— 옛날 `data/gfw_client.py`가 이 역할을 했던 것으로 추정되나 확인 안 함,
이번엔 실제 원본 구조 기준으로 다시 짠다.

### WeatherObservation (해황, 이벤트에 매칭)
| 필드 | 용도 |
|---|---|
| seaSurfaceTempC, windSpeedMs, currentSpeedMs | LightGBM 통제변수 |
| (파고 필드 존재 여부 미확인) | 풍속보다 연료·안전에 더 직접적일 수 있음 — 확인 대상 |

### CongestionBaseline (연안AIS 통계, 원 기획 상 A축 혼잡압력의 원래 기준값)
| 필드 | 용도 |
|---|---|
| region, timeBucket, vesselCount | 혼잡가중압력 — 현재 GFW 이벤트 밀도로 대체 중, 원래 설계와 다를 수 있음 |

## 1-1. 모집단 정의 (실측으로 확정, 2026-08-17)

`flag='KOR'` 단독 필터는 원양 대형선단(동원·오룡 등)까지 다 섞여 들어옴 —
실측으로 확인(예: `MEDRA`는 flag=KOR인데 실제 조업 위치가 서아프리카 해역).
**"근해" 모집단은 국적이 아니라 실제 조업 위치로 정의한다**: `flag='KOR'` AND
GFW Events `region: {dataset:"public-eez-areas", id:"8327"}`(한국 EEZ) 내
조업이벤트 1건 이상. 상세 검증 근거는 `PROCESS_LOG.md` 5번 참고.

## 2. 미확정 사항 (이번 단계에서 정할 것)

- vesselId를 어느 소스 기준으로 통일할지 (조인키 설계 — 순서 5번 단계)
- gearType 국내↔GFW 대응 — 이번엔 처음부터 다대일 구조로 설계
- enginePowerPs_or_Hp 단위(PS/HP) — 외부 확인 필요
- TAC를 개별매칭 할지 업종단위로만 쓸지 (기획서는 업종단위로 명시)
- 연안AIS 키 확보 가능 여부 — 가능하면 CongestionBaseline 살리고, 안되면 GFW 밀도 대체를 "의도적 우회"로 명시

## 3. 스코프 제외

- 법령/제도 정보(금어기, 직불제 요건 등) — explain 담당 영역, 데이터팀 아님
