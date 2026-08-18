"""근해/연안·양식업 태그 부착 — 모집단 범위 결정(PROCESS_LOG.md 14번)의
"필터링하지 않고 태그만 붙인다" 원칙 구현.

태그 소스 2종을 둘 다 붙인다(둘 다 참고용, 하나를 정답으로 안 정함):
  - licenseTag: TAC 매칭됐으면 어업허가 업종명 -> gear_type_categories.py
    매핑표로 조회(제도 기준, 근해/연안/원양/양식/내수면/기타)
  - locationTag: GFW 이벤트 위치가 12해리 이내(eez12Nm) 비율로 추정
    (행동 기준, 어업허가 정보 없어도 항상 계산 가능)

사용법:
    python tag_population.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from gear_type_categories import category_for

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
MATCHES_PATH = PROCESSED / "final_vessel_matches.jsonl"
EVENTS_PATH = PROCESSED / "gfw_events_normalized.jsonl"
OUT_PATH = PROCESSED / "population_tags.jsonl"

# 이벤트 중 12해리 이내 비율이 이 값 이상이면 "연안(추정)", 아니면 "근해(추정)".
# 잠정값 — 본수집 후 분포 보고 재조정 가능.
COASTAL_RATIO_THRESHOLD = 0.5


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _license_tag(tac: dict) -> tuple:
    if not tac or "gearTypeNamesTac" not in tac:
        return "미확인", []
    categories = sorted({category_for(g) for g in tac["gearTypeNamesTac"]})
    if len(categories) == 1:
        return categories[0], categories
    return "복수업종", categories


def run() -> None:
    matches = {m["gfwVesselId"]: m for m in _load_jsonl(MATCHES_PATH)}
    events = _load_jsonl(EVENTS_PATH)

    events_by_vessel = defaultdict(list)
    for e in events:
        events_by_vessel[e["vesselId"]].append(e)

    results = []
    for vessel_id, vessel_events in events_by_vessel.items():
        n = len(vessel_events)
        n_12nm = sum(1 for e in vessel_events if e["regionsEez12Nm"])
        coastal_ratio = n_12nm / n if n else 0.0
        location_tag = "연안(추정)" if coastal_ratio >= COASTAL_RATIO_THRESHOLD else "근해(추정)"

        match = matches.get(vessel_id)
        license_tag, license_categories = _license_tag(match["tac"] if match else None)

        results.append(
            {
                "gfwVesselId": vessel_id,
                "eventCount": n,
                "coastal12NmRatio": round(coastal_ratio, 3),
                "locationTag": location_tag,
                "licenseTag": license_tag,
                "licenseCategories": license_categories,
                "isAquaculture": license_tag == "양식",
            }
        )

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter

    location_counts = Counter(r["locationTag"] for r in results)
    license_counts = Counter(r["licenseTag"] for r in results)

    print(f"선박 {len(results)}척 태그 완료 -> {OUT_PATH}")
    print(f"locationTag 분포: {dict(location_counts)}")
    print(f"licenseTag 분포: {dict(license_counts)}")
    print("\n샘플 5건:")
    for r in results[:5]:
        print(
            f"  {r['gfwVesselId']}: location={r['locationTag']}(12nm비율 {r['coastal12NmRatio']}) "
            f"license={r['licenseTag']}"
        )


if __name__ == "__main__":
    run()
