"""

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
from explain.provider import Prompts
from explain.recommendation_rules import allowed_rules

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
- 자원 압력은 '같은 자리를 얼마나 짧은 주기로 다시 조업하는가'를 잽니다.
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

    allowed = [
        {"factorCode": r.factor_code, "factorLabel": r.factor_label, "axis": r.axis, "action": r.action}
        for r in allowed_rules(data)
    ]

    return (
        f"{build_facts_block()}\n\n"
        f"{build_data_block(data)}\n\n"
        f"점수를 올린 주요 요인: {positives}\n"
        f"점수를 깎은 주요 요인: {negatives}\n\n"
        "허용된 개선 제안(문구와 axis를 그대로 복사해야 함)\n"
        + json.dumps(allowed, ensure_ascii=False, indent=2)
        + "\n\n위 계산 결과를 바탕으로 요약과 개선 제안을 작성하세요. "
        "recommendations에는 허용된 개선 제안만 넣고 action 문구와 axis를 바꾸지 마세요."
    )


def build_factor_metrics_block(data: ExplainInput) -> str:
    """요인별 실측값(선박 자신 값 vs 유사군 평균)을 JSON으로 주입한다."""
    if not data.factor_metrics:
        return ""
    payload = [
        {
            "요인": m.label,
            "축": "자원 압력" if m.axis == "a" else "운항 효율",
            "귀_선박_값": m.self_value,
            "유사군_평균값": m.peer_average,
            "단위": m.unit,
        }
        for m in data.factor_metrics
    ]
    return (
        "요인별 실측값 (여기 있는 숫자만 쓸 수 있습니다)\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


# ─── 질의응답 ─────────────────────────────────────────────────────────────────
QA_SYSTEM_PROMPT = """\
당신은 어선의 지속가능성 점수(BlueScore) 리포트에 대한 어업인의 질문에 답하는 \
역할입니다. 읽는 사람은 배를 모는 어업인이고, 통계나 금융 용어에 익숙하지 않습니다.

지켜야 할 것
- 주어진 계산 결과와 참고 사실에 있는 내용만 근거로 답합니다. 어떤 수치도 새로 \
만들지 마세요.
- 주어진 정보로 답할 수 없는 질문이면, 모른다고 솔직히 말하고 무엇을 확인하면 \
되는지 안내하세요. 추측으로 채우지 마세요.
- 전문용어를 쓰지 않습니다.
- 답변은 2~4문장입니다.
"""


def build_qa_prompt(data: ExplainInput, question: str) -> str:
    metrics_block = build_factor_metrics_block(data)
    return (
        f"{build_facts_block()}\n\n"
        f"{build_data_block(data)}\n\n"
        + (f"{metrics_block}\n\n" if metrics_block else "")
        + f"어업인의 질문: {question.strip()}\n\n"
        "위 정보만 근거로 답하세요."
    )


# ─── 이의제기 응답 ────────────────────────────────────────────────────────────
OBJECTION_SYSTEM_PROMPT = """\
당신은 여신 심사역이 검토하기 전에 이의제기에 대한 답변 초안을 작성하는 \
역할입니다. 이 초안은 그대로 발송되지 않고, 심사역이 검토·수정한 뒤 전달합니다.

지켜야 할 것
- 주어진 계산 결과와 참고 사실에 있는 내용만 근거로 씁니다. 새 수치를 만들지 \
마세요.
- 이의제기 내용이 타당한지 아닌지 당신이 단정하지 마세요. "심사역이 데이터 \
출처와 매칭 신뢰도를 확인 중"이라는 톤을 유지하세요.
- 방어적이거나 형식적인 말투를 피하고, 무엇을 근거로 점수가 산출됐는지 \
차분히 설명하세요.
- 답변은 3~5문장입니다.
"""


def build_objection_prompt(data: ExplainInput, reason: str, detail: str) -> str:
    metrics_block = build_factor_metrics_block(data)
    return (
        f"{build_facts_block()}\n\n"
        f"{build_data_block(data)}\n\n"
        + (f"{metrics_block}\n\n" if metrics_block else "")
        + f"이의제기 사유: {reason}\n"
        f"이의제기 상세 내용: {detail.strip() or '(추가 설명 없음)'}\n\n"
        "위 계산 결과를 근거로, 심사역이 검토 후 전달할 답변 초안을 작성하세요."
    )


# ─── 상세 리포트 ──────────────────────────────────────────────────────────────
REPORT_SYSTEM_PROMPT = """\
당신은 어선의 지속가능성 점수(BlueScore) 리포트에서 요인별 상세 설명을 작성하는 \
역할입니다. 읽는 사람은 배를 모는 어업인입니다.

지켜야 할 것
- '요인별 실측값'에 있는 귀 선박 값과 유사군 평균값만 근거로 씁니다. 새 수치를 \
만들지 마세요.
- 전문용어를 쓰지 않고, 각 요인이 무엇을 재는지 풀어서 설명합니다.
- 유사군 평균과 비교했을 때 좋은 방향인지 개선이 필요한 방향인지 함께 씁니다.
- 자원 압력(A축) 요인은 간격이 길거나 회피율이 높을수록 좋다는 방향을 지키고,
  "같은 자리를 더 반복하라"는 식의 해석은 하지 않습니다.
- **요인마다 항목을 하나씩** 만들고, `label`에는 주어진 요인 라벨을 그대로 \
씁니다. 주어지지 않은 요인을 만들지 마세요.
- 각 `sentence`는 1~2문장입니다. 문단으로 길게 잇지 마세요.
"""


def build_report_prompt(data: ExplainInput) -> str:
    metrics_block = build_factor_metrics_block(data)
    labels = "\n".join(f"- {m.label}" for m in data.factor_metrics)
    return (
        f"{build_facts_block()}\n\n"
        f"{build_data_block(data)}\n\n"
        + (f"{metrics_block}\n\n" if metrics_block else "")
        + f"설명해야 할 요인 목록(이 라벨을 그대로 쓰세요):\n{labels}\n\n"
        "위 요인별 실측값을 근거로, 요인마다 한 항목씩 설명을 작성하세요."
    )


# ─── 개선 팁 (개선 시뮬레이터 탭의 추천 카드) ──────────────────────────────────
TIP_SYSTEM_PROMPT = """\
당신은 어선의 지속가능성 점수(BlueScore)를 올리려는 어업인에게, 배 위에서 \
당장 무엇을 하면 되는지 알려주는 역할입니다.

지켜야 할 것
- **숫자를 쓰지 마세요.** 점수·속도·노트·퍼센트·금리 같은 수치는 화면이 이미 \
따로 보여줍니다. 당신은 '무엇을 하는 행동인지'만 씁니다.
- **'바꿀 것'에 적힌 항목만** 다룹니다. 거기 없는 행동(어장 이동·장비 교체 \
등)을 덧붙이면 안 됩니다. 항목이 하나면 그 하나를 두 문장으로 풀어 쓰세요.
  특히 "다른 어장으로 이동하라"는 조언은 연료를 더 태워 운항 효율 점수를 \
깎으므로 절대 쓰지 마세요.
- 자원 압력(A축)은 같은 자리를 다시 조업하는 주기가 길수록 좋습니다. \
"같은 어장에 더 머무르라"는 식의 반대 조언은 절대 하지 마세요.
- '같은 어장 연속 조업을 줄인다'는 **다른 곳으로 가라는 뜻이 아니라, 같은 \
자리를 다시 찾기까지 시간 간격을 두라는 뜻입니다.** 조업 순서를 돌리거나 \
하루 걸러 들르는 식으로 풀어 쓰고, 장소를 옮기라고 하지 마세요.
- 법률 위반 여부나 처벌을 언급하지 마세요.
- 어업인이 조타실에서 바로 읽고 이해할 수 있는 평이한 문장 2개로 씁니다.
"""


def build_improvement_tip_prompt(data: ExplainInput, plan_label: str, actions: list) -> str:
    """
    개선 조합 하나에 대한 실행 팁 프롬프트.

    `actions`는 계산이 이미 정한 변경 방향(예: "같은 어장 연속 조업을 줄인다")
    문자열 목록이다. 수치는 넘기지 않는다 — 숫자를 안 쓰게 하는 것이 이 팁의
    규칙이고, 넘기지 않으면 애초에 쓸 수가 없다.
    """
    action_lines = "\n".join(f"- {a}" for a in actions) or "- (변경 없음)"
    return (
        f"{build_facts_block()}\n\n"
        f"개선 조합 이름: {plan_label}\n"
        f"바꿀 것:\n{action_lines}\n\n"
        "위 변경을 실제 조업에서 어떻게 실천하는지, 숫자 없이 두 문장으로 알려주세요."
    )


# ─── 압축 프롬프트 (앨런 전용) ────────────────────────────────────────────────
#
# 앨런은 프롬프트를 URL 쿼리에 실어야 해서 약 7KB 한도가 걸린다. 위 원본
# 프롬프트는 시스템 프롬프트(약 5.5KB)와 참고 사실 블록(약 5.5KB)만으로 이미
# 한도를 넘는다. 그래서 앨런에게 보낼 때는 아래 압축본을 쓴다.
#
# 무엇을 버렸나
#   - 참고 사실 블록 전체. 대신 **확인되지 않은 제도·법령을 아예 말하지 말라**는
#     금지 규칙을 남겼다. 근거 목록을 못 주는 대신 입을 닫게 하는 쪽이다.
#   - 시스템 프롬프트의 설명 문장. 규칙 자체는 남기고 부연만 덜어냈다.
#
# 참고 사실이 실제로 필요한 흐름(금어기 같은 제도 질문이 오는 질의응답)은
# 압축본으로 답하면 안 된다. 그래서 QA는 앨런에 걸지 않는 것이 기본 배치다
# (`provider.py` 문서 참고).
#
# 아래 문구는 실측으로 정한 것이다 — 5개 흐름 × 10회 × 입력 2종, `render.py`
# 검증 50/50 통과. 문구를 손보면 폴백률이 달라질 수 있으니 재측정할 것.

# 선박 라벨의 톤수를 답변에 그대로 옮겨 적는 경향이 있어 넣은 규칙. 검증
# 자체는 `contract.ExplainInput.numeric_values()`가 라벨 숫자를 허용 집합에
# 넣어 막고 있고, 이 줄은 "이의제기 답변에 선박 제원을 되풀이하지 않는다"는
# 문장 품질 쪽 규칙이다.
NO_VESSEL_SPEC_RULE = (
    "- 선박 제원(톤수·업종·해역)을 문장에 다시 적지 마세요. 점수와 관련된 수치만 씁니다.\n"
)

_COMPACT_COMMON = (
    "- 아래 계산 결과에 있는 숫자만 쓰세요. 어떤 수치도 새로 만들지 마세요.\n"
    "- 전문용어(잔차·백분위·SHAP·가중치)를 쓰지 말고 풀어 쓰세요.\n"
    "- 금어기·포획금지체장 같은 법령·제도는 언급하지 마세요.\n"
    + NO_VESSEL_SPEC_RULE
)

COMPACT_SYSTEM_PROMPT = (
    "당신은 어선 지속가능성 점수(BlueScore)를 어업인에게 설명합니다.\n"
    + _COMPACT_COMMON
    + "- 자원 압력(A축)은 같은 자리를 다시 조업하는 간격이 길수록 좋습니다. "
    "'같은 어장에 머무르라'고 절대 권하지 마세요.\n"
    "- 단정하지 말고, 나무라는 말투를 쓰지 마세요. 잘한 점을 먼저 말하세요.\n"
    "\n요약(summary)은 2~3문장, 개선 제안(recommendations)은 2~3개입니다.\n"
)

COMPACT_QA_SYSTEM_PROMPT = (
    "당신은 어업인의 BlueScore 관련 질문에 답합니다.\n"
    + _COMPACT_COMMON
    + "- 주어진 정보로 답할 수 없으면 모른다고 말하고 무엇을 확인하면 되는지 "
    "안내하세요. 추측으로 채우지 마세요.\n"
    "- 답변은 2~4문장입니다.\n"
)

COMPACT_OBJECTION_SYSTEM_PROMPT = (
    "당신은 여신 심사역이 검토하기 전 이의제기 답변 초안을 씁니다.\n"
    + _COMPACT_COMMON
    + "- 이의제기가 타당한지 단정하지 말고 '심사역이 데이터 출처와 매칭 신뢰도를 "
    "확인 중'이라는 톤을 지키세요.\n"
    "- 방어적·형식적 말투를 피하고 3~5문장으로 씁니다.\n"
)

COMPACT_REPORT_SYSTEM_PROMPT = (
    "당신은 BlueScore 리포트의 요인별 상세 설명을 씁니다.\n"
    + _COMPACT_COMMON
    + "- 유사군 평균과 비교해 좋은 방향인지 개선이 필요한 방향인지 함께 씁니다.\n"
    "- 자원 압력(A축)은 간격이 길수록 좋습니다. '같은 자리를 더 반복하라'는 "
    "식으로 해석하지 마세요.\n"
    "- 요인마다 항목을 하나씩 만들고 label에는 주어진 라벨을 그대로 씁니다. "
    "주어지지 않은 요인을 만들지 마세요. 각 sentence는 1~2문장입니다.\n"
)

COMPACT_TIP_SYSTEM_PROMPT = (
    "당신은 어업인에게 배 위에서 당장 무엇을 하면 되는지 알려줍니다.\n"
    "- **숫자를 쓰지 마세요.** 점수·속도·노트·퍼센트·금리는 화면이 따로 보여줍니다.\n"
    # "방향만 쓰세요"로는 부족했다. 앨런이 "다른 어장을 찾아 이동하세요"를 계속
    # 덧붙였는데, 이건 '바꿀 것'에 없는 행동인 데다 연료를 더 태우는 조언이라
    # B축을 깎는다. 금지 예시를 박아 넣으니 3/3에서 사라졌다.
    "- **'바꿀 것'에 적힌 항목만** 다루세요. 거기 없는 행동(어장 이동·장비 교체 등)을\n"
    "  덧붙이면 안 됩니다. 항목이 하나면 그 하나를 두 문장으로 풀어 쓰세요.\n"
    "- 자원 압력은 같은 자리를 다시 조업하는 주기가 길수록 좋습니다. "
    "'같은 어장에 더 머무르라'는 반대 조언은 절대 하지 마세요.\n"
    "- '같은 어장 연속 조업을 줄인다'는 다른 곳으로 가라는 뜻이 아니라, "
    "같은 자리를 다시 찾기까지 시간 간격을 두라는 뜻입니다. 조업 순서를 "
    "돌리거나 하루 걸러 들르는 식으로 풀어 쓰고, 장소를 옮기라고 하지 마세요.\n"
    "- 법률 위반 여부나 처벌을 언급하지 마세요.\n"
    "- 조타실에서 바로 읽고 이해할 수 있는 평이한 문장 2개로 씁니다.\n"
)


def build_compact_user_prompt(data: ExplainInput) -> str:
    positives = ", ".join(f.label for f in data.top_positive()) or "없음"
    negatives = ", ".join(f.label for f in data.top_negative()) or "없음"
    allowed = [
        {"action": r.action, "axis": r.axis} for r in allowed_rules(data)
    ]
    return (
        f"{build_data_block(data)}\n\n"
        f"점수를 올린 주요 요인: {positives}\n"
        f"점수를 깎은 주요 요인: {negatives}\n\n"
        "허용된 개선 제안(action 문구와 axis를 그대로 복사):\n"
        + json.dumps(allowed, ensure_ascii=False)
    )


def build_compact_qa_prompt(data: ExplainInput, question: str) -> str:
    metrics_block = build_factor_metrics_block(data)
    return (
        f"{build_data_block(data)}\n\n"
        + (f"{metrics_block}\n\n" if metrics_block else "")
        + f"어업인의 질문: {question.strip()}"
    )


def build_compact_objection_prompt(data: ExplainInput, reason: str, detail: str) -> str:
    return (
        f"{build_data_block(data)}\n\n"
        f"이의제기 사유: {reason}\n"
        f"이의제기 상세 내용: {detail.strip() or '(추가 설명 없음)'}"
    )


def build_compact_report_prompt(data: ExplainInput) -> str:
    metrics_block = build_factor_metrics_block(data)
    labels = "\n".join(f"- {m.label}" for m in data.factor_metrics)
    return (
        (f"{metrics_block}\n\n" if metrics_block else "")
        + f"설명해야 할 요인 목록(이 라벨을 그대로 쓰세요):\n{labels}"
    )


def build_compact_improvement_tip_prompt(plan_label: str, actions: list) -> str:
    action_lines = "\n".join(f"- {a}" for a in actions) or "- (변경 없음)"
    return f"개선 조합 이름: {plan_label}\n바꿀 것:\n{action_lines}"


# ─── 프로바이더에 넘길 프롬프트 한 벌 ────────────────────────────────────────
#
# 원본과 압축본을 함께 묶어 넘긴다. 어느 쪽을 쓸지는 프로바이더가 고른다 —
# 이유는 `provider.Prompts` 문서 참고.


def explain_prompts(data: ExplainInput) -> Prompts:
    return Prompts(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(data),
        compact_system=COMPACT_SYSTEM_PROMPT,
        compact_user=build_compact_user_prompt(data),
    )


def qa_prompts(data: ExplainInput, question: str) -> Prompts:
    return Prompts(
        system=QA_SYSTEM_PROMPT,
        user=build_qa_prompt(data, question),
        compact_system=COMPACT_QA_SYSTEM_PROMPT,
        compact_user=build_compact_qa_prompt(data, question),
    )


def objection_prompts(data: ExplainInput, reason: str, detail: str) -> Prompts:
    return Prompts(
        system=OBJECTION_SYSTEM_PROMPT,
        user=build_objection_prompt(data, reason, detail),
        compact_system=COMPACT_OBJECTION_SYSTEM_PROMPT,
        compact_user=build_compact_objection_prompt(data, reason, detail),
    )


def report_prompts(data: ExplainInput) -> Prompts:
    return Prompts(
        system=REPORT_SYSTEM_PROMPT,
        user=build_report_prompt(data),
        compact_system=COMPACT_REPORT_SYSTEM_PROMPT,
        compact_user=build_compact_report_prompt(data),
    )


def improvement_tip_prompts(data: ExplainInput, plan_label: str, actions: list) -> Prompts:
    return Prompts(
        system=TIP_SYSTEM_PROMPT,
        user=build_improvement_tip_prompt(data, plan_label, actions),
        compact_system=COMPACT_TIP_SYSTEM_PROMPT,
        compact_user=build_compact_improvement_tip_prompt(plan_label, actions),
    )
