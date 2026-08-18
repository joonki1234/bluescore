"""

두 시연 페르소나의 LLM 설명·상세 리포트·개선 팁을 사전 생성해 SQLite에 저장한다.

발표 화면의 GET 요청은 이 캐시를 읽으므로 발표 당일 OpenAI 호출에 의존하지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from explain.recommendation_rules import is_allowed
from explain.render import find_invented_numbers
from services.scoring import ScoringService
from services.workflow import WorkflowService
from storage.database import Database
from storage.repository import Repository


PERSONA_VESSELS = ("VESSEL_A", "VESSEL_B")


def _audit(service: ScoringService, vessel_id: str, report) -> Dict:
    vessel = service._demo_vessel(vessel_id)
    data = service._explain_input(vessel)
    invented = find_invented_numbers(
        " ".join(
            [report.summary]
            + [item.action for item in report.recommendations]
            + [item.sentence for item in report.detailed_report]
        ),
        data,
    )
    allowed = all(is_allowed(data, item) for item in report.recommendations)
    sources: List[str] = [report.explanation_source, report.report_source]
    sources.extend(item.tip_source for item in report.improvement_plans)
    return {
        "vesselId": vessel_id,
        "scoreRunId": report.score_run_id,
        "inventedNumbers": invented,
        "allowedRecommendations": allowed,
        "allSourcesLlm": all(source.startswith("llm:") for source in sources),
        "sources": sources,
        "passed": not invented and allowed and len(report.detailed_report) == len(data.factor_metrics),
    }


def precompute(database: Database, *, use_llm: bool = True) -> List[Dict]:
    scoring = ScoringService()
    workflow = WorkflowService(Repository(database), scoring=scoring)
    audits = []
    for vessel_id in PERSONA_VESSELS:
        workflow.get_score(vessel_id)
        report = workflow.explanation(vessel_id, use_llm=use_llm, refresh=True)
        audits.append(_audit(scoring, vessel_id, report))
    return audits


def main() -> None:
    parser = argparse.ArgumentParser(description="BlueScore 시연 설명 사전 생성·검증")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--fallback-only", action="store_true", help="외부 LLM 없이 템플릿 캐시만 생성"
    )
    parser.add_argument(
        "--allow-fallback", action="store_true", help="실제 LLM 소스가 아니어도 종료코드 0"
    )
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    audits = precompute(Database(args.db), use_llm=not args.fallback_only)
    for audit in audits:
        print(
            f"{audit['vesselId']} · 검증={'통과' if audit['passed'] else '실패'} · "
            f"LLM={'통과' if audit['allSourcesLlm'] else '폴백 포함'} · "
            f"sources={','.join(audit['sources'])}"
        )
    passed = all(item["passed"] for item in audits)
    all_llm = all(item["allSourcesLlm"] for item in audits)
    if not passed or (not args.allow_fallback and not args.fallback_only and not all_llm):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
