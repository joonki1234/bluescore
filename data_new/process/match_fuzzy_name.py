"""매칭 3단계 — 이름(+톤수 있으면 보너스) 다중신호 fuzzy 매칭.

조인키 설계(PROCESS_LOG.md 12번) 3단계. 1·2단계(정확일치)로 못 붙은
GFW 선박에 대해, TAC/어선원부/MOF의 한글 이름을 로마자로 변환한 뒤 GFW
자기신고 로마자명과 유사도를 비교한다. MOF는 이미 그 GFW 선박 이름으로
검색해서 나온 결과라(collect/mof.py) 전역 후보 풀이 아니라 해당 선박
전용 후보로만 추가한다.

**표준 로마자 변환 규칙을 안 따를 수 있다는 점 감안** — 자기신고자가
발음나는 대로 대충 썼을 수 있어, 변환 결과와
정확히 같아야 인정하지 않고 편집거리 기반 유사도 점수로 순위만 매긴다.
자동으로 accept/reject하지 않음 — 옛날 TAC 이름매칭이 정밀도 7.5~13.2%
한계에 부딪혔던 사례(PROCESS_LOG.md 1번)를 반복하지 않기 위해, 후보와
점수만 산출하고 임계값·최종 판정은 이후 결정으로 미룬다.

**한계**: GFW 쪽 톤수는 `registryInfo`가 있는 소수(우리 모집단 대부분
없음, PROCESS_LOG.md 9번)에만 있어, 톤수 교차확인은 "있으면 보너스" 수준
— 이름이 사실상 유일하게 항상 쓸 수 있는 신호다.

사용법:
    python match_fuzzy_name.py
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from korean_romanizer.romanizer import Romanizer

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
TAC_PATH = PROCESSED / "tac_vessels_normalized.jsonl"
REGISTRY_PATH = PROCESSED / "vessel_registry_normalized.jsonl"
MOF_PATH = PROCESSED / "mof_candidates_normalized.jsonl"
PORTS_PATH = PROCESSED / "ports_normalized.jsonl"
EVENTS_PATH = PROCESSED / "gfw_events_normalized.jsonl"
OUT_PATH = PROCESSED / "fuzzy_name_candidates.jsonl"

TOP_N = 3  # GFW 선박 1척당 남길 후보 수
# 항구까지 이 거리(km) 이내면 만점 보너스, 멀수록 선형으로 줄어듦. 잠정값.
LOCATION_BONUS_MAX_KM = 100.0


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _vessel_centroids(events: list) -> dict:
    """GFW vesselId별 조업이벤트 평균 위경도(활동해역 대표점)."""
    by_vessel = defaultdict(list)
    for e in events:
        if e["latitude"] is not None and e["longitude"] is not None:
            by_vessel[e["vesselId"]].append((e["latitude"], e["longitude"]))
    return {
        vid: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        for vid, pts in by_vessel.items()
    }


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _romanize(korean_name: str) -> str:
    try:
        return Romanizer(korean_name).romanize()
    except Exception:
        return ""


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def run() -> None:
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)
    tac_vessels = _load_jsonl(TAC_PATH)
    registry_rows = _load_jsonl(REGISTRY_PATH)
    mof_queries = _load_jsonl(MOF_PATH) if MOF_PATH.exists() else []
    mof_by_gfw_id = {m["gfwVesselId"]: m["candidates"] for m in mof_queries}

    ports = {p["portName"]: (p["latitude"], p["longitude"]) for p in _load_jsonl(PORTS_PATH)} if PORTS_PATH.exists() else {}
    centroids = _vessel_centroids(_load_jsonl(EVENTS_PATH)) if EVENTS_PATH.exists() else {}

    # 매칭 후보 풀(전체 GFW 선박 공통): (출처, 이름, 톤수, 항구명들, 부가정보) 하나로 합침.
    # MOF는 풀에 안 넣는다 — 이미 특정 GFW 선박 이름으로 검색해서 나온
    # 결과라 그 배 전용 후보이지, 다른 GFW 선박과 비교할 대상이 아님.
    pool = []
    for t in tac_vessels:
        pool.append(
            {"source": "tac", "name": t["nameTac"], "tonnage": t["tonnageGtTac"], "key": t["vesselNoTac"], "ports": t.get("portNamesTac") or []}
        )
    for r in registry_rows:
        pool.append(
            {
                "source": "vessel_registry",
                "name": r["nameRegistry"],
                "tonnage": r["tonnageGtRegistry"],
                "key": r["vesselNoRegistry"],
                "ports": [r["portNameRegistry"]] if r.get("portNameRegistry") else [],
            }
        )
    for p in pool:
        p["romanized"] = _normalize(_romanize(p["name"]))

    results = []
    for gfw in gfw_vessels:
        gfw_name = gfw["selfReportedName"] or gfw["registryName"]
        if not gfw_name:
            continue
        gfw_norm = _normalize(gfw_name)
        gfw_tonnage = gfw["registryTonnageGt"]  # 대부분 None(위 한계 참고)
        gfw_centroid = centroids.get(gfw["vesselId"])  # 이벤트 있으면 항상 있음

        vessel_pool = list(pool)
        for mof_cand in mof_by_gfw_id.get(gfw["vesselId"], []):
            if not mof_cand.get("vsslKorNm"):
                continue
            # MOF Info3는 어선 전용이 아니라 국내 등록 선박 전체 대상 검색이라,
            # 어선(vsslKnd 91=연근해어선/92=원양어선)이 아닌 배(상선 등)가
            # 이름만 우연히 겹쳐 후보로 들어오는 오염이 실측으로 확인됨
            # (외국적 대형 컨테이너선·벌크선이 톤수 이상치로 매칭된 사례,
            # PROCESS_LOG.md 39번) — 어선 코드만 후보로 남긴다.
            vssl_knd = mof_cand.get("vsslKnd") or ""
            if not (vssl_knd.startswith("91") or vssl_knd.startswith("92")):
                continue
            vessel_pool.append(
                {
                    "source": "mof",
                    "name": mof_cand["vsslKorNm"],
                    "tonnage": mof_cand.get("grtg"),
                    "key": mof_cand.get("vsslNo") or mof_cand.get("clsgn"),
                    "ports": [],  # MOF 응답엔 항구 정보 없음
                    "romanized": _normalize(_romanize(mof_cand["vsslKorNm"])),
                }
            )

        scored = []
        for p in vessel_pool:
            if not p["romanized"]:
                continue
            name_score = _similarity(gfw_norm, p["romanized"])
            tonnage_bonus = 0.0
            if gfw_tonnage and p["tonnage"]:
                try:
                    diff_ratio = abs(float(gfw_tonnage) - float(p["tonnage"])) / float(gfw_tonnage)
                    tonnage_bonus = max(0.0, 0.1 * (1 - diff_ratio))
                except (ValueError, ZeroDivisionError):
                    pass

            location_bonus = 0.0
            nearest_port_km = None
            if gfw_centroid:
                for port_name in p.get("ports", []):
                    coord = ports.get(port_name)
                    if not coord:
                        continue
                    dist = _haversine_km(gfw_centroid[0], gfw_centroid[1], coord[0], coord[1])
                    if nearest_port_km is None or dist < nearest_port_km:
                        nearest_port_km = dist
                if nearest_port_km is not None:
                    location_bonus = max(0.0, 0.1 * (1 - nearest_port_km / LOCATION_BONUS_MAX_KM))

            scored.append(
                {
                    **p,
                    "nameScore": round(name_score, 3),
                    "tonnageBonus": round(tonnage_bonus, 3),
                    "locationBonus": round(location_bonus, 3),
                    "nearestPortKm": round(nearest_port_km, 1) if nearest_port_km is not None else None,
                }
            )

        scored.sort(key=lambda x: x["nameScore"] + x["tonnageBonus"] + x["locationBonus"], reverse=True)
        top = scored[:TOP_N]
        results.append({"gfwVesselId": gfw["vesselId"], "gfwName": gfw_name, "candidates": top})

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"GFW {len(gfw_vessels)}척 중 이름 있는 {len(results)}척에 대해 후보 산출 -> {OUT_PATH}")
    for r in results:
        print(f"\nGFW {r['gfwName']!r} ({r['gfwVesselId']}):")
        for c in r["candidates"]:
            print(
                f"  {c['source']} {c['name']!r}({c['romanized']}) nameScore={c['nameScore']} "
                f"tonnageBonus={c['tonnageBonus']} locationBonus={c['locationBonus']}(nearestPort={c['nearestPortKm']}km)"
            )


if __name__ == "__main__":
    run()
