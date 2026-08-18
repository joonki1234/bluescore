# data_new — BlueScore 어선 데이터 파이프라인

데이터 파이프라인 전체 — 구조·설계 근거·최종 수치·한계 — 를 이 문서
하나로 설명한다.

## 한 줄 요약

GFW(Global Fishing Watch) 조업 이벤트를 한국 EEZ 내 어선으로 모집단을
잡고, 정부 등록정보(TAC)와 한글 이름으로 직접 대조해 개별 선박을
식별한 뒤, 조업 이벤트에 해양기상을 붙여 A축(자원압력)·B축(운항효율)
점수 계산에 넘긴다. **verified 712척(13.4%)** — 커버리지보다 정밀도를
우선한 결과다.

## 폴더 구조

```
data_new/
├── raw/           소스별 원본 데이터(가공 없음, 스냅샷, git 비추적)
├── reference/      사람이 만든 참고자료(한글명 후보 CSV, git 추적)
├── collect/        raw/를 채우는 수집 스크립트(API 호출)
├── process/        processed/를 만드는 가공·매칭 스크립트
└── processed/      정규화·매칭 결과(raw에서 재생성 가능, 최종 3개만 git 추적)
```

고유 의존성 없음 — 루트 `requirements.txt`(pandas/openpyxl/requests/
python-dotenv 등) 하나로 충분하다.

## 모집단 정의

`flag='KOR'` 단독 필터는 원양 대형선단까지 섞여 들어온다(실측 확인 —
flag=KOR인데 실제 조업 위치가 서아프리카 해역인 배 존재). **국적이
아니라 실제 조업 위치로 정의**: `flag='KOR'` AND 한국 EEZ(GFW
`region: public-eez-areas #8327`) 내 FISHING 이벤트 1건 이상.
5,323척.

## 파이프라인 실행 순서

```bash
# 1. 수집 (collect/) — .env에 GFW_API_KEY/MARINE_WEATHER_API_KEY/KAKAO_API_KEY 필요
cd collect
python gfw_events.py --start 2026-04-01 --end 2026-08-15
python gfw_vessels.py
python marine_weather_range.py --start 20260401 --end 20260814
# TAC 할당승인정보는 API가 공공기관 전용이라 raw/tac/에 정적 파일로 배치

# 2. 가공 (process/)
cd ../process
python normalize_gfw_events.py
python normalize_gfw_vessels.py
python normalize_tac.py

# 3. 매칭
python match_fuzzy_name.py       # GFW<->TAC 한글 직접비교(5단계, 아래 참고)
python assemble_matches.py       # 최종 판정 정리

# 4. 부가 가공
python attach_weather.py --start 20260401 --end 20260814
```

서비스(`sourceType=real`)는 이 중 최종 산출물 3개만 직접 읽는다:
`processed/final_vessel_matches.jsonl`(매칭), `processed/
gfw_vessels_normalized.jsonl`(선박명·어업종), `processed/
events_with_weather.jsonl.gz`(기상결합 이벤트 275,782건). A축·B축은
`score/real_axis_a_pressure.py`·`score/real_axis_b_input.py`가 이
3개를 공용으로 변환해서 쓴다 — 스키마가 안정 계약이라 매칭 로직이
바뀌어도 score/ 쪽 코드는 안 건드려도 된다(`tac`/`mof` 객체 존재
여부만 읽지 `matchTier` 값은 안 봄, 실측 확인함).

## 매칭 설계 — GFW↔TAC 한글 직접비교 (5단계)

GFW 자기신고 영문명을 로마자로 바꿔 TAC 한글명과 유사도 비교하는
방식은 안 쓴다 — 서로 다른 실제 이름인데 로마자로 바꾸면 끝부분이
겹쳐서 점수가 높게 나오는 구조적 오탐이 있다(예: EUNSEONGHO(은성호)가
금성호로 오매칭). 대신 GFW 영문명 4,662척 전체를 한글로 미리 변환해둔
후보(`reference/gfw_korean_name_candidates.csv`)와 한글 원문끼리
직접 비교한다. 이 CSV는 규칙기반 반자동 프로세스로 만들었다 —
letterPart만 변환, 숫자·"호" 접미사 제외, 애매하면 후보 최대 3개를
`|`로 구분, 해수부 선박마스터 자료로 보강하되 음역결과와 일치할
때만 채택, 확신 없으면 보수적으로 빈칸. 오탐 하나가 B축 점수를 그
배 단위로 완전히 틀어지게 만들 수 있어, 이 파이프라인 전체가
커버리지보다 정밀도를 우선한다.

**5단계 규칙** (`process/match_fuzzy_name.py`):

1. **한글 직접비교(exact match만)** — 로마자 유사도 fuzzy는 안 쓴다.
2. **숫자 하드필터** — 이름에 박힌 숫자가 GFW·후보 양쪽에 다 있는데
   값이 다르면 무조건 배제(자릿수 무관).
3. **"제N호" 정규화** — TAC 원문은 "제707태근호"처럼 선단번호를
   이름에 그대로 갖고 있는데 GFW 쪽 한글변환은 숫자를 분리해서
   뺐으므로, 비교 시 이 접두어를 후보 쪽에서도 한 번 더 뗀다.
4. **카카오 지오코딩 거리 확인** — 후보가 몇 개든 조업위치(이벤트
   평균)와 TAC 등록항 사이 거리를 반드시 확인해야 하고, ≤150km인
   경우만 verified. 거리를 확인 못 하면(지오코딩 실패) 후보가
   이름만으로 유일해도 확정하지 않는다 — "모른다"를 "가깝다"로
   오판하지 않기 위함.
5. **TAC 쪽 유일성 강제** — 1~4단계는 GFW 선박마다 독립 판정이라,
   숫자 없는 흔한 이름(예: "한성호")은 서로 다른 GFW 선박 여러 척이
   TAC의 같은 배 하나를 동시에 주장할 수 있다(실측: 이 단계 없이는
   verified의 63.8%가 이 충돌에 걸림 — TAC "한성호" 1척이 GFW 9척에
   매칭되는 식). 4단계까지 마친 뒤 TAC 등록번호별로 재집계해서, 같은
   TAC 배를 여러 GFW 선박이 주장하면 조업위치 최근접 하나만 verified로
   남기고 나머지는 held_multi로 되돌린다.

**후보풀에서 제외한 것**: 어선원부(2006년 처리배치 일부, 전부
비현행이라 신뢰도 낮음, 기여분 0.1%뿐), MOF(이름검색이 어선보다
상선 위주로 편향), GFW `registryInfo`가 있는 선박(21척 — 대부분 IMO
번호·수백GT급 원양 대형선단이라 근해/연안 모집단과 성격이 다름).

## 최종 수치

| 구분 | 척수 | 비중 | 비고 |
|---|---:|---:|---|
| **verified — 사용 권장** | **712** | **13.4%** | 이름·숫자 일치 + 위치 확인(≤150km) + TAC 유일성, 예외 없음 |
| held_multi — 계산 불가 | 1,769 | 33.2% | 동명이선, TAC 중복배정 패배분, 거리 미확인 |
| no_korean — 계산 불가 | 777 | 14.6% | GFW 한글 후보 자체가 없음(범용 영문명 등) |
| unmatched | 2,065 | 38.8% | TAC에 같은 이름 없음, GFW 이름 없음, 원양선 추정 |

단계별 verified 척수: 한글 직접비교 1,262 → 어선원부 제외 1,234 →
TAC 유일성 강제 713 → 원양선 제외 **712(최종)**. 참고로 로마자 유사도
방식은 matched 2,881척이었다.

held_multi·unmatched·no_korean은 `ui/adapter.py`의 `matchingFailed`
게이팅으로 unmatched와 동일하게 블록 처리한다 — 근거 없이 억지로
안 붙인다.

## 알려진 한계

- **정밀도 실측 0건**: 구 로마자 시스템은 사람 라벨링 80쌍으로 실측
  75%를 확인했지만, 새 시스템(712척)은 구조적으로 오탐 경로를
  없앴다는 설계 근거뿐 전수 실측 검증은 아직 안 했다. 다음 우선순위.
- **커버리지 13.4%는 의도적 트레이드오프**: 정밀도 우선 원칙의 결과다.
  no_korean(14.6%)은 방법론 문제가 아니라 한글명 후보 CSV가 83%
  (3,878/4,662척)만 채워진 데이터 문제 — 채우면 커버리지가 오를 여지가
  있다.
- **150km 임계값은 법·데이터 근거가 없다**: 수산업법에 "항구 기준
  반경" 개념 자체가 없고, 민감도 분석(50km→538척, 300km→1,723척)도
  자연스러운 경계를 보여주지 않는다. 정밀도 우선 원칙 아래 보수적으로
  잡은 정책값이며, `LOC_VERIFIED_KM` 상수 하나로 재조정 가능하게
  설계했다.
- **TAC 유일성 강제의 "최근접" 판정은 확률적 근거지 증명이 아니다**:
  해결된 267개 충돌 중 승자-2위 거리 마진이 10km 이내인 경우가
  31.1%(1km 이내도 6.0%) — 지오코딩·이벤트 중심점 오차 범위 안일 수
  있다. 완전한 해결이 아니라 명백한 중복배정 오류를 없앤 것.
- **GFW `selfReportedInfo`(자기신고명)는 원래 신뢰도가 낮다** —
  실측으로 확인된 사례(전혀 다른 배로 반환되는 콜사인/IMO)가 있다.
  한글 직접비교도 이 위에서 동작하므로 원본 오류를 완전히 못 걸러낼
  수 있다.

## 참고

- 매칭 재설계 검증 전체 과정(A/B/C안 비교, 발견한 버그들): 웹 탐색기
  아티팩트(선박 매칭 탐색기) — 별도 공유 링크.
- 팀 결정 로그: 저장소 루트 `CLAUDE.md`.
- 재현: `python data_new/process/match_fuzzy_name.py && python
  data_new/process/assemble_matches.py`
