"""담당: 최지희

Streamlit 컴포넌트가 사용하는 FastAPI 어댑터.

점수 계산, mock JSON 로드, 업무 상태 저장은 하지 않는다. 화면이 기대하는 기존
키 이름으로 API 응답을 얇게 변환하는 것만 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from ui.api_client import ApiClientError, BlueScoreApiClient


EXAMPLE_PRINCIPAL_WON = 100_000_000
EXAMPLE_TERM_YEARS = 3
SIM_REVISIT_RANGE = (1, 5)
SIM_SPEED_DELTA_DOWN = 3.0
SIM_SPEED_DELTA_UP = 2.0
SIM_SPEED_STEP = 0.1

_api = BlueScoreApiClient()


@lru_cache(maxsize=1)
def _config() -> Dict:
    return _api.config()


@lru_cache(maxsize=2)
def _vessel_summaries(source_type: str = "demo") -> Dict:
    return _api.list_vessels(source_type)


@lru_cache(maxsize=32)
def _score(vessel_id: str) -> Dict:
    return _api.score(vessel_id)


# ─── 실산출(sourceType=real) 미리보기 ────────────────────────────────────────
# 2026-08-18(오동규, 최지희 확인 필요): A/B축 실산출이 API까지는 연결됐는데
# 화면 어디서도 안 보이길래 추가함. 데모(fisher.py/bank.py)와 달리 시뮬레이터·
# 설명(explain)·이의제기는 없다 — services/scoring.py._build_real_score()가
# 그 기능들을 아직 지원하지 않는다(데모 fixture 전용). API 응답을 화면 키로
# 변환하지 않고 그대로 쓴다 — 실산출은 아직 "다듬어진 데모 스키마"가 아니라
# API 원본 그대로 정직하게 보여주는 쪽이 맞다고 판단.
@lru_cache(maxsize=1)
def real_vessel_options(limit: int = 50) -> List[Dict]:
    """실산출 선박 목록(최대 limit척). 5,323척 전체를 드롭다운에 넣는 건
    비현실적이라 API의 기본 limit(50)을 그대로 쓴다."""
    try:
        return _vessel_summaries("real")["vessels"][:limit]
    except ApiClientError:
        return []


@lru_cache(maxsize=64)
def get_real_score(vessel_id: str) -> Dict:
    """실산출 선박 하나의 점수 응답 — API 원본 그대로(camelCase) 반환."""
    return _api.score(vessel_id, "real")


@lru_cache(maxsize=8)
def _surface(vessel_id: str) -> Dict:
    return _api.simulation_surface(vessel_id)


@lru_cache(maxsize=8)
def _report(vessel_id: str) -> Dict:
    return _api.explanation(vessel_id)


def clear_cache() -> None:
    for cached in (_config, _vessel_summaries, _score, _surface, _report):
        cached.cache_clear()


@dataclass
class Backend:
    live: bool
    reason: str

    @property
    def label(self) -> str:
        return f"FastAPI · SQLite ({self.reason})"


@dataclass
class Simulation:
    axis_a: float
    axis_b: float
    score: float
    top_percent: int
    axis_a_delta: float
    axis_b_delta: float
    score_delta: float
    fuel_delta_percent: float
    tradeoff_notes: List[str]
    revisit_count: int = 0
    speed_knots: float = 0.0

    def actions(self, vessel: Dict) -> List[str]:
        out: List[str] = []
        if self.revisit_count < vessel["revisitCount"]:
            out.append("같은 어장에서 연달아 조업하는 횟수를 줄인다")
        if self.speed_knots < vessel["averageSpeedKnots"]:
            out.append("어장을 오갈 때의 평균 항해 속도를 낮춘다")
        return out


def scoring_backend() -> Backend:
    health = _api.health()
    return Backend(
        live=True,
        reason=(
            f"REST 연결 · 체인 {health.get('chainMode', 'local')} · "
            f"런타임 LLM {_llm_label(health)}"
        ),
    )


def _llm_label(health: Dict) -> str:
    """
    런타임 LLM 상태를 한 줄로.

    "켜짐/꺼짐"만으로는 부족하다 — 플래그를 켜도 API 프로세스에 키가 없으면
    폴백으로 떨어지는데, 화면에는 그냥 "기본 문구"로만 보여서 원인을 찾는 데
    한참 걸린다. 발표 전 점검이 이 한 줄로 끝나게 한다.
    """
    status = health.get("llm") or {}
    if not status:  # 구버전 API 응답 호환
        return "켜짐" if health.get("runtimeLlmEnabled") else "캐시 우선"
    if status.get("enabled") and status.get("available"):
        return f"켜짐 ({status.get('provider', '?')})"
    if not status.get("enabled"):
        return "꺼짐 · 캐시 우선"
    return f"키 없음 ({status.get('provider', '?')}) · 폴백"


def load_dataset() -> Dict:
    config = _config()
    return {
        "axisWeights": config["axisWeights"],
        "rateGrades": config["rateGrades"],
        "dataFreshness": config["dataFreshness"],
        "minPeerSample": config["minPeerSample"],
        "vessels": list_vessels(),
    }


def _legacy_score(score: Dict) -> Dict:
    vessel = dict(score["vessel"])
    vessel.update(
        {
            "blueScore": score.get("blueScore"),
            "axisA": score["axisA"],
            "axisB": score["axisB"],
            "rateBand": score.get("rateBand"),
            "peerGroup": score["peerGroup"],
            "fuelDeltaPercent": score.get("fuelDeltaPercent"),
            "coveragePercent": score.get("coveragePercent"),
            "shapFactors": score.get("shapFactors", []),
            "factorMetrics": score.get("factorMetrics", []),
            "eligibility": score.get("eligibility", []),
            "recommendations": score.get("recommendations", []),
            "trend": score.get("trend", []),
            "track": score.get("track", []),
            "fishingSegments": score.get("fishingSegments", []),
            "revisitCount": score.get("revisitCount"),
            "averageSpeedKnots": score.get("averageSpeedKnots"),
            "anchor": score.get("anchor"),
            "totalDistanceKm": score.get("totalDistanceKm"),
            "fishingHours": score.get("fishingHours"),
            "estimatedFuelKl": score.get("estimatedFuelKl"),
            "sailCalls": score.get("sailCalls"),
            "fishingDays": score.get("fishingDays"),
            "gapIndex": score.get("gapIndex"),
            "mpaIndex": score.get("mpaIndex"),
            "message": score.get("message"),
            "scoreRunId": score["scoreRunId"],
            "dataSnapshotId": score["dataSnapshotId"],
            "modelVersion": score["modelVersion"],
            "scoringRuleVersion": score["scoringRuleVersion"],
            "rateTableVersion": score["rateTableVersion"],
            "sourceType": score["sourceType"],
        }
    )
    return vessel


def list_vessels() -> List[Dict]:
    summaries = _vessel_summaries()["vessels"]
    return [get_vessel(item["vesselId"]) for item in summaries]


def vessel_options() -> List[str]:
    return [item["vesselId"] for item in _vessel_summaries()["vessels"]]


def vessel_label(vessel_id: str) -> str:
    vessel = get_vessel(vessel_id)
    return f"{vessel['name']} · {vessel['meta']}"


def get_vessel(vessel_id: str) -> Dict:
    return _legacy_score(_score(vessel_id))


def is_scored(vessel: Dict) -> bool:
    return vessel.get("status") == "success"


def blocked_notice(vessel: Dict) -> Dict[str, str]:
    if vessel.get("status") == "matchingFailed":
        return {
            "title": "매칭 실패",
            "body": vessel.get("message") or "등록정보와 연결되지 않아 점수 산출을 보류합니다.",
            "next": "선박의 MMSI 또는 호출부호를 확인해 등록정보와 대조가 필요합니다.",
        }
    return {
        "title": "판정 불가",
        "body": (
            f"비교 대상이 {vessel['peerGroup']['count']}척으로 최소 표본 기준"
            f"({load_dataset()['minPeerSample']}척)에 미달합니다. 점수를 추정하지 않고 산출을 보류합니다."
        ),
        "next": "동일 톤수대·어업종·해역의 관측 선박이 늘어나면 자동으로 산출됩니다.",
    }


def formula_text(axis_a: float, axis_b: float, total: Optional[float] = None) -> str:
    weights = load_dataset()["axisWeights"]
    result = f" = {total:g}" if total is not None else ""
    return f"{weights['a']} × {axis_a:g} + {weights['b']} × {axis_b:g}{result}"


def simulate(vessel: Dict, revisit_count: int, speed_knots: float, **_: object) -> Simulation:
    item = _api.simulate(vessel["vesselId"], revisit_count, speed_knots)
    return Simulation(
        axis_a=item["axisA"], axis_b=item["axisB"], score=item["simulatedScore"],
        top_percent=item["topPercent"], axis_a_delta=item["axisADelta"],
        axis_b_delta=item["axisBDelta"], score_delta=item["scoreDelta"],
        fuel_delta_percent=item["fuelDeltaPercent"], tradeoff_notes=item["tradeoffNotes"],
        revisit_count=revisit_count, speed_knots=speed_knots,
    )


def simulate_surface(vessel: Dict) -> Dict:
    item = _surface(vessel["vesselId"])
    return {
        "revisits": item["revisits"], "speeds": item["speeds"], "grid": item["grid"],
        "base": item["base"], "rateGrades": item["rateGrades"],
        "peerScores": item["peerScores"], "principalWon": item["principalWon"],
        "termYears": item["termYears"],
    }


def simulate_speed_axis(vessel: Dict) -> List[float]:
    return simulate_surface(vessel)["speeds"]


def explanation(vessel: Dict) -> Dict:
    if not is_scored(vessel):
        return {"summary": "", "shapFactors": [], "recommendations": [], "source": ""}
    item = _report(vessel["vesselId"])
    return {
        "summary": item["summary"], "shapFactors": item["shapFactors"],
        "recommendations": item["recommendations"], "source": item["explanationSource"],
        "reportSource": item["reportSource"], "generatedAt": item["generatedAt"],
        "improvementPlans": item.get("improvementPlans", []),
    }


def detailed_report(vessel: Dict) -> Dict:
    item = _report(vessel["vesselId"])
    return {"rows": item["detailedReport"], "source": item["reportSource"]}


def improvement_plans(vessel: Dict) -> List[Dict]:
    return _report(vessel["vesselId"]).get("improvementPlans", [])


def ask_ai(vessel: Dict, question: str) -> Dict:
    return _api.ask(vessel["vesselId"], question)


def _legacy_appeal(item: Dict) -> Dict:
    return {
        "appealId": item["appealId"], "scoreRunId": item["scoreRunId"],
        "vesselId": item["vesselId"], "reason": item["reason"], "detail": item["detail"],
        "status": item["status"], "aiResponse": item.get("aiResponse", ""),
        "aiResponseSource": item.get("aiResponseSource", ""), "review": item.get("review"),
        "submittedAt": item["submittedAt"], "updatedAt": item["updatedAt"],
    }


def submit_objection(vessel_id: str, reason: str, detail: str) -> Dict:
    vessel = get_vessel(vessel_id)
    return _legacy_appeal(_api.create_appeal(vessel["scoreRunId"], reason, detail))


def list_objections(status: Optional[str] = None) -> List[Dict]:
    return [_legacy_appeal(item) for item in _api.list_appeals(status)["appeals"]]


def get_objection(vessel_id: str) -> Optional[Dict]:
    for item in list_objections():
        if item["vesselId"] == vessel_id:
            return item
    return None


def objection_ai_response(vessel: Dict, reason: str = "", detail: str = "") -> Dict:
    appeal = get_objection(vessel["vesselId"])
    if not appeal:
        raise ApiClientError("먼저 이의제기를 접수해야 합니다.")
    item = _api.draft_appeal_response(appeal["appealId"])
    return {"text": item.get("aiResponse", ""), "source": item.get("aiResponseSource", "")}


# `review_objection()`(이의제기가 있어야만 심사할 수 있던 경로)은 제거했다.
# 심사는 이의제기 유무와 무관하게 성립하므로 화면은 `review_score_run()`만 쓴다.
# 이의제기가 접수돼 있으면 서비스 계층이 알아서 같은 심사에 매달아 준다.
def review_score_run(
    score_run_id: str,
    decision: str,
    reason: str,
    reviewer: str = "심사역 A",
    final_discount_bp: Optional[int] = None,
) -> Dict:
    """
    여신 심사 결정을 저장한다.

    이의제기가 있으면 그 건에 함께 매달리고, 없어도 저장된다 — 심사는 차주가
    이의를 제기해야만 열리는 절차가 아니다.
    """
    return _api.review_score_run(score_run_id, decision, reason, reviewer, final_discount_bp)


def get_review(score_run_id: str) -> Optional[Dict]:
    """산출 건에 저장된 심사 결정. 아직 없으면 None."""
    return _api.review_for_score_run(score_run_id)


def rate_lookup(score: float) -> Dict:
    return _api.rate_lookup(score)


def document_id(vessel: Dict, issued_date: str = "") -> str:
    return f"BS-{vessel['scoreRunId']}"


def commit_report(score_run_id: str) -> Dict:
    return _api.commit_report(score_run_id)


def get_report_commit(score_run_id: str) -> Optional[Dict]:
    return _api.report_commit(score_run_id)


def get_chain_record(record_id: str) -> Dict:
    return _api.chain_record(record_id)
