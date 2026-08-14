"""
담당: 김준기, 오동규

실제 GFW 데이터로 A축을 선박 1척까지 산출해보는 검증 스크립트.

배경: `explain/TODO.md`(최지희) P0-3 "실산출 1척" — "A축은 GFW 이벤트만 있으면
계산된다"는 게 실제로 되는지, 지금까지 만든 조각(axis_a_pressure.py,
peer_grouping.py, score_assembly.py)을 실제 수집 데이터(data/raw/)에 붙여서
확인한다. 화면에 바로 연결하는 배선은 ui/ 담당(최지희) 몫이라 여기서는 하지 않고,
"된다"는 것만 스크립트로 증명한다.

실행:
    python -m score.scripts.run_real_axis_a
"""

import gzip
import json
import time
from pathlib import Path

from score.axis_a_pressure import compute_axis_a_pressure
from score.peer_grouping import MIN_PEER_GROUP_SAMPLE_SIZE, build_peer_groups, peer_group_for_vessel
from score.score_assembly import raw_to_score, score_status_for_group

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_events_2026-01-01_2026-08-13.jsonl.gz"
VESSELS_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_vessels_enriched.jsonl.gz"


def _load_jsonl_gz(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main() -> None:
    print(f"[1/4] 이벤트 로드: {EVENTS_PATH.name}")
    t0 = time.time()
    events = _load_jsonl_gz(EVENTS_PATH)
    print(f"      {len(events):,}건, {time.time() - t0:.1f}초")

    print(f"[2/4] 선박 로드: {VESSELS_PATH.name}")
    t0 = time.time()
    vessels = _load_jsonl_gz(VESSELS_PATH)
    print(f"      {len(vessels):,}척, {time.time() - t0:.1f}초")

    print("[3/4] A축 raw 값 산출 (compute_axis_a_pressure) — 전체 이벤트 기준")
    t0 = time.time()
    axis_a_results = compute_axis_a_pressure(events)
    print(f"      {len(axis_a_results):,}척 계산됨, {time.time() - t0:.1f}초")

    print("[4/4] 유사 선박군 그룹핑 (build_peer_groups)")
    t0 = time.time()
    groups, vessel_to_key = build_peer_groups(vessels, events)
    print(f"      {len(groups):,}개 그룹, {time.time() - t0:.1f}초")

    # 이벤트가 있고, raw 값이 계산됐고, 유사군에도 속한 선박 중 하나를 예시로 고른다.
    candidate_id = next(
        (vid for vid in axis_a_results if vid in vessel_to_key and axis_a_results[vid].used_event_count > 0),
        None,
    )
    if candidate_id is None:
        print("\n조건에 맞는 선박을 찾지 못했습니다.")
        return

    result = axis_a_results[candidate_id]
    group = peer_group_for_vessel(candidate_id, groups, vessel_to_key)

    print(f"\n=== 선박 {candidate_id} ===")
    print(f"이벤트 사용 건수     : {result.used_event_count}")
    print(f"평균 재방문 간격(h)  : {result.avg_revisit_interval_hours}")
    print(f"재방문압력 raw       : {result.revisit_interval_raw:.4f}")
    print(f"혼잡압력 raw         : {result.crowding_pressure_raw:.4f}")
    print(f"A축 결합 raw         : {result.axis_a_pressure_raw:.4f}")
    print(f"유사군 키            : {group.key if group else None}")
    print(f"유사군 표본 수       : {group.sample_size if group else 0} (기준 {MIN_PEER_GROUP_SAMPLE_SIZE})")

    status = score_status_for_group(group) if group else "insufficientSample"
    print(f"산출 상태            : {status}")

    if status == "success":
        peer_raws = [
            axis_a_results[vid].axis_a_pressure_raw for vid in group.vessel_ids if vid in axis_a_results
        ]
        score = raw_to_score(result.axis_a_pressure_raw, peer_raws)
        print(f"A축 점수 (백분위)    : {score}")
    else:
        print("표본 부족으로 점수 산출 보류 (insufficientSample)")


if __name__ == "__main__":
    main()
