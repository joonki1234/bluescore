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

import hashlib
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
        return "score/ 실산출" if self.live else f"mock 임시값 ({self.reason})"


def scoring_backend() -> Backend:
    """score/ 실산출 가용 여부를 확인한다."""
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

    # 모듈은 있으나 실제 이벤트 데이터가 아직 없다. 데이터가 붙으면 이 분기를 제거한다.
    # TODO(data/ 김태윤): 조업 이벤트 데이터셋이 확보되면 실산출 경로로 전환.
    return Backend(live=False, reason="조업 이벤트 데이터 미확보")


def _raw_to_score(raw: float, peer_raws: List[float]) -> float:
    """
    raw 값을 유사군 내 백분위 점수(0–100, 높을수록 좋음)로 변환한다.

    A축 압력과 B축 잔차는 둘 다 '클수록 나쁨'이므로 부호를 뒤집는다.
    score/의 실산출을 붙일 때 이 함수를 쓴다.
    """
    if not peer_raws:
        raise ValueError("peer_raws가 비어 있습니다.")
    worse_or_equal = sum(1 for v in peer_raws if v >= raw)
    return round(
        min(AXIS_SCORE_CEIL, max(AXIS_SCORE_FLOOR, worse_or_equal / len(peer_raws) * 100)), 1
    )


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


def simulate(vessel: Dict, revisit_count: int, speed_knots: float) -> Simulation:
    """
    조업 방식을 바꿨을 때의 예상 점수.

    한쪽 축의 개선이 다른 축에 주는 **반작용**을 함께 반영한다. 어장을 자주
    바꾸면 이동거리가 늘어 연료를 더 쓰고(B축 하락), 속도를 낮추면 해상
    체류가 길어진다(A축 소폭 하락). 반작용을 빼면 두 슬라이더를 모두 끝까지
    밀었을 때 물리적으로 불가능한 조합이 최고점으로 나온다.
    """
    base_a = vessel["axisA"]["score"]
    base_b = vessel["axisB"]["score"]

    revisit_steps = vessel["revisitCount"] - revisit_count  # 줄일수록 양수
    speed_steps = vessel["averageSpeedKnots"] - speed_knots  # 낮출수록 양수

    axis_a = base_a + revisit_steps * AXIS_A_GAIN_PER_REVISIT_STEP
    axis_a -= speed_steps * AXIS_A_COST_PER_KNOT
    axis_b = base_b + speed_steps * AXIS_B_GAIN_PER_KNOT
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
    )


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
    canonical = json.dumps(
        _canonicalize(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    from explain.contract import ExplainInput, ShapFactor

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
