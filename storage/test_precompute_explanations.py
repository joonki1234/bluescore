from types import SimpleNamespace

import pytest

from storage.database import Database
from storage import precompute_explanations as subject


class _RankedAdapter:
    def status_ranked_vessels(self):
        return [
            (True, {"vesselId": "S1"}, "success"),
            (False, {"vesselId": "P1"}, "partial"),
            (True, {"vesselId": "S2"}, "success"),
        ]


class _Scoring:
    real_adapter = _RankedAdapter()


def test_demo_targets_remain_the_two_personas_by_default():
    assert subject._target_vessel_ids(_Scoring(), "demo", None, None) == [
        "VESSEL_A",
        "VESSEL_B",
    ]


def test_real_targets_require_an_explicit_id_or_limit():
    with pytest.raises(ValueError, match="--vessel-id 또는 --limit"):
        subject._target_vessel_ids(_Scoring(), "real", None, None)

    assert subject._target_vessel_ids(_Scoring(), "real", None, 1) == ["S1"]


def test_real_precompute_skips_non_success_without_explanation(
    tmp_path, monkeypatch
):
    calls = []

    class FakeWorkflow:
        def __init__(self, repository, scoring):
            pass

        def get_score(self, vessel_id, source_type):
            status = "success" if vessel_id == "S1" else "partial"
            return SimpleNamespace(
                status=status,
                score_run_id=f"run-{vessel_id}",
            )

        def explanation(self, vessel_id, source_type, **kwargs):
            calls.append((vessel_id, source_type, kwargs))
            return SimpleNamespace()

    monkeypatch.setattr(subject, "WorkflowService", FakeWorkflow)
    monkeypatch.setattr(
        subject,
        "_audit",
        lambda scoring, score, report: {
            "vesselId": score.score_run_id.removeprefix("run-"),
            "skipped": False,
            "passed": True,
        },
    )

    audits = subject.precompute(
        Database(tmp_path / "scores.db"),
        use_llm=False,
        source_type="real",
        vessel_ids=["P1", "S1"],
        scoring=_Scoring(),
    )

    assert audits[0]["vesselId"] == "P1"
    assert audits[0]["skipped"] is True
    assert calls == [
        ("S1", "real", {"use_llm": False, "refresh": True})
    ]


def test_audit_checks_real_source_and_version_metadata(monkeypatch):
    metadata = {
        "source_type": "real",
        "data_snapshot_id": "snapshot",
        "model_version": "model",
        "scoring_rule_version": "rule",
        "rate_table_version": "rate",
    }
    score = SimpleNamespace(
        **metadata,
        status="success",
        score_run_id="run-1",
        vessel=SimpleNamespace(vessel_id="V1"),
    )
    report = SimpleNamespace(
        **metadata,
        score_run_id="run-1",
        summary="summary",
        recommendations=[],
        detailed_report=[],
        improvement_plans=[],
        explanation_source="fallback:deterministic",
        report_source="fallback:no_factor_metrics",
    )
    scoring = SimpleNamespace(
        _explain_input_from_score=lambda score: SimpleNamespace(factor_metrics=[])
    )
    monkeypatch.setattr(subject, "find_invented_numbers", lambda text, data: [])

    audit = subject._audit(scoring, score, report)

    assert audit["sourceType"] == "real"
    assert audit["passed"] is True
    assert audit["allSourcesLlm"] is False
