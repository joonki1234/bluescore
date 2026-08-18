"""해양기상 수집 — 전국 관측지점의 기상센서정보.

사용자 제공 공식 매뉴얼(marineweather.nmpnt.go.kr) 기준. 지방청(mmaf)
단위로 소속 관측지점(mmsi)을 콤마로 묶어 한 번에 조회한다 — 지점별로
따로 호출하지 않음(GFW Events 배치 조회와 같은 효율 원칙).

`dataType=2`를 쓴다 — 수집원칙(PROCESS_LOG.md 10번) 결정사항: 기본값(1)은
결측/미관측 항목을 응답에서 아예 빼버려 원칙1(원본 그대로 저장)과 충돌
소지가 있음. 2는 "미제공"(장비 없음)과 "데이터없음"(장비는 있으나 결측)을
구분해서 다 보여줌.

`mmsi` 파라미터는 선박 MMSI가 아니라 관측지점(등대·등부표) 코드다(매뉴얼
용어 그대로 씀, 우리 스키마의 선박 MMSI와 혼동 주의).

사용법:
    python marine_weather.py                  # 최신 관측치
    python marine_weather.py --date 20260810   # 특정 날짜
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from http_common import request_with_retry, save_snapshot

BASE_NOW = "http://marineweather.nmpnt.go.kr:8001/openWeatherNow.do"
BASE_DATE = "http://marineweather.nmpnt.go.kr:8001/openWeatherDate.do"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "marine_weather"

# 지방청(mmaf) -> 소속 관측지점(mmsi) 목록. 출처: 사용자 제공 OPEN API 매뉴얼
# "관측지점 목록"(2026-08-17). API로 조회하는 방법이 없어 매뉴얼 원문을 그대로 옮김.
STATIONS = {
    "101": "1019001,1019002,1019003,1019004,994401578,994401579,994401583,994401584,994401587,994401588,994401594,994401597",
    "102": "0010,0020,1021000,1021013,1021014,1021018,1021024,1021040,1029001,994401001,994401015,994401020,994401021,994401022,994401023,994401039",
    "103": "1030262,1030384,994402917,994402925",
    "104": "1041519",
    "105": "1051101,4402675,4402692,4422880",
    "106": "994401037,994401042",
    "107": "1079001,1079002,1079003,1079004,1079005,1079006,1079007,1079008",
    "108": "1083652,1085555,1086109,1086116,1089651,4406120,994403650,994403658,994403661",
    "109": "1091045,1095079,994401606,994401623",
    "110": "1103579,994403582",
    "111": "1119808,994403800,994403807,994403810",
    "112": "994403894,994403895,994403896,994403901",
    "113": "1139001,1139002,1139006,1139007,JJ,MR",
}


def already_done(date: str) -> set:
    """해당 날짜에 이미 성공적으로 받은 mmaf 목록(메타파일 스캔) — 실규모
    범위수집 중 끊겨도 이어서 하기 위함(원칙5)."""
    done = set()
    for f in glob.glob(str(RAW_DIR / "weather_mmaf*__*Z.meta.json")):
        meta = json.loads(Path(f).read_text(encoding="utf-8"))
        if meta.get("date") == date and meta.get("status_code", 0) < 400:
            done.add(meta.get("mmaf"))
    return done


def collect(api_key: str, date: str = None) -> None:
    url = BASE_DATE if date else BASE_NOW
    skip = already_done(date) if date else set()
    failed = []
    for mmaf, mmsi in STATIONS.items():
        if mmaf in skip:
            continue
        params = {
            "serviceKey": api_key,
            "resultType": "json",
            "mmaf": mmaf,
            "mmsi": mmsi,
            "dataType": "2",
        }
        if date:
            params["date"] = date

        resp = request_with_retry("GET", url, params=params)
        # resp.url엔 serviceKey가 그대로 박혀있어 메타에 못 씀(원칙4) — 직접 구성해서 키만 가림.
        safe_params = {**params, "serviceKey": "REDACTED"}
        meta = {"request_params": safe_params, "status_code": resp.status_code, "mmaf": mmaf, "date": date}

        if not resp.ok:
            failed.append((mmaf, resp.status_code))
            save_snapshot(RAW_DIR, f"weather_mmaf{mmaf}_FAILED", resp.content, meta)
            continue

        path = save_snapshot(RAW_DIR, f"weather_mmaf{mmaf}", resp.content, meta)
        n = len((resp.json().get("result") or {}).get("recordset") or [])
        print(f"mmaf={mmaf}: {n}개 지점 -> {path.name}")

    print(f"완료. 실패 {len(failed)}건.")
    if failed:
        print(f"실패 목록: {failed}")

    problems = _validate(api_key)
    if problems:
        print("검증 게이트 위반:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("검증 게이트 통과.")


def _validate(secret: str) -> list:
    problems = []
    for f in glob.glob(str(RAW_DIR / "weather_mmaf*__*Z.json")):
        text = Path(f).read_text(encoding="utf-8")
        if secret and secret in text:
            problems.append(f"인증키 노출: {f}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"원본 구조 깨짐(JSON 파싱 실패): {f}")
            continue
        if "result" not in data:
            problems.append(f"원본 구조 이상('result' 키 없음): {f}")

        meta_file = Path(f).with_name(Path(f).name[:-5] + ".meta.json")
        if meta_file.exists() and secret and secret in meta_file.read_text(encoding="utf-8"):
            problems.append(f"인증키 노출(메타): {meta_file}")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYYMMDD (미지정 시 최신 관측치)")
    args = parser.parse_args()

    key = os.environ.get("MARINE_WEATHER_API_KEY")
    if not key:
        raise SystemExit("MARINE_WEATHER_API_KEY가 .env에 없습니다.")
    collect(key, date=args.date)
