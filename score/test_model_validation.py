import json
from types import SimpleNamespace

import pytest

from score.model_validation import (
    audit_rate_table,
    cross_validate_power_law,
    fit_power_law,
    load_tac_power_records,
    peer_parameter_sensitivity,
    physics_sensitivity,
    score_weight_sensitivity,
    split_rows_by_vessel,
    validate_lightgbm_baselines,
)


def _row(vessel_id, tonnage=10.0, speed=5.0, hours=2.0):
    return {
        "vesselId": vessel_id,
        "tonnageGt": tonnage,
        "averageSpeedKnots": speed,
        "durationHours": hours,
    }


def test_tac_loader_deduplicates_and_filters(tmp_path):
    path = tmp_path / "tac.jsonl"
    rows = [
        {"vesselNoTac": "a", "tonnageGtTac": 10, "enginePowerTac": 100},
        {"vesselNoTac": "a", "tonnageGtTac": 10, "enginePowerTac": 100},
        {"vesselNoTac": "b", "tonnageGtTac": 20, "enginePowerTac": 200},
        {"vesselNoTac": "c", "tonnageGtTac": 30, "enginePowerTac": 300},
        {"vesselNoTac": "d", "tonnageGtTac": 40, "enginePowerTac": 400},
        {"vesselNoTac": "bad", "tonnageGtTac": 0, "enginePowerTac": 10},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    records, excluded = load_tac_power_records(path)
    assert {row["vesselId"] for row in records} == {"a", "b", "c", "d"}
    assert excluded["duplicate_vessel"] == 1
    assert excluded["non_positive_or_implausible"] == 1


def test_power_fit_and_cross_validation_are_reproducible():
    records = [
        {"tonnageGt": float(value), "enginePower": 3.0 * value**0.8}
        for value in range(2, 22)
    ]
    fit = fit_power_law(records)
    assert fit.coefficient_a == pytest.approx(3.0)
    assert fit.exponent_b == pytest.approx(0.8)
    assert cross_validate_power_law(records, seed=7) == cross_validate_power_law(records, seed=7)


def test_vessel_split_has_no_leakage_and_fixed_seed():
    rows = [_row("a"), _row("a"), _row("b"), _row("c"), _row("d")]
    first = split_rows_by_vessel(rows, seed=9)
    second = split_rows_by_vessel(rows, seed=9)
    assert first == second
    assert {row["vesselId"] for row in first[0]}.isdisjoint({row["vesselId"] for row in first[1]})


def test_physics_sensitivity_has_expected_direction():
    result = physics_sensitivity([_row("a")])
    assert result["sfoc_170"]["median_change_percent"] < 0
    assert result["sfoc_210"]["median_change_percent"] > 0
    assert result["design_speed_8"]["median_change_percent"] > 0
    assert result["design_speed_12"]["median_change_percent"] < 0


def test_score_weights_and_rate_boundaries():
    sensitivity = score_weight_sensitivity({"a": (100, 0), "b": (0, 100), "c": (70, 70)})
    assert sensitivity["65_35"]["rank_spearman"] == pytest.approx(1.0)
    audit = audit_rate_table([54.9, 55, 68, 78])
    assert audit["thresholds_descending"]
    assert audit["discounts_descending"]
    assert audit["boundary_grades"]["55"] == "C"
    assert audit["boundary_grades"]["68"] == "B"
    assert audit["boundary_grades"]["78"] == "A"


def test_lightgbm_validation_compares_holdout_baselines():
    rows = []
    for index in range(30):
        row = _row(f"v{index}", tonnage=10 + index, speed=4 + index % 5, hours=1 + index % 3)
        row.update({"windSpeedMs": index % 4, "currentSpeedMs": index % 2, "seaSurfaceTempC": 15 + index % 5})
        rows.append(row)
    result = validate_lightgbm_baselines(rows, seed=11)
    assert result["split"]["train_vessels"] == 24
    assert result["split"]["validation_vessels"] == 6
    assert "mean_baseline" in result
    assert "current_with_current" in result["candidates"]


def test_peer_parameter_sensitivity_reports_status_changes():
    vessels = [
        {"vesselId": f"v{index}", "tonnage": 10.0, "fishingType": ["TRAWLERS"]}
        for index in range(10)
    ]
    events = [
        {"vesselId": f"v{index}", "start": "2026-01-01T00:00:00Z", "latitude": 35.0, "longitude": 129.0}
        for index in range(10)
    ]
    axis_a = {
        f"v{index}": SimpleNamespace(axis_a_pressure_raw=float(index))
        for index in range(10)
    }
    axis_b = {
        f"v{index}": SimpleNamespace(used_row_count=1)
        for index in range(10)
    }
    result = peer_parameter_sensitivity(
        vessels,
        events,
        axis_a,
        axis_b,
        band_widths=(10,),
        grid_sizes=(1,),
        minimum_samples=(5, 10, 20),
    )
    assert result["band10_grid1_min10"]["status"]["success"] == 10
    assert result["band10_grid1_min20"]["status"]["insufficientSample"] == 10
