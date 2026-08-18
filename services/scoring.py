"""담당: 최지희

시연 fixture와 실제 A축 스냅샷을 동일한 API 계약으로 변환한다.

시연 모드의 축 간 상충계수는 아직 정책 예시다. 실제 score 계수로 오인되지 않도록
SimulationResponse.assumptions에 항상 명시한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from api.schemas import (
    AxisScore,
    ConfigResponse,
    DetailedReportItem,
    EligibilityItem,
    ExplanationResponse,
    FactorMetricSchema,
    ImprovementPlan,
    PeerContext,
    RateBand,
    RateLookupResponse,
    RecommendationSchema,
    ScoreResponse,
    ShapFactorSchema,
    SimulationRequest,
    SimulationResponse,
    SimulationSurfaceResponse,
    TextResponse,
    VesselListResponse,
    VesselSummary,
)
from explain.contract import ExplainInput, FactorMetric, ShapFactor
from explain.explain import explain as run_explain
from explain.explain import (
    answer_question as generate_answer,
    generate_detailed_report,
    generate_improvement_tip,
    respond_to_objection as generate_objection_response,
)
from score.rate_mapping import RATE_GRADES, RateGrade, grade_for_score
from score.tradeoff_coefficients import axis_b_points_per_knot, axis_b_points_per_revisit_step
from services.exceptions import BackendUnavailableError, InvalidStateError, NotFoundError
from services.metadata import response_metadata
from services.real_scoring import RealAxisAAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DATA_PATH = PROJECT_ROOT / "data" / "mock" / "dashboard_mock.json"
PERSONA_PATH = PROJECT_ROOT / "fixtures" / "personas.json"

AXIS_A_WEIGHT = 0.65
AXIS_B_WEIGHT = 0.35
AXIS_A_GAIN_PER_REVISIT_STEP = 7.0
AXIS_A_COST_PER_KNOT = 0.8
# B축 관련 트레이드오프 계수(속도↔B축, 재방문↔B축)는 score/tradeoff_coefficients.py의
# 실제 물리식 기반 함수로 교체했다 — 원래 여기 있던 고정 상수
# (AXIS_B_GAIN_PER_KNOT=3.2, AXIS_B_COST_PER_REVISIT_STEP=2.4)는 근거 없는 정책
# 예시였다.
FUEL_PERCENT_PER_AXIS_B_POINT = 0.55
AXIS_SCORE_FLOOR = 4.0
AXIS_SCORE_CEIL = 97.0
SIM_REVISIT_RANGE = (1, 5)
SIM_SPEED_DELTA_DOWN = 3.0
SIM_SPEED_DELTA_UP = 2.0
SIM_SPEED_STEP = 0.1
EXAMPLE_PRINCIPAL_WON = 100_000_000
EXAMPLE_TERM_YEARS = 3

# 데모 fixture 선박엔 톤수가 없다(data/mock/dashboard_mock.json의 VESSEL_A/B/C
# 전부 tonnage=null). axis_b_points_per_knot/axis_b_points_per_revisit_step은
# tonnage_gt가 필수 인자라, 값이 없으면 이 대표값으로 대체한다.
# 임시값 — 근거 없음, 실제 데모 선박 톤수가 정해지면 교체 필요.
DEMO_FALLBACK_TONNAGE_GT = 50.0


def _rate_band(grade: RateGrade) -> RateBand:
    return RateBand(
        grade=grade.grade,
        min_score=grade.min_score,
        discount_bp=grade.discount_bp,
        label=grade.label,
    )


def _top_percent(value: float, population: List[float]) -> int:
    if not population:
        return 1
    return max(1, round(sum(1 for score in population if score > value) / len(population) * 100))


def _discount_text(band: RateBand) -> str:
    return f"{band.grade} · 우대 없음" if band.discount_bp <= 0 else f"{band.grade} · −{band.discount_bp}bp"


class ScoringService:
    def __init__(
        self,
        demo_data_path: Path = DEMO_DATA_PATH,
        persona_path: Path = PERSONA_PATH,
        real_adapter: RealAxisAAdapter = None,
    ) -> None:
        self.demo_data_path = Path(demo_data_path)
        self.persona_path = Path(persona_path)
        self.real_adapter = real_adapter or RealAxisAAdapter()

    def _demo_data(self) -> dict:
        return json.loads(self.demo_data_path.read_text(encoding="utf-8"))

    def _personas(self) -> List[dict]:
        return json.loads(self.persona_path.read_text(encoding="utf-8"))["personas"]

    def _demo_vessel(self, vessel_id: str) -> dict:
        for vessel in self._demo_data()["vessels"]:
            if vessel["vesselId"] == vessel_id:
                return vessel
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    def config(self) -> ConfigResponse:
        data = self._demo_data()
        return ConfigResponse(
            axis_weights=data["axisWeights"],
            rate_grades=[_rate_band(item) for item in RATE_GRADES],
            data_freshness=data["dataFreshness"],
            min_peer_sample=data["minPeerSample"],
            example_principal_won=EXAMPLE_PRINCIPAL_WON,
            example_term_years=EXAMPLE_TERM_YEARS,
        )

    def rate_lookup(self, score: float) -> RateLookupResponse:
        return RateLookupResponse(
            band=_rate_band(grade_for_score(score)),
            source="rules:score.rate_mapping",
            **response_metadata("demo"),
        )

    def score_run_id(self, vessel_id: str, source_type: str = "demo") -> str:
        if source_type == "demo":
            for persona in self._personas():
                if persona["vesselId"] == vessel_id:
                    return persona["scoreRunId"]
            return f"demo-score-{vessel_id.lower()}-v1"
        return f"real-axis-a-{vessel_id}-20260813"

    def list_vessels(self, source_type: str = "demo", limit: int = 50) -> VesselListResponse:
        metadata = response_metadata(source_type)
        if source_type == "real":
            if not self.real_adapter.available:
                raise BackendUnavailableError("실데이터 스냅샷을 찾을 수 없습니다.")
            # BlueScore까지 완전 산출되는 선박(16.2%)이 목록 앞쪽에 안 걸리면
            # 화면을 처음 열었을 때 A축만 나온 사례부터 보여서 "B축은 안 되나?"로
            # 오해를 살 수 있다. status_ranked_vessels()가 성공 사례부터 정렬해 둔다.
            ranked = self.real_adapter.status_ranked_vessels()
            vessels = [
                VesselSummary(
                    vessel_id=v["vesselId"],
                    name=v.get("name") or "가명 선박",
                    meta=f"{v.get('fishingType') or '어업종 미상'} · {v.get('tonnage') or '톤수 미상'}",
                    fleet_label="실데이터 A축 산출 후보",
                    status=status,
                )
                for _, v, status in ranked[:limit]
            ]
            return VesselListResponse(vessels=vessels, **metadata)

        vessels = [
            VesselSummary(
                vessel_id=v["vesselId"],
                name=v["name"],
                meta=v["meta"],
                fleet_label=v["fleetLabel"],
                status=v["status"],
            )
            for v in self._demo_data()["vessels"]
        ]
        return VesselListResponse(vessels=vessels, **metadata)

    def build_score(self, vessel_id: str, source_type: str = "demo") -> ScoreResponse:
        if source_type == "real":
            return self._build_real_score(vessel_id)
        if source_type != "demo":
            raise InvalidStateError(f"지원하지 않는 sourceType입니다: {source_type}")
        return self._build_demo_score(vessel_id)

    def _build_demo_score(self, vessel_id: str) -> ScoreResponse:
        vessel = self._demo_vessel(vessel_id)
        status = vessel["status"]
        scored = status == "success"
        band = _rate_band(grade_for_score(vessel["blueScore"])) if scored else None
        peer = vessel.get("peerGroup", {})
        message = vessel.get("reason") if not scored else None
        return ScoreResponse(
            score_run_id=self.score_run_id(vessel_id),
            vessel=VesselSummary(
                vessel_id=vessel_id,
                name=vessel["name"],
                meta=vessel["meta"],
                fleet_label=vessel["fleetLabel"],
                status=status,
            ),
            status=status,
            blue_score=vessel.get("blueScore"),
            axis_a=AxisScore(
                score=vessel.get("axisA", {}).get("score"),
                top_percent=vessel.get("axisA", {}).get("topPercent"),
                state="demo" if scored else "unavailable",
                missing_reason=message,
            ),
            axis_b=AxisScore(
                score=vessel.get("axisB", {}).get("score"),
                top_percent=vessel.get("axisB", {}).get("topPercent"),
                state="demo" if scored else "unavailable",
                missing_reason=message,
            ),
            rate_band=band,
            peer_group=PeerContext(
                count=peer.get("count", 0),
                top_percent=peer.get("topPercent"),
                top_percent_interval=peer.get("topPercentInterval"),
                scores=peer.get("scores", []),
                self_index=peer.get("selfIndex"),
                axis_a_scores=peer.get("axisAScores", []),
                axis_b_scores=peer.get("axisBScores", []),
            ),
            matching_confidence=None,
            matching_method="demoFixture",
            matching_reason="가명 시연 선박이며 실선박 식별자 매칭값이 아닙니다.",
            fuel_delta_percent=vessel.get("fuelDeltaPercent"),
            coverage_percent=vessel.get("coveragePercent"),
            shap_factors=[ShapFactorSchema(**item) for item in vessel.get("shapFactors", [])],
            factor_metrics=[FactorMetricSchema(**item) for item in vessel.get("factorMetrics", [])],
            eligibility=[EligibilityItem(**item) for item in vessel.get("eligibility", [])],
            recommendations=[
                RecommendationSchema(**item) for item in vessel.get("recommendations", [])
            ],
            trend=vessel.get("trend", []),
            track=vessel.get("track", []),
            fishing_segments=vessel.get("fishingSegments", []),
            revisit_count=vessel.get("revisitCount"),
            average_speed_knots=vessel.get("averageSpeedKnots"),
            anchor=vessel.get("anchor"),
            total_distance_km=vessel.get("totalDistanceKm"),
            fishing_hours=vessel.get("fishingHours"),
            estimated_fuel_kl=vessel.get("estimatedFuelKl"),
            sail_calls=vessel.get("sailCalls"),
            fishing_days=vessel.get("fishingDays"),
            gap_index=vessel.get("gapIndex"),
            mpa_index=vessel.get("mpaIndex"),
            message=message,
            created_at=datetime.now(timezone.utc),
            **response_metadata("demo"),
        )

    def _build_real_score(self, vessel_id: str) -> ScoreResponse:
        if not self.real_adapter.available:
            raise BackendUnavailableError("실데이터 스냅샷을 찾을 수 없습니다.")
        try:
            result = self.real_adapter.score(vessel_id)
        except KeyError as exc:
            raise NotFoundError(f"실데이터 선박을 찾을 수 없습니다: {vessel_id}") from exc
        vessel = result.vessel

        # B축 연결 이후: A축만 되던 대다수 선박은 그대로 "partial"이고(톤수
        # 매칭 커버리지 43.4%뿐이라 B축 자체가 안 나오는 경우가 흔함), A축+B축이
        # 둘 다 유사군 백분위까지 나온 선박만 "success"로 승격해 BlueScore·
        # 금리구간을 낸다.
        has_axis_b = result.axis_b_score is not None
        status = "success" if result.status == "partial" and has_axis_b else result.status

        blue_score = None
        band = None
        if status == "success":
            blue_score = round(AXIS_A_WEIGHT * result.axis_a_score + AXIS_B_WEIGHT * result.axis_b_score, 1)
            band = _rate_band(grade_for_score(blue_score))

        if status == "success":
            message = (
                "A축·B축 모두 실산출되었습니다. 해양기상 단위(풍속 m/s)는 공식 확인이 "
                "아니라 정황 추정이며, 유속·어업종 일부 필드는 아직 미확인·미보강 "
                "상태입니다 — data_new/README.md 한계 목록 참고."
            )
        elif result.axis_a_score is not None:
            message = "A축만 실산출되었습니다. 이 선박은 유사군 내 B축 표본이 부족해 BlueScore·금리구간은 산출하지 않습니다."
        else:
            message = "A축만 실산출되었습니다. B축·BlueScore·금리구간은 산출하지 않습니다."

        return ScoreResponse(
            score_run_id=self.score_run_id(vessel_id, "real"),
            vessel=VesselSummary(
                vessel_id=vessel_id,
                name=vessel.get("name") or "가명 선박",
                meta=f"{vessel.get('fishingType') or '어업종 미상'} · {vessel.get('tonnage') or '톤수 미상'}",
                fleet_label="GFW 고정 스냅샷 유사군",
                status=status,
            ),
            status=status,
            blue_score=blue_score,
            axis_a=AxisScore(
                score=result.axis_a_score,
                state="real" if result.axis_a_score is not None else "unavailable",
                raw_value=result.axis_a_raw,
                used_event_count=result.used_event_count,
                skipped_event_count=result.skipped_event_count,
                missing_reason=None if result.axis_a_score is not None else "유사군 표본이 부족합니다.",
            ),
            axis_b=AxisScore(
                score=result.axis_b_score,
                state="real" if has_axis_b else "unavailable",
                raw_value=result.axis_b_raw,
                used_event_count=result.axis_b_used_row_count,
                missing_reason=None if has_axis_b else "톤수 미매칭이거나 유사군 내 B축 표본이 부족합니다.",
            ),
            rate_band=band,
            peer_group=PeerContext(count=result.peer_count),
            matching_confidence=None,
            matching_method=result.matching_method,
            matching_reason=result.matching_reason,
            # A축 요인 기여도(SHAP) 실연결. B축은 연결 안 함 — score/shap_factors.py
            # 모듈 docstring 참고("점수"가 아니라 "기준선 조건"만 설명 가능하다는
            # 의미론적 제약으로 B축 SHAP 코드 자체를 들어냄).
            shap_factors=[ShapFactorSchema(**item) for item in result.shap_factors],
            message=message,
            created_at=datetime.now(timezone.utc),
            **response_metadata("real", axis_b_included=has_axis_b),
        )

    def simulate(
        self, vessel_id: str, request: SimulationRequest, *, include_tradeoff: bool = True
    ) -> SimulationResponse:
        vessel = self._demo_vessel(vessel_id)
        if vessel["status"] != "success":
            raise InvalidStateError("점수가 산출되지 않은 선박은 시뮬레이션할 수 없습니다.")

        base_a = vessel["axisA"]["score"]
        base_b = vessel["axisB"]["score"]
        revisit_steps = vessel["revisitCount"] - request.revisit_count
        base_speed = vessel["averageSpeedKnots"]
        speed_steps = base_speed - request.speed_knots
        tonnage_gt = vessel.get("tonnage") or DEMO_FALLBACK_TONNAGE_GT
        # 톤수/현재속도에 따라 값이 달라지는 실제 물리식 기반 계수(고정 상수 아님) —
        # 이 선박의 현재 조업 조건에서 "1노트 더 줄이면"/"재방문 1회 줄이는 대신
        # 다른 어장으로 옮기면"의 한계 효과를 구해, 기존과 같은 선형 구조에 대입한다.
        axis_b_gain_per_knot = axis_b_points_per_knot(tonnage_gt, base_speed)
        axis_b_cost_per_revisit_step = axis_b_points_per_revisit_step(tonnage_gt, base_speed)
        axis_a = base_a + revisit_steps * AXIS_A_GAIN_PER_REVISIT_STEP
        axis_b = base_b + speed_steps * axis_b_gain_per_knot
        if include_tradeoff:
            axis_a -= speed_steps * AXIS_A_COST_PER_KNOT
            axis_b -= revisit_steps * axis_b_cost_per_revisit_step
        axis_a = round(min(AXIS_SCORE_CEIL, max(AXIS_SCORE_FLOOR, axis_a)), 1)
        axis_b = round(min(AXIS_SCORE_CEIL, max(AXIS_SCORE_FLOOR, axis_b)), 1)
        score = round(AXIS_A_WEIGHT * axis_a + AXIS_B_WEIGHT * axis_b, 1)
        peers = list(vessel["peerGroup"]["scores"])
        peers[vessel["peerGroup"]["selfIndex"]] = score
        before = _rate_band(grade_for_score(vessel["blueScore"]))
        after = _rate_band(grade_for_score(score))

        notes = []
        if include_tradeoff and revisit_steps > 0:
            notes.append(
                f"어장을 더 자주 옮기면 이동거리가 늘어 운항 효율이 "
                f"{revisit_steps * axis_b_cost_per_revisit_step:.1f}점 깎입니다."
            )
        if include_tradeoff and speed_steps > 0:
            notes.append(
                f"속도를 낮추면 해상 체류가 길어져 자원 압력이 "
                f"{speed_steps * AXIS_A_COST_PER_KNOT:.1f}점 깎입니다."
            )
        fuel_delta = vessel["fuelDeltaPercent"] - (axis_b - base_b) * FUEL_PERCENT_PER_AXIS_B_POINT

        return SimulationResponse(
            score_run_id=self.score_run_id(vessel_id),
            vessel_id=vessel_id,
            base_score=vessel["blueScore"],
            simulated_score=score,
            score_delta=round(score - vessel["blueScore"], 1),
            axis_a=axis_a,
            axis_b=axis_b,
            axis_a_delta=round(axis_a - base_a, 1),
            axis_b_delta=round(axis_b - base_b, 1),
            top_percent=_top_percent(score, peers),
            fuel_delta_percent=round(fuel_delta, 1),
            before_band=before,
            after_band=after,
            band_changed=before.grade != after.grade,
            tradeoff_notes=notes,
            assumptions=[
                "가명 시연 선박용 정책 시뮬레이션입니다.",
                "축 간 상충계수는 실데이터 검증 전 잠정값입니다.",
            ],
            **response_metadata("demo"),
        )

    def _explain_input(self, vessel: dict) -> ExplainInput:
        return ExplainInput(
            vessel_id=vessel["vesselId"],
            vessel_label=vessel["meta"],
            fleet_label=vessel["fleetLabel"],
            blue_score=vessel["blueScore"],
            axis_a_score=vessel["axisA"]["score"],
            axis_b_score=vessel["axisB"]["score"],
            peer_count=vessel["peerGroup"]["count"],
            top_percent=vessel["peerGroup"]["topPercent"],
            fuel_delta_percent=vessel["fuelDeltaPercent"],
            shap_factors=[ShapFactor(**item) for item in vessel.get("shapFactors", [])],
            factor_metrics=[
                FactorMetric(
                    label=item["label"], axis=item["axis"],
                    self_value=item["selfValue"], peer_average=item["peerAverage"],
                    unit=item["unit"],
                )
                for item in vessel.get("factorMetrics", [])
            ],
        )

    def simulation_surface(self, vessel_id: str) -> SimulationSurfaceResponse:
        vessel = self._demo_vessel(vessel_id)
        if vessel["status"] != "success":
            raise InvalidStateError("점수가 산출되지 않은 선박은 시뮬레이션할 수 없습니다.")
        base_speed = vessel["averageSpeedKnots"]
        lo = round(base_speed - SIM_SPEED_DELTA_DOWN, 1)
        step_count = int(round((SIM_SPEED_DELTA_DOWN + SIM_SPEED_DELTA_UP) / SIM_SPEED_STEP))
        speeds = [round(lo + i * SIM_SPEED_STEP, 1) for i in range(step_count + 1)]
        revisits = list(range(SIM_REVISIT_RANGE[0], SIM_REVISIT_RANGE[1] + 1))
        base_band = _rate_band(grade_for_score(vessel["blueScore"]))
        grid: Dict[str, Dict] = {}
        for revisit in revisits:
            for speed in speeds:
                request = SimulationRequest(revisit_count=revisit, speed_knots=speed)
                sim = self.simulate(vessel_id, request)
                no_tradeoff = self.simulate(vessel_id, request, include_tradeoff=False)
                gained_bp = sim.after_band.discount_bp - base_band.discount_bp
                yearly = int(EXAMPLE_PRINCIPAL_WON * gained_bp / 10000)
                grid[f"{revisit}|{speed:.1f}"] = {
                    "score": sim.simulated_score,
                    "axisA": sim.axis_a,
                    "axisB": sim.axis_b,
                    "topPercent": sim.top_percent,
                    "scoreDelta": sim.score_delta,
                    "fuelDeltaPercent": sim.fuel_delta_percent,
                    "tradeoffNotes": sim.tradeoff_notes,
                    "grade": sim.after_band.grade,
                    "discountBp": sim.after_band.discount_bp,
                    "yearlyWon": yearly,
                    "totalWon": yearly * EXAMPLE_TERM_YEARS,
                    "scoreNoTradeoff": no_tradeoff.simulated_score,
                }
        return SimulationSurfaceResponse(
            score_run_id=self.score_run_id(vessel_id), vessel_id=vessel_id,
            revisits=revisits, speeds=speeds, grid=grid,
            base={
                "revisit": vessel["revisitCount"], "speed": base_speed,
                "score": vessel["blueScore"], "topPercent": vessel["peerGroup"]["topPercent"],
                "grade": base_band.grade, "discountBp": base_band.discount_bp,
            },
            rate_grades=[_rate_band(item) for item in RATE_GRADES],
            peer_scores=vessel["peerGroup"]["scores"],
            principal_won=EXAMPLE_PRINCIPAL_WON, term_years=EXAMPLE_TERM_YEARS,
            **response_metadata("demo"),
        )

    def _improvement_candidates(self, vessel_id: str) -> List[tuple]:
        vessel = self._demo_vessel(vessel_id)
        candidates = []
        base_speed = vessel["averageSpeedKnots"]
        for revisit in range(1, 6):
            for step in range(21):
                speed = round(base_speed - 3.0 + step * 0.25, 2)
                sim = self.simulate(
                    vessel_id, SimulationRequest(revisit_count=revisit, speed_knots=speed)
                )
                candidates.append((revisit, speed, sim))
        return candidates

    def improvement_plans(self, vessel_id: str, *, use_llm: bool = False) -> List[ImprovementPlan]:
        vessel = self._demo_vessel(vessel_id)
        explain_input = self._explain_input(vessel)
        revisit = max(1, vessel["revisitCount"] - 1)
        revisit_sim = self.simulate(
            vessel_id, SimulationRequest(revisit_count=revisit, speed_knots=vessel["averageSpeedKnots"])
        )
        speed_sim = self.simulate(
            vessel_id, SimulationRequest(revisit_count=vessel["revisitCount"], speed_knots=vessel["averageSpeedKnots"] - 1.0)
        )
        easiest_tuple = (
            (revisit, vessel["averageSpeedKnots"], revisit_sim)
            if revisit_sim.score_delta >= speed_sim.score_delta
            else (vessel["revisitCount"], vessel["averageSpeedKnots"] - 1.0, speed_sim)
        )
        current_band = _rate_band(grade_for_score(vessel["blueScore"]))
        candidates = self._improvement_candidates(vessel_id)
        upgraded = [item for item in candidates if item[2].band_changed and item[2].score_delta > 0]
        best_tuple = min(upgraded, key=lambda item: item[2].simulated_score) if upgraded else max(
            candidates, key=lambda item: item[2].simulated_score
        )
        specs = [
            ("easiest", "지금 할 수 있는 가장 쉬운 개선", "한 걸음만 바꿔도 되는 조합", easiest_tuple),
            ("best", "최고의 인센티브를 위한 개선", "다음 우대 구간까지 필요한 조합", best_tuple),
        ]
        plans: List[ImprovementPlan] = []
        for key, title, desc, (target_revisit, target_speed, sim) in specs:
            actions = []
            if target_revisit < vessel["revisitCount"]:
                actions.append("같은 어장에서 연달아 조업하는 횟수를 줄인다")
            if target_speed < vessel["averageSpeedKnots"]:
                actions.append("어장을 오갈 때의 평균 항해 속도를 낮춘다")
            tip = generate_improvement_tip(
                explain_input, "가장 쉬운 개선" if key == "easiest" else "다음 우대 구간까지",
                actions, use_llm=use_llm,
            )
            plans.append(ImprovementPlan(
                key=key, title=title, desc=desc, base_score=vessel["blueScore"],
                score=sim.simulated_score, score_delta=sim.score_delta,
                before_band=_discount_text(current_band), after_band=_discount_text(sim.after_band),
                band_changed=sim.band_changed, actions=actions, tip=tip.text, tip_source=tip.source,
            ))
        return plans

    def explain(self, score: ScoreResponse, *, use_llm: bool = False) -> ExplanationResponse:
        if score.status != "success" or score.blue_score is None:
            raise InvalidStateError("완전한 점수가 없는 산출 건은 설명을 만들 수 없습니다.")
        vessel = self._demo_vessel(score.vessel.vessel_id)
        explain_input = self._explain_input(vessel)
        generated = run_explain(explain_input, use_llm=use_llm)
        generated_report = generate_detailed_report(explain_input, use_llm=use_llm)
        report_sentences = generated_report.items
        contributions = {item["label"]: item["value"] for item in vessel.get("shapFactors", [])}
        report = [
            DetailedReportItem(
                **metric,
                contribution=contributions.get(metric["label"]),
                diff=round(metric["selfValue"] - metric["peerAverage"], 2),
                sentence=report_sentences.get(metric["label"], ""),
            )
            for metric in vessel.get("factorMetrics", [])
        ]
        return ExplanationResponse(
            score_run_id=score.score_run_id,
            vessel_id=vessel["vesselId"],
            summary=generated.summary,
            shap_factors=[ShapFactorSchema(**item.as_dict()) for item in generated.shap_factors],
            recommendations=[
                RecommendationSchema(**item.as_dict()) for item in generated.recommendations
            ],
            detailed_report=report,
            improvement_plans=self.improvement_plans(vessel["vesselId"], use_llm=use_llm),
            explanation_source=generated.source,
            report_source=generated_report.source,
            generated_at=datetime.now(timezone.utc),
            **response_metadata("demo"),
        )

    def answer_question(
        self, vessel_id: str, question: str, *, use_llm: bool = False
    ) -> TextResponse:
        vessel = self._demo_vessel(vessel_id)
        generated = generate_answer(
            self._explain_input(vessel), question, use_llm=use_llm
        )
        return TextResponse(text=generated.text, source=generated.source, **response_metadata("demo"))

    def respond_to_objection(
        self, vessel_id: str, reason: str, detail: str, *, use_llm: bool = False
    ) -> TextResponse:
        vessel = self._demo_vessel(vessel_id)
        generated = generate_objection_response(
            self._explain_input(vessel), reason, detail, use_llm=use_llm
        )
        return TextResponse(text=generated.text, source=generated.source, **response_metadata("demo"))
