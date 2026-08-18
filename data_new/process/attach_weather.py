"""해양기상 부착 — 조업이벤트에 가장 가까운 관측소·시각의 해양기상을 붙인다.

⚠ 시간 정합성 주의: `collect/marine_weather.py`를 `--date` 없이 돌리면
"최신"(수집 시점) 값만 나와서, 몇 주 전 이벤트에 붙이면 시간이 안 맞는
값을 붙이는 꼴이 된다. 이벤트가 걸친 날짜들로 `--date YYYYMMDD`를 따로
수집해야 한다.

날짜별 조회(`openWeatherDate`)는 최신조회와 응답 구조가 다르다 — 지점당
값 1개가 아니라 **그 날 하루 전체의 10분 단위 시계열**이 옴(실측 확인:
12지점 x 144건 = 1,728건, PROCESS_LOG.md 참고). 그래서 이벤트 시각에
가장 가까운 시간대를 골라야 한다.

raw/는 읽기만 한다. processed/에 새로 쓰며 재실행 시 덮어써도 무방.

사용법:
    python attach_weather.py --start 20260401 --end 20260814
    (그 기간 raw/marine_weather/*가 미리 collect/marine_weather_range.py로
    수집돼 있어야 함. 이벤트 날짜인데 해당 날짜 기상이 없으면 그만큼
    부착 불가로 집계만 되고 건너뜀 — 3월 이벤트 780건이 그런 경우, 30번 참고)
"""

from __future__ import annotations

import argparse
import glob
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

RAW_WEATHER_DIR = Path(__file__).resolve().parent.parent / "raw" / "marine_weather"
EVENTS_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_events_normalized.jsonl"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "events_with_weather.jsonl"

WEATHER_FIELDS = [
    "WIND_DIRECT", "WIND_SPEED", "SURFACE_CURR_DRC", "SURFACE_CURR_SPEED",
    "WAVE_DRC", "WAVE_HEIGTH", "AIR_TEMPERATURE", "HUMIDITY", "AIR_PRESSURE",
    "WATER_TEMPER", "SALINITY", "HORIZON_VISIBL",
]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _load_stations_for_date(date_str: str) -> list:
    """해당 날짜에 수집된(파일 메타의 date 파라미터로 필터) 관측소 시계열을 모은다."""
    stations = []
    for f in glob.glob(str(RAW_WEATHER_DIR / "weather_mmaf*__*Z.json")):
        meta_path = Path(f).with_name(Path(f).name[:-5] + ".meta.json")
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("date") != date_str:
            continue
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for rec in (data.get("result") or {}).get("recordset") or []:
            lat, lon = rec.get("LATITUDE"), rec.get("LONGITUDE")
            if lat in (None, "", "0") or lon in (None, "", "0"):
                continue
            stations.append(rec)
    return stations


def _group_by_station(stations: list) -> dict:
    by_station = {}
    for s in stations:
        by_station.setdefault(s["MMSI_CODE"], []).append(s)
    return by_station


def _nearest_reading(event_lat, event_lon, event_dt, by_station: dict):
    """이벤트 위치에서 가장 가까운 관측소를 먼저 고르고, 그 관측소 시계열
    중 이벤트 시각에 가장 가까운 레코드를 반환한다. by_station은 하루치
    관측소 시계열을 미리 묶어둔 것 — 이벤트마다 다시 묶으면(실측, 하루
    ~1,700건 x 이벤트 수만큼) 실규모에서 너무 느려 호출부에서 날짜당
    한 번만 묶어 넘긴다."""
    best_station, best_dist = None, None
    for mmsi, recs in by_station.items():
        r0 = recs[0]
        dist = _haversine_km(event_lat, event_lon, float(r0["LATITUDE"]), float(r0["LONGITUDE"]))
        if best_dist is None or dist < best_dist:
            best_dist, best_station = dist, mmsi

    candidates = by_station[best_station]
    best_rec, best_dt_diff = None, None
    for rec in candidates:
        rec_dt = datetime.strptime(rec["DATETIME"], "%Y%m%d%H%M%S")
        diff = abs((rec_dt - event_dt).total_seconds())
        if best_dt_diff is None or diff < best_dt_diff:
            best_dt_diff, best_rec = diff, rec

    return best_rec, best_dist, best_dt_diff


def run(dates: list) -> None:
    """실규모(여러 날짜) 대응 — 원래 단일 --date만 받던 버전은 OUT_PATH를
    "w"로 매번 덮어써서 날짜별로 반복 호출하면 마지막 날짜 결과만 남는
    버그가 있었다. 이벤트를 한 번만 읽어 날짜별로 묶고, 날짜마다 그날
    관측소만 로드해 매칭한 뒤 한 파일에 누적한다."""
    events_by_date = {}
    with EVENTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if not event["start"]:
                continue
            events_by_date.setdefault(event["start"][:10], []).append(event)

    n_matched = 0
    n_total = 0
    n_no_weather = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for date_str in dates:
            iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            events = events_by_date.get(iso_date, [])
            if not events:
                continue
            stations = _load_stations_for_date(date_str)
            if not stations:
                n_no_weather += len(events)
                continue
            by_station = _group_by_station(stations)

            for event in events:
                n_total += 1
                if event["latitude"] is None or event["longitude"] is None:
                    continue
                event_dt = datetime.fromisoformat(event["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                rec, dist_km, dt_diff_sec = _nearest_reading(event["latitude"], event["longitude"], event_dt, by_station)

                enriched = dict(event)
                enriched["weatherStationDistanceKm"] = round(dist_km, 1)
                enriched["weatherTimeDiffMinutes"] = round(dt_diff_sec / 60, 1)
                for field in WEATHER_FIELDS:
                    enriched[f"weather_{field}"] = rec.get(field)
                out.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                n_matched += 1

    print(f"이벤트 {n_total}건 중 {n_matched}건에 해양기상 부착, "
          f"해당 날짜 기상 없음(부착 불가) {n_no_weather}건 -> {OUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYYMMDD (포함)")
    parser.add_argument("--end", required=True, help="YYYYMMDD (포함)")
    args = parser.parse_args()

    d0 = datetime.strptime(args.start, "%Y%m%d")
    d1 = datetime.strptime(args.end, "%Y%m%d")
    date_list = []
    d = d0
    while d <= d1:
        date_list.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    run(date_list)
