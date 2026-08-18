"""GFW 선박 상세 탐색적 분석 — vessels 실규모 수집 완료(5,323척) 후 확인.

확인 대상:
  1. registryInfo 존재율 재검증 — CLAUDE.md 확정사항(0/50 표본)을 5,323척 전수로
  2. selfReportedInfo flag 분포 — 모집단 정의(flag=KOR) 최종 검증
  3. 이름 없는 선박(registryName/selfReportedName 둘 다 null) 특성
  4. averageSpeedKnots / totalDistanceKm 분포 — 이벤트 원본, 아직 안 본 필드
  5. 상위 이벤트 선박 실명 확인 — explore_events.py의 top10 vesselId에 이름 매칭

읽기전용(raw/·processed/ 안 건드림). 결과는 JSON으로 저장.

사용법:
    python explore_vessels.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

VESSELS_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_vessels_normalized.jsonl"
EVENTS_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_events_normalized.jsonl"
EVENTS_SUMMARY_PATH = Path(__file__).resolve().parent / "output" / "events_summary.json"
OUT_PATH = Path(__file__).resolve().parent / "output" / "vessels_summary.json"


def percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def run() -> None:
    vessels = [json.loads(line) for line in VESSELS_PATH.open(encoding="utf-8")]
    total = len(vessels)

    # 1. registryInfo 존재율
    n_registry = sum(1 for v in vessels if v["hasRegistryMatch"])

    # 2. flag 분포
    flag_counts = Counter(v.get("flag") or "(없음)" for v in vessels)

    # 3. 이름 없는 선박
    no_name = [v for v in vessels if not v.get("registryName") and not v.get("selfReportedName")]
    no_name_has_gear = sum(1 for v in no_name if v.get("combinedGearTypes"))

    # 4. averageSpeedKnots / totalDistanceKm (이벤트 원본)
    speeds, distances = [], []
    for line in EVENTS_PATH.open(encoding="utf-8"):
        e = json.loads(line)
        if e.get("averageSpeedKnots") is not None:
            speeds.append(e["averageSpeedKnots"])
        if e.get("totalDistanceKm") is not None:
            distances.append(e["totalDistanceKm"])
    speeds.sort()
    distances.sort()

    # 5. 상위 이벤트 선박 실명 확인
    vessel_by_id = {v["vesselId"]: v for v in vessels}
    top10_named = []
    if EVENTS_SUMMARY_PATH.exists():
        summary = json.loads(EVENTS_SUMMARY_PATH.read_text(encoding="utf-8"))
        for row in summary["events_per_vessel"]["top10"]:
            v = vessel_by_id.get(row["vesselId"], {})
            name = v.get("registryName") or v.get("selfReportedName") or "(이름 없음)"
            top10_named.append({"vesselId": row["vesselId"], "count": row["count"], "name": name})

    result = {
        "total_vessels": total,
        "registry_match": {"count": n_registry, "rate": round(n_registry / total, 4)},
        "flag_distribution": dict(flag_counts.most_common()),
        "no_name": {
            "count": len(no_name),
            "rate": round(len(no_name) / total, 4),
            "has_gear_type_count": no_name_has_gear,
        },
        "average_speed_knots": {
            "count": len(speeds),
            "min": speeds[0] if speeds else None,
            "median": percentile(speeds, 0.5),
            "p90": percentile(speeds, 0.9),
            "max": speeds[-1] if speeds else None,
        },
        "total_distance_km": {
            "count": len(distances),
            "min": distances[0] if distances else None,
            "median": percentile(distances, 0.5),
            "p90": percentile(distances, 0.9),
            "max": distances[-1] if distances else None,
        },
        "top10_named": top10_named,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"선박 {total}척, registryInfo 매칭 {n_registry}척({result['registry_match']['rate']*100:.1f}%)")
    print(f"flag 분포: {dict(flag_counts.most_common(5))}")
    print(f"이름 없는 선박: {len(no_name)}척({result['no_name']['rate']*100:.1f}%), 그중 gearType 있음 {no_name_has_gear}척")
    print(f"averageSpeedKnots: median={result['average_speed_knots']['median']:.2f} max={result['average_speed_knots']['max']}")
    print(f"totalDistanceKm: median={result['total_distance_km']['median']:.2f} max={result['total_distance_km']['max']}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
