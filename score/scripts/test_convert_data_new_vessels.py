"""
담당: 김준기, 오동규

score/scripts/convert_data_new_vessels.py 단위 테스트.
"""

from score.scripts.convert_data_new_vessels import convert_row, load_gear_types


class TestConvertRow:
    def test_prefers_tac_tonnage_over_mof(self):
        row = {
            "gfwVesselId": "V1",
            "gfwName": "TEST",
            "tac": {"tonnageGtTac": "32"},
            "mof": {"tonnageGtMof": "99"},
        }
        assert convert_row(row)["tonnage"] == 32.0

    def test_falls_back_to_mof_tonnage_when_tac_missing(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": {"tonnageGtMof": "19"}}
        assert convert_row(row)["tonnage"] == 19.0

    def test_none_when_neither_source_has_tonnage(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": None}
        assert convert_row(row)["tonnage"] is None

    def test_invalid_tonnage_string_falls_through_to_none(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": {"tonnageGtTac": "미상"}, "mof": None}
        assert convert_row(row)["tonnage"] is None

    def test_fishing_type_is_empty_list_when_no_gear_map_given(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": None}
        assert convert_row(row)["fishingType"] == []

    def test_fishing_type_looked_up_from_gear_map(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": None}
        gear_by_vessel = {"V1": ["SET_GILLNETS"]}
        assert convert_row(row, gear_by_vessel)["fishingType"] == ["SET_GILLNETS"]

    def test_fishing_type_empty_for_vessel_missing_from_gear_map(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": None}
        gear_by_vessel = {"other-vessel": ["SET_GILLNETS"]}
        assert convert_row(row, gear_by_vessel)["fishingType"] == []

    def test_vessel_id_comes_from_gfw_vessel_id(self):
        row = {"gfwVesselId": "abc123", "gfwName": "TEST", "tac": None, "mof": None}
        assert convert_row(row)["vesselId"] == "abc123"


class TestLoadGearTypes:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert load_gear_types(tmp_path / "does-not-exist.jsonl") == {}

    def test_loads_combined_gear_types_by_vessel_id(self, tmp_path):
        path = tmp_path / "gfw_vessels_normalized.jsonl"
        path.write_text(
            '{"vesselId": "V1", "combinedGearTypes": ["SET_GILLNETS"]}\n'
            '{"vesselId": "V2", "combinedGearTypes": ["TRAWLERS"]}\n',
            encoding="utf-8",
        )
        result = load_gear_types(path)
        assert result == {"V1": ["SET_GILLNETS"], "V2": ["TRAWLERS"]}

    def test_excludes_self_contradicting_labels(self, tmp_path):
        path = tmp_path / "gfw_vessels_normalized.jsonl"
        path.write_text(
            '{"vesselId": "V1", "combinedGearTypes": ["CARGO"]}\n'
            '{"vesselId": "V2", "combinedGearTypes": ["TRAWLERS", "PASSENGER"]}\n',
            encoding="utf-8",
        )
        result = load_gear_types(path)
        assert result == {"V1": [], "V2": ["TRAWLERS"]}

    def test_excludes_ambiguous_labels(self, tmp_path):
        path = tmp_path / "gfw_vessels_normalized.jsonl"
        path.write_text(
            '{"vesselId": "V1", "combinedGearTypes": ["FISHING"]}\n'
            '{"vesselId": "V2", "combinedGearTypes": ["FIXED_GEAR", "NA"]}\n'
            '{"vesselId": "V3", "combinedGearTypes": ["TRAWLERS", "FISHING"]}\n',
            encoding="utf-8",
        )
        result = load_gear_types(path)
        assert result == {"V1": [], "V2": [], "V3": ["TRAWLERS"]}

    def test_missing_combined_gear_types_field_becomes_empty_list(self, tmp_path):
        path = tmp_path / "gfw_vessels_normalized.jsonl"
        path.write_text('{"vesselId": "V1"}\n', encoding="utf-8")
        assert load_gear_types(path) == {"V1": []}
