"""
담당: 김태윤

국내 선박제원정보 매칭 결과(data/match_vessel_spec.py 산출물)를 GFW
선박 목록에 병합해서, 최종적으로 다음 단계(score/)에 넘길 수 있는
선박 목록을 만든다.

정책(2026-08-14, 팀 확정 전까지의 잠정 기본값 — CLAUDE.md "매칭 신뢰도
임계값" 등 미확정 항목과 마찬가지로 임시값이다):
    - 확정 매칭(imo_exact/callsign_exact/name_fuzzy) +
      possibleMisclassification=True
      → confirmed_excluded (국내 등록부로 비어선 확인됨, 이 목록에서 제외)
    - 확정 매칭 + possibleMisclassification=False
      → confirmed_fishing (어선 확인됨, 국내 스펙 값으로 채움)
    - 나머지(미매칭 / 낮은 신뢰도 / 아직 처리 안 함)
      → unknown (판단 불가 — 제외하지 않고 보수적으로 유지)

왜 unknown을 제외하지 않는가: 확정 안 된 걸 지금 빼버리면, 그 판단
자체가 근거 없는 추측이 된다(rules_common.md 1번 "판단 없는 수집"
원칙과 같은 맥락). 확정된 것(confirmed_excluded)만 확실하게 빼고,
나머지는 다음 단계 담당자가 필요하면 populationStatus 필드로 골라
쓸 수 있게 그대로 남겨둔다.

입력:
    data/raw/vessel_spec_matches__*.jsonl.gz (가장 최근 실행분 하나,
        파일명에 타임스탬프가 박혀있어 코드에서 경로를 직접 지정함 —
        재실행 시 이 상수를 최신 파일로 바꿔야 한다)
    data/raw/gfw_vessels_kor_fishing__2026-08-13.jsonl.gz

출력:
    data/raw/gfw_vessels_enriched.jsonl.gz
        각 줄: GFW 선박 필드 + populationStatus + (매칭됐으면) 국내
        스펙으로 덮어쓴 tonnage/length/width, 국내 선종 원문은
        domesticVesselKind에 별도 필드로 추가(fishingType은 GFW
        원본 리스트 그대로 유지 — 아래 build_enriched_vessels 참고)
"""

import gzip
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MATCHES_PATH = PROJECT_ROOT / "data" / "raw" / "vessel_spec_matches__2026-08-13T15-27-59.567740+00-00.jsonl.gz"
GFW_VESSELS_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_vessels_kor_fishing__2026-08-13.jsonl.gz"
OUT_PATH = PROJECT_ROOT / "data" / "raw" / "gfw_vessels_enriched.jsonl.gz"

CONFIDENT_METHODS = {"imo_exact", "callsign_exact", "name_fuzzy"}


def build_population_status() -> dict:
    """vesselId -> {status, spec} 매핑을 매칭 결과 파일로부터 만든다."""
    status_by_id = {}
    with gzip.open(MATCHES_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            vid = r["vesselId"]
            if r["matchMethod"] in CONFIDENT_METHODS:
                if r.get("possibleMisclassification"):
                    status_by_id[vid] = {"status": "confirmed_excluded", "spec": r["matchedSpec"]}
                else:
                    status_by_id[vid] = {"status": "confirmed_fishing", "spec": r["matchedSpec"]}
            else:
                status_by_id[vid] = {"status": "unknown", "spec": None}
    return status_by_id


def build_enriched_vessels(status_by_id: dict) -> dict:
    """GFW 선박 레코드에 populationStatus를 붙이고, 매칭된 것은 국내
    스펙(tonnage/length/width/fishingType)으로 값을 덮어쓴다.
    confirmed_excluded는 결과에서 아예 뺀다.
    """
    enriched = {}
    excluded_count = 0
    no_id_count = 0
    with gzip.open(GFW_VESSELS_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            vid = v["vesselId"]
            if not vid:
                # id/registryInfo.id/selfReportedInfo.id가 다 없는 레코드 —
                # dict 키로 못 쓰므로(겹치면 서로 덮어씀) 세어서 결과에서 뺀다.
                no_id_count += 1
                continue
            info = status_by_id.get(vid, {"status": "unprocessed", "spec": None})

            if info["status"] == "confirmed_excluded":
                excluded_count += 1
                continue

            record = dict(v)
            record["populationStatus"] = info["status"]
            spec = info["spec"]
            if spec:
                # 국내 등록부 값이 있으면 GFW 값보다 우선한다 — 국내가 공식
                # 소스이기 때문. 다만 톤수는 두 소스가 다를 수 있다(MEDRA
                # 사례: GFW 235t vs 국내 743t, 콜사인/IMO/길이는 일치했음).
                # 값 자체의 신뢰도 문제는 여기서 해결하지 않고 그대로 국내
                # 값을 채운다 — 그 판단은 score 단계 몫이다.
                if spec.get("grossTonnage") is not None:
                    record["tonnage"] = spec["grossTonnage"]
                if spec.get("lengthM") is not None:
                    record["length"] = spec["lengthM"]
                if spec.get("widthM") is not None:
                    record["width"] = spec["widthM"]
                if spec.get("vesselKind"):
                    # fishingType(GFW geartype 리스트, 예: ["TRAWLERS"])과는
                    # 분류 체계 자체가 다른 국내 선종 문자열(예: "92[원양
                    # 어선]")이라 같은 필드에 덮어쓰지 않는다 — 덮어쓰면
                    # 매칭 여부에 따라 레코드마다 fishingType 타입이
                    # list/str로 갈려서 후속 소비자가 혼동하기 쉽다.
                    record["domesticVesselKind"] = spec["vesselKind"]
            enriched[vid] = record
    print(f"[enrich] 확정 제외(비어선): {excluded_count}건, ID 없어서 제외: {no_id_count}건")
    return enriched


def main():
    print("[1/2] 매칭 결과로 선박별 판정(status) 만들기...")
    status_by_id = build_population_status()

    counts = {}
    for info in status_by_id.values():
        counts[info["status"]] = counts.get(info["status"], 0) + 1
    print("  판정 분포:", counts)

    print("\n[2/2] GFW 선박 데이터에 국내 spec 병합 후 저장...")
    enriched = build_enriched_vessels(status_by_id)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_PATH, "wt", encoding="utf-8") as out:
        for record in enriched.values():
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  저장 완료: {OUT_PATH} (총 {len(enriched)}척)")


if __name__ == "__main__":
    main()
