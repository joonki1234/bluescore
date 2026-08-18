"""추적 중인 실제 스냅샷의 산출·API·SQLite 캐시 경로를 함께 검증한다."""

from collections import Counter, defaultdict

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from chain.hashing import compute_result_hash
from score.real_axis_b_input import build_axis_b_rows
from score.real_vessel_input import EXCLUDED_GEAR_LABELS
from services.metadata import real_score_run_id, response_metadata
from services.scoring import AXIS_A_WEIGHT, AXIS_B_WEIGHT, ScoringService
from storage.database import Database
from storage.repository import Repository


EXPECTED_STATUSES = {
    "success": 289,
    "partial": 3_395,
    "insufficientSample": 1_630,
    "matchingFailed": 9,
}


@pytest.fixture(scope="module")
def real_snapshot_e2e(tmp_path_factory):
    """무거운 실제 스냅샷 계산을 모듈 전체에서 한 번만 공유한다."""
    db_path = tmp_path_factory.mktemp("real-snapshot-e2e") / "scores.db"
    scoring = ScoringService()
    client = TestClient(
        create_app(db_path, seed_if_empty=False, scoring=scoring)
    )

    health_response = client.get("/health")
    list_response = client.get("/vessels", params={"sourceType": "real"})

    ranked = scoring.real_adapter.status_ranked_vessels()
    vessel_ids_by_status = defaultdict(list)
    for _, vessel, status in ranked:
        vessel_ids_by_status[status].append(vessel["vesselId"])
    representatives = {
        status: sorted(vessel_ids_by_status[status])[0]
        for status in EXPECTED_STATUSES
    }

    score_responses = {
        status: client.get(
            f"/vessels/{vessel_id}/score",
            params={"sourceType": "real"},
        )
        for status, vessel_id in representatives.items()
    }
    unknown_response = client.get(
        "/vessels/UNKNOWN_REAL_VESSEL/score",
        params={"sourceType": "real"},
    )

    vessels = scoring.real_adapter.list_vessels()
    rows = build_axis_b_rows()
    row_counts = {
        "total": len(rows),
        "tonnage": sum(row["tonnageGt"] is not None for row in rows),
        "gear": sum(row["gearType"] is not None for row in rows),
        "both": sum(
            row["tonnageGt"] is not None and row["gearType"] is not None
            for row in rows
        ),
    }
    gear_types = {row["gearType"] for row in rows if row["gearType"] is not None}

    yield {
        "db_path": db_path,
        "health_response": health_response,
        "list_response": list_response,
        "representatives": representatives,
        "score_responses": score_responses,
        "unknown_response": unknown_response,
        "vessels": vessels,
        "status_counts": Counter(status for _, _, status in ranked),
        "row_counts": row_counts,
        "gear_types": gear_types,
    }

    client.close()


def test_tracked_snapshot_counts_and_real_availability(real_snapshot_e2e):
    health = real_snapshot_e2e["health_response"]
    assert health.status_code == 200
    assert health.json()["realAxisASnapshotAvailable"] is True

    vessels = real_snapshot_e2e["vessels"]
    assert len(vessels) == 5_323
    assert sum(vessel["tonnage"] is not None for vessel in vessels) == 1_234
    assert sum(bool(vessel["fishingType"]) for vessel in vessels) == 2_682
    assert sum(
        vessel["tonnage"] is not None and bool(vessel["fishingType"])
        for vessel in vessels
    ) == 665

    assert real_snapshot_e2e["row_counts"] == {
        "total": 275_782,
        "tonnage": 85_985,
        "gear": 147_441,
        "both": 45_305,
    }
    assert real_snapshot_e2e["gear_types"].isdisjoint(EXCLUDED_GEAR_LABELS)
    assert real_snapshot_e2e["status_counts"] == EXPECTED_STATUSES


def test_real_vessel_list_contract_and_order(real_snapshot_e2e):
    response = real_snapshot_e2e["list_response"]
    assert response.status_code == 200
    body = response.json()
    assert body["sourceType"] == "real"
    assert body["vessels"][0]["status"] == "success"
    expected_metadata = response_metadata("real")
    assert {
        "dataSnapshotId": body["dataSnapshotId"],
        "modelVersion": body["modelVersion"],
        "scoringRuleVersion": body["scoringRuleVersion"],
        "rateTableVersion": body["rateTableVersion"],
        "sourceType": body["sourceType"],
    } == {
        "dataSnapshotId": expected_metadata["data_snapshot_id"],
        "modelVersion": expected_metadata["model_version"],
        "scoringRuleVersion": expected_metadata["scoring_rule_version"],
        "rateTableVersion": expected_metadata["rate_table_version"],
        "sourceType": expected_metadata["source_type"],
    }


def test_representative_statuses_use_current_camel_case_contract(real_snapshot_e2e):
    for status, response in real_snapshot_e2e["score_responses"].items():
        assert response.status_code == 200
        body = response.json()
        vessel_id = real_snapshot_e2e["representatives"][status]
        assert body["status"] == status
        assert body["sourceType"] == "real"
        assert body["scoreRunId"] == real_score_run_id(vessel_id)
        assert "score_run_id" not in body

        expected_metadata = response_metadata(
            "real", axis_b_included=status == "success"
        )
        assert body["dataSnapshotId"] == expected_metadata["data_snapshot_id"]
        assert body["modelVersion"] == expected_metadata["model_version"]
        assert body["scoringRuleVersion"] == expected_metadata["scoring_rule_version"]
        assert body["rateTableVersion"] == expected_metadata["rate_table_version"]

    assert real_snapshot_e2e["unknown_response"].status_code == 404


def test_score_invariants_for_each_status(real_snapshot_e2e):
    bodies = {
        status: response.json()
        for status, response in real_snapshot_e2e["score_responses"].items()
    }

    success = bodies["success"]
    assert AXIS_A_WEIGHT == 0.65
    assert AXIS_B_WEIGHT == 0.35
    assert success["axisA"]["score"] is not None
    assert success["axisB"]["score"] is not None
    assert success["blueScore"] == pytest.approx(
        round(
            AXIS_A_WEIGHT * success["axisA"]["score"]
            + AXIS_B_WEIGHT * success["axisB"]["score"],
            1,
        )
    )
    assert success["rateBand"] is not None
    assert success["axisB"]["rawValue"] == pytest.approx(
        success["axisB"]["estimatedFuelKg"]
        - success["axisB"]["expectedFuelKg"]
    )
    assert success["shapFactors"]
    assert all(factor["axis"] == "a" for factor in success["shapFactors"])

    partial = bodies["partial"]
    assert partial["axisA"]["score"] is not None
    assert partial["axisB"]["score"] is None
    assert partial["blueScore"] is None
    assert partial["rateBand"] is None

    insufficient = bodies["insufficientSample"]
    assert insufficient["axisA"]["score"] is None
    assert insufficient["axisB"]["score"] is None
    assert insufficient["blueScore"] is None
    assert insufficient["rateBand"] is None

    matching_failed = bodies["matchingFailed"]
    assert matching_failed["axisA"]["score"] is None
    assert matching_failed["blueScore"] is None
    assert matching_failed["rateBand"] is None
    assert matching_failed["matchingReason"]


def test_api_results_match_sqlite_rows_and_hashes(real_snapshot_e2e):
    repository = Repository(Database(real_snapshot_e2e["db_path"]))

    for status, response in real_snapshot_e2e["score_responses"].items():
        body = response.json()
        stored = repository.get_score_run(body["scoreRunId"])
        assert stored is not None
        assert stored["result"] == body
        assert stored["result_hash"] == compute_result_hash(body)
        assert stored["vessel_id"] == body["vessel"]["vesselId"]
        assert stored["status"] == status
        assert stored["source_type"] == body["sourceType"]
        assert stored["data_snapshot_id"] == body["dataSnapshotId"]
        assert stored["model_version"] == body["modelVersion"]
        assert stored["scoring_rule_version"] == body["scoringRuleVersion"]
        assert stored["rate_table_version"] == body["rateTableVersion"]
        assert stored["blue_score"] == body["blueScore"]
        assert stored["axis_a_score"] == body["axisA"]["score"]
        assert stored["axis_b_score"] == body["axisB"]["score"]
        assert stored["grade"] == (
            body["rateBand"]["grade"] if body["rateBand"] else None
        )
        assert stored["peer_count"] == body["peerGroup"]["count"]


def test_restart_reads_current_scores_without_recalculation(
    real_snapshot_e2e, monkeypatch
):
    restarted_scoring = ScoringService()

    def fail_if_recalculated(*args, **kwargs):
        raise AssertionError("현재 버전의 SQLite 캐시는 다시 계산하면 안 됩니다.")

    monkeypatch.setattr(restarted_scoring, "build_score", fail_if_recalculated)
    restarted_client = TestClient(
        create_app(
            real_snapshot_e2e["db_path"],
            seed_if_empty=False,
            scoring=restarted_scoring,
        )
    )

    try:
        for status, vessel_id in real_snapshot_e2e["representatives"].items():
            response = restarted_client.get(
                f"/vessels/{vessel_id}/score",
                params={"sourceType": "real"},
            )
            assert response.status_code == 200
            assert response.json() == real_snapshot_e2e["score_responses"][status].json()
    finally:
        restarted_client.close()
