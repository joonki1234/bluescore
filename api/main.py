"""담당: 최지희

BlueScore FastAPI 애플리케이션.

실행:
    uvicorn api.main:app --reload
"""

from __future__ import annotations

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
    ErrorResponse,
    ExplanationResponse,
    ReviewDecision,
    ScoreResponse,
    SimulationRequest,
    SimulationResponse,
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
from storage.database import Database
from storage.repository import Repository


def create_app(db_path: Optional[Path] = None, *, seed_if_empty: bool = True) -> FastAPI:
    database = Database(db_path)
    repository = Repository(database)
    scoring = ScoringService()
    workflow = WorkflowService(repository=repository, scoring=scoring)

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
        }

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

    @api.get("/vessels/{vessel_id}/explanation", response_model=ExplanationResponse)
    def explanation(vessel_id: str) -> ExplanationResponse:
        return workflow.explanation(vessel_id)

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

    @api.post("/appeals/{appeal_id}/review", response_model=AppealDetail)
    def review_appeal(appeal_id: str, request: ReviewDecision) -> AppealDetail:
        return workflow.review_appeal(appeal_id, request)

    @api.post("/reports/{score_run_id}/commit", response_model=ChainCommitResponse)
    def commit_report(score_run_id: str) -> ChainCommitResponse:
        return workflow.commit_report(score_run_id)

    @api.get("/chain/records/{record_id}", response_model=ChainRecordResponse)
    def get_chain_record(record_id: str) -> ChainRecordResponse:
        return workflow.get_chain_record(record_id)

    return api


app = create_app()

