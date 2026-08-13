"""GFW raw_data 하드 게이트 검증.

rules_common.md 7번 공통 하드 게이트 + rules_gfw.md 6번 GFW 전용
정보성 체크를 raw_data/gfw/vessels_search, vessels_detail 각 실행분에
대해 확인한다. 이 스크립트는 읽기 전용이다 — raw_data를 수정하지 않는다.

하드 게이트 (하나라도 실패하면 이 실행분은 다음 단계로 넘기지 않음):
  1. 원본 구조 그대로 저장됐는가 (샘플 파일의 최상위 키 구조 확인)
  2. 목록/상세조회 시도 건수와 실제 처리 건수가 일치하는가
     (불일치가 있으면 실패 사유가 기록돼 있는지까지 확인)
  3. 재조회 시 기존 스냅샷 파일이 손상(0바이트 등)되지 않았는가
  4. 토큰이 raw_data 어디에도 노출되지 않았는가

정보성 체크 (통과/실패 판정 없음, 로그만):
  - registryOwners(개인정보 가능) 포함 건수
  - registryInfo 매칭/비매칭 비율
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_BASE = PROJECT_ROOT / "raw_data" / "gfw"
ENV_PATH = PROJECT_ROOT / ".env"

SEARCH_ENTRY_REQUIRED_KEYS = {
    "dataset",
    "registryInfoTotalRecords",
    "registryInfo",
    "registryOwners",
    "combinedSourcesInfo",
    "selfReportedInfo",
}
DETAIL_REQUIRED_KEYS = {
    "registryInfoTotalRecords",
    "registryInfo",
    "registryOwners",
    "combinedSourcesInfo",
    "selfReportedInfo",
    "dataset",
}


def load_token():
    if not ENV_PATH.exists():
        return None
    text = ENV_PATH.read_text(encoding="utf-8")
    m = re.search(r"^GFW_API_TOKEN=(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def gate_token_not_exposed(run_dir, token):
    """게이트 4: 토큰이 raw_data 어디에도 노출되지 않았는가."""
    violations = []
    needles = ["Bearer "]
    if token:
        needles.append(token)
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for needle in needles:
            if needle in text:
                violations.append(str(path))
                break
    return len(violations) == 0, violations


def gate_no_corrupted_snapshots(files):
    """게이트 3(대용): 저장된 파일이 0바이트/파싱불가로 손상되지 않았는가."""
    bad = []
    for f in files:
        if f.stat().st_size == 0:
            bad.append((str(f), "0 bytes"))
            continue
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append((str(f), f"invalid JSON: {e}"))
    return len(bad) == 0, bad


def validate_search_run(run_dir):
    print(f"\n=== [vessels_search] {run_dir.name} ===")
    progress_path = run_dir / "_progress.json"
    if not progress_path.exists():
        print("  SKIP: _progress.json 없음")
        return None
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    pages_dir = run_dir / "pages"
    page_files = sorted(pages_dir.glob("page_*.json")) if pages_dir.exists() else []

    results = {}

    # 게이트 1: 원본 구조 (샘플 최대 5개 페이지)
    sample = page_files[:: max(1, len(page_files) // 5)][:5] if page_files else []
    structure_ok = True
    structure_issues = []
    total_entries_seen = 0
    for f in sample:
        body = json.loads(f.read_text(encoding="utf-8"))
        for e in body.get("entries", []):
            total_entries_seen += 1
            missing = SEARCH_ENTRY_REQUIRED_KEYS - e.keys()
            if missing:
                structure_ok = False
                structure_issues.append(f"{f.name}: missing keys {missing}")
    results["gate1_original_structure"] = structure_ok
    print(f"  게이트1 원본 구조 보존: {'PASS' if structure_ok else 'FAIL'}"
          f" (샘플 {len(sample)}페이지, entry {total_entries_seen}건 검사)")
    if not structure_ok:
        for issue in structure_issues[:5]:
            print(f"    - {issue}")

    # 게이트 2: 목록 total과 실제 수집 건수 일치
    total = progress.get("total_at_first_page")
    collected = progress.get("entries_collected")
    status = progress.get("status")
    count_ok = (total is not None and collected == total) or status == "stopped_intentionally"
    results["gate2_count_match"] = count_ok
    print(f"  게이트2 건수 일치: {'PASS' if count_ok else 'FAIL'}"
          f" (total={total}, collected={collected}, status={status})")
    if status == "stopped_intentionally":
        print(f"    참고: 의도적 중단 — {progress.get('stopped_note', '')[:120]}...")

    # 게이트 3: 스냅샷 손상 여부
    no_corruption, bad_files = gate_no_corrupted_snapshots(page_files)
    results["gate3_no_corruption"] = no_corruption
    print(f"  게이트3 스냅샷 손상 없음: {'PASS' if no_corruption else 'FAIL'} ({len(page_files)}개 파일 검사)")
    for path, reason in bad_files[:5]:
        print(f"    - {path}: {reason}")

    # 게이트 4: 토큰 비노출
    token = load_token()
    no_token, violations = gate_token_not_exposed(run_dir, token)
    results["gate4_no_token_exposure"] = no_token
    print(f"  게이트4 토큰 비노출: {'PASS' if no_token else 'FAIL'}")
    for v in violations[:5]:
        print(f"    - {v}")

    return results


def validate_detail_run(run_dir):
    print(f"\n=== [vessels_detail] {run_dir.name} ===")
    progress_path = run_dir / "_progress.json"
    if not progress_path.exists():
        print("  SKIP: _progress.json 없음")
        return None
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    details_dir = run_dir / "details"
    detail_files = sorted(details_dir.glob("*.json")) if details_dir.exists() else []

    results = {}

    # 게이트 1: 원본 구조 (샘플)
    sample = detail_files[:: max(1, len(detail_files) // 20)][:20] if detail_files else []
    structure_ok = True
    structure_issues = []
    for f in sample:
        body = json.loads(f.read_text(encoding="utf-8"))
        missing = DETAIL_REQUIRED_KEYS - body.keys()
        if missing:
            structure_ok = False
            structure_issues.append(f"{f.name}: missing keys {missing}")
    results["gate1_original_structure"] = structure_ok
    print(f"  게이트1 원본 구조 보존: {'PASS' if structure_ok else 'FAIL'} (샘플 {len(sample)}건 검사)")
    for issue in structure_issues[:5]:
        print(f"    - {issue}")

    # 게이트 2: 목록(target) 건수와 실제 처리(성공+실패) 건수 일치, 실패는 사유 설명 가능해야 함
    total_target = progress.get("total_target")
    completed = progress.get("completed_count", 0)
    failed_list = progress.get("failed", [])
    actual_files = len(detail_files)
    files_match_completed = actual_files == completed
    attempted = completed + len(failed_list)
    status = progress.get("status")
    count_ok = (
        (total_target is not None and attempted == total_target and files_match_completed)
        or status == "stopped_intentionally"
    )
    failures_explained = all("status" in f and "body" in f for f in failed_list)
    results["gate2_count_match"] = count_ok and failures_explained
    if status == "stopped_intentionally":
        print(f"    참고: 의도적 중단 — {progress.get('stopped_note', '')[:160]}...")
    print(f"  게이트2 건수 일치: {'PASS' if count_ok else 'FAIL'}"
          f" (target={total_target}, completed={completed}, failed={len(failed_list)},"
          f" attempted={attempted}, 실제 저장된 파일 수={actual_files})")
    print(f"    실패 사유 기록 여부: {'PASS' if failures_explained else 'FAIL'}"
          f" ({len(failed_list)}건 중 사유 없는 건 "
          f"{sum(1 for f in failed_list if not ('status' in f and 'body' in f))}건)")
    if failed_list:
        print(f"    실패 예시(최대 5건): {[ (f['vesselId'], f.get('status')) for f in failed_list[:5] ]}")

    # 게이트 3: 손상 파일 없음
    no_corruption, bad_files = gate_no_corrupted_snapshots(detail_files)
    results["gate3_no_corruption"] = no_corruption
    print(f"  게이트3 스냅샷 손상 없음: {'PASS' if no_corruption else 'FAIL'} ({actual_files}개 파일 검사)")
    for path, reason in bad_files[:5]:
        print(f"    - {path}: {reason}")

    # 게이트 4: 토큰 비노출
    token = load_token()
    no_token, violations = gate_token_not_exposed(run_dir, token)
    results["gate4_no_token_exposure"] = no_token
    print(f"  게이트4 토큰 비노출: {'PASS' if no_token else 'FAIL'}")
    for v in violations[:5]:
        print(f"    - {v}")

    # 정보성: registryInfo 매칭/비매칭, registryOwners 전수 재집계 (self-reported 카운터와 교차검증)
    matched = 0
    unmatched = 0
    owners_nonempty = 0
    for f in detail_files:
        body = json.loads(f.read_text(encoding="utf-8"))
        if body.get("registryInfo"):
            matched += 1
        else:
            unmatched += 1
        if body.get("registryOwners"):
            owners_nonempty += 1
    total_checked = matched + unmatched
    print(f"\n  [정보성] registryInfo 매칭 비율 (전수 재계산, {total_checked}건 기준):")
    if total_checked:
        print(f"    매칭(있음): {matched}건 ({100*matched/total_checked:.1f}%)")
        print(f"    비매칭(없음): {unmatched}건 ({100*unmatched/total_checked:.1f}%)")
    print(f"  [정보성] registryOwners 값 있는 건: {owners_nonempty}건 ({100*owners_nonempty/total_checked:.1f}%)" if total_checked else "")
    self_reported_matched = progress.get("registry_matched_count")
    self_reported_owners = progress.get("registry_owners_nonempty_count")
    cross_check_ok = (self_reported_matched == matched and self_reported_owners == owners_nonempty)
    print(f"  [교차검증] 수집 스크립트 자체 집계와 일치: {'PASS' if cross_check_ok else 'MISMATCH — 재확인 필요'}"
          f" (스크립트 self-report: matched={self_reported_matched}, owners={self_reported_owners})")

    return results


EVENT_PAGE_REQUIRED_KEYS = {"metadata", "limit", "offset", "total", "entries"}


def validate_events_run(run_dir):
    print(f"\n=== [events] {run_dir.name} ===")
    progress_path = run_dir / "_progress.json"
    if not progress_path.exists():
        print("  SKIP: _progress.json 없음")
        return None
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    batches_dir = run_dir / "batches"
    batch_files = sorted(batches_dir.glob("*.json")) if batches_dir.exists() else []

    results = {}

    # 게이트 1: 원본 구조 (샘플)
    sample = batch_files[:: max(1, len(batch_files) // 20)][:20] if batch_files else []
    structure_ok = True
    structure_issues = []
    for f in sample:
        body = json.loads(f.read_text(encoding="utf-8"))
        missing = EVENT_PAGE_REQUIRED_KEYS - body.keys()
        if missing:
            structure_ok = False
            structure_issues.append(f"{f.name}: missing keys {missing}")
    results["gate1_original_structure"] = structure_ok
    print(f"  게이트1 원본 구조 보존: {'PASS' if structure_ok else 'FAIL'} (샘플 {len(sample)}개 배치 페이지 검사)")
    for issue in structure_issues[:5]:
        print(f"    - {issue}")

    # 게이트 2: 목록(배치) 건수와 실제 처리(완료+실패) 건수 일치, 실패는 사유 설명 가능해야 함
    total_batches = progress.get("total_batches")
    completed_batches = progress.get("completed_batches", 0)
    failed_batches = progress.get("failed_batches", [])
    count_ok = total_batches is not None and completed_batches == total_batches
    failures_explained = all("status" in fb and "body" in fb and "vesselIds" in fb for fb in failed_batches)
    results["gate2_count_match"] = count_ok and failures_explained
    print(f"  게이트2 건수 일치: {'PASS' if count_ok else 'FAIL'}"
          f" (total_batches={total_batches}, completed_batches={completed_batches}, failed_batches={len(failed_batches)})")
    print(f"    실패 사유 기록 여부: {'PASS' if failures_explained else 'FAIL'}")
    if failed_batches:
        print(f"    실패 배치 예시(최대 3건): "
              f"{[(fb['batchIndex'], fb.get('status'), len(fb.get('vesselIds', []))) for fb in failed_batches[:3]]}")

    # 게이트 3: 손상 파일 없음
    no_corruption, bad_files = gate_no_corrupted_snapshots(batch_files)
    results["gate3_no_corruption"] = no_corruption
    print(f"  게이트3 스냅샷 손상 없음: {'PASS' if no_corruption else 'FAIL'} ({len(batch_files)}개 파일 검사)")
    for path, reason in bad_files[:5]:
        print(f"    - {path}: {reason}")

    # 게이트 4: 토큰 비노출
    token = load_token()
    no_token, violations = gate_token_not_exposed(run_dir, token)
    results["gate4_no_token_exposure"] = no_token
    print(f"  게이트4 토큰 비노출: {'PASS' if no_token else 'FAIL'}")
    for v in violations[:5]:
        print(f"    - {v}")

    # 정보성: 이벤트 유무 척수, 타입별 분포 (progress.json 자체 집계, 전수 기준이므로 그대로 보고)
    total_target = progress.get("total_target_vessels")
    with_events = progress.get("vessels_with_events_count")
    without_events = progress.get("vessels_without_events_count")
    print(f"\n  [정보성] vesselId {total_target}개 중 이벤트 1건 이상 있는 배: {with_events}건"
          f" ({100*with_events/total_target:.1f}%)" if total_target else "")
    print(f"  [정보성] 이벤트 0건인 배: {without_events}건"
          f" ({100*without_events/total_target:.1f}%)" if total_target else "")
    print(f"  [정보성] 이벤트 타입별 건수: {json.dumps(progress.get('events_by_type', {}), ensure_ascii=False)}")
    print(f"  [정보성] 총 이벤트 건수: {progress.get('total_events_collected')}")

    # 교차검증: batch 페이지 파일들을 직접 훑어서 progress.json의 자체 집계와 재대조
    recount_by_type = {}
    recount_vessels_with_events = set()
    for f in batch_files:
        body = json.loads(f.read_text(encoding="utf-8"))
        for ev in body.get("entries", []):
            recount_by_type[ev["type"]] = recount_by_type.get(ev["type"], 0) + 1
            vid = (ev.get("vessel") or {}).get("id")
            if vid:
                recount_vessels_with_events.add(vid)
    recount_total = sum(recount_by_type.values())
    cross_ok = (recount_total == progress.get("total_events_collected")
                and recount_by_type == progress.get("events_by_type")
                and len(recount_vessels_with_events) == with_events)
    print(f"  [교차검증] batch 파일 전수 재집계와 progress.json 일치: {'PASS' if cross_ok else 'MISMATCH — 재확인 필요'}"
          f" (재집계 total={recount_total}, by_type={recount_by_type}, vessels_with_events={len(recount_vessels_with_events)})")
    results["cross_check_events"] = cross_ok

    return results


def main():
    all_results = {}
    search_base = RAW_BASE / "vessels_search"
    if search_base.exists():
        for run_dir in sorted(search_base.iterdir()):
            if run_dir.is_dir():
                r = validate_search_run(run_dir)
                if r is not None:
                    all_results[f"search:{run_dir.name}"] = r

    detail_base = RAW_BASE / "vessels_detail"
    if detail_base.exists():
        for run_dir in sorted(detail_base.iterdir()):
            if run_dir.is_dir():
                r = validate_detail_run(run_dir)
                if r is not None:
                    all_results[f"detail:{run_dir.name}"] = r

    events_base = RAW_BASE / "events"
    if events_base.exists():
        for run_dir in sorted(events_base.iterdir()):
            if run_dir.is_dir():
                r = validate_events_run(run_dir)
                if r is not None:
                    all_results[f"events:{run_dir.name}"] = r

    print("\n" + "=" * 60)
    print("전체 요약")
    print("=" * 60)
    any_fail = False
    for name, gates in all_results.items():
        ok = all(gates.values())
        if not ok:
            any_fail = True
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print()
    if any_fail:
        print("결과: 하나 이상의 실행분이 하드 게이트를 통과하지 못함 — 다음 단계로 넘기지 말 것.")
        sys.exit(1)
    else:
        print("결과: 모든 실행분이 하드 게이트 통과.")
        sys.exit(0)


if __name__ == "__main__":
    main()
