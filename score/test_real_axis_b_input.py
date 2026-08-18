"""

score/real_axis_b_input.py 단위 테스트.

data_new/processed/의 실제 파일(이미 커밋됨)로 돈다 — mock을 안 쓰는 이유는
프로젝트 관례대로, 이미 리포에 있는 실제 산출물이면 그걸로 검증하는 게
필드 구조 가정이 실제와 어긋나는 걸 더 잘 잡아내기 때문이다.
"""

import pytest

from score.real_axis_b_input import (
    _to_float,
    build_axis_b_rows,
    load_vessel_tonnage_index,
)


class TestToFloat:
    def test_none_stays_none(self):
        assert _to_float(None) is None

    def test_missing_marker_becomes_none(self):
        assert _to_float("미제공") is None

    def test_empty_string_becomes_none(self):
        assert _to_float("") is None
        assert _to_float("   ") is None

    def test_numeric_string_converts(self):
        assert _to_float("14.5") == 14.5
        assert _to_float(".514") == pytest.approx(0.514)

    def test_non_numeric_string_becomes_none(self):
        assert _to_float("abc") is None

    def test_already_numeric_passes_through(self):
        assert _to_float(3) == 3.0
        assert _to_float(3.5) == 3.5


class TestLoadVesselTonnageIndex:
    def test_returns_float_or_none_per_vessel(self):
        index = load_vessel_tonnage_index()
        assert len(index) > 0
        for value in index.values():
            assert value is None or isinstance(value, float)

    def test_tac_and_mof_are_never_both_present(self):
        """tac와 mof가 동시에 채워지지 않는다는 전제를 회귀로 지켜본다 —
        이게 깨지면 score/TODO.md의 '우선순위/충돌 로직 불필요' 전제가
        무효화된다."""
        import json

        from score.real_axis_b_input import DEFAULT_MATCHES_PATH

        both_present = 0
        with DEFAULT_MATCHES_PATH.open(encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if record.get("tac") and record.get("mof"):
                    both_present += 1
        assert both_present == 0, (
            "tac와 mof가 동시에 채워진 행이 생겼습니다 — "
            "load_vessel_tonnage_index()의 우선순위 로직을 다시 검토하세요."
        )


@pytest.fixture(scope="module")
def rows():
    return build_axis_b_rows()


class TestBuildAxisBRows:
    def test_returns_one_row_per_event(self, rows):
        assert len(rows) > 0

    def test_every_row_has_expected_keys(self, rows):
        expected_keys = {
            "vesselId",
            "tonnageGt",
            "averageSpeedKnots",
            "durationHours",
            "totalDistanceKm",
            "windSpeedMs",
            "seaSurfaceTempC",
            "currentSpeedMs",
            "seaArea",
            "season",
            "gearType",
        }
        assert set(rows[0].keys()) == expected_keys

    def test_gear_type_is_always_none_for_now(self, rows):
        """gearType이 아직 채워지지 않는다는 전제의 회귀 확인 —
        gearType을 채우기 시작하면 이 테스트를 의도적으로 고쳐야 한다."""
        assert all(row["gearType"] is None for row in rows)

    def test_sea_area_is_string_not_tuple(self, rows):
        """튜플을 그대로 쓰면 LightGBM 카테고리 왕복에서 리스트로 망가져
        예측 단계가 죽는다(real_axis_b_input.py의 _sea_area_label() 참고) —
        이 회귀를 다시 안 겪기 위한 테스트."""
        labeled = [row["seaArea"] for row in rows if row["seaArea"] is not None]
        assert labeled, "seaArea가 전부 None입니다 — region_key() 계산이 실패하고 있을 수 있습니다."
        assert all(isinstance(value, str) for value in labeled)

    def test_season_is_half_year_label(self, rows):
        labeled = {row["season"] for row in rows if row["season"] is not None}
        assert labeled
        assert all(v.endswith("-H1") or v.endswith("-H2") for v in labeled)

    def test_some_rows_have_usable_tonnage(self, rows):
        """전부 None이면 병합 자체가 안 되고 있다는 뜻이라 조인이 깨진 것이다."""
        assert any(row["tonnageGt"] is not None for row in rows)

    def test_missing_weather_marker_never_leaks_through_as_string(self, rows):
        for row in rows:
            for key in ("windSpeedMs", "seaSurfaceTempC", "currentSpeedMs"):
                assert row[key] is None or isinstance(row[key], float)

    def test_works_end_to_end_with_axis_b_baseline(self, rows):
        """실제로 fit_baseline_model -> compute_axis_b_efficiency가 에러 없이
        도는지 확인한다 — score/scripts/run_real_axis_b.py가 하는 것의
        축소판."""
        from score.axis_b_baseline import compute_axis_b_efficiency, fit_baseline_model

        model, _ = fit_baseline_model(rows)
        results = compute_axis_b_efficiency(rows, model)
        assert len(results) > 0
        assert any(r.used_row_count > 0 for r in results.values())
