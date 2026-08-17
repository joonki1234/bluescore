"""담당: 최지희

두 시연 페르소나를 FastAPI 경계에서 검증한다.
"""

from fastapi.testclient import TestClient

from api.main import create_app


def _client(tmp_path):
    return TestClient(create_app(tmp_path / "api.db", seed_if_empty=True))


def test_score_contract_uses_camel_case_and_versions(tmp_path):
    client = _client(tmp_path)
    response = client.get("/vessels/VESSEL_A/score")

    assert response.status_code == 200
    body = response.json()
    assert body["scoreRunId"] == "demo-score-persona-1-v1"
    assert body["rateBand"]["grade"] == "B"
    assert body["sourceType"] == "demo"
    assert body["dataSnapshotId"]
    assert body["modelVersion"]
    assert body["scoringRuleVersion"]
    assert body["rateTableVersion"]


def test_persona_one_reaches_a_band(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/vessels/VESSEL_A/simulate",
        json={"revisitCount": 2, "speedKnots": 7.6},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["beforeBand"]["grade"] == "B"
    assert body["afterBand"]["grade"] == "A"
    assert body["simulatedScore"] == 78.0
    assert body["bandChanged"] is True
    assert body["assumptions"]

    surface = client.get("/vessels/VESSEL_A/simulation-surface")
    assert surface.status_code == 200
    assert len(surface.json()["grid"]) == 255
    assert surface.json()["scoreRunId"] == "demo-score-persona-1-v1"


def test_persona_two_appeal_review_commit_and_lookup(tmp_path):
    client = _client(tmp_path)
    score = client.get("/vessels/VESSEL_B/score").json()
    assert score["rateBand"]["grade"] == "C"

    explanation = client.get("/vessels/VESSEL_B/explanation")
    assert explanation.status_code == 200
    assert explanation.json()["detailedReport"]

    created = client.post(
        "/appeals",
        json={
            "scoreRunId": score["scoreRunId"],
            "reason": "동일 해역 반복 조업 판정이 실제와 다름",
            "detail": "기상 대기시간을 확인해 주세요.",
        },
    )
    assert created.status_code == 201
    appeal_id = created.json()["appealId"]
    assert created.json()["scoreRunId"] == score["scoreRunId"]

    listed = client.get("/appeals").json()["appeals"]
    assert listed[0]["scoreRunId"] == score["scoreRunId"]

    drafted = client.post(f"/appeals/{appeal_id}/draft-response", json={"refresh": False})
    assert drafted.status_code == 200
    assert drafted.json()["aiResponse"]

    reviewed = client.post(
        f"/appeals/{appeal_id}/review",
        json={"decision": "approve", "reason": "제출 근거 확인", "reviewer": "심사역 A"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"

    committed = client.post(f"/reports/{score['scoreRunId']}/commit")
    assert committed.status_code == 200
    commit_body = committed.json()
    assert commit_body["ledgerMode"] == "local"
    assert commit_body["transactionHash"] is None

    lookup = client.get(f"/chain/records/{commit_body['recordId']}")
    assert lookup.status_code == 200
    assert lookup.json()["resultHash"] == commit_body["resultHash"]

    by_score_run = client.get(f"/reports/{score['scoreRunId']}/commit")
    assert by_score_run.status_code == 200
    assert by_score_run.json()["recordId"] == commit_body["recordId"]


def test_api_restart_keeps_appeal_state(tmp_path):
    db_path = tmp_path / "api.db"
    first = TestClient(create_app(db_path, seed_if_empty=True))
    created = first.post(
        "/appeals",
        json={
            "scoreRunId": "demo-score-persona-2-v1",
            "reason": "재시작 테스트",
            "detail": "상태가 유지되어야 합니다.",
        },
    ).json()

    second = TestClient(create_app(db_path, seed_if_empty=True))
    restored = second.get(f"/appeals/{created['appealId']}")
    assert restored.status_code == 200
    assert restored.json()["detail"] == "상태가 유지되어야 합니다."


def test_commit_requires_review_and_errors_are_ui_safe(tmp_path):
    client = _client(tmp_path)
    response = client.post("/reports/demo-score-persona-2-v1/commit")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_state"

    missing = client.get("/vessels/UNKNOWN/score")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
