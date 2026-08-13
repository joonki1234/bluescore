"""
담당: 김준기, 오동규

data/tac_status_loader.py 단위 테스트. 실제로 커밋되어 있는
data/raw/tac_status.xlsx를 그대로 사용해서 검증한다 (mock 없음).
"""

import pytest

from data.tac_status_loader import list_available_periods, load_tac_status

LATEST_PERIOD = "2023년 7월~2024년 2월 5주"


class TestListAvailablePeriods:
    def test_returns_24_periods_ending_with_latest(self):
        periods = list_available_periods()

        assert len(periods) == 24
        assert periods[-1] == LATEST_PERIOD

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            list_available_periods("data/raw/does_not_exist.xlsx")


class TestLoadTacStatus:
    def test_default_loads_latest_period_and_is_not_empty(self):
        rows = load_tac_status()

        assert len(rows) > 0
        assert all(row["periodLabel"] == LATEST_PERIOD for row in rows)

    def test_species_forward_filled_across_multiple_gear_rows(self):
        rows = load_tac_status()
        squid_rows = [row for row in rows if row["speciesName"] == "오징어"]
        gear_types = {row["gearType"] for row in squid_rows}

        assert len(squid_rows) > 1
        assert len(gear_types) > 1

    def test_numeric_fields_are_numeric(self):
        rows = load_tac_status()
        rows_with_ratio = [row for row in rows if row["consumptionRatioPercent"] is not None]

        assert rows_with_ratio
        for row in rows_with_ratio:
            assert isinstance(row["consumptionRatioPercent"], (int, float))

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_tac_status(file_path="data/raw/does_not_exist.xlsx")

    def test_older_sheet_with_five_column_layout_parses_without_error(self):
        rows = load_tac_status(sheet_name="2016년 1~12월")

        assert len(rows) > 0
        assert all(row["periodLabel"] == "2016년 1~12월" for row in rows)
        squid_rows = [row for row in rows if row["speciesName"] == "오징어"]
        assert len(squid_rows) > 1
