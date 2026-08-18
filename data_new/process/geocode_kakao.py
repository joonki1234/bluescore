"""카카오 로컬 API(키워드 장소검색) 지오코딩 — TAC 항구명의 유일한
지오코딩 경로(match_fuzzy_name.py에서 씀). 일반 장소검색이라 "대천항"
같은 항구 고유명사도 대부분 찾는다(TAC 위치확인율 96.4%). 단
"부산직"처럼 원본 데이터 자체가 잘린 문자열은 못 찾는다(지오코딩
문제가 아니라 데이터 정제 문제).

결과를 로컬 JSON에 캐싱한다 — 같은 지명이 TAC 여러 행에서 반복
등장하고, 재실행할 때마다 API를 또 부르는 건 낭비라서. 실패(결과
없음)도 캐싱해서 매번 재시도 안 한다.

사용법 (단독 실행 시 캐시 미리 채우기):
    python geocode_kakao.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
CACHE_PATH = Path(__file__).resolve().parent.parent / "processed" / "kakao_geocode_cache.json"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


_CACHE = _load_cache()


def geocode_kakao(query: str) -> tuple | None:
    """장소명 -> (lat, lon). 캐시 우선, 없으면 API 호출 후 캐싱(실패도 캐싱)."""
    if not query:
        return None
    if query in _CACHE:
        return tuple(_CACHE[query]) if _CACHE[query] else None

    key = os.environ.get("KAKAO_API_KEY")
    if not key:
        return None

    try:
        resp = requests.get(
            KAKAO_URL,
            headers={"Authorization": f"KakaoAK {key}"},
            params={"query": query, "size": 1},
            timeout=10,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents") or []
    except (requests.RequestException, ValueError):
        return None

    if not docs:
        _CACHE[query] = None
        _save_cache(_CACHE)
        return None

    lat, lon = float(docs[0]["y"]), float(docs[0]["x"])
    _CACHE[query] = [lat, lon]
    _save_cache(_CACHE)
    return (lat, lon)


if __name__ == "__main__":
    from match_fuzzy_name import _load_jsonl, TAC_PATH  # noqa: E402

    names = set()
    for t in _load_jsonl(TAC_PATH):
        for p in t.get("portNamesTac") or []:
            names.add(p)

    names = sorted(names)
    print(f"고유 지명 {len(names)}개, 카카오로 캐시 미리 채우기...")
    found = 0
    for i, name in enumerate(names):
        coord = geocode_kakao(name)
        if coord:
            found += 1
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(names)} (지금까지 {found}개 해결)")
    print(f"완료: {found}/{len(names)} 해결 -> {CACHE_PATH}")
