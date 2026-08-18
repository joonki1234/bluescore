"""GFW 이벤트 탐색적 분석 — 실규모 수집 완료(276,562건) 직후, process/ 매칭
파이프라인을 다 돌리기 전에 바로 확인 가능한 지점들만 모은다.

확인 대상(전부 processed/gfw_events_normalized.jsonl 하나로 충분, 매칭/기상
부착 대기 불필요):
  1. 선박당 이벤트수 분포 — 소수 선박 편중 여부(A축 설계 관련)
  2. 월별 이벤트 밀도 — 계절성
  3. 위경도 0.5도 격자 밀집도 — 혼잡구역 후보
  4. regions.mpa 실값 비율 — CLAUDE.md 확정사항(표본 70,747건 중 14.7%)을
     실규모로 재검증
  5. durationHours 분포·이상치 — 음수/0/24시간 초과 등

가공(process/) 단계 산출물만 읽는 읽기전용 분석이라 raw/·processed/ 둘 다
건드리지 않는다. 결과는 JSON으로 저장 — 재실행하면 덮어씀(재현 가능).

사용법:
    python explore_events.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

IN_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_events_normalized.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "output" / "events_summary.json"


def percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def run() -> None:
    events = [json.loads(line) for line in IN_PATH.open(encoding="utf-8")]
    total = len(events)

    # 1. 선박당 이벤트수 분포
    per_vessel = Counter(e["vesselId"] for e in events)
    counts_sorted = sorted(per_vessel.values())
    top10 = per_vessel.most_common(10)

    # 2. 월별 이벤트 밀도
    monthly = Counter(e["start"][:7] for e in events if e.get("start"))

    # 3. 위경도 0.5도 격자 밀집도(상위 10칸)
    grid = Counter()
    for e in events:
        lat, lon = e.get("latitude"), e.get("longitude")
        if lat is None or lon is None:
            continue
        grid[(round(lat * 2) / 2, round(lon * 2) / 2)] += 1
    top_grid = grid.most_common(10)

    # 4. regions.mpa 실값 비율
    mpa_nonempty = sum(1 for e in events if e.get("regionsMpa"))

    # 5. durationHours 분포·이상치
    durations = sorted(e["durationHours"] for e in events if e.get("durationHours") is not None)
    n_negative = sum(1 for d in durations if d < 0)
    n_zero = sum(1 for d in durations if d == 0)
    n_over24 = sum(1 for d in durations if d > 24)
    bucket_edges = [0, 1, 2, 4, 8, 12, 24, 48, 10**9]
    bucket_labels = ["0-1h", "1-2h", "2-4h", "4-8h", "8-12h", "12-24h", "24-48h", "48h+"]
    buckets = [0] * len(bucket_labels)
    for d in durations:
        for i in range(len(bucket_edges) - 1):
            if bucket_edges[i] <= d < bucket_edges[i + 1]:
                buckets[i] += 1
                break

    summary = {
        "total_events": total,
        "distinct_vessels": len(per_vessel),
        "events_per_vessel": {
            "min": counts_sorted[0],
            "p25": percentile(counts_sorted, 0.25),
            "median": percentile(counts_sorted, 0.5),
            "p75": percentile(counts_sorted, 0.75),
            "p90": percentile(counts_sorted, 0.9),
            "p99": percentile(counts_sorted, 0.99),
            "max": counts_sorted[-1],
            "top10": [{"vesselId": v, "count": c} for v, c in top10],
        },
        "monthly_counts": dict(sorted(monthly.items())),
        "top_grid_cells": [
            {"lat": lat, "lon": lon, "count": c} for (lat, lon), c in top_grid
        ],
        "mpa_nonempty": {
            "count": mpa_nonempty,
            "total": total,
            "rate": round(mpa_nonempty / total, 4),
        },
        "duration_hours": {
            "count": len(durations),
            "negative_count": n_negative,
            "zero_count": n_zero,
            "over_24h_count": n_over24,
            "min": durations[0] if durations else None,
            "median": percentile(durations, 0.5),
            "p90": percentile(durations, 0.9),
            "p99": percentile(durations, 0.99),
            "max": durations[-1] if durations else None,
            "buckets": [{"label": l, "count": c} for l, c in zip(bucket_labels, buckets)],
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"이벤트 {total}건, 선박 {len(per_vessel)}척")
    print(f"선박당 이벤트수: median={summary['events_per_vessel']['median']:.0f} "
          f"p90={summary['events_per_vessel']['p90']:.0f} max={summary['events_per_vessel']['max']}")
    print(f"regions.mpa 실값 비율: {mpa_nonempty}/{total} ({summary['mpa_nonempty']['rate']*100:.1f}%)")
    print(f"durationHours: 음수 {n_negative}건, 0 {n_zero}건, 24시간초과 {n_over24}건, "
          f"median={summary['duration_hours']['median']:.2f}h")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
