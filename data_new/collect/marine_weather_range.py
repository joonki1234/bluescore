"""해양기상 실규모 수집 — GFW 이벤트 수집기간(PROCESS_LOG.md 26번)과 같은
날짜범위를 하루씩 marine_weather.py의 collect()로 반복 호출한다.

날짜/mmaf 단위 재개는 marine_weather.py의 already_done()이 처리 — 중간에
끊겨도 그냥 다시 실행하면 이미 받은 (날짜,mmaf)는 건너뛴다.

사용법:
    python marine_weather_range.py --start 20260401 --end 20260814
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta

from marine_weather import collect

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYYMMDD (포함)")
    parser.add_argument("--end", required=True, help="YYYYMMDD (포함)")
    args = parser.parse_args()

    key = os.environ.get("MARINE_WEATHER_API_KEY")
    if not key:
        raise SystemExit("MARINE_WEATHER_API_KEY가 .env에 없습니다.")

    start = datetime.strptime(args.start, "%Y%m%d")
    end = datetime.strptime(args.end, "%Y%m%d")
    total_days = (end - start).days + 1
    d = start
    i = 0
    while d <= end:
        i += 1
        date_str = d.strftime("%Y%m%d")
        print(f"[{i}/{total_days}] {date_str}")
        collect(key, date=date_str)
        d += timedelta(days=1)
