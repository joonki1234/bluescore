"""

데모 또는 실산출 성공 선박의 설명을 사전 생성해 SQLite에 저장한다.

발표 화면의 GET 요청은 이 캐시를 읽으므로 발표 당일 OpenAI 호출에 의존하지 않는다.
기본값은 기존과 동일하게 데모 페르소나 두 척이다. 실산출은 실수로 전체 선박에
LLM을 호출하지 않도록 `--vessel-id` 또는 `--limit`를 반드시 지정한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from dotenv import load_dotenv

from explain.recommendation_rules import is_allowed
from explain.render import find_invented_numbers
from services.scoring import ScoringService
from services.workflow import WorkflowService
from storage.database import Database
from storage.repository import Repository


PERSONA_VESSELS = ("VESSEL_A", "VESSEL_B")


def _audit(service: ScoringService, score, report) -> Dict:
    data = service._explain_input_from_score(score)
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
    llm_sources = [source for source in sources if source != "fallback:no_factor_metrics"]
    metadata_matches = all(
        getattr(report, field) == getattr(score, field)
        for field in (
            "source_type",
            "data_snapshot_id",
            "model_version",
            "scoring_rule_version",
            "rate_table_version",
        )
    )
    return {
        "vesselId": score.vessel.vessel_id,
        "scoreRunId": report.score_run_id,
        "sourceType": report.source_type,
        "status": score.status,
        "skipped": False,
        "inventedNumbers": invented,
        "allowedRecommendations": allowed,
        "allSourcesLlm": all(source.startswith("llm:") for source in llm_sources),
        "sources": sources,
        "passed": (
            not invented
            and allowed
            and metadata_matches
            and report.score_run_id == score.score_run_id
            and len(report.detailed_report) == len(data.factor_metrics)
        ),
    }


def _target_vessel_ids(
    scoring: ScoringService,
    source_type: str,
    vessel_ids: Optional[Sequence[str]],
    limit: Optional[int],
) -> List[str]:
    if source_type not in {"demo", "real"}:
        raise ValueError(f"지원하지 않는 sourceType입니다: {source_type}")
    if limit is not None and limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    explicit = list(dict.fromkeys(vessel_ids or []))
    if source_type == "demo":
        targets = explicit or list(PERSONA_VESSELS)
    elif explicit:
        targets = explicit
    else:
        if limit is None:
            raise ValueError("real 사전 생성에는 --vessel-id 또는 --limit이 필요합니다.")
        targets = [
            vessel["vesselId"]
            for _, vessel, status in scoring.real_adapter.status_ranked_vessels()
            if status == "success"
        ]
    return targets[:limit] if limit is not None else targets


def precompute(
    database: Database,
    *,
    use_llm: bool = True,
    source_type: str = "demo",
    vessel_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    scoring: Optional[ScoringService] = None,
) -> List[Dict]:
    scoring = scoring or ScoringService()
    workflow = WorkflowService(Repository(database), scoring=scoring)
    audits = []
    targets = _target_vessel_ids(scoring, source_type, vessel_ids, limit)
    for vessel_id in targets:
        score = workflow.get_score(vessel_id, source_type)
        if source_type == "real" and score.status != "success":
            audits.append(
                {
                    "vesselId": vessel_id,
                    "scoreRunId": score.score_run_id,
                    "sourceType": source_type,
                    "status": score.status,
                    "skipped": True,
                    "inventedNumbers": [],
                    "allowedRecommendations": True,
                    "allSourcesLlm": True,
                    "sources": [],
                    "passed": True,
                }
            )
            continue
        report = workflow.explanation(
            vessel_id,
            source_type,
            use_llm=use_llm,
            refresh=True,
        )
        audits.append(_audit(scoring, score, report))
    return audits


def main() -> None:
    parser = argparse.ArgumentParser(description="BlueScore 설명 사전 생성·검증")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--source-type", choices=("demo", "real"), default="demo"
    )
    parser.add_argument(
        "--vessel-id",
        action="append",
        dest="vessel_ids",
        help="대상 선박 ID. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="대상 수 제한. real에서 선박 ID를 생략할 때 필수입니다.",
    )
    parser.add_argument(
        "--fallback-only", action="store_true", help="외부 LLM 없이 템플릿 캐시만 생성"
    )
    parser.add_argument(
        "--allow-fallback", action="store_true", help="실제 LLM 소스가 아니어도 종료코드 0"
    )
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    try:
        audits = precompute(
            Database(args.db),
            use_llm=not args.fallback_only,
            source_type=args.source_type,
            vessel_ids=args.vessel_ids,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))
    for audit in audits:
        if audit["skipped"]:
            print(
                f"{audit['vesselId']} · 건너뜀 · status={audit['status']} · "
                "완전한 실산출 점수 없음"
            )
            continue
        print(
            f"{audit['vesselId']} · 검증={'통과' if audit['passed'] else '실패'} · "
            f"LLM={'통과' if audit['allSourcesLlm'] else '폴백 포함'} · "
            f"sources={','.join(audit['sources'])}"
        )
    processed = [item for item in audits if not item["skipped"]]
    passed = bool(processed) and all(item["passed"] for item in processed)
    all_llm = all(item["allSourcesLlm"] for item in processed)
    if not passed or (not args.allow_fallback and not args.fallback_only and not all_llm):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
