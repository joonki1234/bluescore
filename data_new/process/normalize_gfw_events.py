"""GFW 조업이벤트 정규화 — 원본(raw, 중첩구조)을 score/ 계약(flat) 형태로 변환.

score/ 계약 필드(vesselId, latitude, longitude, averageSpeedKnots,
durationHours 등)는 GFW 원본 응답 구조와 다르다(SCHEMA_DRAFT.md 발견,
PROCESS_LOG.md 5번 — vessel.id/position.lat.lon/타입별 하위객체로 중첩돼
있음) — 이 스크립트가 그 변환을 전담한다.

가공 단계라 raw/는 절대 건드리지 않고 읽기만 한다. 산출물은 processed/에
새로 쓰며, 원본에서 결정론적으로 다시 만들 수 있어 raw의 스냅샷 원칙
(재조회 덮어쓰기 금지)이 적용되지 않는다 — 다시 돌리면 그냥 덮어쓴다.

우리 이벤트 수집(collect/gfw_events.py)이 FISHING 타입만 받으므로, 이
스크립트도 FISHING 하위객체(`fishing.*`)만 다룬다.

사용법:
    python normalize_gfw_events.py
"""

from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "events"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_events_normalized.jsonl"


def _duration_hours(start: str, end: str) -> float:
    """GFW `fishing.averageDurationHours`는 100% null이다(19,613건 확인).
    대신 매 이벤트에 항상 있는 start/end(null 0건)로 직접 계산한다."""
    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (e - s).total_seconds() / 3600.0


def normalize_event(raw: dict) -> dict:
    """원본 이벤트 1건을 score/ 계약 형태(flat)로 변환한다.

    필드 매핑 근거(SCHEMA_DRAFT.md FishingEvent 섹션):
        id -> eventId, vessel.id -> vesselId, position.lat/lon -> latitude/longitude,
        durationHours는 GFW 필드를 그대로 안 쓰고 start/end로 직접 계산(_duration_hours 참고)
    """
    fishing = raw.get("fishing") or {}
    position = raw.get("position") or {}
    vessel = raw.get("vessel") or {}
    regions = raw.get("regions") or {}
    start, end = raw.get("start"), raw.get("end")
    return {
        "eventId": raw.get("id"),
        "vesselId": vessel.get("id"),
        "type": raw.get("type"),
        "start": start,
        "end": end,
        "latitude": position.get("lat"),
        "longitude": position.get("lon"),
        "averageSpeedKnots": fishing.get("averageSpeedKnots"),
        "totalDistanceKm": fishing.get("totalDistanceKm"),
        "durationHours": _duration_hours(start, end) if start and end else None,
        "regionsMpa": regions.get("mpa") or [],
        "regionsEez": regions.get("eez") or [],
        "regionsEez12Nm": regions.get("eez12Nm") or [],
    }


def run() -> None:
    patterns = [
        "fishing_events_page[0-9][0-9][0-9][0-9]__*Z.json",
        "fishing_events_offset[0-9][0-9][0-9][0-9][0-9][0-9][0-9]__*Z.json",
    ]
    files = sorted({f for p in patterns for f in glob.glob(str(RAW_DIR / p))})
    if not files:
        raise SystemExit(f"원본 이벤트 파일이 없습니다: {RAW_DIR}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    skipped_no_vessel = 0
    skipped_dup = 0
    seen_ids = set()
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for f in files:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            for raw_event in data.get("entries", []):
                n_in += 1
                normalized = normalize_event(raw_event)
                if not normalized["vesselId"]:
                    # score/의 axis_a_pressure.py 등이 vesselId 없는 이벤트를 못 쓰므로
                    # 여기서 명시적으로 제외 사유를 남기고 건너뛴다(조용히 누락 금지).
                    skipped_no_vessel += 1
                    continue
                # 소량표본(7/1~10)이 실규모(4/1~8/14) 기간에 포함돼 같은 raw/
                # 폴더에 두 배치 파일이 공존한다 — eventId 기준으로 중복 제거.
                eid = normalized["eventId"]
                if eid in seen_ids:
                    skipped_dup += 1
                    continue
                seen_ids.add(eid)
                out.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                n_out += 1

    print(f"입력 {n_in}건 -> 출력 {n_out}건 (vesselId 없어 제외 {skipped_no_vessel}건, 중복 제외 {skipped_dup}건)")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
