"""담당: 최지희

SQLite 상태 전이와 앱 재시작 복원 테스트.
"""

from api.schemas import AppealCreate, ReviewDecision, SimulationRequest
from services.workflow import WorkflowService
from storage.database import Database
from storage.repository import Repository
from storage.seed_demo import seed_demo


def test_persona_fixtures_are_deterministic(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)

    score_a = service.get_score("VESSEL_A")
    simulation = service.simulate(
        "VESSEL_A", SimulationRequest(revisit_count=2, speed_knots=7.6)
    )
    score_b = service.get_score("VESSEL_B")

    assert score_a.rate_band.grade == "B"
    assert simulation.simulated_score == 78.0
    assert simulation.after_band.grade == "A"
    assert score_b.rate_band.grade == "C"
    assert score_a.source_type == "demo"
    assert score_a.data_snapshot_id
    stored = Repository(database).get_score_run(score_a.score_run_id)
    assert stored["result_hash"]


def test_appeal_review_and_chain_record_survive_restart(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    service.explanation("VESSEL_B")
    stored_score = Repository(database).get_score_run("demo-score-persona-2-v1")
    assert stored_score["report_hash"]
    appeal = service.submit_appeal(
        AppealCreate(
            score_run_id="demo-score-persona-2-v1",
            reason="반복 조업 판정 검토",
            detail="기상 대기시간을 확인해 주세요.",
        )
    )
    reviewed = service.review_appeal(
        appeal.appeal_id,
        ReviewDecision(decision="hold", reason="항차 원자료 추가 확인 필요"),
    )
    committed = service.commit_report(reviewed.score_run_id)

    restarted = WorkflowService(Repository(database))
    restored_appeal = restarted.get_appeal(appeal.appeal_id)
    restored_chain = restarted.get_chain_record(committed.record_id)

    assert restored_appeal.status == "held"
    assert restored_appeal.review.decision == "hold"
    assert restored_chain.result_hash == committed.result_hash
    assert restored_chain.ledger_mode == "local"


def test_seed_reset_restores_initial_state(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    appeal = service.submit_appeal(
        AppealCreate(score_run_id="demo-score-persona-2-v1", reason="검토", detail="")
    )
    assert service.get_appeal(appeal.appeal_id)

    reset_service = seed_demo(database, reset=True)
    assert reset_service.list_appeals().appeals == []
    assert reset_service.get_score("VESSEL_A").rate_band.grade == "B"
