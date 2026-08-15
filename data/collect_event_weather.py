"""
담당: 김태윤

score/axis_b_baseline.py의 LightGBM 피처(seaSurfaceTempC 등)에 쓸 해양기상을
조업 이벤트에 붙이기 위한 1단계(수집)다. 이벤트에 값을 붙이는 가공은
data/attach_event_weather.py 몫이다(rules_common.md 1번 — 수집과 가공 분리).

대상 범위: 톤수가 있는 선박(data/raw/gfw_vessels_enriched.jsonl.gz의
tonnage != null)의 이벤트만. score/axis_b_physics.py가 톤수 없는 선박은
애초에 계산에서 스킵하므로(REQUIRED_PHYSICS_FIELDS), 톤수 없는 선박의
이벤트에 날씨를 붙여봤자 안 쓰인다 — 91만 건 전체가 아니라 이 부분집합만
받는 이유(2026-08-14 팀 논의: 매칭 끝난 뒤 진행하기로 한 결정과 동일 맥락).

효율화: 이벤트 1건마다 API를 부르지 않는다. 이벤트의 (위경도)로
find_nearest_station()을 먼저 로컬 계산(API 아님)하고, (관측지점, 날짜)
조합으로 중복 제거한 뒤 그 조합 단위로만 API를 부른다 — 2026-08-14 실측:
대상 이벤트 10,546건이 관측지점+날짜 조합으로는 2,354건까지 줄어듦.

진행상태 저장/재개(rules_common.md 6번): (station_code, date) 조합별로
파일 하나씩 저장하고, 이미 있으면 건너뛴다.

출력: data/raw/event_weather/<station_code>__<date>.json
    한 관측지점·한 날짜의 해양기상 원본(정규화된 형태, get_weather_by_date
    결과 그대로).
"""

import gzip
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.marine_weather_client import (  # noqa: E402
    MarineWeatherApiError,
    find_nearest_station,
    get_weather_by_date,
)
from data.snapshot_utils import find_latest  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
ENRICHED_VESSELS_PATH = RAW_DIR / "gfw_vessels_enriched.jsonl.gz"
EVENTS_PATH = find_latest(RAW_DIR, "gfw_events_20*.jsonl.gz")
OUTPUT_DIR = RAW_DIR / "event_weather"

# 선박 1척당 이벤트가 몰려있어도 API 부하는 관측지점 수에 비례하므로,
# 데이터고 쿼터 한도가 문서화돼 있지 않아 vessel_spec 수집 때와 동일하게
# 우선 10으로 시작.
MAX_WORKERS = 10


def tonnage_vessel_ids() -> set:
    """톤수(tonnage)가 있는 GFW 선박의 vesselId 집합. 이 모듈과
    data/attach_event_weather.py가 공유한다(둘 다 톤수 있는 선박만
    대상으로 하는 이유는 모듈 docstring 참고)."""
    ids = set()
    with gzip.open(ENRICHED_VESSELS_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            if v.get("tonnage") is not None:
                ids.add(v["vesselId"])
    return ids


def build_target_pairs() -> list:
    """(station_code, agency_code, date) 고유 조합 목록을 만든다.
    date는 이벤트의 start(YYYY-MM-DD...)에서 YYYYMMDD로 변환한다."""
    vessel_ids = tonnage_vessel_ids()
    pairs = {}

    with gzip.open(EVENTS_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("vesselId") not in vessel_ids:
                continue
            lat, lon, start = e.get("latitude"), e.get("longitude"), e.get("start")
            if lat is None or lon is None or not start:
                continue
            try:
                station = find_nearest_station(lat, lon)
            except ValueError:
                continue
            date = start[:10].replace("-", "")
            key = (station.station_code, station.agency_code, date)
            pairs[key] = pairs.get(key, 0) + 1

    return sorted(pairs.keys())


def fetch_one(station_code: str, agency_code: str, date: str) -> dict:
    """(station_code, agency_code, date) 하나를 조회한다.
    실제 재시도(429/5xx)는 marine_weather_client._call_weather_endpoint가
    이미 처리하므로 여기서는 결과만 감싼다."""
    try:
        records = get_weather_by_date(date=date, station_codes=station_code, agency_code=agency_code)
        return {"status": "ok", "records": records}
    except MarineWeatherApiError as exc:
        return {"status": "error", "error": {"status_code": exc.status_code, "details": str(exc.details)[:500]}}


def main():
    print("[1/2] 대상 (관측지점, 날짜) 조합 계산 중...")
    pairs = build_target_pairs()
    print(f"  대상 조합: {len(pairs)}건")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    to_fetch = []
    already_done = 0
    for station_code, agency_code, date in pairs:
        out_path = OUTPUT_DIR / f"{station_code}__{date}.json"
        if out_path.exists():
            already_done += 1
            continue
        to_fetch.append((station_code, agency_code, date))
    print(f"  이미 받아둔 것: {already_done}건, 새로 받을 것: {len(to_fetch)}건")

    if not to_fetch:
        print("[complete] 더 받을 게 없습니다.")
        return

    print("[2/2] 수집 중...")
    lock = threading.Lock()
    done_count = 0
    error_count = 0
    consecutive_errors = 0
    stop_flag = False
    t0 = time.time()

    def worker(station_code, agency_code, date):
        result = fetch_one(station_code, agency_code, date)
        return station_code, agency_code, date, result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(worker, *item): item for item in to_fetch}
        for future in as_completed(futures):
            if stop_flag:
                future.cancel()
                continue
            station_code, agency_code, date, result = future.result()

            with lock:
                if result["status"] == "ok":
                    out_path = OUTPUT_DIR / f"{station_code}__{date}.json"
                    out_path.write_text(
                        json.dumps(
                            {"stationCode": station_code, "agencyCode": agency_code, "date": date, "records": result["records"]},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    consecutive_errors = 0
                else:
                    error_count += 1
                    consecutive_errors += 1
                    if consecutive_errors >= 20:
                        print("[warn] 에러 20회 연속 — 쿼터 소진 등 구조적 문제일 수 있음. 중단합니다.")
                        stop_flag = True
                        for pending in futures:
                            pending.cancel()

                done_count += 1
                if done_count % 200 == 0:
                    elapsed = time.time() - t0
                    print(f"  [progress] {done_count}/{len(to_fetch)}, 에러={error_count}, {elapsed:.0f}s 경과")

    print(f"[complete] 완료 {done_count}/{len(to_fetch)}, 에러 {error_count}건, {time.time()-t0:.0f}초 소요")


if __name__ == "__main__":
    main()
