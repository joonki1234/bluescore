"""
담당: 김준기, 오동규

score/real_axis_b_scoring.py 단위 테스트.
"""

from score.axis_b_baseline import VesselAxisBResult
from score.real_axis_b_scoring import compute_axis_b_results


class TestComputeAxisBResults:
    def test_returns_results_for_real_data_new_snapshot(self):
        results = compute_axis_b_results()
        assert len(results) > 5000
        assert all(isinstance(r, VesselAxisBResult) for r in results.values())

    def test_cached_call_returns_same_object(self):
        first = compute_axis_b_results()
        second = compute_axis_b_results()
        assert first is second

    def test_some_vessels_have_used_rows(self):
        # 태윤님이 data_new/ 매칭을 GFW-TAC 한글 직접비교 단일 소스로 바꾸면서
        # 톤수 매칭 커버리지가 43.4%(2,278척대)에서 23.2%(1,234척)로 줄었다
        # (CLAUDE.md 참고, final_vessel_matches.jsonl 재생성). 임계값도 그에
        # 맞춰 낮춘다 — 여전히 "일부 선박은 B축 계산이 된다"만 확인하면 된다.
        results = compute_axis_b_results()
        used = [r for r in results.values() if r.used_row_count > 0]
        assert len(used) > 1000
