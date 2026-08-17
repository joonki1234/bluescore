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


def _decision_panel(vessel: dict, draft: str = "") -> None:
    objection = adapter.get_objection(vessel["vesselId"])
    st.markdown("##### 심사 의견")
    if not objection:
        st.info("접수된 이의제기가 없어 심사 결정을 저장할 수 없습니다.")
        return
    if objection.get("review"):
        review = objection["review"]
        status_text = "승인" if review["decision"] == "approve" else "보류"
        st.success(f"{status_text} 결정이 SQLite에 저장되었습니다 · {review['reviewer']}")
        st.caption(review["reason"])
        return
    st.text_area(
        "의견",
        value=draft,
        key=f"opinion_{vessel['vesselId']}",
        placeholder="심사 의견을 입력하세요",
        height=160,
        label_visibility="collapsed",
        help="AI가 초안을 작성했습니다. 그대로 쓰거나 자유롭게 수정하세요." if draft else None,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("승인", key=f"approve_{vessel['vesselId']}", width="stretch"):
            opinion = st.session_state.get(f"opinion_{vessel['vesselId']}") or "제출 근거 확인"
            adapter.review_objection(vessel["vesselId"], "approve", opinion)
            st.rerun()
    with col_b:
        if st.button("보류", key=f"hold_{vessel['vesselId']}", width="stretch"):
            opinion = st.session_state.get(f"opinion_{vessel['vesselId']}") or "추가 소명 필요"
            adapter.review_objection(vessel["vesselId"], "hold", opinion)
            st.rerun()

    st.markdown(
        '<div class="bs-note">본 리포트는 <b>심사 보조자료</b>입니다. 금리 구간은 사전 '
        '승인된 규칙표에 따른 제안이며, <b>최종 여신 승인은 심사역이 수행합니다.</b></div>',
        unsafe_allow_html=True,
    )


def _final_rate_decision(vessel: dict, band: dict, issued: str) -> None:
    """최종금리결정 탭 — 이의제기 대응, 금리 조회, 심사의견, 승인/보류, 온체인 기록."""
    peer = vessel["peerGroup"]

    components.animated_stat_cards(
        [
            {"label": "BlueScore", "value": vessel["blueScore"], "decimals": 1, "size": 22,
             "color": theme.AXIS_A},
            {"label": "유사군 내", "value": peer["topPercent"], "unit": "%", "size": 22},
            {"label": "비교 대상", "value": peer["count"], "unit": "척", "size": 22},
            {"label": "현재 규칙표 구간", "value": theme.discount_text(band), "size": 17},
        ]
    )

    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        components.objection_panel_bank(vessel)
        st.markdown("##### 금리 구간표")
        components.rate_table(vessel["blueScore"])
        st.markdown("##### 금리 규칙 조회")
        components.smart_contract_lookup_card(vessel, vessel["blueScore"])

    with right:
        explanation = adapter.explanation(vessel)
        draft = (
            f"{vessel['name']}은 BlueScore {vessel['blueScore']}점"
            f"(유사군 {peer['count']}척 중 상위 {peer['topPercent']}%)으로 "
            f"{theme.discount_text(band)} 구간에 해당합니다. {explanation['summary']}"
        )

        principal, term = adapter.EXAMPLE_PRINCIPAL_WON, adapter.EXAMPLE_TERM_YEARS
        yearly, total = theme.interest_saving(band["discountBp"], principal, term)
        st.markdown(
            f'<div class="bs-note">{principal // 100_000_000}억 원 · {term}년 만기 기준 예시</div>',
            unsafe_allow_html=True,
        )
        components.animated_stat_cards(
            [
                {"label": "연간 이자 절감", "value": yearly // 10_000, "unit": "만원",
                 "color": theme.POSITIVE, "size": 20},
                {"label": "만기까지 절감", "value": total // 10_000, "unit": "만원",
                 "color": theme.POSITIVE, "size": 20},
            ],
            height=100,
        )

        _decision_panel(vessel, draft=draft)

        st.markdown("##### 온체인 기록 · 조회")
        objection = adapter.get_objection(vessel["vesselId"])
        commit = adapter.get_report_commit(vessel["scoreRunId"])
        if objection and objection.get("review") and not commit:
            if st.button("심사 결과 온체인 커밋", key=f"commit_{vessel['vesselId']}", width="stretch"):
                adapter.commit_report(vessel["scoreRunId"])
                st.rerun()
        elif not objection or not objection.get("review"):
            st.caption("승인·보류 결정 후 커밋할 수 있습니다.")

        if commit:
            st.markdown(
                f'<div class="bs-card"><div class="bs-label">Record ID</div>'
                f'<div class="bs-hash">{commit["recordId"]}</div>'
                f'<div class="bs-label" style="margin-top:10px;">Result hash</div>'
                f'<div class="bs-hash">{commit["resultHash"]}</div>'
                f'<div class="bs-note" style="margin-top:10px;">원장 {commit["ledgerMode"]} · '
                f'블록 {commit.get("blockNumber") or "-"} · {commit["committedAt"]}<br>'
                f'트랜잭션 {commit.get("transactionHash") or "로컬 모드"}<br>'
                f'컨트랙트 {commit.get("contractAddress") or "-"}</div></div>',
                unsafe_allow_html=True,
            )
        record_id = st.text_input(
            "Record ID 조회", value=commit["recordId"] if commit else "",
            key=f"record_lookup_{vessel['vesselId']}", placeholder="BS-demo-score-...",
        )
        if st.button("기록 조회", key=f"record_lookup_btn_{vessel['vesselId']}") and record_id:
            st.json(adapter.get_chain_record(record_id))


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
    dataset = adapter.load_dataset()
    band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

    tab_detail, tab_final = st.tabs(["1 · 심사상세", "2 · 최종금리결정"])

    with tab_detail:
        _header(vessel, issued)
        peer = vessel["peerGroup"]

        components.animated_stat_cards(
            [
                {"label": "BlueScore", "value": vessel["blueScore"], "decimals": 1, "size": 22,
                 "color": theme.AXIS_A},
                {"label": "유사군 내", "value": peer["topPercent"], "unit": "%", "size": 22},
                {"label": "비교 대상", "value": peer["count"], "unit": "척", "size": 22},
                {"label": "제안 구간", "value": theme.discount_text(band), "size": 17},
            ]
        )

        st.markdown("##### 조업 지도")
        components.voyage_map(vessel, height=340)

        left, right = st.columns([1.3, 1], gap="medium")
        with left:
            components.axis_breakdown(vessel)
            st.markdown("##### 요인별 기여도 (SHAP)")
            components.shap_contributions(vessel, height=320)
            meta = MODEL_META + [
                ("기대 대비 연료", theme.signed(vessel["fuelDeltaPercent"], "%"))
            ]
            components.animated_stat_cards(
                [{"label": label, "value": value, "size": 15} for label, value in meta]
            )
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

            # 어업인 화면과 같은 explain/ 결과를 쓴다. adapter.explanation()이 선박당
            # 한 번만 생성해 캐시하므로, 두 화면이 같은 문장을 본다 — 화면마다 다른
            # 설명이 나오면 "제3자가 관측한 동일한 점수"라는 전제가 문장 층에서 깨진다.
            # 개선 코칭(recommendations)은 여기 두지 않는다. 코칭은 어업인 화면 몫이다.
            explanation = adapter.explanation(vessel)
            st.markdown("##### 산출 근거 요약")
            st.markdown(
                f'<div class="bs-card"><div style="font-size:13.5px; line-height:1.85;">'
                f'{explanation["summary"]}</div></div>',
                unsafe_allow_html=True,
            )
            components.explanation_source(explanation)
            st.markdown("##### 산출 조건")
            components.animated_stat_cards(
                [
                    {"label": "비교 대상", "value": vessel["peerGroup"]["count"], "unit": "척"},
                    {"label": "분석 항차", "value": vessel["sailCalls"], "unit": "회"},
                    {"label": "관측 커버리지", "value": vessel["coveragePercent"], "unit": "%"},
                ]
            )

    with tab_final:
        _final_rate_decision(vessel, band, issued)

    components.backend_footer()
