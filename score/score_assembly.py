"""

raw 값 → 점수 조립: 유사 선박군 내 백분위 정규화.

참고: CLAUDE.md — "각 모듈 하단의 raw 값(예: axis_a_pressure_raw,
axis_b_residual_raw)은 절대 점수가 아니라, 점수조립 단계에서 유사 선박군 내
상대값(백분위 등)으로 다시 정규화되어야 하는 중간 산출값이다."

점수 조립은 이 모듈에서 수행한다. ui/adapter.py의 `_raw_to_score()`는
화면용 임시 구현이므로 이 함수와 동기화해야 한다.

axis_a_pressure_raw(압력)와 axis_b_residual_raw(기대 대비 초과 연료)는 둘 다
"클수록 나쁨" 방향이라, 백분위로 뒤집어서 "클수록 좋음" 점수(0~100)로 바꾼다.
"""

from typing import List

from score.peer_grouping import MIN_PEER_GROUP_SAMPLE_SIZE, PeerGroup

# 화면에 보여줄 점수 하한/상한 — ui/adapter.py의 기존 값을 그대로 가져온
# 잠정값이다. 0/100 대신 여백을 두는 이유는 극단값이 "완전 0점/100점"처럼
# 보이지 않게 하기 위함(ui/adapter.py 원본 의도, 확정된 근거는 아님).
AXIS_SCORE_FLOOR = 4.0
AXIS_SCORE_CEIL = 97.0


def raw_to_score(
    raw: float,
    peer_raws: List[float],
    floor: float = AXIS_SCORE_FLOOR,
    ceil: float = AXIS_SCORE_CEIL,
) -> float:
    """raw 값을 유사군 내 백분위 점수(0~100, 높을수록 좋음)로 변환한다.

    peer_raws는 raw와 같은 유사 선박군(score/peer_grouping.py 참고)에 속한
    모든 선박의 같은 축 raw 값 목록이며, raw 자기 자신도 포함해야 한다.
    """
    if not peer_raws:
        raise ValueError("peer_raws가 비어 있습니다.")
    worse_or_equal = sum(1 for v in peer_raws if v >= raw)
    percentile = worse_or_equal / len(peer_raws) * 100
    return round(min(ceil, max(floor, percentile)), 1)


def score_status_for_group(group: PeerGroup, min_size: int = MIN_PEER_GROUP_SAMPLE_SIZE) -> str:
    """유사 선박군의 표본 수에 따라 산출 가능 여부를 상태 문자열로 반환한다.

    표본이 부족하면 백분위 자체가 의미 없으므로(예: 2척 중 1등이 "상위 50%") 점수를
    내지 않고 insufficientSample로 판정한다 (`data/mock/README_mock_data 제안.md`
    5번의 상태값과 동일한 이름을 쓴다).
    """
    return "success" if group.has_sufficient_sample(min_size) else "insufficientSample"
