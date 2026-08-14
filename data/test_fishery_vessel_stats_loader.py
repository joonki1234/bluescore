"""
담당: 김태윤

data/fishery_vessel_stats_loader.py 단위 테스트. mock 없이 실제로 커밋되어
있는 data/raw/해양수산부_수산정보_MR 어업별어선_20240910.csv를 그대로
읽어서 검증한다.
"""

import pytest

from data.fishery_vessel_stats_loader import (
    _normalize_gear_type_name,
    get_gear_type_stats,
    list_gear_type_names,
    load_fishery_vessel_stats,
)


@pytest.fixture(scope="module")
def stats_rows():
    return load_fishery_vessel_stats()


class TestNormalizeGearTypeName:
    def test_strips_internal_spacing(self):
        assert _normalize_gear_type_name("- 근  해   채  낚  기   어  업") == "-근해채낚기어업"

    def test_total_row_normalizes_cleanly(self):
        assert _normalize_gear_type_name("총                          계") == "총계"


class TestLoadFisheryVesselStats:
    def test_row_count_matches_source_file(self, stats_rows):
        assert len(stats_rows) == 1000

    def test_gear_type_names_are_normalized_no_internal_spaces(self, stats_rows):
        for row in stats_rows[:50]:
            assert " " not in row["gearTypeName"]

    def test_sub_category_flag_matches_leading_dash(self, stats_rows):
        sub_category_rows = [row for row in stats_rows if row["isSubCategory"]]
        top_level_rows = [row for row in stats_rows if not row["isSubCategory"]]
        assert sub_category_rows
        assert top_level_rows
        assert all(row["gearTypeName"].startswith("-") for row in sub_category_rows)
        assert all(not row["gearTypeName"].startswith("-") for row in top_level_rows)

    def test_unpowered_vessels_have_no_horsepower_field_but_key_exists(self, stats_rows):
        assert "poweredHorsepower" in stats_rows[0]
        assert "unpoweredVesselCount" in stats_rows[0]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_fishery_vessel_stats("data/raw/does_not_exist.csv")


class TestGetGearTypeStats:
    def test_known_gear_type_and_year_found(self, stats_rows):
        result = get_gear_type_stats(stats_rows, gear_type_name="총계", year=2020)
        assert result is not None
        assert result["totalVesselCount"] is not None

    def test_unknown_combination_returns_none(self, stats_rows):
        assert get_gear_type_stats(stats_rows, gear_type_name="존재하지않는업종", year=2020) is None


class TestListGearTypeNames:
    def test_returns_unique_sorted_names(self, stats_rows):
        names = list_gear_type_names(stats_rows)
        assert names == sorted(set(names))
        assert "총계" in names
