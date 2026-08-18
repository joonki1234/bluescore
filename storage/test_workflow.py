"""담당: 최지희

SQLite 상태 전이와 앱 재시작 복원 테스트.
"""

import json

import pytest

from services.exceptions import ConflictError

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
    # score/tradeoff_coefficients.py의 실제 계수를 반영한 기대값(밴드는 B->A 전환).
    assert simulation.simulated_score == 89.7
    assert simulation.after_band.grade == "A"
    assert score_b.rate_band.grade == "C"
    assert score_a.source_type == "demo"
    assert score_a.data_snapshot_id
    stored = Repository(database).get_score_run(score_a.score_run_id)
    assert stored["result_hash"]


def test_legacy_demo_score_cache_is_upgraded_without_database_reset(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    original = service.get_score("VESSEL_A")

    with database.transaction() as connection:
        row = connection.execute(
            "SELECT result_json FROM score_runs WHERE score_run_id = ?",
            (original.score_run_id,),
        ).fetchone()
        legacy = json.loads(row["result_json"])
        legacy["anchor"] = None
        connection.execute(
            "UPDATE score_runs SET result_json = ? WHERE score_run_id = ?",
            (json.dumps(legacy, ensure_ascii=False), original.score_run_id),
        )

    restarted = WorkflowService(Repository(database))
    upgraded = restarted.get_score("VESSEL_A")
    stored = Repository(database).get_score_run(original.score_run_id)

    assert upgraded.anchor is not None
    assert upgraded.track
    assert stored["result"]["anchor"] == upgraded.anchor


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


def test_이의제기_없이도_심사_결정을_저장하고_커밋한다(tmp_path):
    """여신 심사는 차주가 이의를 제기해야만 열리는 절차가 아니다."""
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    score_run_id = service.get_score("VESSEL_A").score_run_id
    assert service.list_appeals().appeals == []

    review = service.review_score_run(
        score_run_id,
        ReviewDecision(decision="approve", reason="근거 확인 완료", final_discount_bp=20),
    )

    assert review.appeal_id is None
    assert review.final_discount_bp == 20
    assert service.get_review(score_run_id).decision == "approve"

    committed = service.commit_report(score_run_id)
    assert committed.result_hash

    restarted = WorkflowService(Repository(database))
    assert restarted.get_review(score_run_id).reason == "근거 확인 완료"


def test_이의제기가_있으면_같은_심사에_함께_매달린다(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    appeal = service.submit_appeal(
        AppealCreate(score_run_id="demo-score-persona-2-v1", reason="검토 요청", detail="")
    )

    review = service.review_score_run(
        appeal.score_run_id, ReviewDecision(decision="hold", reason="추가 소명 필요")
    )

    assert review.appeal_id == appeal.appeal_id
    # 이의제기 상태도 함께 전이돼야 어업인 화면이 결과를 볼 수 있다.
    assert service.get_appeal(appeal.appeal_id).status == "held"


def test_같은_산출건을_두_번_심사할_수_없다(tmp_path):
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    score_run_id = service.get_score("VESSEL_A").score_run_id
    service.review_score_run(score_run_id, ReviewDecision(decision="approve", reason="1차"))

    with pytest.raises(ConflictError):
        service.review_score_run(score_run_id, ReviewDecision(decision="hold", reason="2차"))


def test_옛_reviews_스키마도_삭제_없이_이전된다(tmp_path):
    """appeal_id NOT NULL이던 기존 instance DB를 지우지 않고 앞으로 옮긴다."""
    database = Database(tmp_path / "legacy.db")
    service = seed_demo(database)
    appeal = service.submit_appeal(
        AppealCreate(score_run_id="demo-score-persona-2-v1", reason="검토", detail="")
    )
    service.review_appeal(appeal.appeal_id, ReviewDecision(decision="hold", reason="보류"))

    # reviews를 옛 모양(score_run_id 없음, appeal_id NOT NULL)으로 되돌린다.
    with database.transaction() as connection:
        connection.execute("DROP INDEX IF EXISTS idx_reviews_score_run")
        connection.execute("ALTER TABLE reviews RENAME TO reviews_new")
        connection.execute(
            """
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY,
                appeal_id TEXT NOT NULL UNIQUE REFERENCES appeals(appeal_id),
                decision TEXT NOT NULL CHECK(decision IN ('approve', 'hold')),
                reason TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decided_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reviews (review_id, appeal_id, decision, reason, reviewer, decided_at)
            SELECT review_id, appeal_id, decision, reason, reviewer, decided_at FROM reviews_new
            """
        )
        connection.execute("DROP TABLE reviews_new")

    migrated = WorkflowService(Repository(database))
    restored = migrated.get_review("demo-score-persona-2-v1")

    assert restored is not None, "기존 심사 기록이 마이그레이션에서 사라졌습니다"
    assert restored.decision == "hold"
    assert restored.appeal_id == appeal.appeal_id


def test_원장에만_기록이_남아_있어도_같은_해시면_커밋이_복구된다(tmp_path):
    """
    시연 중 DB만 리셋하고 API 프로세스를 살려 두면 인메모리 원장에는 기록이
    남는다. 같은 내용이면 커밋은 이미 사실이므로 DB만 맞추고 통과해야 한다.
    """
    from chain.ledger import HashLedger

    ledger = HashLedger()
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    service.ledger = ledger
    score_run_id = service.get_score("VESSEL_A").score_run_id
    service.review_score_run(score_run_id, ReviewDecision(decision="approve", reason="1차"))
    first = service.commit_report(score_run_id)

    # DB의 체인 기록만 지운다(원장은 그대로).
    with database.transaction() as connection:
        connection.execute("DELETE FROM chain_commits")

    recovered = service.commit_report(score_run_id)

    assert recovered.result_hash == first.result_hash
    assert recovered.record_id == first.record_id


def test_원장의_해시가_다르면_커밋을_막는다(tmp_path):
    """기록을 덮어쓰지 않는 것이 이 기능의 존재 이유다."""
    from chain.ledger import HashLedger

    ledger = HashLedger()
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    service.ledger = ledger
    score_run_id = service.get_score("VESSEL_A").score_run_id
    service.review_score_run(score_run_id, ReviewDecision(decision="approve", reason="1차"))

    # 같은 record_id에 다른 해시가 이미 올라가 있는 상황을 만든다.
    ledger._records.clear()
    ledger.commit(f"BS-{score_run_id}", "다른내용의해시")

    with pytest.raises(ConflictError):
        service.commit_report(score_run_id)


def test_마이그레이션이_다른_테이블의_외래키를_망가뜨리지_않는다(tmp_path):
    """
    ALTER TABLE RENAME은 legacy_alter_table 가드가 없으면 다른 테이블의 외래키
    절까지 임시 이름으로 고쳐 쓴다. 그 상태로 임시 테이블을 지우면 chain_commits가
    없는 테이블을 참조하게 되어 삭제·삽입이 전부 죽는다.
    """
    database = Database(tmp_path / "demo.db")
    service = seed_demo(database)
    score_run_id = service.get_score("VESSEL_A").score_run_id
    service.review_score_run(score_run_id, ReviewDecision(decision="approve", reason="확인"))
    service.commit_report(score_run_id)

    with database.connect() as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chain_commits'"
        ).fetchone()["sql"]
    assert "reviews_legacy" not in sql, "외래키가 임시 테이블을 가리키고 있습니다"

    # reset_demo가 chain_commits를 실제로 지울 수 있어야 한다.
    Repository(database).reset_demo()
    assert seed_demo(database).list_appeals().appeals == []
