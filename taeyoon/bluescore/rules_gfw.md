# GFW 데이터 수집 — 소스 전용 규칙

이 문서는 GFW(Global Fishing Watch) API에만 해당하는 규칙이다.
재시도, 저장, 인증, 반기 계산, 검증 같은 공통 규칙은
**`rules_common.md`를 먼저 읽고 그대로 따른다.** 이 문서는 그 위에
GFW 고유의 것만 얹는다.

---

## 1. 수집 대상 범위

**한다:**
- Vessels Search API — 한국 국적(`flag='KOR'`) **어업 선박**(`combinedSourcesInfo.shiptypes.name='FISHING'`) 목록 전체 (2026-08-13 범위 확정, 근거는 2-1번 참고)
- Events API — 위 목록의 distinct vesselId 전체(32,105개), 이벤트 타입
  5종(FISHING, GAP, PORT_VISIT, ENCOUNTER, LOITERING)을 한 호출에 동시 요청
- Vessels 상세 API — **이벤트가 1건 이상 있었던 vesselId 우선**
  (9,723개, 2026-08-13 우선순위 확정, 근거는 2-2번 참고). 순서도
  Search → Events → 상세조회로 바뀜(원래 상세조회가 2단계였으나 Events
  결과로 상세조회 대상을 좁히기 위해 순서를 바꿈).

**하지 않는다 (다음 단계로 미룬다):**
- 4Wings(격자 단위 조업효과) API
- Regions API로 EEZ id 조회 — 아래 2번 이유로 이번 단계에서 불필요

---

## 2. 선박 목록 확보 방법

**왜 EEZ(위치) 기준이 아니라 국적(flag) 기준인가**

| 방법 | 걸리는 조건 | 문제 |
|---|---|---|
| 한국 EEZ 위치로 필터 | 위치 | 중국·일본 배도 한국 해역에서 조업하면 같이 잡힘 |
| 4Wings로 조업 이벤트 있는 배만 | 국적 + 이벤트 발생 | 등록만 돼 있고 최근 조업 이벤트가 없는 배는 누락 |
| **Vessels Search, `flag='KOR'`** | **국적 자체** | 등록부 자체를 직접 조회 — 조업 여부·위치 무관하게 전체 모집단 확보 |

Vessels Search를 1순위로 쓴다. 이게 "한국 국적으로 등록된 전체 어선"
이라는 분모를 만들고, 이후 Events 조회에서 실제로 데이터가 잡히는
배가 분자가 된다. 이 분모/분자 비율 자체가 나중에 유용한 지표가 된다
— 등록은 됐는데 AIS 데이터가 안 잡히는 배가 얼마나 되는지 알 수 있다.

---

## 2-1. 어업 선박(FISHING)으로 범위 좁히기 (2026-08-13 결정)

**배경:** `flag='KOR'` 단독 조건으로 조회하면 89,897척이 나오는데,
BlueScore는 어업 선박만 필요하다. 이 프로젝트는 어업 선박이 아닌
선종(화물선, 여객선, 벙커선 등)까지 raw로 받을 이유가 없으므로,
"무엇을 수집 대상으로 삼을지"를 정하는 범위 결정으로서 국적 조건에
어업 선박 조건을 추가한다. (raw 원칙 위반 아님 — 대상 범위 설정과
받은 데이터를 가공하는 것은 다른 문제. `rules_common.md` 1번 참고.)

**시도 1: datasets 파라미터로 fishing-vessels만 지정 — 안 됨.**
`public-global-fishing-vessels:latest` 등 3종 데이터셋명은 이미
7번 표에서 404로 확인됨. v3 Vessels Search의 `datasets`는
`public-global-vessel-identity:latest` 하나만 유효하다. 즉 데이터셋
단위로 어업 선박만 서버가 걸러주는 방법은 없다.

**시도 2: where 절에 선종 조건 추가 — 됨.** `where`에 존재하지
않는 필드를 넣으면(예: `shiptypes`) 422 에러가 나는데, 그 에러
메시지가 **허용된 필드 전체 목록**을 그대로 알려준다:

```
id, registryLastUpdateDate, shipname, nShipname, ssvid, callsign, imo,
flag, geartypes, transmissionDateFrom, transmissionDateTo,
combinedSourcesInfo.shiptypes.name, combinedSourcesInfo.geartypes.name,
selfReportedInfo.id, selfReportedInfo.shipname, selfReportedInfo.nShipname,
selfReportedInfo.ssvid, selfReportedInfo.callsign, selfReportedInfo.imo,
selfReportedInfo.flag, selfReportedInfo.transmissionDateFrom,
selfReportedInfo.transmissionDateTo, registryInfo.shipname,
registryInfo.nShipname, registryInfo.ssvid, registryInfo.callsign,
registryInfo.imo, registryInfo.flag, registryInfo.geartypes,
registryInfo.recordId, registryInfo.transmissionDateFrom,
registryInfo.transmissionDateTo, registryOwners.name,
registryTmtExtraFields.masterEntityId
```

이 중 선종 분류에 쓸 수 있는 필드는 두 개이고, **의미가 다르다**:

| 필드 | 의미 | `='FISHING'`으로 걸었을 때 (flag='KOR' 기준) |
|---|---|---|
| `combinedSourcesInfo.shiptypes.name` | 등록부+AIS 결합 추정 **선종 분류**(FISHING/CARGO/PASSENGER/CARRIER/BUNKER/OTHER/NA 등) | **total 31,605건** — 이전에 수집된 raw 표본(36,600건) 클라이언트 집계로 나온 비율(34.5%)과 거의 정확히 일치 (89,897 × 34.5% ≈ 31,014) → 신뢰도 높음 |
| `geartypes` (바로 이 이름, registryInfo.geartypes와 combinedSourcesInfo.geartypes.name에 OR로 확장됨) | 조업 **방식/장비** 분류(TRAWLERS, TUNA_PURSE_SEINES 등)이며 일부만 값이 "FISHING"으로 뭉뚱그려 들어있음 — 선종 판별용이 아님 | total 9,931건 — `shiptypes` 결과와 다른 개념이라 채택 안 함 |

**채택한 조건:** `where=flag='KOR' AND combinedSourcesInfo.shiptypes.name='FISHING'`
(서버가 `(selfReportedInfo.flag='KOR' OR registryInfo.flag='KOR') AND
combinedSourcesInfo.shiptypes.name='FISHING'`로 정규화해서 처리함을
응답 metadata.query로 확인). **total = 31,605건** (2026-08-13 기준).

**기존에 진행 중이던 `flag='KOR'` 단독 수집(89,897척 대상)은
48,800건(976페이지)까지 받은 상태에서 의도적으로 중단.** 이미 저장된
raw 파일은 삭제·수정하지 않고 `raw_data/gfw/vessels_search/flag_KOR__2026-08-13T07-23-02.173Z/`에
그대로 보존(그 폴더의 `_progress.json`에 중단 사유 기록). 이후 수집은
`flag_KOR_shiptype_FISHING__*` 폴더에서 새 스냅샷으로 진행한다.

---

## 2-2. 상세조회 우선순위: 이벤트 있는 배 먼저 (2026-08-13 결정)

**배경:** Events 수집(3단계) 결과, 어업 선박 distinct vesselId
32,105개 중 2026-01-01~08-13 기간에 이벤트가 1건이라도 있는 배는
9,723개(30.3%)뿐이었다. 나머지 22,382개(69.7%)는 등록은 돼 있지만
이 기간 동안 FISHING/GAP/PORT_VISIT/ENCOUNTER/LOITERING 어느 것도
잡히지 않았다.

**결정:** 상세조회(2단계, 순서상으로는 Events 다음)를 32,105개
전체가 아니라 이벤트가 있었던 **9,723개부터 먼저** 진행한다.

**이건 값 기반 필터링이 아니라 구조적 우선순위 결정이다.** 톤수,
근해/연안 여부 같은 속성으로 일부를 골라내는 것과는 다르다 —
이벤트가 0건인 배는 애초에 이벤트 기반으로 계산하는 후속 지표(A/B축
등) 자체가 성립하지 않으므로, 상세조회 리소스를 우선순위가 높은
쪽(이벤트가 있어서 실제로 지표 계산에 쓰일 배)에 먼저 투입하는
것뿐이다. `rules_common.md` 1번의 "필터링 금지" 원칙과 충돌하지
않는다 — 대상에서 빼는(exclude) 게 아니라 순서를 뒤로 미루는
(defer) 것이다.

**22,382개(이벤트 0건)는 영구 제외가 아니라 보류다.** 이 vesselId
들은 1단계(Vessels Search) raw 데이터에 그대로 남아있으므로, 언제든
필요하면 이어서 상세조회할 수 있다. 이미 32,105개 전체를 대상으로
시작했던 상세조회 실행(`vessel_detail__2026-08-13T08-16-00.192Z`,
1,357건 부분완료)도 삭제하지 않고 그대로 보존했다 — 나중에 22,382개
쪽을 마저 진행할 때 이미 받은 건 건너뛰고 재사용된다.

**대상 목록 출처:** `raw_data/gfw/events/events__2026-08-13T08-22-34.917Z/vessels_with_events.json`
(3단계 수집 스크립트가 완료 시 자동 저장한, 이벤트가 있는 vesselId
9,723개 목록). 새 상세조회 실행은 이 파일을 그대로 읽어서 대상을
정한다 — 재계산하지 않음으로써 "이벤트 있음"의 정의가 3단계와 항상
일치하게 한다.

---

## 3. GFW 고유 지연 시간 (공통 규칙 5번 "반기 계산"에 적용할 값)

- Vessels registry: 최대 2개월 지연
- Events: 최대 72시간 지연

이 지연이 있기 때문에 스냅샷 원칙(공통 규칙 2번)이 특히 중요하다.
"이 시점에 실제로 어떤 값이었는지"를 나중에 재현하려면, registry가
갱신되기 전 값도 남아있어야 한다.

---

## 4. Events 호출 시 효율 규칙

**이벤트 타입을 하나씩 나눠 호출하지 않는다.** GFW Events API는 한
번의 호출에 여러 이벤트 타입을 동시에 요청할 수 있다.

```
잘못된 방법 (호출 5배):
  선박 1척당 FISHING 호출 1번 + GAP 호출 1번 + ... = 5번 호출

옳은 방법 (호출 1번):
  선박 1척당 5개 이벤트 타입을 한 호출에 동시 요청
  → 1번의 호출로 5종 이벤트를 동시에 받음
```

이유: "raw는 다 받는다"는 원칙과 "불필요하게 호출 횟수를 늘리지
않는다"는 효율성이 이 방식으로 동시에 만족된다.

**페이지네이션은 자동으로 끝까지 순회한다.** 응답의 전체 건수와
현재 받은 건수를 비교해서, 아직 안 받은 데이터가 남아있으면 다음
페이지를 계속 요청한다. 첫 페이지만 받고 멈추지 않는다.

---

## 5. GFW 고유 API 제약

**4Wings API는 유저당 활성 리포트 1개만 허용**, 동시 요청 시 429.
리포트 생성 100초 초과 시 524 타임아웃. (이번 단계는 4Wings를
다루지 않으므로 참고만, 이후 확장 시 적용.)

---

## 6. GFW 전용 검증 게이트 (공통 규칙 7번에 추가)

공통 하드 게이트 4개(원본 보존, 무설명 누락 금지, 스냅샷 보존, 토큰
비노출)에 더해, GFW 수집에서는 아래를 정보성으로 기록한다.

**정보성 체크 (통과/실패 판정 없음):**
- `registryOwners`(선박 소유자명 등 개인정보 가능) 포함 여부와 건수
  — 공통 규칙 1번의 "개인정보 배제보다 원본 보존 우선" 원칙에 따라
    이번 단계에서는 하드 게이트로 만들지 않는다.

---

## 7. 확인되지 않은 사항 (실행 전 실제 호출로 확정할 것)

아래는 공식 문서만으로는 확정되지 않았다. 코드를 짜기 전에 실제
API를 소규모로 호출해서 먼저 확정하고, 그 결과를 이 문서에 반영한다.

| 항목 | 상태 |
|---|---|
| Vessels Search에서 국적 조건(`flag='KOR'`)을 걸 때 쓸 정확한 파라미터명 | **확정: `where=flag='KOR'`** (2026-08-13 실제 호출로 검증). `query`는 SQL 조건식을 해석하지 않고 자유 텍스트 토큰 검색으로 처리됨 — `query=flag='KOR'`을 보내면 `FLAGKOR`로 정규화되어 flag가 KOR이 아닌 배(예: flag=IND, shipname="KOR")까지 섞여 나옴 (200 응답이지만 오답). `where=flag='KOR'`은 작은따옴표/큰따옴표 둘 다 200을 반환하며 결과가 동일함 — API가 내부적으로 `(selfReportedInfo.flag='KOR' OR registryInfo.flag='KOR')`로 정규화해 두 표기를 동등하게 처리함. total=89,897건. **datasets 값도 함께 확정**: 이 작업지시서에 있던 3종(`public-global-fishing-vessels:latest`, `public-global-carrier-vessels:latest`, `public-global-support-vessels:latest`)은 v3 Vessels Search에서 404(Not Found)를 반환함 — 존재하지 않는/무효한 데이터셋명. 공식 문서(api-doc.globalfishingwatch.org) 및 실호출로 확인된 올바른 값은 단일 통합 데이터셋 `datasets[0]=public-global-vessel-identity:latest` 하나뿐임. |
| GFW 계정의 실제 quota(총 호출 한도) | 공식 문서에서 수치 확인 안 됨 — 계정 대시보드에서 별도 확인 권장 |
| 한 번의 Events 호출로 5개 타입이 정말 동시에 오는지 | 문서의 실제 예시에 근거한 추정, 실제 응답으로 검증 필요 |
| Vessels Search 페이지네이션 방식과 페이지당 최대 건수 | **확정** (2026-08-13 실제 호출로 검증). `offset` 파라미터는 존재하지 않음 — 보내면 422 (`"property offset should not exist"`). 응답 바디에 포함된 `since` 값(커서 토큰)을 다음 요청의 `since` 파라미터로 그대로 넘기는 커서 기반 페이지네이션만 지원함. `limit` 최대값은 50 — 51 이상 요청 시 422 (`"limit must not be greater than 50"`). `flag='KOR'` 조건 기준 `total`은 약 89,897건이므로 완주하려면 페이지 약 1,798회(순차 호출, 이전 페이지의 `since` 없이는 다음 페이지를 못 받으므로 병렬화 불가) 필요. `since` 토큰은 서버 측 스크롤 컨텍스트로 추정되며, 장시간 중단 후 재개 시 만료돼 있을 가능성이 있음 — 재개 시도 시 이 가능성을 염두에 둘 것 (만료됐다면 처음부터 새 스냅샷으로 다시 시작). |

**이 표를 채우지 않은 채로 대량 수집을 시작하지 않는다.** 먼저 선박
소수(1~5척 수준)로 시험 호출해서 표의 각 항목을 확정한 뒤, 확정된
방식으로 전체 수집을 진행한다 (공통 규칙 8번 참고).

---

## 8. GFW 전용 체크리스트 (공통 규칙 9번에 추가)

- [ ] 톤수, 조업 여부 등을 기준으로 일부 선박을 수집 대상에서 제외
- [ ] 이벤트 타입별로 API를 따로따로 호출 (4번 규칙 위반)
- [ ] `query`/`where` 파라미터를 확인 없이 추측만으로 코드에 반영함
