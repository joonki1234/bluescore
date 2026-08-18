"""

score/rate_mapping.py 단위 테스트.
"""

import pytest

from score.rate_mapping import RATE_GRADES, RateGrade, discount_bp_for_score, grade_for_score


class TestGradeForScore:
    def test_score_at_top_boundary_gets_grade_a(self):
        assert grade_for_score(78).grade == "A"

    def test_score_above_top_boundary_gets_grade_a(self):
        assert grade_for_score(95).grade == "A"

    def test_score_just_below_top_boundary_gets_grade_b(self):
        assert grade_for_score(77.99).grade == "B"

    def test_score_at_grade_b_boundary(self):
        assert grade_for_score(68).grade == "B"

    def test_score_at_grade_c_boundary(self):
        assert grade_for_score(55).grade == "C"

    def test_score_below_grade_c_boundary_gets_grade_d(self):
        assert grade_for_score(54.99).grade == "D"

    def test_score_zero_gets_grade_d(self):
        assert grade_for_score(0).grade == "D"

    def test_empty_grades_raises(self):
        with pytest.raises(ValueError):
            grade_for_score(72.6, grades=[])

    def test_custom_grades_are_respected(self):
        custom = [RateGrade(grade="X", min_score=50, discount_bp=99, label="custom")]
        assert grade_for_score(72.6, grades=custom).grade == "X"


class TestDiscountBpForScore:
    def test_matches_grade_discount(self):
        assert discount_bp_for_score(80) == 20
        assert discount_bp_for_score(70) == 12
        assert discount_bp_for_score(60) == 6
        assert discount_bp_for_score(10) == 0


class TestRateGradesTable:
    def test_sorted_descending_by_min_score(self):
        scores = [band.min_score for band in RATE_GRADES]
        assert scores == sorted(scores, reverse=True)

    def test_last_grade_covers_zero(self):
        assert RATE_GRADES[-1].min_score == 0
