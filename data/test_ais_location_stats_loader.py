"""
담당: 김태윤

data/ais_location_stats_loader.py 단위 테스트. mock 없이 커밋된 원본 TXT를
그대로 읽어서 검증한다. 774,843행이라 모듈 스코프 fixture로 한 번만 읽는다.
"""

import pytest

from data.ais_location_stats_loader import (
    build_grid_boundary_lookup,
    build_vessel_count_index,
    load_ais_location_stats,
)


@pytest.fixture(scope="module")
def stats_rows():
    return load_ais_location_stats()


class TestLoadAisLocationStats:
    def test_row_count_matches_source_file(self, stats_rows):
        assert len(stats_rows) == 774_843

    def test_first_row_matches_known_values(self, stats_rows):
        first = stats_rows[0]
        assert first["seaGridId"] == 100
        assert first["date"] == "2020-01-01"
        assert first["hour"] == 0
        assert first["vesselCount"] == 80
        assert first["topLeftLon"] == 129.0
        assert first["topLeftLat"] == 35.0

    def test_some_rows_have_missing_boundary_as_none(self, stats_rows):
        missing_boundary_rows = [row for row in stats_rows if row["topLeftLon"] is None]
        assert len(missing_boundary_rows) == 4646
        assert all(row["topLeftLat"] is None for row in missing_boundary_rows)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_ais_location_stats("data/raw/does_not_exist.TXT")


class TestBuildVesselCountIndex:
    def test_known_lookup_matches(self, stats_rows):
        index = build_vessel_count_index(stats_rows)
        assert index[(100, "2020-01-01", 0)] == 80

    def test_unknown_key_not_present(self, stats_rows):
        index = build_vessel_count_index(stats_rows)
        assert (999999, "1900-01-01", 0) not in index


class TestBuildGridBoundaryLookup:
    def test_known_grid_boundary(self, stats_rows):
        lookup = build_grid_boundary_lookup(stats_rows)
        assert lookup[100]["topLeftLon"] == 129.0
        assert lookup[100]["bottomRightLat"] == 34.5

    def test_grids_without_any_boundary_are_excluded(self, stats_rows):
        lookup = build_grid_boundary_lookup(stats_rows)
        missing_grid_ids = {row["seaGridId"] for row in stats_rows if row["topLeftLon"] is None}
        grid_ids_with_some_boundary = {row["seaGridId"] for row in stats_rows if row["topLeftLon"] is not None}
        truly_always_missing = missing_grid_ids - grid_ids_with_some_boundary
        assert truly_always_missing.isdisjoint(lookup.keys())
