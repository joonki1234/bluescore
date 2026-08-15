"""
담당: 김태윤

GFW 선박 하나당 "국내 선박제원(MOF) 매칭 상태"와 "TAC 매칭 상태(경로A/B)"를
필터링 없이 옆으로 이어붙여서 한 줄로 보여주는 통합 뷰를 만든다.

기존에는 이 정보가 세 파일에 따로 있었다 — vessel_spec_matches(MOF),
tac_vessel_matches(경로A: GFW->MOF->TAC), tac_vessel_matches_direct(경로B:
GFW->TAC 직접). 각 파일의 matchMethod 등급(확정/임계값미달/미매칭)은 그대로
보존하고 누락 없이 전부 담는다 — gfw_vessels_enriched.jsonl.gz처럼 신뢰도
통과한 것만 남기는 필터링본이 아니라, "지금 상태가 어떤지" 진단용이다.

대상 모집단: GFW 어업선박 중 이벤트가 있는 9,468척(match_tac_to_gfw_direct의
대상과 동일) — TAC 경로B가 이 전체를 커버하므로 그 파일에서 vesselId 집합을
가져온다.

출력:
    data/raw/gfw_matching_overview__<날짜>.jsonl.gz  (전체 필드)
    data/raw/gfw_matching_overview__<날짜>.csv        (엑셀에서 바로 열어보기용)
"""

import csv
import gzip
import json
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.match_tac_vessels import MOF_MATCHES_PATH  # noqa: E402
from data.snapshot_utils import find_latest  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
VESSEL_SPEC_MATCHES_PATH = MOF_MATCHES_PATH
TAC_PATH_A_PATH = find_latest(RAW_DIR, "tac_vessel_matches__*.jsonl.gz")
TAC_PATH_B_PATH = find_latest(RAW_DIR, "tac_vessel_matches_direct__*.jsonl.gz")
ENRICHED_VESSELS_PATH = RAW_DIR / "gfw_vessels_enriched.jsonl.gz"

CSV_FIELDS = [
    "vesselId", "gfwName", "gfwTonnage",
    "mofStatus", "mofNameKor", "mofTonnage", "mofPossibleMisclassification",
    "tacPathA_status", "tacPathA_name", "tacPathA_numberStatus",
    "tacPathB_status", "tacPathB_name", "tacPathB_numberStatus",
]


def load_mof_status() -> dict:
    """vesselId -> {status, nameKor, tonnage, possibleMisclassification}.
    이 파일엔 콜사인/이름 둘 다 없어 매칭 시도 자체를 안 한 2,141척은
    없다 — 그 경우는 build_overview()에서 "no_identifier"로 채운다."""
    status = {}
    with gzip.open(VESSEL_SPEC_MATCHES_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            spec = r.get("matchedSpec") or {}
            status[r["vesselId"]] = {
                "status": r["matchMethod"],
                "nameKor": spec.get("vesselNameKor"),
                "tonnage": spec.get("grossTonnage"),
                "possibleMisclassification": bool(r.get("possibleMisclassification")),
            }
    return status


def load_tac_status(path: Path) -> dict:
    """vesselId -> {status, name, numberStatus}. unmatched인 행도 그대로 남긴다."""
    status = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            status[r["vesselId"]] = {
                "status": r["matchMethod"],
                "name": r.get("tacName"),
                "numberStatus": r.get("numberStatus"),
            }
    return status


def load_gfw_basic_info() -> dict:
    """vesselId -> {name, tonnage} — gfw_vessels_enriched.jsonl.gz에서."""
    info = {}
    with gzip.open(ENRICHED_VESSELS_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            info[v["vesselId"]] = {"name": v.get("name"), "tonnage": v.get("tonnage")}
    return info


def build_overview() -> list:
    mof_status = load_mof_status()
    tac_a_status = load_tac_status(TAC_PATH_A_PATH)
    tac_b_status = load_tac_status(TAC_PATH_B_PATH)
    gfw_info = load_gfw_basic_info()

    # 경로B가 GFW 대상 선박(9,468척) 전체를 커버하므로, 그 vesselId 집합을
    # 모집단 기준으로 삼는다.
    all_vessel_ids = set(tac_b_status.keys())

    rows = []
    for vessel_id in sorted(all_vessel_ids):
        mof = mof_status.get(vessel_id)
        tac_a = tac_a_status.get(vessel_id)
        tac_b = tac_b_status.get(vessel_id)
        gfw = gfw_info.get(vessel_id, {})

        rows.append({
            "vesselId": vessel_id,
            "gfwName": gfw.get("name"),
            "gfwTonnage": gfw.get("tonnage"),
            "mofStatus": mof["status"] if mof else "no_identifier",
            "mofNameKor": mof["nameKor"] if mof else None,
            "mofTonnage": mof["tonnage"] if mof else None,
            "mofPossibleMisclassification": mof["possibleMisclassification"] if mof else None,
            "tacPathA_status": tac_a["status"] if tac_a else "not_attempted_no_mof_match",
            "tacPathA_name": tac_a["name"] if tac_a else None,
            "tacPathA_numberStatus": tac_a["numberStatus"] if tac_a else None,
            "tacPathB_status": tac_b["status"] if tac_b else "unmatched",
            "tacPathB_name": tac_b["name"] if tac_b else None,
            "tacPathB_numberStatus": tac_b["numberStatus"] if tac_b else None,
        })
    return rows


def main():
    print("[1/2] 세 파일 로드 및 vesselId 기준 병합 중...")
    rows = build_overview()
    print(f"  대상 GFW 선박: {len(rows)}척")

    out_jsonl = RAW_DIR / f"gfw_matching_overview__{date.today().isoformat()}.jsonl.gz"
    with gzip.open(out_jsonl, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    out_csv = RAW_DIR / f"gfw_matching_overview__{date.today().isoformat()}.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"[output] {out_jsonl}")
    print(f"[output] {out_csv}")

    print("[2/2] 요약...")
    mof_matched = sum(1 for r in rows if r["mofStatus"] in ("imo_exact", "callsign_exact", "name_fuzzy"))
    tac_a_mutual = sum(1 for r in rows if r["tacPathA_status"] == "name_fuzzy_mutual")
    tac_b_mutual = sum(1 for r in rows if r["tacPathB_status"] == "name_fuzzy_mutual")
    tac_any_mutual = sum(1 for r in rows if r["tacPathA_status"] == "name_fuzzy_mutual" or r["tacPathB_status"] == "name_fuzzy_mutual")
    print(f"  MOF 확정매칭: {mof_matched}척")
    print(f"  TAC 경로A 상호매칭: {tac_a_mutual}척 / 경로B 상호매칭: {tac_b_mutual}척 / 둘 중 하나라도: {tac_any_mutual}척")


if __name__ == "__main__":
    main()
