"""GFW Vessels 상세조회 — gfw_events.py로 모은 이벤트에서 vesselId를 추출해
각 배의 신원 정보를 받는다 (본수집 2단계).

수집 순서(PROCESS_LOG.md 7번 결정): Vessels Search를 국적 기준으로 먼저
넓게 받지 않고, 실제 조업 이벤트에 등장한 배만 상세조회한다 — 우리
모집단(근해/연안)은 registryInfo 매칭 자체가 없어 Search 선(先)수집이
의미가 작기 때문. 엔드포인트는 GET /v3/vessels/{id}(공식 소스코드로 확인,
PROCESS_LOG.md 5번) — 응답이 목록(entries)이 아니라 선박 1척짜리 단일
객체라 이벤트 수집과 검증 방식이 다름.

재개: 이미 받은 vesselId는 건너뛴다(파일 존재 여부로 판단 — 페이지네이션이
없어 offset 진행상태가 필요 없음).

사용법:
    python gfw_vessels.py
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from http_common import check_files_valid_and_secret_free, request_with_retry, save_snapshot

EVENTS_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "events"
VESSELS_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "vessels"
VESSEL_URL = "https://gateway.api.globalfishingwatch.org/v3/vessels"


def extract_vessel_ids() -> set:
    """이벤트 스냅샷 전체에서 등장한 distinct vesselId를 모은다."""
    ids = set()
    patterns = [
        "fishing_events_page[0-9][0-9][0-9][0-9]__*Z.json",
        "fishing_events_offset[0-9][0-9][0-9][0-9][0-9][0-9][0-9]__*Z.json",
    ]
    files = sorted({f for p in patterns for f in glob.glob(str(EVENTS_DIR / p))})
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            vid = (entry.get("vessel") or {}).get("id")
            if vid:
                ids.add(vid)
    return ids


def already_fetched() -> set:
    """이미 상세조회 저장된 vesselId 목록(파일명에서 복원)."""
    done = set()
    for f in glob.glob(str(VESSELS_DIR / "vessel_*__*Z.json")):
        stem = Path(f).name.split("__")[0]  # "vessel_{id}"
        done.add(stem[len("vessel_") :])
    return done


def collect(api_key: str, limit: int = None) -> None:
    vessel_ids = extract_vessel_ids()
    done = already_fetched()
    todo = sorted(vessel_ids - done)
    print(f"이벤트에서 발견한 선박 {len(vessel_ids)}척, 이미 받음 {len(done)}척, 남은 것 {len(todo)}척")
    if limit is not None:
        todo = todo[:limit]
        print(f"--limit {limit} 적용 — 이번 실행은 {len(todo)}척만 처리")

    failed = []
    for i, vid in enumerate(todo):
        resp = request_with_retry(
            "GET",
            f"{VESSEL_URL}/{vid}",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"dataset": "public-global-vessel-identity:latest"},
        )
        meta = {"request_url": resp.url, "status_code": resp.status_code, "vessel_id": vid}

        if not resp.ok:
            # 요청 오류든 재시도 소진이든, 이 배만 실패로 기록하고 다음으로 진행
            # (수집원칙: 항목 하나 실패해도 전체 수집은 계속).
            failed.append((vid, resp.status_code))
            save_snapshot(VESSELS_DIR, f"vessel_{vid}_FAILED", resp.content, meta)
            continue

        path = save_snapshot(VESSELS_DIR, f"vessel_{vid}", resp.content, meta)
        if (i + 1) % 50 == 0 or (i + 1) == len(todo):
            print(f"{i + 1}/{len(todo)} -> {path.name}")

    print(f"완료. 신규 {len(todo) - len(failed)}척, 실패 {len(failed)}척.")
    if failed:
        print(f"실패 목록: {failed}")

    problems, parsed = check_files_valid_and_secret_free(
        VESSELS_DIR, "vessel_*__*Z.json", api_key
    )
    for f, data in parsed.items():
        if "dataset" not in data:
            problems.append(f"원본 구조 이상('dataset' 키 없음): {f}")
    if problems:
        print("검증 게이트 위반:")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"검증 게이트 통과 ({len(parsed)}개 파일).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="검증용으로 N척만 처리(미지정 시 전부)")
    args = parser.parse_args()

    key = os.environ.get("GFW_API_KEY")
    if not key:
        raise SystemExit("GFW_API_KEY가 .env에 없습니다.")
    collect(key, limit=args.limit)
