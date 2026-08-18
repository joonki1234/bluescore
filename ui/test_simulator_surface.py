"""`adapter.simulate_surface` 사전계산표의 회귀 테스트.

모든 슬라이더 조합이 존재하고 `simulate()` 결과와 일치하는지 전수 검증한다.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from ui import adapter, theme

VESSEL_ID = "V-001"


class _InProcessApi:
    """HTTP 서버 대신 TestClient를 쓰되 adapter에는 REST 응답만 보이게 한다."""

    def __init__(self, client):
        self.client = client

    def config(self):
        return self.client.get("/config").json()

    def list_vessels(self, source_type="demo"):
        return self.client.get("/vessels", params={"sourceType": source_type}).json()

    def score(self, vessel_id, source_type="demo"):
        return self.client.get(
            f"/vessels/{vessel_id}/score", params={"sourceType": source_type}
        ).json()

    def simulation_surface(self, vessel_id):
        return self.client.get(f"/vessels/{vessel_id}/simulation-surface").json()

    def simulate(self, vessel_id, revisit_count, speed_knots):
        return self.client.post(
            f"/vessels/{vessel_id}/simulate",
            json={"revisitCount": revisit_count, "speedKnots": speed_knots},
        ).json()


@pytest.fixture(autouse=True)
def _api_backend(monkeypatch, tmp_path):
    client = TestClient(create_app(tmp_path / "ui.db"))
    monkeypatch.setattr(adapter, "_api", _InProcessApi(client))
    adapter.clear_cache()
    yield
    adapter.clear_cache()


def _vessel():
    for v in adapter.load_dataset()["vessels"]:
        if adapter.is_scored(v):
            return v
    raise AssertionError("점수가 산출된 mock 선박이 없습니다.")


class TestGradeBandMatchesScoreModule:
    """
    금리구간 판정은 `score/rate_mapping.py`에 정식 구현이 이미 있다.

    화면은 아직 `theme.grade_band()`(mock JSON의 rateGrades를 읽는 잠정 구현)를
    쓰고 있는데, 두 구현의 경계값이 갈리면 시뮬레이터가 보여주는 우대구간과
    score/가 계산할 구간이 달라진다. `explain/TODO.md` 4단계에서 rate_mapping을
    정식 경로로 붙일 때까지, 최소한 판정 결과가 같은지는 지켜본다.
    """

    def test_matches_across_full_score_range(self):
        from score.rate_mapping import grade_for_score

        grades = adapter.load_dataset()["rateGrades"]
        for tenth in range(0, 1001):
            score = tenth / 10.0
            assert theme.grade_band(score, grades)["grade"] == grade_for_score(score).grade, (
                f"{score}점에서 theme(화면)과 score/rate_mapping의 구간 판정이 갈립니다."
            )


class TestSurfaceCoversEverySliderPosition:
    def test_no_missing_cell(self):
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        missing = [
            f"{r}|{s:.1f}"
            for r in surface["revisits"]
            for s in surface["speeds"]
            if f"{r}|{s:.1f}" not in surface["grid"]
        ]
        assert not missing, f"격자에 빠진 조합: {missing[:5]}"

    def test_speed_axis_matches_slider_domain(self):
        vessel = _vessel()
        speeds = adapter.simulate_speed_axis(vessel)
        base = vessel["averageSpeedKnots"]
        assert speeds[0] == round(base - adapter.SIM_SPEED_DELTA_DOWN, 1)
        assert speeds[-1] == round(base + adapter.SIM_SPEED_DELTA_UP, 1)
        # 슬라이더는 인덱스로 움직이므로 눈금이 균일해야 한다.
        gaps = {round(b - a, 1) for a, b in zip(speeds, speeds[1:])}
        assert gaps == {adapter.SIM_SPEED_STEP}

    def test_base_position_exists_in_grid(self):
        """기본값(배가 실제로 하던 조업)이 격자 위에 정확히 올라와 있어야 한다."""
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        key = f"{surface['base']['revisit']}|{surface['base']['speed']:.1f}"
        assert key in surface["grid"]
        assert surface["grid"][key]["score"] == vessel["blueScore"]


class TestSurfaceValuesMatchSimulate:
    """표의 모든 칸이 simulate()의 반환값과 정확히 같아야 한다."""

    def test_every_cell_matches(self):
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        for r in surface["revisits"]:
            for s in surface["speeds"]:
                cell = surface["grid"][f"{r}|{s:.1f}"]
                sim = adapter.simulate(vessel, r, s)
                assert cell["score"] == sim.score
                assert cell["topPercent"] == sim.top_percent
                assert cell["scoreDelta"] == sim.score_delta
                assert cell["fuelDeltaPercent"] == sim.fuel_delta_percent
                assert cell["tradeoffNotes"] == sim.tradeoff_notes

    def test_savings_follow_the_rate_table(self):
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        base_bp = surface["base"]["discountBp"]
        for cell in surface["grid"].values():
            gained = cell["discountBp"] - base_bp
            expected = int(adapter.EXAMPLE_PRINCIPAL_WON * gained / 10000)
            assert cell["yearlyWon"] == expected
            assert cell["totalWon"] == expected * adapter.EXAMPLE_TERM_YEARS


class TestTradeoffIsVisibleInTheSurface:
    """
    축 간 반작용이 표 위에서 실제로 어떻게 작동하는지 고정한다.

    `services/scoring.py`가 `score/tradeoff_coefficients.py`의 실제 물리식
    기반 계수를 쓰는 현재 기준으로, `explain/TODO.md` 시연 구성 ③번("최고점은
    중간에 있고 끝에서는 떨어진다")이 성립한다 — VESSEL_A 기준 최고점이 구간
    끝이 아니라 속도 8.6kn(구간 7.4~12.4kn 중간쯤)에서 나온다.

    다만 "반작용은 항상 손해만 준다"는 가정은 전역적으로 참이 아니다 — 고속
    구간(약 11.5kn 이상) 10개 셀에서 반작용 있는 점수가 없는 점수보다
    미세하게(0.1~0.7점) 더 높게 나온다. 원인은 B축 계수가 커서 바닥값(4.0)에
    양쪽 다 걸리는 구간이 넓어졌고, 그 구간에서는 B축 차이가 사라지면서 A축
    쪽의 `AXIS_A_COST_PER_KNOT`(속도를 올리면 A축이 오히려 오른다는,
    `score/tradeoff_coefficients.py` 독스트링에 이미 "코드베이스에 근거
    공식이 없다"고 적힌 미검증 계수)가 그대로 드러나기 때문이다. A축 계수는
    이번 범위 밖이라 고치지 않고, 아래에서 그 크기가 작다는 것만 회귀로
    지켜본다.
    """

    def test_peak_is_interior_not_at_either_edge(self):
        """③번 "최고점은 중간에 있고 끝에서는 떨어진다"가 실제로 성립하는지 고정한다."""
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        row = surface["revisits"][0]
        cells = [surface["grid"][f"{row}|{s:.1f}"] for s in surface["speeds"]]
        scores = [c["score"] for c in cells]

        peak = max(scores)
        assert scores[0] < peak and scores[-1] < peak, (
            "최고점이 구간 끝에 있습니다. 계수가 바뀐 것으로 보이니 "
            "시뮬레이터 곡선 문구(components._SIMULATOR_HTML)와 시연 구성 ③번을 "
            "다시 확인하세요."
        )

    def test_tradeoff_violation_is_small_and_localized(self):
        """반작용이 손해를 안 주는(오히려 미세하게 이득인) 셀이 있다는 걸 알고
        지켜본다 — AXIS_A_COST_PER_KNOT이 미검증 계수라 생기는 부작용
        (클래스 독스트링 참고). 이 폭이 갑자기 커지면 뭔가 달라진 것이다."""
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        row = surface["revisits"][0]
        cells = [surface["grid"][f"{row}|{s:.1f}"] for s in surface["speeds"]]

        violations = [c["score"] - c["scoreNoTradeoff"] for c in cells if c["score"] > c["scoreNoTradeoff"] + 1e-9]
        assert len(violations) <= len(cells) // 2, "반작용이 손해를 안 주는 셀이 절반을 넘습니다."
        assert max(violations, default=0.0) < 2.0, "반작용 역전 폭이 예상보다 큽니다."

    def test_tradeoff_cost_is_actually_nonzero_somewhere(self):
        """대가가 0이면 점선과 실선이 겹쳐 화면에서 아무것도 못 보여준다."""
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        gaps = [c["scoreNoTradeoff"] - c["score"] for c in surface["grid"].values()]
        assert max(gaps) > 0.5, "반작용이 눈에 보일 만큼 크지 않습니다."
