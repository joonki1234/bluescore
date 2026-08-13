"""
담당: 김준기, 오동규

score/axis_a_pressure.py 단위 테스트. 실제 GFW API 없이 더미 normalized
event 딕셔너리만으로 검증한다.
"""

import pytest

from score.axis_a_pressure import (
    _grid_cell_for_point,
    _neighbor_cells,
    compute_axis_a_pressure,
    revisit_pressure_from_interval,
)


def make_event(event_id, vessel_id, start, latitude, longitude):
    return {
        "eventId": event_id,
        "vesselId": vessel_id,
        "start": start,
        "end": start,
        "latitude": latitude,
        "longitude": longitude,
        "durationHours": 1.0,
        "averageSpeedKnots": 5.0,
        "totalDistanceKm": 1.0,
        "mpaRelated": False,
        "raw": {},
    }


class TestGridCellForPoint:
    def test_same_cell_for_nearby_points(self):
        assert _grid_cell_for_point(10.01, 20.01, 0.05) == _grid_cell_for_point(10.02, 20.02, 0.05)

    def test_different_cells_far_apart(self):
        assert _grid_cell_for_point(10.0, 20.0, 0.05) != _grid_cell_for_point(11.0, 21.0, 0.05)


class TestNeighborCells:
    def test_distance_one_returns_nine_cells(self):
        neighbors = _neighbor_cells((0, 0), chebyshev_distance=1)
        assert len(neighbors) == 9
        assert (0, 0) in neighbors
        assert (1, 1) in neighbors
        assert (-1, -1) in neighbors


class TestRevisitPressureFromInterval:
    def test_none_interval_returns_zero(self):
        assert revisit_pressure_from_interval(None) == 0.0

    def test_shorter_interval_gives_higher_pressure(self):
        short = revisit_pressure_from_interval(1.0)
        long_ = revisit_pressure_from_interval(100.0)
        assert short > long_

    def test_negative_interval_raises(self):
        with pytest.raises(ValueError):
            revisit_pressure_from_interval(-1.0)


class TestComputeAxisAPressure:
    def test_invalid_cell_size_raises(self):
        with pytest.raises(ValueError):
            compute_axis_a_pressure([], cell_size_deg=0)

    def test_empty_events_returns_empty_dict(self):
        assert compute_axis_a_pressure([]) == {}

    def test_single_event_vessel_has_no_revisit_interval(self):
        events = [make_event("e1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0)]
        result = compute_axis_a_pressure(events)

        assert result["v1"].used_event_count == 1
        assert result["v1"].avg_revisit_interval_hours is None
        assert result["v1"].revisit_interval_raw == 0.0

    def test_missing_coordinates_are_skipped_with_reason(self):
        events = [
            make_event("e1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("e2", "v1", "2026-08-01T06:00:00Z", None, None),
        ]
        result = compute_axis_a_pressure(events)

        assert result["v1"].used_event_count == 1
        assert len(result["v1"].skipped_events) == 1
        assert result["v1"].skipped_events[0].event_id == "e2"
        assert result["v1"].skipped_events[0].reason == "missing_coordinates"

    def test_frequent_revisits_score_higher_than_rare_revisits(self):
        frequent_events = [
            make_event("f1", "frequent", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("f2", "frequent", "2026-08-01T02:00:00Z", 10.0, 20.0),
            make_event("f3", "frequent", "2026-08-01T04:00:00Z", 10.0, 20.0),
        ]
        rare_events = [
            make_event("r1", "rare", "2026-08-01T00:00:00Z", 30.0, 40.0),
            make_event("r2", "rare", "2026-09-01T00:00:00Z", 30.0, 40.0),
            make_event("r3", "rare", "2026-10-01T00:00:00Z", 30.0, 40.0),
        ]
        result = compute_axis_a_pressure(frequent_events + rare_events)

        assert result["frequent"].revisit_interval_raw > result["rare"].revisit_interval_raw

    def test_congested_cell_scores_higher_than_isolated_cell(self):
        # v1 조업 격자에는 다른 두 척(v2, v3)도 함께 조업 -> 밀도가 높다
        congested_events = [
            make_event("c1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("c2", "v2", "2026-08-01T01:00:00Z", 10.0, 20.0),
            make_event("c3", "v3", "2026-08-01T02:00:00Z", 10.0, 20.0),
        ]
        # v4는 아무도 없는 격자에서 홀로 조업 -> 밀도가 낮다
        isolated_events = [
            make_event("i1", "v4", "2026-08-01T00:00:00Z", 50.0, 60.0),
        ]
        result = compute_axis_a_pressure(congested_events + isolated_events)

        assert result["v1"].crowding_pressure_raw > result["v4"].crowding_pressure_raw

    def test_congestion_excludes_own_revisits(self):
        # 다른 배는 하나도 없이, v1 혼자 같은 격자를 5번 반복 방문 ->
        # 혼잡압력은 "다른 배 기준"이므로 0이어야 한다 (자기 자신은 카운트하지 않음).
        solo_events = [
            make_event(f"s{i}", "v1", f"2026-08-0{i + 1}T00:00:00Z", 10.0, 20.0) for i in range(5)
        ]
        result = compute_axis_a_pressure(solo_events)

        assert result["v1"].crowding_pressure_raw == 0.0
        # 재방문압력 자체는 여전히 0보다 커야 한다 (반복 방문 신호는 살아있음)
        assert result["v1"].revisit_interval_raw > 0.0

    def test_interaction_term_amplifies_when_both_signals_high(self):
        # v1: 같은 혼잡한 격자(다른 배 v2, v3 포함)를 짧은 간격으로 반복 방문
        repeated_congested_events = [
            make_event("a1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("a2", "v1", "2026-08-01T02:00:00Z", 10.0, 20.0),
            make_event("a3", "v1", "2026-08-01T04:00:00Z", 10.0, 20.0),
            make_event("a4", "v2", "2026-08-01T00:30:00Z", 10.0, 20.0),
            make_event("a5", "v3", "2026-08-01T01:00:00Z", 10.0, 20.0),
        ]
        result = compute_axis_a_pressure(repeated_congested_events)
        v1 = result["v1"]

        plain_weighted_sum = 0.5 * v1.revisit_interval_raw + 0.5 * v1.crowding_pressure_raw
        assert v1.interaction_raw > 0.0
        assert v1.axis_a_pressure_raw > plain_weighted_sum
