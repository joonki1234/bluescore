"""
담당: 김준기, 오동규

score/tradeoff_coefficients.py 단위 테스트.
"""

import pytest

from score.tradeoff_coefficients import (
    axis_a_pressure_raw_delta_for_revisit_step,
    axis_b_points_per_knot,
    axis_b_points_per_revisit_step,
)


class TestAxisBPointsPerKnot:
    def test_matches_hand_computed_value_at_reference_speed(self):
        # tonnage=50, speed=8->7, operating_hours=5 로 직접 계산한 값과 대조.
        points = axis_b_points_per_knot(tonnage_gt=50.0, current_speed_kn=8.0, operating_hours=5.0)
        assert points == pytest.approx(60.0, abs=1.0)

    def test_slower_current_speed_gives_larger_points_cubic_law(self):
        slow = axis_b_points_per_knot(tonnage_gt=50.0, current_speed_kn=8.0, operating_hours=5.0)
        fast = axis_b_points_per_knot(tonnage_gt=50.0, current_speed_kn=20.0, operating_hours=5.0)
        assert slow > fast

    def test_speed_at_or_below_one_raises(self):
        with pytest.raises(ValueError):
            axis_b_points_per_knot(tonnage_gt=50.0, current_speed_kn=1.0)

    def test_larger_vessel_uses_more_fuel_but_same_relative_saving(self):
        small = axis_b_points_per_knot(tonnage_gt=20.0, current_speed_kn=10.0, operating_hours=5.0)
        large = axis_b_points_per_knot(tonnage_gt=200.0, current_speed_kn=10.0, operating_hours=5.0)
        # 톤수는 speed_load_ratio에 곱해지는 배율일 뿐이라 퍼센트 절감폭(=점수)은
        # 톤수와 무관해야 한다 — 물리식 구조 검증.
        assert small == pytest.approx(large, abs=0.01)


class TestAxisBPointsPerRevisitStep:
    def test_positive_cost(self):
        points = axis_b_points_per_revisit_step(tonnage_gt=50.0, current_speed_kn=10.4, operating_hours=5.0)
        assert points > 0

    def test_slower_speed_means_more_time_to_cover_same_distance_so_higher_cost(self):
        slow = axis_b_points_per_revisit_step(tonnage_gt=50.0, current_speed_kn=6.0, operating_hours=5.0)
        fast = axis_b_points_per_revisit_step(tonnage_gt=50.0, current_speed_kn=15.0, operating_hours=5.0)
        assert slow > fast


class TestAxisAPressureRawDeltaForRevisitStep:
    def test_positive_delta_pressure_decreases_when_revisit_count_drops(self):
        delta = axis_a_pressure_raw_delta_for_revisit_step(period_hours=4380, revisit_count=6)
        assert delta > 0

    def test_revisit_count_of_one_raises(self):
        with pytest.raises(ValueError):
            axis_a_pressure_raw_delta_for_revisit_step(period_hours=4380, revisit_count=1)

    def test_non_positive_period_raises(self):
        with pytest.raises(ValueError):
            axis_a_pressure_raw_delta_for_revisit_step(period_hours=0, revisit_count=5)
