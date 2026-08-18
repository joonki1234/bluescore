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

# .env를 환경변수로 올린다. Streamlit은 .env를 자동으로 읽지 않기 때문에,
# 이게 없으면 파일에 키를 넣어도 os.getenv()가 못 본다.
# python-dotenv가 없어도 앱은 돌아간다 — 환경변수를 직접 export한 경우도 있고,
# 키 없이 폴백으로 도는 것이 정상 동작이기 때문이다.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # pragma: no cover
    pass

from ui import adapter, theme  # noqa: E402

st.set_page_config(
    page_title="BlueScore — 해양 ESG 여신 스코어링",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar_header() -> None:
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


def _sidebar_freshness() -> None:
    st.divider()
    st.caption("데이터 기준일자")
    for name, day in adapter.load_dataset()["dataFreshness"].items():
        st.caption(f"{name} · {day}")


def _sidebar(*, appeal_inbox: bool = False) -> None:
    with st.sidebar:
        _sidebar_header()

        if appeal_inbox:
            appeals = adapter.list_objections()
            if appeals:
                appeal_by_id = {item["appealId"]: item for item in appeals}

                def _open_selected_appeal() -> None:
                    selected = st.session_state.get("selected_appeal_id")
                    if selected in appeal_by_id:
                        st.session_state["vessel_id"] = appeal_by_id[selected]["vesselId"]

                st.selectbox(
                    "이의제기 업무함",
                    options=list(appeal_by_id),
                    format_func=lambda appeal_id: (
                        f"{appeal_by_id[appeal_id]['vesselId']} · "
                        f"{appeal_by_id[appeal_id]['status']} · "
                        f"{appeal_by_id[appeal_id]['scoreRunId']}"
                    ),
                    key="selected_appeal_id",
                    on_change=_open_selected_appeal,
                )
                if not st.session_state.get("appeal_inbox_initialized"):
                    _open_selected_appeal()
                    st.session_state["appeal_inbox_initialized"] = True
            else:
                st.caption("접수된 이의제기가 없습니다.")

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

        _sidebar_freshness()


def _fisher_page() -> None:
    from ui import fisher

    try:
        _sidebar()
        fisher.render()
    except adapter.ApiClientError as exc:
        st.error(str(exc))
        st.code("uvicorn api.main:app --reload --port 8000\nstreamlit run app.py")


def _bank_page() -> None:
    from ui import bank

    try:
        _sidebar(appeal_inbox=True)
        bank.render()
    except adapter.ApiClientError as exc:
        st.error(str(exc))
        st.code("uvicorn api.main:app --reload --port 8000\nstreamlit run app.py")


def _real_preview_page() -> None:
    from ui import real_preview

    try:
        with st.sidebar:
            _sidebar_header()
            st.caption("실제 GFW 조업 이벤트 기준 미리보기 화면입니다.")
            _sidebar_freshness()
        real_preview.render()
    except adapter.ApiClientError as exc:
        st.error(str(exc))
        st.code("uvicorn api.main:app --reload --port 8000\nstreamlit run app.py")


def main() -> None:
    theme.inject()
    # 기본 페이지는 Streamlit이 루트("/")로 서빙하며 url_path를 무시한다.
    # 따라서 시연용 북마크 주소는 어업인 "/" · 금융기관 "/bank" · 실산출 "/real" 세 개다.
    pages = [
        st.Page(_fisher_page, title="어업인", icon=":material/sailing:", default=True),
        st.Page(_bank_page, title="금융기관", icon=":material/account_balance:",
                url_path="bank"),
        st.Page(_real_preview_page, title="실산출", icon=":material/database:",
                url_path="real"),
    ]
    st.navigation(pages, position="top").run()


if __name__ == "__main__":
    main()
