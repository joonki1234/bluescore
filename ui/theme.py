"""
담당: 최지희

색 토큰 · 전역 CSS · 숫자 포맷 헬퍼.

색 규칙 (두 체계를 절대 섞지 않는다)
------------------------------------
    축 색     A 자원압력 = 파랑 · B 운항효율 = 앰버
    방향 색   가점 = 청록 · 감점 = 빨강

발표 목업에서는 주황 하나가 '지도의 조업 이벤트'와 'B축 운항효율' 양쪽에
쓰여 2축 분해 화면에서 오독을 부를 수 있었다. 여기서는 지도의 조업 이벤트를
파랑(A축)으로 칠한다 — 조업 위치와 재방문이 만들어내는 값이 A축이기 때문이다.
그 결과 앰버는 연료·효율에만 남고, 색이 곧 축을 뜻하게 된다.

대비: 목업의 보조 텍스트 #98A2B3은 흰 배경에서 2.58:1로 WCAG AA(4.5:1)에
미달해 폐기했다. INK_SOFT(#667085, 4.98:1)를 하한으로 쓴다.
"""

from typing import List, Tuple

# ─── 축 색 ────────────────────────────────────────────────────────────────
AXIS_A = "#1E40AF"
AXIS_A_SOFT = "#E5EDFF"
AXIS_B = "#B45309"
AXIS_B_SOFT = "#FDF0DC"

# ─── 방향 색 ──────────────────────────────────────────────────────────────
POSITIVE = "#0F766E"
POSITIVE_SOFT = "#E6F4F1"
NEGATIVE = "#B91C1C"
NEGATIVE_SOFT = "#FBE9E9"

# ─── 중립 ─────────────────────────────────────────────────────────────────
BG = "#F8FAFC"
SURFACE = "#FFFFFF"
LINE = "#D9E2EC"
INK = "#101828"
INK_SOFT = "#667085"

FONT_SANS = (
    "Pretendard, -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', "
    "'Malgun Gothic', sans-serif"
)
FONT_MONO = "'IBM Plex Mono', 'SFMono-Regular', Menlo, monospace"

_CSS = f"""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"] {{ font-family: {FONT_SANS}; }}
.stApp {{ background: {BG}; }}

.bs-card {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
  padding: 16px 18px; margin-bottom: 12px;
}}
.bs-label {{ font-size: 12px; color: {INK_SOFT}; margin-bottom: 4px; }}
.bs-value {{ font-size: 20px; font-weight: 700; color: {INK}; }}
.bs-value .unit {{ font-size: 12px; font-weight: 500; color: {INK_SOFT}; margin-left: 2px; }}
.bs-mono {{ font-family: {FONT_MONO}; }}
.bs-note {{ font-size: 12px; color: {INK_SOFT}; line-height: 1.65; }}

.bs-scorebar {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
  padding: 14px 18px; margin-bottom: 16px;
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
}}
.bs-scorebar .seg {{ padding-left: 20px; border-left: 1px solid {LINE}; }}
.bs-scorebar .seg:first-child {{ padding-left: 0; border-left: none; }}
.bs-scorebar .big {{
  font-family: {FONT_MONO}; font-size: 30px; font-weight: 600; color: {INK}; line-height: 1.1;
}}
.bs-scorebar .mid {{ font-size: 16px; font-weight: 700; color: {INK}; }}

.bs-pill {{
  display: inline-block; border-radius: 999px; padding: 5px 12px;
  font-size: 12px; font-weight: 600; margin: 0 6px 6px 0;
}}
.bs-pill.pass {{ background: {POSITIVE_SOFT}; color: {POSITIVE}; }}
.bs-pill.fail {{ background: {NEGATIVE_SOFT}; color: {NEGATIVE}; }}
.bs-pill.info {{ background: {AXIS_A_SOFT}; color: {AXIS_A}; }}

.bs-blocked {{
  background: {SURFACE}; border: 1px solid {LINE}; border-left: 4px solid {INK_SOFT};
  border-radius: 0 12px 12px 0; padding: 18px 20px;
}}
.bs-blocked .t {{ font-size: 19px; font-weight: 700; color: {INK}; margin-bottom: 8px; }}

.bs-hash {{
  font-family: {FONT_MONO}; font-size: 12px; background: {BG};
  border: 1px solid {LINE}; border-radius: 8px; padding: 12px;
  word-break: break-all; color: {INK_SOFT};
}}
.bs-prov {{
  font-size: 12px; color: {INK_SOFT}; line-height: 1.9;
  border-top: 1px solid {LINE}; padding-top: 10px;
}}
.bs-prov .d {{ font-family: {FONT_MONO}; color: {INK}; }}

div[data-testid="stMetricValue"] {{ font-family: {FONT_MONO}; }}
</style>
"""


def inject() -> None:
    """전역 CSS 주입. 각 페이지 최상단에서 한 번 호출한다."""
    import streamlit as st

    st.markdown(_CSS, unsafe_allow_html=True)


def axis_color(axis: str) -> str:
    return AXIS_A if axis == "a" else AXIS_B


def direction_color(value: float) -> str:
    return POSITIVE if value >= 0 else NEGATIVE


def signed(value: float, unit: str = "p", decimals: int = 1) -> str:
    """부호를 항상 붙인다. 색만으로 방향을 전달하지 않기 위한 것."""
    return f"{value:+.{decimals}f}{unit}"


def top_percent_text(pct: int) -> str:
    return f"상위 {pct}%"


def interval_text(interval: dict) -> str:
    return f"90% 구간 {interval['lower']}–{interval['upper']}%"


def grade_band(score: float, grades: List[dict]) -> dict:
    """점수를 은행 사전 승인 규칙표의 등급 구간에 매핑한다."""
    for band in grades:
        if score >= band["minScore"]:
            return band
    return grades[-1]


def discount_text(band: dict) -> str:
    if band["discountBp"] <= 0:
        return f"{band['grade']} · 우대 없음"
    return f"{band['grade']} · −{band['discountBp']}bp"


def interest_saving(discount_bp: int, principal_won: int, years: int) -> Tuple[int, int]:
    """(연간 절감액, 만기까지 절감액) 원 단위. 단리 근사 — 예시 표기용."""
    yearly = int(principal_won * discount_bp / 10000)
    return yearly, yearly * years
