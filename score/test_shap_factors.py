"""
담당: 김준기, 오동규

score/shap_factors.py 단위 테스트.
"""

import pytest

from score.axis_a_pressure import VesselAxisAResult
from score.axis_b_baseline import fit_baseline_model
from score.shap_factors import (
    axis_a_factor_contributions,
    axis_a_factor_shares,
    axis_b_baseline_expected_value,
    axis_b_baseline_factor_contributions,
)
from score.test_axis_b_baseline import make_dummy_dataset


def _make_axis_a_result(revisit_raw=4.0, congestion_raw=3.0):
    interaction_raw = revisit_raw * congestion_raw
    combined = 0.5 * revisit_raw + 0.5 * congestion_raw + 0.1 * interaction_raw
    return VesselAxisAResult(
        vessel_id="v1",
        used_event_count=10,
        revisit_interval_raw=revisit_raw,
        crowding_pressure_raw=congestion_raw,
        interaction_raw=interaction_raw,
        axis_a_pressure_raw=combined,
    )


class TestAxisAFactorContributions:
    def test_returns_three_labeled_factors(self):
        result = _make_axis_a_result()
        factors = axis_a_factor_contributions(result)

        assert len(factors) == 3
        assert {f["label"] for f in factors} == {"재방문압력", "혼잡압력", "재방문×혼잡 상호작용"}
        assert all(f["axis"] == "a" for f in factors)

    def test_contributions_sum_to_axis_a_pressure_raw(self):
        result = _make_axis_a_result(revisit_raw=6.5, congestion_raw=2.1)
        factors = axis_a_factor_contributions(result)

        total = sum(f["raw_contribution"] for f in factors)
        assert total == pytest.approx(result.axis_a_pressure_raw)

    def test_uses_provided_weights_not_just_defaults(self):
        result = _make_axis_a_result(revisit_raw=2.0, congestion_raw=1.0)
        factors = axis_a_factor_contributions(
            result, revisit_weight=1.0, congestion_weight=0.0, interaction_weight=0.0
        )
        by_label = {f["label"]: f["raw_contribution"] for f in factors}

        assert by_label["재방문압력"] == 2.0
        assert by_label["혼잡압력"] == 0.0
        assert by_label["재방문×혼잡 상호작용"] == 0.0


class TestAxisAFactorShares:
    def test_absolute_values_sum_to_about_100_percent(self):
        result = _make_axis_a_result(revisit_raw=6.5, congestion_raw=2.1)
        shares = axis_a_factor_shares(result)

        total_abs = sum(abs(s["value"]) for s in shares)
        assert total_abs == pytest.approx(100.0)

    def test_sign_is_preserved_from_raw_contribution(self):
        result = _make_axis_a_result(revisit_raw=6.5, congestion_raw=2.1)
        shares = {s["label"]: s["value"] for s in axis_a_factor_shares(result)}
        contributions = {c["label"]: c["raw_contribution"] for c in axis_a_factor_contributions(result)}

        for label in shares:
            assert (shares[label] >= 0) == (contributions[label] >= 0)

    def test_returns_value_key_not_raw_contribution_key(self):
        """ShapFactorSchema(**item)에 바로 넣을 수 있어야 하므로 키 이름은
        raw_contribution이 아니라 value여야 한다."""
        result = _make_axis_a_result()
        shares = axis_a_factor_shares(result)

        for share in shares:
            assert "value" in share
            assert "raw_contribution" not in share

    def test_all_zero_raw_values_do_not_divide_by_zero(self):
        result = VesselAxisAResult(
            vessel_id="v1",
            used_event_count=0,
            revisit_interval_raw=0.0,
            crowding_pressure_raw=0.0,
            interaction_raw=0.0,
            axis_a_pressure_raw=0.0,
        )
        shares = axis_a_factor_shares(result)

        assert all(s["value"] == 0.0 for s in shares)


@pytest.fixture(scope="module")
def fitted_model():
    large_fast, small_slow = make_dummy_dataset()
    model, _ = fit_baseline_model(large_fast + small_slow)
    return model, (large_fast + small_slow)[0]


class TestAxisBBaselineFactorContributions:
    def test_returns_one_factor_per_feature_column(self, fitted_model):
        model, row = fitted_model
        factors = axis_b_baseline_factor_contributions(model, row)

        assert len(factors) == 8  # NUMERIC 5 + CATEGORICAL 3
        assert all(f["axis"] == "b" for f in factors)
        assert all("raw_contribution_kg" in f for f in factors)

    def test_labels_are_korean_not_raw_column_names(self, fitted_model):
        model, row = fitted_model
        factors = axis_b_baseline_factor_contributions(model, row)

        labels = {f["label"] for f in factors}
        assert "톤수" in labels
        assert "tonnageGt" not in labels

    def test_additivity_matches_model_prediction(self, fitted_model):
        """SHAP의 기본 성질: 모든 피처 기여도 합 + 기준값 == 모델 예측값.
        연료 물리와 무관하게 항상 성립해야 한다 — 안 맞으면 구현이 잘못된 것."""
        from score.axis_b_baseline import predict_expected_fuel_kg

        model, row = fitted_model
        factors = axis_b_baseline_factor_contributions(model, row)
        base_value = axis_b_baseline_expected_value(model, row)

        total = sum(f["raw_contribution_kg"] for f in factors) + base_value
        predicted = predict_expected_fuel_kg(model, [row])[0]
        assert total == pytest.approx(predicted, abs=1e-6)
