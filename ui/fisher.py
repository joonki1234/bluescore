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

def _simulator(vessel: dict) -> None:
    """
    개선 시뮬레이터.

    슬라이더·결과 카드·곡선·구간표를 iframe 하나(`components.live_simulator`)에
    통째로 담는다. 예전에는 `st.slider` 두 개를 놓고 매 칸마다 Python을 왕복했는데,
    실측상 왕복 1회가 300~570ms였고 그때마다 결과 카드 iframe이 다시 로드돼
    900ms짜리 카운트업이 처음부터 재생됐다 — 드래그하는 동안 숫자가 목표값에
    도달하지 못했다. 지금은 `adapter.simulate_surface()`가 전 구간을 미리 계산해
    넘기고 브라우저는 조회만 하므로 왕복이 없다. 계산 창구는 여전히 adapter 한 곳이다.
    """
    components.live_simulator(vessel)
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
        # 개선 추천 카드는 시뮬레이터 위젯 안(유사군 분포 아래)으로 옮겼다.
        # 슬라이더로 조합을 만지기 전에 "추천 조합"이 먼저 눈에 들어오면
        # 시뮬레이터가 답을 미리 알려주는 꼴이 되고, 분포를 본 직후에 놓여야
        # "내 위치 → 그래서 뭘 바꾸면 되는지" 순서로 읽힌다.
        st.markdown("##### 우대 요인")
        components.eligibility_card(
            vessel,
            "금어기 위반·해양보호구역 진입이 없고 관측 데이터가 충분할수록 우대 자격 "
            "요건을 갖춘 것입니다 — 지속가능한 조업을 실천했는지 보는 항목입니다.",
        )
        st.divider()
        _simulator(vessel)

    components.backend_footer()
