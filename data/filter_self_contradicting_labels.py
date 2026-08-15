"""
담당: 김태윤

GFW 모집단 필터를 정교화한다. 지금까지는 possibleMisclassification
(MOF 교차검증, 커버리지 제한적) 하나에만 의존했는데, GFW 응답 안에
이미 있는 자기모순 신호를 하나 더 쓴다 — 비용이 전혀 안 든다(새 API
호출도, 다른 소스도 필요 없음. 이미 갖고 있는 필드만 재활용).

발견 배경: 톤수 이상치를 파다가, shiptypes.name='FISHING'으로 걸러진
배들 중 일부가 자기 자신의 geartypes 필드에 CARGO/PASSENGER/CARRIER를
직접 갖고 있는 것을 발견함(예: "WISE HONEST" — 실제로는 알려진 북한
화물선, fishingType=['CARGO']). GFW가 두 신호(shiptypes 추정 vs
geartypes 자기신고)를 내부적으로 일치시키지 않는다는 뜻 — 이 불일치
자체가 무료 신뢰도 신호다.

이건 possibleMisclassification(MOF 매칭 필요, 커버리지 제한적)과 달리
GFW 데이터 자체만으로 전체 모집단에 즉시 적용 가능하다는 게 핵심 장점.

출력: data/raw/gfw_self_contradicting_vessel_ids__<타임스탬프>.json
    삭제가 아니라 플래그용 vesselId 목록 — 실제로 걸러 쓸지는 소비자가
    판단한다(possibleMisclassification과 동일 패턴).
"""

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.snapshot_utils import find_latest  # noqa: E402

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# geartypes 필드에 이 값이 하나라도 있으면 "어업선박"이라는 앵커 분류와
# 자기모순 — GFW 자기신고 스스로가 비어선이라고 말하고 있는 것.
SELF_CONTRADICTING_LABELS = {"CARGO", "PASSENGER", "CARRIER"}

# 뭉뚱그려진 라벨(FISHING/OTHER/NA/INCONCLUSIVE/GEAR/FIXED_GEAR)은 모순은
# 아니지만 근거가 약함 — 별도 등급으로만 표시하고 제외하지는 않는다.
AMBIGUOUS_LABELS = {"FISHING", "OTHER", "NA", "INCONCLUSIVE", "GEAR", "FIXED_GEAR", "TROLLERS",
                     "OTHER_PURSE_SEINES", "OTHER_SEINES"}


def classify(fishing_types: list) -> str:
    types = set(fishing_types or [])
    if types & SELF_CONTRADICTING_LABELS:
        return "self_contradicting"  # 강한 신호 — 제외 권장
    if types and types <= AMBIGUOUS_LABELS:
        return "ambiguous"  # 약한 신호 — 주의만
    if types:
        return "specific_fishing_gear"  # 구체적인 어업 장비 라벨 — 신뢰도 높음
    return "no_label"


def main():
    enriched_path = find_latest(DATA_RAW_DIR, "gfw_vessels_enriched.jsonl.gz")

    counts = {"self_contradicting": 0, "ambiguous": 0, "specific_fishing_gear": 0, "no_label": 0}
    self_contradicting_examples = []
    flagged_ids = []

    with gzip.open(enriched_path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]

    for v in rows:
        label = classify(v.get("fishingType"))
        counts[label] += 1
        if label == "self_contradicting":
            flagged_ids.append(v["vesselId"])
            if len(self_contradicting_examples) < 10:
                self_contradicting_examples.append((v.get("name"), v.get("tonnage"), v.get("fishingType")))

    print("=== GFW 자기모순 라벨 필터 결과 ===\n")
    total = len(rows)
    for label, n in counts.items():
        print(f"  {label}: {n:,}척 ({100*n/total:.2f}%)")

    print(f"\n자기모순(CARGO/PASSENGER/CARRIER 자기신고) 예시:")
    for name, tonnage, fts in self_contradicting_examples:
        print(f"  {name!r}  톤수={tonnage}  fishingType={fts}")

    ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
    out_path = DATA_RAW_DIR / f"gfw_self_contradicting_vessel_ids__{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"flaggedVesselIds": flagged_ids, "count": len(flagged_ids)}, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {out_path}")
    print(f"\n제안: 이 {len(flagged_ids)}척은 모집단 필터 단계에 'GFW 자기모순 제외'로 "
          f"추가하면 좋음 — MOF 매칭 없이도 전체 모집단에 적용 가능.")


if __name__ == "__main__":
    main()
