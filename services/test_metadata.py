import pytest

from services.metadata import real_score_run_id, real_score_version_key
from services.scoring import ScoringService


def test_real_score_version_key_is_deterministic():
    assert real_score_version_key() == real_score_version_key()
    assert real_score_run_id("V1") == real_score_run_id("V1")
    assert real_score_run_id("V1") != real_score_run_id("V2")


@pytest.mark.parametrize(
    "component",
    [
        "data_snapshot",
        "partial_model",
        "full_model",
        "scoring_rule",
        "rate_table",
        "pipeline",
    ],
)
def test_every_real_version_component_changes_the_key(component):
    assert real_score_version_key(**{component: "changed"}) != real_score_version_key()


def test_scoring_service_preserves_demo_ids_and_versions_real_ids():
    scoring = ScoringService()

    assert scoring.score_run_id("VESSEL_A", "demo") == "demo-score-persona-1-v1"
    assert scoring.score_run_id("V1", "real") == real_score_run_id("V1")
    assert "20260813" not in scoring.score_run_id("V1", "real")
