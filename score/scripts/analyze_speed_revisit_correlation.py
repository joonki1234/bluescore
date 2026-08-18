"""
담당: 김준기, 오동규

`AXIS_A_COST_PER_KNOT`(속도를 낮추면 자원 압력이 깎인다는 트레이드오프
계수)가 실측 근거가 있는지, data_new/ 데이터로 평균 속도와 평균 재방문
간격의 상관관계를 확인한다. axis_a_pressure.py에는 속도->압력 공식이 없어
이 계수는 원래 추측값이었다 — 상관관계가 없으면 계수를 0에 가깝게 두는
근거로 삼는다.

실행:
    python -m score.scripts.analyze_speed_revisit_correlation
"""

import gzip
import json
from collections import defaultdict
from pathlib import Path

from scipy import stats

from score.axis_a_pressure import compute_axis_a_pressure

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"

MIN_EVENTS_PER_VESSEL = 5  # 평균 속도·재방문 간격이 안정적으로 나오려면 최소 이벤트 수


def _load_jsonl_gz(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def average_speed_by_vessel(events: list) -> dict:
    speeds_by_vessel = defaultdict(list)
    for event in events:
        vessel_id = event.get("vesselId")
        speed = event.get("averageSpeedKnots")
        if vessel_id and speed is not None and speed >= 0:
            speeds_by_vessel[vessel_id].append(speed)

    return {
        vessel_id: sum(speeds) / len(speeds)
        for vessel_id, speeds in speeds_by_vessel.items()
        if len(speeds) >= MIN_EVENTS_PER_VESSEL
    }


def main() -> None:
    print(f"[1/3] 이벤트 로드: {EVENTS_PATH.name}")
    events = _load_jsonl_gz(EVENTS_PATH)
    print(f"      {len(events):,}건")

    print("[2/3] 선박별 평균 속도 · A축 재방문 간격 산출")
    avg_speed = average_speed_by_vessel(events)
    axis_a_results = compute_axis_a_pressure(events)

    pairs = [
        (avg_speed[vessel_id], result.avg_revisit_interval_hours)
        for vessel_id, result in axis_a_results.items()
        if vessel_id in avg_speed and result.avg_revisit_interval_hours is not None
    ]
    print(f"      평균속도·재방문간격 둘 다 있는 선박: {len(pairs)}척 "
          f"(이벤트 {MIN_EVENTS_PER_VESSEL}건 이상 기준)")

    if len(pairs) < 10:
        print("\n표본이 너무 적어 상관분석이 무의미합니다.")
        return

    speeds = [s for s, _ in pairs]
    intervals = [i for _, i in pairs]

    print("\n[3/3] 상관분석 (평균 속도 vs 평균 재방문 간격)")
    pearson_r, pearson_p = stats.pearsonr(speeds, intervals)
    spearman_r, spearman_p = stats.spearmanr(speeds, intervals)
    print(f"  Pearson  r={pearson_r:+.4f}  p={pearson_p:.4f}")
    print(f"  Spearman r={spearman_r:+.4f}  p={spearman_p:.4f}")

    print("\n=== 해석 ===")
    if pearson_p < 0.05 and abs(pearson_r) > 0.1:
        direction = "느릴수록 재방문 간격이 길다(원래 가정과 반대 방향일 수 있음)" if pearson_r > 0 else \
            "느릴수록 재방문 간격이 짧다(원래 가정 — 체류가 길어져 압력 증가 — 과 같은 방향)"
        print(f"  통계적으로 유의미한 상관관계 있음(p<0.05). 방향: {direction}")
    else:
        print("  통계적으로 유의미한 상관관계를 찾지 못함(p>=0.05 또는 |r|<0.1).")
        print("  -> AXIS_A_COST_PER_KNOT을 실측 기반으로 못 만든다는 뜻 — 0에 가깝게")
        print("     두는 쪽이, 근거 없는 비영값을 쓰는 것보다 낫다는 판단을 지지함.")


if __name__ == "__main__":
    main()
