from score.scripts import run_real_axis_a


def test_diagnostic_uses_tracked_service_vessels_without_legacy_file(monkeypatch):
    expected = [{"vesselId": "V1"}]
    monkeypatch.setattr(
        run_real_axis_a,
        "load_real_vessel_records",
        lambda: expected,
    )

    assert run_real_axis_a.load_service_vessels() == expected
    assert not hasattr(run_real_axis_a, "VESSELS_PATH")
