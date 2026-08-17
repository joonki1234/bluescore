"""담당: 최지희

화면과 FastAPI가 공유하는 공개 데이터 계약.

파이썬 내부에서는 snake_case를 쓰고 JSON에서는 기존 Streamlit/mock과 동일한
camelCase를 쓴다. 이 파일이 API 응답 형태의 단일 원본이다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        use_enum_values=True,
    )


class SourceType(str, Enum):
    REAL = "real"
    ESTIMATED = "estimated"
    DEMO = "demo"


class ScoreStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    INSUFFICIENT_SAMPLE = "insufficientSample"
    MATCHING_FAILED = "matchingFailed"


class AxisState(str, Enum):
    REAL = "real"
    ESTIMATED = "estimated"
    DEMO = "demo"
    UNAVAILABLE = "unavailable"


class AppealStatus(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    HELD = "held"


class DecisionType(str, Enum):
    APPROVE = "approve"
    HOLD = "hold"


class LedgerMode(str, Enum):
    LOCAL = "local"
    ONCHAIN = "onchain"


class VersionedResponse(ApiModel):
    data_snapshot_id: str
    model_version: str
    scoring_rule_version: str
    rate_table_version: str
    source_type: SourceType


class VesselSummary(ApiModel):
    vessel_id: str
    name: str
    meta: str
    fleet_label: str
    status: ScoreStatus


class VesselListResponse(VersionedResponse):
    vessels: List[VesselSummary]


class AxisScore(ApiModel):
    score: Optional[float] = None
    state: AxisState
    raw_value: Optional[float] = None
    used_event_count: Optional[int] = None
    skipped_event_count: Optional[int] = None
    missing_reason: Optional[str] = None


class RateBand(ApiModel):
    grade: str
    min_score: float
    discount_bp: int
    label: str


class PeerContext(ApiModel):
    count: int
    top_percent: Optional[int] = None
    top_percent_interval: Optional[Dict[str, int]] = None


class ShapFactorSchema(ApiModel):
    label: str
    value: float
    axis: str


class RecommendationSchema(ApiModel):
    action: str
    axis: str


class FactorMetricSchema(ApiModel):
    label: str
    axis: str
    self_value: float
    peer_average: float
    unit: str


class EligibilityItem(ApiModel):
    label: str
    passed: bool


class ScoreResponse(VersionedResponse):
    score_run_id: str
    vessel: VesselSummary
    status: ScoreStatus
    blue_score: Optional[float] = None
    axis_a: AxisScore
    axis_b: AxisScore
    rate_band: Optional[RateBand] = None
    peer_group: PeerContext
    matching_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    matching_method: str
    matching_reason: Optional[str] = None
    fuel_delta_percent: Optional[float] = None
    coverage_percent: Optional[float] = None
    shap_factors: List[ShapFactorSchema] = Field(default_factory=list)
    factor_metrics: List[FactorMetricSchema] = Field(default_factory=list)
    eligibility: List[EligibilityItem] = Field(default_factory=list)
    recommendations: List[RecommendationSchema] = Field(default_factory=list)
    trend: List[float] = Field(default_factory=list)
    track: List[List[float]] = Field(default_factory=list)
    fishing_segments: List[List[int]] = Field(default_factory=list)
    revisit_count: Optional[int] = None
    average_speed_knots: Optional[float] = None
    message: Optional[str] = None
    created_at: datetime


class SimulationRequest(ApiModel):
    revisit_count: int = Field(ge=1, le=5)
    speed_knots: float = Field(gt=0, le=60)


class SimulationResponse(VersionedResponse):
    score_run_id: str
    vessel_id: str
    base_score: float
    simulated_score: float
    score_delta: float
    axis_a: float
    axis_b: float
    axis_a_delta: float
    axis_b_delta: float
    top_percent: int
    fuel_delta_percent: float
    before_band: RateBand
    after_band: RateBand
    band_changed: bool
    tradeoff_notes: List[str]
    assumptions: List[str]


class DetailedReportItem(ApiModel):
    label: str
    axis: str
    self_value: float
    peer_average: float
    unit: str
    contribution: Optional[float] = None
    sentence: str


class ExplanationResponse(VersionedResponse):
    score_run_id: str
    vessel_id: str
    summary: str
    shap_factors: List[ShapFactorSchema]
    recommendations: List[RecommendationSchema]
    detailed_report: List[DetailedReportItem]
    explanation_source: str


class AppealCreate(ApiModel):
    score_run_id: str
    reason: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=4000)


class ReviewDecision(ApiModel):
    decision: DecisionType
    reason: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(default="demo-reviewer", min_length=1, max_length=200)


class ReviewDetail(ApiModel):
    review_id: str
    appeal_id: str
    decision: DecisionType
    reason: str
    reviewer: str
    decided_at: datetime


class AppealDetail(VersionedResponse):
    appeal_id: str
    score_run_id: str
    vessel_id: str
    status: AppealStatus
    reason: str
    detail: str
    submitted_at: datetime
    updated_at: datetime
    review: Optional[ReviewDetail] = None


class AppealListResponse(VersionedResponse):
    appeals: List[AppealDetail]


class ChainCommitResponse(VersionedResponse):
    record_id: str
    score_run_id: str
    review_id: str
    result_hash: str
    ledger_mode: LedgerMode
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    contract_address: Optional[str] = None
    committed_at: datetime


class ChainRecordResponse(ChainCommitResponse):
    pass


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
