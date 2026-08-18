"""

B축 실산출을 API 계층에서 쓸 수 있는 형태(선박별 residual_raw)로 준비한다.

`score/real_axis_b_input.py`(`build_axis_b_rows`)가 만드는 이벤트 단위 입력을
`axis_b_baseline.py`로 학습·추론해 선박별 B축 raw(잔차)까지 낸다. 이 결과를
A축과 같은 유사 선박군(`peer_grouping.build_peer_groups`)으로 백분위 변환하는
건 호출부(`services/real_scoring.py`)가 한다 — 그룹핑은 A축 쪽에서 이미 한
번 계산되므로 여기서 중복하지 않는다.

⚠ 이 결과를 쓸 때 같이 알아야 할 한계(score/TODO.md 참고):
    - 해양기상 단위(풍속 m/s)는 공식 확인이 아니라 정황 추정이다.
    - 유속(currentSpeedMs) 단위는 추정 근거조차 없다.
    - gearType은 TAC 매칭된 선박만 채워지고 나머지는 None이다.
    - 톤수 매칭 커버리지가 23.2%뿐이라 대부분 선박은 애초에 계산 자체가 스킵된다.
"""

from functools import lru_cache
from typing import Dict

from score.axis_b_baseline import VesselAxisBResult, compute_axis_b_efficiency, fit_baseline_model
from score.real_axis_b_input import build_axis_b_rows


@lru_cache(maxsize=1)
def compute_axis_b_results() -> Dict[str, VesselAxisBResult]:
    """B축 이벤트 입력을 로드·학습·추론까지 한 번에 하고 프로세스 내에 캐싱한다."""
    rows = build_axis_b_rows()
    model, _ = fit_baseline_model(rows)
    return compute_axis_b_efficiency(rows, model)
