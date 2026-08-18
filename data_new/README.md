# data_new — BlueScore 데이터 파이프라인 (재구축 중)

`bluescore/data/`(구)는 참고하지 않고 처음부터 다시 설계한 데이터
수집·가공 파이프라인. 왜 이렇게 설계했는지(결정 근거)는 `PROCESS_LOG.md`,
지금까지 뭐가 끝났는지는 `TODO.md`, 데이터 스키마 정의는
`SCHEMA_DRAFT.md` 참고 — 이 문서는 "이 폴더가 뭔지, 어떻게 돌리는지"만
다룬다.

## 폴더 구조

```
data_new/
├── raw/           소스별 원본 데이터(가공 없음, 스냅샷 원칙)
│   ├── gfw/       GFW API 수집 결과(events/, vessels/)
│   ├── mof/       MOF 선박제원 검색 결과(XML)
│   ├── marine_weather/  해양기상 관측 결과
│   ├── tac/       TAC 할당승인정보(사용자가 data.go.kr에서 받은 정적 파일)
│   ├── fishery_stats/   어업별어선(MR) 업종별 집계(정적 파일)
│   ├── vessel_registry/ 어선원부(정적 파일)
│   └── ports/     어항정보(정적 파일)
├── collect/       raw/를 채우는 수집 스크립트(API 호출)
├── process/       processed/를 만드는 가공·매칭 스크립트
├── processed/     정규화·매칭 결과(재실행하면 덮어써도 안전 — raw에서
│                  결정론적으로 재생성 가능)
├── SCHEMA_DRAFT.md   데이터 정의(엔티티·필드)
├── PROCESS_LOG.md    진행 기록(결정과 근거, 시간순)
└── TODO.md           체크리스트
```

고유 의존성 없음 — 루트 `requirements.txt`(pandas/openpyxl/requests/
python-dotenv 등) 하나로 충분하다.

## 현재 서비스 스냅샷 (2026-08-19 기준)

실규모 수집·가공 결과가 `sourceType=real` 서비스에 연결됐다. 현재 production
런타임은 아래 추적 파일 3개만 직접 읽는다.

- `processed/final_vessel_matches.jsonl`: GFW↔TAC 최종 매칭 5,323척
- `processed/gfw_vessels_normalized.jsonl`: GFW 선박명·어업종
- `processed/events_with_weather.jsonl.gz`: 기상 결합 이벤트 275,782건

최종 매칭은 TAC 한글 직접비교 + TAC 유일성 강제 + 원양선 제외 방식이며
verified **712척(13.4%)**, unmatched 4,611척이다(2026-08-18,
PROCESS_LOG.md 53·54번 — TAC 중복배정·원양선 오매칭 스팟체크로 발견돼
1,234척에서 두 차례 더 줄었다). success/partial/insufficientSample/
matchingFailed별 서비스 상태는 이 매칭 수정 이전 값(55번 작성 당시
스냅샷)이라 재계산 필요. 과거 fuzzy/MOF 파이프라인의 수치와 조사
기록은 `PROCESS_LOG.md`에 당시 결과로 보존한다.

## 전체 파이프라인 실행 순서

의존성 있는 순서대로 정리 — 상세 옵션(`--start`/`--date`/`--limit` 등)은
각 스크립트 상단 docstring 참고.

```bash
pip install -r ../requirements.txt

# 1. 수집 (collect/) — .env에 GFW_API_KEY/MARINE_WEATHER_API_KEY/KAKAO_API_KEY 필요
cd collect
python gfw_events.py --start 2026-04-01 --end 2026-08-15     # 이벤트 먼저(모집단이 여기서 나옴)
python gfw_vessels.py                                         # 이벤트에서 나온 vesselId 상세조회(건당 1요청)
python marine_weather_range.py --start 20260401 --end 20260814 # 이벤트 기간 전체 재수집(날짜별 재개 지원)

# 2. 가공 (process/)
cd ../process
python normalize_gfw_events.py
python normalize_gfw_vessels.py
python normalize_tac.py

# 3. 매칭 (GFW<->TAC 한글 직접비교, matching_redesign_proposal/README.md 참고)
python match_fuzzy_name.py              # 3단계: 한글 직접비교 + 카카오 지오코딩 거리확인
python assemble_matches.py              # 4단계: 최종 판정 정리

# 4. 부가 가공
python attach_weather.py --start 20260401 --end 20260814  # 해양기상 부착(수집한 기간과 맞춰서)
```

## 서비스 소비와 선택적 파생 파일

수집·가공 단계는 로컬 `raw/`와 여러 중간 산출물을 사용하지만, 서비스는 위의
최종 스냅샷 3개만 소비한다. `tac_vessels_normalized.jsonl`과
`kakao_geocode_cache.json`은 매칭 재생성·검증용 추적 자료이며 production 점수
런타임 입력은 아니다.

다음 명령은 레거시 분석 도구와 파일 검사를 위한 선택적 exporter다. 생성 결과가
없어도 API와 `/real` 화면은 동작한다.

```bash
python -m score.scripts.convert_data_new_vessels  # vessels_for_score.jsonl.gz
python -m data_new.process.build_axis_b_input     # axis_b_input.jsonl
```

A축·B축 진단은 파생 파일을 먼저 만들지 않고 공용 production 변환을 직접 사용한다.

```bash
python -m score.scripts.run_real_axis_a
python -m score.scripts.run_real_axis_b
```

## 과거 재구축 과정에서 확인한 한계

아래 수치는 당시 fuzzy/MOF 파이프라인을 평가한 기록이며 현재 TAC 한글 직접비교
스냅샷의 운영 건수는 위 “현재 서비스 스냅샷”을 기준으로 한다. 조사에서 확인한
데이터 품질 한계와 결정 근거는 비교를 위해 보존한다.

- **매칭률 54.1%의 실제 정밀도는 사람 라벨링으로 재확인함**(49번) —
  층화 랜덤추출 80쌍을 직접 라벨링한 결과 **약 75%**(0.95+ 구간은
  92.9%, 임계값 올릴수록 정밀도도 오름). 자동검증(48번, MOF 정답신호
  기반)이 시사했던 11~22%는 MOF 경유 매칭에 편향된 표본 탓으로 결론 —
  단 **MOF 경유 매칭(tier3의 6.6%)만은 여전히 저정밀도로 별도 취급
  권장**. 숫자접두어 신호(번호일치 95~100%, 번호불일치 0%, 44·49번)로
  unmatched 134척 타겟 구제 가능.
- **정적 파일 3종(TAC/어업별어선/어선원부)은 CP949 인코딩** — UTF-8 아님
- **어선원부는 전체 등록대장이 아니라 2006년 처리배치 일부**(1,379행,
  전부 현행여부='N') — 매칭되면 보너스 정도로만 취급
- **매칭 3단계 임계값(0.8)은 잠정값** — 실규모(5,323척) 결과 tier2 0.1% /
  tier3 54.1% / unmatched 45.9%. 근접점수(0.70~0.80) 60건 육안실사 결과
  체감정밀도 25~40%라 단순 인하는 비추천, 숫자접두어 신호 추가안이
  대안(PROCESS_LOG.md 38번, 회의 안건)
- **B축 톤수 커버리지 43.4%**(전체 5,323척 기준) — 매칭 실패(45.9%) +
  매칭돼도 톤수 없는 경우가 겹쳐서 이렇게 낮음. 해양기상 부착은 100%라
  병목 아님(PROCESS_LOG.md 36·41번)
- **해역신호용 어항정보 실효성 낮음**(46번) — TAC 항구정보 있는 1,990척
  중 113개 리스트에 실제로 매칭되는 건 5.1%(102척)뿐, 매칭 로직의
  해역보너스는 전체의 9.9%에서만 실제 작동. 리스트 확장보다 TAC
  `portNamesTac`의 항구명/행정구역명 혼재부터 정리가 선행돼야 함
- **GFW `registryInfo`는 우리 실제 모집단(근해/연안)엔 거의 없음**(5,323척
  전수 기준 0.4%, 21척) — 매칭은 대부분 3단계(fuzzy)에 의존
- **MOF 검색 구조적으로 소형 어선에 안 맞음**(45번) — 쿼리 4,662건 중
  89.9%가 응답 자체가 0건. GFW 로마자명으로 검색하는데 MOF는 사실상
  `vsslEngNm`(영문명) 매칭이라, 영문명이 잘 없는 국내 소형 연근해
  어선은 구조적으로 거의 못 찾고 영문명이 있는 상선급만 걸림(39번
  상선 오염과 같은 원인). 실질 기여율 약 4.2%. 톤수 보강 수단으로는
  TAC·어선원부보다 훨씬 실효성 낮음.
- **`totalDistanceKm` 이상치는 해소됨**(42번) — max 772.99km은 실제
  4.5일짜리 장기 조업이벤트로 물리적 일관성 확인, 이상치 아님
