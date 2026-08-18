"""
담당: 오동규, 김준기 (최지희 확인 필요)

실산출(sourceType=real) 미리보기 화면.

배경: A/B축 실산출 파이프라인(score/real_axis_b_scoring.py 등)은 API까지
연결됐지만, Streamlit 화면은 sourceType을 "demo"로 고정 호출해서 실산출이
화면 어디서도 보이지 않았다. 데모 화면(fisher.py/bank.py)을 그대로 실산출에
재사용하지 않은 이유: 그 화면들은 시뮬레이터·설명(explain)·이의제기까지
쓰는데, services/scoring.py._build_real_score()는 점수 산출만 지원한다
(데모 fixture 전용 기능들). 그래서 이 화면은 "점수가 실제로 계산됐다"를
보여주는 최소 기능만 담당하는 별도 페이지로 뺐다.

커버리지가 낮다(A축 69.2%, BlueScore까지 나오는 건 5.4%뿐)는 것과, 해양기상
단위 등 미검증 가정이 있다는 걸 화면에 항상 같이 보여준다 — "모르면 모른다"
원칙.
"""

from __future__ import annotations

import streamlit as st

from ui import adapter, components, theme

# services/scoring.py의 AXIS_A_WEIGHT/AXIS_B_WEIGHT와 동일 — 실산출 결과
# 계산식을 화면에 보여줄 때 쓴다. 그쪽 값이 바뀌면 여기도 같이 바꿔야 한다.
_AXIS_A_WEIGHT = 0.65
_AXIS_B_WEIGHT = 0.35


def _discount_text(band: dict) -> str:
    if band["discountBp"] <= 0:
        return f"{band['grade']} · 우대 없음"
    return f"{band['grade']} · -{band['discountBp']}bp"


def render() -> None:
    components.page_title(
        "실산출 미리보기",
        badge_html='<span class="bs-live-badge"><span class="dot"></span>LIVE DATA</span>',
    )
    st.caption(
        "가명 시연 데이터가 아니라 실제 GFW 조업 이벤트(2026-04~08월)로 계산한 결과입니다."
    )

    list_placeholder = st.empty()
    with list_placeholder.container():
        components.skeleton_score_card(
            "실산출 선박 목록을 불러오는 중입니다 — 프로세스 첫 요청은 전체 5,323척의 "
            "산출 상태를 정렬하느라 최대 20여 초 걸릴 수 있습니다(이후엔 즉시 응답)…"
        )
    vessels = adapter.real_vessel_options()
    list_placeholder.empty()

    if not vessels:
        st.warning("실산출 스냅샷을 불러올 수 없습니다. API 서버가 떠 있는지 확인하세요.")
        return

    options = [v["vesselId"] for v in vessels]
    label_by_id = {
        v["vesselId"]: f"{v['name']} · {v['meta']} · {v['status']}" for v in vessels
    }

    vessel_id = st.selectbox(
        "선박 선택 (실데이터)",
        options=options,
        format_func=lambda vid: label_by_id.get(vid, vid),
        key="real_vessel_id",
    )

    score_placeholder = st.empty()
    with score_placeholder.container():
        components.skeleton_score_card("점수를 계산하는 중입니다(B축은 첫 요청에서 모델을 새로 학습합니다)…")
    score = adapter.get_real_score(vessel_id)
    score_placeholder.empty()

    if score["status"] != "success":
        st.warning(f"{score['status']} — {score.get('message') or ''}")

    peer = score.get("peerGroup") or {}
    components.real_vessel_meta_card(
        score["vessel"]["meta"],
        score.get("matchingReason"),
        peer.get("count", 0),
        score["axisA"].get("usedEventCount"),
        score["axisB"].get("usedEventCount"),
    )

    axis_a_score = score["axisA"].get("score")
    axis_b_score = score["axisB"].get("score")
    components.animated_stat_cards(
        [
            {
                "label": "BlueScore",
                "value": score["blueScore"] if score.get("blueScore") is not None else "—",
                "decimals": 1,
                "size": 26,
            },
            {
                "label": "A. 자원 압력",
                "value": axis_a_score if axis_a_score is not None else "—",
                "decimals": 1,
                "size": 26,
            },
            {
                "label": "B. 운항 효율",
                "value": axis_b_score if axis_b_score is not None else "—",
                "decimals": 1,
                "size": 26,
            },
        ],
        height=108,
    )

    # services/scoring.py의 AXIS_A_WEIGHT/AXIS_B_WEIGHT와 동일한 값을 여기 직접
    # 쓴다 — adapter.formula_text()는 데모 fixture 설정(data/mock/dashboard_mock.json의
    # axisWeights)에서 가중치를 읽어오는 함수라, 지금은 값이 우연히 같아도(둘 다
    # 0.65/0.35) 실산출 화면에 데모 설정을 끌어다 쓰는 건 개념적으로 맞지 않다.
    #
    # BlueScore가 없는 경우(현재 94.6%, B축 미산출)에도 섹션 자체를 숨기지 않고
    # 왜 계산이 안 됐는지 보여준다 — 조용히 사라지면 "원래 계산식이 없다"로
    # 오해할 수 있다("모르면 모른다" 원칙).
    blue_score = score.get("blueScore")
    if blue_score is not None and axis_a_score is not None and axis_b_score is not None:
        st.markdown(
            f'<div class="bs-card"><span class="bs-mono" style="font-size:14px; '
            f'color:{theme.INK_SOFT};">{_AXIS_A_WEIGHT:g} × {axis_a_score:g} + '
            f'{_AXIS_B_WEIGHT:g} × {axis_b_score:g} = {blue_score:g}</span>'
            f'<div class="bs-note" style="margin-top:8px;">축 간 비중(자원 압력 '
            f'{_AXIS_A_WEIGHT:g} · 운항 효율 {_AXIS_B_WEIGHT:g})은 검증 전 잠정치입니다.</div></div>',
            unsafe_allow_html=True,
        )
    else:
        missing_reason = score["axisB"].get("missingReason") or score["axisA"].get("missingReason")
        st.markdown(
            f'<div class="bs-card"><span class="bs-mono" style="font-size:14px; '
            f'color:{theme.INK_SOFT};">{_AXIS_A_WEIGHT:g} × A + {_AXIS_B_WEIGHT:g} × B = BlueScore</span>'
            f'<div class="bs-note" style="margin-top:8px;">B축이 산출되지 않아 BlueScore는 '
            f'계산하지 않습니다{f" — {missing_reason}" if missing_reason else ""}.</div></div>',
            unsafe_allow_html=True,
        )

    if score.get("rateBand"):
        st.info(f"제안 금리 등급 · {_discount_text(score['rateBand'])}")

    shap_factors = score.get("shapFactors") or []
    if shap_factors:
        st.markdown("###### A. 자원 압력 — 요인 기여도")
        components.real_shap_factor_bars(shap_factors)

    estimated_fuel = score["axisB"].get("estimatedFuelKg")
    expected_fuel = score["axisB"].get("expectedFuelKg")
    if estimated_fuel is not None and expected_fuel is not None:
        st.markdown("###### B. 운항 효율 — 산출 근거")
        components.animated_transition_card(
            "유사 조건 기준선 예측 → 실측 기반 추정 연료",
            expected_fuel,
            estimated_fuel,
            unit="kg",
            decimals=1,
            color=theme.direction_color(expected_fuel - estimated_fuel),
            note_html=(
                "같은 톤수·속도·조업시간대 다른 배들의 평균(기준선)보다 실제로 "
                "덜 태웠으면 초록, 더 태웠으면 빨강입니다. B축 점수는 이 차이를 "
                "유사 선박군 안에서 백분위로 바꾼 값입니다."
            ),
        )
