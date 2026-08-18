"""매칭 2단계 — 어선원부 ↔ GFW, 콜사인 + 이름 교차확인.

GFW `selfReportedInfo.callsign`은 신뢰도가 낮아(POLARIS PRINCE 사례로 확인)
콜사인 일치만으로 확정하지 않고 이름도 같이 남겨 사람이 검토할 근거로 쓴다
(자동 accept/reject 아님).

**접두어(prefix) 매칭은 폐기함** — "306" 같은 짧은 숫자 코드가 어선원부에서
서로 다른 배 6척과 동시에 prefix 매칭돼 동명이인 충돌을 그대로 재현하는 게
실측으로 확인됨. 정확일치(exact)만 신호로 쓴다.

사용법:
    python match_gfw_vessel_registry.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "processed"
REGISTRY_PATH = PROCESSED / "vessel_registry_normalized.jsonl"
GFW_VESSELS_PATH = PROCESSED / "gfw_vessels_normalized.jsonl"
OUT_PATH = PROCESSED / "gfw_vessel_registry_matched.jsonl"


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _callsign_signal(gfw_callsign: str, registry_callsign: str) -> str:
    # prefix 매칭은 폐기(모듈 docstring 참고) — 정확일치만 신호로 인정.
    return "exact" if gfw_callsign == registry_callsign else "none"


def run() -> None:
    registry_rows = [r for r in _load_jsonl(REGISTRY_PATH) if r["callsignRegistry"]]
    gfw_vessels = _load_jsonl(GFW_VESSELS_PATH)

    print(f"콜사인 있는 어선원부 {len(registry_rows)}건, GFW 선박 {len(gfw_vessels)}척 대상 비교")

    candidates = []
    for gfw in gfw_vessels:
        gfw_callsign = gfw["selfReportedCallsign"] or gfw["registryCallsign"]
        if not gfw_callsign:
            continue
        for reg in registry_rows:
            signal = _callsign_signal(gfw_callsign, reg["callsignRegistry"])
            if signal != "none":
                candidates.append(
                    {
                        "gfwVesselId": gfw["vesselId"],
                        "gfwCallsign": gfw_callsign,
                        "gfwName": gfw["selfReportedName"] or gfw["registryName"],
                        "registryVesselNo": reg["vesselNoRegistry"],
                        "registryCallsign": reg["callsignRegistry"],
                        "registryName": reg["nameRegistry"],
                        "callsignSignal": signal,
                    }
                )

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for c in candidates:
            out.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"콜사인 신호 있는 후보 {len(candidates)}건 -> {OUT_PATH}")
    for c in candidates:
        print(f"  {c['callsignSignal']}: GFW({c['gfwCallsign']!r} {c['gfwName']!r}) <-> 원부({c['registryCallsign']!r} {c['registryName']!r})")


if __name__ == "__main__":
    run()
