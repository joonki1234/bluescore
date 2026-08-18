"""매칭 정밀도 사람 라벨링용 표본 추출 — 48번 정답신호 검증을 보완하는
수동 검증 표본을 만든다(라벨링 아티팩트에 임베드된 데이터의 재현용 스크립트).

층화추출: tier3(TAC 출처) 매칭을 점수구간 4개(0.80~0.85/0.85~0.90/
0.90~0.95/0.95~) 15개씩 + unmatched 근접점수(0.70~0.80) 20개, 총 80쌍.
시드 고정(42)이라 재실행해도 같은 표본이 나온다.

읽기전용(raw/·processed/ 안 건드림).

사용법:
    python generate_labeling_sample.py
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
MATCHES_PATH = PROCESSED / "final_vessel_matches.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "output" / "labeling_sample.json"

RANDOM_SEED = 42
BAND_SAMPLE_SIZE = 15
UNMATCHED_SAMPLE_SIZE = 20
SCORE_BANDS = [(0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.2)]


def _gfw_num(name: str) -> str | None:
    m = re.match(r"^\D*?(\d{2,4})", name or "")
    return m.group(1) if m else None


def _kr_num(name: str) -> str | None:
    m = re.search(r"제(\d{2,4})|^(\d{2,4})", name or "")
    return (m.group(1) or m.group(2)) if m else None


def _num_flag(gfw_name: str, kr_name: str) -> str:
    gn, kn = _gfw_num(gfw_name), _kr_num(kr_name)
    if not gn or not kn:
        return "unknown"
    return "match" if gn == kn else "mismatch"


def run() -> None:
    rows = [json.loads(line) for line in MATCHES_PATH.open(encoding="utf-8")]
    rng = random.Random(RANDOM_SEED)
    samples = []

    tier3 = [r for r in rows if r["matchTier"] == "tier3_fuzzy_name" and r.get("tac") and r["tac"].get("nameTac")]
    for lo, hi in SCORE_BANDS:
        pool = [r for r in tier3 if lo <= r["fuzzyScore"] < hi]
        for r in rng.sample(pool, min(BAND_SAMPLE_SIZE, len(pool))):
            samples.append(
                {
                    "group": f"matched_{lo}-{hi}",
                    "gfwVesselId": r["gfwVesselId"],
                    "gfwName": r["gfwName"],
                    "candidateName": r["tac"]["nameTac"],
                    "score": r["fuzzyScore"],
                    "source": r["fuzzySource"],
                    "numFlag": _num_flag(r["gfwName"], r["tac"]["nameTac"]),
                }
            )

    unmatched = [r for r in rows if r["matchTier"] == "unmatched" and r.get("bestRejectedCandidate")]
    near = [r for r in unmatched if 0.70 <= r["bestRejectedCandidate"]["score"] < 0.80]
    for r in rng.sample(near, min(UNMATCHED_SAMPLE_SIZE, len(near))):
        samples.append(
            {
                "group": "unmatched_0.70-0.80",
                "gfwVesselId": r["gfwVesselId"],
                "gfwName": r["gfwName"],
                "candidateName": r["bestRejectedCandidate"]["name"],
                "score": r["bestRejectedCandidate"]["score"],
                "source": "rejected",
                "numFlag": _num_flag(r["gfwName"], r["bestRejectedCandidate"]["name"]),
            }
        )

    rng.shuffle(samples)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"표본 {len(samples)}건 -> {OUT_PATH}")


if __name__ == "__main__":
    run()
