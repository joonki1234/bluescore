"""매칭·태깅 결과 탐색적 분석 — process/ 파이프라인 실규모 재실행(35번) 후
최종 산출물(final_vessel_matches.jsonl, population_tags.jsonl)을 확인한다.

확인 대상:
  1. tier3 fuzzyScore 분포 — 임계값 0.8(잠정) 재조정 논의의 실제 근거
  2. unmatched의 "아깝게 떨어진" 후보 점수 분포 — 임계값을 낮추면 얼마나
     더 붙는지 가늠
  3. 매칭된 선박의 톤수(GT) 분포 — B축 peer_grouping(톤수대) 설계 참고
  4. 매칭률 — locationTag(근해/연안)별 교차 — 특정 집단이 매칭이 더/덜
     되는 편향이 있는지

읽기전용(raw/·processed/ 안 건드림). 결과는 JSON으로 저장.

사용법:
    python explore_matches.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
MATCHES_PATH = PROCESSED / "final_vessel_matches.jsonl"
TAGS_PATH = PROCESSED / "population_tags.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "output" / "matches_summary.json"


def percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _bucket(vals: list, edges: list, labels: list) -> list:
    counts = [0] * len(labels)
    for v in vals:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
    return [{"label": l, "count": c} for l, c in zip(labels, counts)]


def run() -> None:
    matches = [json.loads(line) for line in MATCHES_PATH.open(encoding="utf-8")]
    tags = {t["gfwVesselId"]: t for t in (json.loads(line) for line in TAGS_PATH.open(encoding="utf-8"))}
    total = len(matches)

    # 1. tier3 fuzzyScore 분포
    fuzzy_scores = sorted(m["fuzzyScore"] for m in matches if m["matchTier"] == "tier3_fuzzy_name")
    edges = [0.8, 0.82, 0.85, 0.88, 0.92, 0.96, 1.001]
    labels = ["0.80-0.82", "0.82-0.85", "0.85-0.88", "0.88-0.92", "0.92-0.96", "0.96-1.00"]
    fuzzy_buckets = _bucket(fuzzy_scores, edges, labels)

    # 2. unmatched의 최고 후보 점수 분포 (임계값 낮추면 구제될 수 있는 후보)
    rejected_scores = sorted(
        m["bestRejectedCandidate"]["score"]
        for m in matches
        if m["matchTier"] == "unmatched" and m.get("bestRejectedCandidate")
    )
    r_edges = [0, 0.5, 0.6, 0.7, 0.75, 0.78, 0.8]
    r_labels = ["0-0.5", "0.5-0.6", "0.6-0.7", "0.7-0.75", "0.75-0.78", "0.78-0.80"]
    rejected_buckets = _bucket(rejected_scores, r_edges, r_labels)
    near_miss_070_080 = sum(1 for s in rejected_scores if 0.7 <= s < 0.8)

    # 3. 매칭된 선박 톤수(GT) 분포
    def _tonnage(m):
        for src in ("tac", "mof"):
            d = m.get(src)
            if d:
                key = "tonnageGtTac" if src == "tac" else "tonnageGtMof"
                v = d.get(key)
                if v not in (None, ""):
                    try:
                        return float(v)
                    except ValueError:
                        return None
        return None

    tonnages = sorted(t for t in (_tonnage(m) for m in matches) if t is not None)

    # 4. locationTag별 매칭률
    by_tag = Counter()
    matched_by_tag = Counter()
    for m in matches:
        tag = tags.get(m["gfwVesselId"], {}).get("locationTag", "(태그없음)")
        by_tag[tag] += 1
        if m["matchTier"] != "unmatched":
            matched_by_tag[tag] += 1
    match_rate_by_tag = {
        tag: {"total": n, "matched": matched_by_tag[tag], "rate": round(matched_by_tag[tag] / n, 4)}
        for tag, n in by_tag.items()
    }

    result = {
        "total_vessels": total,
        "fuzzy_score": {
            "count": len(fuzzy_scores),
            "min": fuzzy_scores[0] if fuzzy_scores else None,
            "median": percentile(fuzzy_scores, 0.5),
            "p90": percentile(fuzzy_scores, 0.9),
            "max": fuzzy_scores[-1] if fuzzy_scores else None,
            "buckets": fuzzy_buckets,
        },
        "rejected_score": {
            "count": len(rejected_scores),
            "buckets": rejected_buckets,
            "near_miss_0.70_0.80_count": near_miss_070_080,
        },
        "tonnage_gt": {
            "count": len(tonnages),
            "min": tonnages[0] if tonnages else None,
            "median": percentile(tonnages, 0.5),
            "p90": percentile(tonnages, 0.9),
            "max": tonnages[-1] if tonnages else None,
        },
        "match_rate_by_location_tag": match_rate_by_tag,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"tier3 fuzzyScore: n={len(fuzzy_scores)} median={result['fuzzy_score']['median']:.3f} p90={result['fuzzy_score']['p90']:.3f}")
    print(f"unmatched 최고후보점수 0.70~0.80(임계값 낮추면 구제 후보): {near_miss_070_080}척")
    print(f"매칭된 선박 톤수(GT): n={len(tonnages)} median={result['tonnage_gt']['median']:.1f} p90={result['tonnage_gt']['p90']:.1f} max={result['tonnage_gt']['max']}")
    print(f"locationTag별 매칭률: {match_rate_by_tag}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
