"""담당: 최지희

점수·이의제기·심사·체인 기록에 대한 SQLite 저장/조회 함수.

화면과 API는 SQL을 직접 알지 않는다. 상태 전이 규칙은 services/workflow.py가
검사하고, 이 모듈은 외래키·중복키를 포함한 영속화만 담당한다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from chain.hashing import compute_result_hash
from storage.database import Database


def _json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    def save_score_run(self, result: Dict[str, Any]) -> None:
        axis_a = result.get("axisA", {})
        axis_b = result.get("axisB", {})
        band = result.get("rateBand") or {}
        peer = result.get("peerGroup") or {}
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO score_runs (
                    score_run_id, vessel_id, status, source_type,
                    data_snapshot_id, model_version, scoring_rule_version,
                    rate_table_version, blue_score, axis_a_score, axis_b_score,
                    grade, peer_count, result_json, result_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(score_run_id) DO UPDATE SET
                    result_json=excluded.result_json,
                    result_hash=excluded.result_hash,
                    status=excluded.status,
                    source_type=excluded.source_type,
                    blue_score=excluded.blue_score,
                    axis_a_score=excluded.axis_a_score,
                    axis_b_score=excluded.axis_b_score,
                    grade=excluded.grade,
                    peer_count=excluded.peer_count
                """,
                (
                    result["scoreRunId"],
                    result["vessel"]["vesselId"],
                    result["status"],
                    result["sourceType"],
                    result["dataSnapshotId"],
                    result["modelVersion"],
                    result["scoringRuleVersion"],
                    result["rateTableVersion"],
                    result.get("blueScore"),
                    axis_a.get("score"),
                    axis_b.get("score"),
                    band.get("grade"),
                    peer.get("count", 0),
                    _json(result),
                    compute_result_hash(result),
                    result["createdAt"],
                ),
            )

    def get_score_run(self, score_run_id: str) -> Optional[Dict[str, Any]]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM score_runs WHERE score_run_id = ?", (score_run_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["report"] = json.loads(result["report_json"]) if result.get("report_json") else None
        return result

    def find_score_run_by_vessel(self, vessel_id: str) -> Optional[Dict[str, Any]]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT score_run_id FROM score_runs
                WHERE vessel_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (vessel_id,),
            ).fetchone()
        return self.get_score_run(row["score_run_id"]) if row else None

    def save_report(self, score_run_id: str, report: Dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE score_runs SET report_json = ?, report_hash = ?,
                    report_source = ?, report_generated_at = ?
                WHERE score_run_id = ?
                """,
                (
                    _json(report), compute_result_hash(report),
                    report.get("explanationSource"), report.get("generatedAt"), score_run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(score_run_id)

    def create_appeal(self, appeal: Dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO appeals (
                    appeal_id, score_run_id, vessel_id, reason, detail,
                    status, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    appeal["appeal_id"],
                    appeal["score_run_id"],
                    appeal["vessel_id"],
                    appeal["reason"],
                    appeal["detail"],
                    appeal["status"],
                    appeal["submitted_at"],
                    appeal["updated_at"],
                ),
            )

    def get_appeal(self, appeal_id: str) -> Optional[Dict[str, Any]]:
        with self.database.connect() as connection:
            appeal = connection.execute(
                "SELECT * FROM appeals WHERE appeal_id = ?", (appeal_id,)
            ).fetchone()
            review = connection.execute(
                "SELECT * FROM reviews WHERE appeal_id = ?", (appeal_id,)
            ).fetchone()
        result = _row_dict(appeal)
        if result is None:
            return None
        result["review"] = _row_dict(review)
        return result

    def list_appeals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT appeal_id FROM appeals"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY submitted_at DESC"
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self.get_appeal(row["appeal_id"]) for row in rows]  # type: ignore[list-item]

    def save_review(self, review: Dict[str, Any], appeal_status: str) -> None:
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT status FROM appeals WHERE appeal_id = ?", (review["appeal_id"],)
            ).fetchone()
            if current is None:
                raise KeyError(review["appeal_id"])
            if current["status"] != "submitted":
                raise ValueError(f"이미 심사된 이의제기입니다: {review['appeal_id']}")
            connection.execute(
                """
                INSERT INTO reviews (
                    review_id, appeal_id, decision, reason, reviewer, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review["review_id"],
                    review["appeal_id"],
                    review["decision"],
                    review["reason"],
                    review["reviewer"],
                    review["decided_at"],
                ),
            )
            connection.execute(
                "UPDATE appeals SET status = ?, updated_at = ? WHERE appeal_id = ?",
                (appeal_status, review["decided_at"], review["appeal_id"]),
            )

    def save_appeal_response(self, appeal_id: str, text: str, source: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE appeals SET ai_response = ?, ai_response_source = ?, updated_at = ?
                WHERE appeal_id = ?
                """,
                (text, source, datetime.now(timezone.utc).isoformat(), appeal_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(appeal_id)

    def save_chain_commit(self, record: Dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO chain_commits (
                    record_id, score_run_id, review_id, result_hash, ledger_mode,
                    transaction_hash, block_number, contract_address, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["record_id"],
                    record["score_run_id"],
                    record["review_id"],
                    record["result_hash"],
                    record["ledger_mode"],
                    record.get("transaction_hash"),
                    record.get("block_number"),
                    record.get("contract_address"),
                    record["committed_at"],
                ),
            )

    def get_chain_commit(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chain_commits WHERE record_id = ?", (record_id,)
            ).fetchone()
        return _row_dict(row)

    def get_chain_commit_for_score_run(self, score_run_id: str) -> Optional[Dict[str, Any]]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chain_commits WHERE score_run_id = ?", (score_run_id,)
            ).fetchone()
        return _row_dict(row)

    def reset_demo(self) -> None:
        """시연 DB만 초기화한다. 원천 데이터 파일에는 접근하지 않는다."""
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM chain_commits")
            connection.execute("DELETE FROM reviews")
            connection.execute("DELETE FROM appeals")
            connection.execute("DELETE FROM score_runs")
