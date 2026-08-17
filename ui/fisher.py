"""
담당: 최지희

어업인 화면.

심사역 화면과 같은 숫자를 쓰되, 표현을 다르게 한다.
    · 잔차·백분위 같은 용어를 노출하지 않는다
    · 금리는 '제안 구간'이 아니라 '예상 우대 구간'으로 부른다
    · 문서번호·해시·승인 버튼·모델 메타데이터는 두지 않는다
    · 개선 시뮬레이터가 이 화면의 주역이다

기획서 (8-2) 설계 원칙 — "점수만 주지 않는다. 모든 점수 옆에 '왜'와 '무엇을
바꾸면'이 함께 붙는다."
"""

from __future__ import annotations

import streamlit as st

from ui import adapter, components, theme

SIM_PRINCIPAL_WON = adapter.EXAMPLE_PRINCIPAL_WON
SIM_TERM_YEARS = adapter.EXAMPLE_TERM_YEARS


def _simulator(vessel: dict) -> None:
    base_revisit = vessel["revisitCount"]
    base_speed = vessel["averageSpeedKnots"]
    key = vessel["vesselId"]

    left, right = st.columns([1.25, 1], gap="medium")

    with left:
        st.markdown("##### 조업 방식을 바꿔 보세요")
        revisit = st.slider(
            "같은 어장 연속 조업 (회)",
            min_value=1,
            max_value=5,
            value=base_revisit,
            step=1,
            key=f"revisit_{key}",
            help="같은 자리를 연속으로 몇 번 조업하는지. 줄일수록 자원에 회복 여지가 생깁니다.",
        )
        speed = st.slider(
            "평균 항해 속도 (노트)",
            min_value=round(base_speed - 3.0, 1),
            max_value=round(base_speed + 2.0, 1),
            value=base_speed,
            step=0.1,
            key=f"speed_{key}",
            help="어장을 오갈 때의 평균 속도. 낮출수록 연료를 덜 씁니다.",
        )

        sim = adapter.simulate(vessel, revisit, speed)

        if sim.tradeoff_notes:
            st.markdown(
                '<div class="bs-card" style="border-left:4px solid ' + theme.AXIS_B + ';">'
                '<div class="bs-label">바꾸면 따라오는 대가</div>'
                + "".join(f'<div class="bs-note">· {n}</div>' for n in sim.tradeoff_notes)
                + '<div class="bs-note" style="margin-top:8px;">한쪽을 좋게 하면 다른 쪽이 '
                '조금 깎입니다. 두 슬라이더를 끝까지 미는 것이 항상 최선은 아닙니다.</div></div>',
                unsafe_allow_html=True,
            )

        components.rate_table(vessel["blueScore"], sim.score)

    with right:
        st.markdown("##### 예상 결과")
        components.animated_transition_card(
            "예상 BlueScore", vessel["blueScore"], sim.score,
            note_html=(
                f'{theme.top_percent_text(vessel["peerGroup"]["topPercent"])} → '
                f'<b>{theme.top_percent_text(sim.top_percent)}</b> · 점수 {theme.signed(sim.score_delta)}'
            ),
        )

        dataset = adapter.load_dataset()
        before_band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])
        after_band = theme.grade_band(sim.score, dataset["rateGrades"])
        changed = after_band["grade"] != before_band["grade"]

        components.animated_transition_card(
            "예상 우대 구간",
            theme.discount_text(before_band), theme.discount_text(after_band),
            color=theme.POSITIVE if changed else theme.INK,
            note_html="최종 여신 승인은 은행 심사역이 수행합니다. 위 구간은 규칙표가 매핑한 제안값입니다.",
        )

        gained_bp = after_band["discountBp"] - before_band["discountBp"]
        yearly, total = theme.interest_saving(gained_bp, SIM_PRINCIPAL_WON, SIM_TERM_YEARS)
        st.markdown(
            f'<div class="bs-note">{SIM_PRINCIPAL_WON // 100_000_000}억 원 · '
            f'{SIM_TERM_YEARS}년 만기 기준 예시</div>',
            unsafe_allow_html=True,
        )
        components.animated_stat_cards(
            [
                {"label": "연간 절감", "value": yearly // 10_000, "unit": "만원", "color": theme.POSITIVE},
                {"label": "만기까지", "value": total // 10_000, "unit": "만원", "color": theme.POSITIVE},
                {"label": "기대 대비 연료", "value": sim.fuel_delta_percent, "unit": "%",
                 "decimals": 1, "signed": True,
                 "color": theme.direction_color(-sim.fuel_delta_percent)},
            ]
        )

        components.peer_distribution(vessel, simulated_score=sim.score, height=200)

    st.markdown(
        '<div class="bs-note">시뮬레이션 결과는 예상치이며 확정된 조건이 아닙니다. '
        '축 간 반작용 계수는 검증 전 잠정값입니다.</div>',
        unsafe_allow_html=True,
    )


def render() -> None:
    theme.inject()
    vessel_id = st.session_state.get("vessel_id", adapter.vessel_options()[0])
    vessel = adapter.get_vessel(vessel_id)

    st.markdown(f"### {vessel['name']} · 내 조업 성적")

    if not adapter.is_scored(vessel):
        components.blocked_page(vessel)
        return

    components.score_bar(vessel, show_grade=False)

    tab_voyage, tab_report, tab_sim = st.tabs(
        ["1 · 조업 현황", "2 · 점수리포트", "3 · 개선 시뮬레이터"]
    )

    with tab_voyage:
        left, right = st.columns([1.5, 1], gap="medium")
        with left:
            components.voyage_map(vessel)
        with right:
            st.markdown("##### 최근 6개월 추이")
            components.trend_chart(vessel)
            st.markdown(
                f'<div class="bs-card"><div class="bs-label">이번 기간</div>'
                f'<div class="bs-note">출항 {vessel["sailCalls"]}회 · '
                f'조업일 {vessel["fishingDays"]}일</div></div>',
                unsafe_allow_html=True,
            )
        components.voyage_stats(vessel)

        st.markdown("##### 내 점수")
        left, right = st.columns([1.4, 1], gap="medium")
        with left:
            components.axis_breakdown(vessel)
        with right:
            st.markdown("##### 비슷한 배들 사이에서")
            components.peer_distribution(vessel)
            st.markdown(
                f'<div class="bs-card"><div class="bs-label">비교 대상</div>'
                f'<div class="bs-note">{vessel["fleetLabel"]}<br>'
                f'같은 톤수대·어업종·해역·계절의 {vessel["peerGroup"]["count"]}척과 '
                f'견줍니다. 절대 성적이 아니라 <b>비슷한 조건의 배들 사이에서의 위치</b>입니다.'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    with tab_report:
        left, right = st.columns([1.3, 1], gap="medium")
        with left:
            st.markdown("##### 어떤 것이 점수를 올리고 내렸나")
            components.shap_contributions(vessel)
            st.markdown(
                '<div class="bs-note">막대 길이가 그 요인이 점수에 준 영향입니다. '
                '부호가 +면 올린 것, −면 내린 것입니다. 위쪽 "1 · 조업 현황" 탭 지도의 '
                '조업 이벤트 색 진하기·재방문 표시도 같은 요인에서 나온 것입니다.</div>',
                unsafe_allow_html=True,
            )
            st.markdown("##### 유사 선박군과 비교한 실측값")
            components.peer_metric_comparison(vessel)
            components.detailed_report(vessel)
        with right:
            explanation = adapter.explanation(vessel)
            st.markdown("##### 요약")
            st.markdown(
                f'<div class="bs-card"><div style="font-size:14px; line-height:1.85;">'
                f'{explanation["summary"]}</div>'
                f'<div class="bs-note" style="margin-top:12px;">공개 데이터에 기반한 '
                f'추정입니다.</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown("##### 바꿀 수 있는 것")
            items = "".join(
                f'<div style="display:flex; gap:8px; padding:6px 0;">'
                f'<span style="color:{theme.axis_color(r["axis"])}; font-weight:800;">·</span>'
                f'<span style="font-size:13.5px;">{r["action"]}</span></div>'
                for r in explanation["recommendations"]
            )
            st.markdown(f'<div class="bs-card">{items}</div>', unsafe_allow_html=True)
            components.explanation_source(explanation)
            st.markdown(
                '<div class="bs-note">👉 위 개선 방향을 실제로 적용하면 점수와 금리가 '
                '어떻게 바뀌는지 <b>"3 · 개선 시뮬레이터"</b> 탭에서 미리 확인할 수 '
                '있습니다.</div>',
                unsafe_allow_html=True,
            )
            st.divider()
            components.ai_qa_widget(vessel)
            st.divider()
            components.objection_form(vessel)

    with tab_sim:
        components.improvement_recommendation_cards(vessel)
        st.markdown("##### 우대 요인")
        components.eligibility_card(
            vessel,
            "금어기 위반·해양보호구역 진입이 없고 관측 데이터가 충분할수록 우대 자격 "
            "요건을 갖춘 것입니다 — 지속가능한 조업을 실천했는지 보는 항목입니다.",
        )
        st.divider()
        _simulator(vessel)

    components.backend_footer()
