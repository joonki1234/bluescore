"""
담당: 김태윤

data/collect_vessel_spec_candidates.py가 모아둔 국내 선박제원정보 후보들
중에서, 어떤 후보가 실제로 같은 배인지 판정한다. 여기서부터가 "가공"
단계다 (rules_common.md 1번 — 수집은 이미 끝났고, 여기서 처음으로 판단이
들어간다).

매칭 규칙 (단계별, 위에서부터 먼저 성립하는 것을 채택):
    1. IMO 완전일치 — GFW imo와 후보 imoNo가 둘 다 있고 정확히 같으면
       확정. 가장 신뢰도 높음(국제 고유 식별자).
    2. 콜사인 완전일치 — GFW callSign과 후보 callSign이 대소문자 무시하고
       정확히 같으면 확정. 국내 API 자체는 검색 시 부분일치로 후보를
       주므로(예: "615" 검색 -> "017615" 등도 나옴), 여기서는 반드시
       완전일치만 인정한다.
    3. 이름 유사도(fuzzy) — 위 둘 다 실패하면 정규화된 영문명 유사도를
       계산한다. NAME_SIMILARITY_THRESHOLD는 팀에서 아직 확정하지 않은
       잠정값이다 (CLAUDE.md "매칭 신뢰도 임계값" 참고) — 검증 후 교체.
       임계값 미만이어도 최고 점수 후보와 점수는 기록해서, 나중에
       임계값이 바뀌면 재계산 없이 바로 다시 판정할 수 있게 한다.
    4. 미매칭 — 위 셋 다 실패하면 매칭 실패로 기록한다.

톤수는 매칭 판정에 쓰지 않는다 — 실사례(MEDRA)에서 IMO/콜사인/길이가
전부 일치하는데도 톤수만 3배 이상 차이가 났다(GFW 235GT vs 국내 743GT).
길이(length)는 판정에는 안 쓰지만 참고용 교차검증 신호로 같이 기록한다.

출력: data/raw/vessel_spec_matches/<run_timestamp>.jsonl.gz
    한 줄에 선박 하나, {vesselId, matchMethod, matchConfidence,
    matchedSpec(국내 필드들), crossCheck(length 비교 등)}
"""

import gzip
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.collect_vessel_spec_candidates import clean_vessel_name  # noqa: E402

CANDIDATES_BASE = PROJECT_ROOT / "data" / "raw" / "vessel_spec_candidates"
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"

# 잠정값 — 팀에서 아직 확정 안 함(CLAUDE.md "매칭 신뢰도 임계값" 참고).
# 검증 후 교체될 때까지 임시로 쓴다.
NAME_SIMILARITY_THRESHOLD = 0.85

# 국내 vesselKind(예: "92[원양 어선]", "63[근해 예선]")에 "어선"이
# 포함돼 있으면 국내 등록부 기준으로도 어선임이 확인된 것. 화이트리스트
# 방식(비어선 종류를 일일이 나열하는 블랙리스트보다 안전 — 실제로
# 블랙리스트 방식일 때 "시멘트운반선"처럼 목록에 없는 종류를 놓친 적
# 있음, 2026-08-13). "GFW가 FISHING이라고 분류했지만 실제로는 어선이
# 아닐 수 있다"는 의심 신호로만 기록한다 — 자동 제외하지 않는다(판단은
# 사람 몫, rules_common.md 1번 참고). 실사례: SAWASDEE BALTIC이 GFW엔
# FISHING으로 잡혔지만 국내 vesselKind는 "풀컨테이너선"이었음.
FISHING_VESSEL_KIND_KEYWORD = "어선"


def check_possible_misclassification(vessel_kind: str) -> bool:
    """vesselKind에 국내 등록부 기준 '어선' 표시가 없으면 True
    (GFW가 FISHING이라고 했지만 국내는 다르게 분류한다는 의심 신호일
    뿐, 자동 제외 아님). vesselKind 자체가 없으면(국내에 그 필드가
    안 채워진 경우) 판단 불가로 보고 False."""
    if not vessel_kind:
        return False
    return FISHING_VESSEL_KIND_KEYWORD not in vessel_kind


def normalize_name(name: str) -> str:
    """이름 유사도 비교 전 정규화: 대문자 통일, 공백/특수문자 정리,
    GFW 자기신고명에 흔한 두 가지 패턴 제거.

    숫자접두어/"XX HO" 제거는 collect_vessel_spec_candidates.py의
    clean_vessel_name()과 동일 로직을 그대로 재사용한다(검색 시점
    정제와 비교 시점 정규화가 따로 놀면서 서서히 어긋나는 걸 방지 —
    실측 근거는 그쪽 함수의 docstring 참고).
    """
    if not name:
        return ""
    name = clean_vessel_name(name).upper()
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def find_latest_candidates_run() -> Path:
    runs = sorted(CANDIDATES_BASE.iterdir())
    if not runs:
        raise RuntimeError("data/raw/vessel_spec_candidates/에 수집 결과가 없습니다. 먼저 collect_vessel_spec_candidates.py를 실행하세요.")
    latest = runs[-1]

    progress_path = latest / "_progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        status = progress.get("status")
        if status != "complete":
            attempted = (
                progress.get("completed_count", 0)
                + len(progress.get("skipped_no_identifier", []))
                + len(progress.get("failed", []))
            )
            total = progress.get("total_target", "?")
            print(
                f"[warn] {latest.name}의 수집이 아직 끝나지 않았습니다 "
                f"(status={status}, {attempted}/{total}건 처리됨). "
                f"나머지 선박은 candidates 파일 자체가 없어 자동으로 "
                f"'unmatched'와 구분 없이 섞입니다 — collect_vessel_spec_candidates.py를 "
                f"이어서 완료한 뒤 다시 매칭하는 것을 권장합니다."
            )

    return latest


def match_one(record: dict) -> dict:
    gfw_imo = record.get("gfwImo")
    gfw_call_sign = record.get("gfwCallSign")
    gfw_name = record.get("gfwName")

    all_candidates = []
    for attempt in record["attempts"]:
        for c in attempt["candidates"]:
            all_candidates.append(c)

    # 1단계: IMO 완전일치
    if gfw_imo:
        for c in all_candidates:
            if c.get("imoNo") and str(c["imoNo"]).strip() == str(gfw_imo).strip():
                return _build_match_result(record, c, "imo_exact", 1.0)

    # 2단계: 콜사인 완전일치 (대소문자 무시)
    if gfw_call_sign:
        gfw_cs_upper = gfw_call_sign.strip().upper()
        for c in all_candidates:
            if (c.get("callSign") or "").strip().upper() == gfw_cs_upper:
                return _build_match_result(record, c, "callsign_exact", 1.0)

    # 3단계: 이름 유사도
    if gfw_name and all_candidates:
        best_candidate = None
        best_score = 0.0
        for c in all_candidates:
            score = max(
                name_similarity(gfw_name, c.get("vesselNameEng")),
                name_similarity(gfw_name, c.get("vesselNameKor")),
            )
            if score > best_score:
                best_score = score
                best_candidate = c
        if best_candidate is not None:
            method = "name_fuzzy" if best_score >= NAME_SIMILARITY_THRESHOLD else "name_fuzzy_below_threshold"
            return _build_match_result(record, best_candidate, method, best_score)

    # 4단계: 미매칭
    return {
        "vesselId": record["vesselId"],
        "matchMethod": "unmatched",
        "matchConfidence": 0.0,
        "candidateCount": len(all_candidates),
        "matchedSpec": None,
        "crossCheck": None,
        "possibleMisclassification": None,
    }


def _build_match_result(record: dict, candidate: dict, method: str, confidence: float) -> dict:
    cross_check = None
    gfw_length = record.get("gfwLengthM")  # 현재 candidates 파일엔 없음 — 추후 GFW length 포함 시 채워짐
    if gfw_length and candidate.get("lengthM"):
        cross_check = {
            "gfwLengthM": gfw_length,
            "domesticLengthM": candidate.get("lengthM"),
            "lengthDiffM": round(abs(gfw_length - candidate["lengthM"]), 2),
        }
    return {
        "vesselId": record["vesselId"],
        "matchMethod": method,
        "matchConfidence": round(confidence, 4),
        "candidateCount": sum(len(a["candidates"]) for a in record["attempts"]),
        "matchedSpec": candidate,
        "crossCheck": cross_check,
        "possibleMisclassification": check_possible_misclassification(candidate.get("vesselKind")),
    }


def main():
    run_dir = find_latest_candidates_run()
    candidates_dir = run_dir / "candidates"
    files = sorted(candidates_dir.glob("*.json"))
    print(f"[source] {run_dir.name} ({len(files)}건)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"vessel_spec_matches__{run_dir.name.split('__')[-1]}.jsonl.gz"

    counts = {}
    misclassification_count = 0
    with gzip.open(out_path, "wt", encoding="utf-8") as out:
        for f in files:
            record = json.loads(f.read_text(encoding="utf-8"))
            result = match_one(record)
            counts[result["matchMethod"]] = counts.get(result["matchMethod"], 0) + 1
            if result.get("possibleMisclassification"):
                misclassification_count += 1
            out.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"[output] {out_path}")
    print("[summary]")
    for method, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {method}: {count} ({100*count/len(files):.1f}%)")
    print(f"[정보성] 매칭된 것 중 비어선 의심(possibleMisclassification): {misclassification_count}건")


if __name__ == "__main__":
    main()
