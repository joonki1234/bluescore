"""
담당: 김준기, 오동규

score/scripts/fit_power_regression.py 단위 테스트.
"""

import numpy as np
import pytest

from score.scripts.fit_power_regression import fit_power_law, load_tonnage_power_pairs


class TestFitPowerLaw:
    def test_recovers_known_power_law_exactly(self):
        # P = 10 * GT^0.5 을 잡음 없이 그대로 넣으면 회귀가 정확히 복원해야 한다.
        tonnages = [10, 20, 50, 100, 200]
        pairs = [(gt, 10 * gt**0.5) for gt in tonnages]
        fit = fit_power_law(pairs)
        assert fit["a"] == pytest.approx(10.0, rel=1e-6)
        assert fit["b"] == pytest.approx(0.5, rel=1e-6)
        assert fit["r_squared"] == pytest.approx(1.0, abs=1e-6)
        assert fit["n"] == 5

    def test_reports_sample_size(self):
        pairs = [(10, 50), (20, 80), (30, 100)]
        assert fit_power_law(pairs)["n"] == 3


class TestLoadTonnagePowerPairs:
    def test_loads_real_committed_tac_file(self):
        pairs = load_tonnage_power_pairs()
        assert len(pairs) > 1000
        for tonnage, power_kw in pairs[:5]:
            assert tonnage > 0
            assert power_kw > 0

    def test_deduplicates_by_vessel_number(self):
        # 실제 파일 기준 어선 번호 dedupe가 됐는지 — 총 쌍 수가 TAC 원본
        # 전체 행수(5,794)보다 훨씬 적어야 한다(같은 배가 여러 할당을 가짐).
        pairs = load_tonnage_power_pairs()
        assert len(pairs) < 5794
