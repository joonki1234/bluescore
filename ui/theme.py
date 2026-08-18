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
.bs-blocked .bs-note {{ font-size: 15px; line-height: 1.7; }}

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

/* ─── 금융기관(PC웹) 화면 ─────────────────────────────────────────────────
   심사 화면은 항목이 많아 섹션 경계가 없으면 카드가 흩어져 보인다. 아래
   클래스는 "제목 → 내용" 한 덩어리를 만들어 화면 전체에 같은 리듬을 준다. */
.bs-sec {{
  font-size: 11px; font-weight: 700; letter-spacing: .06em;
  color: {INK_SOFT}; text-transform: uppercase;
  padding-bottom: 6px; margin: 18px 0 10px;
  border-bottom: 1px solid {LINE};
  display: flex; align-items: baseline; gap: 8px;
}}
.bs-sec .n {{ font-weight: 400; letter-spacing: 0; text-transform: none; font-size: 11.5px; }}

/* 심사 요약 밴드 — 판단에 바로 쓰는 값만 한 줄에 모은다. */
.bs-band {{
  display: grid; gap: 0; background: {SURFACE};
  border: 1px solid {LINE}; border-radius: 12px; overflow: hidden;
}}
.bs-band .cell {{ padding: 13px 16px; border-left: 1px solid {LINE}; }}
.bs-band .cell:first-child {{ border-left: none; }}
.bs-band .k {{ font-size: 11.5px; color: {INK_SOFT}; margin-bottom: 3px; }}
.bs-band .v {{ font-family: {FONT_MONO}; font-size: 19px; font-weight: 700; color: {INK}; }}
.bs-band .s {{ font-size: 11px; color: {INK_SOFT}; margin-top: 2px; }}

/* 요인 원장 — 금리를 내릴 근거 / 올릴 근거를 한 행씩 대조한다. */
.bs-led {{ display: flex; flex-direction: column; gap: 7px; }}
.bs-led .row {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 9px;
  padding: 9px 11px;
}}
.bs-led .top {{ display: flex; align-items: baseline; gap: 7px; }}
.bs-led .lab {{ font-size: 12.5px; font-weight: 600; }}
.bs-led .amt {{ margin-left: auto; font-family: {FONT_MONO}; font-weight: 700; font-size: 13px; }}
.bs-led .bar {{ height: 5px; border-radius: 3px; background: {BG}; margin: 6px 0 5px; }}
.bs-led .bar > i {{ display: block; height: 5px; border-radius: 3px; }}
.bs-led .met {{ font-size: 11px; color: {INK_SOFT}; font-family: {FONT_MONO}; }}
.bs-led .say {{ font-size: 12px; line-height: 1.6; margin-top: 4px; }}

/* 금리 게이지 — 현재 점수가 구간 경계에서 얼마나 떨어져 있는지. */
.bs-gauge {{ position: relative; height: 34px; margin: 14px 0 6px; }}
.bs-gauge .track {{
  position: absolute; top: 13px; left: 0; right: 0; height: 8px;
  border-radius: 5px; overflow: hidden; display: flex;
}}
.bs-gauge .track > span {{ display: block; height: 8px; }}
.bs-gauge .pin {{
  position: absolute; top: 4px; width: 3px; height: 26px;
  background: {INK}; border-radius: 2px;
}}
.bs-gauge .tick {{
  position: absolute; top: 24px; font-size: 10px; color: {INK_SOFT};
  font-family: {FONT_MONO}; transform: translateX(-50%);
}}

/* 축 막대·비교 막대가 채워지는 느낌을 주는 트랜지션. Streamlit은 JS 트리거를
   못 주므로, 요소가 렌더되며 폭이 확정되는 순간 브라우저가 자동 재생하는
   순수 CSS 트랜지션으로 대체한다. */
.bs-fill {{ transition: width 0.9s cubic-bezier(0.22, 1, 0.36, 1); }}

@keyframes bs-fade-in {{
  from {{ opacity: 0; transform: translateY(4px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.bs-card, .bs-scorebar {{ animation: bs-fade-in 0.4s ease-out; }}

/* 실산출처럼 첫 계산에 수 초~수십 초가 걸리는 화면에서, 빈 화면 대신
   "불러오는 중"임을 보여주는 스켈레톤 카드. 값 없이 회색 막대만 깜빡인다 —
   실제 숫자와 헷갈리지 않도록 굴곡·글자를 전혀 넣지 않는다. */
@keyframes bs-skeleton-pulse {{
  0%, 100% {{ opacity: 0.55; }}
  50% {{ opacity: 1; }}
}}
.bs-skeleton-bar {{
  background: {LINE}; border-radius: 6px; animation: bs-skeleton-pulse 1.3s ease-in-out infinite;
}}

/* 실산출 화면이 데모와 같은 톤이라 "이건 진짜 계산값"이라는 게 안 드러났다.
   초록 점을 맥동시켜 실시간 산출임을 시각적으로도 표시한다. */
@keyframes bs-live-pulse {{
  0%   {{ box-shadow: 0 0 0 0 rgba(15, 118, 110, 0.45); }}
  70%  {{ box-shadow: 0 0 0 6px rgba(15, 118, 110, 0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(15, 118, 110, 0); }}
}}
.bs-live-badge {{
  display: inline-flex; align-items: center; gap: 6px; margin-left: 10px;
  padding: 3px 10px 3px 8px; border-radius: 999px;
  background: {POSITIVE_SOFT}; color: {POSITIVE}; font-size: 11.5px; font-weight: 700;
  vertical-align: middle;
}}
.bs-live-badge .dot {{
  width: 7px; height: 7px; border-radius: 50%; background: {POSITIVE};
  animation: bs-live-pulse 1.8s ease-out infinite;
}}

/* 온체인 기록 완료 체크마크 — 결과가 뜨자마자 나타나는 대신 획이 그려지는
   느낌을 줘서, 이의제기→심사→해시 기록 흐름의 마지막 단계임을 체감하게 한다. */
.bs-check-circle {{
  stroke: {POSITIVE}; stroke-width: 2; fill: none;
  stroke-dasharray: 63; stroke-dashoffset: 63;
  animation: bs-check-draw 0.5s ease-out forwards;
}}
.bs-check-mark {{
  stroke: {POSITIVE}; stroke-width: 2.4; fill: none;
  stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 18; stroke-dashoffset: 18;
  animation: bs-check-draw 0.3s ease-out 0.45s forwards;
}}
@keyframes bs-check-draw {{ to {{ stroke-dashoffset: 0; }} }}
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
