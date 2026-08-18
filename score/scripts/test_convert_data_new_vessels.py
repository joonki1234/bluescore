"""
담당: 김준기, 오동규

score/scripts/convert_data_new_vessels.py 단위 테스트.
"""

from score.scripts.convert_data_new_vessels import convert_row


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

    def test_fishing_type_is_always_empty_list(self):
        row = {"gfwVesselId": "V1", "gfwName": "TEST", "tac": None, "mof": None}
        assert convert_row(row)["fishingType"] == []

    def test_vessel_id_comes_from_gfw_vessel_id(self):
        row = {"gfwVesselId": "abc123", "gfwName": "TEST", "tac": None, "mof": None}
        assert convert_row(row)["vesselId"] == "abc123"
