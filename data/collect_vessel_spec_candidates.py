"""
담당: 김태윤

국내 선박제원정보(공공데이터포털, data/vessel_spec_client.py)를 GFW 활동
있는 선박(9,723척 중 GFW 벡터 데이터에서 이름을 찾은 9,468척) 대상으로
조회해 후보를 raw로 저장한다.

수집만 한다 — 어떤 후보가 진짜 매칭인지 판단(가공)은 여기서 하지 않는다
(rules_common.md 1번, "수집과 가공을 절대 섞지 않는다"). 판단은 별도
스크립트(data/match_vessel_spec.py)의 몫이다.

검색 방식 (2026-08-13, 실제 커버리지 확인 후 결정 — mmsi/imo/callSign/name
커버리지: mmsi 100%, imo 0.5%, callSign 64.8%, name 61.6%):
    - 콜사인이 있으면 먼저 call_sign으로 검색한다. 콜사인 완전일치는
      이름 유사도보다 훨씬 결정적(이진 판정)이라 우선순위를 높였다.
    - 콜사인 검색 결과에 완전일치(대소문자 무시)가 없으면(콜사인이
      없거나, 국내 API가 부분일치로 돌려준 후보 중 완전일치가 없는
      경우 — 예: "615" 검색 시 "017615" 등만 나오는 경우) 이름이 있으면
      이름으로 한 번 더 검색해 보완한다.
    - 콜사인/이름 둘 다 없으면 검색 자체를 스킵하고 스킵 사유를 기록한다.
    - 두 검색을 다 시도한 경우 두 결과 모두 원본 그대로 저장한다 —
      어느 쪽이 맞는 매칭인지 판단(가공)은 하지 않는다(rules_common.md
      1번). 판단은 별도 스크립트(data/match_vessel_spec.py)의 몫이다.

이름 정제(2026-08-14 추가, 실측으로 검증됨): GFW 자기신고 선박명에
등록번호로 보이는 숫자가 접두어로 그대로 붙어있거나("236YANGCHANG"),
"호"가 영문 "HO"로 분리돼 있는 경우("TAESAN HO")가 실제로 많다. 이
상태 그대로 검색하면 성공률이 각각 0.1%(686건 중 1건), 5.6%(1716건
중 96건)로 일반 이름(11.3%)보다 훨씬 낮다는 게 6,024건 규모의 1차
수집 결과로 확인됐다. `clean_vessel_name()`으로 정제한 값을 우선
검색어로 쓴다 — 다만 정제 방식(HO를 그냥 떼는 게 맞는지, 붙여쓰는
게 맞는지)은 실제 API 재개 후 소규모로 먼저 검증할 것(현재 쿼터
소진으로 검증 못 함).

재시도 정책(rules_common.md 3번과 동일하게 이 스크립트 레벨에서 적용):
    - 429/5xx, 네트워크 오류: 최대 3회, 2s/4s/8s 백오프
    - resultCode != "00"(인증/쿼터 초과 등 API 자체 에러): 재시도해도
      같은 결과일 가능성이 높아 실패로 기록하고 다음으로 넘어간다
      (단, LIMIT_OVER류 에러가 연속으로 나오면 쿼터 소진일 수 있어
      진행 중 콘솔에 경고를 남긴다).

진행상태 저장/재개(rules_common.md 6번): 이미 candidates/<vesselId>.json이
있으면 건너뛴다 — 중단 후 재실행해도 이어서 진행된다.

출력:
    data/raw/vessel_spec_candidates/<run_timestamp>/candidates/<gfw_vesselId>.json
    data/raw/vessel_spec_candidates/<run_timestamp>/_progress.json
"""

import gzip
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

# Windows 콘솔/로그 리다이렉션이 기본적으로 cp949를 쓰면 한글 print()가
# UnicodeEncodeError로 스크립트 전체를 죽인다(2026-08-14 실제로 겪음 —
# "API 에러 20회 연속" 경고를 출력하려다 그 경고 자체가 스크립트를
# 죽여서 원인 로그도 못 남기고 백그라운드 프로세스가 조용히 죽었음).
# UTF-8로 강제해서 이 문제 자체를 없앤다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.vessel_spec_client import VesselSpecApiError, search_vessel_spec  # noqa: E402

GFW_EVENTS_FILE = PROJECT_ROOT / "data" / "raw" / "gfw_events_2026-01-01_2026-08-13.jsonl.gz"
GFW_VESSELS_FLAT = PROJECT_ROOT / "data" / "raw" / "gfw_vessels_kor_fishing__2026-08-13.jsonl.gz"

OUTPUT_BASE = PROJECT_ROOT / "data" / "raw" / "vessel_spec_candidates"

NUM_OF_ROWS = 20  # 후보 풀 크기 (API 최대 50, 20이면 충분히 넉넉한 후보 수)
RETRYABLE_NETWORK_ERRORS = (requests.exceptions.RequestException,)
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 524}  # rules_common.md 3번
MAX_RETRIES = 3
BACKOFF_SECONDS = [2, 4, 8]

# 선박마다 독립적인 조회라 동시성을 둘 수 있다 — 검색 페이지네이션처럼
# 커서에 의존하지 않으므로 병렬화 제약이 없음(GFW 상세조회 때도 같은
# 논리로 병렬화한 전례가 있었음). 쿼터 한도가 문서화돼 있지 않아 우선 10으로
# 시작 — 429가 잦으면 재시도 로직이 자동으로 완화하고, 더 안전하게
# 가려면 낮추면 된다. 순차 처리 시 9,468척에 7~8시간 걸릴 것으로
# 측정돼(2026-08-14) 동시성 없이는 현실적이지 않았다.
MAX_WORKERS = 10


NUMBER_PREFIX_RE = re.compile(r"^\d+(?=[A-Za-z])")
HO_SUFFIX_RE = re.compile(r"\s+HO$", re.IGNORECASE)


def clean_vessel_name(name: str) -> str:
    """검색어로 쓰기 전 GFW 자기신고 선박명을 정제한다.

    실측 근거(2026-08-14, 6,024건 규모 1차 수집 결과): 숫자접두어가
    붙은 이름("236YANGCHANG")의 검색 성공률 0.1%(686건 중 1건), "XX HO"
    형태("TAESAN HO")는 5.6%(1716건 중 96건) — 둘 다 일반 이름의 성공률
    11.3%보다 훨씬 낮았다. 원본도 같이 시도할 가치가 있는지는 API
    쿼터 소진으로 아직 검증 못 함 — 지금은 정제된 값만 우선 사용한다.
    """
    if not name:
        return name
    cleaned = name.strip()
    cleaned = NUMBER_PREFIX_RE.sub("", cleaned)
    cleaned = HO_SUFFIX_RE.sub("", cleaned)
    return cleaned.strip() or name


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_timestamp(iso: str) -> str:
    return iso.replace(":", "-")


def load_target_vessels() -> list:
    """GFW 활동 있는 선박(9,723) 중, 우리 GFW 벡터 데이터에서 실제로
    찾아진 선박(9,468)의 (vesselId, name, callSign) 목록을 만든다.

    9,723은 data/raw/gfw_events_*.jsonl.gz의 distinct vesselId 수와 같다 —
    이벤트 파일에서 직접 재계산한다."""
    active_ids = set()
    with gzip.open(GFW_EVENTS_FILE, "rt", encoding="utf-8") as f:
        for line in f:
            vid = json.loads(line).get("vesselId")
            if vid:
                active_ids.add(vid)

    targets = []
    with gzip.open(GFW_VESSELS_FLAT, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            if v["vesselId"] in active_ids:
                targets.append(
                    {
                        "vesselId": v["vesselId"],
                        "name": v.get("name"),
                        "callSign": v.get("callSign"),
                        "imo": v.get("imo"),
                    }
                )
    return targets


def fetch_candidates_with_retry(vessel_name, call_sign):
    """search_vessel_spec을 재시도 정책(rules_common.md 3번)과 함께 호출.
    반환: (candidates, error_info or None).

    VesselSpecApiError는 두 가지 서로 다른 원인을 하나의 예외로 감싼다:
    - 진짜 HTTP 에러(429/5xx 등, status_code에 실제 코드가 들어있음) — 재시도 대상.
    - API 자체 응답 에러(resultCode != 00, 인증 실패 등, status_code=None) —
      재시도해도 같은 결과이므로 즉시 실패 처리.
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            candidates = search_vessel_spec(
                vessel_name=vessel_name, call_sign=call_sign, num_of_rows=NUM_OF_ROWS
            )
            return candidates, None
        except VesselSpecApiError as exc:
            last_error = {"type": "api_error", "status_code": exc.status_code, "details": exc.details}
            if exc.status_code in RETRYABLE_HTTP_STATUS_CODES and attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS[attempt])
                continue
            return None, last_error
        except RETRYABLE_NETWORK_ERRORS as exc:
            last_error = {"type": "network_error", "message": str(exc)}
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS[attempt])
                continue
            return None, last_error
    return None, last_error


def find_resumable_run():
    """가장 최근 run이 in_progress일 때만 그걸 재개한다.

    최근 run 이전의 오래된 run을 대신 재개하지 않는다 — 예를 들어
    오래된 run A가 중단(in_progress)된 채 남아있고, 그 뒤 새로 시작한
    run B가 쿼터 소진 등으로 stopped_on_repeated_errors가 됐다면,
    B가 최신이므로 B 기준으로 새로 시작(또는 B의 상태를 보고 판단)
    해야지 A로 조용히 되돌아가면 B에 쌓인 최신 진행상황을 잃는다.
    """
    if not OUTPUT_BASE.exists():
        return None
    runs = sorted(OUTPUT_BASE.iterdir(), reverse=True)
    if not runs:
        return None
    latest = runs[0]
    progress_path = latest / "_progress.json"
    if not progress_path.exists():
        return None
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if progress.get("status") == "in_progress":
        return latest, progress
    return None


def process_one_vessel(target: dict, candidates_dir: Path):
    """선박 한 척을 처리(콜사인->필요시 이름 순으로 검색, 파일 저장)한다.
    스레드에서 병렬로 호출되므로 공유 상태(progress)는 건드리지 않고
    결과만 반환한다 — 파일 쓰기는 vesselId별로 독립적이라 안전하다.
    """
    vessel_id = target["vesselId"]
    out_path = candidates_dir / f"{vessel_id}.json"
    if out_path.exists():
        return {"status": "already_done"}

    name = target["name"]
    call_sign = target["callSign"]

    if not name and not call_sign:
        return {"status": "skipped_no_identifier", "vesselId": vessel_id}

    attempts = []
    error_entry = None

    if call_sign:
        cs_candidates, cs_error = fetch_candidates_with_retry(vessel_name=None, call_sign=call_sign)
        if cs_error is not None:
            error_entry = {"vesselId": vessel_id, "step": "callSign", "error": cs_error, "at": now_iso()}
        else:
            attempts.append({"searchedBy": "callSign", "searchValue": call_sign, "candidates": cs_candidates})

    cs_exact_hit = any(
        (c.get("callSign") or "").strip().upper() == call_sign.strip().upper()
        for a in attempts if a["searchedBy"] == "callSign"
        for c in a["candidates"]
    ) if call_sign else False

    if name and (not call_sign or not cs_exact_hit) and error_entry is None:
        search_name = clean_vessel_name(name)
        nm_candidates, nm_error = fetch_candidates_with_retry(vessel_name=search_name, call_sign=None)
        if nm_error is not None:
            error_entry = {"vesselId": vessel_id, "step": "name", "error": nm_error, "at": now_iso()}
        else:
            attempts.append({"searchedBy": "name", "searchValue": search_name, "candidates": nm_candidates})

    if error_entry is not None and not attempts:
        return {"status": "error", "error_entry": error_entry}

    record = {
        "vesselId": vessel_id,
        "gfwImo": target["imo"],
        "gfwCallSign": call_sign,
        "gfwName": name,
        "attempts": attempts,
    }
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


def main(limit=None):
    all_targets = load_target_vessels()
    targets = all_targets[:limit] if limit else all_targets
    print(f"[target] 대상 선박 수: {len(targets)}, 동시성: {MAX_WORKERS}")
    if limit:
        print(f"[note] limit={limit} — 실행분(테스트)일 뿐, 전체 대상은 {len(all_targets)}건입니다. "
              f"이 실행이 끝나도 전체가 완료된 게 아니면 상태를 'complete'로 표시하지 않습니다.")

    resumable = find_resumable_run()
    if resumable:
        run_dir, progress = resumable
        print(f"[resume] {run_dir}")
    else:
        start_iso = now_iso()
        run_dir = OUTPUT_BASE / f"vessel_spec_candidates__{safe_timestamp(start_iso)}"
        (run_dir / "candidates").mkdir(parents=True, exist_ok=True)
        progress = {
            "query_key": "vessel_spec_candidates__source_events__2026-08-13T08-22-34.917Z",
            "started_at": start_iso,
            "updated_at": start_iso,
            "status": "in_progress",
            "total_target": len(targets),
            "completed_count": 0,
            "skipped_no_identifier": [],
            "failed": [],
        }
        (run_dir / "_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
        print(f"[start] {run_dir}")

    candidates_dir = run_dir / "candidates"
    progress_lock = threading.Lock()
    consecutive_api_errors = 0
    stop_flag = False
    done_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_one_vessel, target, candidates_dir): target
            for target in targets
        }
        for future in as_completed(futures):
            if stop_flag:
                # 이미 시작된 작업(최대 MAX_WORKERS개)은 취소할 수 없지만,
                # 아직 스레드풀 큐에서 대기 중인 나머지는 cancel()로 막아서
                # 쿼터 소진 등으로 중단을 결정한 뒤에도 API를 계속 두들기지
                # 않게 한다.
                future.cancel()
                continue
            result = future.result()
            done_count += 1

            with progress_lock:
                if result["status"] == "already_done":
                    # 이전 실행이 크래시 등으로 중단됐다가 재개된 경우 —
                    # 파일은 이미 있으니 완료로 집계해야 completed_count가
                    # 실제 처리량을 반영하고, fully_done 판정도 정확해진다.
                    progress["completed_count"] += 1
                elif result["status"] == "skipped_no_identifier":
                    progress["skipped_no_identifier"].append(result["vesselId"])
                elif result["status"] == "error":
                    progress["failed"].append(result["error_entry"])
                    consecutive_api_errors += 1
                    if consecutive_api_errors >= 20:
                        print("[warn] API 에러가 20회 연속 발생 — 일일 쿼터 초과 등 구조적 문제일 수 있음. 중단합니다.")
                        stop_flag = True
                        for pending_future in futures:
                            pending_future.cancel()
                elif result["status"] == "ok":
                    progress["completed_count"] += 1
                    consecutive_api_errors = 0

                if done_count % 200 == 0:
                    progress["updated_at"] = now_iso()
                    (run_dir / "_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
                    print(
                        f"  [progress] {done_count}/{len(targets)}, 완료={progress['completed_count']}, "
                        f"실패={len(progress['failed'])}"
                    )

    # 전체 대상(progress['total_target'], limit과 무관하게 원래 목표) 기준으로
    # 실제로 다 끝났는지 확인한다 — limit으로 일부만 돌린 실행을 "complete"로
    # 잘못 표시하면 재개 로직이 이어서 못 돕는다(2026-08-14 실제로 겪은 버그).
    attempted_total = progress["completed_count"] + len(progress["skipped_no_identifier"]) + len(progress["failed"])
    fully_done = attempted_total >= progress["total_target"]

    if stop_flag:
        progress["status"] = "stopped_on_repeated_errors"
    elif fully_done:
        progress["status"] = "complete"
    else:
        progress["status"] = "in_progress"  # limit 등으로 일부만 처리 — 다음 실행에서 이어감

    progress["updated_at"] = now_iso()
    if progress["status"] == "complete":
        progress["completed_at"] = now_iso()
    (run_dir / "_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    print(
        f"[complete] status={progress['status']} 완료={progress['completed_count']}/{progress['total_target']} "
        f"스킵(식별자없음)={len(progress['skipped_no_identifier'])} 실패={len(progress['failed'])}"
    )


if __name__ == "__main__":
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit_arg)
