"""한국 행정구역명(시군구) -> 중심좌표 지오코딩.

data_new/reference/sigungu_centroids_2017.csv 출처: cubensys/Korea_District
(대한민국_기초자치단체_중심점_2017, CC 공개 저장소). TAC `portNamesTac`이
항구명이 아니라 행정구역명("경주시 감포읍" 등)인 경우가 많아서(46번,
어항정보 113개 리스트로는 3.6%만 커버) 이 표로 폴백한다.

매칭 방식: 문자열 토큰으로 쪼개 시군구명이 있는지 찾는다. 같은 이름(예:
"중구")이 여러 도시에 있어 모호하면 포기한다(틀린 좌표를 주느니 모르는
게 낫다 — 원칙4와 같은 결로).

ponytail: 읍/면/동 단위까지는 안 내려감(시군구 중심점까지만) — 그래도
전국 규모 구분(예: 제주 vs 인천)에는 충분하고, 더 정밀한 좌표가
필요해지면 그때 읍면동 표로 교체.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

CENTROID_PATH = Path(__file__).resolve().parent.parent / "reference" / "sigungu_centroids_2017.csv"


def _load_sigungu() -> dict:
    table: dict[str, list[tuple[float, float]]] = {}
    with CENTROID_PATH.open(encoding="cp949") as f:
        for row in csv.DictReader(f):
            table.setdefault(row["SIG_KOR_NM"], []).append((float(row["Y"]), float(row["X"])))
    return table


_SIGUNGU = _load_sigungu()


def geocode(location_str: str) -> tuple | None:
    """행정구역 문자열 -> (lat, lon). 토큰을 못 찾거나 동명 시군구가 여럿이면 None."""
    if not location_str:
        return None
    tokens = re.split(r"[\s()]+", location_str)
    hits = [t for t in tokens if t in _SIGUNGU]
    if not hits:
        return None
    best = max(hits, key=len)
    candidates = _SIGUNGU[best]
    if len(candidates) != 1:
        return None
    return candidates[0]


if __name__ == "__main__":
    samples = ["경주시 감포읍", "부산광역시 동구", "제주시 한림읍", "인천광역시 남동구", "중구"]
    for s in samples:
        print(f"{s!r:20} -> {geocode(s)}")
