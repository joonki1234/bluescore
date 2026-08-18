"""

실제 data_new/ 산출물로 A축 요인 기여도(score/shap_factors.py) 계산을
검증하는 스크립트. 여기서는 raw 단위 기여도가 실제로 계산되고,
axis_a_pressure_raw와 정확히 합이 맞는지만 증명한다.

B축은 다루지 않는다 — LightGBM 기준선에 shap.TreeExplainer를 붙이면
"기대 연료소비량이 왜 이렇게 예측됐는지"(조건 설명)만 알려줄 뿐 "왜 이
선박의 B축 효율이 좋다/나쁘다"는 설명하지 못한다(잔차를 만드는 진짜
원인인 속도가 순환성 방지를 위해 모델 입력에서 빠져있어서 SHAP이 찾아낼
수 없음). 자세한 내용은 `score/shap_factors.py` 모듈 docstring 참고.

실행:
    python -m score.scripts.run_shap_factors
"""

import gzip
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from score.axis_a_pressure import compute_axis_a_pressure
from score.shap_factors import axis_a_factor_contributions

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"


def _load_jsonl_gz(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main() -> None:
    print("=== A축 요인 기여도 ===")
    events = _load_jsonl_gz(EVENTS_PATH)
    axis_a_results = compute_axis_a_pressure(events)

    candidate_id = next(
        (vid for vid, r in axis_a_results.items() if r.used_event_count > 0), None
    )
    if candidate_id is None:
        print("조건에 맞는 선박을 찾지 못했습니다.")
        return

    result = axis_a_results[candidate_id]
    factors = axis_a_factor_contributions(result)

    print(f"선박 {candidate_id} (이벤트 사용 {result.used_event_count}건)")
    for factor in factors:
        print(f"  {factor['label']:<16} {factor['raw_contribution']:+.4f}")
    total = sum(f["raw_contribution"] for f in factors)
    print(f"  {'합계':<16} {total:+.4f}  (axis_a_pressure_raw = {result.axis_a_pressure_raw:+.4f})")


if __name__ == "__main__":
    main()
