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
        "tac": {"tonnageGtTac": "32", "nameTac": "테스트호", "vesselNoTac": "SECRET"},
        "mof": {"tonnageGtMof": "99"},
        "distKm": 12.5,
    }

    record = convert_row(row, {"V1": ["SET_GILLNETS"]})

    assert record == {
        "vesselId": "V1",
        "name": "TEST",
        "tonnage": 32.0,
        "fishingType": ["SET_GILLNETS"],
        "matchTier": "verified",
        "matchConfidence": "high",
        "matchingEvidence": {
            "matchTier": "verified",
            "confidenceLabel": "high",
            "source": "TAC",
            "gfwName": "TEST",
            "matchedName": "테스트호",
            "distanceKm": 12.5,
            "tonnageGt": 32.0,
            "tonnageSource": "TAC",
            "fishingTypes": ["SET_GILLNETS"],
            "fishingTypeSource": "GFW",
            "unmatchedReason": None,
        },
    }
    assert "vesselNoTac" not in str(record)


def test_convert_row_keeps_unmatched_reason_without_tac_details():
    record = convert_row(
        {
            "gfwVesselId": "V2",
            "gfwName": "UNKNOWN",
            "matchTier": "unmatched",
            "matchConfidence": None,
            "unmatchedReason": "held_multi",
            "tac": None,
            "mof": None,
        },
        {"V2": ["DRIFTING_LONGLINES"]},
    )

    evidence = record["matchingEvidence"]
    assert evidence["unmatchedReason"] == "held_multi"
    assert evidence["matchedName"] is None
    assert evidence["distanceKm"] is None
    assert evidence["tonnageGt"] is None
    assert evidence["confidenceLabel"] is None
    assert evidence["fishingTypeSource"] == "GFW"


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

    evidence = [record["matchingEvidence"] for record in records]
    verified = [item for item in evidence if item["matchTier"] == "verified"]
    unmatched = [item for item in evidence if item["matchTier"] == "unmatched"]
    assert len(verified) == 1_234
    assert len(unmatched) == 4_089
    assert all(item["confidenceLabel"] == "high" for item in verified)
    assert all(not isinstance(item["confidenceLabel"], float) for item in evidence)
    assert all(item["source"] == "TAC" for item in verified)
    assert all(item["tonnageSource"] == "TAC" for item in verified)
    assert all(item["matchedName"] is None for item in unmatched)
    assert all(item["distanceKm"] is None for item in unmatched)
