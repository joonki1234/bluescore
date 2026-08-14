"""
담당: 최지희

금융기관(심사역) 화면.

어업인 화면과 **같은 숫자**를 쓰되 노출 범위가 다르다.
    · 전문용어를 그대로 쓴다 (잔차, 백분위, SHAP)
    · 자격 요건 판정, 데이터 출처·기준일자, 산출 이력을 전면에 둔다
    · 해시와 재현성 정보를 노출한다
    · 개선 시뮬레이터는 참고용으로 접어 둔다
    · '산출 근거 요약'은 explain/이 생성한 문장을 어업인 화면과 공유한다.
      LLM 생성인지 템플릿 폴백인지도 함께 표시한다 — 심사역에게는 이 구분 자체가
      심사 근거의 출처 정보다.

기획서 9번 — "AI는 점수와 근거만 산출한다. 금리 구간은 은행이 사전 승인한
규칙표가 매핑하고, 여신 최종 승인은 심사역이 한다. 자동화한 것은 '결정'이
아니라 '계산과 기록'이다."
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from ui import adapter, components, theme

MODEL_META = [
    ("기준선 모델", "LightGBM"),
    ("학습 표본", "1,860 항차"),
    ("설명 방식", "SHAP"),
]


def _header(vessel: dict, issued: str) -> None:
    doc_id = adapter.document_id(vessel, issued)
    st.markdown(
        f'<div style="display:flex; align-items:flex-start; gap:12px; margin-bottom:6px;">'
        f'<div><div style="font-size:20px; font-weight:700;">여신 심사 리포트</div>'
        f'<div class="bs-note">심사 보조자료 · {issued} 생성 · 차주 선박 {vessel["name"]}</div></div>'
        f'<div style="margin-left:auto;" class="bs-hash">{doc_id}</div></div>',
        unsafe_allow_html=True,
    )


def _decision_panel(vessel: dict) -> None:
    st.markdown("##### 심사 의견")
    st.text_area(
        "의견",
        key=f"opinion_{vessel['vesselId']}",
        placeholder="심사 의견을 입력하세요",
        height=120,
        label_visibility="collapsed",
    )
    col_a, col_b = st.columns(2)
    decided = st.session_state.get(f"decision_{vessel['vesselId']}")
    with col_a:
        if st.button("승인", key=f"approve_{vessel['vesselId']}", width="stretch"):
            st.session_state[f"decision_{vessel['vesselId']}"] = "approve"
            decided = "approve"
    with col_b:
        if st.button("보류", key=f"hold_{vessel['vesselId']}", width="stretch"):
            st.session_state[f"decision_{vessel['vesselId']}"] = "hold"
            decided = "hold"

    if decided == "approve":
        st.success("승인 처리되었습니다 (심사 보조자료 기준).")
    elif decided == "hold":
        st.info("보류 처리되었습니다. 추가 소명 자료를 요청할 수 있습니다.")

    st.markdown(
        '<div class="bs-note">본 리포트는 <b>심사 보조자료</b>입니다. 금리 구간은 사전 '
        '승인된 규칙표에 따른 제안이며, <b>최종 여신 승인은 심사역이 수행합니다.</b></div>',
        unsafe_allow_html=True,
    )


def render() -> None:
    theme.inject()
    vessel_id = st.session_state.get("vessel_id", adapter.vessel_options()[0])
    vessel = adapter.get_vessel(vessel_id)
    issued = date.today().isoformat()

    st.markdown(f"### {vessel['name']} · 여신 심사")

    if not adapter.is_scored(vessel):
        notice = adapter.blocked_notice(vessel)
        st.markdown(
            f'<div class="bs-blocked"><div class="t">{notice["title"]} — 산출 보류</div>'
            f'<div class="bs-note">{notice["body"]}<br><br><b>다음 조치</b> · {notice["next"]}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("##### 관측된 조업 활동")
        components.voyage_map(vessel, height=320)
        components.voyage_stats(vessel)
        components.provenance()
        components.backend_footer()
        return

    components.score_bar(vessel)

    tab_summary, tab_basis, tab_data, tab_sim = st.tabs(
        ["1 · 심사 개요", "2 · 산출 근거", "3 · 데이터·검증", "4 · 개선 여지 (참고)"]
    )

    with tab_summary:
        _header(vessel, issued)
        peer = vessel["peerGroup"]
        dataset = adapter.load_dataset()
        band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

        cols = st.columns(4)
        summary_stats = [
            ("BlueScore", f"{vessel['blueScore']}", ""),
            ("유사군 내", f"{peer['topPercent']}", "%"),
            ("비교 대상", f"{peer['count']}", "척"),
            ("제안 구간", theme.discount_text(band), ""),
        ]
        for col, (label, value, unit) in zip(cols, summary_stats):
            with col:
                st.markdown(
                    f'<div class="bs-card"><div class="bs-label">{label}</div>'
                    f'<div class="bs-value">{value}<span class="unit">{unit}</span></div></div>',
                    unsafe_allow_html=True,
                )

        left, right = st.columns([1.3, 1], gap="medium")
        with left:
            components.axis_breakdown(vessel)
            components.rate_table(vessel["blueScore"])
        with right:
            st.markdown("##### 자격 요건")
            components.eligibility_card(
                vessel,
                "준법 항목(금어기·보호구역)은 점수 축에서 제외하고 <b>우대 자격 요건</b>으로만 "
                "둡니다. 준법을 점수화하면 변별력이 없을뿐더러 서비스가 감시 도구로 작동하기 "
                "때문입니다.",
            )
            st.markdown("##### 유사 선박군 내 위치")
            components.peer_distribution(vessel, height=210)
            st.markdown("##### 산출 이력")
            history = "".join(
                f'<div style="display:flex; gap:10px; font-size:12.5px; '
                f'color:{theme.INK_SOFT}; padding:5px 0;">'
                f'<b class="bs-mono" style="color:{theme.INK};">{m}</b> · BlueScore {s}</div>'
                for m, s in zip(["3월", "4월", "5월", "6월", "7월", "8월"], vessel["trend"])
            )
            st.markdown(f'<div class="bs-card">{history}</div>', unsafe_allow_html=True)

    with tab_basis:
        left, right = st.columns([1.3, 1], gap="medium")
        with left:
            st.markdown("##### 요인별 기여도 (SHAP)")
            components.shap_contributions(vessel, height=320)
            cols = st.columns(4)
            meta = MODEL_META + [
                ("기대 대비 연료", theme.signed(vessel["fuelDeltaPercent"], "%"))
            ]
            for col, (label, value) in zip(cols, meta):
                with col:
                    st.markdown(
                        f'<div class="bs-card"><div class="bs-label">{label}</div>'
                        f'<div style="font-size:14.5px; font-weight:700;">{value}</div></div>',
                        unsafe_allow_html=True,
                    )
        with right:
            # 어업인 화면과 같은 explain/ 결과를 쓴다. adapter.explanation()이 선박당
            # 한 번만 생성해 캐시하므로, 두 화면이 같은 문장을 본다 — 화면마다 다른
            # 설명이 나오면 "제3자가 관측한 동일한 점수"라는 전제가 문장 층에서 깨진다.
            # 개선 코칭(recommendations)은 여기 두지 않는다. 설계 공유 문서의 노출
            # 범위표대로 코칭은 어업인 화면 몫이고, 여기서는 4번 탭에 참고로만 둔다.
            explanation = adapter.explanation(vessel)
            st.markdown("##### 산출 근거 요약")
            st.markdown(
                f'<div class="bs-card"><div style="font-size:13.5px; line-height:1.85;">'
                f'{explanation["summary"]}</div></div>',
                unsafe_allow_html=True,
            )
            components.explanation_source(explanation)
            st.markdown("##### 요인 상세")
            rows = "".join(
                f'<div style="display:grid; grid-template-columns:1fr auto auto; gap:8px;'
                f' align-items:center; padding:5px 0; font-size:12.5px;">'
                f'<span style="color:{theme.INK_SOFT};">{f["label"]}</span>'
                f'<span style="color:{theme.axis_color(f["axis"])}; font-size:11px; '
                f'font-weight:700;">{f["axis"].upper()}축</span>'
                f'<span class="bs-mono" style="color:{theme.direction_color(f["value"])}; '
                f'font-weight:600;">{theme.signed(f["value"], "")}</span></div>'
                for f in sorted(vessel["shapFactors"], key=lambda x: -abs(x["value"]))
            )
            st.markdown(f'<div class="bs-card">{rows}</div>', unsafe_allow_html=True)

    with tab_data:
        left, right = st.columns([1.2, 1], gap="medium")
        with left:
            st.markdown("##### 관측된 조업 활동")
            components.voyage_map(vessel, height=340)
            st.markdown("##### 데이터 출처")
            st.markdown(
                '<div class="bs-card"><div class="bs-note">'
                'Global Fishing Watch 조업 이벤트(위치·시각·평균속도·이동거리) · '
                '해양수산부 선박제원정보 · 연안 AIS 해역별 척수 통계 · '
                '한국수산자원공단 TAC 소진현황 · 국립해양측위정보원 해양기상<br><br>'
                '보호구역 판정은 GFW 이벤트의 <span class="bs-mono">regions.mpa</span> 태그를 '
                '사용합니다(별도 폴리곤 겹침 연산 없음). 선박 식별정보는 해시 처리되어 '
                '저장되며, 원본 이벤트 데이터는 외부에 기록되지 않습니다.</div></div>',
                unsafe_allow_html=True,
            )
            components.provenance()
        with right:
            st.markdown("##### 산출 조건")
            cond = st.columns(3)
            conditions = [
                ("비교 대상", vessel["peerGroup"]["count"], "척"),
                ("분석 항차", vessel["sailCalls"], "회"),
                ("관측 커버리지", vessel["coveragePercent"], "%"),
            ]
            for col, (label, value, unit) in zip(cond, conditions):
                with col:
                    st.markdown(
                        f'<div class="bs-card"><div class="bs-label">{label}</div>'
                        f'<div class="bs-value">{value}<span class="unit">{unit}</span></div></div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("##### 기록 검증")
            payload = adapter.hash_payload(vessel)
            st.markdown(
                f'<div class="bs-hash">{adapter.score_hash(payload)}</div>'
                f'<div class="bs-note" style="margin-top:10px;">산출 시점의 점수와 근거를 '
                f'해시로 기록해 <b>사후 변조를 막습니다</b>. 항적 원본이나 식별정보는 '
                f'기록하지 않습니다.</div>',
                unsafe_allow_html=True,
            )
            with st.expander("해시 대상 원문 보기"):
                st.json(payload)
                st.markdown(
                    '<div class="bs-note">CLAUDE.md 확정 규칙 5번 적용 — '
                    '<span class="bs-mono">sort_keys=True</span> 직렬화, 소수점 둘째 자리 '
                    '반올림 후 문자열화, 빈 값은 키 자체를 제외.</div>',
                    unsafe_allow_html=True,
                )

            _decision_panel(vessel)

    with tab_sim:
        st.markdown(
            '<div class="bs-note">차주에게 제시될 개선 경로입니다. 심사 판단의 근거가 '
            '아니라 상담용 참고 자료입니다.</div>',
            unsafe_allow_html=True,
        )
        sim = adapter.simulate(
            vessel, vessel["revisitCount"] - 1, vessel["averageSpeedKnots"] - 1.0
        )
        cols = st.columns(4)
        preview = [
            ("현재", f"{vessel['blueScore']}", ""),
            ("개선 시", f"{sim.score}", ""),
            ("순위 변화", f"{vessel['peerGroup']['topPercent']}→{sim.top_percent}", "%"),
            ("기대 대비 연료", theme.signed(sim.fuel_delta_percent, "%"), ""),
        ]
        for col, (label, value, unit) in zip(cols, preview):
            with col:
                st.markdown(
                    f'<div class="bs-card"><div class="bs-label">{label}</div>'
                    f'<div class="bs-value">{value}<span class="unit">{unit}</span></div></div>',
                    unsafe_allow_html=True,
                )
        for note in sim.tradeoff_notes:
            st.markdown(f'<div class="bs-note">· {note}</div>', unsafe_allow_html=True)
        components.rate_table(vessel["blueScore"], sim.score)

    components.backend_footer()
