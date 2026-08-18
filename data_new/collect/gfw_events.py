"""GFW Events 수집 — 한국 EEZ 내 FISHING 이벤트 (본수집 1단계).

모집단 정의(PROCESS_LOG.md 6번): flag='KOR' AND 한국 EEZ(marineregions.org
MRGID 8327) 내 FISHING 타입 이벤트 1건 이상. Events API는 POST(공식
파이썬 클라이언트 소스코드로 확인, PROCESS_LOG.md 5번).

수집 순서(PROCESS_LOG.md 7번 결정): Vessels Search를 먼저 넓게 받지 않고,
이 스크립트로 실제 조업 이벤트를 먼저 모아 vesselId를 추출한 뒤
gfw_vessels.py로 그 배들만 상세조회한다 — 우리 모집단(근해/연안)은
registryInfo 매칭 자체가 없어 Search 선(先)수집이 의미가 작기 때문.

중단 후 재개: 같은 조건(기간 등)으로 다시 실행하면 이어서 진행한다.
조건이 다르면 이어받지 않고 새로 시작한다(수집원칙 표 참고).

사용법:
    python gfw_events.py --start 2026-08-01 --end 2026-08-17
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import json

from http_common import (
    check_files_valid_and_secret_free,
    load_progress,
    request_with_retry,
    save_progress,
    save_snapshot,
)

EVENTS_URL = "https://gateway.api.globalfishingwatch.org/v3/events"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "events"
PROGRESS_PATH = RAW_DIR / "_progress.json"
# 실측 확인(2026-08-17): limit=50000도 API가 그대로 받아주고, 요청 하나당
# 걸리는 시간이 건수와 거의 무관(고정 오버헤드가 대부분) — 1000짜리
# 277번보다 50000짜리 6번이 압도적으로 빠름(28초 vs 20초x277). PROCESS_LOG.md
# 28번 참고.
PAGE_LIMIT = 50000


def collect(start_date: str, end_date: str, api_key: str) -> None:
    params = {
        "datasets": ["public-global-fishing-events:latest"],
        "flags": ["KOR"],
        "region": {"dataset": "public-eez-areas", "id": "8327"},
        "startDate": start_date,
        "endDate": end_date,
    }

    offset = load_progress(PROGRESS_PATH, params)
    if offset > 0:
        print(f"이전 진행상태 발견 — offset={offset}부터 이어서 진행")

    total = None
    while True:
        # 파일명은 "페이지 번호"가 아니라 offset 자체로 — PAGE_LIMIT을 실행마다
        # 바꿔도(실제로 1000->50000으로 바뀐 적 있음, PROCESS_LOG.md 28번)
        # 파일명이 서로 안 겹치고 뜻이 헷갈리지 않음.
        url = f"{EVENTS_URL}?limit={PAGE_LIMIT}&offset={offset}"
        resp = request_with_retry(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=params,
        )

        meta = {"request_url": url, "request_body": params, "status_code": resp.status_code}

        if not resp.ok:
            # 요청 오류는 재시도해도 같은 결과라 여기서 실패로 기록하고 중단.
            # 진행상태는 건드리지 않는다 — 다음 실행이 이 offset부터 이어받게.
            save_snapshot(RAW_DIR, f"fishing_events_offset{offset:07d}_FAILED", resp.content, meta)
            raise RuntimeError(f"수집 실패: {resp.status_code} {resp.text[:300]}")

        path = save_snapshot(RAW_DIR, f"fishing_events_offset{offset:07d}", resp.content, meta)

        data = resp.json()
        total = data.get("total", 0)
        n = len(data.get("entries", []))
        print(f"offset={offset} 받은건수={n} total={total} -> {path.name}")

        offset += n
        save_progress(PROGRESS_PATH, params, offset, total, completed=(n == 0 or offset >= total))
        if n == 0 or offset >= total:
            break

    print(f"수집 완료. 총 {offset}건. -> {RAW_DIR}")

    problems = _validate_this_run(params, total or 0, api_key)
    if problems:
        print("검증 게이트 위반:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("검증 게이트 통과.")


def _validate_this_run(params: dict, expected_total: int, secret: str) -> list:
    """건수 일치 검증 — 같은 폴더에 다른 조회조건(기간 등)의 과거 스냅샷이
    남아있을 수 있어(실제로 겪음, PROCESS_LOG.md 28번: 테스트용 7/1~10
    파일이 본수집 폴더에 섞여 건수 불일치로 오검출됨), 파일명 패턴만으로
    다 세지 않고 각 파일의 메타데이터(request_body)가 **이번 실행의
    params와 정확히 같은 파일만** 골라서 센다."""
    problems, parsed = check_files_valid_and_secret_free(
        RAW_DIR,
        [
            "fishing_events_page[0-9][0-9][0-9][0-9]__*Z.json",
            "fishing_events_offset[0-9][0-9][0-9][0-9][0-9][0-9][0-9]__*Z.json",
        ],
        secret,
    )
    total_entries = 0
    for f, data in parsed.items():
        if "entries" not in data:
            problems.append(f"원본 구조 이상('entries' 키 없음): {f}")
            continue
        # save_snapshot의 메타 파일명 규칙(확장자 제외 후 ".meta.json")과 동일하게 계산
        stem = Path(f).name
        ext = stem.rsplit(".", 1)[-1]
        meta_path = Path(f).with_name(stem[: -(len(ext) + 1)] + ".meta.json")
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("request_body") == params:
            total_entries += len(data["entries"])

    if total_entries != expected_total:
        problems.append(f"건수 불일치(이번 조회조건 파일만 집계): 저장된 {total_entries}건 vs API total {expected_total}건")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (조회 시작일, 포함)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (조회 종료일, 미포함)")
    args = parser.parse_args()

    key = os.environ.get("GFW_API_KEY")
    if not key:
        raise SystemExit("GFW_API_KEY가 .env에 없습니다.")
    collect(args.start, args.end, key)
