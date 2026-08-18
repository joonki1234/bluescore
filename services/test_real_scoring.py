"""

실데이터 A축 어댑터의 작은 결정론적 회귀 테스트.
"""

import gzip
import json

from services.real_scoring import RealAxisAAdapter, compute_axis_a_for_vessel


def _vessels():
    return [
        {"vesselId": vessel_id, "name": vessel_id, "tonnage": 25, "fishingType": "POT"}
        for vessel_id in ("R1", "R2", "R3")
    ]


def _event(vessel_id, event_id, start, latitude=35.1, longitude=128.1):
    return {
        "vesselId": vessel_id,
        "eventId": event_id,
        "start": start,
        "latitude": latitude,
        "longitude": longitude,
    }


def test_real_axis_a_pipeline_connects_raw_peer_and_score():
    events = [
        _event("R1", "1", "2026-05-01T00:00:00Z"),
        _event("R1", "2", "2026-05-01T06:00:00Z"),
        _event("R2", "3", "2026-05-01T00:00:00Z", 35.2, 128.2),
        _event("R2", "4", "2026-05-02T00:00:00Z", 35.2, 128.2),
        _event("R3", "5", "2026-05-01T00:00:00Z", 35.3, 128.3),
        _event("R3", "6", "2026-05-03T00:00:00Z", 35.3, 128.3),
    ]

    result = compute_axis_a_for_vessel("R1", _vessels(), events, min_peer_size=3)

    assert result.status == "partial"
    assert result.peer_count == 3
    assert result.axis_a_raw is not None
    assert result.axis_a_score is not None
    assert result.used_event_count == 2


def test_real_axis_a_does_not_invent_score_without_events():
    result = compute_axis_a_for_vessel("R1", _vessels(), [], min_peer_size=1)
    assert result.status == "matchingFailed"
    assert result.axis_a_score is None
    assert result.matching_reason


def test_shap_factors_populated_for_axis_a_only():
    """A축 요인 기여도(SHAP) 실연결 테스트 — B축은 연결 안 하므로
    axis="b"가 섞이면 안 된다."""
    events = [
        _event("R1", "1", "2026-05-01T00:00:00Z"),
        _event("R1", "2", "2026-05-01T06:00:00Z"),
        _event("R2", "3", "2026-05-01T00:00:00Z", 35.2, 128.2),
        _event("R2", "4", "2026-05-02T00:00:00Z", 35.2, 128.2),
        _event("R3", "5", "2026-05-01T00:00:00Z", 35.3, 128.3),
        _event("R3", "6", "2026-05-03T00:00:00Z", 35.3, 128.3),
    ]

    result = compute_axis_a_for_vessel("R1", _vessels(), events, min_peer_size=3)

    assert len(result.shap_factors) == 3
    assert all(f["axis"] == "a" for f in result.shap_factors)


def test_shap_factors_empty_when_matching_failed():
    result = compute_axis_a_for_vessel("R1", _vessels(), [], min_peer_size=1)
    assert result.shap_factors == []


def test_adapter_uses_tracked_sources_without_derived_vessel_file(tmp_path, monkeypatch):
    matches_path = tmp_path / "final_vessel_matches.jsonl"
    gfw_path = tmp_path / "gfw_vessels_normalized.jsonl"
    events_path = tmp_path / "events_with_weather.jsonl.gz"
    matches_path.write_text(
        json.dumps(
            {
                "gfwVesselId": "R1",
                "gfwName": "REAL ONE",
                "matchTier": "verified",
                "matchConfidence": "high",
                "tac": {"tonnageGtTac": "25"},
                "mof": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gfw_path.write_text(
        json.dumps({"vesselId": "R1", "combinedGearTypes": ["POTS_AND_TRAPS"]}) + "\n",
        encoding="utf-8",
    )
    with gzip.open(events_path, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(_event("R1", "1", "2026-05-01T00:00:00Z")) + "\n")

    monkeypatch.setattr("services.real_scoring.compute_axis_b_results", lambda: {})
    adapter = RealAxisAAdapter(
        events_path=events_path,
        matches_path=matches_path,
        gfw_vessels_path=gfw_path,
    )

    assert adapter.available is True
    assert adapter.list_vessels()[0]["matchConfidence"] == "high"
    assert adapter.score("R1").vessel["name"] == "REAL ONE"


def test_adapter_availability_requires_both_tracked_vessel_sources(tmp_path):
    events_path = tmp_path / "events.jsonl.gz"
    matches_path = tmp_path / "matches.jsonl"
    events_path.touch()
    matches_path.touch()

    adapter = RealAxisAAdapter(
        events_path=events_path,
        matches_path=matches_path,
        gfw_vessels_path=tmp_path / "missing-gfw.jsonl",
    )

    assert adapter.available is False

