"""
담당: 김태윤

TAC 할당승인정보(data/raw/해양수산부_수산정보_TAC 할당 승인 정보_20251105.csv,
data.go.kr 15136496)를 GFW 어업 선박에 연결한다 — 톤수·기관출력(마력)·
할당어업종류를 확보하기 위함. TAC는 콜사인/IMO가 없어 이름 유사도가
유일한 판정 수단이다.

두 경로를 각각 돌려서 서로 다른 파일로 남긴다(2026-08-14 시행착오 끝에
확정 — 아래 "경로 A vs B" 참고):

경로 A: TAC(한글) -> MOF 선박제원정보(vesselNameKor, 한글) -> GFW
    match_vessel_spec.py의 확정 매칭(imo_exact/callsign_exact/name_fuzzy)만
    대상으로 쓴다. MOF<->GFW 연결이 이미 검증돼 있어 신뢰도가 가장 높지만,
    선박제원정보 수집이 63.6%(6,024/9,468척)만 끝난 상태라 커버리지가
    그만큼으로 제한된다 — 나머지 선박제원 수집이 끝나면 다시 돌려야 한다.
    출력: data/raw/tac_vessel_matches__<날짜>.jsonl.gz

경로 B: TAC(한글) -> romanize_korean()으로 로마자화 -> GFW 자기신고명과 직접 비교
    MOF를 거치지 않아 GFW 전체 9,468척을 대상으로 할 수 있다. 로마자화가
    근사값이고 GFW 자기신고명도 표기가 일정하지 않아 개별 신뢰도는 경로 A보다
    낮지만, 경로 A의 좁은 커버리지를 보완한다.
    출력: data/raw/tac_vessel_matches_direct__<날짜>.jsonl.gz

경로 A vs B 비교(2026-08-14 실측, 상호매칭 기준): A 76척(모집단 493척 중
11.4%) vs B 329척(모집단 9,468척 중 3.2%) — 모집단당 정확도는 A가 높지만
B가 MOF 커버리지 한계를 우회해 절대 수로는 5.5배 더 찾아낸다. 두 경로가
겹치는 6척 중 3척은 서로 다른 TAC 선박을 지목했는데, 그 3건 모두 A의
신뢰도가 B보다 높거나 같았다 — **두 경로가 충돌하면 A(MOF 경유)를
우선한다.**

오탐을 줄이기 위해 "상호 최고매칭"(mutual best match)만 확정으로
인정한다: TAC 선박 X의 최고 점수 상대가 Y이고, 동시에 Y 입장에서도
최고 점수 상대가 X일 때만 matched로 채택한다(단순 최고매칭이면 흔한
이름 "바다호"/"동양호" 등에서 다른 배로 잘못 연결되는 사례가 실제로
있었음).

숫자 처리(split_number_and_base() 참고, 2026-08-14 추가): 이름의 숫자를
base와 분리해서 base끼리만 문자 유사도 비교하고, 숫자는 따로 정확히
비교해 numberStatus 필드로 남긴다. 처음엔 숫자를 문자열에 그대로 두고
비교했더니 "23대영호"와 "227대영호"(실제로 다른 배일 가능성이 높음 —
동명이인처럼 같은 이름 다른 번호의 선박이 흔함)가 부분점수로 매칭돼
버리는 문제가 있었다. numberStatus가 "mismatch"인 건은 자동으로
같다/다르다 판정하지 않고 사람이 확인하도록 남겨둔다 — "102대풍호"가
GFW 자기신고 "DAEPUNG1HO"(번호가 다름)와 같은 배인지조차 공식 문서로
확인이 안 되기 때문(팀에 문의 필요).

TAC는 선박 1척(어선번호)당 여러 행(할당/어업종별로 나뉨)이라, 매칭 전에
어선번호 기준으로 먼저 집계한다. 톤수/마력이 행마다 다르면(원칙: 임의로
평균 내지 않고 원본 보존 — 팀 공유 데이터검증 문서의 원칙과 동일) 첫
값을 대표값으로 쓰고 충돌 여부만 별도 필드에 기록한다.

출력 (세 파일):
    data/raw/tac_vessel_matches__<날짜>.jsonl.gz      경로 A 전체 결과
    data/raw/tac_vessel_matches_direct__<날짜>.jsonl.gz 경로 B 전체 결과
    data/raw/tac_vessel_matches_confirmed__<날짜>.jsonl.gz
        위 두 결과 중 "바로 신뢰 가능" 등급만 뽑아 중복 제거한 최종본
        (build_confirmed_tier() 참고) — data/merge_tac_into_enriched.py가
        이 파일을 읽어 gfw_vessels_enriched.jsonl.gz에 병합한다.
    공통 레코드 구조: {vesselId, matchMethod, matchConfidence, numberStatus,
    tacVesselNo, tacName, tonnageGt, enginePowerHp, gearTypes,
    tonnageConflict, enginePowerConflict}

실측 결과 요약(2026-08-14, 선박제원정보 100% 수집 반영한 최종 실행 기준,
두 경로 합쳐 중복 제거 418척): **93척 바로 신뢰 가능**(경로 A 중
numberStatus!=mismatch, 또는 경로 A와 안 겹치는 경로 B 중
numberStatus=match), 나머지 325척은 이름은 맞으나 교차검증 신호가
없거나(numberStatus=none/one_side_missing) 숫자가 안 맞아서
(numberStatus=mismatch) 검토 필요 — 정확한 세부 건수는 스크립트 실행
시 출력되는 요약 참고(하드코딩하지 않음, 재실행 때마다 바뀔 수 있어서).
"""

import csv
import gzip
import json
import re
import sys
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.collect_vessel_spec_candidates import clean_vessel_name, load_target_vessels  # noqa: E402
from data.match_vessel_spec import normalize_name as normalize_gfw_name  # noqa: E402
from data.snapshot_utils import find_latest  # noqa: E402
from data.vessel_spec_client import _to_float  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"
TAC_CSV_PATH = find_latest(OUTPUT_DIR, "해양수산부_수산정보_TAC 할당 승인 정보_*.csv")
MOF_MATCHES_PATH = find_latest(OUTPUT_DIR, "vessel_spec_matches__*.jsonl.gz")

CONFIDENT_MOF_METHODS = {"imo_exact", "callsign_exact", "name_fuzzy"}

# 잠정값 — match_vessel_spec.py의 NAME_SIMILARITY_THRESHOLD와 별개로 관리한다.
# TAC<->MOF는 둘 다 한글이라 같은 임계값을 재사용해도 되지만, 실측 검증
# 전까지는 독립적으로 튜닝할 수 있게 분리해둔다. 팀에서 아직 확정 안 함.
NAME_SIMILARITY_THRESHOLD = 0.85


# 국어의 로마자 표기법(개정 로마자 표기법) 간이 구현 — MOF 확정매칭(63.6%만
# 수집된 상태라 커버리지가 제한적)을 거치지 않고, TAC 한글명을 로마자로
# 변환해 GFW 자기신고명과 직접 비교하는 대안 경로를 시도하기 위함
# (2026-08-14: 3개 샘플 검증 결과 2개 완전일치, 1개는 "영"->"YEONG"
# vs 실제 등록명 "YOUNG" 표기 차이로 근사 일치 — 실전 투입 전 이 함수의
# 정확도를 실제 GFW 전체 모집단으로 검증해본다). 받침 로마자화는 연음
# 규칙(예: 받침 뒤 모음이 오면 그대로 이어짐)을 반영하지 않은 간이
# 버전이라 정확한 표준 표기와 다를 수 있다 — 근사 매칭용으로만 쓴다.
_RR_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_RR_MEDIALS = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
    "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
]
_RR_FINALS = [
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "l",
    "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t",
]


def romanize_korean(text: str) -> str:
    """한글 음절을 개정 로마자 표기법 근사값으로 변환한다. 한글이 아닌
    문자(숫자·영문 등)는 그대로 통과시킨다."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            initial = offset // (21 * 28)
            medial = (offset % (21 * 28)) // 28
            final = offset % 28
            out.append(_RR_INITIALS[initial] + _RR_MEDIALS[medial] + _RR_FINALS[final])
        else:
            out.append(ch)
    return "".join(out).upper()


def split_number_and_base(name: str) -> tuple:
    """이름에서 숫자를 전부 뽑아 이어붙이고, 나머지 글자만 base로 분리한다.

    2026-08-14: 숫자를 이름 문자열에 그대로 두고 통째로 유사도 비교하면
    두 가지 문제가 있었다 — (1) "23대영호" vs "227대영호"처럼 실제로는
    다른 배일 숫자 차이를 SequenceMatcher가 부분점수로 눈감아줌,
    (2) "102대풍호"(TAC, 숫자가 앞) vs "DAEPUNG1HO"(GFW 자기신고,
    숫자가 이름 중간)처럼 숫자 위치가 소스마다 달라 같은 배도 문자열이
    안 맞음. 숫자를 아예 분리해서 base는 base끼리 유사도 비교, 숫자는
    숫자끼리 별도로 정확히 비교하면 위치 문제는 사라지고, 숫자 불일치는
    (실제로 다른 배인지 확신할 근거가 없으므로 — "102대풍호"가
    "대풍102호"와 같은 배인지조차 공식 문서로 확인 못 함) 자동 판정하지
    않고 numberStatus 필드로 남겨 사람이 보게 한다.
    """
    if not name:
        return None, ""
    digits = "".join(re.findall(r"\d+", name))
    base = re.sub(r"\d+", "", name)
    return (digits or None, base)


def _number_status(query_number, candidate_number) -> str:
    if query_number is None and candidate_number is None:
        return "none"
    if query_number is None or candidate_number is None:
        return "one_side_missing"
    try:
        return "match" if int(query_number) == int(candidate_number) else "mismatch"
    except ValueError:
        return "match" if query_number == candidate_number else "mismatch"


def normalize_korean_name(name: str) -> str:
    """한글 선박명 비교용 정규화 (숫자는 split_number_and_base()가 이미
    분리했다고 가정 — 이 함수는 base 부분만 받는다). clean_vessel_name()의
    HO접미어 제거는 로마자 대상 규칙이라 한글엔 대부분 no-op이지만, 공백/
    대소문자 정리 부분은 공유해서 정규화 로직이 여러 곳에서 어긋나지
    않게 한다."""
    if not name:
        return ""
    name = clean_vessel_name(name).upper()
    name = re.sub(r"[^A-Z 가-힣]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def load_tac_vessels(csv_path: Path = TAC_CSV_PATH) -> list:
    """TAC CSV를 어선번호 기준으로 집계한다."""
    by_vessel_no = {}

    with open(csv_path, encoding="cp949", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vessel_no = (row.get("어선 번호") or "").strip()
            if not vessel_no:
                continue
            name = (row.get("어선 명") or "").strip()
            tonnage = _to_float(row.get("선박 톤수"))
            power = _to_float(row.get("선박 마력"))
            gear = (row.get("할당 어업 종류 명") or "").strip()

            entry = by_vessel_no.get(vessel_no)
            if entry is None:
                entry = {
                    "tacVesselNo": vessel_no,
                    "tacName": name,
                    "tonnageGt": tonnage,
                    "enginePowerHp": power,
                    "gearTypes": set(),
                    "tonnageConflict": None,
                    "enginePowerConflict": None,
                }
                by_vessel_no[vessel_no] = entry

            if gear:
                entry["gearTypes"].add(gear)
            if tonnage is not None and entry["tonnageGt"] is not None and tonnage != entry["tonnageGt"]:
                entry["tonnageConflict"] = {"first": entry["tonnageGt"], "other": tonnage}
            if power is not None and entry["enginePowerHp"] is not None and power != entry["enginePowerHp"]:
                entry["enginePowerConflict"] = {"first": entry["enginePowerHp"], "other": power}

    vessels = list(by_vessel_no.values())
    for v in vessels:
        v["gearTypes"] = sorted(v["gearTypes"])
    return vessels


def load_mof_matches_and_misclassification_flags(path: Path = MOF_MATCHES_PATH) -> tuple:
    """MOF_MATCHES_PATH를 한 번만 읽어 (확정 매칭 목록, 비어선 의심 vesselId
    집합) 튜플을 반환한다. 원래 이 둘을 각자 파일을 처음부터 다시 읽는
    별도 함수(load_mof_confirmed_matches/load_mof_misclassification_flags)로
    나눠뒀었는데, 같은 ~740KB gzip 파일을 두 번 열고 파싱하는 낭비라 하나로
    합쳤다(2026-08-14).

    - 확정 매칭: match_vessel_spec.py의 확정 매칭(imo_exact/callsign_exact/
      name_fuzzy)만, GFW vesselId와 이미 연결돼 있다.
    - 비어선 의심 집합: matchMethod와 무관하게 matchedSpec이 있고
      possibleMisclassification=True인 적이 있는 GFW vesselId 전부.
      2026-08-14 발견: TAC 확정매칭 93척 중 72척이 하필 이 집합과 겹쳤다 —
      실제 vesselKind를 까보니 석유제품운반선/화물선/예선 등 진짜 비어선
      이었다. TAC 쪽 이름 매칭이 흔한 이름("OO호") 때문에 실제로는
      다른(비어선) 배로 잘못 연결됐을 가능성이 높다는 뜻 —
      build_confirmed_tier()에서 이 집합과 겹치는 건 "확정"에서 빼고
      별도로 표시한다.
    """
    confirmed_matches = []
    misclassified_ids = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("possibleMisclassification"):
                misclassified_ids.add(r["vesselId"])
            if r["matchMethod"] in CONFIDENT_MOF_METHODS:
                spec = r.get("matchedSpec") or {}
                kor_name = spec.get("vesselNameKor")
                if kor_name:
                    confirmed_matches.append(
                        {
                            "vesselId": r["vesselId"],
                            "vesselNameKor": kor_name,
                            "mofMatchMethod": r["matchMethod"],
                        }
                    )
    return confirmed_matches, misclassified_ids


def _best_match_normalized(norm_name: str, candidate_names_normalized: list) -> tuple:
    """이미 정규화된 norm_name과 candidate_names_normalized 중 가장 유사한
    것의 (index, score). quick_ratio()로 상한을 먼저 확인해 불필요한 전체
    비교(ratio())를 건너뛴다. 정규화 방식이 호출부마다 다를 수 있어
    (한글 비교 vs 로마자 비교) 정규화는 호출자가 하고 이 함수는 순수
    문자열 비교만 담당한다."""
    if not norm_name:
        return None, 0.0

    matcher = SequenceMatcher(None, norm_name, "")
    best_idx, best_score = None, 0.0
    for idx, cand_norm in enumerate(candidate_names_normalized):
        if not cand_norm:
            continue
        matcher.set_seq2(cand_norm)
        if matcher.quick_ratio() <= best_score:
            continue
        score = matcher.ratio()
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx, best_score


def match_tac_to_mof(tac_vessels: list, mof_matches: list) -> list:
    """상호 최고매칭(mutual best match)만 확정으로 채택한다. 숫자는
    base와 분리해서 비교하고, 결과에 numberStatus로 남긴다(자동으로
    같다/다르다 판정하지 않음 — split_number_and_base() docstring 참고)."""
    tac_num_base = [split_number_and_base(tv["tacName"]) for tv in tac_vessels]
    mof_num_base = [split_number_and_base(m["vesselNameKor"]) for m in mof_matches]

    tac_bases_normalized = [normalize_korean_name(base) for _, base in tac_num_base]
    mof_bases_normalized = [normalize_korean_name(base) for _, base in mof_num_base]

    # TAC -> 최고매칭 MOF (base 이름 기준)
    tac_best = [_best_match_normalized(n, mof_bases_normalized) for n in tac_bases_normalized]
    # MOF -> 최고매칭 TAC (역방향, "상호" 여부 판정용)
    mof_best = [_best_match_normalized(n, tac_bases_normalized) for n in mof_bases_normalized]

    results = []
    for mof_idx, mof in enumerate(mof_matches):
        tac_idx, score = mof_best[mof_idx]
        record = {
            "vesselId": mof["vesselId"],
            "matchMethod": "unmatched",
            "matchConfidence": 0.0,
            "numberStatus": None,
            "tacVesselNo": None,
            "tacName": None,
            "tonnageGt": None,
            "enginePowerHp": None,
            "gearTypes": None,
            "tonnageConflict": None,
            "enginePowerConflict": None,
        }
        if tac_idx is not None and score >= NAME_SIMILARITY_THRESHOLD:
            is_mutual = tac_best[tac_idx][0] == mof_idx
            tv = tac_vessels[tac_idx]
            mof_number, _ = mof_num_base[mof_idx]
            tac_number, _ = tac_num_base[tac_idx]
            record.update(
                {
                    "matchMethod": "name_fuzzy_mutual" if is_mutual else "name_fuzzy_non_mutual",
                    "matchConfidence": round(score, 4),
                    "numberStatus": _number_status(mof_number, tac_number),
                    "tacVesselNo": tv["tacVesselNo"],
                    "tacName": tv["tacName"],
                    "tonnageGt": tv["tonnageGt"],
                    "enginePowerHp": tv["enginePowerHp"],
                    "gearTypes": tv["gearTypes"],
                    "tonnageConflict": tv["tonnageConflict"],
                    "enginePowerConflict": tv["enginePowerConflict"],
                }
            )
        elif tac_idx is not None:
            record["matchMethod"] = "name_fuzzy_below_threshold"
            record["matchConfidence"] = round(score, 4)
        results.append(record)
    return results


def match_tac_to_gfw_direct(tac_vessels: list, gfw_vessels: list) -> list:
    """MOF를 거치지 않고, TAC 한글명을 romanize_korean()으로 로마자화해
    GFW 자기신고명과 직접 비교한다. MOF 확정매칭(63.6%만 수집된 상태라
    493척으로 제한됨)의 커버리지 한계를 우회해 GFW 전체 9,468척을
    대상으로 시도해볼 수 있지만, 로마자화 자체가 근사값이고 GFW
    자기신고명도 표기가 일정하지 않아 MOF 경로보다 신뢰도가 낮을 수
    있다 — 두 결과를 비교해서 실제로 어느 쪽이 나은지 확인할 것.
    숫자는 base와 분리해서 비교한다(match_tac_to_mof()와 동일 원칙).
    """
    tac_num_base = [split_number_and_base(tv["tacName"]) for tv in tac_vessels]
    gfw_num_base = [split_number_and_base(v["name"] or "") for v in gfw_vessels]

    gfw_bases_normalized = [normalize_gfw_name(base) for _, base in gfw_num_base]
    tac_bases_romanized = [normalize_gfw_name(romanize_korean(base)) for _, base in tac_num_base]

    tac_best = [_best_match_normalized(n, gfw_bases_normalized) for n in tac_bases_romanized]
    gfw_best = [_best_match_normalized(n, tac_bases_romanized) for n in gfw_bases_normalized]

    results = []
    for gfw_idx, gv in enumerate(gfw_vessels):
        tac_idx, score = gfw_best[gfw_idx]
        record = {
            "vesselId": gv["vesselId"],
            "matchMethod": "unmatched",
            "matchConfidence": 0.0,
            "numberStatus": None,
            "tacVesselNo": None,
            "tacName": None,
            "tonnageGt": None,
            "enginePowerHp": None,
            "gearTypes": None,
            "tonnageConflict": None,
            "enginePowerConflict": None,
        }
        if tac_idx is not None and score >= NAME_SIMILARITY_THRESHOLD:
            is_mutual = tac_best[tac_idx][0] == gfw_idx
            tv = tac_vessels[tac_idx]
            gfw_number, _ = gfw_num_base[gfw_idx]
            tac_number, _ = tac_num_base[tac_idx]
            record.update(
                {
                    "matchMethod": "name_fuzzy_mutual" if is_mutual else "name_fuzzy_non_mutual",
                    "matchConfidence": round(score, 4),
                    "numberStatus": _number_status(gfw_number, tac_number),
                    "tacVesselNo": tv["tacVesselNo"],
                    "tacName": tv["tacName"],
                    "tonnageGt": tv["tonnageGt"],
                    "enginePowerHp": tv["enginePowerHp"],
                    "gearTypes": tv["gearTypes"],
                    "tonnageConflict": tv["tonnageConflict"],
                    "enginePowerConflict": tv["enginePowerConflict"],
                }
            )
        elif tac_idx is not None:
            record["matchMethod"] = "name_fuzzy_below_threshold"
            record["matchConfidence"] = round(score, 4)
        results.append(record)
    return results


def build_confirmed_tier(results_via_mof: list, results_direct: list, mof_misclassified_ids: set) -> tuple:
    """두 경로 결과에서 "바로 신뢰 가능" 등급만 뽑아 vesselId 기준으로
    중복 제거한 최종본을 만든다. (확정 리스트, 충돌로 걸러진 리스트) 튜플을
    반환한다.

    등급 기준(2026-08-14 결정):
        - 경로 A(MOF 경유) mutual + numberStatus != "mismatch"
        - 경로 B(직접) mutual + numberStatus == "match" (숫자까지 정확히
          일치 — MOF 검증 없이 로마자 비교만으로 신뢰하려면 이 정도는
          돼야 함)
    두 경로 다 해당하는 vesselId는 A를 우선한다(경로 A vs B 비교 항목
    참고 — 실측상 A가 더 신뢰도 높았음).

    추가 교차검증(2026-08-14): mof_misclassified_ids(load_mof_misclassification_flags()
    참고)와 겹치는 건 확정에서 빼고 conflicting 리스트로 따로 보낸다 —
    실측 사례: 93척 중 72척이 이 경우였고, 실제 vesselKind가 석유제품
    운반선/화물선 등 진짜 비어선이었다. TAC 이름 매칭이 흔한 이름 때문에
    실제로는 다른(비어선) 배로 잘못 연결됐을 가능성이 높다는 뜻.
    """
    confirmed_by_id = {}

    for r in results_via_mof:
        if r["matchMethod"] == "name_fuzzy_mutual" and r["numberStatus"] != "mismatch":
            confirmed_by_id[r["vesselId"]] = dict(r, source="mof")

    for r in results_direct:
        if r["vesselId"] in confirmed_by_id:
            continue  # 경로 A가 이미 확정했으면 그대로 우선
        if r["matchMethod"] == "name_fuzzy_mutual" and r["numberStatus"] == "match":
            confirmed_by_id[r["vesselId"]] = dict(r, source="direct")

    confirmed, conflicting = [], []
    for vessel_id, record in confirmed_by_id.items():
        if vessel_id in mof_misclassified_ids:
            conflicting.append(dict(record, conflictReason="mof_possible_misclassification"))
        else:
            confirmed.append(record)

    return confirmed, conflicting


def _write_and_summarize(results: list, out_path: Path, label: str) -> dict:
    counts = defaultdict(int)
    with gzip.open(out_path, "wt", encoding="utf-8") as out:
        for r in results:
            counts[r["matchMethod"]] += 1
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[output:{label}] {out_path}")
    for method, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {method}: {count} ({100*count/len(results):.1f}%)" if results else f"  {method}: {count}")
    return counts


def main():
    print("[1/4] TAC CSV 로드 및 어선번호 단위 집계...")
    tac_vessels = load_tac_vessels()
    print(f"  TAC 고유 선박: {len(tac_vessels)}척")

    print("[2/4] MOF 확정 매칭(GFW 연결된 것) + 비어선 의심 플래그 로드...")
    mof_matches, mof_misclassified_ids = load_mof_matches_and_misclassification_flags()
    print(f"  MOF 확정 매칭(vesselNameKor 보유): {len(mof_matches)}척, 플래그된 GFW vesselId: {len(mof_misclassified_ids)}개")

    print("[3/4] 경로 A: TAC <-> MOF(한글) -> GFW (상호 최고매칭만 확정)...")
    results_via_mof = match_tac_to_mof(tac_vessels, mof_matches)
    counts_via_mof = _write_and_summarize(
        results_via_mof,
        OUTPUT_DIR / f"tac_vessel_matches__{date.today().isoformat()}.jsonl.gz",
        "MOF 경유",
    )

    print("[4/4] 경로 B: TAC 로마자화 <-> GFW 직접 비교 (MOF 커버리지 한계 우회 시도)...")
    gfw_vessels = load_target_vessels()
    print(f"  GFW 대상 선박(이벤트 있는 전체): {len(gfw_vessels)}척")
    results_direct = match_tac_to_gfw_direct(tac_vessels, gfw_vessels)
    counts_direct = _write_and_summarize(
        results_direct,
        OUTPUT_DIR / f"tac_vessel_matches_direct__{date.today().isoformat()}.jsonl.gz",
        "직접(로마자)",
    )

    mutual_via_mof = counts_via_mof.get("name_fuzzy_mutual", 0)
    mutual_direct = counts_direct.get("name_fuzzy_mutual", 0)
    print(
        f"\n[비교] MOF 경유 상호매칭 {mutual_via_mof}척 (모집단 {len(mof_matches)}척 중) "
        f"vs 직접 상호매칭 {mutual_direct}척 (모집단 {len(gfw_vessels)}척 중)"
    )

    confirmed, conflicting = build_confirmed_tier(results_via_mof, results_direct, mof_misclassified_ids)

    confirmed_path = OUTPUT_DIR / f"tac_vessel_matches_confirmed__{date.today().isoformat()}.jsonl.gz"
    _write_and_summarize(confirmed, confirmed_path, "확정본")

    conflicting_path = OUTPUT_DIR / f"tac_vessel_matches_conflicting__{date.today().isoformat()}.jsonl.gz"
    _write_and_summarize(conflicting, conflicting_path, "충돌(비어선 의심과 겹침)")

    # "전체 후보"는 상호매칭(mutual)된 것만 기준으로 잡는다 — below_threshold/
    # non_mutual까지 포함하면 분모가 너무 넓어져(예: 5,862척) "검토해볼 만한
    # 후보"라는 의미가 흐려진다.
    mutual_union = len({r["vesselId"] for r in results_via_mof if r["matchMethod"] == "name_fuzzy_mutual"}
                        | {r["vesselId"] for r in results_direct if r["matchMethod"] == "name_fuzzy_mutual"})
    print(
        f"  바로 신뢰 가능: {len(confirmed)}척 / MOF와 충돌(재검토 필요): {len(conflicting)}척 "
        f"(상호매칭 중복제거 {mutual_union}척 중, 나머지 {mutual_union - len(confirmed) - len(conflicting)}척은 검토/제외 대상)"
    )


if __name__ == "__main__":
    main()
