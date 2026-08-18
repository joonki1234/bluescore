"""MOF 재질의 — 1차 수집(영문/로마자명)에서 매칭 실패한 선박만, 역-로마자
한글 후보명으로 다시 MOF를 검색한다.

mof.py와 같은 파일명 규칙(`mof_search_{gfw_id}__시각.xml`)을 그대로 써서
raw/mof/에 이어붙인다 — process/normalize_mof.py가 vesselId 단위로 합쳐
읽으므로 원본 질의 결과가 유실되지 않는다.

전제: process/assemble_matches.py까지 이미 한 번 돌아 있어야 한다(대상
선정이 최종 매칭 결과에 의존).

사용법:
    python mof_korean_retry.py [--limit N] [--candidates-per-vessel N]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
from pathlib import Path

from hangul_reverse import candidate_names
from http_common import request_with_retry, save_snapshot

MAX_WORKERS = 15

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "processed"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "mof"
MATCHES_PATH = PROCESSED_DIR / "final_vessel_matches.jsonl"
MOF_URL = "http://apis.data.go.kr/1192000/SicsVsslManp3/Info3"


def unmatched_vessels() -> list:
    if not MATCHES_PATH.exists():
        raise SystemExit(f"{MATCHES_PATH} 없음 — process/assemble_matches.py 먼저 실행하세요.")
    out = []
    with MATCHES_PATH.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["matchTier"] == "unmatched" and r.get("gfwName"):
                out.append((r["gfwVesselId"], r["gfwName"]))
    return out


def build_queries(vessels: list, candidates_per_vessel: int) -> list:
    """(gfw_id, 한글후보명) 쌍 목록. 후보 생성 자체가 안 되는 이름(로마자
    분절 실패)은 건너뛴다."""
    queries = []
    for gfw_id, name in vessels:
        for cand in candidate_names(name, beam=candidates_per_vessel)[:candidates_per_vessel]:
            queries.append((gfw_id, cand))
    return queries


def collect(api_key: str, queries: list) -> None:
    def fetch(item):
        gfw_id, name = item
        resp = request_with_retry(
            "GET",
            MOF_URL,
            params={"serviceKey": api_key, "pageNo": "1", "numOfRows": "10", "vsslNm": name},
        )
        return gfw_id, name, resp

    failed = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, (gfw_id, name, resp) in enumerate(ex.map(fetch, queries)):
            meta = {
                "request_params": {"pageNo": "1", "numOfRows": "10", "vsslNm": name, "serviceKey": "REDACTED"},
                "status_code": resp.status_code,
                "gfw_vessel_id": gfw_id,
                "queried_name": name,
                "query_round": "korean_retry",
            }
            if not resp.ok:
                failed.append((gfw_id, name, resp.status_code))
                save_snapshot(RAW_DIR, f"mof_search_{gfw_id}_FAILED", resp.content, meta, ext="xml")
                continue

            path = save_snapshot(RAW_DIR, f"mof_search_{gfw_id}", resp.content, meta, ext="xml")
            if (i + 1) % 50 == 0 or (i + 1) == len(queries):
                print(f"{i + 1}/{len(queries)} name={name!r} -> {path.name}")

    print(f"완료. 신규 {len(queries) - len(failed)}건, 실패 {len(failed)}건.")
    if failed:
        print(f"실패 목록: {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="검증용으로 선박 N척만 처리")
    parser.add_argument("--candidates-per-vessel", type=int, default=2, help="선박당 시도할 한글 후보 수")
    args = parser.parse_args()

    key = os.environ.get("VESSEL_SPEC_API_KEY")
    if not key:
        raise SystemExit("VESSEL_SPEC_API_KEY가 .env에 없습니다.")

    vessels = unmatched_vessels()
    if args.limit is not None:
        vessels = vessels[: args.limit]
    queries = build_queries(vessels, args.candidates_per_vessel)
    print(f"unmatched {len(vessels)}척 중 한글후보 생성됨 -> 질의 {len(queries)}건(선박당 최대 {args.candidates_per_vessel}개)")

    collect(key, queries)
