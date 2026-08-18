"""실산출(sourceType=real) 미리보기 화면.

시뮬레이터·설명·이의제기를 포함한 데모 화면과 분리해 실산출 결과만 보여준다.
낮은 커버리지와 미검증 가정도 함께 표시한다.
"""

from __future__ import annotations

from html import escape as escape_html

import streamlit as st

from ui import adapter, components, theme

# services/scoring.py의 AXIS_A_WEIGHT/AXIS_B_WEIGHT와 동일 — 실산출 결과
# 계산식을 화면에 보여줄 때 쓴다. 그쪽 값이 바뀌면 여기도 같이 바꿔야 한다.
_AXIS_A_WEIGHT = 0.65
_AXIS_B_WEIGHT = 0.35

_STATUS_LABELS = {
    "전체": None,
    "완전 산출": "success",
    "A축만 산출": "partial",
    "유사군 표본 부족": "insufficientSample",
    "유효 이벤트 없음": "matchingFailed",
}

_UNMATCHED_REASON_LABELS = {
    "held_multi": "복수 후보가 남았거나 거리 기준을 충족하지 못함",
    "no_korean": "정규화된 한국어 후보명이 없음",
    "unmatched": "TAC에서 정확히 대응하는 후보를 확인하지 못함",
}


def _discount_text(band: dict) -> str:
    if band["discountBp"] <= 0:
        return f"{band['grade']} · 우대 없음"
    return f"{band['grade']} · -{band['discountBp']}bp"


def _unmatched_reason_text(reason: str | None) -> str:
    return _UNMATCHED_REASON_LABELS.get(reason or "", "매칭 근거를 확인할 수 없음")


def _status_notice(score: dict) -> str | None:
    status = score.get("status")
    if status == "success":
        return None
    if status == "partial":
        return score["axisB"].get("missingReason") or score.get("message")
    if status == "insufficientSample":
        return (
            f"유효 이벤트의 원시값은 계산됐지만 유사 선박군이 "
            f"{score.get('peerGroup', {}).get('count', 0)}척이라 점수로 변환하지 않습니다."
        )
    return score.get("matchingReason") or "스냅샷에 유효한 조업 이벤트가 없습니다."


def _can_load_explanation(score: dict) -> bool:
    return score.get("status") == "success"


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
    filter_col, search_col = st.columns([1, 2])
    with filter_col:
        status_label = st.selectbox(
            "산출 상태",
            options=list(_STATUS_LABELS),
            key="real_status_filter",
        )
    with search_col:
        search = st.text_input(
            "선박 ID 또는 이름 검색",
            placeholder="전체 5,323척에서 검색",
            key="real_vessel_search",
        )

    page = adapter.real_vessel_page(
        status=_STATUS_LABELS[status_label],
        query=search,
        limit=100,
    )
    vessels = page["vessels"]
    list_placeholder.empty()

    if not vessels:
        st.warning("조건에 맞는 실산출 선박이 없습니다.")
        return

    status_counts = page.get("statusCounts") or {}
    st.caption(
        f"검색 결과 {page.get('total', len(vessels)):,}척 · 화면에는 최대 100척만 표시 · "
        f"완전 산출 {status_counts.get('success', 0):,} / "
        f"A축만 {status_counts.get('partial', 0):,} / "
        f"표본 부족 {status_counts.get('insufficientSample', 0):,} / "
        f"이벤트 없음 {status_counts.get('matchingFailed', 0):,}"
    )

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

    notice = _status_notice(score)
    if notice:
        st.warning(f"{score['status']} — {notice}")

    peer = score.get("peerGroup") or {}
    components.real_vessel_meta_card(
        score["vessel"]["meta"],
        score.get("matchingReason"),
        peer.get("count", 0),
        score["axisA"].get("usedEventCount"),
        score["axisB"].get("usedEventCount"),
        score.get("matchingMethod"),
    )

    evidence = score.get("matchingEvidence") or {}
    fishing_types = evidence.get("fishingTypes") or []
    st.markdown("###### 선박 메타데이터와 등록정보 매칭 근거")
    components.real_matching_evidence_card(
        evidence,
        ", ".join(fishing_types),
        _unmatched_reason_text(evidence.get("unmatchedReason")),
    )

    axis_a_score = score["axisA"].get("score")
    axis_b_score = score["axisB"].get("score")
    axis_a_value = axis_a_score
    axis_a_label = "A. 자원 압력"
    if score["status"] == "insufficientSample":
        axis_a_value = score["axisA"].get("rawValue")
        axis_a_label = "A. 자원 압력 원시값"

    components.animated_stat_cards(
        [
            {
                "label": "BlueScore",
                "value": score["blueScore"] if score.get("blueScore") is not None else "—",
                "decimals": 1,
                "size": 26,
            },
            {
                "label": axis_a_label,
                "value": axis_a_value if axis_a_value is not None else "—",
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
    st.markdown("###### BlueScore 계산")
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
        escaped_reason = escape_html(str(missing_reason)) if missing_reason else ""
        st.markdown(
            f'<div class="bs-card"><span class="bs-mono" style="font-size:14px; '
            f'color:{theme.INK_SOFT};">{_AXIS_A_WEIGHT:g} × A + {_AXIS_B_WEIGHT:g} × B = BlueScore</span>'
            f'<div class="bs-note" style="margin-top:8px;">B축이 산출되지 않아 BlueScore는 '
            f'계산하지 않습니다{f" — {escaped_reason}" if escaped_reason else ""}.</div></div>',
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

    st.markdown("###### 설명과 질의")
    if _can_load_explanation(score):
        st.caption("설명은 버튼을 눌렀을 때만 sourceType=real로 불러옵니다.")
        if st.button("실산출 설명 불러오기", key=f"real_explanation_{vessel_id}"):
            explanation = adapter.get_real_explanation(score)
            if explanation:
                st.write(explanation.get("summary") or "설명이 없습니다.")
                st.caption(
                    f"설명 출처: {explanation.get('explanationSource', 'unknown')}"
                )

        with st.form(key=f"real_question_{vessel_id}"):
            question = st.text_input("이 실산출 결과에 질문하기")
            submitted = st.form_submit_button("질문 보내기")
        if submitted and question.strip():
            answer = adapter.ask_real(score, question.strip())
            if answer:
                st.write(answer.get("text") or "답변이 없습니다.")
                st.caption(f"답변 출처: {answer.get('source', 'unknown')}")
    else:
        st.info("완전 산출 상태가 아니므로 설명·질의 API를 호출하지 않습니다.")

    st.caption(
        "실데이터 시뮬레이션은 모델·정책 파라미터 검증 전이므로 제공하지 않습니다."
    )
