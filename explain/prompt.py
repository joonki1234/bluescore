"""
담당: 최지희

프롬프트 조립.

핵심은 **계산 결과를 전부 주입하고 문장 생성만 맡기는 것**이다. 기획서 (8-3)의
"숫자를 창작하지 않도록 계산 결과를 프롬프트에 주입하고 문장 생성만 맡긴다"를
그대로 구현한 것이며, `render.py`의 숫자 검증이 이 전제를 사후에 강제한다.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from explain import facts
from explain.contract import ExplainInput

SYSTEM_PROMPT = """\
당신은 어선의 지속가능성 점수(BlueScore)를 어업인에게 설명하는 역할입니다.
읽는 사람은 배를 모는 어업인이고, 통계나 금융 용어에 익숙하지 않습니다.

지켜야 할 것
- 주어진 계산 결과에 있는 숫자만 씁니다. 어떤 수치도 새로 만들지 마세요.
  비율을 다시 계산하거나 어림잡아 반올림하지도 마세요.
- 전문용어를 쓰지 않습니다. '잔차', '백분위', 'SHAP', '가중치' 같은 말 대신
  '기대치와의 차이', '비슷한 배들 사이에서의 순위'처럼 풀어 씁니다.
- 아래 '참고 사실'에 없는 법령·제도·규제 내용은 언급하지 않습니다.
  금어기 일정이나 법 시행일처럼 확인되지 않은 것은 아예 말하지 마세요.
- 점수는 확정된 평가가 아니라 추정치이자 제안입니다. 단정하지 마세요.
- 감시하거나 나무라는 말투를 쓰지 않습니다. 잘한 점을 먼저 말하고,
  개선할 점은 할 수 있는 행동으로 제시합니다.

자원 압력(A축)에 대해 반드시 지킬 것
- 자원 압력은 '같은 자리를 얼마나 짧은 주기로 다시 긁는가'를 잽니다.
  간격이 길수록 좋고, 짧을수록 나쁩니다.
- **같은 어장에 머무르라거나 같은 자리를 반복해서 조업하라고 절대 권하지 마세요.**
  그것은 자원 압력을 낮추는 행동이 아니라 높이는 행동입니다.
- '어장 이동 거리'가 점수를 깎았더라도 해법은 "덜 움직여라"가 아닙니다.
  같은 어장을 다시 찾기까지의 간격을 두는 방향으로 제안하세요.

요약(summary)은 2~3문장입니다.
개선 제안(recommendations)은 2~3개이고, 각각 어업인이 내일 실제로 할 수 있는
구체적인 행동이어야 합니다. '효율을 높이세요' 같은 막연한 말은 쓰지 마세요.
"""


def build_facts_block() -> str:
    """확정 사실 + 언급 금지 주제."""
    forbidden = ", ".join(facts.pending_topics())
    return (
        "참고 사실 (이 안에 있는 내용만 근거로 삼으세요)\n"
        f"{facts.as_prompt_block()}\n\n"
        f"언급 금지 주제 (출처 확인 전이라 사실 여부를 보장할 수 없음): {forbidden}"
    )


def build_data_block(data: ExplainInput) -> str:
    """
    계산 결과를 JSON으로 주입한다.

    사람이 읽는 문장이 아니라 JSON으로 넣는 이유는, 모델이 값을 그대로
    옮겨 적기 쉽고 어떤 숫자가 주어졌는지 경계가 분명해지기 때문이다.
    """
    payload: Dict[str, Any] = {
        "선박": data.vessel_label,
        "유사선박군": data.fleet_label,
        "BlueScore": data.blue_score,
        "A축_자원압력_점수": data.axis_a_score,
        "B축_운항효율_점수": data.axis_b_score,
        "유사선박군_척수": data.peer_count,
        "유사선박군_내_상위퍼센트": data.top_percent,
        "기대대비_연료_퍼센트": data.fuel_delta_percent,
        "요인별_기여도": [
            {
                "요인": f.label,
                "기여도": f.value,
                "축": "자원 압력" if f.axis == "a" else "운항 효율",
            }
            for f in data.shap_factors
        ],
    }
    return (
        "계산 결과 (여기 있는 숫자만 쓸 수 있습니다)\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def build_user_prompt(data: ExplainInput) -> str:
    positives = ", ".join(f.label for f in data.top_positive()) or "없음"
    negatives = ", ".join(f.label for f in data.top_negative()) or "없음"

    return (
        f"{build_facts_block()}\n\n"
        f"{build_data_block(data)}\n\n"
        f"점수를 올린 주요 요인: {positives}\n"
        f"점수를 깎은 주요 요인: {negatives}\n\n"
        "위 계산 결과를 바탕으로 요약과 개선 제안을 작성하세요. "
        "개선 제안은 점수를 깎은 요인부터 다루되, 깎은 요인이 없으면 "
        "지금의 좋은 패턴을 유지하라는 쪽으로 씁니다."
    )
