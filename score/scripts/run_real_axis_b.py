"""
담당: 김준기, 오동규

실제 data_new/ 산출물로 B축을 선박 단위까지 산출해보는 검증 스크립트.

배경: `score/real_axis_b_input.py`가 `data_new/processed/`의
`events_with_weather.jsonl.gz` + `final_vessel_matches.jsonl`을
`score/axis_b_baseline.py`가 요구하는 형태로 변환하는데, 이걸로 실제로
`fit_baseline_model()` -> `compute_axis_b_efficiency()`까지 에러 없이
도는지 증명한다(`score/scripts/run_real_axis_a.py`가 A축에서 한 것과 같은
목적). 화면 연결은 범위 밖 — 여기서는 "된다"만 증명한다.

실행:
    python -m score.scripts.run_real_axis_b
"""

import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from score.axis_b_baseline import compute_axis_b_efficiency, fit_baseline_model
from score.real_axis_b_input import build_axis_b_rows


def main() -> None:
    print("[1/3] B축 입력 행 생성 (data_new/ 산출물 조인)...")
    rows = build_axis_b_rows()
    print(f"      {len(rows):,}행")

    print("[2/3] LightGBM 기준선 학습...")
    model, skipped_from_fit = fit_baseline_model(rows)
    print(f"      학습 완료 (학습 단계 자체 스킵 {len(skipped_from_fit):,}건)")

    print("[3/3] 선박별 B축 raw 산출...")
    results = compute_axis_b_efficiency(rows, model)
    print(f"      {len(results):,}척 계산됨")

    used = [r for r in results.values() if r.used_row_count > 0]
    print(f"\n실제 산출된 선박: {len(used):,}척 / 전체 {len(results):,}척")

    skip_reasons: Counter = Counter()
    for result in results.values():
        for skipped in result.skipped_rows:
            skip_reasons[skipped.reason.split(":", 1)[0]] += 1
    print("\n스킵 사유 분포 (이벤트 단위):")
    for reason, count in skip_reasons.most_common():
        print(f"  {reason}: {count:,}건")

    if not used:
        print("\n실제 산출된 선박이 없습니다.")
        return

    example = max(used, key=lambda r: r.used_row_count)
    print(f"\n=== 예시 선박 {example.vessel_id} (사용 행 수 최다) ===")
    print(f"사용 행 수     : {example.used_row_count}")
    print(f"추정 연료(kg)  : {example.estimated_fuel_kg:.2f}")
    print(f"기대 연료(kg)  : {example.expected_fuel_kg:.2f}")
    print(f"잔차(raw)      : {example.residual_raw:.2f}")


if __name__ == "__main__":
    main()
