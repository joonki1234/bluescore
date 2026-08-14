"""
담당: 최지희

BlueScore 대시보드 진입점.

어업인용 화면과 금융기관(심사역)용 화면을 **별도 페이지**로 분리한다. 두 화면은
보여주는 범위가 다르지만, 숫자는 반드시 ui/adapter.py 한 곳에서만 나온다 —
같은 선박에 대해 서로 다른 점수가 보이면 "제3자가 관측한 동일한 점수"라는
서비스 전제가 무너지기 때문이다.

실행:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui import adapter, theme  # noqa: E402

st.set_page_config(
    page_title="BlueScore — 해양 ESG 여신 스코어링",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar() -> None:
    with st.sidebar:
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">'
            f'<div style="width:26px; height:26px; border-radius:7px; '
            f'background:{theme.AXIS_A};"></div>'
            f'<div><div style="font-weight:800; font-size:16px;">BlueScore</div>'
            f'<div style="font-size:11.5px; color:{theme.INK_SOFT};">해양 ESG 여신 스코어링</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        st.divider()

        options = adapter.vessel_options()
        st.selectbox(
            "선박",
            options=options,
            format_func=adapter.vessel_label,
            key="vessel_id",
            help="사용자 입력은 선박 선택 하나뿐입니다. 나머지는 공개 데이터에서 채워집니다.",
        )
        st.selectbox("기간", options=["2026.02 – 2026.07"], key="period", disabled=True)

        vessel = adapter.get_vessel(st.session_state["vessel_id"])
        if adapter.is_scored(vessel):
            st.caption(f"유사 선박군 · {vessel['fleetLabel']}")
        else:
            st.warning(adapter.blocked_notice(vessel)["title"], icon="⚠️")

        st.divider()
        st.caption("데이터 기준일자")
        for name, day in adapter.load_dataset()["dataFreshness"].items():
            st.caption(f"{name} · {day}")


def _fisher_page() -> None:
    from ui import fisher

    _sidebar()
    fisher.render()


def _bank_page() -> None:
    from ui import bank

    _sidebar()
    bank.render()


def main() -> None:
    theme.inject()
    # 기본 페이지는 Streamlit이 루트("/")로 서빙하며 url_path를 무시한다.
    # 따라서 시연용 북마크 주소는 어업인 "/" · 금융기관 "/bank" 두 개다.
    pages = [
        st.Page(_fisher_page, title="어업인", icon=":material/sailing:", default=True),
        st.Page(_bank_page, title="금융기관", icon=":material/account_balance:",
                url_path="bank"),
    ]
    st.navigation(pages, position="top").run()


if __name__ == "__main__":
    main()
