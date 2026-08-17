"""담당: 최지희

두 페르소나의 초기 점수 상태를 반복 생성한다.

이 스크립트가 지우는 범위는 BLUESCORE_DB_PATH 또는 기본 instance DB의 업무 테이블
뿐이다. data/raw의 원천 스냅샷은 읽거나 삭제하지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from services.scoring import ScoringService
from services.workflow import WorkflowService
from storage.database import Database
from storage.repository import Repository


def seed_demo(database: Database, *, reset: bool = True) -> WorkflowService:
    repository = Repository(database)
    if reset:
        repository.reset_demo()
    service = WorkflowService(repository=repository, scoring=ScoringService())
    service.get_score("VESSEL_A")
    service.get_score("VESSEL_B")
    return service


def main() -> None:
    parser = argparse.ArgumentParser(description="BlueScore 시연 SQLite 초기화")
    parser.add_argument("--db", type=Path, default=None, help="기본값: instance/bluescore_demo.db")
    parser.add_argument("--no-reset", action="store_true", help="기존 업무 데이터를 지우지 않음")
    args = parser.parse_args()
    database = Database(args.db)
    seed_demo(database, reset=not args.no_reset)
    print(f"시연 DB 준비 완료: {database.path}")


if __name__ == "__main__":
    main()
