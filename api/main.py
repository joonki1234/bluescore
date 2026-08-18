"""담당: 최지희

BlueScore FastAPI 애플리케이션.

실행:
    uvicorn api.main:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# .env를 환경변수로 올린다. uvicorn은 Streamlit 진입점(app.py)과 **다른
# 프로세스**라 app.py의 load_dotenv가 여기까지 오지 않는다. 이게 없으면
# 파일에 키를 넣어도 OPENAI_API_KEY도 BLUESCORE_LLM_RUNTIME_ENABLED도
# 보이지 않아, 질의응답이 조용히 llm_disabled 폴백으로 떨어진다.
# python-dotenv가 없어도 앱은 돌아간다 — 환경변수를 직접 export한 경우도 있고,
# 키 없이 폴백으로 도는 것이 정상 동작이기 때문이다.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass

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


def _llm_status() -> dict:
    """
    런타임 LLM이 실제로 답할 수 있는 상태인가.

    플래그(`runtimeLlmEnabled`)만으로는 부족하다 — 플래그를 켜도 이 프로세스에
    `OPENAI_API_KEY`가 없으면 폴백으로 떨어지는데, 화면에는 둘 다 그냥
    "기본 문구"로만 보여서 원인을 구분할 수 없다. 여기서 갈라 둔다.
    """
    from explain.provider import ProviderUnavailable, get_provider

    enabled = _runtime_llm_enabled()
    try:
        provider = get_provider(flow="qa")
        available = provider.is_available()
        name = provider.name
    except ProviderUnavailable as exc:
        return {"enabled": enabled, "available": False, "provider": "unknown", "detail": str(exc)}
    return {
        "enabled": enabled,
        "available": available,
        "provider": name,
        "detail": "" if enabled and available else (
            "BLUESCORE_LLM_RUNTIME_ENABLED가 꺼져 있습니다." if not enabled
            else f"{name} 프로바이더를 쓸 수 없습니다 (API 키를 확인하세요)."
        ),
    }


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
            "llm": _llm_status(),
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
    def explanation(
        vessel_id: str,
        refresh: bool = Query(default=False),
    ) -> ExplanationResponse:
        """
        요약·요인별 상세 설명. 처음 만들 때 LLM을 타고, 이후에는 저장된 것을
        그대로 돌려준다.

        매번 다시 만들지 않는 이유는 심사역 화면(`ui/bank.py`)이 어업인과 같은
        리포트를 읽기 때문이다. 온도가 있어 재생성할 때마다 문장이 흔들리는데,
        이의제기 건에서 어업인이 본 리포트와 심사역이 검토하는 리포트가 다르면
        "금융기관이 근거를 확인해 결정한다"는 전제가 무너진다. 설명 문장은
        온체인 해시 대상이 아니므로(`commit_report` 참고) 재현성 요구는 아니고,
        **두 화면이 같은 것을 봐야 한다**는 요구다.

        `refresh=true`는 시연 전 워밍업용이다 — 저장된 템플릿 리포트를 LLM
        문장으로 갈아끼울 때 쓴다.
        """
        return workflow.explanation(
            vessel_id, use_llm=_runtime_llm_enabled(), refresh=refresh
        )

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
