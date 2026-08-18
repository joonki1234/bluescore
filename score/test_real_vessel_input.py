import json

from score.real_vessel_input import (
    DEFAULT_GFW_VESSELS_PATH,
    DEFAULT_MATCHES_PATH,
    convert_row,
    load_gear_types,
    load_real_vessel_records,
)


def test_convert_row_builds_only_the_service_schema():
    row = {
        "gfwVesselId": "V1",
        "gfwName": "TEST",
        "matchTier": "verified",
        "matchConfidence": "high",
        "tac": {"tonnageGtTac": "32"},
        "mof": {"tonnageGtMof": "99"},
    }

    record = convert_row(row, {"V1": ["SET_GILLNETS"]})

    assert record == {
        "vesselId": "V1",
        "name": "TEST",
        "tonnage": 32.0,
        "fishingType": ["SET_GILLNETS"],
        "matchTier": "verified",
        "matchConfidence": "high",
    }


def test_load_gear_types_excludes_non_specific_labels(tmp_path):
    path = tmp_path / "gfw.jsonl"
    row = {
        "vesselId": "V1",
        "combinedGearTypes": [
            "CARGO",
            "PASSENGER",
            "CARRIER",
            "FISHING",
            "OTHER",
            "NA",
            "INCONCLUSIVE",
            "GEAR",
            "FIXED_GEAR",
            "TROLLERS",
            "OTHER_PURSE_SEINES",
            "OTHER_SEINES",
            "SET_GILLNETS",
        ],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert load_gear_types(path) == {"V1": ["SET_GILLNETS"]}


def test_load_real_vessel_records_joins_the_two_sources(tmp_path):
    matches_path = tmp_path / "matches.jsonl"
    gfw_path = tmp_path / "gfw.jsonl"
    matches_path.write_text(
        json.dumps(
            {
                "gfwVesselId": "V1",
                "gfwName": "TEST",
                "matchTier": "verified",
                "matchConfidence": "high",
                "tac": {"tonnageGtTac": "24"},
                "mof": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gfw_path.write_text(
        json.dumps({"vesselId": "V1", "combinedGearTypes": ["POTS_AND_TRAPS"]}) + "\n",
        encoding="utf-8",
    )

    records = load_real_vessel_records(matches_path, gfw_path)

    assert records[0]["vesselId"] == "V1"
    assert records[0]["tonnage"] == 24.0
    assert records[0]["fishingType"] == ["POTS_AND_TRAPS"]


def test_tracked_snapshot_service_record_counts():
    records = load_real_vessel_records(DEFAULT_MATCHES_PATH, DEFAULT_GFW_VESSELS_PATH)

    assert len(records) == 5_323
    assert sum(record["tonnage"] is not None for record in records) == 1_234
    assert sum(bool(record["fishingType"]) for record in records) == 2_682
    assert sum(
        record["tonnage"] is not None and bool(record["fishingType"])
        for record in records
    ) == 665
