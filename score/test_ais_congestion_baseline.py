"""
담당: 김준기, 오동규

score/ais_congestion_baseline.py 단위 테스트.
"""

from score.ais_congestion_baseline import (
    build_congestion_baseline_by_hour,
    congestion_baseline_for_point,
    find_grid_for_point,
)


def make_row(grid_id, date, hour, count):
    return {"seaGridId": grid_id, "date": date, "hour": hour, "vesselCount": count}


class TestBuildCongestionBaselineByHour:
    def test_averages_across_dates_ignoring_year_and_month(self):
        rows = [
            make_row(100, "2019-10-01", 9, 80),
            make_row(100, "2020-03-15", 9, 120),
        ]
        baseline = build_congestion_baseline_by_hour(rows)
        assert baseline[(100, 9)] == 100.0

    def test_different_grid_or_hour_are_separate_keys(self):
        rows = [
            make_row(100, "2019-10-01", 9, 80),
            make_row(100, "2019-10-01", 10, 40),
            make_row(200, "2019-10-01", 9, 5),
        ]
        baseline = build_congestion_baseline_by_hour(rows)
        assert baseline[(100, 9)] == 80.0
        assert baseline[(100, 10)] == 40.0
        assert baseline[(200, 9)] == 5.0

    def test_skips_rows_with_missing_vessel_count(self):
        rows = [make_row(100, "2019-10-01", 9, 80), make_row(100, "2019-10-02", 9, None)]
        baseline = build_congestion_baseline_by_hour(rows)
        assert baseline[(100, 9)] == 80.0


class TestFindGridForPoint:
    BOUNDARY_LOOKUP = {
        100: {"topLeftLon": 129.0, "topLeftLat": 35.0, "bottomRightLon": 129.5, "bottomRightLat": 34.5},
        200: {"topLeftLon": 128.5, "topLeftLat": 35.5, "bottomRightLon": 129.0, "bottomRightLat": 35.0},
    }

    def test_point_inside_grid(self):
        assert find_grid_for_point(34.8, 129.2, self.BOUNDARY_LOOKUP) == 100

    def test_point_on_boundary_is_inclusive(self):
        assert find_grid_for_point(35.0, 129.0, self.BOUNDARY_LOOKUP) == 100

    def test_point_outside_all_grids_returns_none(self):
        assert find_grid_for_point(10.0, 10.0, self.BOUNDARY_LOOKUP) is None


class TestCongestionBaselineForPoint:
    BOUNDARY_LOOKUP = {
        100: {"topLeftLon": 129.0, "topLeftLat": 35.0, "bottomRightLon": 129.5, "bottomRightLat": 34.5},
    }
    BASELINE = {(100, 9): 80.0}

    def test_returns_baseline_for_known_point_and_hour(self):
        value = congestion_baseline_for_point(34.8, 129.2, 9, self.BASELINE, self.BOUNDARY_LOOKUP)
        assert value == 80.0

    def test_none_when_point_outside_coverage(self):
        value = congestion_baseline_for_point(10.0, 10.0, 9, self.BASELINE, self.BOUNDARY_LOOKUP)
        assert value is None

    def test_none_when_hour_has_no_sample(self):
        value = congestion_baseline_for_point(34.8, 129.2, 3, self.BASELINE, self.BOUNDARY_LOOKUP)
        assert value is None


class TestRealData:
    def test_builds_and_queries_against_committed_ais_file(self):
        from data.ais_location_stats_loader import build_grid_boundary_lookup, load_ais_location_stats

        rows = load_ais_location_stats()
        baseline = build_congestion_baseline_by_hour(rows)
        boundary_lookup = build_grid_boundary_lookup(rows)

        assert len(baseline) > 0
        assert len(boundary_lookup) > 0

        # 실제 로더 첫 행 좌표(부산 인근)로 조회 가능한지 확인.
        value = congestion_baseline_for_point(34.8, 129.2, 0, baseline, boundary_lookup)
        assert value is not None
        assert value > 0
