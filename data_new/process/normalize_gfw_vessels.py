"""GFW 선박 상세 정규화 — registryInfo/selfReportedInfo를 필드별로 뽑아
score/ 계약 + 조인키 설계에 쓸 형태로 정리한다.

**출처를 섞지 않는다** — registryInfo(공식 등록부 매칭, 신뢰도 높음)와
selfReportedInfo(AIS 자기신고, 신뢰도 낮음 — POLARIS PRINCE 사례,
PROCESS_LOG.md 9번)를 하나의 필드로 합쳐버리면 어느 쪽에서 온 값인지
잃어버려서, 매칭 단계(조인키 설계 2~3단계)가 신뢰도를 구분해서 쓸 수 없게
된다. 그래서 `registry*` / `selfReported*` 접두어로 따로 남긴다.

가공 단계라 raw/는 읽기만 한다. processed/에 새로 쓰며, 원본에서 결정론적
으로 재생성 가능해 스냅샷 원칙(재조회 덮어쓰기 금지) 적용 대상이 아니다.

vesselId는 응답 본문이 아니라 **파일명**에서 뽑는다 — 우리가 실제로
요청한 ID 그대로라 가장 신뢰도 높음(combinedSourcesInfo가 비어있는
경우에도 항상 있음, 방금 실측으로 확인됨).

사용법:
    python normalize_gfw_vessels.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "vessels"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "gfw_vessels_normalized.jsonl"


def normalize_vessel(vessel_id: str, raw: dict) -> dict:
    registry = (raw.get("registryInfo") or [{}])[0] if raw.get("registryInfo") else {}
    self_reported = (raw.get("selfReportedInfo") or [{}])[0] if raw.get("selfReportedInfo") else {}
    combined = (raw.get("combinedSourcesInfo") or [{}])[0] if raw.get("combinedSourcesInfo") else {}

    return {
        "vesselId": vessel_id,
        "hasRegistryMatch": bool(raw.get("registryInfo")),
        "flag": registry.get("flag") or self_reported.get("flag"),
        # registryInfo(공식 등록부) — 있으면 신뢰도 높음
        "registryName": registry.get("shipname"),
        "registryCallsign": registry.get("callsign"),
        "registryImo": registry.get("imo"),
        "registryTonnageGt": registry.get("tonnageGt"),
        "registryLengthM": registry.get("lengthM"),
        "registryGearTypes": registry.get("geartypes") or [],
        "registrySourceCode": registry.get("sourceCode") or [],
        # selfReportedInfo(AIS 자기신고) — 신뢰도 낮음, 교차확인 없이 단독 신뢰 금지
        "selfReportedName": self_reported.get("shipname"),
        "selfReportedCallsign": self_reported.get("callsign"),
        "selfReportedImo": self_reported.get("imo"),
        "selfReportedSsvid": self_reported.get("ssvid"),
        # combinedSourcesInfo(등록부+AIS 결합 추정) — gearType/shipType 참고용
        "combinedShipTypes": [s.get("name") for s in combined.get("shiptypes", [])],
        "combinedGearTypes": [g.get("name") for g in combined.get("geartypes", [])],
    }


def run() -> None:
    files = sorted(glob.glob(str(RAW_DIR / "vessel_*__*Z.json")))
    if not files:
        raise SystemExit(f"원본 선박 파일이 없습니다: {RAW_DIR}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    n_registry_match = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for f in files:
            vessel_id = Path(f).name.split("__")[0][len("vessel_") :]
            raw = json.loads(Path(f).read_text(encoding="utf-8"))
            normalized = normalize_vessel(vessel_id, raw)
            if normalized["hasRegistryMatch"]:
                n_registry_match += 1
            out.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            n += 1

    print(f"선박 {n}척 정규화 완료 (registryInfo 매칭 {n_registry_match}척, {n_registry_match / n * 100:.1f}%)")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
