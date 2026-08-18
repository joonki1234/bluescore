"""추적 스냅샷으로 모델·정책 검증 결과를 JSON으로 출력한다.

production 상수나 스냅샷은 변경하지 않는 분석 전용 CLI다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from score.axis_a_pressure import compute_axis_a_pressure
from score.axis_b_baseline import compute_axis_b_efficiency, fit_baseline_model
from score.model_validation import (
    HP_TO_KW,
    PS_TO_KW,
    audit_rate_table,
    axis_a_weight_sensitivity,
    bootstrap_peer_stability,
    cross_validate_power_law,
    evaluate_power_law,
    fit_power_law,
    load_tac_power_records,
    peer_parameter_sensitivity,
    physics_sensitivity,
    score_weight_sensitivity,
    validate_lightgbm_baselines,
)
from score.peer_grouping import build_peer_groups
from score.real_axis_b_input import build_axis_b_rows
from score.real_vessel_input import load_real_vessel_records
from score.score_assembly import raw_to_score
from services.real_scoring import DEFAULT_EVENTS_PATH, _load_jsonl_gz


def run_validation() -> dict:
    tac, excluded = load_tac_power_records()
    fitted = fit_power_law(tac)
    tac_result = {
        "sample_size": len(tac),
        "excluded": dict(excluded),
        "current": asdict(evaluate_power_law(tac, 5.46, 0.70)),
        "fitted": asdict(fitted),
        "fitted_in_sample": asdict(evaluate_power_law(tac, fitted.coefficient_a, fitted.exponent_b)),
        "fitted_cross_validation": asdict(cross_validate_power_law(tac)),
        "unit_sensitivity": {
            "PS_to_kW_coefficient_a": fit_power_law(tac, PS_TO_KW).coefficient_a,
            "HP_to_kW_coefficient_a": fit_power_law(tac, HP_TO_KW).coefficient_a,
            "conversion_difference_percent": (HP_TO_KW / PS_TO_KW - 1) * 100,
        },
    }

    rows = build_axis_b_rows()
    lightgbm = validate_lightgbm_baselines(rows)
    physics = physics_sensitivity(rows, (fitted.coefficient_a, fitted.exponent_b))
    model, _ = fit_baseline_model(rows)
    axis_b_results = compute_axis_b_efficiency(rows, model)

    vessels = load_real_vessel_records()
    events = _load_jsonl_gz(DEFAULT_EVENTS_PATH)
    axis_a_results = compute_axis_a_pressure(events)
    peer = peer_parameter_sensitivity(vessels, events, axis_a_results, axis_b_results)
    groups, vessel_to_key = build_peer_groups(vessels, events)
    a_weights = axis_a_weight_sensitivity(groups, axis_a_results)
    bootstrap = bootstrap_peer_stability(groups, axis_a_results)

    axis_pairs = {}
    for vessel in vessels:
        vessel_id = vessel.get("vesselId")
        if vessel_id not in axis_a_results or vessel_id not in axis_b_results:
            continue
        group = groups[vessel_to_key[vessel_id]]
        a_raws = [axis_a_results[peer_id].axis_a_pressure_raw for peer_id in group.vessel_ids if peer_id in axis_a_results]
        b_raws = [axis_b_results[peer_id].residual_raw for peer_id in group.vessel_ids if peer_id in axis_b_results and axis_b_results[peer_id].used_row_count > 0]
        if len(a_raws) >= 10 and len(b_raws) >= 10 and axis_b_results[vessel_id].used_row_count > 0:
            axis_pairs[vessel_id] = (
                raw_to_score(axis_a_results[vessel_id].axis_a_pressure_raw, a_raws),
                raw_to_score(axis_b_results[vessel_id].residual_raw, b_raws),
            )
    score_weights = score_weight_sensitivity(axis_pairs)
    production_scores = [round(0.65 * pair[0] + 0.35 * pair[1], 1) for pair in axis_pairs.values()]
    baseline_status = peer["band10_grid1_min10"]["status"]
    return {
        "snapshot": {
            "vessels": len(vessels),
            "axis_b_rows": len(rows),
            "tonnage_rows": sum(row.get("tonnageGt") is not None for row in rows),
            "gear_rows": sum(row.get("gearType") is not None for row in rows),
            "tonnage_and_gear_rows": sum(row.get("tonnageGt") is not None and row.get("gearType") is not None for row in rows),
            "status": baseline_status,
        },
        "tac_power": tac_result,
        "lightgbm": lightgbm,
        "physics": physics,
        "peer_parameters": peer,
        "axis_a_weights": a_weights,
        "peer_bootstrap": bootstrap,
        "score_weights": score_weights,
        "rate_table": audit_rate_table(production_scores),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="선택적 JSON 결과 파일")
    args = parser.parse_args()
    result = run_validation()
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
