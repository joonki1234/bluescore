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
        reason=f"REST 연결 · 체인 {health.get('chainMode', 'local')} · 런타임 LLM {'켜짐' if health.get('runtimeLlmEnabled') else '캐시 우선'}",
    )


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


def review_objection(vessel_id: str, decision: str, reason: str, reviewer: str = "심사역 A") -> Dict:
    appeal = get_objection(vessel_id)
    if not appeal:
        raise ApiClientError("심사할 이의제기가 없습니다.")
    return _legacy_appeal(_api.review_appeal(appeal["appealId"], decision, reason, reviewer))


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
