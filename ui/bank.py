"""
담당: 최지희

금융기관(심사역) 화면.

어업인 화면과 **같은 숫자**를 쓰되 노출 범위가 다르다.
    · 전문용어를 그대로 쓴다 (잔차, 백분위, SHAP)
    · 자격 요건 판정, 데이터 출처·기준일자, 산출 이력을 전면에 둔다
    · 해시와 재현성 정보, 심사의견·승인/보류는 "최종금리결정" 탭에 모아 둔다
    · '산출 근거 요약'은 explain/이 생성한 문장을 어업인 화면과 공유한다.
      LLM 생성인지 템플릿 폴백인지도 함께 표시한다 — 심사역에게는 이 구분 자체가
      심사 근거의 출처 정보다.

탭 구성 — "1 · 심사상세"(심사개요+산출근거+데이터검증 통합), "2 · 최종금리결정"
(이의제기 대응, 금리 조회, 심사의견, 승인/보류, 온체인 기록). 기존 "개선 여지"
탭은 삭제했다 — 코칭은 어업인 화면 몫이라는 원칙과 맞지 않고 심사역에게
실질적으로 쓰이지 않았다.

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


def _review_detail_tab(vessel: dict, band: dict, issued: str) -> None:
    """
    심사상세 탭 — 여신 판단에 필요한 근거를 위에서 아래로 한 줄기로 놓는다.

        판정 요약 → 금리 구간 여유 → 인하/제약 근거 → 관측 근거 → 재현 정보

    이 순서는 심사역이 실제로 묻는 순서다. "얼마인가 → 구간을 넘기는가 →
    무엇 때문인가 → 그 근거가 관측에서 어떻게 나왔나 → 이 결과를 재현할 수
    있나". 예전에는 지도·SHAP·출처가 좌우 컬럼에 섞여 있어 이 흐름이 끊겼다.
    """
    review = adapter.get_review(vessel["scoreRunId"])

    _header(vessel, issued)
    components.review_summary_band(vessel, band, review)

    components.section("금리 구간 여유", "규칙표 경계까지의 거리")
    components.rate_gauge(vessel)

    components.section("금리 판단 근거", "요인별 기여도 · 실측값 대조")
    components.factor_ledger(vessel)

    components.section("판정 종합", "AI 생성 문장 · 계산 결과만 근거로 사용")
    summary_col, eligibility_col = st.columns([1.55, 1], gap="medium")
    with summary_col:
        explanation = adapter.explanation(vessel)
        st.markdown(
            f'<div class="bs-card"><div style="font-size:13.5px; line-height:1.85;">'
            f'{explanation["summary"]}</div></div>',
            unsafe_allow_html=True,
        )
        components.explanation_source(explanation)
    with eligibility_col:
        components.eligibility_card(
            vessel,
            "준법 항목(금어기·보호구역)은 점수 축에서 제외하고 <b>우대 자격 요건</b>으로만 "
            "둡니다. 준법을 점수화하면 변별력이 없을뿐더러 서비스가 감시 도구로 작동하기 "
            "때문입니다.",
        )

    components.section("2축 분해와 유사군 위치")
    axis_col, peer_col = st.columns([1.55, 1], gap="medium")
    with axis_col:
        components.axis_breakdown(vessel)
    with peer_col:
        components.peer_distribution(vessel, height=232)

    components.section("관측 근거", "점수의 원천이 된 조업 활동")
    map_col, obs_col = st.columns([1.55, 1], gap="medium")
    with map_col:
        components.voyage_map(vessel, height=340)
    with obs_col:
        components.animated_stat_cards(
            [
                {"label": "분석 항차", "value": vessel["sailCalls"], "unit": "회", "size": 18},
                {"label": "조업일", "value": vessel["fishingDays"], "unit": "일", "size": 18},
                {"label": "관측 커버리지", "value": vessel["coveragePercent"], "unit": "%",
                 "size": 18},
            ],
            height=92,
        )
        components.animated_stat_cards(
            [
                {"label": "총 이동거리", "value": vessel["totalDistanceKm"], "unit": "km",
                 "size": 18},
                {"label": "추정 연료", "value": vessel["estimatedFuelKl"], "unit": "kL",
                 "decimals": 1, "size": 18},
                {"label": "기대 대비 연료", "value": vessel["fuelDeltaPercent"], "unit": "%",
                 "decimals": 1, "signed": True, "size": 18,
                 "color": theme.direction_color(-vessel["fuelDeltaPercent"])},
            ],
            height=92,
        )
        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
        history = "".join(
            f'<div style="display:flex; gap:10px; font-size:12.5px; '
            f'color:{theme.INK_SOFT}; padding:4px 0;">'
            f'<b class="bs-mono" style="color:{theme.INK}; min-width:34px;">{m}</b>'
            f'<span>BlueScore {s}</span></div>'
            for m, s in zip(["3월", "4월", "5월", "6월", "7월", "8월"], vessel["trend"])
        )
        st.markdown(
            f'<div class="bs-card"><div class="bs-label">산출 이력</div>{history}</div>',
            unsafe_allow_html=True,
        )

    components.section("재현 정보", "같은 결과를 다시 만들기 위한 조건")
    repro_col, source_col = st.columns(2, gap="medium")
    with repro_col:
        components.reproducibility_panel(vessel)
    with source_col:
        meta_rows = "".join(
            f'<div style="display:grid; grid-template-columns:110px 1fr; gap:10px; padding:3px 0;">'
            f'<span class="bs-note">{k}</span>'
            f'<span class="bs-mono" style="font-size:11.5px;">{v}</span></div>'
            for k, v in MODEL_META
        )
        st.markdown(
            f'<div class="bs-card">{meta_rows}'
            f'<div style="border-top:1px solid {theme.LINE}; margin:9px 0 7px;"></div>'
            '<div class="bs-note">'
            'Global Fishing Watch 조업 이벤트(위치·시각·평균속도·이동거리) · '
            '해양수산부 선박제원정보 · 연안 AIS 해역별 척수 통계 · '
            '한국수산자원공단 TAC 소진현황 · 국립해양측위정보원 해양기상<br><br>'
            '보호구역 판정은 GFW 이벤트의 <span class="bs-mono">regions.mpa</span> 태그를 '
            '사용합니다(별도 폴리곤 겹침 연산 없음). 선박 식별정보는 해시 처리되어 '
            '저장되며, 원본 이벤트 데이터는 외부에 기록되지 않습니다.'
            '</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="bs-note">본 리포트는 <b>심사 보조자료</b>입니다. 금리 구간은 사전 '
        '승인된 규칙표에 따른 제안이며, <b>최종 여신 승인은 심사역이 수행합니다.</b></div>',
        unsafe_allow_html=True,
    )


DEFAULT_BASE_RATE_PERCENT = 4.50


def _opinion_draft(vessel: dict, band: dict, final_bp: int) -> str:
    """심사 의견 초안. 심사역이 그대로 쓰거나 고쳐 쓴다."""
    peer = vessel["peerGroup"]
    explanation = adapter.explanation(vessel)
    objection = adapter.get_objection(vessel["vesselId"])

    lines = [
        f"{vessel['name']}은 BlueScore {vessel['blueScore']:g}점"
        f"(유사군 {peer['count']}척 중 상위 {peer['topPercent']}%)으로 "
        f"규칙표상 {band['grade']}구간에 해당합니다.",
        explanation["summary"],
    ]
    if final_bp != band["discountBp"]:
        lines.append(
            f"규칙표 제안({band['discountBp']}bp)과 달리 최종 우대금리를 {final_bp}bp로 "
            f"조정했습니다. 조정 사유를 아래에 보완해 주세요."
        )
    if objection:
        lines.append(f"차주 이의제기 사유('{objection['reason']}')를 검토했습니다.")
    return " ".join(line for line in lines if line)


def _decision_panel(vessel: dict, *, final_bp: int, draft: str) -> None:
    """심사 의견 작성과 승인/보류. 이의제기가 없어도 결정을 저장할 수 있다."""
    review = adapter.get_review(vessel["scoreRunId"])
    if review:
        decided = "승인" if review["decision"] == "approve" else "보류"
        bp = review.get("finalDiscountBp")
        st.success(
            f"{decided} 결정이 저장되었습니다 · {review['reviewer']}"
            + (f" · 최종 우대 −{bp}bp" if bp is not None else "")
        )
        st.markdown(
            f'<div class="bs-card"><div class="bs-label">심사 의견</div>'
            f'<div style="font-size:13.5px; line-height:1.8;">{review["reason"]}</div></div>',
            unsafe_allow_html=True,
        )
        return

    st.text_area(
        "심사 의견",
        value=draft,
        key=f"opinion_{vessel['vesselId']}",
        height=150,
        label_visibility="collapsed",
        help="AI가 초안을 작성했습니다. 그대로 쓰거나 자유롭게 수정하세요.",
    )
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("승인", key=f"approve_{vessel['vesselId']}", width="stretch",
                     type="primary"):
            opinion = st.session_state.get(f"opinion_{vessel['vesselId']}") or "제출 근거 확인"
            adapter.review_score_run(
                vessel["scoreRunId"], "approve", opinion, final_discount_bp=final_bp
            )
            st.session_state[f"decided_{vessel['vesselId']}"] = "approve"
            st.rerun()
    with col_b:
        if st.button("보류", key=f"hold_{vessel['vesselId']}", width="stretch"):
            opinion = st.session_state.get(f"opinion_{vessel['vesselId']}") or "추가 소명 필요"
            adapter.review_score_run(
                vessel["scoreRunId"], "hold", opinion, final_discount_bp=final_bp
            )
            st.session_state[f"decided_{vessel['vesselId']}"] = "hold"
            st.rerun()


def _final_rate_decision(vessel: dict, band: dict, issued: str) -> None:
    """
    최종금리결정 탭.

        수치 요약 → 이의제기 대응 → 금리 규칙 조회 → 최종 금리 확정 →
        심사 의견·결정 → 온체인 기록

    금리를 먼저 확정하고 그 값을 심사 의견 초안과 온체인 payload가 함께 쓰도록
    순서를 잡았다. 규칙표가 제안한 값과 심사역이 확정한 값을 나눠 저장해야
    "자동화한 것은 결정이 아니라 계산과 기록"이라는 원칙이 데이터로도 남는다.
    """
    review = adapter.get_review(vessel["scoreRunId"])
    commit = adapter.get_report_commit(vessel["scoreRunId"])

    components.review_summary_band(vessel, band, review)

    components.section("이의제기 대응", "차주 소명과 회신 초안")
    obj_col, rule_col = st.columns([1.15, 1], gap="medium")
    with obj_col:
        components.objection_panel_bank(vessel)
    with rule_col:
        components.smart_contract_lookup_card(vessel, vessel["blueScore"])
        components.rate_table(vessel["blueScore"])

    components.section("최종 금리 확정", "규칙표 제안을 검토해 심사역이 확정")
    locked_bp = review.get("finalDiscountBp") if review else None
    proposed_bp = band["discountBp"]

    set_col, impact_col = st.columns([1, 1.75], gap="medium")
    with set_col:
        base_rate = st.number_input(
            "기준금리 (%)", min_value=0.0, max_value=20.0, step=0.05,
            value=DEFAULT_BASE_RATE_PERCENT, key=f"base_rate_{vessel['vesselId']}",
            disabled=review is not None,
        )
        principal_eok = st.number_input(
            "대출 원금 (억 원)", min_value=0.1, max_value=100.0, step=0.5,
            value=float(adapter.EXAMPLE_PRINCIPAL_WON) / 100_000_000,
            key=f"principal_{vessel['vesselId']}", disabled=review is not None,
        )
        term_years = st.number_input(
            "만기 (년)", min_value=1, max_value=30, step=1,
            value=adapter.EXAMPLE_TERM_YEARS, key=f"term_{vessel['vesselId']}",
            disabled=review is not None,
        )
        final_bp = st.number_input(
            "최종 우대금리 (bp)", min_value=0, max_value=100, step=1,
            value=int(locked_bp if locked_bp is not None else proposed_bp),
            key=f"final_bp_{vessel['vesselId']}", disabled=review is not None,
            help="규칙표 제안값이 기본으로 들어옵니다. 심사역 판단으로 조정할 수 있습니다.",
        )
        if final_bp != proposed_bp:
            st.markdown(
                f'<div class="bs-note" style="color:{theme.AXIS_B};">규칙표 제안 '
                f'{proposed_bp}bp에서 <b>{final_bp - proposed_bp:+d}bp</b> 조정했습니다. '
                f'조정 사유를 심사 의견에 남겨 주세요.</div>',
                unsafe_allow_html=True,
            )
    with impact_col:
        components.interest_impact(
            base_rate_percent=float(base_rate),
            final_bp=int(final_bp),
            principal_won=int(principal_eok * 100_000_000),
            term_years=int(term_years),
        )

    components.section("심사 의견과 결정", "최종 여신 승인은 심사역이 수행")
    opinion_col, chain_col = st.columns([1.35, 1], gap="medium")
    with opinion_col:
        _decision_panel(
            vessel,
            final_bp=int(final_bp),
            draft=_opinion_draft(vessel, band, int(final_bp)),
        )
        st.markdown(
            '<div class="bs-note">본 리포트는 <b>심사 보조자료</b>입니다. 금리 구간은 사전 '
            '승인된 규칙표에 따른 제안이며, <b>최종 여신 승인은 심사역이 수행합니다.</b></div>',
            unsafe_allow_html=True,
        )

    with chain_col:
        if not review:
            st.markdown(
                '<div class="bs-card"><div class="bs-note">승인 또는 보류 결정을 저장하면 '
                '최종 리포트 해시를 온체인에 기록할 수 있습니다.</div></div>',
                unsafe_allow_html=True,
            )
        elif not commit:
            if st.button("심사 결과 온체인 커밋", key=f"commit_{vessel['vesselId']}",
                         width="stretch", type="primary"):
                with st.spinner("해시를 계산해 원장에 기록하는 중..."):
                    adapter.commit_report(vessel["scoreRunId"])
                st.session_state[f"just_committed_{vessel['vesselId']}"] = True
                st.rerun()

        if commit:
            just = st.session_state.pop(f"just_committed_{vessel['vesselId']}", False)
            if just:
                st.toast("온체인에 기록했습니다.", icon="⛓️")
                st.balloons()
            components.onchain_receipt(commit)

        with st.expander("Record ID로 기록 조회"):
            record_id = st.text_input(
                "Record ID", value=commit["recordId"] if commit else "",
                key=f"record_lookup_{vessel['vesselId']}", placeholder="BS-demo-score-...",
                label_visibility="collapsed",
            )
            if st.button("조회", key=f"record_lookup_btn_{vessel['vesselId']}") and record_id:
                st.json(adapter.get_chain_record(record_id))


def render() -> None:
    theme.inject()
    vessel_id = st.session_state.get("vessel_id", adapter.vessel_options()[0])
    vessel = adapter.get_vessel(vessel_id)
    issued = date.today().isoformat()

    components.page_title(vessel['name'], "여신 심사")

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
    dataset = adapter.load_dataset()
    band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

    tab_detail, tab_final = st.tabs(["1 · 심사상세", "2 · 최종금리결정"])

    with tab_detail:
        _review_detail_tab(vessel, band, issued)

    with tab_final:
        _final_rate_decision(vessel, band, issued)

    components.backend_footer()
