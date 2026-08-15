"""
담당: 김태윤

모든 소스의 매칭 결과를 "선박 하나 = 한 줄"인 마스터 테이블로 항상
통합한다. 지금까지는 이 통합 뷰(build_matching_overview.py)가 MOF/TAC
매칭 상태만 옆으로 이어붙인 진단용이었는데, 여기에 TAC 업종단위 집계
(aggregate_tac_by_gear_type.py)까지 더해서 "이 선박이 기관출력 정보를
어디서 확보했는가"를 한 줄로 볼 수 있게 한다.

재수집·재매칭을 하지 않는다 — 이미 있는 결과물을 그대로 재사용한다:
    - GFW 앵커: data/raw/gfw_vessels_enriched.jsonl.gz
    - MOF·TAC 개별매칭: data/raw/gfw_matching_overview__*.jsonl.gz
    - TAC 업종단위 집계: data/raw/tac_gear_type_aggregates.json
      (aggregate_tac_by_gear_type.py의 산출물 — 먼저 실행해둘 것)

⚠ tacAggregateValue의 신뢰도 한계는 aggregate_tac_by_gear_type.py 상단
경고 참고 — gear_type_mapping_draft.py가 팀 확정 전 초안이라, 표본의
92.2%가 미검증 'approximate' 매핑 기반이다.

출력: data/raw/master_vessel_registry__<타임스탬프>.jsonl.gz
"""

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.snapshot_utils import find_latest  # noqa: E402

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"


def load_gear_type_aggregates() -> dict:
    path = find_latest(DATA_RAW_DIR, "tac_gear_type_aggregates*.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_matching_overview() -> dict:
    """build_matching_overview.py 산출물 재사용 — vesselId 기준 dict로."""
    path = find_latest(DATA_RAW_DIR, "gfw_matching_overview__*.jsonl.gz")
    by_id = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_id[r["vesselId"]] = r
    return by_id


def load_self_contradicting_ids() -> set:
    """filter_self_contradicting_labels.py 산출물 재사용 — 있으면 쓰고,
    없으면 빈 집합(아직 안 돌렸을 수 있음)."""
    try:
        path = find_latest(DATA_RAW_DIR, "gfw_self_contradicting_vessel_ids__*.json")
    except FileNotFoundError:
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("flaggedVesselIds", []))


def derive_tac_individual(overview_row: dict) -> dict:
    """경로A(MOF경유)를 우선하고, 없으면 경로B(직접)를 쓴다 —
    match_tac_vessels.py의 build_confirmed_tier()와 동일한 우선순위 원칙."""
    if overview_row["tacPathA_status"] == "name_fuzzy_mutual":
        return {
            "status": "confirmed_fuzzy" if not overview_row.get("mofPossibleMisclassification") else "rejected",
            "path": "mof경유",
            "name": overview_row["tacPathA_name"],
            "numberStatus": overview_row["tacPathA_numberStatus"],
        }
    if overview_row["tacPathB_status"] == "name_fuzzy_mutual":
        return {
            "status": "confirmed_fuzzy" if not overview_row.get("mofPossibleMisclassification") else "rejected",
            "path": "직접(로마자)",
            "name": overview_row["tacPathB_name"],
            "numberStatus": overview_row["tacPathB_numberStatus"],
        }
    return {"status": "not_found", "path": None, "name": None, "numberStatus": None}


def derive_mof(overview_row: dict) -> dict:
    if overview_row["mofStatus"] in ("imo_exact", "callsign_exact", "name_fuzzy"):
        status = "exact_id" if overview_row["mofStatus"] != "name_fuzzy" else "confirmed_fuzzy"
    else:
        status = "not_found"
    return {
        "status": status,
        "nameKor": overview_row["mofNameKor"],
        "tonnage": overview_row["mofTonnage"],
        "possibleMisclassification": overview_row["mofPossibleMisclassification"],
    }


def build_registry() -> list:
    gfw_path = find_latest(DATA_RAW_DIR, "gfw_vessels_enriched.jsonl.gz")
    overview_by_id = load_matching_overview()
    gear_aggregates = load_gear_type_aggregates()
    self_contradicting_ids = load_self_contradicting_ids()

    rows = []
    with gzip.open(gfw_path, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            vessel_id = v["vesselId"]
            fishing_types = v.get("fishingType") or []
            overview_row = overview_by_id.get(vessel_id)

            # TAC 업종단위 집계 — GFW 자기신고 gear type이 집계표에 있으면 커버됨.
            # 여러 gear type이 있으면(드묾) 표본이 제일 큰 것을 대표로 쓴다.
            matched_gear_types = [gt for gt in fishing_types if gt in gear_aggregates]
            if matched_gear_types:
                best_gear_type = max(matched_gear_types, key=lambda gt: gear_aggregates[gt]["sourceVesselCount"])
                agg = gear_aggregates[best_gear_type]
                tac_aggregate = {
                    "status": "confirmed_fuzzy" if agg["mappingConfidence"] == "direct" else "needs_human_review",
                    "gfwGearType": best_gear_type,
                    "domesticGearTypes": agg["domesticGearTypes"],
                    "avgEnginePowerHp": agg["avgEnginePowerHp"],
                    "avgTonnageGt": agg["avgTonnageGt"],
                    "sourceVesselCount": agg["sourceVesselCount"],
                }
            else:
                tac_aggregate = {"status": "not_found", "gfwGearType": None, "domesticGearTypes": None,
                                  "avgEnginePowerHp": None, "avgTonnageGt": None, "sourceVesselCount": None}

            row = {
                "vesselId": vessel_id,
                "gfwName": v.get("name"),
                "gfwTonnage": v.get("tonnage"),
                "gfwFishingType": fishing_types,
                "mofStatus": derive_mof(overview_row)["status"] if overview_row else "not_found",
                "mofValue": derive_mof(overview_row) if overview_row else None,
                "tacIndividualStatus": derive_tac_individual(overview_row)["status"] if overview_row else "not_found",
                "tacIndividualValue": derive_tac_individual(overview_row) if overview_row else None,
                "tacAggregateStatus": tac_aggregate["status"],
                "tacAggregateValue": tac_aggregate,
                "gfwSelfContradictingFlag": vessel_id in self_contradicting_ids,
            }
            rows.append(row)
    return rows


def main():
    print("[1/2] 마스터 레지스트리 조립 중 (재수집 없이 기존 산출물만 재사용)...")
    rows = build_registry()
    print(f"  총 {len(rows)}척")

    ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
    out_path = DATA_RAW_DIR / f"master_vessel_registry__{ts}.jsonl.gz"
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[output] {out_path}")

    print("\n[2/2] 커버리지 요약")
    mof_covered = sum(1 for r in rows if r["mofStatus"] in ("exact_id", "confirmed_fuzzy"))
    tac_individual_covered = sum(1 for r in rows if r["tacIndividualStatus"] == "confirmed_fuzzy")
    tac_aggregate_covered = sum(1 for r in rows if r["tacAggregateStatus"] in ("confirmed_fuzzy", "needs_human_review"))
    any_engine_power = sum(
        1 for r in rows
        if r["tacIndividualValue"] and r["tacIndividualStatus"] == "confirmed_fuzzy"
        or r["tacAggregateStatus"] in ("confirmed_fuzzy", "needs_human_review")
    )
    self_contradicting_flagged = sum(1 for r in rows if r["gfwSelfContradictingFlag"])
    print(f"  전체: {len(rows)}척")
    print(f"  MOF 매칭(exact_id/confirmed_fuzzy): {mof_covered}척 ({100*mof_covered/len(rows):.1f}%)")
    print(f"  TAC 개별매칭: {tac_individual_covered}척 ({100*tac_individual_covered/len(rows):.2f}%)")
    print(f"  TAC 업종단위 집계 커버: {tac_aggregate_covered}척 ({100*tac_aggregate_covered/len(rows):.1f}%) "
          f"⚠ 미검증 초안 매핑 기반 — aggregate_tac_by_gear_type.py 경고 참고")
    print(f"  기관출력 확보(개별+업종단위 합계, 중복없이): {any_engine_power}척 ({100*any_engine_power/len(rows):.1f}%)")
    print(f"  GFW 자기모순 플래그: {self_contradicting_flagged}척 ({100*self_contradicting_flagged/len(rows):.2f}%) "
          f"— 삭제 아님, 하위 소비자가 걸러 쓸 판단 필드")


if __name__ == "__main__":
    main()
