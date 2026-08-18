"""

score/real_axis_b_scoring.py 단위 테스트.
"""

from score.axis_b_baseline import VesselAxisBResult
from score.real_axis_b_scoring import compute_axis_b_results


class TestComputeAxisBResults:
    def test_returns_results_for_real_data_new_snapshot(self):
        results = compute_axis_b_results()
        assert len(results) > 5000
        assert all(isinstance(r, VesselAxisBResult) for r in results.values())

    def test_cached_call_returns_same_object(self):
        first = compute_axis_b_results()
        second = compute_axis_b_results()
        assert first is second

    def test_some_vessels_have_used_rows(self):
        results = compute_axis_b_results()
        used = [r for r in results.values() if r.used_row_count > 0]
        assert len(used) > 2000
