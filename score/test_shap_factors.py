"""

score/shap_factors.py 단위 테스트.
"""

import pytest

from score.axis_a_pressure import VesselAxisAResult
from score.shap_factors import axis_a_factor_contributions, axis_a_factor_shares


def _make_axis_a_result(revisit_zscore=4.0, congestion_zscore=3.0):
    """axis_a_factor_contributions()는 zscore 필드로 결합값을 재현하므로,
    raw 필드는 (여기서는 안 쓰이지만) 임의의 다른 값으로 채워 raw 필드가
    실수로 쓰이면 테스트가 바로 깨지게 해둔다."""
    interaction_zscore = revisit_zscore * congestion_zscore
    combined = 0.5 * revisit_zscore + 0.5 * congestion_zscore + 0.1 * interaction_zscore
    return VesselAxisAResult(
        vessel_id="v1",
        used_event_count=10,
        revisit_interval_raw=-999.0,
        crowding_pressure_raw=-999.0,
        interaction_raw=-999.0,
        revisit_zscore=revisit_zscore,
        crowding_zscore=congestion_zscore,
        interaction_zscore=interaction_zscore,
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
        result = _make_axis_a_result(revisit_zscore=6.5, congestion_zscore=2.1)
        factors = axis_a_factor_contributions(result)

        total = sum(f["raw_contribution"] for f in factors)
        assert total == pytest.approx(result.axis_a_pressure_raw)

    def test_uses_provided_weights_not_just_defaults(self):
        result = _make_axis_a_result(revisit_zscore=2.0, congestion_zscore=1.0)
        factors = axis_a_factor_contributions(
            result, revisit_weight=1.0, congestion_weight=0.0, interaction_weight=0.0
        )
        by_label = {f["label"]: f["raw_contribution"] for f in factors}

        assert by_label["재방문압력"] == 2.0
        assert by_label["혼잡압력"] == 0.0
        assert by_label["재방문×혼잡 상호작용"] == 0.0


class TestAxisAFactorShares:
    def test_absolute_values_sum_to_about_100_percent(self):
        result = _make_axis_a_result(revisit_zscore=6.5, congestion_zscore=2.1)
        shares = axis_a_factor_shares(result)

        total_abs = sum(abs(s["value"]) for s in shares)
        assert total_abs == pytest.approx(100.0)

    def test_sign_is_preserved_from_raw_contribution(self):
        result = _make_axis_a_result(revisit_zscore=6.5, congestion_zscore=2.1)
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
