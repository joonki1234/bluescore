"""
담당: 김준기, 오동규

`data_new/processed/final_vessel_matches.jsonl`(김태윤 작업물)을
`services/real_scoring.py`가 기대하는 평판화된 선박 레코드(vesselId/tonnage/
fishingType)로 변환한다.

톤수 우선순위: tac.tonnageGtTac > mof.tonnageGtMof (둘 다 문자열이라 float로
변환, 파싱 실패/누락은 None). 실측 확인 결과 이 둘이 동시에 채워진 행은
0건이라 실제로는 우선순위가 발동하지 않는다 — 다만 나중에
데이터가 바뀌어 둘 다 채워지는 경우가 생기면 이 우선순위가 조용히 MOF 값을
버린다는 점은 알아둘 것.

fishingType은 `data_new/processed/gfw_vessels_normalized.jsonl`
(GFW 자체 gear 정보, `combinedGearTypes`)이 공개돼서 이제 채운다.
CARGO/PASSENGER/CARRIER(자기모순 라벨, 구 `data/filter_self_contradicting_labels.py`
참고 — "어업선박"이라는 앵커 분류와 자기 gear 신고가 모순되는 경우)는 제외한다 —
비어선일 가능성이 큰 선박을 실제 어법 카테고리처럼 그룹핑에 섞으면 안 되기
때문이다.

FISHING/NA/OTHER/GEAR/FIXED_GEAR 같은 뭉뚱그려진 라벨(구
`filter_self_contradicting_labels.py`의 AMBIGUOUS_LABELS와 동일)도 제외한다.
처음엔 이것도 그냥 남겨뒀는데, 유사군 그룹핑에
gearType을 추가한 결과를 실제로 돌려보니 A축 실산출 비율이 73%(3,887/5,323)
→32%(1,684/5,323)로 급락했다 — 전체의 44%가 이 뭉뚱그려진 라벨이라, 그룹이
톤수×**gear**×해역×계절로 과도하게 쪼개지면서 최소표본(20척) 미달 그룹이
급증한 것. "더 정밀한 그룹핑"이 "더 적은 실산출"을 낳는 트레이드오프가
실측으로 확인된 사례 — 그래서 애매한 라벨은 None(=톤수·해역·계절만으로
그룹핑)으로 되돌리고, 구체적인 gear 값(TRAWLERS 등)만 그룹 키로 쓴다.

gfw_vessels_normalized.jsonl이 없으면(공개 전 상태) fishingType은 빈 리스트로
대체되며, 이 경우
score/peer_grouping.gear_type_key(None)이 None을 반환해 톤수·해역·계절만으로
그룹핑되므로 실행 자체는 막히지 않는다.

이벤트 파일은 별도 변환이 필요 없다 — `data_new/processed/events_with_weather.jsonl.gz`가
`eventId/vesselId/start/latitude/longitude` 등 score/axis_a_pressure.py가
요구하는 필드를 이미 그대로 갖고 있다.

출력: data_new/processed/vessels_for_score.jsonl.gz
"""

import gzip
import json
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IN_PATH = PROJECT_ROOT / "data_new" / "processed" / "final_vessel_matches.jsonl"
GEAR_PATH = PROJECT_ROOT / "data_new" / "processed" / "gfw_vessels_normalized.jsonl"
OUT_PATH = PROJECT_ROOT / "data_new" / "processed" / "vessels_for_score.jsonl.gz"

# GFW 자기신고 gear가 "어업선박"이라는 앵커 분류와 자기모순인 라벨 — 이런 값은
# 실제 어법 카테고리가 아니라 비어선일 가능성이 높다는 신호라 fishingType에서
# 제외한다 (구 data/filter_self_contradicting_labels.py의 SELF_CONTRADICTING_LABELS
# 와 동일한 목록).
SELF_CONTRADICTING_GEAR_LABELS = {"CARGO", "PASSENGER", "CARRIER"}

# 뭉뚱그려진(=그룹핑에 쓰기엔 정보가 없는) 라벨 — 구
# data/filter_self_contradicting_labels.py의 AMBIGUOUS_LABELS와 동일한 목록.
# 그대로 두면 유사군이 과도하게 쪼개지는 게 실측으로 확인돼(위 docstring 참고)
# fishingType에서 제외한다 — 이 라벨만 있는 선박은 톤수·해역·계절만으로 묶인다.
AMBIGUOUS_GEAR_LABELS = {
    "FISHING", "OTHER", "NA", "INCONCLUSIVE", "GEAR", "FIXED_GEAR",
    "TROLLERS", "OTHER_PURSE_SEINES", "OTHER_SEINES",
}


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def load_gear_types(path: Path = GEAR_PATH) -> Dict[str, List[str]]:
    """gfw_vessels_normalized.jsonl에서 vesselId -> fishingType(gear 리스트)을 만든다.

    파일이 없으면(아직 공개 전) 빈 dict를 반환한다 — 호출부는 이 경우 fishingType을
    빈 리스트로 채우면 된다.
    """
    if not path.exists():
        return {}

    gear_by_vessel: Dict[str, List[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            excluded = SELF_CONTRADICTING_GEAR_LABELS | AMBIGUOUS_GEAR_LABELS
            gear_types = [g for g in (row.get("combinedGearTypes") or []) if g not in excluded]
            gear_by_vessel[row["vesselId"]] = gear_types
    return gear_by_vessel


def convert_row(row: dict, gear_by_vessel: Dict[str, List[str]] = None) -> dict:
    """final_vessel_matches.jsonl의 한 행을 score/ 계약 형태로 변환한다."""
    gear_by_vessel = gear_by_vessel or {}
    tac = row.get("tac") or {}
    mof = row.get("mof") or {}

    tonnage = _to_float(tac.get("tonnageGtTac"))
    if tonnage is None:
        tonnage = _to_float(mof.get("tonnageGtMof"))

    return {
        "vesselId": row["gfwVesselId"],
        "name": row.get("gfwName"),
        "tonnage": tonnage,
        "fishingType": gear_by_vessel.get(row["gfwVesselId"], []),
        "matchTier": row.get("matchTier"),
        "matchConfidence": row.get("matchConfidence"),
        "fuzzyScore": row.get("fuzzyScore"),
        "fuzzySource": row.get("fuzzySource"),
    }


def main() -> None:
    gear_by_vessel = load_gear_types()
    print(f"[gear] {GEAR_PATH.name}: {'로드됨 ' + str(len(gear_by_vessel)) + '척' if gear_by_vessel else '없음(fishingType 전부 빈 리스트)'}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with_tonnage = 0
    with_gear = 0
    with open(IN_PATH, encoding="utf-8") as f_in, gzip.open(OUT_PATH, "wt", encoding="utf-8") as f_out:
        for line in f_in:
            row = json.loads(line)
            converted = convert_row(row, gear_by_vessel)
            if converted["tonnage"] is not None:
                with_tonnage += 1
            if converted["fishingType"]:
                with_gear += 1
            f_out.write(json.dumps(converted, ensure_ascii=False) + "\n")
            total += 1

    print(f"[output] {OUT_PATH}")
    print(f"  총 {total}척, 톤수 확보 {with_tonnage}척 ({100 * with_tonnage / total:.1f}%), "
          f"gear 확보 {with_gear}척 ({100 * with_gear / total:.1f}%)")


if __name__ == "__main__":
    main()
