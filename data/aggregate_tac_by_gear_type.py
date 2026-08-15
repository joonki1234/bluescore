"""
담당: 김태윤

TAC(총허용어획량) 할당승인정보를 개별 선박 이름매칭이 아니라 **업종(어업
종류) 단위 집계값**으로 GFW 선박에 연결한다. 개별매칭(`match_tac_vessels.py`)
은 TAC에 GFW와 이을 고유식별자(콜사인/IMO)가 없어 이름 유사도로만 다리를
놓을 수 있는데, 실측 결과(`BlueScore_TAC매칭_임계값_실측분석.md`) 임계값을
아무리 튜닝해도 정밀도 7.5~13.2%에 그친다(동명이인 충돌이 근본 원인,
알고리즘으로 해결 불가). 이 스크립트는 매칭을 아예 우회한다 — TAC의
"할당 어업 종류 명"으로 그룹만 지으면 되고, 이름 비교가 필요 없다.

GFW 선박에 실제로 이 값을 붙이려면 "이 GFW 선박이 어느 업종인가"를 알아야
하는데, 그것도 개별 매칭 없이 푼다 — GFW가 이미 자체적으로 신고하는
gear type(fishingType 필드, 예: TRAWLERS)을 다리로 쓴다. 국내 어업종 ↔
GFW gear type 대응표(gear_type_mapping_draft.py)를 거꾸로 뒤집어서
"GFW gear type → 국내 업종들 → TAC 집계값"으로 조회 가능하게 만든다.

⚠⚠⚠ 중요 — 이 값의 신뢰도 한계 (2026-08-15 실측 확인):
gear_type_mapping_draft.py는 파일 자체에 "확정본이 아니다... 팀 회의에서
확정할 것"이라고 명시된 초안이다. 이 스크립트가 만드는 TAC 집계 표본
1,898척 중 92.2%(1,750척)가 그 초안의 "approximate"(불확실) 등급 매핑을
거쳐서 나온 값이다 — 예를 들어 국내 트롤 계열 어업종 6개가 전부 GFW
TRAWLERS 하나로 뭉뚱그려진다. 즉 이 스크립트로 얻는 커버리지 수치는
**수산업 도메인 지식이 있는 사람이 gear_type_mapping_draft.py를 확인하기
전까지는 잠정치로만 취급해야 한다.** 팀 확정 전에 "N% 확보"라고 확정된
사실처럼 공유하지 말 것.

출력: data/raw/tac_gear_type_aggregates.json
    {GFW gear type: {avgEnginePowerHp, avgTonnageGt, sourceVesselCount,
     mappingConfidence, domesticGearTypes: [...]}}
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.gear_type_mapping_draft import GEAR_TYPE_MAPPING_DRAFT  # noqa: E402
from data.snapshot_utils import find_latest  # noqa: E402

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_PATH = DATA_RAW_DIR / "tac_gear_type_aggregates.json"


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def aggregate_tac_by_domestic_gear_type() -> dict:
    """TAC CSV를 "할당 어업 종류 명" 기준으로 그룹지어 평균 톤수/마력을 낸다.
    어선번호 단위로 먼저 중복 제거한다 — TAC는 한 선박이 여러 행(할당별)을
    가질 수 있어서, 그룹 평균에 같은 배가 중복으로 들어가지 않게 한다."""
    tac_csv_path = find_latest(DATA_RAW_DIR, "해양수산부_수산정보_TAC 할당 승인 정보_*.csv")

    vessels_by_gear_type = defaultdict(dict)  # {gear_type: {vessel_no: (tonnage, power)}}
    with open(tac_csv_path, encoding="cp949", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vessel_no = (row.get("어선 번호") or "").strip()
            gear_type = (row.get("할당 어업 종류 명") or "").strip()
            if not vessel_no or not gear_type:
                continue
            tonnage = _to_float(row.get("선박 톤수"))
            power = _to_float(row.get("선박 마력"))
            vessels_by_gear_type[gear_type][vessel_no] = (tonnage, power)

    aggregates = {}
    for gear_type, vessels in vessels_by_gear_type.items():
        tonnages = [t for t, _ in vessels.values() if t is not None]
        powers = [p for _, p in vessels.values() if p is not None]
        aggregates[gear_type] = {
            "vesselCount": len(vessels),
            "avgTonnageGt": round(sum(tonnages) / len(tonnages), 1) if tonnages else None,
            "avgEnginePowerHp": round(sum(powers) / len(powers), 1) if powers else None,
        }
    return aggregates


def build_reverse_gear_type_map() -> dict:
    """국내 업종 → GFW gear type(gear_type_mapping_draft.py)을 뒤집어서
    GFW gear type → 국내 업종 목록으로 만든다. 여러 국내 업종이 같은 GFW
    gear type에 뭉뚱그려지는 경우(예: 트롤 계열 6종 전부 TRAWLERS)가 있어서
    1:N이 된다."""
    reverse = defaultdict(list)
    for domestic_name, entry in GEAR_TYPE_MAPPING_DRAFT.items():
        gfw_type = entry["gfwGearType"]
        if gfw_type is None:
            continue  # unmappable(잠수기어업, 연안복합어업) — GFW 쪽으로 못 감
        reverse[gfw_type].append({"domesticName": domestic_name, "confidence": entry["confidence"]})
    return reverse


def build_gfw_gear_type_aggregates() -> dict:
    """최종 산출물: GFW gear type 기준으로 국내 업종들의 TAC 집계값을
    가중평균(선박 수 가중)해서 하나로 합친다."""
    domestic_aggregates = aggregate_tac_by_domestic_gear_type()
    reverse_map = build_reverse_gear_type_map()

    result = {}
    for gfw_type, domestic_entries in reverse_map.items():
        total_vessels = 0
        weighted_tonnage_sum = 0.0
        weighted_power_sum = 0.0
        tonnage_weight = 0
        power_weight = 0
        used_domestic_names = []
        confidences = set()

        for entry in domestic_entries:
            name = entry["domesticName"]
            agg = domestic_aggregates.get(name)
            if agg is None:
                continue
            used_domestic_names.append(name)
            confidences.add(entry["confidence"])
            total_vessels += agg["vesselCount"]
            if agg["avgTonnageGt"] is not None:
                weighted_tonnage_sum += agg["avgTonnageGt"] * agg["vesselCount"]
                tonnage_weight += agg["vesselCount"]
            if agg["avgEnginePowerHp"] is not None:
                weighted_power_sum += agg["avgEnginePowerHp"] * agg["vesselCount"]
                power_weight += agg["vesselCount"]

        if not used_domestic_names:
            continue

        # 근사대응 업종이 하나라도 섞이면 전체를 approximate로 표시 — 과신 방지
        overall_confidence = "direct" if confidences == {"direct"} else "approximate"

        result[gfw_type] = {
            "domesticGearTypes": used_domestic_names,
            "mappingConfidence": overall_confidence,
            "sourceVesselCount": total_vessels,
            "avgTonnageGt": round(weighted_tonnage_sum / tonnage_weight, 1) if tonnage_weight else None,
            "avgEnginePowerHp": round(weighted_power_sum / power_weight, 1) if power_weight else None,
        }
    return result


def main():
    print("[1/2] TAC를 국내 업종 단위로 집계 중...")
    result = build_gfw_gear_type_aggregates()
    print(f"  GFW gear type {len(result)}종에 대해 업종단위 집계값 생성됨")

    approx_vessels = sum(v["sourceVesselCount"] for v in result.values() if v["mappingConfidence"] == "approximate")
    total_vessels = sum(v["sourceVesselCount"] for v in result.values())
    if total_vessels:
        print(f"  ⚠ 표본 {total_vessels}척 중 {approx_vessels}척({100*approx_vessels/total_vessels:.1f}%)이 "
              f"미검증 'approximate' 매핑 기반 — gear_type_mapping_draft.py 팀 확정 전까지 잠정치로 취급할 것")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[output] {OUTPUT_PATH}")

    print("\n[2/2] 요약:")
    for gfw_type, agg in sorted(result.items()):
        print(f"  {gfw_type}: 선박{agg['sourceVesselCount']}척 표본, "
              f"평균톤수 {agg['avgTonnageGt']}, 평균마력 {agg['avgEnginePowerHp']} "
              f"({agg['mappingConfidence']})")


if __name__ == "__main__":
    main()
