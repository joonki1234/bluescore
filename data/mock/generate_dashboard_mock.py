"""
담당: 최지희

대시보드(app.py)용 mock 데이터 생성기.

기존 `README_mock_data 제안.md`의 스키마를 확장해, 화면이 필요로 하지만 아직
`score/`에서 나오지 않는 값들을 합성한다. 실제 산출 파이프라인이 완성되면
이 스크립트 전체를 버리고 `score/`의 실산출로 교체한다.

왜 이 스크립트가 필요한가
------------------------
발표용 목업 화면(`blue_score_dashboard_3.html`)은 유사 선박군 내 위치를
`0.65 × A축상위% + 0.35 × B축상위%`로 계산했는데, 이는 백분위끼리 가중평균한
값이라 통계적으로 성립하지 않는다. 올바른 계산은

    ① 유사군 N척 각각의 BlueScore를 먼저 구하고
    ② 그 분포 안에서 대상 선박의 순위를 매기는 것

이다. ②를 하려면 유사군 **전체의 점수 분포**가 있어야 하는데 기존 mock에는
`peerGroup: {count, topPercent}` 스칼라 두 개뿐이라 분포가 없었다. 그래서
여기서 분포를 합성한다.

합성 가정 (교체 시 이 부분이 근거로 남는다)
------------------------------------------
1. 축 점수(axisA/axisB)는 기획서 백업 B1의 정의상
   `0.5 × 유사군 내 순위 + 0.5 × 개선률 순위` 형태의 **순위 기반 값**이다.
   순위 기반 값의 주변분포는 0–100 균등분포에 가까우므로 균등분포로 둔다.
2. 두 축은 약한 양의 상관을 가진다고 본다 (AXIS_CORRELATION = 0.3).
   운항을 잘 관리하는 선박이 자원 압력 쪽도 대체로 낫다는 판단이며,
   확정된 값이 아니다.
3. 대상 5척의 축 점수(axisA, axisB)는 발표 목업의 값을 그대로 쓴다.
   BlueScore 총점은 목업 표기값을 쓰지 않고 `0.65×A + 0.35×B`로 **재계산**한다
   (목업의 선박 B·C는 총점이 자기 산식과 어긋나 있었다).

산출물: `dashboard_mock.json`

실행:
    python data/mock/generate_dashboard_mock.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Dict, List, Tuple

# ─── 확정된 규칙 (CLAUDE.md 기준) ─────────────────────────────────────────────
AXIS_A_WEIGHT = 0.65
AXIS_B_WEIGHT = 0.35

# ─── 합성 파라미터 — 잠정값. score/의 실산출로 교체되면 전부 폐기 ──────────────
# TODO(score/): 유사군 전체 점수 분포가 나오면 아래 합성 로직 전체를 삭제한다.
AXIS_CORRELATION = 0.3  # A축·B축 점수 간 상관 — 잠정값
AXIS_SCORE_MIN = 4.0
AXIS_SCORE_MAX = 97.0
RANDOM_SEED = 20260814  # 고정: 재실행해도 같은 분포가 나와야 한다

# 유사 선박군으로 인정할 최소 표본 수 — 잠정값.
# TODO(팀): CLAUDE.md '미확정 항목'의 유사군 최소 표본 기준 확정 후 교체.
MIN_PEER_SAMPLE = 20

# 백분위 신뢰구간 산출용 부트스트랩 설정
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_LOWER_PCT = 5
BOOTSTRAP_UPPER_PCT = 95


def _normal_cdf(z: float) -> float:
    """표준정규 누적분포함수 (stdlib만 사용)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _correlated_uniforms(rng: random.Random, rho: float) -> Tuple[float, float]:
    """가우시안 코퓰러로 상관을 가진 균등난수 두 개를 뽑는다."""
    z1 = rng.gauss(0.0, 1.0)
    z2 = rng.gauss(0.0, 1.0)
    y2 = rho * z1 + math.sqrt(1.0 - rho**2) * z2
    return _normal_cdf(z1), _normal_cdf(y2)


def _to_axis_score(u: float) -> float:
    """균등난수(0–1)를 축 점수 범위로 변환."""
    return round(AXIS_SCORE_MIN + u * (AXIS_SCORE_MAX - AXIS_SCORE_MIN), 1)


def blue_score(axis_a: float, axis_b: float) -> float:
    """확정 산식. 화면·리포트 어디서든 이 함수만 쓴다."""
    return round(AXIS_A_WEIGHT * axis_a + AXIS_B_WEIGHT * axis_b, 1)


def top_percent(value: float, population: List[float]) -> int:
    """
    population 안에서 value가 상위 몇 %인지 반환한다 (1이 가장 좋음).

    목업의 `0.65 × A상위% + 0.35 × B상위%` 를 대체하는 올바른 계산이다.
    동점은 자신보다 '큰' 값의 개수로만 세어 보수적으로 처리한다.
    """
    if not population:
        raise ValueError("population이 비어 있습니다.")
    better_count = sum(1 for v in population if v > value)
    return max(1, round(better_count / len(population) * 100))


def _bootstrap_top_percent_interval(
    value: float, population: List[float], rng: random.Random
) -> Dict[str, int]:
    """
    상위 %의 표본 불확실성을 부트스트랩으로 추정한다.

    점수 72.6 자체는 입력이 주어지면 결정론적이다. 불확실한 것은 '유사군 42척
    안에서 어디쯤인가'이고, 42척은 작은 표본이라 흔들린다. 그래서 점수가 아니라
    **순위**에 구간을 붙인다.
    """
    n = len(population)
    samples = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        resampled = [population[rng.randrange(n)] for _ in range(n)]
        samples.append(top_percent(value, resampled))
    samples.sort()

    def pick(pct: int) -> int:
        idx = min(len(samples) - 1, max(0, int(len(samples) * pct / 100)))
        return samples[idx]

    return {"lower": pick(BOOTSTRAP_LOWER_PCT), "upper": pick(BOOTSTRAP_UPPER_PCT)}


def build_peer_group(
    rng: random.Random, size: int, focal_axis_a: float, focal_axis_b: float
) -> Dict:
    """
    대상 선박 1척 + 합성된 (size-1)척으로 유사 선박군을 구성한다.

    Returns:
        scores 배열, selfIndex, 그리고 축별/종합 상위 % 및 신뢰구간.
    """
    axis_a_scores = [focal_axis_a]
    axis_b_scores = [focal_axis_b]

    for _ in range(size - 1):
        ua, ub = _correlated_uniforms(rng, AXIS_CORRELATION)
        axis_a_scores.append(_to_axis_score(ua))
        axis_b_scores.append(_to_axis_score(ub))

    scores = [blue_score(a, b) for a, b in zip(axis_a_scores, axis_b_scores)]
    focal_score = scores[0]

    return {
        "count": size,
        "scores": scores,
        "selfIndex": 0,
        "axisAScores": axis_a_scores,
        "axisBScores": axis_b_scores,
        "topPercent": top_percent(focal_score, scores),
        "topPercentInterval": _bootstrap_top_percent_interval(focal_score, scores, rng),
        "axisATopPercent": top_percent(focal_axis_a, axis_a_scores),
        "axisBTopPercent": top_percent(focal_axis_b, axis_b_scores),
    }


# ─── 대상 선박 정의 ──────────────────────────────────────────────────────────
# 축 점수·항적·이벤트 등은 발표 목업(blue_score_dashboard_3.html)에서 가져왔다.
# BlueScore 총점만 목업 표기값 대신 blue_score()로 재계산한다.
VESSEL_SEEDS = [
    {
        "vesselId": "VESSEL_A",
        "name": "선박 A",
        "meta": "근해통발 · 29톤 · 남해",
        "fleetLabel": "근해통발 · 20–30톤 · 남해 · 하계",
        "axisA": 81.0,
        "axisB": 57.0,
        "peerSize": 42,
        "anchor": [37.196, 131.792],
        "revisitCount": 3,
        "averageSpeedKnots": 10.4,
        "totalDistanceKm": 1240,
        "fishingHours": 214,
        "estimatedFuelKl": 38.2,
        "sailCalls": 24,
        "fishingDays": 38,
        "fuelDeltaPercent": 8.0,
        "coveragePercent": 96,
        "trend": [64.1, 66.0, 68.4, 69.2, 70.8, 72.6],
        "shapFactors": [
            {"label": "동일 격자 재방문 간격", "value": 6.2, "axis": "a"},
            {"label": "혼잡 어장 회피", "value": 3.1, "axis": "a"},
            {"label": "조업 시간 배분", "value": 1.4, "axis": "a"},
            {"label": "어장 이동 거리", "value": 0.8, "axis": "a"},
            {"label": "입출항 규칙성", "value": 0.5, "axis": "a"},
            {"label": "표류·대기 시간 비중", "value": -2.2, "axis": "b"},
            {"label": "조업 시간당 연료", "value": -3.6, "axis": "b"},
            {"label": "항해 속도", "value": -5.4, "axis": "b"},
        ],
        "summary": (
            "같은 어장을 연속으로 긁지 않는 편이라 자원 압력 점수가 높습니다. "
            "다만 연료를 기대치보다 8% 더 씁니다. 항해 속도가 주된 이유이고, "
            "표류·대기 시간이 긴 것도 영향을 줍니다."
        ),
        "recommendations": [
            {"action": "같은 어장 연속 조업을 3회에서 2회로 줄이기", "axis": "a"},
            {"action": "평균 항해 속도 1노트 감속", "axis": "b"},
            {"action": "어장 도착 전 대기 시간 단축", "axis": "b"},
        ],
        "eligibility": [
            {"label": "금어기 위반 없음", "passed": True},
            {"label": "해양보호구역 진입 없음", "passed": True},
            {"label": "관측 데이터 충분", "passed": True},
        ],
        "track": [
            [70, 300], [100, 260], [150, 240], [210, 255], [230, 210], [260, 180],
            [300, 190], [330, 150], [300, 120], [260, 110], [220, 140], [190, 170],
            [160, 150],
        ],
        "fishingSegments": [[3, 7], [9, 12]],
        "gapIndex": 8,
        "mpaIndex": 6,
    },
    {
        "vesselId": "VESSEL_B",
        "name": "선박 B",
        "meta": "통발 · 19톤 · 남해",
        "fleetLabel": "통발 · 15–20톤 · 남해 · 하계",
        "axisA": 52.0,
        "axisB": 66.0,
        "peerSize": 37,
        "anchor": [37.281, 131.938],
        "revisitCount": 4,
        "averageSpeedKnots": 12.8,
        "totalDistanceKm": 980,
        "fishingHours": 176,
        "estimatedFuelKl": 31.4,
        "sailCalls": 19,
        "fishingDays": 29,
        "fuelDeltaPercent": -14.0,
        "coveragePercent": 91,
        "trend": [61.0, 60.2, 59.5, 59.1, 59.6, 56.9],
        "shapFactors": [
            {"label": "조업 시간당 연료", "value": 5.4, "axis": "b"},
            {"label": "입출항 규칙성", "value": 2.0, "axis": "a"},
            {"label": "조업 시간 배분", "value": 0.9, "axis": "a"},
            {"label": "어장 이동 거리", "value": 0.4, "axis": "a"},
            {"label": "혼잡 어장 회피", "value": -1.1, "axis": "a"},
            {"label": "항해 속도", "value": -2.9, "axis": "b"},
            {"label": "표류·대기 시간 비중", "value": -3.8, "axis": "b"},
            {"label": "동일 격자 재방문 간격", "value": -6.7, "axis": "a"},
        ],
        "summary": (
            "같은 어장을 상대적으로 자주 재방문하는 편이라 자원 압력 점수가 낮습니다. "
            "운항 효율은 양호한 편으로, 연료는 기대치보다 오히려 절감되고 있습니다."
        ),
        "recommendations": [
            {"action": "같은 어장 연속 조업을 4회에서 2회로 줄이기", "axis": "a"},
            {"action": "재방문 간격 평균 3일 확보", "axis": "a"},
            {"action": "혼잡 해역 진입 빈도 축소", "axis": "a"},
        ],
        "eligibility": [
            {"label": "금어기 위반 없음", "passed": True},
            {"label": "해양보호구역 진입 없음", "passed": True},
            {"label": "관측 데이터 충분", "passed": True},
        ],
        "track": [
            [60, 90], [110, 110], [150, 150], [190, 140], [220, 170], [260, 200],
            [300, 220], [330, 260], [300, 290], [260, 300], [220, 280], [180, 250],
        ],
        "fishingSegments": [[1, 4], [6, 9]],
        "gapIndex": -1,
        "mpaIndex": -1,
    },
    {
        "vesselId": "VESSEL_C",
        "name": "선박 C",
        "meta": "자망 · 24톤 · 동해",
        "fleetLabel": "자망 · 20–30톤 · 동해 · 하계",
        "axisA": 88.0,
        "axisB": 79.0,
        "peerSize": 31,
        "anchor": [37.452, 130.795],
        "revisitCount": 2,
        "averageSpeedKnots": 9.1,
        "totalDistanceKm": 1510,
        "fishingHours": 248,
        "estimatedFuelKl": 41.0,
        "sailCalls": 27,
        "fishingDays": 44,
        "fuelDeltaPercent": -6.0,
        "coveragePercent": 98,
        "trend": [74.8, 77.2, 79.6, 81.5, 83.4, 84.9],
        "shapFactors": [
            {"label": "재방문 간격 확보", "value": 7.4, "axis": "a"},
            {"label": "경제속도 준수", "value": 4.8, "axis": "b"},
            {"label": "혼잡 해역 회피", "value": 3.0, "axis": "a"},
            {"label": "조업 시간 배분", "value": 1.1, "axis": "a"},
            {"label": "입출항 규칙성", "value": 0.6, "axis": "a"},
            {"label": "해황 보정(유속·풍속)", "value": -1.2, "axis": "b"},
            {"label": "어장 이동 거리", "value": -1.6, "axis": "a"},
        ],
        "summary": (
            "재방문 간격을 넉넉히 확보하고 경제속도를 준수해 두 축 모두 유사군 "
            "상위권입니다. 연료도 기대치보다 6% 적게 씁니다. 다만 해황 보정 변수의 "
            "영향이 소폭 남아 있습니다."
        ),
        "recommendations": [
            {"action": "현재 조업 패턴 그대로 유지", "axis": "a"},
            {"action": "해황 급변 구간만 사전 회피", "axis": "b"},
            {"action": "정박 대기 효율화", "axis": "b"},
        ],
        "eligibility": [
            {"label": "금어기 위반 없음", "passed": True},
            {"label": "해양보호구역 진입 없음", "passed": True},
            {"label": "관측 데이터 충분", "passed": True},
        ],
        "track": [
            [80, 60], [120, 90], [170, 80], [210, 100], [250, 90], [290, 110],
            [330, 100], [360, 130], [340, 170], [300, 190], [260, 180], [220, 200],
        ],
        "fishingSegments": [[2, 5], [7, 10]],
        "gapIndex": -1,
        "mpaIndex": -1,
    },
    {
        "vesselId": "VESSEL_D",
        "name": "선박 D",
        "meta": "연승 · 8톤 · 동해",
        "fleetLabel": "연승 · 5–10톤 · 동해 · 하계",
        "status": "insufficientSample",
        "reason": "유사 선박군 표본이 부족합니다.",
        "peerSize": 14,
        "anchor": [37.470, 130.949],
        "totalDistanceKm": 410,
        "fishingHours": 88,
        "estimatedFuelKl": 11.6,
        "sailCalls": 9,
        "fishingDays": 13,
        "coveragePercent": 74,
        "track": [[90, 220], [120, 200], [150, 210], [170, 180], [150, 160]],
        "fishingSegments": [[2, 4]],
        "gapIndex": 1,
        "mpaIndex": -1,
    },
    {
        "vesselId": "VESSEL_E",
        "name": "선박 E",
        "meta": "통발 · 15톤 · 남해",
        "fleetLabel": "매칭 실패 — 국내 등록정보 미연결",
        "status": "matchingFailed",
        "reason": "GFW 선박 정보와 국내 선박제원정보를 연결하지 못했습니다.",
        "peerSize": 0,
        "anchor": [37.163, 131.706],
        "totalDistanceKm": 260,
        "fishingHours": 52,
        "estimatedFuelKl": 7.4,
        "sailCalls": 6,
        "fishingDays": 8,
        "coveragePercent": 88,
        "track": [[380, 300], [350, 270], [330, 240], [300, 230]],
        "fishingSegments": [[1, 3]],
        "gapIndex": -1,
        "mpaIndex": -1,
    },
]

# 데이터 소스별 기준일자 — 심사역 화면 표시용.
# TODO(data/): 김태윤 로더가 각 소스의 실제 기준일자를 반환하면 교체.
DATA_FRESHNESS = {
    "Global Fishing Watch": "2026-08-13",
    "해양수산부 선박제원정보": "2026-08-10",
    "한국수산자원공단 TAC 소진현황": "2026-07-31",
    "국립해양측위정보원 해양기상": "2026-08-13",
}

RATE_GRADES = [
    {"grade": "A", "minScore": 78, "discountBp": 20, "label": "BlueScore 78 이상"},
    {"grade": "B", "minScore": 68, "discountBp": 12, "label": "BlueScore 68 – 77"},
    {"grade": "C", "minScore": 55, "discountBp": 6, "label": "BlueScore 55 – 67"},
    {"grade": "D", "minScore": 0, "discountBp": 0, "label": "BlueScore 55 미만"},
]


def build() -> Dict:
    rng = random.Random(RANDOM_SEED)
    vessels = []

    for seed in VESSEL_SEEDS:
        vessel = {k: v for k, v in seed.items() if k not in ("axisA", "axisB", "peerSize")}
        vessel["status"] = seed.get("status", "success")

        if vessel["status"] != "success":
            vessel["peerGroup"] = {"count": seed["peerSize"], "scores": []}
            vessels.append(vessel)
            continue

        peer = build_peer_group(rng, seed["peerSize"], seed["axisA"], seed["axisB"])
        vessel["axisA"] = {"score": seed["axisA"], "topPercent": peer.pop("axisATopPercent")}
        vessel["axisB"] = {"score": seed["axisB"], "topPercent": peer.pop("axisBTopPercent")}
        vessel["blueScore"] = blue_score(seed["axisA"], seed["axisB"])
        vessel["peerGroup"] = peer
        vessels.append(vessel)

    return {
        "_meta": {
            "generator": "data/mock/generate_dashboard_mock.py",
            "owner": "최지희",
            "purpose": "app.py 대시보드용 임시 데이터. score/ 실산출 완성 시 폐기.",
            "seed": RANDOM_SEED,
            "assumptions": [
                "축 점수의 주변분포를 0–100 균등분포로 가정",
                f"A축·B축 점수 간 상관 {AXIS_CORRELATION} (잠정)",
                "BlueScore 총점은 0.65×A + 0.35×B로 재계산 (목업 표기값 미사용)",
            ],
        },
        "minPeerSample": MIN_PEER_SAMPLE,
        "axisWeights": {"a": AXIS_A_WEIGHT, "b": AXIS_B_WEIGHT},
        "rateGrades": RATE_GRADES,
        "dataFreshness": DATA_FRESHNESS,
        "vessels": vessels,
    }


def main() -> None:
    payload = build()
    out_path = Path(__file__).with_name("dashboard_mock.json")
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"작성: {out_path}")
    print()
    print("선박         BlueScore  A축(상위%)   B축(상위%)   종합 상위%  (90% 구간)")
    print("─" * 76)
    for v in payload["vessels"]:
        if v["status"] != "success":
            print(f"{v['name']:<12} —          {v['status']}")
            continue
        peer = v["peerGroup"]
        interval = peer["topPercentInterval"]
        print(
            f"{v['name']:<12} {v['blueScore']:<10} "
            f"{v['axisA']['score']:>4.0f} ({v['axisA']['topPercent']:>2}%)  "
            f"{v['axisB']['score']:>4.0f} ({v['axisB']['topPercent']:>2}%)  "
            f"{peer['count']}척 중 {peer['topPercent']:>2}%  "
            f"({interval['lower']}–{interval['upper']}%)"
        )


if __name__ == "__main__":
    main()
