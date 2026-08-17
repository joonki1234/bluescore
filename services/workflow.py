"""담당: 최지희

점수 산출부터 이의제기·심사·해시 기록까지의 업무 흐름.

FastAPI는 이 서비스만 호출하며 SQLite나 계산 모듈을 직접 다루지 않는다.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import ValidationError

from api.schemas import (
    AppealCreate,
    AppealDetail,
    AppealListResponse,
    ChainCommitResponse,
    ChainRecordResponse,
    ConfigResponse,
    ExplanationResponse,
    RateLookupResponse,
    ReviewDecision,
    ReviewDetail,
    ScoreResponse,
    SimulationRequest,
    SimulationResponse,
    SimulationSurfaceResponse,
    TextResponse,
    VesselListResponse,
)
from chain.hashing import compute_result_hash
from chain.ledger import HashLedger, LedgerLike
from services.exceptions import ConflictError, InvalidStateError, NotFoundError
from services.metadata import response_metadata
from services.scoring import ScoringService
from storage.repository import Repository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _metadata_from_score(score: ScoreResponse) -> dict:
    return {
        "data_snapshot_id": score.data_snapshot_id,
        "model_version": score.model_version,
        "scoring_rule_version": score.scoring_rule_version,
        "rate_table_version": score.rate_table_version,
        "source_type": score.source_type,
    }


class WorkflowService:
    def __init__(
        self,
        repository: Repository,
        scoring: Optional[ScoringService] = None,
        ledger: Optional[LedgerLike] = None,
    ) -> None:
        self.repository = repository
        self.scoring = scoring or ScoringService()
        self.ledger = ledger or HashLedger()

    def list_vessels(self, source_type: str = "demo", limit: int = 50) -> VesselListResponse:
        return self.scoring.list_vessels(source_type, limit)

    def config(self) -> ConfigResponse:
        return self.scoring.config()

    def rate_lookup(self, score: float) -> RateLookupResponse:
        return self.scoring.rate_lookup(score)

    def get_score(self, vessel_id: str, source_type: str = "demo") -> ScoreResponse:
        score_run_id = self.scoring.score_run_id(vessel_id, source_type)
        stored = self.repository.get_score_run(score_run_id)
        if stored:
            return ScoreResponse.model_validate(stored["result"])
        score = self.scoring.build_score(vessel_id, source_type)
        self.repository.save_score_run(score.model_dump(mode="json", by_alias=True))
        return score

    def get_score_run(self, score_run_id: str) -> ScoreResponse:
        stored = self.repository.get_score_run(score_run_id)
        if stored is None:
            raise NotFoundError(f"점수 산출 건을 찾을 수 없습니다: {score_run_id}")
        return ScoreResponse.model_validate(stored["result"])

    def simulate(self, vessel_id: str, request: SimulationRequest) -> SimulationResponse:
        self.get_score(vessel_id, "demo")
        return self.scoring.simulate(vessel_id, request)

    def simulation_surface(self, vessel_id: str) -> SimulationSurfaceResponse:
        self.get_score(vessel_id, "demo")
        return self.scoring.simulation_surface(vessel_id)

    def explanation(
        self, vessel_id: str, *, use_llm: bool = False, refresh: bool = False
    ) -> ExplanationResponse:
        score = self.get_score(vessel_id, "demo")
        stored = self.repository.get_score_run(score.score_run_id)
        if stored and stored.get("report") and not refresh:
            try:
                return ExplanationResponse.model_validate(stored["report"])
            except ValidationError:
                # 이전 스키마 캐시는 새 필드가 없을 수 있다. 런타임 LLM을 부르지
                # 않고 현재 계약의 결정론적 폴백으로 안전하게 다시 만든다.
                pass
        report = self.scoring.explain(score, use_llm=use_llm)
        self.repository.save_report(
            score.score_run_id, report.model_dump(mode="json", by_alias=True)
        )
        return report

    def answer_question(self, vessel_id: str, question: str, *, use_llm: bool = False) -> TextResponse:
        self.get_score(vessel_id, "demo")
        return self.scoring.answer_question(vessel_id, question, use_llm=use_llm)

    def submit_appeal(self, request: AppealCreate) -> AppealDetail:
        score = self.get_score_run(request.score_run_id)
        if score.status != "success":
            raise InvalidStateError("완전한 점수가 없는 산출 건에는 이의를 제기할 수 없습니다.")
        now = _utc_now()
        record = {
            "appeal_id": f"appeal-{uuid.uuid4().hex}",
            "score_run_id": score.score_run_id,
            "vessel_id": score.vessel.vessel_id,
            "reason": request.reason,
            "detail": request.detail,
            "status": "submitted",
            "submitted_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        try:
            self.repository.create_appeal(record)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("이의제기를 저장하지 못했습니다.") from exc
        return self._appeal_detail(self.repository.get_appeal(record["appeal_id"]))

    def list_appeals(self, status: Optional[str] = None) -> AppealListResponse:
        items = [self._appeal_detail(row) for row in self.repository.list_appeals(status)]
        # 이의제기가 하나도 없어도 시연 시스템의 버전은 demo로 명시한다.
        return AppealListResponse(appeals=items, **response_metadata("demo"))

    def get_appeal(self, appeal_id: str) -> AppealDetail:
        row = self.repository.get_appeal(appeal_id)
        if row is None:
            raise NotFoundError(f"이의제기를 찾을 수 없습니다: {appeal_id}")
        return self._appeal_detail(row)

    def objection_draft(
        self, appeal_id: str, *, use_llm: bool = False, refresh: bool = False
    ) -> AppealDetail:
        appeal = self.repository.get_appeal(appeal_id)
        if appeal is None:
            raise NotFoundError(f"이의제기를 찾을 수 없습니다: {appeal_id}")
        if appeal.get("ai_response") and not refresh:
            return self._appeal_detail(appeal)
        generated = self.scoring.respond_to_objection(
            appeal["vessel_id"], appeal["reason"], appeal["detail"], use_llm=use_llm
        )
        self.repository.save_appeal_response(appeal_id, generated.text, generated.source)
        return self.get_appeal(appeal_id)

    def review_appeal(self, appeal_id: str, request: ReviewDecision) -> AppealDetail:
        appeal = self.repository.get_appeal(appeal_id)
        if appeal is None:
            raise NotFoundError(f"이의제기를 찾을 수 없습니다: {appeal_id}")
        now = _utc_now()
        review = {
            "review_id": f"review-{uuid.uuid4().hex}",
            "appeal_id": appeal_id,
            "decision": request.decision,
            "reason": request.reason,
            "reviewer": request.reviewer,
            "decided_at": now.isoformat(),
        }
        status = "approved" if request.decision == "approve" else "held"
        try:
            self.repository.save_review(review, status)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        return self.get_appeal(appeal_id)

    def commit_report(self, score_run_id: str) -> ChainCommitResponse:
        existing = self.repository.get_chain_commit_for_score_run(score_run_id)
        if existing:
            return self._chain_response(existing, record_model=ChainCommitResponse)

        score = self.get_score_run(score_run_id)
        reviewed = next(
            (
                appeal
                for appeal in self.repository.list_appeals()
                if appeal["score_run_id"] == score_run_id and appeal.get("review")
            ),
            None,
        )
        if reviewed is None:
            raise InvalidStateError("승인 또는 보류 결정이 저장된 뒤에만 커밋할 수 있습니다.")

        review = reviewed["review"]
        payload = {
            "scoreRunId": score.score_run_id,
            "vesselId": score.vessel.vessel_id,
            "blueScore": score.blue_score,
            "axisA": score.axis_a.score,
            "axisB": score.axis_b.score,
            "decision": review["decision"],
            "dataSnapshotId": score.data_snapshot_id,
            "modelVersion": score.model_version,
            "scoringRuleVersion": score.scoring_rule_version,
            "rateTableVersion": score.rate_table_version,
        }
        result_hash = compute_result_hash(payload)
        record_id = f"BS-{score_run_id}"
        try:
            committed = self.ledger.commit(record_id, result_hash)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc

        record = {
            "record_id": record_id,
            "score_run_id": score_run_id,
            "review_id": review["review_id"],
            "result_hash": result_hash,
            "ledger_mode": committed.ledger_mode,
            "transaction_hash": committed.transaction_hash,
            "block_number": committed.block_number,
            "contract_address": committed.contract_address,
            "committed_at": committed.committed_at.isoformat(),
        }
        try:
            self.repository.save_chain_commit(record)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("이미 커밋된 심사 건입니다.") from exc
        return self._chain_response(record, score=score, record_model=ChainCommitResponse)

    def get_chain_record(self, record_id: str) -> ChainRecordResponse:
        record = self.repository.get_chain_commit(record_id)
        if record is None:
            raise NotFoundError(f"체인 기록을 찾을 수 없습니다: {record_id}")
        if record["ledger_mode"] == "onchain":
            onchain = self.ledger.get(record_id)
            if onchain is None:
                raise NotFoundError(f"온체인 컨트랙트에서 기록을 찾을 수 없습니다: {record_id}")
            record = dict(record)
            record["result_hash"] = onchain.result_hash
            record["committed_at"] = onchain.committed_at.isoformat()
        return self._chain_response(record, record_model=ChainRecordResponse)

    def get_chain_record_for_score_run(self, score_run_id: str) -> ChainRecordResponse:
        record = self.repository.get_chain_commit_for_score_run(score_run_id)
        if record is None:
            raise NotFoundError(f"점수 산출 건의 체인 기록을 찾을 수 없습니다: {score_run_id}")
        return self.get_chain_record(record["record_id"])

    def _appeal_detail(self, row: dict) -> AppealDetail:
        score = self.get_score_run(row["score_run_id"])
        review = row.get("review")
        review_detail = None
        if review:
            review_detail = ReviewDetail(
                review_id=review["review_id"],
                appeal_id=review["appeal_id"],
                decision=review["decision"],
                reason=review["reason"],
                reviewer=review["reviewer"],
                decided_at=review["decided_at"],
            )
        return AppealDetail(
            appeal_id=row["appeal_id"],
            score_run_id=row["score_run_id"],
            vessel_id=row["vessel_id"],
            status=row["status"],
            reason=row["reason"],
            detail=row["detail"],
            submitted_at=row["submitted_at"],
            updated_at=row["updated_at"],
            ai_response=row.get("ai_response") or "",
            ai_response_source=row.get("ai_response_source") or "",
            response_sent_at=row.get("response_sent_at"),
            review=review_detail,
            **_metadata_from_score(score),
        )

    def _chain_response(self, row: dict, *, score=None, record_model):
        score = score or self.get_score_run(row["score_run_id"])
        return record_model(
            record_id=row["record_id"],
            score_run_id=row["score_run_id"],
            review_id=row["review_id"],
            result_hash=row["result_hash"],
            ledger_mode=row["ledger_mode"],
            transaction_hash=row.get("transaction_hash"),
            block_number=row.get("block_number"),
            contract_address=row.get("contract_address"),
            committed_at=row["committed_at"],
            **_metadata_from_score(score),
        )
