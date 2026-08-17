"""담당: 최지희

BlueScore FastAPI 애플리케이션.

실행:
    uvicorn api.main:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.schemas import (
    AppealCreate,
    AppealDetail,
    AppealListResponse,
    ChainCommitResponse,
    ChainRecordResponse,
    ConfigResponse,
    ErrorResponse,
    ExplanationResponse,
    ObjectionDraftRequest,
    QuestionRequest,
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
from services.exceptions import (
    BackendUnavailableError,
    ConflictError,
    InvalidStateError,
    NotFoundError,
    ServiceError,
)
from services.scoring import ScoringService
from services.workflow import WorkflowService
from chain.ledger import HashLedger, LedgerLike, OnChainHashLedger
from storage.database import Database
from storage.repository import Repository


def _runtime_llm_enabled() -> bool:
    return os.getenv("BLUESCORE_LLM_RUNTIME_ENABLED", "false").lower() in {"1", "true", "yes"}


def _configured_ledger() -> LedgerLike:
    mode = os.getenv("BLUESCORE_CHAIN_MODE", "local").lower()
    if mode == "onchain":
        return OnChainHashLedger()
    return HashLedger()


def create_app(
    db_path: Optional[Path] = None, *, seed_if_empty: bool = True,
    ledger: Optional[LedgerLike] = None,
) -> FastAPI:
    database = Database(db_path)
    repository = Repository(database)
    scoring = ScoringService()
    workflow = WorkflowService(repository=repository, scoring=scoring, ledger=ledger or _configured_ledger())

    if seed_if_empty:
        # 삭제 없이 초기 점수만 보장한다. 이의제기·심사·체인 기록은 보존된다.
        workflow.get_score("VESSEL_A")
        workflow.get_score("VESSEL_B")

    api = FastAPI(
        title="BlueScore API",
        version="0.1.0",
        description="가명 시연 선박과 버전 고정 실데이터 A축을 제공하는 REST API",
    )
    api.state.database = database
    api.state.workflow = workflow

    @api.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        status = 500
        if isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, ConflictError):
            status = 409
        elif isinstance(exc, InvalidStateError):
            status = 422
        elif isinstance(exc, BackendUnavailableError):
            status = 503
        payload = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=status, content=payload.model_dump(mode="json", by_alias=True))

    @api.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = ErrorResponse(
            code="validation_error",
            message="요청 값이 API 계약과 맞지 않습니다.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=422, content=payload.model_dump(mode="json", by_alias=True))

    @api.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "database": str(database.path),
            "realAxisASnapshotAvailable": scoring.real_adapter.available,
            "chainMode": "onchain" if isinstance(workflow.ledger, OnChainHashLedger) else "local",
            "runtimeLlmEnabled": _runtime_llm_enabled(),
        }

    @api.get("/config", response_model=ConfigResponse)
    def config() -> ConfigResponse:
        return workflow.config()

    @api.get("/rates/lookup", response_model=RateLookupResponse)
    def rate_lookup(score: float = Query(ge=0, le=100)) -> RateLookupResponse:
        return workflow.rate_lookup(score)

    @api.get("/vessels", response_model=VesselListResponse)
    def list_vessels(
        source_type: str = Query(default="demo", alias="sourceType", pattern="^(demo|real)$"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> VesselListResponse:
        return workflow.list_vessels(source_type, limit)

    @api.get("/vessels/{vessel_id}/score", response_model=ScoreResponse)
    def get_score(
        vessel_id: str,
        source_type: str = Query(default="demo", alias="sourceType", pattern="^(demo|real)$"),
    ) -> ScoreResponse:
        return workflow.get_score(vessel_id, source_type)

    @api.post("/vessels/{vessel_id}/simulate", response_model=SimulationResponse)
    def simulate(vessel_id: str, request: SimulationRequest) -> SimulationResponse:
        return workflow.simulate(vessel_id, request)

    @api.get(
        "/vessels/{vessel_id}/simulation-surface", response_model=SimulationSurfaceResponse
    )
    def simulation_surface(vessel_id: str) -> SimulationSurfaceResponse:
        return workflow.simulation_surface(vessel_id)

    @api.get("/vessels/{vessel_id}/explanation", response_model=ExplanationResponse)
    def explanation(vessel_id: str) -> ExplanationResponse:
        return workflow.explanation(vessel_id)

    @api.post("/vessels/{vessel_id}/questions", response_model=TextResponse)
    def answer_question(vessel_id: str, request: QuestionRequest) -> TextResponse:
        return workflow.answer_question(
            vessel_id, request.question, use_llm=_runtime_llm_enabled()
        )

    @api.post("/appeals", response_model=AppealDetail, status_code=201)
    def submit_appeal(request: AppealCreate) -> AppealDetail:
        return workflow.submit_appeal(request)

    @api.get("/appeals", response_model=AppealListResponse)
    def list_appeals(
        status: Optional[str] = Query(default=None, pattern="^(submitted|approved|held)$")
    ) -> AppealListResponse:
        return workflow.list_appeals(status)

    @api.get("/appeals/{appeal_id}", response_model=AppealDetail)
    def get_appeal(appeal_id: str) -> AppealDetail:
        return workflow.get_appeal(appeal_id)

    @api.post("/appeals/{appeal_id}/draft-response", response_model=AppealDetail)
    def objection_draft(appeal_id: str, request: ObjectionDraftRequest) -> AppealDetail:
        return workflow.objection_draft(
            appeal_id, use_llm=_runtime_llm_enabled(), refresh=request.refresh
        )

    @api.post("/appeals/{appeal_id}/review", response_model=AppealDetail)
    def review_appeal(appeal_id: str, request: ReviewDecision) -> AppealDetail:
        return workflow.review_appeal(appeal_id, request)

    @api.post("/score-runs/{score_run_id}/review", response_model=ReviewDetail)
    def review_score_run(score_run_id: str, request: ReviewDecision) -> ReviewDetail:
        """
        여신 심사 결정을 저장한다.

        이의제기가 접수돼 있으면 그 건에 함께 매달리고, 없어도 결정을 남길 수
        있다 — 심사는 차주의 이의제기와 무관하게 이루어지는 절차다.
        """
        return workflow.review_score_run(score_run_id, request)

    @api.get("/score-runs/{score_run_id}/review", response_model=Optional[ReviewDetail])
    def get_review(score_run_id: str) -> Optional[ReviewDetail]:
        return workflow.get_review(score_run_id)

    @api.post("/reports/{score_run_id}/commit", response_model=ChainCommitResponse)
    def commit_report(score_run_id: str) -> ChainCommitResponse:
        return workflow.commit_report(score_run_id)

    @api.get("/reports/{score_run_id}/commit", response_model=ChainRecordResponse)
    def get_report_commit(score_run_id: str) -> ChainRecordResponse:
        return workflow.get_chain_record_for_score_run(score_run_id)

    @api.get("/chain/records/{record_id}", response_model=ChainRecordResponse)
    def get_chain_record(record_id: str) -> ChainRecordResponse:
        return workflow.get_chain_record(record_id)

    return api


app = create_app()
