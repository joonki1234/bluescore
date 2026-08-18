"""
담당: 오동규, 김준기 (최지희 확인 필요)

실산출(sourceType=real) 미리보기 화면.

배경: A/B축 실산출 파이프라인(score/real_axis_b_scoring.py 등)이 API까지는
연결됐는데(2026-08-18), Streamlit 화면은 sourceType을 "demo"로 고정 호출해서
실산출이 화면 어디서도 안 보였다. 데모 화면(fisher.py/bank.py)을 그대로
실산출에 재사용하지 않은 이유: 그 화면들은 시뮬레이터·설명(explain)·
이의제기까지 쓰는데, services/scoring.py._build_real_score()는 점수 산출만
지원한다(데모 fixture 전용 기능들). 그래서 이 화면은 "점수가 실제로
계산됐다"를 보여주는 최소 기능만 담당하는 별도 페이지로 뺐다.

커버리지가 낮다(A축 61.4%, BlueScore까지 나오는 건 15.2%뿐)는 것과, 해양기상
단위 등 미검증 가정이 있다는 걸 화면에 항상 같이 보여준다 — "모르면 모른다"
원칙.
"""

from __future__ import annotations

import streamlit as st

from ui import adapter, components


def _discount_text(band: dict) -> str:
    if band["discountBp"] <= 0:
        return f"{band['grade']} · 우대 없음"
    return f"{band['grade']} · -{band['discountBp']}bp"


def render() -> None:
    st.markdown(
        '### 실산출 미리보기'
        '<span class="bs-live-badge"><span class="dot"></span>LIVE DATA</span>',
        unsafe_allow_html=True,
    )
    st.caption(
        "가명 시연 데이터가 아니라 실제 GFW 조업 이벤트(data_new/, 2026-04~08월)로 "
        "계산한 결과입니다. 실제 5,323척 규모 데이터 중 807척에 대해 BlueScore가 "
        "완전 산출됩니다. 해양기상 단위(풍속 m/s)는 공식 확인이 아니라 정황 "
        "추정이며, 유속·일부 어업종 필드는 미확인 상태입니다."
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
        f"선박 (실데이터, 상위 {len(vessels)}척)",
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
    else:
        st.success(score.get("message") or "")

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
                "label": "자원 압력 (A축)",
                "value": axis_a_score if axis_a_score is not None else "—",
                "decimals": 1,
                "size": 26,
            },
            {
                "label": "운항 효율 (B축)",
                "value": axis_b_score if axis_b_score is not None else "—",
                "decimals": 1,
                "size": 26,
            },
        ],
        height=108,
    )

    if score.get("rateBand"):
        st.info(f"제안 금리 등급 · {_discount_text(score['rateBand'])}")

    peer = score.get("peerGroup") or {}
    st.caption(f"유사 선박군 표본 {peer.get('count', 0)}척")

    with st.expander("원본 API 응답 (디버그용)"):
        st.json(score)
