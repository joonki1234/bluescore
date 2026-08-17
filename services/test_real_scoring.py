"""담당: 최지희

실데이터 A축 어댑터의 작은 결정론적 회귀 테스트.
"""

from services.real_scoring import compute_axis_a_for_vessel


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

