from copy import deepcopy

import pytest

from api.schemas import AppealCreate, ReviewDecision
from services.exceptions import ConflictError
from services.metadata import (
    REAL_DATA_SNAPSHOT_ID,
    REAL_MODEL_VERSION_WITH_B,
    RATE_TABLE_VERSION,
    SCORING_RULE_VERSION,
)
from services.scoring import ScoringService
from services.workflow import WorkflowService
from storage.database import Database
from storage.repository import Repository
from storage.seed_demo import seed_demo


def _demo_payload(score_run_id="score-run-test"):
    score = ScoringService().build_score("VESSEL_A")
    payload = score.model_dump(mode="json", by_alias=True)
    payload["scoreRunId"] = score_run_id
    return payload


def _real_score(score_run_id: str):
    score = ScoringService().build_score("VESSEL_A")
    return score.model_copy(
        update={
            "score_run_id": score_run_id,
            "source_type": "real",
            "data_snapshot_id": REAL_DATA_SNAPSHOT_ID,
            "model_version": REAL_MODEL_VERSION_WITH_B,
            "scoring_rule_version": SCORING_RULE_VERSION,
            "rate_table_version": RATE_TABLE_VERSION,
        }
    )


class _FakeScoring:
    def __init__(self, score):
        self.score = score
        self.build_calls = 0

    def score_run_id(self, vessel_id, source_type="demo"):
        return self.score.score_run_id

    def build_score(self, vessel_id, source_type="demo"):
        self.build_calls += 1
        return self.score


def test_score_run_update_syncs_columns_and_invalidates_changed_report(tmp_path):
    repository = Repository(Database(tmp_path / "lifecycle.db"))
    original = _demo_payload()
    repository.save_score_run(original)
    repository.save_report(original["scoreRunId"], {"summary": "old"})

    updated = deepcopy(original)
    updated.update(
        {
            "dataSnapshotId": "snapshot-new",
            "modelVersion": "model-new",
            "scoringRuleVersion": "rule-new",
            "rateTableVersion": "rate-new",
            "createdAt": "2026-08-18T12:00:00+00:00",
            "message": "changed",
        }
    )
    repository.save_score_run(updated)

    stored = repository.get_score_run(original["scoreRunId"])
    assert stored["data_snapshot_id"] == updated["dataSnapshotId"]
    assert stored["model_version"] == updated["modelVersion"]
    assert stored["scoring_rule_version"] == updated["scoringRuleVersion"]
    assert stored["rate_table_version"] == updated["rateTableVersion"]
    assert stored["created_at"] == updated["createdAt"]
    assert stored["result"] == updated
    assert stored["report"] is None
    assert stored["report_hash"] is None


def test_unchanged_score_run_keeps_report_cache(tmp_path):
    repository = Repository(Database(tmp_path / "lifecycle.db"))
    payload = _demo_payload()
    repository.save_score_run(payload)
    repository.save_report(payload["scoreRunId"], {"summary": "keep"})

    repository.save_score_run(deepcopy(payload))

    assert repository.get_score_run(payload["scoreRunId"])["report"] == {
        "summary": "keep"
    }


@pytest.mark.parametrize("audit_stage", ["appeal", "chain"])
def test_audited_score_run_cannot_be_overwritten(tmp_path, audit_stage):
    database = Database(tmp_path / f"{audit_stage}.db")
    service = seed_demo(database)
    score = service.get_score("VESSEL_A")
    if audit_stage == "appeal":
        service.submit_appeal(
            AppealCreate(score_run_id=score.score_run_id, reason="검토", detail="")
        )
    else:
        service.review_score_run(
            score.score_run_id,
            ReviewDecision(decision="approve", reason="확인"),
        )
        service.commit_report(score.score_run_id)

    changed = score.model_dump(mode="json", by_alias=True)
    changed["message"] = "changed"

    with pytest.raises(ValueError, match="감사 기록"):
        service.repository.save_score_run(changed)

    assert service.get_score_run(score.score_run_id).message != "changed"
    if audit_stage == "appeal":
        assert service.list_appeals().appeals
    else:
        assert service.get_review(score.score_run_id) is not None
        assert service.get_chain_record_for_score_run(score.score_run_id)


def test_current_and_historical_score_runs_are_kept_separately(tmp_path):
    repository = Repository(Database(tmp_path / "history.db"))
    historical = _real_score("real-axis-a-VESSEL_A-20260813").model_copy(
        update={"data_snapshot_id": "old-snapshot"}
    )
    repository.save_score_run(historical.model_dump(mode="json", by_alias=True))
    current = _real_score("real-score-VESSEL_A-current")
    scoring = _FakeScoring(current)
    workflow = WorkflowService(repository, scoring=scoring)

    first = workflow.get_score("VESSEL_A", "real")
    second = workflow.get_score("VESSEL_A", "real")
    restored = workflow.get_score_run(historical.score_run_id)

    assert first.score_run_id == current.score_run_id
    assert second.created_at == first.created_at
    assert scoring.build_calls == 1
    assert restored.score_run_id == historical.score_run_id
    assert restored.data_snapshot_id == "old-snapshot"
    assert repository.get_score_run(current.score_run_id)
    assert repository.get_score_run(historical.score_run_id)


def test_stale_current_id_with_audit_is_service_conflict(tmp_path):
    database = Database(tmp_path / "conflict.db")
    repository = Repository(database)
    current = _real_score("real-score-VESSEL_A-current")
    stale = current.model_copy(update={"scoring_rule_version": "old-rule"})
    repository.save_score_run(stale.model_dump(mode="json", by_alias=True))
    repository.create_appeal(
        {
            "appeal_id": "appeal-test",
            "score_run_id": stale.score_run_id,
            "vessel_id": stale.vessel.vessel_id,
            "reason": "검토",
            "detail": "",
            "status": "submitted",
            "submitted_at": "2026-08-18T00:00:00+00:00",
            "updated_at": "2026-08-18T00:00:00+00:00",
        }
    )
    workflow = WorkflowService(repository, scoring=_FakeScoring(current))

    with pytest.raises(ConflictError, match="감사 기록"):
        workflow.get_score("VESSEL_A", "real")
