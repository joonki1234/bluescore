"""담당: 최지희

SQLite 연결과 스키마 초기화.

연결을 호출마다 짧게 열고 닫으므로 FastAPI 요청 스레드가 달라도 같은 connection을
공유하지 않는다. WAL은 앱과 시연 리셋이 겹칠 때 읽기 잠금을 줄이기 위한 설정이다.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "instance" / "bluescore_demo.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: Optional[Path] = None) -> None:
        configured = os.getenv("BLUESCORE_DB_PATH")
        self.path = Path(path or configured or DEFAULT_DB_PATH)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.connect() as connection:
            # 스키마를 적용하기 **전에** 테이블 재작성 마이그레이션을 끝낸다.
            # schema.sql이 reviews(score_run_id)에 인덱스를 걸기 때문에, 옛 모양의
            # 테이블이 남아 있으면 executescript가 "no such column"으로 죽는다.
            self._repair_dangling_review_references(connection)
            self._migrate_reviews_to_score_run(connection)
            connection.executescript(schema)
            # 개발 중 이미 생성된 instance DB도 삭제 없이 앞으로 이동시킨다.
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(score_runs)")
            }
            if "report_hash" not in columns:
                connection.execute("ALTER TABLE score_runs ADD COLUMN report_hash TEXT")
            if "report_source" not in columns:
                connection.execute("ALTER TABLE score_runs ADD COLUMN report_source TEXT")
            if "report_generated_at" not in columns:
                connection.execute("ALTER TABLE score_runs ADD COLUMN report_generated_at TEXT")

            appeal_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(appeals)")
            }
            if "ai_response" not in appeal_columns:
                connection.execute("ALTER TABLE appeals ADD COLUMN ai_response TEXT NOT NULL DEFAULT ''")
            if "ai_response_source" not in appeal_columns:
                connection.execute(
                    "ALTER TABLE appeals ADD COLUMN ai_response_source TEXT NOT NULL DEFAULT ''"
                )
            if "response_sent_at" not in appeal_columns:
                connection.execute("ALTER TABLE appeals ADD COLUMN response_sent_at TEXT")

    @staticmethod
    def _migrate_reviews_to_score_run(connection: sqlite3.Connection) -> None:
        """`reviews`를 이의제기 종속에서 점수 산출 건 종속으로 옮긴다.

        예전 스키마는 `appeal_id NOT NULL`이라 이의제기 없이는 심사 결정을
        저장할 수 없었다. SQLite는 컬럼의 NOT NULL을 떼지 못하므로 테이블을
        새로 만들어 옮긴다. 기존 행의 `score_run_id`는 연결된 이의제기에서
        가져온다.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(reviews)")}
        if not columns or "score_run_id" in columns:
            if columns and "final_discount_bp" not in columns:
                connection.execute("ALTER TABLE reviews ADD COLUMN final_discount_bp INTEGER")
            return

        # legacy_alter_table=ON이 아니면 RENAME이 **다른 테이블의 외래키 절까지**
        # 새 이름으로 고쳐 쓴다. 그러면 chain_commits가 reviews_legacy를 참조하게
        # 되고, 아래에서 그 임시 테이블을 지우는 순간 참조가 끊긴다.
        connection.execute("PRAGMA legacy_alter_table = ON")
        connection.execute("ALTER TABLE reviews RENAME TO reviews_legacy")
        connection.execute(
            """
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY,
                score_run_id TEXT NOT NULL REFERENCES score_runs(score_run_id),
                appeal_id TEXT UNIQUE REFERENCES appeals(appeal_id),
                decision TEXT NOT NULL CHECK(decision IN ('approve', 'hold')),
                reason TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                final_discount_bp INTEGER,
                decided_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reviews (
                review_id, score_run_id, appeal_id, decision, reason, reviewer, decided_at
            )
            SELECT r.review_id, a.score_run_id, r.appeal_id, r.decision, r.reason,
                   r.reviewer, r.decided_at
            FROM reviews_legacy AS r
            JOIN appeals AS a ON a.appeal_id = r.appeal_id
            """
        )
        connection.execute("DROP TABLE reviews_legacy")
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_score_run ON reviews(score_run_id)"
        )

    @staticmethod
    def _repair_dangling_review_references(connection: sqlite3.Connection) -> None:
        """
        `chain_commits`가 사라진 `reviews_legacy`를 참조하는 상태를 되돌린다.

        legacy_alter_table 가드 없이 마이그레이션이 한 번 돌았던 DB가 이 상태가
        된다 — 외래키 절이 임시 테이블 이름으로 바뀐 채 그 테이블이 지워져서,
        `chain_commits`에 쓰거나 지우는 순간 "no such table"로 죽는다.
        """
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chain_commits'"
        ).fetchone()
        if row is None or "reviews_legacy" not in (row["sql"] or ""):
            return

        connection.execute("PRAGMA legacy_alter_table = ON")
        connection.execute("ALTER TABLE chain_commits RENAME TO chain_commits_broken")
        connection.execute(
            """
            CREATE TABLE chain_commits (
                record_id TEXT PRIMARY KEY,
                score_run_id TEXT NOT NULL REFERENCES score_runs(score_run_id),
                review_id TEXT NOT NULL UNIQUE REFERENCES reviews(review_id),
                result_hash TEXT NOT NULL,
                ledger_mode TEXT NOT NULL CHECK(ledger_mode IN ('local', 'onchain')),
                transaction_hash TEXT,
                block_number INTEGER,
                contract_address TEXT,
                committed_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO chain_commits SELECT * FROM chain_commits_broken"
        )
        connection.execute("DROP TABLE chain_commits_broken")
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chain_commits_score_run "
            "ON chain_commits(score_run_id)"
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
