"""
담당: 김태윤

data/match_tac_vessels.py의 확정본(tac_vessel_matches_confirmed__*.jsonl.gz,
"바로 신뢰 가능" 등급만)을 data/raw/gfw_vessels_enriched.jsonl.gz에 병합한다.
score팀이 실제로 쓰는 파일은 gfw_vessels_enriched.jsonl.gz 하나이므로,
TAC 결과가 여기 들어가야 axis_b_physics.py 등에서 실제로 쓰인다.

병합 방침:
    - enginePowerHp, gearTypes(TAC의 domesticGearTypes로 이름 붙여 추가)는
      GFW/MOF 어느 쪽에도 없던 정보라 그냥 추가한다 — 충돌 여지 없음.
    - tonnageGt는 이미 gfw_vessels_enriched.jsonl.gz에 있을 수 있다(MOF
      매칭된 선박은 국내 톤수로 이미 채워져 있음). TAC 쪽 값과 다르면
      GFW-vs-MOF 톤수 불일치 실사례(MEDRA, CLAUDE.md 참고)처럼 실제로
      서로 다른 소스가 다른 값을 줄 수 있다는 신호이므로, 어느 한쪽으로
      임의로 덮어쓰지 않고 tacTonnageGt 필드로 별도 기록 + 불일치 여부를
      tacTonnageConflictWithExisting에 남긴다(원칙: 판단 없이 원본 보존).
    - TAC 매칭 자체가 안 된(unknown 상태 등) 선박은 그대로 둔다.

출력: data/raw/gfw_vessels_enriched.jsonl.gz를 덮어쓴다(원본은 여러 번
재실행 가능한 파생 산출물이라 — build_enriched_vessel_population.py도
매번 덮어쓰는 것과 동일 원칙. 실수로 지운 게 아니라 재생성 가능한 파일).
추가 필드: tacVesselNo, tacName, tacEnginePowerHp, tacTonnageGt,
tacDomesticGearTypes, tacMatchSource(mof/direct), tacTonnageConflictWithExisting.
"""

import gzip
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.snapshot_utils import find_latest  # noqa: E402

ENRICHED_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_vessels_enriched.jsonl.gz"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def find_latest_confirmed_tac() -> Path:
    try:
        return find_latest(RAW_DIR, "tac_vessel_matches_confirmed__*.jsonl.gz")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "tac_vessel_matches_confirmed__*.jsonl.gz가 없습니다. "
            "먼저 data/match_tac_vessels.py를 실행하세요."
        ) from exc


def load_confirmed_tac(path: Path) -> dict:
    by_id = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_id[r["vesselId"]] = r
    return by_id


def main():
    tac_path = find_latest_confirmed_tac()
    print(f"[1/2] TAC 확정본 로드: {tac_path.name}")
    tac_by_id = load_confirmed_tac(tac_path)
    print(f"  대상: {len(tac_by_id)}척")

    print("[2/2] gfw_vessels_enriched.jsonl.gz에 병합...")
    vessels = []
    with gzip.open(ENRICHED_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            vessels.append(json.loads(line))

    merged_count = 0
    tonnage_conflict_count = 0
    for v in vessels:
        tac = tac_by_id.get(v["vesselId"])
        if tac is None:
            continue

        v["tacVesselNo"] = tac["tacVesselNo"]
        v["tacName"] = tac["tacName"]
        v["tacEnginePowerHp"] = tac["enginePowerHp"]
        v["tacTonnageGt"] = tac["tonnageGt"]
        v["tacDomesticGearTypes"] = tac["gearTypes"]
        v["tacMatchSource"] = tac["source"]

        existing_tonnage = v.get("tonnage")
        conflict = (
            existing_tonnage is not None
            and tac["tonnageGt"] is not None
            and abs(existing_tonnage - tac["tonnageGt"]) > 0.01
        )
        v["tacTonnageConflictWithExisting"] = conflict
        if conflict:
            tonnage_conflict_count += 1
        merged_count += 1

    with gzip.open(ENRICHED_PATH, "wt", encoding="utf-8") as out:
        for v in vessels:
            out.write(json.dumps(v, ensure_ascii=False) + "\n")

    print(f"[output] {ENRICHED_PATH}")
    print(f"  병합됨: {merged_count}척, 기존 톤수와 충돌: {tonnage_conflict_count}척")


if __name__ == "__main__":
    main()
