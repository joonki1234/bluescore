"""
담당: 김준기, 오동규

score/score_assembly.py 단위 테스트.
"""

import pytest

from score.peer_grouping import PeerGroup
from score.score_assembly import raw_to_score, score_status_for_group


class TestRawToScore:
    def test_empty_peer_raws_raises(self):
        with pytest.raises(ValueError):
            raw_to_score(5.0, [])

    def test_best_in_group_gets_full_percentile(self):
        # raw가 가장 낮음(제일 좋음) -> 전원이 자기보다 크거나 같음 -> 100%
        score = raw_to_score(1.0, [1.0, 5.0, 9.0])
        assert score == 97.0  # ceil에 걸림

    def test_worst_in_group_gets_low_percentile_but_floored(self):
        score = raw_to_score(9.0, [1.0, 5.0, 9.0])
        assert score == 33.3

    def test_middle_of_group(self):
        score = raw_to_score(5.0, [1.0, 5.0, 9.0])
        assert score == 66.7

    def test_respects_custom_floor_and_ceil(self):
        score = raw_to_score(1.0, [1.0, 5.0, 9.0], floor=0.0, ceil=100.0)
        assert score == 100.0


class TestScoreStatusForGroup:
    def test_sufficient_sample_is_success(self):
        group = PeerGroup(key=(20, "TRAWLERS", None, None), vessel_ids=[f"V{i}" for i in range(20)])
        assert score_status_for_group(group, min_size=20) == "success"

    def test_insufficient_sample_is_insufficient_sample(self):
        group = PeerGroup(key=(20, "TRAWLERS", None, None), vessel_ids=["V1"])
        assert score_status_for_group(group, min_size=20) == "insufficientSample"
