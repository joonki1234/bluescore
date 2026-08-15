"""
담당: 김태윤 (초안 — 팀 확정 필요, 혼자 결정하지 않음)

국내 어업종(TAC 할당승인정보의 "할당 어업 종류 명", 19개 유형) ↔ GFW
gear type 대응표 초안. score/axis_b_baseline.py의 CATEGORICAL_FEATURE_COLUMNS
"gearType" 피처에 쓸 통합 카테고리를 만들기 위함.

**이 파일은 확정본이 아니다.** 자동으로 만들 수 없는 도메인 판단이라
(오동규 2026-08-14 메모 — 김태윤 혼자 결정하지 말고 팀 회의에서 확정할
것 권장), 아래 매핑은 국내 어업법상 명칭의 문자적 의미로 추정한 초안일
뿐이다. confidence가 "approximate"/"unmappable"인 항목은 특히 실제
수산업 도메인 지식이 있는 사람의 확인이 필요하다.

국내 어업종 출처: data/raw/해양수산부_수산정보_TAC 할당 승인 정보_20251105.csv,
    "할당 어업 종류 명" 컬럼의 고유값 19개 (2026-08-14 기준 실제 수집 데이터).
GFW gear type 출처: data/raw/gfw_vessels_kor_fishing__2026-08-13.jsonl.gz의
    fishingType 필드 실제 관측값(추측 아님) — FISHING/NA/GEAR/OTHER/
    INCONCLUSIVE 같은 범용·결측 라벨과, CARGO/PASSENGER/CARRIER 같은
    비어업 라벨(TODO.md의 "GFW FISHING 오분류" 발견과 일관됨)은 매핑
    대상에서 제외했다 — 실제 조업방식을 나타내는 라벨만 후보로 뒀다.

confidence 값:
    "direct"      — 국내 어업종명과 GFW 라벨이 같은 조업방식을 가리킴이 명확
    "approximate" — 방향은 맞지만 GFW 쪽 분류가 더 뭉뚱그려져 있거나
                    (예: "저인망"/"트롤" 구분 없이 TRAWLERS 하나뿐), 후보가
                    두 개 이상이라 확정 못함
    "unmappable"  — GFW gear type taxonomy에 대응 개념 자체가 없음(예: 잠수기어업처럼
                    선박이 그물/낚시 장비를 안 쓰는 방식)
"""

GEAR_TYPE_MAPPING_DRAFT = {
    "근해안강망어업": {
        "gfwGearType": "SET_GILLNETS",
        "confidence": "approximate",
        "note": "안강망(조류에 닻으로 고정한 깔때기형 그물)은 GFW 분류에 정확히 대응하는 항목이 없음 — 고정형 그물류 중 가장 가까운 SET_GILLNETS로 잠정 배정.",
    },
    "근해연승어업": {
        "gfwGearType": "SET_LONGLINES",
        "confidence": "approximate",
        "note": "연승(주낙)은 고정식(SET_LONGLINES)/유동식(DRIFTING_LONGLINES) 둘 다 국내에서 쓰임 — 국내 통계만으로는 구분 불가, 확인 필요.",
    },
    "근해자망어업": {
        "gfwGearType": "SET_GILLNETS",
        "confidence": "direct",
        "note": "자망=gillnet, 직접 대응.",
    },
    "근해채낚기어업": {
        "gfwGearType": "SQUID_JIGGER",
        "confidence": "approximate",
        "note": "채낚기(지깅)는 오징어 대상이 흔해 SQUID_JIGGER를 우선 배정했으나, 대상 어종에 따라 POLE_AND_LINE이 맞을 수도 있음.",
    },
    "기선권현망어업": {
        "gfwGearType": "SEINERS",
        "confidence": "approximate",
        "note": "권현망(선단식 멸치 저인망)은 저인망(트롤)과 선망(seine)의 중간 성격 — SEINERS/OTHER_SEINES 중 확인 필요.",
    },
    "기타통발어업": {
        "gfwGearType": "POTS_AND_TRAPS",
        "confidence": "direct",
        "note": "통발=trap/pot, 직접 대응.",
    },
    "대형선망어업": {
        "gfwGearType": "PURSE_SEINES",
        "confidence": "direct",
        "note": "선망=purse seine, 직접 대응. (참치 선망이면 TUNA_PURSE_SEINES일 수 있음 — 국내 통계만으론 대상어종 구분 불가.)",
    },
    "대형트롤어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "direct",
        "note": "트롤=trawl, 직접 대응.",
    },
    "동해구기선저인망어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "approximate",
        "note": "저인망(끄는 그물)은 GFW에서 TRAWLERS로 뭉뚱그려짐 — 국내처럼 어법 세부 구분(외끌이/쌍끌이 등)이 GFW엔 없음.",
    },
    "동해구트롤어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "direct",
        "note": "트롤=trawl, 직접 대응.",
    },
    "소형선망어업": {
        "gfwGearType": "PURSE_SEINES",
        "confidence": "direct",
        "note": "선망=purse seine, 규모(소형)는 GFW 분류에 반영 안 됨.",
    },
    "쌍끌이대형기선저인망어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "approximate",
        "note": "쌍끌이(2척 협업) 저인망도 GFW엔 TRAWLERS 하나로 뭉뚱그려짐.",
    },
    "쌍끌이서남해구기선저인망어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "approximate",
        "note": "위와 동일 — 해역(서남해)도 GFW 분류에 반영 안 됨.",
    },
    "연안복합어업": {
        "gfwGearType": None,
        "confidence": "unmappable",
        "note": "'복합'=한 척이 여러 어법을 겸업 — 단일 GFW gear type으로 표현 불가. 대표 어법이 있으면 사람이 개별 배정하거나, gearType을 다중값/None으로 둬야 함.",
    },
    "연안자망어업": {
        "gfwGearType": "SET_GILLNETS",
        "confidence": "direct",
        "note": "자망=gillnet, 직접 대응.",
    },
    "연안통발어업": {
        "gfwGearType": "POTS_AND_TRAPS",
        "confidence": "direct",
        "note": "통발=trap/pot, 직접 대응.",
    },
    "외끌이대형기선저인망어업": {
        "gfwGearType": "TRAWLERS",
        "confidence": "approximate",
        "note": "외끌이(1척) 저인망도 GFW엔 TRAWLERS 하나로 뭉뚱그려짐.",
    },
    "잠수기어업": {
        "gfwGearType": None,
        "confidence": "unmappable",
        "note": "잠수기(잠수부가 직접 채취)는 그물/낚시 장비를 안 씀 — GFW gear type taxonomy 자체가 이런 방식을 다루지 않음.",
    },
    "패류형망어업": {
        "gfwGearType": "DREDGE_FISHING",
        "confidence": "direct",
        "note": "형망=dredge, 직접 대응.",
    },
}

# 참고: 실제 데이터에서 관측된 GFW gear type 중 위 매핑에 쓰이지 않은
# 나머지 — 국내 19개 어업종 어디에도 안 맞는 것들(범용/결측/비어업 라벨).
# TODO.md "GFW FISHING 오분류" 항목과 연결됨.
UNMATCHED_GFW_LABELS = [
    "FISHING",       # 범용(구체적 어법 불명)
    "NA",            # 결측
    "FIXED_GEAR",    # 범용 고정식 어구
    "GEAR",          # 범용
    "OTHER",         # 범용
    "INCONCLUSIVE",  # GFW가 판단 못함
    "OTHER_PURSE_SEINES",
    "OTHER_SEINES",
    "TROLLERS",      # 국내 19개 유형엔 트롤링(끌낚시)에 해당하는 게 안 보임
    "CARGO", "PASSENGER", "CARRIER",  # 비어업 선박 — 애초에 매칭 대상 아님
]


def get_gfw_gear_type(domestic_gear_type_name: str):
    """국내 어업종명으로 GFW gear type 후보를 조회한다.
    미확정 초안이므로 confidence를 같이 반환한다."""
    entry = GEAR_TYPE_MAPPING_DRAFT.get(domestic_gear_type_name)
    if entry is None:
        return None, "not_in_draft"
    return entry["gfwGearType"], entry["confidence"]
