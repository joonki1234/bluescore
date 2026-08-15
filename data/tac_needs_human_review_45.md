# TAC 검토필요 45척 — 사람 확인용 근거 정리

담당: 김태윤


자동 규칙(MOF 교차검증 + 숫자상태 + 톤수)으로 걸러지지 않은 나머지 45척. 44척은 MOF 선박제원정보 자체에 해당 GFW 선박 기록이 없어(MOF 미수집/미등록 선박으로 추정) 비어선 의심 여부를 교차검증할 수 없는 경우 — 즉 데이터 부족으로 못 정한 것이지, 매칭 품질이 의심스러워서가 아님. GFW 자기신고 gear type을 참고 신호로 추가함(약한 신호, 선박이 스스로 신고한 값이라 교차검증은 아님).


| TAC명 | GFW명 | 경로 | 신뢰도 | 숫자상태 | MOF기록 | GFW자기신고 gear | 톤수(TAC) |
|---|---|---|---:|---|---|---|---:|
| 행복호 | HAENG BOK HO | MOF경유 | 1.00 | one_side_missing | 있음(92[원양 어선]) | FISHING | 21.0 |
| 금영호 | GEUM GYEONG7HO | 직접(로마자) | 0.92 | one_side_missing | 없음 | OTHER_PURSE_SEINES | 20.0 |
| 해양호 | 5HAEYANGHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | SET_LONGLINES | 22.0 |
| 사량호 | SARANGHO | 직접(로마자) | 0.94 | none | 없음 | FISHING | 3.68 |
| 서해1호 | SEOHAEHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | DREDGE_FISHING | 9.77 |
| 풍년호 | PUNG NYEON 2 | 직접(로마자) | 0.86 | one_side_missing | 없음 | DREDGE_FISHING | 9.77 |
| 천명호 | CHEONGMYEONG | 직접(로마자) | 0.88 | none | 없음 | POLE_AND_LINE | 4.55 |
| 금성호 | 2GEUMSEONG | 직접(로마자) | 0.90 | one_side_missing | 없음 | FISHING | 10.0 |
| 209대청호 | TAECHEONGHO | 직접(로마자) | 0.91 | one_side_missing | 없음 | POTS_AND_TRAPS | 15.0 |
| 영남호 | YEONG NAM HO@ | 직접(로마자) | 0.91 | none | 없음 | FISHING | 72.0 |
| 연창호 | 112YEONCHANG | 직접(로마자) | 0.90 | one_side_missing | 없음 | OTHER_PURSE_SEINES | 29.0 |
| 명천호 | 77MYEONG CHEON | 직접(로마자) | 0.88 | one_side_missing | 없음 | FISHING | 41.0 |
| 광해호 | GWANGHAE7 HO | 직접(로마자) | 0.89 | one_side_missing | 없음 | NA, FISHING | 30.0 |
| 제3강남호 | NEWGANGNAMHO | 직접(로마자) | 0.87 | one_side_missing | 없음 | FISHING | 77.0 |
| 202강남호 | KANGNAMHO | 직접(로마자) | 0.89 | one_side_missing | 없음 | FIXED_GEAR | 23.0 |
| 제27화승호 | HWASUNGHO | 직접(로마자) | 0.86 | one_side_missing | 없음 | SET_GILLNETS | 85.0 |
| 예진호 | YE JIN HO@ | 직접(로마자) | 0.88 | none | 없음 | FISHING | 24.0 |
| 순일호 | 111SUNILHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | OTHER_PURSE_SEINES | 9.77 |
| 201길은호 | KILEUNHO | 직접(로마자) | 0.88 | one_side_missing | 없음 | FISHING | 24.0 |
| 201남양호 | NAMYANGHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | FIXED_GEAR | 12.0 |
| 신창호 | SINCHANG HO | 직접(로마자) | 0.89 | none | 없음 | FISHING | 4.49 |
| 풍성호 | 88PUNGSEONG | 직접(로마자) | 0.90 | one_side_missing | 없음 | TRAWLERS | 20.0 |
| 천전호 | CHEONGJEONG16HO | 직접(로마자) | 0.92 | one_side_missing | 없음 | POLE_AND_LINE | 4.23 |
| 동해호 | 306DONGHAHO | 직접(로마자) | 0.94 | one_side_missing | 없음 | FIXED_GEAR | 29.0 |
| 흥영호 | HEUNGYEONG | 직접(로마자) | 0.91 | none | 없음 | SET_GILLNETS, NA | 48.0 |
| 신화호 | 77SINHWA | 직접(로마자) | 0.86 | one_side_missing | 없음 | FISHING | 9.77 |
| 216상진호 | SANGJINHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | SET_GILLNETS | 69.0 |
| 75동명호 | DONGMYEONGHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | FIXED_GEAR | 135.0 |
| 갈릴리호 | GALRILRI | 직접(로마자) | 0.89 | none | 없음 | SET_GILLNETS, NA | 21.0 |
| 평은17호 | PYEONGEUNHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | FISHING | 42.0 |
| 현주호 | YEOJUHO | 직접(로마자) | 0.88 | none | 없음 | FISHING | 9.77 |
| 제5007동민호 | JEONGMINHO | 직접(로마자) | 0.95 | one_side_missing | 없음 | SET_GILLNETS | 79.0 |
| 용천호 | 2008YONGCHEON | 직접(로마자) | 0.90 | one_side_missing | 없음 | FISHING | 24.0 |
| 흥미호 | HEUNG MIN HO@ | 직접(로마자) | 0.86 | none | 없음 | FISHING | 5.47 |
| 바다소리호 | BADASORI | 직접(로마자) | 0.89 | none | 없음 | FISHING | 29.0 |
| 남영호 | NAMYOUNG1HO | 직접(로마자) | 0.90 | one_side_missing | 없음 | FISHING | 54.0 |
| 1만복호 | MAN BOK HO@ | 직접(로마자) | 0.89 | one_side_missing | 없음 | TRAWLERS | 22.0 |
| 청마호 | CHEONG MA HO@ | 직접(로마자) | 0.91 | none | 없음 | POLE_AND_LINE | 3.0 |
| 태진호 | 211TAEJINHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | FISHING | 29.0 |
| 수경1호 | SUGYEONGHO | 직접(로마자) | 1.00 | one_side_missing | 없음 | FIXED_GEAR | 8.55 |
| 우강호 | YUGANGHO | 직접(로마자) | 0.93 | none | 없음 | POLE_AND_LINE | 9.77 |
| 영종호 | YEONGOONGHO | 직접(로마자) | 0.91 | none | 없음 | SET_GILLNETS | 3.3 |
| 강동호 | GANGDONG | 직접(로마자) | 0.89 | none | 없음 | SET_GILLNETS | 69.0 |
| 진수호 | JINSUNG1HO | 직접(로마자) | 0.88 | one_side_missing | 없음 | DREDGE_FISHING | 6.67 |
| 충남호 | 808CHUNGNAM | 직접(로마자) | 0.89 | one_side_missing | 없음 | FISHING | 9.77 |

## 판단 가이드
- **MOF기록 '있음'인데 검토필요로 남은 건 1척뿐**(행복호/HAENG BOK HO) — 톤수도 10.5%로 근접, gear도 FISHING, populationStatus도 confirmed_fishing이라 **사실상 accept로 봐도 무방**해 보임(숫자상태만 one_side_missing이라 자동 규칙에서 안 걸렸을 뿐).
- **나머지 44척은 MOF 기록 자체가 없어** 비어선 의심 여부를 교차검증할 방법이 없음. GFW 자기신고 gear type이 SET_LONGLINES/OTHER_PURSE_SEINES처럼 구체적인 어업 장비면 상대적으로 신뢰도가 높고, populationStatus가 'unknown'인 건 GFW 쪽에서도 아직 어선 여부를 확정 못한 것.
- 실무적으로는: 톤수가 서로 비슷하고(TAC 값 자체가 소형 어선 범위, 대부분 3~135톤) gear type이 구체적인 어업 종류로 찍히는 건 채택 리스크가 낮고, 반대로 gear가 없거나 이름 유사도가 낮은 쪽(0.85 근처)이 상대적으로 리스크 높음.
