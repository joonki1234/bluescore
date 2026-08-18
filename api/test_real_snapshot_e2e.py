"""추적 중인 실제 스냅샷의 산출·API·SQLite 캐시 경로를 함께 검증한다."""

from collections import Counter, defaultdict

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from chain.hashing import compute_result_hash
from chain.ledger import HashLedger
from score.real_axis_b_input import build_axis_b_rows
from score.real_vessel_input import EXCLUDED_GEAR_LABELS
from services.metadata import real_score_run_id, response_metadata
from services.scoring import AXIS_A_WEIGHT, AXIS_B_WEIGHT, ScoringService
from storage.database import Database
from storage.repository import Repository


EXPECTED_STATUSES = {
    "success": 73,
    "partial": 3_909,
    "insufficientSample": 1_332,
    "matchingFailed": 9,
}


@pytest.fixture(scope="module")
def real_snapshot_e2e(tmp_path_factory):
    """무거운 실제 스냅샷 계산을 모듈 전체에서 한 번만 공유한다."""
    db_path = tmp_path_factory.mktemp("real-snapshot-e2e") / "scores.db"
    scoring = ScoringService()
    client = TestClient(
        create_app(
            db_path,
            seed_if_empty=False,
            scoring=scoring,
            ledger=HashLedger(),
        )
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
    vessel_by_tier = {
        tier: next(v for v in vessels if v["matchTier"] == tier)
        for tier in ("verified", "unmatched")
    }
    matching_responses = {
        tier: client.get(
            f"/vessels/{vessel['vesselId']}/score",
            params={"sourceType": "real"},
        )
        for tier, vessel in vessel_by_tier.items()
    }
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
        "client": client,
        "scoring": scoring,
        "health_response": health_response,
        "list_response": list_response,
        "representatives": representatives,
        "score_responses": score_responses,
        "unknown_response": unknown_response,
        "vessels": vessels,
        "vessel_by_tier": vessel_by_tier,
        "matching_responses": matching_responses,
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
    assert sum(vessel["tonnage"] is not None for vessel in vessels) == 712
    assert sum(bool(vessel["fishingType"]) for vessel in vessels) == 2_682
    assert sum(
        vessel["tonnage"] is not None and bool(vessel["fishingType"])
        for vessel in vessels
    ) == 368

    assert real_snapshot_e2e["row_counts"] == {
        "total": 275_782,
        "tonnage": 55_608,
        "gear": 147_441,
        "both": 29_249,
    }
    assert real_snapshot_e2e["gear_types"].isdisjoint(EXCLUDED_GEAR_LABELS)
    assert real_snapshot_e2e["status_counts"] == EXPECTED_STATUSES

    evidence = [vessel["matchingEvidence"] for vessel in vessels]
    verified = [item for item in evidence if item["matchTier"] == "verified"]
    unmatched = [item for item in evidence if item["matchTier"] == "unmatched"]
    assert len(verified) == 712
    assert len(unmatched) == 4_611
    assert Counter(item["unmatchedReason"] for item in unmatched) == {
        "held_multi": 1_769,
        "no_korean": 777,
        "unmatched": 2_065,
    }
    distances = [item["distanceKm"] for item in verified]
    assert min(distances) == pytest.approx(0.2206538985869675)
    assert max(distances) == pytest.approx(147.64398951323338)
    assert sum(distances) / len(distances) == pytest.approx(55.41395659349788)


def test_real_vessel_list_contract_and_order(real_snapshot_e2e):
    response = real_snapshot_e2e["list_response"]
    assert response.status_code == 200
    body = response.json()
    assert body["sourceType"] == "real"
    assert body["vessels"][0]["status"] == "success"
    assert len(body["vessels"]) == 50
    assert body["total"] == 5_323
    assert body["statusCounts"] == EXPECTED_STATUSES
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


def test_real_vessel_list_filters_search_and_pagination(real_snapshot_e2e):
    client = real_snapshot_e2e["client"]
    filtered = client.get(
        "/vessels",
        params={"sourceType": "real", "status": "partial", "limit": 7},
    ).json()
    assert filtered["total"] == EXPECTED_STATUSES["partial"]
    assert len(filtered["vessels"]) == 7
    assert {item["status"] for item in filtered["vessels"]} == {"partial"}

    first = client.get(
        "/vessels",
        params={"sourceType": "real", "status": "success", "limit": 5},
    ).json()["vessels"]
    second = client.get(
        "/vessels",
        params={
            "sourceType": "real",
            "status": "success",
            "limit": 5,
            "offset": 5,
        },
    ).json()["vessels"]
    assert {item["vesselId"] for item in first}.isdisjoint(
        item["vesselId"] for item in second
    )

    target = real_snapshot_e2e["vessels"][0]
    by_id = client.get(
        "/vessels",
        params={"sourceType": "real", "query": target["vesselId"].lower()},
    ).json()
    assert any(item["vesselId"] == target["vesselId"] for item in by_id["vessels"])
    if target.get("name"):
        by_name = client.get(
            "/vessels",
            params={"sourceType": "real", "query": target["name"].swapcase()},
        ).json()
        assert any(item["vesselId"] == target["vesselId"] for item in by_name["vessels"])


def test_real_matching_evidence_contract(real_snapshot_e2e):
    verified = real_snapshot_e2e["matching_responses"]["verified"]
    unmatched = real_snapshot_e2e["matching_responses"]["unmatched"]
    assert verified.status_code == 200
    assert unmatched.status_code == 200

    verified_body = verified.json()
    verified_source = real_snapshot_e2e["vessel_by_tier"]["verified"]
    evidence = verified_body["matchingEvidence"]
    assert verified_body["matchingConfidence"] is None
    assert evidence == verified_source["matchingEvidence"]
    assert evidence["confidenceLabel"] == "high"
    assert not isinstance(evidence["confidenceLabel"], (int, float))
    assert evidence["source"] == "TAC"
    assert "vesselNo" not in str(evidence)

    unmatched_evidence = unmatched.json()["matchingEvidence"]
    assert unmatched_evidence["matchTier"] == "unmatched"
    assert unmatched_evidence["unmatchedReason"] in {
        "held_multi",
        "no_korean",
        "unmatched",
    }
    assert unmatched_evidence["matchedName"] is None
    assert unmatched_evidence["distanceKm"] is None
    assert unmatched_evidence["tonnageGt"] is None


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


def test_real_source_type_status_limits_and_simulation_hold(
    real_snapshot_e2e, monkeypatch
):
    monkeypatch.setenv("BLUESCORE_LLM_RUNTIME_ENABLED", "false")
    client = real_snapshot_e2e["client"]

    for status in ("partial", "insufficientSample", "matchingFailed"):
        vessel_id = real_snapshot_e2e["representatives"][status]
        explanation = client.get(
            f"/vessels/{vessel_id}/explanation",
            params={"sourceType": "real"},
        )
        question = client.post(
            f"/vessels/{vessel_id}/questions",
            params={"sourceType": "real"},
            json={"question": "점수 근거를 알려 주세요."},
        )
        assert explanation.status_code == 422
        assert explanation.json()["code"] == "invalid_state"
        assert question.status_code == 422
        assert question.json()["code"] == "invalid_state"
        appeal = client.post(
            "/appeals",
            json={
                "scoreRunId": real_snapshot_e2e["score_responses"][status].json()[
                    "scoreRunId"
                ],
                "reason": "상태 제한 확인",
                "detail": "",
            },
        )
        assert appeal.status_code == 422
        assert appeal.json()["code"] == "invalid_state"

    success_id = real_snapshot_e2e["representatives"]["success"]
    simulation = client.post(
        f"/vessels/{success_id}/simulate",
        params={"sourceType": "real"},
        json={"revisitCount": 2, "speedKnots": 8.0},
    )
    surface = client.get(
        f"/vessels/{success_id}/simulation-surface",
        params={"sourceType": "real"},
    )
    for response in (simulation, surface):
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_state"
        assert "정책 파라미터 검증 전" in response.json()["message"]

    unknown = client.post(
        "/vessels/UNKNOWN_REAL_VESSEL/simulate",
        params={"sourceType": "real"},
        json={"revisitCount": 2, "speedKnots": 8.0},
    )
    assert unknown.status_code == 404
    unknown_explanation = client.get(
        "/vessels/UNKNOWN_REAL_VESSEL/explanation",
        params={"sourceType": "real"},
    )
    assert unknown_explanation.status_code == 404


def test_real_success_workflow_and_restart_caches(
    real_snapshot_e2e, monkeypatch
):
    monkeypatch.setenv("BLUESCORE_LLM_RUNTIME_ENABLED", "false")
    client = real_snapshot_e2e["client"]
    scoring = real_snapshot_e2e["scoring"]
    vessel_id = real_snapshot_e2e["representatives"]["success"]
    score = real_snapshot_e2e["score_responses"]["success"].json()

    explanation_response = client.get(
        f"/vessels/{vessel_id}/explanation",
        params={"sourceType": "real"},
    )
    assert explanation_response.status_code == 200
    explanation = explanation_response.json()
    assert explanation["scoreRunId"] == score["scoreRunId"]
    assert explanation["sourceType"] == "real"
    assert explanation["modelVersion"] == score["modelVersion"]
    assert explanation["dataSnapshotId"] == score["dataSnapshotId"]
    assert explanation["scoringRuleVersion"] == score["scoringRuleVersion"]
    assert explanation["rateTableVersion"] == score["rateTableVersion"]
    assert explanation["shapFactors"]
    assert all(item["axis"] == "a" for item in explanation["shapFactors"])
    assert explanation["detailedReport"] == []
    assert explanation["improvementPlans"] == []
    assert "None" not in explanation["summary"]

    question = client.post(
        f"/vessels/{vessel_id}/questions",
        params={"sourceType": "real"},
        json={"question": "이 점수는 어떤 자료로 계산됐나요?"},
    )
    assert question.status_code == 200
    assert question.json()["sourceType"] == "real"
    assert question.json()["modelVersion"] == score["modelVersion"]

    appeal_response = client.post(
        "/appeals",
        json={
            "scoreRunId": score["scoreRunId"],
            "reason": "실제 산출 근거 확인",
            "detail": "사용된 스냅샷을 검토해 주세요.",
        },
    )
    assert appeal_response.status_code == 201
    appeal = appeal_response.json()
    assert appeal["sourceType"] == "real"

    draft_response = client.post(
        f"/appeals/{appeal['appealId']}/draft-response",
        json={"refresh": False},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["aiResponse"]
    assert draft["sourceType"] == "real"

    def fail_if_objection_is_regenerated(*args, **kwargs):
        raise AssertionError("저장된 이의제기 답변은 다시 생성하면 안 됩니다.")

    monkeypatch.setattr(
        scoring, "respond_to_objection", fail_if_objection_is_regenerated
    )
    cached_draft = client.post(
        f"/appeals/{appeal['appealId']}/draft-response",
        json={"refresh": False},
    )
    assert cached_draft.status_code == 200
    assert cached_draft.json()["aiResponse"] == draft["aiResponse"]

    demo_score = client.get("/vessels/VESSEL_B/score").json()
    demo_appeal = client.post(
        "/appeals",
        json={
            "scoreRunId": demo_score["scoreRunId"],
            "reason": "데모 목록 분리 확인",
            "detail": "",
        },
    ).json()
    real_list = client.get("/appeals", params={"sourceType": "real"}).json()
    demo_list = client.get("/appeals", params={"sourceType": "demo"}).json()
    assert real_list["sourceType"] == "real"
    assert real_list["modelVersion"] == score["modelVersion"]
    assert demo_list["sourceType"] == "demo"
    assert {item["appealId"] for item in real_list["appeals"]} == {
        appeal["appealId"]
    }
    assert {item["appealId"] for item in demo_list["appeals"]} == {
        demo_appeal["appealId"]
    }

    review_response = client.post(
        f"/score-runs/{score['scoreRunId']}/review",
        json={
            "decision": "approve",
            "reason": "실제 산출 근거 확인 완료",
            "reviewer": "심사역 A",
            "finalDiscountBp": score["rateBand"]["discountBp"],
        },
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["scoreRunId"] == score["scoreRunId"]
    assert review["appealId"] == appeal["appealId"]
    assert review["sourceType"] == "real"
    assert review["modelVersion"] == score["modelVersion"]

    commit_response = client.post(f"/reports/{score['scoreRunId']}/commit")
    assert commit_response.status_code == 200
    commit = commit_response.json()
    assert commit["sourceType"] == "real"
    assert commit["modelVersion"] == score["modelVersion"]
    record_response = client.get(f"/chain/records/{commit['recordId']}")
    assert record_response.status_code == 200
    assert record_response.json()["resultHash"] == commit["resultHash"]
    assert record_response.json()["sourceType"] == "real"

    restarted_scoring = ScoringService()

    def fail_if_recalculated(*args, **kwargs):
        raise AssertionError("재시작 후 점수나 설명을 다시 계산하면 안 됩니다.")

    monkeypatch.setattr(restarted_scoring, "build_score", fail_if_recalculated)
    monkeypatch.setattr(restarted_scoring, "explain", fail_if_recalculated)
    restarted_client = TestClient(
        create_app(
            real_snapshot_e2e["db_path"],
            seed_if_empty=False,
            scoring=restarted_scoring,
            ledger=HashLedger(),
        )
    )
    try:
        restored = restarted_client.get(
            f"/vessels/{vessel_id}/explanation",
            params={"sourceType": "real"},
        )
        assert restored.status_code == 200
        assert restored.json() == explanation
    finally:
        restarted_client.close()
