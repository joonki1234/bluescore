"""
담당: 김준기, 오동규

BlueScore 값을 금리구간(A/B/C/D)과 우대금리(bp)로 매핑한다.

주의: RATE_GRADES의 구간 경계값(78/68/55)과 discount_bp는 `ui/bank.py`,
`data/mock/generate_dashboard_mock.py`의 목업 값을 그대로 가져온 것이며,
실제 금융기관 정책으로 확정된 값이 아니다 (TODO: 확정 후 교체).
"""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class RateGrade:
    grade: str
    min_score: float
    discount_bp: int
    label: str


# 잠정값 — ui/bank.py, data/mock/generate_dashboard_mock.py의 RATE_GRADES와 동일한
# 목업 구간표. min_score 내림차순으로 정렬되어 있어야 한다 (grade_for_score가 순서에
# 의존한다).
RATE_GRADES: List[RateGrade] = [
    RateGrade(grade="A", min_score=78, discount_bp=20, label="BlueScore 78 이상"),
    RateGrade(grade="B", min_score=68, discount_bp=12, label="BlueScore 68 – 77"),
    RateGrade(grade="C", min_score=55, discount_bp=6, label="BlueScore 55 – 67"),
    RateGrade(grade="D", min_score=0, discount_bp=0, label="BlueScore 55 미만"),
]


def grade_for_score(score: float, grades: List[RateGrade] = RATE_GRADES) -> RateGrade:
    """BlueScore 값을 구간표에서 매칭되는 금리등급으로 변환한다.

    grades는 min_score 내림차순으로 정렬되어 있어야 하며, score 이상인 min_score를
    가진 첫 구간을 반환한다. 어느 구간에도 안 걸리는 경우는 없다 — 마지막 구간의
    min_score가 0이면 항상 매칭된다.
    """
    if not grades:
        raise ValueError("grades는 비어 있을 수 없습니다.")
    for band in grades:
        if score >= band.min_score:
            return band
    return grades[-1]


def discount_bp_for_score(score: float, grades: List[RateGrade] = RATE_GRADES) -> int:
    """BlueScore 값에 대응하는 우대금리(bp)만 바로 반환하는 편의 함수."""
    return grade_for_score(score, grades).discount_bp
