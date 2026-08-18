"""실제 데이터로 B축을 선박 1척까지 산출해보는 검증 스크립트 (run_real_axis_a.py와 짝).

배경: data_new/process/build_axis_b_input.py가 처음으로 events_with_weather.jsonl +
final_vessel_matches.jsonl을 score/axis_b_baseline.py 계약 형태로 합쳤다 —
그 산출물(data_new/processed/axis_b_input.jsonl)이 실제로 학습·추론까지
되는지 "된다"만 증명한다.

실행:
    python -m score.scripts.run_real_axis_b
"""

import json
import time
from pathlib import Path

from score.axis_b_baseline import compute_axis_b_efficiency, fit_baseline_model

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data_new" / "processed" / "axis_b_input.jsonl"


def _load_jsonl(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main() -> None:
    print(f"[1/3] 입력 로드: {INPUT_PATH.name}")
    t0 = time.time()
    rows = _load_jsonl(INPUT_PATH)
    print(f"      {len(rows):,}행, {time.time() - t0:.1f}초")

    print("[2/3] 기준선 모델 학습 (fit_baseline_model)")
    t0 = time.time()
    model, skipped = fit_baseline_model(rows)
    print(f"      학습 {time.time() - t0:.1f}초, 스킵된 행 {len(skipped):,}건")

    print("[3/3] 선박별 B축 raw 값 산출 (compute_axis_b_efficiency)")
    t0 = time.time()
    results = compute_axis_b_efficiency(rows, model)
    print(f"      {len(results):,}척 계산됨, {time.time() - t0:.1f}초")

    success = [v for v in results.values() if v.used_row_count > 0]
    print(f"\n유효 이벤트 1건 이상인 선박: {len(success):,}척 / 전체 {len(results):,}척")

    candidate = success[0] if success else next(iter(results.values()))
    print(f"\n=== 선박 {candidate.vessel_id} ===")
    print(f"사용 이벤트 건수     : {candidate.used_row_count}")
    print(f"스킵된 이벤트 건수   : {len(candidate.skipped_rows)}")
    print(f"추정(물리식) 연료kg  : {candidate.estimated_fuel_kg:.2f}")
    print(f"기대(LightGBM) 연료kg: {candidate.expected_fuel_kg:.2f}")
    print(f"B축 잔차 raw         : {candidate.residual_raw:.2f}")


if __name__ == "__main__":
    main()
