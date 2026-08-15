"""
담당: 김태윤

"모집단이 어디서 얼마나 빠지는지"를 대화 중에 우연히 발견하는 게 아니라,
실행할 때마다 자동으로 보여준다.

전부 실제 로컬 파일에서 다시 계산한다(하드코딩 없음) — 단, 국적 필터
(flag='KOR') 단계 하나는 예외다. 이 단계는 원래 수집을 의도적으로
중단하고 raw 파일을 부분본만 남겨서, 로컬 파일로는 총량을 재계산할 수
없다(실제 API 응답 메타데이터로만 확인된 값). 이런 "재계산 불가" 단계는
숨기지 않고 출처를 그대로 밝힌다.

⚠ 이벤트 지속시간 이상치 관련 정정(2026-08-15): raw 이벤트 913,715건 중
6,650건(0.73%)이 30일 넘는 지속시간(최장 5,082일=14년)을 갖고 있어 처음엔
GAP(신호 끊김) 이벤트로 추정했으나, GFW API 라이브 재조회로 확인한 결과
**GAP이 아니라 port_visit(항구 정박) 이벤트의 장기 오탐**이었다(eventId·
duration 정확히 일치하는 3건 표본 전부 type="port_visit" 확인). 항구
근처 장기 저활동 구간을 GFW 알고리즘이 하나의 방문으로 뭉친 것으로
보인다. score팀이 durationHours를 쓰는 로직이 있다면 이 이상치가
걸러지는지 확인 필요.
"""

import gzip
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.snapshot_utils import find_latest  # noqa: E402

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# 재계산 불가 — 실제 API 호출 메타데이터로만 확인된 값(2026-08-13).
# 이 단계의 raw 수집은 48,800건에서 의도적으로 중단됐고 이후 조건을 좁혀
# 재수집했기 때문에, 로컬 파일에 전체 89,897건이 남아있지 않다.
FLAG_KOR_TOTAL_FROM_API_METADATA = 89897

DURATION_OUTLIER_HOURS = 30 * 24  # 30일 — port_visit 오탐 이상치 기준


def count_jsonl_gz(path: Path) -> int:
    n = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def count_distinct_vessel_ids(path: Path) -> int:
    ids = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            vid = json.loads(line).get("vesselId")
            if vid:
                ids.add(vid)
    return len(ids)


def main():
    print("=== 모집단 퍼널 리포트 ===\n")

    print("[국적·선종 필터]")
    print(f"  1. flag='KOR' 전체: {FLAG_KOR_TOTAL_FROM_API_METADATA:,}척  "
          f"(※ 로컬 파일로 재계산 불가 — 실제 API 메타데이터 기록값)")

    fishing_path = find_latest(DATA_RAW_DIR, "gfw_vessels_kor_fishing__*.jsonl.gz")
    fishing_total = count_jsonl_gz(fishing_path)
    fishing_pct = 100 * fishing_total / FLAG_KOR_TOTAL_FROM_API_METADATA
    print(f"  2. + shiptypes.name='FISHING': {fishing_total:,}척  ({fishing_pct:.1f}%, 1번 대비)")
    print(f"     ⚠ 이 필터 자체의 정확도가 낮음(표본 검증: 88~90.5%가 실제로는 비어선)")

    print("\n[이벤트 기간 필터]")
    events_path = find_latest(DATA_RAW_DIR, "gfw_events_20*.jsonl.gz")
    event_vessel_total = count_distinct_vessel_ids(events_path)
    event_pct = 100 * event_vessel_total / fishing_total
    print(f"  3. 이 기간에 이벤트가 1건이라도 있는 선박: {event_vessel_total:,}척  ({event_pct:.1f}%, 2번 대비)")
    print(f"     ⚠ 나머지 {fishing_total - event_vessel_total:,}척은 등록은 됐지만 이 기간 활동이 안 잡힌 배")

    # 이벤트 이상치(port_visit 장기 오탐) 참고 정보 — 모집단에서 빼진 않지만
    # 얼마나 섞여있는지 매번 보여준다.
    outlier_vessel_ids = set()
    normal_vessel_ids = set()
    with gzip.open(events_path, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            vid = e.get("vesselId")
            if not vid:
                continue
            if (e.get("durationHours") or 0) > DURATION_OUTLIER_HOURS:
                outlier_vessel_ids.add(vid)
            else:
                normal_vessel_ids.add(vid)
    pure_outlier_only = outlier_vessel_ids - normal_vessel_ids
    if pure_outlier_only:
        print(f"     ⚠ 그중 {len(pure_outlier_only):,}척은 순수하게 port_visit 장기 이상치(30일+ 지속시간) "
              f"이벤트로만 모집단에 들어옴(정상 이벤트 없음) — 위 정정 사항 참고")

    gfw_flat_ids = set()
    with gzip.open(fishing_path, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            gfw_flat_ids.add(v["vesselId"])
    event_ids = set()
    with gzip.open(events_path, "rt", encoding="utf-8") as f:
        for line in f:
            vid = json.loads(line).get("vesselId")
            if vid:
                event_ids.add(vid)
    matched_in_search = len(event_ids & gfw_flat_ids)
    print(f"  4. + GFW Vessels Search 결과에서도 실제로 찾아짐: {matched_in_search:,}척  "
          f"({100*matched_in_search/event_vessel_total:.1f}%, 3번 대비)")

    print("\n[국내 매칭 → 최종 score 대상 모집단]")
    enriched_path = find_latest(DATA_RAW_DIR, "gfw_vessels_enriched.jsonl.gz")
    enriched_total = count_jsonl_gz(enriched_path)
    excluded = fishing_total - enriched_total
    print(f"  5. MOF 비어선 의심(확정매칭+플래그) 제외 후 최종 모집단: {enriched_total:,}척  "
          f"({excluded:,}척 제외, 2번 대비 {100*enriched_total/fishing_total:.1f}%)")

    tonnage_known = 0
    with gzip.open(enriched_path, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            if v.get("tonnage") is not None:
                tonnage_known += 1
    print(f"  6. 그중 톤수 확보: {tonnage_known:,}척  ({100*tonnage_known/enriched_total:.1f}%, 5번 대비)")

    # GFW 자기모순 라벨 필터(filter_self_contradicting_labels.py 산출물) —
    # MOF 매칭 없이 GFW 자체 응답만으로 5번 모집단에 적용 가능한 무료 필터.
    print("\n[GFW 자기모순 라벨 필터 — 5번 모집단에 추가 적용 시]")
    try:
        flagged_path = find_latest(DATA_RAW_DIR, "gfw_self_contradicting_vessel_ids__*.json")
        with open(flagged_path, encoding="utf-8") as f:
            flagged = json.load(f)
        flagged_ids = set(flagged.get("flaggedVesselIds", []))
        with gzip.open(enriched_path, "rt", encoding="utf-8") as f:
            flagged_in_population = sum(
                1 for line in f if json.loads(line)["vesselId"] in flagged_ids
            )
        after_filter = enriched_total - flagged_in_population
        print(f"  7. CARGO/PASSENGER/CARRIER 자기신고(WISE HONEST 등) {flagged_in_population}척 "
              f"추가 제외 시: {after_filter:,}척 ({100*after_filter/enriched_total:.2f}%, 5번 대비)")
    except FileNotFoundError:
        print("  ⚠ 필터 산출물 없음 — filter_self_contradicting_labels.py 먼저 실행 필요")

    print("\n=== 요약 ===")
    print(f"국적 등록({FLAG_KOR_TOTAL_FROM_API_METADATA:,}) → 어업선박 분류({fishing_total:,}, "
          f"{100*fishing_total/FLAG_KOR_TOTAL_FROM_API_METADATA:.1f}%) → 최근 활동 확인({event_vessel_total:,}, "
          f"{100*event_vessel_total/fishing_total:.1f}%) → 최종 모집단({enriched_total:,}, "
          f"{100*enriched_total/fishing_total:.1f}%)")
    print("각 단계 필터의 정확도(특히 2번)는 별도 검증 필요 — 위 ⚠ 표시 참고.")


if __name__ == "__main__":
    main()
