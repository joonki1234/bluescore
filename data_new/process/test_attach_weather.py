import gzip
import json

from data_new.process import attach_weather


def test_run_writes_the_tracked_gzip_service_snapshot(tmp_path, monkeypatch):
    events_path = tmp_path / "gfw_events_normalized.jsonl"
    output_path = tmp_path / "events_with_weather.jsonl.gz"
    event = {
        "eventId": "E1",
        "start": "2026-04-01T00:00:00Z",
        "latitude": 35.0,
        "longitude": 128.0,
    }
    events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    reading = {field: "1" for field in attach_weather.WEATHER_FIELDS}

    monkeypatch.setattr(attach_weather, "EVENTS_PATH", events_path)
    monkeypatch.setattr(attach_weather, "OUT_PATH", output_path)
    monkeypatch.setattr(
        attach_weather,
        "_load_stations_for_date",
        lambda date: [reading],
    )
    monkeypatch.setattr(
        attach_weather,
        "_group_by_station",
        lambda stations: {"station": stations},
    )
    monkeypatch.setattr(
        attach_weather,
        "_nearest_reading",
        lambda *args: (reading, 2.5, 60.0),
    )

    attach_weather.run(["20260401"])

    with gzip.open(output_path, "rt", encoding="utf-8") as stream:
        enriched = json.loads(stream.read())
    assert enriched["eventId"] == "E1"
    assert enriched["weatherStationDistanceKm"] == 2.5
    assert enriched["weather_WIND_SPEED"] == "1"
