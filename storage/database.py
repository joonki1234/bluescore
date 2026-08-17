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
