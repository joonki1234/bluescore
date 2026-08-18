"""
담당: 김준기, 오동규

실제 data_new/ 산출물로 요인 기여도(score/shap_factors.py) 계산을 검증하는
스크립트. 화면 연결은 범위 밖 — 여기서는 raw 단위 기여도가 실제로 계산되고,
A축은 axis_a_pressure_raw와 정확히 합이 맞고, B축은 SHAP 가법성이 실제
모델에서도 성립하는지만 증명한다.

실행:
    python -m score.scripts.convert_data_new_vessels  # A축 선박 파일 먼저 생성
    python -m score.scripts.run_shap_factors
"""

import gzip
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from score.axis_a_pressure import compute_axis_a_pressure
from score.axis_b_baseline import compute_axis_b_efficiency, fit_baseline_model, predict_expected_fuel_kg
from score.real_axis_b_input import build_axis_b_rows
from score.shap_factors import (
    axis_a_factor_contributions,
    axis_b_baseline_expected_value,
    axis_b_baseline_factor_contributions,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"


def _load_jsonl_gz(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_axis_a() -> None:
    print("=== A축 요인 기여도 ===")
    events = _load_jsonl_gz(EVENTS_PATH)
    axis_a_results = compute_axis_a_pressure(events)

    candidate_id = next(
        (vid for vid, r in axis_a_results.items() if r.used_event_count > 0), None
    )
    if candidate_id is None:
        print("조건에 맞는 선박을 찾지 못했습니다.")
        return

    result = axis_a_results[candidate_id]
    factors = axis_a_factor_contributions(result)

    print(f"선박 {candidate_id} (이벤트 사용 {result.used_event_count}건)")
    for factor in factors:
        print(f"  {factor['label']:<16} {factor['raw_contribution']:+.4f}")
    total = sum(f["raw_contribution"] for f in factors)
    print(f"  {'합계':<16} {total:+.4f}  (axis_a_pressure_raw = {result.axis_a_pressure_raw:+.4f})")


def run_axis_b() -> None:
    print("\n=== B축 기준선 요인 기여도 ===")
    rows = build_axis_b_rows()
    model, _ = fit_baseline_model(rows)
    results = compute_axis_b_efficiency(rows, model)

    candidate_id = next((vid for vid, r in results.items() if r.used_row_count > 0), None)
    if candidate_id is None:
        print("조건에 맞는 선박을 찾지 못했습니다.")
        return

    example_row = next(row for row in rows if row.get("vesselId") == candidate_id)
    factors = axis_b_baseline_factor_contributions(model, example_row)
    base_value = axis_b_baseline_expected_value(model, example_row)
    predicted = predict_expected_fuel_kg(model, [example_row])[0]

    print(f"선박 {candidate_id}")
    for factor in factors:
        print(f"  {factor['label']:<12} {factor['raw_contribution_kg']:+.4f} kg")
    total = sum(f["raw_contribution_kg"] for f in factors) + base_value
    print(f"  {'기준값':<12} {base_value:+.4f} kg")
    print(f"  {'합계':<12} {total:+.4f} kg  (model 예측 = {predicted:+.4f} kg)")


def main() -> None:
    run_axis_a()
    run_axis_b()


if __name__ == "__main__":
    main()
