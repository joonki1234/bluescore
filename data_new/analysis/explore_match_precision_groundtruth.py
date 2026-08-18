"""매칭 정밀도 — MOF vsslKnd를 정답 대용 신호로 쓴 실측 검증.

배경: `bluescore/data/BlueScore_TAC매칭_임계값_실측분석.md`(구 파이프라인)가
쓴 방법론을 데이터_new에 재적용한다. 구 분석은 MOF의
"비어선 의심" 플래그를 정답 대용으로 써서 TAC 이름매칭 정밀도를
0.70~0.98 임계값 전 구간에서 실측했고, 7.5~13.2%로 낮고 임계값을
올려도 안 오른다는 결론(동명이인 문제)을 냈다 — analysis/의 다른
스크립트들이 한 "육안 표본 판단"(38·40번)보다 훨씬 엄격한 방법.

방법: tier3(TAC/어선원부 출처) 매칭된 GFW 선박마다, **그 매칭과 무관하게
독립적으로 수집해둔** MOF 검색 결과(raw, 91/92 필터 전)를 확인한다.
GFW 자기신고명과 아주 비슷한 이름의 MOF 후보가 있는데 그 후보의
vsslKnd가 어선(91/92)이 아니면 — "이 GFW 선박은 사실 다른(비어선)
실체와 이름이 겹치는 것 아닌가"라는 충돌 신호로 본다.

읽기전용(raw/·processed/ 안 건드림). 결과는 JSON으로 저장.

사용법:
    python explore_match_precision_groundtruth.py
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
MATCHES_PATH = PROCESSED / "final_vessel_matches.jsonl"
MOF_PATH = PROCESSED / "mof_candidates_normalized.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "output" / "match_precision_groundtruth.json"

CONFLICT_NAME_SIM_THRESHOLD = 0.85  # 이 이상 비슷하면 "같은 배를 가리킬 가능성" 신호로 봄


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def run() -> None:
    matches = [json.loads(line) for line in MATCHES_PATH.open(encoding="utf-8")]
    mof_by_gfw_id = {}
    for line in MOF_PATH.open(encoding="utf-8"):
        row = json.loads(line)
        mof_by_gfw_id[row["gfwVesselId"]] = row["candidates"]

    tier3 = [m for m in matches if m["matchTier"] == "tier3_fuzzy_name" and m["fuzzySource"] in ("tac", "vessel_registry")]

    # 임계값(fuzzyScore)을 0.80~1.00까지 늘려가며, 그 임계값을 넘는 매칭 중
    # MOF 비어선 충돌 신호가 있는/없는 비율을 계산 — 구 분석과 같은 표 형태.
    thresholds = [0.80, 0.85, 0.90, 0.95, 0.98]
    table = []
    checkable_total = 0

    per_vessel_conflict = {}
    for m in tier3:
        gfw_id = m["gfwVesselId"]
        cands = mof_by_gfw_id.get(gfw_id)
        if not cands:
            continue  # 이 선박은 MOF 검색결과 자체가 없어 검증 불가(대상에서 제외)
        gfw_norm = _normalize(m["gfwName"])
        conflict = False
        for c in cands:
            eng = c.get("vsslEngNm") or c.get("vsslKorNm")
            if not eng:
                continue
            sim = _similarity(gfw_norm, _normalize(eng))
            if sim >= CONFLICT_NAME_SIM_THRESHOLD:
                vk = c.get("vsslKnd") or ""
                if not (vk.startswith("91") or vk.startswith("92")):
                    conflict = True
                    break
        per_vessel_conflict[gfw_id] = conflict

    checkable_total = len(per_vessel_conflict)

    for th in thresholds:
        passed = [m for m in tier3 if m["fuzzyScore"] >= th and m["gfwVesselId"] in per_vessel_conflict]
        n = len(passed)
        conflicts = sum(1 for m in passed if per_vessel_conflict[m["gfwVesselId"]])
        clean = n - conflicts
        precision_floor = round(clean / n, 3) if n else None
        table.append({"threshold": th, "checkable_n": n, "clean": clean, "conflict": conflicts, "precision_floor": precision_floor})

    result = {
        "tier3_tac_registry_total": len(tier3),
        "checkable_via_mof_crosscheck": checkable_total,
        "note": "검증 가능한 건 MOF 검색결과가 있는 선박뿐(전체의 일부) — 구 분석(572건)과 비슷한 제약",
        "table": table,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"tier3(tac/registry) {len(tier3)}척 중 MOF 교차검증 가능 {checkable_total}척")
    print(f"{'임계값':>6} {'검증가능':>8} {'충돌없음':>8} {'충돌':>6} {'정밀도하한':>10}")
    for row in table:
        print(f"{row['threshold']:>6} {row['checkable_n']:>8} {row['clean']:>8} {row['conflict']:>6} {row['precision_floor']}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
