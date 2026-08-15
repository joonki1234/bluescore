"""
담당: 김태윤

data/collect_event_weather.py가 모아둔 (관측지점, 날짜)별 해양기상 원본을
조업 이벤트에 실제로 붙이는 가공 단계다 (rules_common.md 1번 — 수집은
이미 끝났고, 여기서 이벤트-관측값 매칭 판단이 들어간다).

붙이는 방법: 이벤트의 위경도로 최근접 관측지점을 다시 계산하고(수집
때와 동일 로직, find_nearest_station), 그 관측지점의 그 날짜 레코드들
중 이벤트 시작시각(DATETIME)과 가장 가까운 것 하나를 고른다 — 하루에
144개(10분 간격)가 오므로 그중 제일 가까운 시각을 쓴다.

관측지점에 따라 센서 종류가 달라서(등대형은 풍향/풍속/기온/기압만,
부이형은 수온/해류/파고까지) 값이 없을 수 있다 — 이벤트별로 어떤 필드가
채워졌는지 그대로 두고 내려보낸다(값을 지어내지 않음).

출력: data/raw/gfw_events_with_weather.jsonl.gz
    이벤트 원본 필드 + weather{...}(관측값, 없으면 각 필드 null) +
    weatherStationCode + weatherObservedAt + weatherDistanceKm
    (이벤트 위치와 관측지점 사이 거리 — 너무 멀면 신뢰도 낮다는 신호로
    score팀이 활용할 수 있게 남긴다) + weatherTimeDiffMinutes(이벤트
    시작시각과 관측시각의 차이, 분 단위 — 마찬가지로 신뢰도 신호).
"""

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.collect_event_weather import tonnage_vessel_ids  # noqa: E402
from data.marine_weather_client import _haversine_km, find_nearest_station  # noqa: E402
from data.snapshot_utils import find_latest  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
EVENTS_PATH = find_latest(RAW_DIR, "gfw_events_20*.jsonl.gz")
WEATHER_DIR = RAW_DIR / "event_weather"
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_events_with_weather.jsonl.gz"

WEATHER_FIELDS = [
    "seaSurfaceTempC", "airTempC", "windDirectionDeg", "windSpeedMs",
    "humidityPercent", "pressureHpa", "currentDirectionDeg", "currentSpeedMs",
    "waveDirectionDeg", "waveHeightM", "salinity", "visibilityM",
    "tideSpeed", "tideDirectionDeg", "tideTendency",
]


def _parse_event_dt(start: str):
    try:
        return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_weather_dt(datetime_str: str):
    # DATETIME 형식: "20260814092000" (YYYYMMDDHHMMSS)
    try:
        return datetime.strptime(datetime_str, "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None


def _load_weather_file(station_code: str, date: str) -> dict:
    path = WEATHER_DIR / f"{station_code}__{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _closest_record(records: list, event_dt) -> dict:
    """레코드 목록(하루치, 10분 간격) 중 event_dt와 가장 가까운 걸 고른다.
    event_dt가 tz-aware일 수 있으므로 naive로 맞춰 비교한다."""
    if not records or event_dt is None:
        return None, None
    target = event_dt.replace(tzinfo=None) if event_dt.tzinfo else event_dt

    best_record, best_diff = None, None
    for r in records:
        rdt = _parse_weather_dt(r.get("observedAt"))
        if rdt is None:
            continue
        diff = abs((rdt - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff, best_record = diff, r
    return best_record, best_diff


def main():
    vessel_ids = tonnage_vessel_ids()
    print(f"[1/2] 대상 선박(톤수 있음): {len(vessel_ids)}척")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stats = {"attached": 0, "no_weather_file": 0, "no_matching_record": 0, "skipped_no_coords": 0, "not_target_vessel": 0}

    print("[2/2] 이벤트에 날씨 붙이는 중...")
    with gzip.open(EVENTS_PATH, "rt", encoding="utf-8") as fin, gzip.open(OUTPUT_PATH, "wt", encoding="utf-8") as fout:
        for line in fin:
            e = json.loads(line)
            if e.get("vesselId") not in vessel_ids:
                stats["not_target_vessel"] += 1
                continue

            record = dict(e)
            for field in WEATHER_FIELDS:
                record[field] = None
            record["weatherStationCode"] = None
            record["weatherObservedAt"] = None
            record["weatherDistanceKm"] = None
            record["weatherTimeDiffMinutes"] = None

            lat, lon, start = e.get("latitude"), e.get("longitude"), e.get("start")
            event_dt = _parse_event_dt(start) if start else None

            if lat is None or lon is None or event_dt is None:
                stats["skipped_no_coords"] += 1
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                continue

            station = find_nearest_station(lat, lon)
            date = start[:10].replace("-", "")
            weather_file = _load_weather_file(station.station_code, date)

            if weather_file is None:
                stats["no_weather_file"] += 1
            else:
                closest, diff_seconds = _closest_record(weather_file.get("records", []), event_dt)
                if closest is None:
                    stats["no_matching_record"] += 1
                else:
                    for field in WEATHER_FIELDS:
                        record[field] = closest.get(field)
                    record["weatherStationCode"] = station.station_code
                    record["weatherObservedAt"] = closest.get("observedAt")
                    record["weatherDistanceKm"] = round(
                        _haversine_km(lat, lon, station.latitude, station.longitude), 2
                    )
                    record["weatherTimeDiffMinutes"] = round(diff_seconds / 60, 1)
                    stats["attached"] += 1

            fout.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[output] {OUTPUT_PATH}")
    print("[summary]", stats)


if __name__ == "__main__":
    main()
