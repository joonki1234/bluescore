"""
담당: 최지희

개선 시뮬레이터의 사전계산 표(`adapter.simulate_surface`) 회귀 테스트.

이 표는 브라우저(iframe 안 JS)가 슬라이더를 움직일 때 조회하는 유일한 값
출처다. 화면이 서버를 왕복하지 않는 대신, 아래 두 가지가 깨지면 시연 중에
바로 티가 난다.

    1. 격자에 빠진 조합이 있으면 → 슬라이더가 그 칸에 서는 순간 화면이 빈다
    2. 표의 값이 `simulate()`와 다르면 → "adapter가 유일한 계산 창구"라는
       전제가 무너진다 (브라우저가 자기 숫자를 갖게 된다)

그래서 전수로 대조한다.
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

    2026-08-17 실측 결과, 지금의 잠정 계수에서 반작용은 이득을 **줄이기만 하고
    부호를 뒤집지 못한다** (속도 1노트당 순 +0.60점, 연속조업 1회당 순 +3.71점).
    따라서 `explain/TODO.md` 시연 구성 ③번의 "최고점은 중간에 있고 끝에서는
    떨어진다"는 지금 계수로는 **성립하지 않는다** — 화면도 그렇게 말하지 않는다.

    score/의 실제 계수(`score/tradeoff_coefficients.py`)로 교체되면 이 성질이
    바뀔 수 있다. 그때 아래 테스트가 실패하면서 시연 문구를 다시 볼 기회를 준다.
    """

    def test_tradeoff_reduces_the_gain_but_does_not_reverse_it(self):
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        row = surface["revisits"][0]
        cells = [surface["grid"][f"{row}|{s:.1f}"] for s in surface["speeds"]]

        # 반작용을 넣은 점수는 뺀 점수보다 항상 낮거나 같다 (대가는 항상 음수 방향)
        assert all(c["score"] <= c["scoreNoTradeoff"] + 1e-9 for c in cells)
        # 그런데도 감속 방향으로는 계속 오른다 — 즉 부호가 뒤집히지 않는다
        scores = [c["score"] for c in cells]
        assert scores[0] == max(scores), (
            "최적점이 더 이상 구간 끝이 아닙니다. 계수가 바뀐 것으로 보이니 "
            "시뮬레이터 곡선 문구(components._SIMULATOR_HTML)와 시연 구성 ③번을 "
            "다시 확인하세요."
        )

    def test_tradeoff_cost_is_actually_nonzero_somewhere(self):
        """대가가 0이면 점선과 실선이 겹쳐 화면에서 아무것도 못 보여준다."""
        vessel = _vessel()
        surface = adapter.simulate_surface(vessel)
        gaps = [c["scoreNoTradeoff"] - c["score"] for c in surface["grid"].values()]
        assert max(gaps) > 0.5, "반작용이 눈에 보일 만큼 크지 않습니다."
