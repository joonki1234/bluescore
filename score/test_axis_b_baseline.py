"""
담당: 김준기, 오동규

score/axis_b_baseline.py 단위 테스트. 실제 데이터 없이 더미 행 리스트로만 검증한다.
"""

import pytest

from score.axis_b_baseline import (
    SkippedRow,
    compute_estimated_fuel_kg,
    compute_axis_b_efficiency,
    compute_residual,
    fit_baseline_model,
    predict_expected_fuel_kg,
)
from score.axis_b_physics import estimate_fuel_consumption


def make_row(
    vessel_id,
    tonnage_gt,
    average_speed_knots,
    duration_hours,
    gear_type="저인망",
    sea_area="동해",
    season="여름",
):
    return {
        "vesselId": vessel_id,
        "tonnageGt": tonnage_gt,
        "gearType": gear_type,
        "seaArea": sea_area,
        "season": season,
        "seaSurfaceTempC": 20.0,
        "windSpeedMs": 5.0,
        "currentSpeedMs": 0.5,
        "averageSpeedKnots": average_speed_knots,
        "totalDistanceKm": average_speed_knots * duration_hours * 1.852,
        "durationHours": duration_hours,
    }


def make_dummy_dataset():
    """톤수/속도가 크게 다른 두 그룹(대형·고속 vs 소형·저속)의 더미 데이터."""
    large_fast = [
        make_row(f"large{i}", tonnage_gt=100.0 + i, average_speed_knots=15.0 + (i % 3), duration_hours=10.0)
        for i in range(8)
    ]
    small_slow = [
        make_row(f"small{i}", tonnage_gt=10.0 + i * 0.5, average_speed_knots=5.0 + (i % 2), duration_hours=10.0)
        for i in range(8)
    ]
    return large_fast, small_slow


class TestComputeEstimatedFuelKg:
    def test_matches_axis_b_physics_directly(self):
        row = make_row("v1", tonnage_gt=50.0, average_speed_knots=10.0, duration_hours=5.0)
        expected = estimate_fuel_consumption(tonnage_gt=50.0, speed_kn=10.0, operating_hours=5.0)
        assert compute_estimated_fuel_kg(row) == expected


class TestComputeResidual:
    def test_positive_when_estimated_exceeds_expected(self):
        assert compute_residual(100.0, 80.0) == 20.0

    def test_negative_when_estimated_below_expected(self):
        assert compute_residual(80.0, 100.0) == -20.0


class TestFitBaselineModel:
    def test_raises_when_no_valid_data(self):
        rows = [{"vesselId": "v1", "tonnageGt": None, "averageSpeedKnots": None, "durationHours": None}]
        with pytest.raises(ValueError):
            fit_baseline_model(rows)

    def test_fits_and_predicts_without_error(self):
        large_fast, small_slow = make_dummy_dataset()
        model, skipped = fit_baseline_model(large_fast + small_slow)

        assert skipped == []
        predictions = predict_expected_fuel_kg(model, large_fast + small_slow)
        assert len(predictions) == len(large_fast) + len(small_slow)
        assert all(p >= 0 for p in predictions)

    def test_large_fast_group_predicted_higher_than_small_slow_group(self):
        large_fast, small_slow = make_dummy_dataset()
        model, _ = fit_baseline_model(large_fast + small_slow)

        large_predictions = predict_expected_fuel_kg(model, large_fast)
        small_predictions = predict_expected_fuel_kg(model, small_slow)

        avg_large = sum(large_predictions) / len(large_predictions)
        avg_small = sum(small_predictions) / len(small_predictions)
        assert avg_large > avg_small


class TestComputeAxisBEfficiency:
    def test_missing_required_feature_is_skipped_with_reason(self):
        large_fast, small_slow = make_dummy_dataset()
        model, _ = fit_baseline_model(large_fast + small_slow)

        rows_with_missing = large_fast + [
            {"vesselId": "incomplete1", "tonnageGt": None, "averageSpeedKnots": 10.0, "durationHours": 5.0}
        ]
        results = compute_axis_b_efficiency(rows_with_missing, model)

        assert results["incomplete1"].used_row_count == 0
        assert len(results["incomplete1"].skipped_rows) == 1
        assert isinstance(results["incomplete1"].skipped_rows[0], SkippedRow)
        assert "missing_required_feature" in results["incomplete1"].skipped_rows[0].reason

    def test_invalid_physics_input_is_skipped_with_reason(self):
        large_fast, small_slow = make_dummy_dataset()
        model, _ = fit_baseline_model(large_fast + small_slow)

        rows_with_invalid = large_fast + [
            make_row("invalid1", tonnage_gt=0.0, average_speed_knots=10.0, duration_hours=5.0)
        ]
        results = compute_axis_b_efficiency(rows_with_invalid, model)

        assert results["invalid1"].used_row_count == 0
        assert "invalid_physics_input" in results["invalid1"].skipped_rows[0].reason

    def test_multiple_events_per_vessel_are_averaged(self):
        large_fast, small_slow = make_dummy_dataset()
        model, _ = fit_baseline_model(large_fast + small_slow)

        repeated_vessel_rows = [
            make_row("repeatv", tonnage_gt=50.0, average_speed_knots=10.0, duration_hours=5.0),
            make_row("repeatv", tonnage_gt=50.0, average_speed_knots=10.0, duration_hours=5.0),
        ]
        results = compute_axis_b_efficiency(repeated_vessel_rows, model)

        assert results["repeatv"].used_row_count == 2
        assert results["repeatv"].residual_raw == pytest.approx(
            compute_residual(results["repeatv"].estimated_fuel_kg, results["repeatv"].expected_fuel_kg)
        )

    def test_end_to_end_pipeline_runs_without_error(self):
        large_fast, small_slow = make_dummy_dataset()
        model, _ = fit_baseline_model(large_fast + small_slow)

        results = compute_axis_b_efficiency(large_fast + small_slow, model)

        assert len(results) == len(large_fast) + len(small_slow)
        for vessel_id, result in results.items():
            assert result.used_row_count == 1
            assert result.estimated_fuel_kg > 0
