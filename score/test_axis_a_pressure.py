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
        # v1과 크루 5척(c1~c5) 전부 같은 혼잡한 격자를 같은 간격으로 반복
        # 방문한다 — self-exclusion 때문에 "혼자 반복 방문"만으로는 다른 배
        # 밀도가 오히려 낮게 잡히므로(자기 몫이 빠짐), v1이 revisit·congestion
        # 둘 다에서 population 평균보다 높게(z-score 양수) 나오려면 v1처럼
        # 자주 오는 다른 배들이 실제로 여러 척 더 있어야 한다. v2/v3는 아예
        # 동떨어진 격자에 한 번씩만 방문해 두 raw 값 다 낮은 "대조군"이다.
        crowded_cell_events = []
        for vessel_id in ["v1", "c1", "c2", "c3", "c4", "c5"]:
            crowded_cell_events += [
                make_event(f"{vessel_id}-1", vessel_id, "2026-08-01T00:00:00Z", 10.0, 20.0),
                make_event(f"{vessel_id}-2", vessel_id, "2026-08-01T02:00:00Z", 10.0, 20.0),
                make_event(f"{vessel_id}-3", vessel_id, "2026-08-01T04:00:00Z", 10.0, 20.0),
            ]
        isolated_events = [
            make_event("v2-1", "v2", "2026-08-01T00:00:00Z", 50.0, 60.0),
            make_event("v3-1", "v3", "2026-08-01T00:00:00Z", -30.0, -40.0),
        ]
        result = compute_axis_a_pressure(crowded_cell_events + isolated_events)
        v1 = result["v1"]

        # v1이 population 평균보다 재방문·혼잡 둘 다 높다는 전제를 먼저 확인
        assert v1.revisit_zscore > 0.0
        assert v1.crowding_zscore > 0.0

        # axis_a_pressure_raw는 raw가 아니라 z-score로 결합되므로(모듈
        # docstring 참고), "일반 가중합보다 크다"는 비교도 z-score 필드로
        # 해야 한다.
        plain_weighted_sum = 0.5 * v1.revisit_zscore + 0.5 * v1.crowding_zscore
        assert v1.interaction_raw > 0.0
        assert v1.axis_a_pressure_raw > plain_weighted_sum


class TestZScoreNormalization:
    def test_zscores_center_on_population_mean_and_unit_std(self):
        import statistics

        events = [
            # va/vb는 같은 격자를 공유해 서로에게 혼잡압력을 준다(congestion
            # raw 값에 변동이 생기게 하기 위함 — 전부 고립돼 있으면 congestion
            # 이 전부 0이 돼 표준편차 자체가 0인 특수 케이스가 돼버린다).
            make_event("a1", "va", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("a2", "va", "2026-08-01T02:00:00Z", 10.0, 20.0),
            make_event("b1", "vb", "2026-08-01T01:00:00Z", 10.0, 20.0),
            make_event("b2", "vb", "2026-08-01T03:00:00Z", 10.0, 20.0),
            make_event("c1", "vc", "2026-08-01T00:00:00Z", 50.0, 60.0),
        ]
        result = compute_axis_a_pressure(events)
        used = [r for r in result.values() if r.used_event_count > 0]

        revisit_zscores = [r.revisit_zscore for r in used]
        crowding_zscores = [r.crowding_zscore for r in used]

        # population 표준 z-score 성질: 평균은 0, 표준편차는 1(또는 표준편차가
        # 0인 특수 케이스에서만 전부 0) 근처여야 한다.
        assert statistics.mean(revisit_zscores) == pytest.approx(0.0, abs=1e-9)
        assert statistics.pstdev(revisit_zscores) == pytest.approx(1.0, abs=1e-9)
        assert statistics.mean(crowding_zscores) == pytest.approx(0.0, abs=1e-9)
        assert statistics.pstdev(crowding_zscores) == pytest.approx(1.0, abs=1e-9)

    def test_zero_stddev_population_does_not_raise_and_zscores_are_zero(self):
        # 선박이 1척뿐이면(또는 전부 raw 값이 동일하면) population 표준편차가
        # 0이 된다 — ZeroDivisionError 없이 z-score를 0.0으로 처리해야 한다.
        events = [
            make_event("a1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0),
        ]
        result = compute_axis_a_pressure(events)
        v1 = result["v1"]

        assert v1.revisit_zscore == 0.0
        assert v1.crowding_zscore == 0.0
        assert v1.interaction_zscore == 0.0

    def test_vessel_with_no_used_events_has_zero_zscores(self):
        events = [
            make_event("a1", "v1", "2026-08-01T00:00:00Z", 10.0, 20.0),
            make_event("a2", "v2", "2026-08-01T00:00:00Z", None, None),
        ]
        result = compute_axis_a_pressure(events)
        v2 = result["v2"]

        assert v2.used_event_count == 0
        assert v2.revisit_zscore == 0.0
        assert v2.crowding_zscore == 0.0
