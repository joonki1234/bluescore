"""
담당: 최지희

화면과 계산 사이의 유일한 창구.

어업인 화면(ui/fisher.py)과 심사역 화면(ui/bank.py)은 여기서만 숫자를 받아간다.
두 화면이 각자 계산하면 같은 선박에 대해 서로 다른 점수가 나올 수 있고, 그러면
"제3자가 관측한 동일한 점수"라는 서비스 전제가 무너진다.

현재 상태
--------
`score/`의 A축·B축 산출은 geopandas / lightgbm에 의존한다. 두 패키지가 설치돼
있으면 실산출을 시도하고, 없으면 mock으로 폴백한다. 어느 쪽인지는
`scoring_backend()`가 알려주며 화면 하단에 항상 표시된다 — 시연 중 무엇이
실계산이고 무엇이 임시값인지 숨기지 않기 위한 것이다.

`score/`가 반환하는 것은 **raw 값**이지 점수가 아니다. 방향도 반대다.
    axis_a_pressure_raw  압력이므로 **클수록 나쁨**
    residual_raw         기대 대비 초과 연료이므로 **클수록 나쁨**
따라서 유사군 내 백분위로 정규화할 때 부호를 뒤집어야 한다. `_raw_to_score()`
참고.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

MOCK_PATH = Path(__file__).resolve().parent.parent / "data" / "mock" / "dashboard_mock.json"

# ─── 시뮬레이터 축 간 트레이드오프 계수 — 전부 잠정값 ─────────────────────────
# 기획서(BlueScore_점수산정_요약.md)는 "멀리 옮기면 연료를 더 써서 B축이 깎인다"고
# 명시하고 있다. 한쪽 축만 올리는 시뮬레이터는 물리적으로 불가능한 조합을 좋은
# 것처럼 보여주므로, 반작용을 계수로 넣는다.
#
# TODO(score/ 김준기·오동규): 아래 4개는 근거 없는 잠정값이다. 실제 계수 또는
# 산출 방식을 받으면 교체할 것. 값이 확정되기 전까지 화면에는 '잠정'을 표기한다.
AXIS_A_GAIN_PER_REVISIT_STEP = 7.0  # 연속 조업 1회 감축당 A축 상승폭
AXIS_B_COST_PER_REVISIT_STEP = 2.4  # 그 대가로 어장을 옮기며 드는 B축 하락폭
AXIS_B_GAIN_PER_KNOT = 3.2  # 항해속도 1노트 감속당 B축 상승폭
AXIS_A_COST_PER_KNOT = 0.8  # 그 대가로 해상 체류가 길어지며 드는 A축 하락폭

# 연료 변화 환산 — B축 1점당 기대 대비 연료 %p. 잠정값.
FUEL_PERCENT_PER_AXIS_B_POINT = 0.55

AXIS_SCORE_FLOOR = 4.0
AXIS_SCORE_CEIL = 97.0

# 심사 리포트 금리 예시의 기준 — 화면 표기용 상수
EXAMPLE_PRINCIPAL_WON = 100_000_000
EXAMPLE_TERM_YEARS = 3


@dataclass
class Backend:
    """계산이 실제 score/에서 나왔는지, mock인지."""

    live: bool
    reason: str

    @property
    def label(self) -> str:
        return "score/ 실산출" if self.live else f"시연용 데이터 ({self.reason})"


def scoring_backend() -> Backend:
    """현재 화면의 산출 경로와 실제 A축 어댑터 준비 상태를 알린다."""
    try:
        import geopandas  # noqa: F401
        import lightgbm  # noqa: F401
    except ImportError as exc:
        missing = str(exc).split("'")[-2] if "'" in str(exc) else "의존 패키지"
        return Backend(live=False, reason=f"{missing} 미설치")

    try:
        from score.axis_a_pressure import compute_axis_a_pressure  # noqa: F401
        from score.axis_b_baseline import compute_axis_b_efficiency  # noqa: F401
    except ImportError as exc:
        return Backend(live=False, reason=f"score/ 임포트 실패: {exc}")

    from services.real_scoring import RealAxisAAdapter

    if not RealAxisAAdapter().available:
        return Backend(live=False, reason="실데이터 스냅샷 없음")

    # 두 페르소나 화면은 결정론적 fixture를 쓰고, REST API의 sourceType=real 경로가
    # 실제 GFW 스냅샷→A축→유사군→백분위를 제공한다. B축이 검증되기 전에는
    # 실데이터 총점을 억지로 만들지 않는다.
    return Backend(live=False, reason="fixture 고정 · 실제 A축 연결됨 · B축 검증 대기")


def _raw_to_score(raw: float, peer_raws: List[float]) -> float:
    """
    raw 값을 유사군 내 백분위 점수(0–100, 높을수록 좋음)로 변환한다.

    A축 압력과 B축 잔차는 둘 다 '클수록 나쁨'이므로 부호를 뒤집는다.
    score/의 실산출을 붙일 때 이 함수를 쓴다.
    """
    from score.score_assembly import raw_to_score

    return raw_to_score(raw, peer_raws, floor=AXIS_SCORE_FLOOR, ceil=AXIS_SCORE_CEIL)


def _read_dataset(_mtime: float) -> Dict:
    """
    mock 데이터셋 실제 로드.

    `_mtime`은 값 자체를 쓰지 않고 **캐시 키**로만 쓴다. 이게 없으면 JSON을
    다시 생성해도 Streamlit 캐시가 옛 데이터를 계속 들고 있어, 서버를 재시작하기
    전까지 화면이 바뀌지 않는다.
    """
    with MOCK_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


try:  # Streamlit 런타임 안에서만 캐시를 적용한다 (테스트·스크립트에서도 임포트 가능하게)
    import streamlit as st

    _read_dataset = st.cache_data(show_spinner=False)(_read_dataset)  # type: ignore[assignment]
except ImportError:  # pragma: no cover
    pass


def load_dataset() -> Dict:
    """mock 데이터셋 로드. 파일이 바뀌면 캐시가 자동으로 무효화된다."""
    return _read_dataset(MOCK_PATH.stat().st_mtime)


def list_vessels() -> List[Dict]:
    return load_dataset()["vessels"]


def vessel_options() -> List[str]:
    return [v["vesselId"] for v in list_vessels()]


def vessel_label(vessel_id: str) -> str:
    v = get_vessel(vessel_id)
    return f"{v['name']} · {v['meta']}"


def get_vessel(vessel_id: str) -> Dict:
    for v in list_vessels():
        if v["vesselId"] == vessel_id:
            return v
    raise KeyError(f"알 수 없는 선박: {vessel_id}")


def is_scored(vessel: Dict) -> bool:
    """점수를 산출할 수 있는 선박인가 (표본 부족·매칭 실패가 아닌가)."""
    return vessel.get("status") == "success"


def blocked_notice(vessel: Dict) -> Dict[str, str]:
    """
    점수를 내지 않는 경우의 표기 내용.

    기획서 9번의 "모르면 모른다고 한다" 원칙 — 억지로 점수를 내는 대신
    사유와 다음 행동을 안내한다.
    """
    dataset = load_dataset()
    if vessel.get("status") == "matchingFailed":
        return {
            "title": "매칭 실패",
            "body": (
                "GFW 조업 이벤트는 확인되지만 국내 등록정보(어선번호 기준)와 "
                "연결되지 않아 B축(운항 효율)을 계산할 수 없습니다. "
                "매칭되지 않은 선박은 점수를 추정하지 않고 산출을 보류합니다."
            ),
            "next": "선박의 MMSI 또는 호출부호를 확인해 등록정보와 대조가 필요합니다.",
        }
    return {
        "title": "판정 불가",
        "body": (
            f"비교 대상이 {vessel['peerGroup']['count']}척으로 최소 표본 기준"
            f"({dataset['minPeerSample']}척)에 미달합니다. "
            "억지로 점수를 내는 대신 유사 선박군 표본이 쌓일 때까지 산출을 보류합니다."
        ),
        "next": "동일 톤수대·어업종·해역의 관측 선박이 늘어나면 자동으로 산출됩니다.",
    }


def top_percent(value: float, population: List[float]) -> int:
    """
    population 안에서 value가 상위 몇 %인지 (1이 가장 좋음).

    발표 목업의 `0.65 × A상위% + 0.35 × B상위%`를 대체하는 올바른 계산이다.
    백분위끼리 가중평균하는 것은 통계적으로 성립하지 않는다.
    """
    if not population:
        raise ValueError("population이 비어 있습니다.")
    better = sum(1 for v in population if v > value)
    return max(1, round(better / len(population) * 100))


def blue_score(axis_a: float, axis_b: float) -> float:
    weights = load_dataset()["axisWeights"]
    return round(weights["a"] * axis_a + weights["b"] * axis_b, 1)


def formula_text(axis_a: float, axis_b: float) -> str:
    weights = load_dataset()["axisWeights"]
    return (
        f"{weights['a']} × {axis_a:g} + {weights['b']} × {axis_b:g} "
        f"= {blue_score(axis_a, axis_b)}"
    )


@dataclass
class Simulation:
    """개선 시뮬레이션 결과. 트레이드오프를 반영한 값이다."""

    axis_a: float
    axis_b: float
    score: float
    top_percent: int
    axis_a_delta: float
    axis_b_delta: float
    score_delta: float
    fuel_delta_percent: float
    tradeoff_notes: List[str]
    # 이 결과를 만든 슬라이더 위치. 개선 추천 카드가 "무엇을 바꾼 조합인지"를
    # 말하려면 결과만으로는 부족해서 함께 들고 다닌다.
    revisit_count: int = 0
    speed_knots: float = 0.0

    def actions(self, vessel: Dict) -> List[str]:
        """
        기준 조업 방식 대비 무엇을 바꾸는 조합인지 문장으로 만든다.

        숫자는 넣지 않는다 — 이 문장이 그대로 LLM 개선팁 프롬프트의 입력이 되고,
        팁은 수치를 쓰지 않는 것이 규칙이기 때문이다(`explain/prompt.py` 참고).
        """
        out: List[str] = []
        if self.revisit_count < vessel["revisitCount"]:
            out.append("같은 어장에서 연달아 조업하는 횟수를 줄인다")
        elif self.revisit_count > vessel["revisitCount"]:
            out.append("같은 어장에서 연달아 조업하는 횟수를 늘린다")
        if self.speed_knots < vessel["averageSpeedKnots"]:
            out.append("어장을 오갈 때의 평균 항해 속도를 낮춘다")
        elif self.speed_knots > vessel["averageSpeedKnots"]:
            out.append("어장을 오갈 때의 평균 항해 속도를 높인다")
        return out


def simulate(
    vessel: Dict, revisit_count: int, speed_knots: float, *, include_tradeoff: bool = True
) -> Simulation:
    """
    조업 방식을 바꿨을 때의 예상 점수.

    한쪽 축의 개선이 다른 축에 주는 **반작용**을 함께 반영한다. 어장을 자주
    바꾸면 이동거리가 늘어 연료를 더 쓰고(B축 하락), 속도를 낮추면 해상
    체류가 길어진다(A축 소폭 하락).

    `include_tradeoff=False`는 그 반작용을 뺀 값이다 — 화면이 "반작용을 넣지
    않았다면 이만큼 올라간다고 착각했을 곡선"을 점선으로 나란히 그려 대가를
    눈에 보이게 하는 용도이며, 점수 표시에는 쓰지 않는다.

    주의(2026-08-17 실측): 현재 잠정 계수에서는 반작용이 이득을 **줄이기만 할 뿐
    부호를 뒤집지 못한다** — 속도 1노트 감속당 순 +0.60점(반작용 없으면 +1.12),
    연속조업 1회 감축당 순 +3.71점(반작용 없으면 +4.55). 즉 두 슬라이더 모두
    끝까지 미는 것이 실제로 최고점이며, "최고점은 중간에 있다"는 시연 논지는
    지금 계수로는 성립하지 않는다. `ui/test_simulator_surface.py` 참고.
    """
    base_a = vessel["axisA"]["score"]
    base_b = vessel["axisB"]["score"]

    revisit_steps = vessel["revisitCount"] - revisit_count  # 줄일수록 양수
    speed_steps = vessel["averageSpeedKnots"] - speed_knots  # 낮출수록 양수

    axis_a = base_a + revisit_steps * AXIS_A_GAIN_PER_REVISIT_STEP
    axis_b = base_b + speed_steps * AXIS_B_GAIN_PER_KNOT
    if include_tradeoff:
        axis_a -= speed_steps * AXIS_A_COST_PER_KNOT
        axis_b -= revisit_steps * AXIS_B_COST_PER_REVISIT_STEP

    axis_a = round(min(AXIS_SCORE_CEIL, max(AXIS_SCORE_FLOOR, axis_a)), 1)
    axis_b = round(min(AXIS_SCORE_CEIL, max(AXIS_SCORE_FLOOR, axis_b)), 1)

    score = blue_score(axis_a, axis_b)
    peer_scores = list(vessel["peerGroup"]["scores"])
    peer_scores[vessel["peerGroup"]["selfIndex"]] = score

    notes: List[str] = []
    if revisit_steps > 0:
        cost = revisit_steps * AXIS_B_COST_PER_REVISIT_STEP
        notes.append(
            f"어장을 더 자주 옮기면 이동거리가 늘어 운항 효율이 {cost:.1f}점 깎입니다."
        )
    if speed_steps > 0:
        cost = speed_steps * AXIS_A_COST_PER_KNOT
        notes.append(
            f"속도를 낮추면 해상 체류가 길어져 자원 압력이 {cost:.1f}점 깎입니다."
        )
    if revisit_steps < 0:
        notes.append("같은 어장 연속 조업을 늘리면 자원 압력 점수가 떨어집니다.")
    if speed_steps < 0:
        notes.append("속도를 올리면 연료 소비가 늘어 운항 효율 점수가 떨어집니다.")

    fuel_delta = vessel["fuelDeltaPercent"] - (axis_b - base_b) * FUEL_PERCENT_PER_AXIS_B_POINT

    return Simulation(
        axis_a=axis_a,
        axis_b=axis_b,
        score=score,
        top_percent=top_percent(score, peer_scores),
        axis_a_delta=round(axis_a - base_a, 1),
        axis_b_delta=round(axis_b - base_b, 1),
        score_delta=round(score - vessel["blueScore"], 1),
        fuel_delta_percent=round(fuel_delta, 1),
        tradeoff_notes=notes,
        revisit_count=revisit_count,
        speed_knots=speed_knots,
    )


# 시뮬레이터 슬라이더의 정의역. 화면(ui/fisher.py)이 아니라 여기서 정한다 —
# 사전계산한 격자와 슬라이더의 눈금이 어긋나면 조회가 빈칸을 만나기 때문이다.
SIM_REVISIT_RANGE = (1, 5)
SIM_SPEED_DELTA_DOWN = 3.0
SIM_SPEED_DELTA_UP = 2.0
SIM_SPEED_STEP = 0.1


def simulate_speed_axis(vessel: Dict) -> List[float]:
    """속도 슬라이더가 취할 수 있는 값 전체."""
    base = vessel["averageSpeedKnots"]
    lo = round(base - SIM_SPEED_DELTA_DOWN, 1)
    steps = int(round((SIM_SPEED_DELTA_DOWN + SIM_SPEED_DELTA_UP) / SIM_SPEED_STEP))
    return [round(lo + i * SIM_SPEED_STEP, 1) for i in range(steps + 1)]


def simulate_surface(vessel: Dict) -> Dict:
    """
    슬라이더 전 구간의 시뮬레이션 결과를 미리 계산한다.

    `simulate()`를 격자 전체(연속조업 5칸 × 속도 51칸)에 돌린 표다. 화면이
    이 표를 통째로 받아 브라우저에서 조회만 하면, 슬라이더를 움직일 때마다
    서버를 왕복하지 않아도 된다 — 실측상 왕복 1회가 300~570ms였고 그때마다
    결과 카드 iframe이 다시 로드돼 카운트업 애니메이션이 처음부터 재생됐다.

    **계산은 여전히 전부 여기(파이썬)서 한다.** 브라우저는 이 표를 읽기만 하며
    새 숫자를 만들지 않는다 — adapter가 유일한 계산 창구라는 전제를 지킨다.

    `simulate()`가 순수 산술이라 255개 조합을 다 돌려도 비용이 무시할 수준이다.
    """
    from ui import theme  # 이 파일의 다른 함수들과 같은 지연 임포트 방식

    grades = load_dataset()["rateGrades"]
    base_band = theme.grade_band(vessel["blueScore"], grades)
    speeds = simulate_speed_axis(vessel)
    revisits = list(range(SIM_REVISIT_RANGE[0], SIM_REVISIT_RANGE[1] + 1))

    grid: Dict[str, Dict] = {}
    for revisit in revisits:
        for speed in speeds:
            sim = simulate(vessel, revisit, speed)
            band = theme.grade_band(sim.score, grades)
            gained_bp = band["discountBp"] - base_band["discountBp"]
            yearly = int(EXAMPLE_PRINCIPAL_WON * gained_bp / 10000)
            grid[f"{revisit}|{speed:.1f}"] = {
                "score": sim.score,
                "axisA": sim.axis_a,
                "axisB": sim.axis_b,
                "topPercent": sim.top_percent,
                "scoreDelta": sim.score_delta,
                "fuelDeltaPercent": sim.fuel_delta_percent,
                "tradeoffNotes": sim.tradeoff_notes,
                "grade": band["grade"],
                "discountBp": band["discountBp"],
                "yearlyWon": yearly,
                "totalWon": yearly * EXAMPLE_TERM_YEARS,
                # 반작용을 뺀 값. 곡선에 점선으로 겹쳐 그려 "대가"를 보이게 한다.
                "scoreNoTradeoff": simulate(
                    vessel, revisit, speed, include_tradeoff=False
                ).score,
            }

    return {
        "revisits": revisits,
        "speeds": speeds,
        "grid": grid,
        "base": {
            "revisit": vessel["revisitCount"],
            "speed": vessel["averageSpeedKnots"],
            "score": vessel["blueScore"],
            "topPercent": vessel["peerGroup"]["topPercent"],
            "grade": base_band["grade"],
            "discountBp": base_band["discountBp"],
        },
        "rateGrades": grades,
        "peerScores": vessel["peerGroup"]["scores"],
        "principalWon": EXAMPLE_PRINCIPAL_WON,
        "termYears": EXAMPLE_TERM_YEARS,
    }


# ─── 해시 (CLAUDE.md 확정 규칙 5번) ───────────────────────────────────────────
def _canonicalize(value):
    """
    해시 대상 JSON 정규화.

    CLAUDE.md 확정 규칙:
        · sort_keys=True로 직렬화
        · 소수점이 있는 값은 둘째 자리 반올림 후 문자열로 변환
        · 빈 값(None/누락)은 null을 넣지 않고 키 자체를 제외
    """
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value if v is not None]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return f"{round(value, 2):.2f}"
    return value


def score_hash(payload: Dict) -> str:
    """
    산출 결과의 SHA-256 해시.

    발표 목업은 자체 곱셈 해시를 써서 위 규칙을 따르지 않았다. 여기서는 규칙대로
    구현하되, 온체인 커밋은 chain/ 담당 몫이다.
    TODO(chain/ 김준기·오동규): chain/의 해시 함수가 나오면 이 구현을 그쪽 호출로
    교체하고, 두 결과가 일치하는지 검증할 것.
    """
    from chain.hashing import compute_result_hash

    return "0x" + compute_result_hash(payload)


def hash_payload(vessel: Dict, simulation: Optional[Simulation] = None) -> Dict:
    """해시 대상이 되는 산출 결과 본체."""
    payload = {
        "vesselId": vessel["vesselId"],
        "blueScore": vessel["blueScore"],
        "axisA": vessel["axisA"]["score"],
        "axisB": vessel["axisB"]["score"],
        "peerCount": vessel["peerGroup"]["count"],
        "topPercent": vessel["peerGroup"]["topPercent"],
    }
    if simulation is not None:
        payload["simulatedScore"] = simulation.score
    return payload


def document_id(vessel: Dict, issued_date: str) -> str:
    digest = score_hash(hash_payload(vessel))[2:10].upper()
    return f"BS-{issued_date.replace('-', '')}-{digest}"


# ─── 설명 계층 (explain/) ────────────────────────────────────────────────────
def _build_explain_input(vessel: Dict):
    """mock 선박 레코드를 explain/의 입력 계약으로 옮긴다."""
    from explain.contract import ExplainInput, FactorMetric, ShapFactor

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
        shap_factors=[
            ShapFactor(label=f["label"], value=f["value"], axis=f["axis"])
            for f in vessel["shapFactors"]
        ],
        factor_metrics=[
            FactorMetric(
                label=m["label"],
                axis=m["axis"],
                self_value=m["selfValue"],
                peer_average=m["peerAverage"],
                unit=m["unit"],
            )
            for m in vessel.get("factorMetrics", [])
        ],
    )


def _explain_uncached(vessel_id: str, _mtime: float) -> Dict:
    """
    설명 생성 실제 호출.

    `_mtime`은 캐시 키 전용이다 (mock JSON이 바뀌면 설명도 다시 만든다).
    LLM 호출은 느리고 유료라 선박당 한 번만 하고 캐시에 태운다.
    """
    from explain.explain import explain as run_explain

    vessel = get_vessel(vessel_id)
    return run_explain(_build_explain_input(vessel)).as_dict()


try:
    import streamlit as st

    _explain_uncached = st.cache_data(show_spinner="설명을 생성하는 중...")(  # type: ignore[assignment]
        _explain_uncached
    )
except ImportError:  # pragma: no cover
    pass


def explanation(vessel: Dict) -> Dict:
    """
    선박의 설명 문구를 가져온다.

    반환 형태는 `data/mock/README_mock_data 제안.md` 5번과 같다:
    `summary` / `shapFactors` / `recommendations`, 그리고 `source`.

    `source`는 이 문구가 LLM이 쓴 것인지 템플릿 폴백인지 알려준다. 화면에
    그대로 표시해, 시연 중 무엇이 생성이고 무엇이 대체인지 숨기지 않는다.
    """
    if not is_scored(vessel):
        return {"summary": "", "shapFactors": [], "recommendations": [], "source": ""}
    return _explain_uncached(vessel["vesselId"], MOCK_PATH.stat().st_mtime)


def _detailed_report_uncached(vessel_id: str, _mtime: float) -> Dict:
    from explain.explain import generate_detailed_report

    vessel = get_vessel(vessel_id)
    return generate_detailed_report(_build_explain_input(vessel)).as_dict()


try:
    import streamlit as st

    _detailed_report_uncached = st.cache_data(show_spinner="상세 리포트를 생성하는 중...")(  # type: ignore[assignment]
        _detailed_report_uncached
    )
except ImportError:  # pragma: no cover
    pass


def detailed_report(vessel: Dict) -> Dict:
    """
    요인별 상세 리포트. 선박당 한 번만 생성해 캐시한다.

    반환 형태는 `{"rows": [...], "source": ...}`이며 `rows`의 각 항목은
    요인 하나다 — 실측값(내 값·유사군 평균), 기여도, 그리고 그 요인에 대한
    설명 문장이 한 줄에 묶여 있다. 화면이 요인별로 끊어 그릴 수 있게 여기서
    미리 합쳐 둔다.
    """
    if not is_scored(vessel):
        return {"rows": [], "source": ""}

    result = _detailed_report_uncached(vessel["vesselId"], MOCK_PATH.stat().st_mtime)
    sentences = result.get("items", {})
    contributions = {f["label"]: f["value"] for f in vessel.get("shapFactors", [])}

    rows = []
    for metric in vessel.get("factorMetrics", []):
        label = metric["label"]
        diff = metric["selfValue"] - metric["peerAverage"]
        rows.append({
            "label": label,
            "axis": metric["axis"],
            "selfValue": metric["selfValue"],
            "peerAverage": metric["peerAverage"],
            "unit": metric["unit"],
            "diff": round(diff, 2),
            "contribution": contributions.get(label),
            "sentence": sentences.get(label, ""),
        })
    return {"rows": rows, "source": result.get("source", "")}


def ask_ai(vessel: Dict, question: str) -> Dict:
    """어업인의 자유 질문에 답한다. 질문마다 새로 호출하며 캐시하지 않는다."""
    from explain.explain import answer_question

    if not question.strip():
        return {"text": "", "source": ""}
    return answer_question(_build_explain_input(vessel), question).as_dict()


def objection_ai_response(vessel: Dict, reason: str, detail: str) -> Dict:
    """이의제기에 대한 AI 답변 초안. 심사역이 검토 후 전달한다."""
    from explain.explain import respond_to_objection

    return respond_to_objection(_build_explain_input(vessel), reason, detail).as_dict()


# ─── 이의제기 (세션 메모리 전용, 새로고침·서버 재시작 시 소실) ─────────────────
def submit_objection(vessel_id: str, reason: str, detail: str) -> None:
    """
    이의제기를 세션에 접수한다.

    어업인 화면과 금융기관 화면은 같은 Streamlit 프로세스의 같은 브라우저
    세션(st.session_state)을 공유하므로, 페이지를 전환해도 값이 유지된다.
    지속 저장소가 아니므로 새로고침·서버 재시작 시 사라진다 — 데모 범위에
    맞춘 의도적인 선택이다.
    """
    import streamlit as st

    objections = st.session_state.setdefault("objections", {})
    objections[vessel_id] = {
        "reason": reason,
        "detail": detail,
        "status": "pending",
        "aiResponse": "",
        "aiResponseSource": "",
    }


def get_objection(vessel_id: str) -> Optional[Dict]:
    import streamlit as st

    return st.session_state.get("objections", {}).get(vessel_id)


def resolve_objection(vessel_id: str, ai_response: str, source: str) -> None:
    """AI 답변 초안을 이의제기에 붙인다. 심사역의 발송 여부와 무관하게 기록만 한다."""
    import streamlit as st

    objections = st.session_state.setdefault("objections", {})
    if vessel_id not in objections:
        return
    objections[vessel_id]["aiResponse"] = ai_response
    objections[vessel_id]["aiResponseSource"] = source
    objections[vessel_id]["status"] = "answered"


# ─── 스마트컨트랙트 조회 (UI 연출) ─────────────────────────────────────────────
def rate_lookup(score: float) -> Dict:
    """
    점수로 금리 구간을 조회한다.

    현재는 `score.rate_mapping`의 은행 사전 승인 규칙표를 사용한다. 실제
    온체인 컨트랙트(점수→금리 매핑)가 배포되면 이 함수 내부만 web3 호출로
    바꾸면 되고, 호출부(ui/bank.py)는 손댈 필요가 없다 — `scoring_backend()`와
    같은 스왑 지점 패턴이다.
    TODO(chain/ 김준기·오동규): 실제 컨트랙트가 나오면 mock 대신 web3 조회로 교체.
    """
    from score.rate_mapping import grade_for_score

    grade = grade_for_score(score)
    band = {
        "grade": grade.grade,
        "minScore": grade.min_score,
        "discountBp": grade.discount_bp,
        "label": grade.label,
    }
    return {"band": band, "source": "rules:score.rate_mapping"}


# ─── 개선 추천 (개선 시뮬레이터 탭) ────────────────────────────────────────────
def easiest_improvement(vessel: Dict) -> Simulation:
    """
    지금 할 수 있는 가장 쉬운 개선 — 트레이드오프 대가가 더 작은 쪽 한 걸음만 옮긴다.
    """
    revisit_only = simulate(vessel, vessel["revisitCount"] - 1, vessel["averageSpeedKnots"])
    speed_only = simulate(vessel, vessel["revisitCount"], vessel["averageSpeedKnots"] - 1.0)
    return revisit_only if revisit_only.score_delta >= speed_only.score_delta else speed_only


def best_incentive_improvement(vessel: Dict) -> Simulation:
    """
    최고의 인센티브(다음 등급 도달)를 위해 필요한 최소 조합.

    revisit 1~5 × speed 0.5노트 단위로 간단히 그리드 탐색해, 다음 등급에
    도달하면서 두 축 하락(트레이드오프 대가)이 가장 작은 조합을 고른다.
    다음 등급에 못 미치면 그중 점수가 가장 높은 조합을 돌려준다.
    """
    from ui import theme

    dataset = load_dataset()
    current_band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

    base_speed = vessel["averageSpeedKnots"]
    candidates: List[Simulation] = []
    for revisit in range(1, 6):
        for step in range(0, 21):
            speed = round(base_speed - 3.0 + step * 0.25, 2)
            candidates.append(simulate(vessel, revisit, speed))

    upgraded = [
        c for c in candidates
        if theme.grade_band(c.score, dataset["rateGrades"])["grade"] != current_band["grade"]
        and c.score > vessel["blueScore"]
    ]
    if upgraded:
        # 다음 등급을 막 넘기는 조합 — 필요 이상으로 많이 바꾸지 않는 최소 조합.
        return min(upgraded, key=lambda c: c.score)
    # 어떤 조합도 다음 등급에 못 미치면, 그중 가장 점수가 높은 조합을 보여준다.
    return max(candidates, key=lambda c: c.score)


def _improvement_tip_uncached(vessel_id: str, plan_key: str, _mtime: float) -> Dict[str, str]:
    """
    개선 조합 하나의 실행 팁 생성.

    `explanation()`과 같은 이유로 캐시에 태운다 — LLM 호출은 느리고 유료라
    선박·조합당 한 번만 한다. `_mtime`은 캐시 키 전용이다.
    """
    from explain.explain import generate_improvement_tip

    vessel = get_vessel(vessel_id)
    sim = easiest_improvement(vessel) if plan_key == "easiest" else best_incentive_improvement(vessel)
    label = "가장 쉬운 개선" if plan_key == "easiest" else "다음 우대 구간까지"
    result = generate_improvement_tip(_build_explain_input(vessel), label, sim.actions(vessel))
    return {"text": result.text, "source": result.source}


try:
    import streamlit as st

    _improvement_tip_uncached = st.cache_data(show_spinner=False)(  # type: ignore[assignment]
        _improvement_tip_uncached
    )
except ImportError:  # pragma: no cover
    pass


def improvement_plans(vessel: Dict) -> List[Dict]:
    """
    개선 시뮬레이터의 추천 카드 두 장에 필요한 것 전부.

    점수·등급·금리 변화는 `simulate()`가 계산하고, "그래서 배에서 뭘 하면
    되는지"만 `explain/`이 문장으로 만든다. 숫자와 문장의 출처를 나누는 것이
    `explain/TODO.md`의 원칙이라(LLM은 숫자를 만들지 않는다) 여기서도 지킨다.
    """
    from ui import theme

    dataset = load_dataset()
    before = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])
    plans = [
        ("easiest", "지금 할 수 있는 가장 쉬운 개선", "한 걸음만 바꿔도 되는 조합",
         easiest_improvement(vessel)),
        ("best", "최고의 인센티브를 위한 개선", "다음 우대 구간까지 필요한 조합",
         best_incentive_improvement(vessel)),
    ]

    out: List[Dict] = []
    for key, title, desc, sim in plans:
        after = theme.grade_band(sim.score, dataset["rateGrades"])
        tip = _improvement_tip_uncached(vessel["vesselId"], key, MOCK_PATH.stat().st_mtime)
        out.append({
            "key": key,
            "title": title,
            "desc": desc,
            "baseScore": vessel["blueScore"],
            "score": sim.score,
            "scoreDelta": sim.score_delta,
            "beforeBand": theme.discount_text(before),
            "afterBand": theme.discount_text(after),
            "bandChanged": after["grade"] != before["grade"],
            "actions": sim.actions(vessel),
            "tip": tip["text"],
            "tipSource": tip["source"],
        })
    return out
