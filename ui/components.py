"""
담당: 최지희

어업인 화면과 심사역 화면이 공유하는 컴포넌트.

여기 있는 컴포넌트는 두 화면에서 **같은 숫자**를 그린다. 표현(라벨 문구, 노출
범위)만 화면별로 다르고, 값은 전부 ui/adapter.py에서 온다.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional

import plotly.graph_objects as go
import streamlit as st
from streamlit.components.v1 import html as components_html

from ui import adapter, theme

# 추상 격자좌표를 선박 앵커 기준 위경도로 변환하는 계수 (발표 목업과 동일)
_SCALE_LAT = 0.00032
_SCALE_LNG = 0.00042

_PLOTLY_FONT = dict(family=theme.FONT_SANS, size=13, color=theme.INK)

# Esri World Imagery — API 키가 필요 없는 위성 타일. 발표용 목업 HTML에서 이미
# 정상 동작을 확인한 소스이며, 시연 이미지의 어두운 위성 지도와 같은 계열이다.
ESRI_WORLD_IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
ESRI_ATTRIBUTION = "Tiles &copy; Esri — Esri, Maxar, Earthstar Geographics"

# 줌 역산에 쓰는 가정 폭(px). 2단 레이아웃의 왼쪽 컬럼 실측에 가깝게 잡았다.
_ASSUMED_MAP_WIDTH_PX = 560

# 어두운 위성 배경 위에서 읽히도록 조정한 지도 전용 색. 조업 이벤트는 A축
# 계열(파랑), 보호구역은 감점색(theme.NEGATIVE)을 그대로 써서 축 색 체계를 유지한다.
MAP_FISHING = "#60A5FA"
MAP_SAILING = "#BBD3FA"
MAP_GAP = "#EEF1F5"
MAP_MPA = theme.NEGATIVE

# 지리 기준점 — 지도가 어디를 보고 있는지 즉시 알 수 있게 한다.
_LANDMARKS = [
    {"lat": 37.2416, "lng": 131.8686, "name": "독도"},
    {"lat": 37.5054, "lng": 130.8642, "name": "울릉도"},
]

# ─── JS 애니메이션 위젯 공용 스타일·스크립트 ───────────────────────────────────
# Streamlit이 재실행마다 DOM을 새로 그리므로 CSS 트랜지션은 중간 상태 없이
# 최종값을 바로 페인트한다. 카운트업·막대 채움은 components.v1.html(iframe) 안에서
# 진짜 JS로 애니메이션한다. iframe은 전역 CSS를 못 받아 bs-card 스타일을 여기 한
# 곳에 최소 복제해 재사용한다.
_MINI_CARD_CSS = f"""
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:0; background:transparent; font-family:{theme.FONT_SANS}; }}
  .bs-mini-card {{
    background:{theme.SURFACE}; border:1px solid {theme.LINE}; border-radius:12px;
    padding:14px 16px; opacity:0; transform:translateY(6px);
    animation:bs-mini-in 0.5s ease-out forwards;
  }}
  @keyframes bs-mini-in {{ to {{ opacity:1; transform:translateY(0); }} }}
  .bs-mini-label {{ font-size:12px; color:{theme.INK_SOFT}; margin-bottom:4px; }}
  .bs-mini-value-row {{ display:flex; align-items:baseline; gap:3px; }}
  .bs-mini-value {{ font-family:{theme.FONT_MONO}; font-weight:700; }}
  .bs-mini-unit {{ font-size:12px; font-weight:500; color:{theme.INK_SOFT}; }}
  .bs-mini-track {{
    position:relative; height:8px; background:{theme.BG}; border-radius:5px; margin-top:8px;
  }}
  .bs-mini-fill {{
    height:100%; border-radius:5px; width:0%;
    transition:width 1.1s cubic-bezier(0.22, 1, 0.36, 1);
  }}
  .bs-mini-marker {{
    position:absolute; top:-3px; width:2px; height:14px; background:{theme.INK_SOFT};
  }}
  .bs-mini-pill {{
    display:inline-block; border-radius:999px; padding:3px 10px;
    font-size:11px; font-weight:700; margin-top:8px;
  }}
  .bs-mini-pill.favorable {{ background:{theme.POSITIVE_SOFT}; color:{theme.POSITIVE}; }}
  .bs-mini-pill.unfavorable {{ background:{theme.NEGATIVE_SOFT}; color:{theme.NEGATIVE}; }}
</style>
"""

_COUNT_UP_JS = """
function bsAnimateCount(el, from, target, decimals, duration, signed) {
  var startTime = null;
  function step(ts) {
    if (!startTime) startTime = ts;
    var progress = Math.min((ts - startTime) / duration, 1);
    var eased = 1 - Math.pow(1 - progress, 3);
    var current = from + (target - from) * eased;
    var text = current.toFixed(decimals);
    if (signed && current >= 0) { text = '+' + text; }
    el.textContent = text;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
function bsAnimateAll(root) {
  root.querySelectorAll('[data-count]').forEach(function(el) {
    bsAnimateCount(
      el, parseFloat(el.dataset.from || '0'), parseFloat(el.dataset.count),
      parseInt(el.dataset.decimals || '0'), parseInt(el.dataset.duration || '900'),
      el.dataset.signed === '1'
    );
  });
  root.querySelectorAll('[data-fill]').forEach(function(el) {
    setTimeout(function() { el.style.width = el.dataset.fill + '%'; }, 50);
  });
}
window.addEventListener('DOMContentLoaded', function() { bsAnimateAll(document); });
"""


def _stat_card_html(s: Dict) -> str:
    value = s["value"]
    if isinstance(value, (int, float)):
        number_html = (
            f'<span class="bs-mini-value" style="font-size:{s.get("size", 20)}px; '
            f'color:{s.get("color", theme.INK)};" data-count="{value}" '
            f'data-decimals="{s.get("decimals", 0)}" data-signed="{1 if s.get("signed") else 0}">0</span>'
        )
    else:
        # 문자열 값(등급 텍스트 등)은 셀 수 없으니 애니메이션 없이 그대로 보여준다.
        number_html = (
            f'<span class="bs-mini-value" style="font-size:{s.get("size", 20)}px; '
            f'color:{s.get("color", theme.INK)};">{value}</span>'
        )
    unit = f'<span class="bs-mini-unit">{s.get("unit", "")}</span>' if s.get("unit") else ""
    return (
        f'<div class="bs-mini-card"><div class="bs-mini-label">{s["label"]}</div>'
        f'<div class="bs-mini-value-row">{number_html}{unit}</div></div>'
    )


def animated_stat_cards(stats: List[Dict], height: int = 100) -> None:
    """숫자 카드 여러 개를 한 행에 0→값 카운트업 애니메이션과 함께 그린다.

    `stats` 각 항목: {"label","value","unit","color","decimals","signed"}. `value`가
    문자열이면(예: 등급 텍스트) 애니메이션 없이 그대로 표시한다.
    """
    cards = "".join(_stat_card_html(s) for s in stats)
    html = (
        f"{_MINI_CARD_CSS}"
        f'<div style="display:grid; grid-template-columns:repeat({len(stats)}, 1fr); gap:12px;">'
        f"{cards}</div><script>{_COUNT_UP_JS}</script>"
    )
    components_html(html, height=height, scrolling=False)


def animated_transition_card(
    label: str,
    before,
    after,
    *,
    unit: str = "",
    decimals: int = 1,
    color: Optional[str] = None,
    note_html: str = "",
    height: int = 118,
) -> None:
    """"72.6 → 76.3" 같은 전후 비교 카드. before/after가 숫자면 그 구간을
    카운트업하고, 문자열(등급 텍스트 등)이면 애니메이션 없이 페이드인만 한다."""
    numeric = isinstance(before, (int, float)) and isinstance(after, (int, float))
    if numeric:
        color = color or theme.direction_color(after - before)
        before_display = f"{before:.{decimals}f}"
        after_html = (
            f'<span class="bs-mini-value" style="font-size:28px; font-weight:700; '
            f'color:{color};" data-count="{after}" data-from="{before}" '
            f'data-decimals="{decimals}">{before_display}</span>'
        )
    else:
        color = color or theme.INK
        before_display = str(before)
        after_html = (
            f'<span style="font-size:21px; font-weight:800; color:{color};">{after}</span>'
        )

    html = f"""
{_MINI_CARD_CSS}
<div class="bs-mini-card">
  <div class="bs-mini-label">{label}</div>
  <div style="display:flex; align-items:baseline; gap:10px;">
    <span style="font-size:17px; color:{theme.INK_SOFT};">{before_display}</span>
    <span style="color:{theme.INK_SOFT};">→</span>
    {after_html}
    <span class="bs-mini-unit">{unit}</span>
  </div>
  <div style="font-size:12px; color:{theme.INK_SOFT}; line-height:1.65; margin-top:8px;">{note_html}</div>
</div>
<script>{_COUNT_UP_JS}</script>
"""
    components_html(html, height=height, scrolling=False)


def _chart(fig: go.Figure, height: int, margin: Optional[Dict[str, int]] = None) -> None:
    fig.update_layout(
        height=height,
        margin=margin or dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=_PLOTLY_FONT,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def card(body: str) -> None:
    st.markdown(f'<div class="bs-card">{body}</div>', unsafe_allow_html=True)


def page_title(title: str, subtitle: str, *, badge_html: str = "") -> None:
    """어업인/금융기관/실산출 화면 최상단 제목 — 담백한 사각 박스 하나로 표시한다.
    Streamlit 기본 헤딩은 다른 카드들과 존재감이 비슷해 화면 최상단이라는 게
    눈에 잘 안 들어온다. 좌측 축색 강조 바 + 더 크고 굵은 제목으로 구분한다.
    """
    st.markdown(
        f"""<div class="bs-card" style="padding:16px 18px; margin-bottom:16px;">
  <div style="display:flex; align-items:baseline; gap:10px;">
    <span style="font-size:20px; font-weight:700; color:{theme.INK};">{title}</span>
    {badge_html}
  </div>
  <div class="bs-label" style="margin-top:2px;">{subtitle}</div>
</div>""",
        unsafe_allow_html=True,
    )


# ─── 실산출 미리보기 전용 시각화 ────────────────────────────────────────────
def real_vessel_meta_card(vessel_meta: str, matching_reason: Optional[str], peer_count: int,
                           axis_a_event_count: Optional[int], axis_b_event_count: Optional[int]) -> None:
    """선택한 선박의 어업종·톤수·A/B축 각각의 이벤트 건수를 pill 형태로 보여준다.

    A/B축 건수는 같은 개념이 아니다 — A축은 GFW 원본 이벤트 전체, B축은
    거기서 해양기상 결합·톤수 매칭까지 된 부분집합이라 서로 다를 수 있다
    (score/real_axis_b_input.py 참고). 그래서 각각 표시한다 — 하나로 합치면
    "B축이 왜 이 값 미만인지"를 설명할 근거가 사라진다.
    """
    pills = [f'<span class="bs-pill info">{vessel_meta}</span>']
    if axis_a_event_count is not None:
        pills.append(f'<span class="bs-pill info">A축 이벤트 {axis_a_event_count:,}건</span>')
    if axis_b_event_count is not None:
        pills.append(f'<span class="bs-pill info">B축 이벤트 {axis_b_event_count:,}건</span>')
    pills.append(f'<span class="bs-pill info">유사 선박군 {peer_count}척</span>')
    note = f'<div class="bs-note" style="margin-top:8px;">{matching_reason}</div>' if matching_reason else ""
    st.markdown(
        f'<div class="bs-card">{"".join(pills)}{note}</div>',
        unsafe_allow_html=True,
    )


def real_shap_factor_bars(factors: List[Dict]) -> None:
    """A축 요인 기여도(SHAP)를 axis_breakdown()과 같은 카운트업+채움 막대로 보여준다.

    factors는 score/shap_factors.axis_a_factor_shares()가 낸 {"label","value","axis"} 리스트.
    raw가 낮을수록(압력이 적을수록) A축 점수가 높아지므로, value의 +/- 부호는
    좋고 나쁨과 반대로 읽혀 오독하기 쉽다. +/- 부호는 빼고 절댓값만 보여주며,
    유리(value<0)는 초록, 불리(value>0)는 빨강으로 직접 칠해 "좋다=초록"을 통일한다.
    """
    if not factors:
        return

    rows = []
    for f in factors:
        value = f["value"]
        width = min(abs(value), 100.0)
        if value < 0:
            color = theme.POSITIVE
            pill = f'<span class="bs-mini-pill favorable">압력 감소 · 이 선박에 유리</span>'
        elif value > 0:
            color = theme.NEGATIVE
            pill = f'<span class="bs-mini-pill unfavorable">압력 증가 · 이 선박에 불리</span>'
        else:
            color = theme.INK_SOFT
            pill = ""
        rows.append(
            f"""<div class="bs-mini-card" style="margin-bottom:10px;">
  <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:6px;">
    <span style="font-size:13.5px; font-weight:700; color:{theme.INK};">{f['label']}</span>
    <span class="bs-mini-value" style="margin-left:auto; font-size:16px; font-weight:800;
      color:{color};" data-count="{width}" data-decimals="1">0</span>
    <span class="bs-mini-unit">%</span>
  </div>
  <div class="bs-mini-track">
    <div class="bs-mini-fill" style="background:{color};" data-fill="{width}"></div>
  </div>
  {pill}
</div>"""
        )

    html = f"{_MINI_CARD_CSS}{''.join(rows)}<script>{_COUNT_UP_JS}</script>"
    components_html(html, height=118 * len(factors), scrolling=False)


def skeleton_score_card(label: str = "불러오는 중…") -> None:
    """BlueScore/A축/B축 카드 자리의 로딩 스켈레톤.

    실산출 화면은 첫 요청에서 전체 선박 상태 정렬·B축 LightGBM 학습이 걸려
    빈 화면이 멈춘 것처럼 보이므로, 기다리는 동안 값 없는 회색 막대를 보여준다.
    """
    bar = '<div class="bs-skeleton-bar" style="height:{h}px; width:{w}%; margin-bottom:{m}px;"></div>'
    cols_html = "".join(
        f'<div class="bs-card" style="flex:1;">'
        + bar.format(h=12, w=50, m=10)
        + bar.format(h=26, w=70, m=0)
        + "</div>"
        for _ in range(3)
    )
    st.markdown(
        f'<div class="bs-note" style="margin-bottom:8px;">{label}</div>'
        f'<div style="display:flex; gap:12px;">{cols_html}</div>',
        unsafe_allow_html=True,
    )


# score_bar 전용 CSS — theme.py의 .bs-scorebar/.seg/.bs-label/.big/.mid를 그대로
# 복제한다. iframe(components_html) 안이라 전역 CSS(theme.inject())를 못 받는다.
_SCOREBAR_CSS = f"""
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:0; background:transparent; font-family:{theme.FONT_SANS}; }}
  .bs-scorebar {{
    background:{theme.SURFACE}; border:1px solid {theme.LINE}; border-radius:12px;
    padding:14px 18px; display:flex; align-items:center; gap:20px; flex-wrap:wrap;
    opacity:0; transform:translateY(4px); animation:bs-fade-in 0.4s ease-out forwards;
  }}
  @keyframes bs-fade-in {{ to {{ opacity:1; transform:translateY(0); }} }}
  .bs-scorebar .seg {{ padding-left:20px; border-left:1px solid {theme.LINE}; }}
  .bs-scorebar .seg:first-child {{ padding-left:0; border-left:none; }}
  .bs-scorebar .bs-label {{ font-size:12px; color:{theme.INK_SOFT}; margin-bottom:4px; }}
  .bs-scorebar .big {{
    font-family:{theme.FONT_MONO}; font-size:30px; font-weight:600; color:{theme.INK}; line-height:1.1;
  }}
  .bs-scorebar .mid {{ font-size:16px; font-weight:700; color:{theme.INK}; }}
</style>
"""


def score_bar(vessel: Dict, *, show_grade: bool = True) -> None:
    """화면 최상단에 항상 붙는 점수 띠. 어느 탭에 있든 점수가 보이게 해서
    시뮬레이터에서의 변화가 시야에서 사라지지 않게 한다. st.markdown의 <script>는
    Streamlit이 실행해주지 않으므로 components.v1.html(iframe)에서 _COUNT_UP_JS로 돌린다.
    """
    if not adapter.is_scored(vessel):
        notice = adapter.blocked_notice(vessel)
        st.markdown(
            f'<div class="bs-blocked"><div class="t">{notice["title"]}</div>'
            f'<div class="bs-note">{notice["body"]}<br><br>{notice["next"]}</div></div>',
            unsafe_allow_html=True,
        )
        return

    peer = vessel["peerGroup"]
    dataset = adapter.load_dataset()
    band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

    grade_seg = ""
    if show_grade:
        grade_seg = (
            f'<div class="seg"><div class="bs-label">제안 등급</div>'
            f'<div class="mid">{theme.discount_text(band)}</div></div>'
        )

    html = f"""{_SCOREBAR_CSS}
<div class="bs-scorebar">
  <div class="seg">
    <div class="bs-label">BlueScore</div>
    <div class="big" data-count="{vessel['blueScore']}" data-decimals="1" data-duration="900">0.0</div>
  </div>
  <div class="seg">
    <div class="bs-label">유사 선박군 {peer['count']}척 내</div>
    <div class="mid">{theme.top_percent_text(peer['topPercent'])}</div>
    <div class="bs-label" style="margin-top:2px;">{theme.interval_text(peer['topPercentInterval'])}</div>
  </div>
  {grade_seg}
  <div class="seg" style="margin-left:auto; text-align:right;">
    <div class="bs-label">{vessel['fleetLabel']}</div>
    <div class="bs-label">관측 커버리지 {vessel['coveragePercent']}%</div>
  </div>
</div>
<script>{_COUNT_UP_JS}</script>
"""
    components_html(html, height=104, scrolling=False)


def voyage_map(vessel: Dict, height: int = 380) -> None:
    """조업 이벤트 지도.

    CLAUDE.md 확정 규칙 1번 — GFW는 연속 항적이 아니라 이산 이벤트만 제공하므로
    점선 보간 + 이벤트 지점 강조로 그린다. 이어진 선은 항적선이 아니라 이벤트
    순서 보조선이다. 조업 이벤트는 파랑(A축 색), 앰버는 연료·효율(B축)에만 남긴다.
    """
    track = vessel["track"]
    if not track:
        st.info("표시할 조업 이벤트가 없습니다.")
        return

    origin_x, origin_y = track[0]
    anchor = vessel.get("anchor")
    if not anchor or len(anchor) != 2:
        st.warning("지도 기준 좌표가 없어 조업 이벤트 지도를 표시할 수 없습니다.")
        return
    anchor_lat, anchor_lng = anchor

    def _to_latlng(gx: float, gy: float) -> tuple:
        return (anchor_lat - (gy - origin_y) * _SCALE_LAT,
                anchor_lng + (gx - origin_x) * _SCALE_LNG)

    # 동일 구역 반복조업 — 격자좌표를 셀 단위로 묶는다.
    # TODO(score/): 셀 크기는 화면 표현용 임시값이다. A축의 GRID_CELL_SIZE_DEG가
    # 확정되면 그 격자를 그대로 그려야 화면과 계산이 같은 격자를 말하게 된다.
    cell_size = 40
    cell_members: Dict[tuple, List[int]] = {}
    for idx, (gx, gy) in enumerate(track):
        cell_members.setdefault((gx // cell_size, gy // cell_size), []).append(idx)

    # 재방문 '횟수'는 그 격자의 이벤트 개수가 아니라 연속 구간(방문)의 개수다 —
    # A축이 재방문 '간격'을 보는 지표이므로 이 구분이 곧 지표의 정의다.
    def _visit_runs(members: List[int]) -> List[List[int]]:
        runs: List[List[int]] = []
        for idx in members:
            if runs and idx == runs[-1][-1] + 1:
                runs[-1].append(idx)
            else:
                runs.append([idx])
        return runs

    cell_visits: Dict[tuple, List[List[int]]] = {
        cell: _visit_runs(members) for cell, members in cell_members.items()
    }

    shap_by_axis = {"a": [], "b": []}
    for factor in vessel.get("shapFactors", []):
        shap_by_axis.setdefault(factor["axis"], []).append(factor)
    top_a_factor = max(shap_by_axis["a"], key=lambda f: abs(f["value"]), default=None)
    top_b_factor = max(shap_by_axis["b"], key=lambda f: abs(f["value"]), default=None)
    # 반복조업 지점에는 재방문 관련 요인을 붙인다. 없으면 A축 최대 요인으로 대체.
    revisit_factor = next(
        (f for f in shap_by_axis["a"] if "재방문" in f["label"]), top_a_factor
    )

    def _impact_of(factor: Optional[Dict]) -> str:
        """점수를 올린 요인인지 내린 요인인지는 실제 기여도 부호로 정한다.

        "반복 조업 = 점수 하락"으로 단정하면, 재방문 간격을 충분히 확보해
        기여도가 양수인 선박에서 화면이 사실과 반대되는 말을 하게 된다.
        """
        if not factor:
            return "neutral"
        return "up" if factor["value"] > 0 else "down" if factor["value"] < 0 else "neutral"

    def _factor_note(factor: Optional[Dict]) -> str:
        if not factor:
            return ""
        direction = "올린" if factor["value"] > 0 else "내린" if factor["value"] < 0 else "영향이 없는"
        return f"{factor['label']} {factor['value']:+.1f}점 — 점수를 {direction} 요인입니다."

    events = []
    heat_points = []
    for idx, (gx, gy) in enumerate(track):
        lat, lng = _to_latlng(gx, gy)
        is_fishing = any(s <= idx <= e for s, e in vessel["fishingSegments"])
        is_gap = idx == vessel.get("gapIndex", -1)
        is_mpa = idx == vessel.get("mpaIndex", -1)
        cell = (gx // cell_size, gy // cell_size)
        revisits = len(cell_visits[cell])

        if is_gap:
            kind, radius = "신호두절(GAP)", 5
        elif is_fishing:
            kind, radius = "조업", 6
            heat_points.append([lat, lng, min(1.0, 0.35 + 0.25 * revisits)])
        else:
            kind, radius = "항해", 4

        # headline(무슨 일이 있었는지)은 관측 사실만, impact(점수 방향)는 실제
        # 기여도 부호에서 가져온다 — 섞어 단정하면 계산 결과와 반대로 말하게 된다.
        if is_mpa:
            impact = "down"
            headline = "해양보호구역에서 조업 신호가 잡혔어요"
            detail = "보호구역 진입은 우대 자격 요건에서 감점 요인입니다."
        elif is_gap:
            impact = "warn"
            headline = "이 지점에서 위치 신호가 끊겼어요"
            detail = "신호두절 구간은 관측 커버리지를 떨어뜨립니다."
        elif is_fishing and revisits > 1:
            impact = _impact_of(revisit_factor)
            verb = {"down": "그만큼 자원압력 점수가 깎였어요",
                    "up": "그래도 되돌아오는 간격은 넉넉했어요",
                    "neutral": ""}[impact]
            headline = f"이 구역을 {revisits}번 반복 조업했어요"
            if verb:
                headline += f" — {verb}"
            detail = _factor_note(revisit_factor)
        elif is_fishing:
            impact = _impact_of(revisit_factor)
            headline = "이 구역에서는 한 번만 조업했어요"
            detail = _factor_note(revisit_factor)
        else:
            impact = _impact_of(top_b_factor)
            headline = "어장을 오가는 항해 구간이에요"
            detail = _factor_note(top_b_factor)

        events.append({
            "lat": lat, "lng": lng, "radius": radius,
            "fishing": is_fishing, "dashed": is_gap, "mpa": is_mpa,
            "home": idx == 0, "seq": idx + 1, "kind": kind,
            "revisits": revisits, "impact": impact,
            "headline": headline, "detail": detail,
        })

    # 반복조업 경로 — 같은 격자를 **다시 찾아온** 순서를 이어, 근사 항적 위에
    # "이 배가 여기를 또 왔다"를 선으로 덧댄다. A축이 무엇을 재는지가 이 선이다.
    # 방문마다 첫 이벤트만 이어서 '돌아온 경로'만 남긴다.
    revisit_paths = [
        {
            "points": [[events[v[0]]["lat"], events[v[0]]["lng"]] for v in visits],
            "count": len(visits),
            "impact": _impact_of(revisit_factor),
            "note": _factor_note(revisit_factor),
        }
        for cell, visits in cell_visits.items()
        if len(visits) > 1 and any(events[i]["fishing"] for v in visits for i in v)
    ]

    # 재방문 격자 — A축이 실제로 쓰는 단위(격자)를 눈에 보이게 한다.
    revisit_cells = []
    for cell, visits in cell_visits.items():
        if len(visits) < 2:
            continue
        cx, cy = cell
        lat_a, lng_a = _to_latlng(cx * cell_size, cy * cell_size)
        lat_b, lng_b = _to_latlng((cx + 1) * cell_size, (cy + 1) * cell_size)
        revisit_cells.append({
            "bounds": [[min(lat_a, lat_b), min(lng_a, lng_b)],
                       [max(lat_a, lat_b), max(lng_a, lng_b)]],
            "count": len(visits),
        })

    center, zoom = _fit_view(events, height)
    payload = {
        "events": events,
        "heatPoints": heat_points,
        "revisitPaths": revisit_paths,
        "revisitCells": revisit_cells,
        "landmarks": _LANDMARKS,
        "center": center,
        "zoom": zoom,
        "fishingColor": MAP_FISHING,
        "mpaColor": MAP_MPA,
        "pathColor": MAP_SAILING,
        "gapColor": MAP_GAP,
        "positiveColor": theme.POSITIVE,
        "axisAColor": theme.AXIS_A,
        "tileUrl": ESRI_WORLD_IMAGERY_URL,
        "attribution": ESRI_ATTRIBUTION,
    }

    components_html(_leaflet_html(payload, height), height=height, scrolling=False)

    if vessel.get("mpaIndex", -1) >= 0:
        st.markdown(
            f'<div class="bs-card" style="border-left:4px solid {theme.NEGATIVE}; '
            f'background:{theme.NEGATIVE_SOFT};">'
            f'<div style="font-weight:700; color:{theme.NEGATIVE}; margin-bottom:3px;">'
            f'해양보호구역 진입 신호</div>'
            f'<div class="bs-note">지도의 빨간 원 지점에서 해양보호구역 태그가 붙은 조업 '
            f'이벤트가 관측됐습니다. 우대 자격 요건에서 감점 요인이며, 관측 기반 추정이므로 '
            f'실제 진입 여부는 확인이 필요합니다. 최신 구역 현황은 '
            f'<a href="https://www.meis.go.kr/mes/marineSanctuary/situation.do" target="_blank">'
            f'해양수산부 해양보호구역 통합정보시스템</a>에서 확인할 수 있습니다.</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="bs-note">GFW는 연속 항적이 아니라 이산 이벤트만 제공해, 이벤트 지점을 '
        '점선으로 이어 근사 경로를 표시합니다. '
        '점에 마우스를 올리면 그 지점이 점수를 올렸는지 내렸는지 함께 표시됩니다.</div>',
        unsafe_allow_html=True,
    )


def _fit_view(events: List[Dict], height: int) -> tuple:
    """항적이 화면에 알맞게 들어오는 중심 좌표와 줌을 계산한다.

    Leaflet의 fitBounds에 맡기지 않는 이유 — iframe 안에서는 지도 컨테이너 크기가
    확정되기 전에 스크립트가 실행될 수 있어 잘못된 줌이 잡힌다.
    """
    lats = [e["lat"] for e in events]
    lngs = [e["lng"] for e in events]
    center = [(max(lats) + min(lats)) / 2, (max(lngs) + min(lngs)) / 2]

    # 항적 주변에 여백을 두고, 웹 메르카토르 기준으로 줌을 역산한다.
    span_lat = max(max(lats) - min(lats), 0.01) * 1.6
    span_lng = max(max(lngs) - min(lngs), 0.01) * 1.4
    cos_lat = math.cos(math.radians(center[0]))

    zoom_by_width = math.log2(360.0 * _ASSUMED_MAP_WIDTH_PX / (256.0 * span_lng))
    zoom_by_height = math.log2(360.0 * height * cos_lat / (256.0 * span_lat))
    zoom = min(zoom_by_width, zoom_by_height)

    # 상한 11 — 그보다 당기면 먼바다라 위성 이미지에 아무것도 안 남아 화면이
    # 검게만 보인다. 이 정도로 두면 독도·울릉도가 시야에 걸려 위치 감각이 생긴다.
    return center, round(max(7.0, min(11.0, zoom)), 2)


def _leaflet_html(payload: Dict, height: int) -> str:
    """Leaflet + Esri World Imagery 위성 지도를 iframe 안에 그린다.

    pydeck을 쓰지 않는 이유 — Streamlit의 deck.gl 컴포넌트는 키 없이는
    Carto/Mapbox 베이스맵이 비어 나온다. Leaflet + Esri는 API 키가 필요 없다.
    iframe으로 격리돼 있어 다른 위젯 재실행에도 지도 상태가 얽히지 않는다.
    """
    data = json.dumps(payload, ensure_ascii=False)
    return f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js"></script>
<style>
  html, body {{ margin:0; padding:0; }}
  /* 범례가 지도 좌하단에 붙도록 기준 컨테이너로 삼는다. */
  #bsmap {{ position:relative; width:100%; height:{height}px; border-radius:8px; background:#0B1B2B; }}
  .geo-label {{
    background:rgba(16,24,40,.78) !important; border:none !important; box-shadow:none !important;
    color:#FFFFFF !important; font-size:11px !important; padding:2px 6px !important;
  }}
  .geo-label::before {{ display:none !important; }}
  .leaflet-container {{ font-family:{theme.FONT_SANS}; }}
  .leaflet-control-attribution {{ font-size:9.5px; }}
  .bs-heat-layer {{ opacity:0; transition:opacity 1.1s ease-out; }}
  .bs-glow-dot {{
    filter:drop-shadow(0 0 4px var(--dot-color)); transition:filter 0.15s ease-out;
  }}
  .bs-glow-dot-hover {{ filter:drop-shadow(0 0 9px var(--dot-color)) drop-shadow(0 0 3px var(--dot-color)); }}

  /* 점수를 내린 지점은 계속 맥동시켜 지도에서 먼저 눈에 띄게 한다. */
  @keyframes bs-pulse {{
    0%   {{ stroke-opacity:0.95; stroke-width:2; }}
    55%  {{ stroke-opacity:0.25; stroke-width:6; }}
    100% {{ stroke-opacity:0.95; stroke-width:2; }}
  }}
  .bs-pulse {{ animation:bs-pulse 2.1s ease-in-out infinite; }}

  /* 반복조업 경로는 흐르는 점선으로 "다시 왔다"는 움직임을 준다. */
  @keyframes bs-flow {{ to {{ stroke-dashoffset:-100; }} }}
  .bs-revisit-path {{ animation:bs-flow 3.2s linear infinite; }}

  /* 이벤트 점이 순서대로 나타난다 — 항적을 시간순으로 읽게 만든다. */
  .bs-drop {{ opacity:0; animation:bs-fadein .45s ease-out forwards; }}
  @keyframes bs-fadein {{ to {{ opacity:1; }} }}

  /* Leaflet 기본값이 `.leaflet-tooltip {{ white-space:nowrap }}`이라 반드시
     덮어야 한다. max-width만 주면 상자 너비는 잘리는데 글자는 줄바꿈을 못 해
     상자 밖으로 그대로 흘러나온다 — 실제로 조업 툴팁 제목이 그렇게 넘쳤다.
     한국어는 어절 단위로 끊는 keep-all이 자연스럽고, 끊을 자리가 없는 긴
     토큰만 break-word가 받아낸다. */
  .bs-tip {{
    background:rgba(255,255,255,.97) !important; border:none !important;
    border-radius:9px !important; box-shadow:0 4px 14px rgba(16,24,40,.28) !important;
    padding:9px 11px !important;
    color:{theme.INK} !important; font-size:12px !important; line-height:1.6 !important;
    white-space:normal !important; word-break:keep-all; overflow-wrap:break-word;
    width:max-content !important; max-width:260px !important;
  }}
  .bs-tip .bs-tip-badge {{
    display:inline-block; font-size:10.5px; font-weight:700; padding:1px 7px;
    border-radius:999px; margin-bottom:5px;
  }}
  .bs-tip .bs-tip-head {{ font-weight:700; display:block; margin-bottom:3px; }}
  /* 설명 줄도 block이어야 제목 아래로 떨어진다. inline이면 제목 끝에 이어 붙어
     한 줄이 그만큼 길어지고, 배지까지 있는 툴팁에서 특히 지저분해진다. */
  .bs-tip .bs-tip-detail {{ display:block; color:{theme.INK_SOFT}; font-size:11.5px; }}

  .bs-legend {{
    position:absolute; left:10px; bottom:12px; z-index:600;
    background:rgba(16,24,40,.82); color:#fff; border-radius:8px;
    padding:8px 10px; font-size:10.5px; line-height:1.75; pointer-events:none;
  }}
  .bs-legend i {{
    display:inline-block; width:9px; height:9px; border-radius:50%;
    margin-right:5px; vertical-align:middle;
  }}
  .bs-legend .bar {{
    display:inline-block; width:14px; height:0; margin-right:5px; vertical-align:middle;
  }}
</style>
<div id="bsmap"></div>
<script>
const D = {data};
const map = L.map('bsmap', {{ scrollWheelZoom:false, zoomControl:true }})
  .setView(D.center, D.zoom);
L.tileLayer(D.tileUrl, {{ maxZoom:16, minZoom:6, attribution:D.attribution }}).addTo(map);

// GFW의 조업강도 히트맵과 같은 접근 — 동일 구역 반복조업일수록 진하게 빛난다.
// 색은 프로젝트의 축 색 체계(A축=파랑)를 그대로 따른다.
if (D.heatPoints.length) {{
  const heat = L.heatLayer(D.heatPoints, {{
    radius: 34, blur: 26, maxZoom: 12, minOpacity: 0.25,
    gradient: {{ 0.2: '#0B1B2B', 0.45: '#1E3A8A', 0.7: '#1E40AF', 0.85: '#3B82F6', 1.0: '#93C5FD' }}
  }}).addTo(map);
  const heatEl = heat.getContainer ? heat.getContainer() : heat._canvas;
  if (heatEl) {{
    heatEl.classList.add('bs-heat-layer');
    setTimeout(function() {{ heatEl.style.opacity = 1; }}, 120);
  }}
}}

D.landmarks.forEach(function(m) {{
  L.circleMarker([m.lat, m.lng], {{
    radius:4, color:'#FFFFFF', weight:1.5, fillColor:'#EAF6FF', fillOpacity:1
  }}).addTo(map).bindTooltip(m.name, {{
    permanent:true, direction:'top', offset:[0,-6], className:'geo-label'
  }});
}});

// A축이 실제로 쓰는 단위(격자)를 그린다 — 재방문이 잦은 칸일수록 진하다.
D.revisitCells.forEach(function(c) {{
  L.rectangle(c.bounds, {{
    color:D.axisAColor, weight:1, opacity:0.55, dashArray:'3 3',
    fillColor:D.axisAColor, fillOpacity:Math.min(0.30, 0.07 * c.count)
  }}).addTo(map).bindTooltip(
    '<span class="bs-tip-head">이 격자에서 ' + c.count + '번 조업했어요</span>' +
    '<span class="bs-tip-detail">A축(자원 압력)은 같은 격자를 다시 찾는 간격으로 계산합니다. ' +
    '간격이 짧을수록 점수가 내려갑니다.</span>',
    {{ className:'bs-tip', sticky:true }}
  );
}});

// 근사 항적 — 이벤트를 시간순으로 이은 보조선(연속 항적이 아님).
const latlngs = D.events.map(function(e) {{ return [e.lat, e.lng]; }});
L.polyline(latlngs, {{
  color:D.pathColor, weight:2, opacity:0.7, dashArray:'2 6', lineCap:'round'
}}).addTo(map);

// 점수를 올린 요인인지 내린 요인인지는 파이썬이 실제 기여도 부호로 정해 넘긴다.
const BADGE = {{
  down: {{ text:'점수 하락 요인', bg:'#FBE9E9', fg:D.mpaColor }},
  up:   {{ text:'점수 상승 요인', bg:'#E6F4F1', fg:D.positiveColor }},
  warn: {{ text:'관측 품질 주의', bg:'#FDF0DC', fg:'#B45309' }},
  neutral: {{ text:'', bg:'', fg:'' }}
}};

// 반복조업 경로 — 같은 격자를 다시 찾아온 순서대로 덧댄 흐르는 선.
D.revisitPaths.forEach(function(p) {{
  if (p.points.length < 2) return;
  const line = L.polyline(p.points, {{
    color:D.axisAColor, weight:3, opacity:0.9, dashArray:'7 6',
    lineCap:'round', className:'bs-revisit-path'
  }}).addTo(map);
  const pb = BADGE[p.impact] || BADGE.neutral;
  line.bindTooltip(
    (pb.text ? '<span class="bs-tip-badge" style="background:' + pb.bg + '; color:' + pb.fg + ';">' +
      pb.text + '</span>' : '') +
    '<span class="bs-tip-head">같은 구역으로 ' + p.count + '번 돌아온 경로예요</span>' +
    '<span class="bs-tip-detail">A축은 되돌아오는 <b>간격</b>으로 계산합니다. ' +
    (p.note || '') + '</span>',
    {{ className:'bs-tip', sticky:true }}
  );
}});

function tipHtml(e) {{
  const b = BADGE[e.impact] || BADGE.neutral;
  let html = '';
  if (b.text) {{
    html += '<span class="bs-tip-badge" style="background:' + b.bg + '; color:' + b.fg + ';">' +
            b.text + '</span>';
  }}
  html += '<span class="bs-tip-head">' + e.headline + '</span>';
  if (e.detail) html += '<span class="bs-tip-detail">' + e.detail + '</span>';
  html += '<span class="bs-tip-detail" style="display:block; margin-top:4px;">#' + e.seq +
          ' · ' + e.kind + '</span>';
  return html;
}}

D.events.forEach(function(e, i) {{
  // 이벤트를 시간순으로 하나씩 떨어뜨려 항적이 그려지는 것처럼 보이게 한다.
  const delay = Math.min(i * 45, 1400);

  if (e.mpa) {{
    const ring = L.circle([e.lat, e.lng], {{
      radius:900, color:D.mpaColor, weight:2, dashArray:'3 4', fill:false, opacity:0.95,
      className:'bs-pulse'
    }}).addTo(map);
    ring.bindTooltip(tipHtml(e), {{ className:'bs-tip', sticky:true }});
  }}

  let marker;
  if (e.dashed) {{
    marker = L.circleMarker([e.lat, e.lng], {{
      radius:e.radius, color:'#98A2B3', weight:1.6, dashArray:'2 2',
      fillColor:D.gapColor, fillOpacity:0.5
    }});
  }} else {{
    const color = e.fishing ? D.fishingColor : D.pathColor;
    marker = L.circleMarker([e.lat, e.lng], {{
      radius:e.radius, color:'#FFFFFF', weight:1.3, fillColor:color, fillOpacity:1,
      className:'bs-glow-dot'
    }});
  }}
  marker.addTo(map).bindTooltip(tipHtml(e), {{ className:'bs-tip', direction:'top', sticky:true }});
  if (marker._path) {{
    if (!e.dashed) {{
      marker._path.style.setProperty('--dot-color', e.fishing ? D.fishingColor : D.pathColor);
    }}
    marker._path.classList.add('bs-drop');
    marker._path.style.animationDelay = delay + 'ms';
  }}

  // 마우스를 올리면 그 지점만 커지고 발광이 강해져서, 어느 점을 읽고 있는지
  // 헷갈리지 않는다.
  marker.on('mouseover', function() {{
    marker.setRadius(e.radius + 3);
    if (marker._path) marker._path.classList.add('bs-glow-dot-hover');
  }});
  marker.on('mouseout', function() {{
    marker.setRadius(e.radius);
    if (marker._path) marker._path.classList.remove('bs-glow-dot-hover');
  }});

  if (e.home) {{
    L.circleMarker([e.lat, e.lng], {{ radius:0, opacity:0 }}).addTo(map)
      .bindTooltip('모항', {{ permanent:true, direction:'right', offset:[8,0], className:'geo-label' }});
  }}
}});

// 툴팁을 지도 안쪽으로 물린다.
//
// Leaflet은 툴팁을 가리키는 지점 기준으로만 놓고 컨테이너 경계는 보지 않는다.
// 어업인 화면은 2단 레이아웃이라 지도 폭이 500px도 안 되는데, 가장자리 지점에
// 마우스를 올리면 툴팁이 밖으로 나가 `.leaflet-container{{overflow:hidden}}`에
// 잘려 글자가 반쯤 사라진다.
//
// sticky 툴팁은 마우스를 따라다니므로 tooltipopen 한 번으로는 부족하다.
// 매번 marginLeft를 0으로 되돌리고 다시 재서, 이전 보정이 누적되지 않게 한다.
function clampTooltips() {{
  const box = map.getContainer().getBoundingClientRect();
  const pad = 8;
  document.querySelectorAll('.leaflet-tooltip-pane .bs-tip').forEach(function(el) {{
    el.style.marginLeft = '0px';
    const tip = el.getBoundingClientRect();
    let shift = 0;
    if (tip.left < box.left + pad) {{
      shift = (box.left + pad) - tip.left;
    }} else if (tip.right > box.right - pad) {{
      shift = (box.right - pad) - tip.right;
    }}
    if (shift) {{ el.style.marginLeft = shift + 'px'; }}
  }});
}}
map.on('tooltipopen', clampTooltips);
map.on('mousemove', clampTooltips);

// 범례 — 색과 선이 무엇을 뜻하는지 지도 안에서 바로 확인한다.
const legend = L.DomUtil.create('div', 'bs-legend');
legend.innerHTML =
  '<div><i style="background:' + D.fishingColor + ';"></i>조업 이벤트</div>' +
  '<div><i style="background:' + D.pathColor + ';"></i>항해 이벤트</div>' +
  '<div><i style="background:' + D.gapColor + '; border:1px dashed #98A2B3;"></i>신호두절</div>' +
  '<div><span class="bar" style="border-top:3px dashed ' + D.axisAColor + ';"></span>반복조업 경로</div>' +
  '<div><span class="bar" style="border-top:2px dashed ' + D.mpaColor + ';"></span>해양보호구역</div>';
document.getElementById('bsmap').appendChild(legend);

// 중심·줌은 파이썬에서 계산해 넘겨받았다. 여기서는 컨테이너 크기가 확정된 뒤
// 타일이 빈칸으로 남지 않도록 크기만 다시 잡아 준다.
setTimeout(function() {{ map.invalidateSize(); }}, 80);
window.addEventListener('load', function() {{ map.invalidateSize(); }});
</script>
"""


def axis_breakdown(vessel: Dict, simulation: Optional[adapter.Simulation] = None) -> None:
    """
    A축·B축 분해. 시뮬레이션이 주어지면 변화 후 값을 함께 그린다.

    점수 숫자와 막대는 JS로 애니메이션한다(0→점수 카운트업, 0→길이 채움) —
    `animated_stat_cards`와 같은 이유로 components.v1.html을 쓴다.
    """
    dataset = adapter.load_dataset()
    weights = dataset["axisWeights"]
    peer = vessel["peerGroup"]

    def _peer_average(key: str) -> Optional[float]:
        values = peer.get(key)
        return sum(values) / len(values) if values else None

    rows = [
        ("A. 자원 압력", "a", vessel["axisA"], weights["a"],
         "자원에 회복 여지를 남겼는가 — 동일 격자 재방문 간격, 혼잡 어장 회피",
         simulation.axis_a if simulation else None, _peer_average("axisAScores")),
        ("B. 운항 효율", "b", vessel["axisB"], weights["b"],
         "같은 조업을 덜 태우며 했는가 — 유사 선박군 기준선 대비 연료 소비 차이",
         simulation.axis_b if simulation else None, _peer_average("axisBScores")),
    ]

    row_blocks = []
    for name, axis, data, weight, desc, after, peer_avg in rows:
        color = theme.axis_color(axis)
        after_html = ""
        if after is not None and abs(after - data["score"]) >= 0.05:
            delta = after - data["score"]
            after_html = (
                f'<span style="font-size:14px; color:{theme.direction_color(delta)}; '
                f'font-weight:700; margin-left:8px;">→ {after:g} ({theme.signed(delta)})</span>'
            )
        marker_html = ""
        if peer_avg is not None:
            marker_html = f'<div class="bs-mini-marker" style="left:{peer_avg:.1f}%;"></div>'

        row_blocks.append(
            f"""<div class="bs-mini-card" style="margin-bottom:12px;">
  <div style="display:flex; align-items:baseline; gap:10px; margin-bottom:8px;">
    <span style="font-size:15px; font-weight:700; color:{theme.INK};">{name}</span>
    <span style="font-size:11px; color:{theme.INK_SOFT}; border:1px solid {theme.LINE};
      border-radius:5px; padding:2px 7px;">가중치 {int(weight * 100)}%</span>
    <span class="bs-mini-value" style="margin-left:auto; font-size:20px; font-weight:800;
      color:{theme.INK};" data-count="{data['score']}" data-decimals="1">0</span>
    <span style="font-size:12px; color:{theme.INK_SOFT}; font-weight:600;">
      {theme.top_percent_text(data['topPercent'])}</span>{after_html}
  </div>
  <div class="bs-mini-track">
    <div class="bs-mini-fill" style="background:{color};" data-fill="{data['score']}"></div>
    {marker_html}
  </div>
  <div style="font-size:12px; color:{theme.INK_SOFT}; line-height:1.65; margin-top:8px;">{desc}
    {f'· 유사 선박군 평균 {peer_avg:.1f}' if peer_avg is not None else ''}</div>
</div>"""
        )

    html = f"{_MINI_CARD_CSS}{''.join(row_blocks)}<script>{_COUNT_UP_JS}</script>"
    components_html(html, height=210 * len(rows), scrolling=False)

    st.markdown(
        f'<div class="bs-card"><span class="bs-mono" style="font-size:14px; '
        f'color:{theme.INK_SOFT};">{adapter.formula_text(vessel["axisA"]["score"], vessel["axisB"]["score"], vessel["blueScore"])}</span>'
        f'<div class="bs-note" style="margin-top:8px;">축 간 비중은 검증 전 잠정치이며, '
        f'은행이 상품 설계에 따라 조정하는 정책 파라미터입니다.</div></div>',
        unsafe_allow_html=True,
    )


def peer_distribution(
    vessel: Dict, simulated_score: Optional[float] = None, height: int = 230
) -> None:
    """
    유사 선박군의 실제 점수 분포 위에 이 배의 위치를 표시한다.

    발표 목업은 난수로 점을 뿌려서 리렌더할 때마다 분포가 바뀌었다. 여기서는
    peerGroup.scores 실제 배열을 그린다.
    """
    peer = vessel["peerGroup"]
    scores = peer["scores"]
    if not scores:
        return

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=scores,
            nbinsx=max(8, min(16, len(scores) // 3)),
            marker=dict(color=theme.LINE, line=dict(color="#FFFFFF", width=1)),
            hovertemplate="%{x:.0f}점 구간 · %{y}척<extra></extra>",
        )
    )
    fig.add_vline(
        x=vessel["blueScore"],
        line=dict(color=theme.AXIS_A, width=3),
        annotation_text=f"이 배 {vessel['blueScore']}",
        annotation_position="top",
        annotation_font=dict(color=theme.AXIS_A, size=12),
    )
    if simulated_score is not None and abs(simulated_score - vessel["blueScore"]) >= 0.05:
        fig.add_vline(
            x=simulated_score,
            line=dict(color=theme.POSITIVE, width=3, dash="dot"),
            annotation_text=f"개선 시 {simulated_score}",
            annotation_position="bottom",
            annotation_font=dict(color=theme.POSITIVE, size=12),
        )

    # 막대가 플롯 경계에서 잘려 보이지 않도록, 실제 값 범위에 5% 여백을 둔다.
    lo, hi = min(scores + [vessel["blueScore"]]), max(scores + [vessel["blueScore"]])
    pad = max((hi - lo) * 0.05, 1.0)
    fig.update_xaxes(
        title_text="BlueScore", range=[lo - pad, hi + pad], gridcolor=theme.LINE, zeroline=False
    )
    fig.update_yaxes(title_text="척수", gridcolor=theme.LINE, zeroline=False)
    # vline 주석("이 배 72.6" 등)은 플롯 영역 위/아래로 튀어나오는데, 기존 공용
    # 여백(t=8, b=8)이 너무 좁아 글자가 잘렸다. 이 차트만 위아래 여백을 넉넉히 준다.
    _chart(fig, height, margin=dict(l=8, r=8, t=34, b=30))
    st.markdown(
        f'<div class="bs-note">유사 선박군 {peer["count"]}척의 실제 점수 분포입니다. '
        f'표본이 작아 순위에는 폭이 있습니다 — {theme.interval_text(peer["topPercentInterval"])}.</div>',
        unsafe_allow_html=True,
    )


# 시뮬레이터 iframe 템플릿. f-string을 쓰지 않는다 — CSS·JS 중괄호를 전부
# 이중으로 escape 해야 해서 읽을 수 없게 된다. 대신 __SURFACE__ 등을 치환한다.
_SIMULATOR_HTML = """
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0; background: transparent;
    font-family: var(--font-sans); color: var(--ink);
  }
  .wrap { display: grid; grid-template-columns: 1.25fr 1fr; gap: 14px; }
  @media (max-width: 820px) { .wrap { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 12px; padding: 14px 16px; margin-bottom: 12px;
  }
  .label { font-size: 12px; color: var(--ink-soft); margin-bottom: 4px; }
  .h5 { font-size: 14px; font-weight: 700; margin: 0 0 8px; }
  .note { font-size: 12px; color: var(--ink-soft); line-height: 1.65; }
  .mono { font-family: var(--font-mono); }

  .slider-row { margin-bottom: 14px; }
  .slider-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 2px;
  }
  .slider-head b { font-size: 13px; font-weight: 600; }
  .slider-val {
    font-family: var(--font-mono); font-weight: 700; font-size: 15px; color: var(--axis-a);
  }
  input[type=range] {
    -webkit-appearance: none; appearance: none; width: 100%; height: 22px;
    background: transparent; cursor: pointer; margin: 0;
  }
  input[type=range]::-webkit-slider-runnable-track {
    height: 5px; border-radius: 3px; background: var(--track);
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 17px; height: 17px;
    border-radius: 50%; background: var(--axis-a); border: 2px solid #fff;
    box-shadow: 0 1px 4px rgba(16,24,40,.35); margin-top: -6px;
  }
  .ticks {
    display: flex; justify-content: space-between;
    font-size: 11px; color: var(--ink-soft); font-family: var(--font-mono);
  }

  .big {
    font-family: var(--font-mono); font-weight: 700; font-size: 30px; line-height: 1.15;
  }
  .from { font-size: 17px; color: var(--ink-soft); font-family: var(--font-mono); }
  .arrow { color: var(--ink-soft); margin: 0 6px; }

  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .stat { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 10px 11px; }
  .stat .v { font-family: var(--font-mono); font-weight: 700; font-size: 17px; }
  .stat .u { font-size: 11px; color: var(--ink-soft); font-weight: 500; margin-left: 2px; }

  .grade-row {
    display: grid; grid-template-columns: 26px 1fr auto auto; gap: 9px;
    align-items: center; padding: 7px 9px; border-radius: 6px; font-size: 13px;
  }
  .grade-row.cur { background: var(--bg); }
  .pill {
    font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
    background: #EEF2FF; color: #3538CD; font-weight: 600; white-space: nowrap;
  }
  .pill.up { background: var(--positive-soft); color: var(--positive); }
  .tnote { font-size: 12.5px; line-height: 1.7; }
  svg { display: block; width: 100%; }
  .fade { animation: fadein .45s ease-out; }
  @keyframes fadein { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
</style>

<div class="wrap fade">
  <div>
    <div class="card">
      <div class="h5">조업 방식을 바꿔 보세요</div>

      <div class="slider-row">
        <div class="slider-head">
          <b>같은 어장 연속 조업</b><span class="slider-val"><span id="rv">3</span> 회</span>
        </div>
        <input type="range" id="revisit">
        <div class="ticks"><span id="rvmin"></span><span id="rvmax"></span></div>
      </div>

      <div class="slider-row">
        <div class="slider-head">
          <b>평균 항해 속도</b><span class="slider-val"><span id="sp">10.4</span> 노트</span>
        </div>
        <input type="range" id="speed">
        <div class="ticks"><span id="spmin"></span><span id="spmax"></span></div>
      </div>

      <div class="note">
        줄일수록 자원에 회복 여지가 생기고(연속 조업), 낮출수록 연료를 덜 씁니다(속도).
      </div>
    </div>

    <div class="card">
      <div class="h5">속도에 따른 점수 곡선</div>
      <svg id="curve" viewBox="0 0 520 190" preserveAspectRatio="none" height="190"></svg>
      <div class="note" id="curvenote"></div>
    </div>

    <div class="card" id="tradeoff" style="border-left:4px solid var(--axis-b);">
      <div class="label">바꾸면 따라오는 대가</div>
      <div id="tnotes"></div>
      <div class="note" style="margin-top:8px;">
        한쪽을 좋게 하면 다른 쪽이 조금 깎입니다. 두 슬라이더를 끝까지 미는 것이 항상 최선은 아닙니다.
      </div>
    </div>

    <div class="card">
      <div style="font-size:13px; font-weight:700; margin-bottom:6px;">
        금리 구간표 <span style="font-weight:400; color:var(--ink-soft); font-size:11.5px;">· 은행 사전 승인</span>
      </div>
      <div id="grades"></div>
    </div>
  </div>

  <div>
    <div class="h5">예상 결과</div>

    <div class="card">
      <div class="label">예상 BlueScore</div>
      <div style="display:flex; align-items:baseline;">
        <span class="from" id="basescore"></span><span class="arrow">→</span>
        <span class="big" id="score"></span>
      </div>
      <div class="note" style="margin-top:6px;" id="scorenote"></div>
    </div>

    <div class="card">
      <div class="label">예상 우대 구간</div>
      <div style="display:flex; align-items:baseline;">
        <span class="from" id="baseband"></span><span class="arrow">→</span>
        <span style="font-size:21px; font-weight:800;" id="band"></span>
      </div>
      <div class="note" style="margin-top:6px;" id="bandnote"></div>
    </div>

    <div class="note" style="margin-bottom:6px;" id="principal"></div>
    <div class="stats">
      <div class="stat">
        <div class="label">연간 절감</div>
        <div><span class="v" id="yearly" style="color:var(--positive);">0</span><span class="u">만원</span></div>
      </div>
      <div class="stat">
        <div class="label">만기까지</div>
        <div><span class="v" id="total" style="color:var(--positive);">0</span><span class="u">만원</span></div>
      </div>
      <div class="stat">
        <div class="label">기대 대비 연료</div>
        <div><span class="v" id="fuel">0</span><span class="u">%</span></div>
      </div>
    </div>

    <div class="card" style="margin-top:12px;">
      <div class="h5">비슷한 배들 사이에서</div>
      <svg id="peer" viewBox="0 0 400 150" preserveAspectRatio="none" height="150"></svg>
      <div class="note" id="peernote"></div>
    </div>

    <div class="h5" style="margin-top:16px;">추천 개선 조합</div>
    <div id="plans"></div>
  </div>
</div>

<script>
(function () {
  var S = __SURFACE__;
  var T = __TOKENS__;

  var root = document.documentElement.style;
  root.setProperty('--font-sans', T.fontSans);
  root.setProperty('--font-mono', T.fontMono);
  root.setProperty('--ink', T.ink);
  root.setProperty('--ink-soft', T.inkSoft);
  root.setProperty('--surface', T.surface);
  root.setProperty('--line', T.line);
  root.setProperty('--bg', T.bg);
  root.setProperty('--axis-a', T.axisA);
  root.setProperty('--axis-b', T.axisB);
  root.setProperty('--positive', T.positive);
  root.setProperty('--positive-soft', T.positiveSoft);
  root.setProperty('--track', T.line);

  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n, d) { return n.toFixed(d === undefined ? 1 : d); };
  var signed = function (n, d) { return (n >= 0 ? '+' : '') + fmt(n, d); };
  var man = function (won) { return Math.round(won / 10000); };

  // ── 상태 ────────────────────────────────────────────────────────────────
  var iRevisit = S.revisits.indexOf(S.base.revisit);
  var iSpeed = 0, best = 1e9;
  S.speeds.forEach(function (v, i) {
    var d = Math.abs(v - S.base.speed);
    if (d < best) { best = d; iSpeed = i; }
  });

  function cell() {
    return S.grid[S.revisits[iRevisit] + '|' + S.speeds[iSpeed].toFixed(1)];
  }

  // ── 숫자 트윈 ───────────────────────────────────────────────────────────
  // 0부터 다시 세지 않고 "지금 보이는 값"에서 목표로 이어 달린다. 드래그
  // 중에도 숫자가 끊기지 않고 따라온다.
  var shown = {};
  function tween(id, target, decimals, opts) {
    opts = opts || {};
    var el = $(id);
    if (shown[id] === undefined) shown[id] = opts.from !== undefined ? opts.from : target;
    var from = shown[id];
    if (Math.abs(from - target) < 1e-9) {
      el.textContent = (opts.sign ? signed(target, decimals) : fmt(target, decimals));
      return;
    }
    var dur = opts.duration || 240, t0 = null;
    if (el.__raf) cancelAnimationFrame(el.__raf);
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min((ts - t0) / dur, 1);
      var e = 1 - Math.pow(1 - p, 3);
      var v = from + (target - from) * e;
      shown[id] = v;
      el.textContent = opts.sign ? signed(v, decimals) : fmt(v, decimals);
      if (p < 1) el.__raf = requestAnimationFrame(step); else shown[id] = target;
    }
    el.__raf = requestAnimationFrame(step);
  }

  // ── 점수 곡선 ───────────────────────────────────────────────────────────
  function drawCurve() {
    var W = 520, H = 190, PL = 34, PR = 10, PT = 14, PB = 26;
    var rv = S.revisits[iRevisit];
    var pts = S.speeds.map(function (sp) { return S.grid[rv + '|' + sp.toFixed(1)].score; });
    var raw = S.speeds.map(function (sp) { return S.grid[rv + '|' + sp.toFixed(1)].scoreNoTradeoff; });
    var all = pts.concat(raw);
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = Math.max((hi - lo) * 0.15, 0.5);
    lo -= pad; hi += pad;
    var x = function (i) { return PL + i / (pts.length - 1) * (W - PL - PR); };
    var y = function (v) { return PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB); };

    var optIdx = 0;
    pts.forEach(function (v, i) { if (v > pts[optIdx]) optIdx = i; });

    var d = pts.map(function (v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); }).join(' ');
    var area = d + ' L' + x(pts.length - 1).toFixed(1) + ' ' + (H - PB) + ' L' + PL + ' ' + (H - PB) + ' Z';

    var g = '';
    // y축 눈금 (최저·최고)
    [lo + pad, hi - pad].forEach(function (v) {
      g += '<line x1="' + PL + '" y1="' + y(v).toFixed(1) + '" x2="' + (W - PR) + '" y2="' + y(v).toFixed(1) +
           '" stroke="' + T.line + '" stroke-width="1"/>';
      g += '<text x="' + (PL - 6) + '" y="' + (y(v) + 3.5).toFixed(1) + '" text-anchor="end" font-size="10" ' +
           'font-family="' + T.fontMono + '" fill="' + T.inkSoft + '">' + v.toFixed(0) + '</text>';
    });
    g += '<path d="' + area + '" fill="' + T.axisA + '" opacity="0.07"/>';

    // 반작용을 뺐을 때의 곡선(점선). 실선과의 간격이 곧 "대가"다.
    var dRaw = raw.map(function (v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); }).join(' ');
    g += '<path d="' + dRaw + '" fill="none" stroke="' + T.axisB + '" stroke-width="1.6" ' +
         'stroke-dasharray="5 4" opacity="0.85"/>';
    g += '<path d="' + d + '" fill="none" stroke="' + T.axisA + '" stroke-width="2.2" stroke-linejoin="round"/>';

    // 두 곡선의 간격을 현재 위치에서 세로선으로 강조
    if (Math.abs(raw[iSpeed] - pts[iSpeed]) > 0.05) {
      g += '<line x1="' + x(iSpeed).toFixed(1) + '" y1="' + y(pts[iSpeed]).toFixed(1) + '" x2="' +
           x(iSpeed).toFixed(1) + '" y2="' + y(raw[iSpeed]).toFixed(1) + '" stroke="' + T.axisB +
           '" stroke-width="4" opacity="0.28" stroke-linecap="round"/>';
    }

    // 최적점
    g += '<circle cx="' + x(optIdx).toFixed(1) + '" cy="' + y(pts[optIdx]).toFixed(1) + '" r="6" fill="none" ' +
         'stroke="' + T.positive + '" stroke-width="2"/>';
    g += '<text x="' + x(optIdx).toFixed(1) + '" y="' + (y(pts[optIdx]) - 11).toFixed(1) + '" text-anchor="' +
         (optIdx === 0 ? 'start' : (optIdx === pts.length - 1 ? 'end' : 'middle')) + '" ' +
         'font-size="10.5" font-weight="700" fill="' + T.positive + '">최적 ' + S.speeds[optIdx].toFixed(1) + 'kn</text>';

    // 범례
    g += '<text x="' + (W - PR) + '" y="' + (PT - 2) + '" text-anchor="end" font-size="10" fill="' + T.axisB +
         '">┄ 반작용을 빼면</text>';

    // 현재 위치
    g += '<line x1="' + x(iSpeed).toFixed(1) + '" y1="' + PT + '" x2="' + x(iSpeed).toFixed(1) + '" y2="' + (H - PB) +
         '" stroke="' + T.axisA + '" stroke-width="1" stroke-dasharray="3 3" opacity="0.55"/>';
    g += '<circle cx="' + x(iSpeed).toFixed(1) + '" cy="' + y(pts[iSpeed]).toFixed(1) + '" r="5" fill="' + T.axisA + '" ' +
         'stroke="#fff" stroke-width="2"/>';

    // x축 라벨
    [0, pts.length - 1].forEach(function (i) {
      g += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (i ? 'end' : 'start') +
           '" font-size="10" font-family="' + T.fontMono + '" fill="' + T.inkSoft + '">' +
           S.speeds[i].toFixed(1) + 'kn</text>';
    });

    $('curve').innerHTML = g;

    // 문구는 실선과 점선의 간격(= 반작용이 깎아간 몫)을 말한다. 곡선이 어디서
    // 꺾이는지는 계수에 달린 문제라 단정하지 않는다 — 현재 잠정 계수에서는
    // 최적점이 구간 끝에 놓인다(adapter.simulate 주석 참고).
    var cost = raw[iSpeed] - pts[iSpeed];
    var gap = raw[optIdx] - pts[optIdx];
    var atEdge = (optIdx === 0 || optIdx === pts.length - 1);
    var head = optIdx === iSpeed
      ? '지금이 이 구간의 <b>최고점</b>입니다. '
      : '최고점은 <b>' + S.speeds[optIdx].toFixed(1) + '노트</b>(' + pts[optIdx].toFixed(1) + '점)이고, ' +
        '지금은 거기서 ' + Math.abs(pts[iSpeed] - pts[optIdx]).toFixed(1) + '점 낮습니다. ';
    var tail = cost > 0.05
      ? '점선은 축 사이 반작용을 빼고 계산한 곡선입니다 — 지금 위치에서 <b>' + cost.toFixed(1) +
        '점</b>이 그 대가로 깎였습니다.'
      : '점선은 축 사이 반작용을 빼고 계산한 곡선입니다.';
    var edge = atEdge
      ? ' <b>현재 잠정 계수에서는 최적점이 구간 끝에 있습니다</b> — 반작용이 이득을 줄이기만 하고 ' +
        '뒤집지는 못하기 때문입니다(끝에서 ' + gap.toFixed(1) + '점 상실). 계수가 확정되면 달라질 수 있습니다.'
      : '';
    $('curvenote').innerHTML = head + tail + edge;
  }

  // ── 유사군 분포 ─────────────────────────────────────────────────────────
  function drawPeer(simScore) {
    var W = 400, H = 150, PL = 6, PR = 6, PT = 20, PB = 22;
    var sc = S.peerScores;
    if (!sc || !sc.length) { $('peer').innerHTML = ''; return; }
    var lo = Math.min.apply(null, sc.concat([S.base.score, simScore]));
    var hi = Math.max.apply(null, sc.concat([S.base.score, simScore]));
    var pad = Math.max((hi - lo) * 0.06, 1);
    lo -= pad; hi += pad;
    var nb = Math.max(8, Math.min(16, Math.floor(sc.length / 3)));
    var bins = new Array(nb).fill(0);
    sc.forEach(function (v) {
      var i = Math.min(nb - 1, Math.floor((v - lo) / (hi - lo) * nb));
      bins[i]++;
    });
    var top = Math.max.apply(null, bins);
    var bw = (W - PL - PR) / nb;
    var g = '';
    bins.forEach(function (n, i) {
      var h = n / top * (H - PT - PB);
      g += '<rect x="' + (PL + i * bw + 0.8).toFixed(1) + '" y="' + (H - PB - h).toFixed(1) +
           '" width="' + (bw - 1.6).toFixed(1) + '" height="' + h.toFixed(1) + '" fill="' + T.line + '"/>';
    });
    var xs = function (v) { return PL + (v - lo) / (hi - lo) * (W - PL - PR); };
    g += '<line x1="' + xs(S.base.score).toFixed(1) + '" y1="' + PT + '" x2="' + xs(S.base.score).toFixed(1) +
         '" y2="' + (H - PB) + '" stroke="' + T.axisA + '" stroke-width="2.5"/>';
    g += '<text x="' + xs(S.base.score).toFixed(1) + '" y="' + (PT - 6) + '" text-anchor="middle" font-size="10.5" ' +
         'fill="' + T.axisA + '" font-weight="700">지금 ' + S.base.score.toFixed(1) + '</text>';
    if (Math.abs(simScore - S.base.score) >= 0.05) {
      g += '<line x1="' + xs(simScore).toFixed(1) + '" y1="' + PT + '" x2="' + xs(simScore).toFixed(1) +
           '" y2="' + (H - PB) + '" stroke="' + T.positive + '" stroke-width="2.5" stroke-dasharray="4 3"/>';
      g += '<text x="' + xs(simScore).toFixed(1) + '" y="' + (H - 7) + '" text-anchor="middle" font-size="10.5" ' +
           'fill="' + T.positive + '" font-weight="700">개선 시 ' + simScore.toFixed(1) + '</text>';
    }
    $('peer').innerHTML = g;
  }

  // ── 추천 개선 조합 카드 ─────────────────────────────────────────────────
  // 슬라이더와 무관하게 선박당 고정이라 한 번만 그린다. 점수·구간은 파이썬이
  // 계산했고, tip 문장만 explain/(LLM 또는 폴백)이 만든 것이다.
  function drawPlans() {
    var el = $('plans');
    if (!el || !S.plans || !S.plans.length) return;
    el.innerHTML = S.plans.map(function (p) {
      var up = p.scoreDelta >= 0;
      var arrowColor = up ? T.positive : T.negative;
      var bandHtml = p.bandChanged
        ? p.beforeBand + ' <span style="color:' + T.inkSoft + ';">→</span> <b style="color:' +
          T.positive + ';">' + p.afterBand + '</b>'
        : p.beforeBand + ' <span style="color:' + T.inkSoft + ';">→</span> <b>' + p.afterBand + '</b>';
      var src = p.tipSource && p.tipSource.indexOf('llm:') === 0 ? 'AI 생성' : '기본 안내문';
      return '<div class="card" style="margin-bottom:10px;">' +
        '<div class="label">' + p.title + '</div>' +
        '<div class="note" style="margin:-2px 0 8px;">' + p.desc + '</div>' +
        '<div style="display:flex; align-items:baseline; gap:7px;">' +
          '<span class="from">' + p.baseScore.toFixed(1) + '</span>' +
          '<span class="arrow">→</span>' +
          '<span class="mono" style="font-size:24px; font-weight:700; color:' + arrowColor + ';">' +
            p.score.toFixed(1) + '</span>' +
        '</div>' +
        '<div class="note" style="margin-top:5px;">' + bandHtml + '</div>' +
        '<div style="margin-top:9px; padding-top:9px; border-top:1px solid ' + T.line + ';">' +
          '<div class="tnote">' + p.tip + '</div>' +
          '<div class="note" style="margin-top:5px; font-size:11px;">개선팁 · ' + src + '</div>' +
        '</div></div>';
    }).join('');
  }

  // ── 금리 구간표 ─────────────────────────────────────────────────────────
  function drawGrades(c) {
    $('grades').innerHTML = S.rateGrades.map(function (b) {
      var tags = '';
      if (b.grade === S.base.grade) tags += '<span class="pill">현재</span> ';
      if (b.grade === c.grade && c.grade !== S.base.grade) tags += '<span class="pill up">개선 시</span>';
      var bp = b.discountBp <= 0 ? '우대 없음' : '−' + b.discountBp + ' bp';
      return '<div class="grade-row' + (b.grade === S.base.grade ? ' cur' : '') + '">' +
             '<span style="font-weight:800;">' + b.grade + '</span>' +
             '<span style="color:' + T.inkSoft + '; font-size:12.5px;">' + b.label + '</span>' +
             '<span>' + tags + '</span>' +
             '<span class="mono" style="font-size:12.5px;">' + bp + '</span></div>';
    }).join('');
  }

  // ── 렌더 ────────────────────────────────────────────────────────────────
  function render(first) {
    var c = cell();
    $('rv').textContent = S.revisits[iRevisit];
    $('sp').textContent = S.speeds[iSpeed].toFixed(1);

    var d = first ? 900 : 240;
    tween('score', c.score, 1, { from: first ? S.base.score : undefined, duration: d });
    tween('yearly', man(c.yearlyWon), 0, { duration: d });
    tween('total', man(c.totalWon), 0, { duration: d });
    tween('fuel', c.fuelDeltaPercent, 1, { sign: true, duration: d });

    $('score').style.color = c.scoreDelta >= 0 ? T.positive : T.negative;
    $('fuel').style.color = c.fuelDeltaPercent <= 0 ? T.positive : T.negative;
    $('scorenote').innerHTML = '상위 ' + S.base.topPercent + '% → <b>상위 ' + c.topPercent + '%</b> · 점수 ' +
                               signed(c.scoreDelta, 1) + 'p';

    var bandText = c.discountBp <= 0 ? c.grade + ' · 우대 없음' : c.grade + ' · −' + c.discountBp + 'bp';
    $('band').textContent = bandText;
    $('band').style.color = c.grade !== S.base.grade ? T.positive : T.ink;
    $('bandnote').textContent = '최종 여신 승인은 은행 심사역이 수행합니다. 위 구간은 규칙표가 매핑한 제안값입니다.';

    $('tnotes').innerHTML = c.tradeoffNotes.length
      ? c.tradeoffNotes.map(function (n) { return '<div class="tnote">· ' + n + '</div>'; }).join('')
      : '<div class="tnote" style="color:' + T.inkSoft + ';">지금은 기준 조업 방식 그대로입니다.</div>';

    drawGrades(c);
    drawCurve();
    drawPeer(c.score);
  }

  // ── 초기화 ──────────────────────────────────────────────────────────────
  var rvEl = $('revisit'), spEl = $('speed');
  rvEl.min = 0; rvEl.max = S.revisits.length - 1; rvEl.step = 1; rvEl.value = iRevisit;
  spEl.min = 0; spEl.max = S.speeds.length - 1; spEl.step = 1; spEl.value = iSpeed;
  $('rvmin').textContent = S.revisits[0] + '회';
  $('rvmax').textContent = S.revisits[S.revisits.length - 1] + '회';
  $('spmin').textContent = S.speeds[0].toFixed(1) + 'kn';
  $('spmax').textContent = S.speeds[S.speeds.length - 1].toFixed(1) + 'kn';

  $('basescore').textContent = S.base.score.toFixed(1);
  $('baseband').textContent = S.base.discountBp <= 0
    ? S.base.grade + ' · 우대 없음' : S.base.grade + ' · −' + S.base.discountBp + 'bp';
  $('principal').textContent = (S.principalWon / 100000000) + '억 원 · ' + S.termYears + '년 만기 기준 예시';

  rvEl.addEventListener('input', function () { iRevisit = +rvEl.value; render(false); });
  spEl.addEventListener('input', function () { iSpeed = +spEl.value; render(false); });

  drawPlans();
  render(true);

  // ── 높이 맞추기 ─────────────────────────────────────────────────────────
  // components.v1.html은 높이를 고정으로 받기 때문에, 폭이 좁아 2단이 1단으로
  // 접히면 내용이 잘린다(실측: 데스크톱에서도 104px 넘침). srcdoc iframe은
  // 부모와 동일 출처라 자기 높이를 직접 고칠 수 있다. 실패해도 파이썬이 넘긴
  // 기본 높이로 그대로 돌아가도록 조용히 넘어간다.
  function fitHeight() {
    try {
      var el = window.frameElement;
      if (!el) return;
      var h = document.body.scrollHeight;
      if (!h || Math.abs(el.getBoundingClientRect().height - h) < 2) return;
      el.style.height = h + 'px';
      el.height = h;
      // Streamlit은 파이썬이 넘긴 높이를 iframe 바깥 stElementContainer에도
      // 그대로 물린다. 여기를 같이 늘리지 않으면 iframe만 커져서 컨테이너를
      // 삐져나오고, 뒤따르는 요소와 겹친다(모바일 1단 레이아웃에서 실제로 겹쳤다).
      var box = el.parentElement, hops = 0;
      while (box && box !== document.body && hops < 3) {
        if (box.getAttribute('data-testid') === 'stElementContainer') {
          box.style.height = h + 'px';
          break;
        }
        box = box.parentElement; hops++;
      }
    } catch (e) { /* 출처가 갈리면 기본 높이 사용 */ }
  }
  fitHeight();
  window.addEventListener('resize', fitHeight);
  if (window.ResizeObserver) new ResizeObserver(fitHeight).observe(document.body);
})();
</script>
"""


def live_simulator(vessel: Dict, height: int = 880) -> None:
    """개선 시뮬레이터 전체를 iframe 하나에 담아 서버 왕복 없이 돌린다.

    `st.slider`는 움직일 때마다 Python 왕복 + 전체 리렌더가 일어나 카운트업
    애니메이션이 목표값에 도달하지 못하고 계속 0부터 다시 셌다. 대신
    `adapter.simulate_surface()`가 슬라이더 전 구간을 미리 계산해 넘기고
    브라우저는 조회만 한다 — 계산은 여전히 adapter 한 곳에서만 나온다.
    """
    surface = adapter.simulate_surface(vessel)
    # 추천 개선 조합은 슬라이더와 무관하게 선박당 고정이라 표에 함께 실어 보낸다.
    surface["plans"] = adapter.improvement_plans(vessel)
    tokens = {
        "axisA": theme.AXIS_A,
        "axisB": theme.AXIS_B,
        "positive": theme.POSITIVE,
        "positiveSoft": theme.POSITIVE_SOFT,
        "negative": theme.NEGATIVE,
        "bg": theme.BG,
        "surface": theme.SURFACE,
        "line": theme.LINE,
        "ink": theme.INK,
        "inkSoft": theme.INK_SOFT,
        "fontSans": theme.FONT_SANS,
        "fontMono": theme.FONT_MONO,
    }
    html = (
        _SIMULATOR_HTML.replace("__SURFACE__", json.dumps(surface, ensure_ascii=False))
        .replace("__TOKENS__", json.dumps(tokens, ensure_ascii=False))
        .replace("__HEIGHT__", str(height))
    )
    components_html(html, height=height, scrolling=False)


def shap_contributions(vessel: Dict, height: int = 300) -> None:
    """
    요인별 기여도.

    색만으로 방향을 전달하지 않도록 막대 끝에 부호를 붙인다 (색각 대응).
    """
    factors = sorted(vessel["shapFactors"], key=lambda f: f["value"])
    labels = [f["label"] for f in factors]
    values = [f["value"] for f in factors]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=[theme.direction_color(v) for v in values]),
            text=[theme.signed(v, "") for v in values],
            textposition="outside",
            textfont=dict(family=theme.FONT_MONO, size=12),
            hovertemplate="%{y}: %{x:+.1f}<extra></extra>",
        )
    )
    span = max(abs(v) for v in values) * 1.35
    fig.update_xaxes(range=[-span, span], gridcolor=theme.LINE, zeroline=True,
                     zerolinecolor=theme.INK_SOFT, zerolinewidth=1, title_text="점수 기여도")
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    _chart(fig, height)


def trend_chart(vessel: Dict, height: int = 200) -> None:
    """최근 6개월 BlueScore 추이."""
    trend = vessel.get("trend")
    if not trend:
        return
    months = ["3월", "4월", "5월", "6월", "7월", "8월"][-len(trend):]

    fig = go.Figure(
        go.Scatter(
            x=months,
            y=trend,
            mode="lines+markers",
            line=dict(color=theme.AXIS_A, width=2.5),
            marker=dict(size=7, color=theme.AXIS_A),
            fill="tozeroy",
            fillcolor="rgba(30,64,175,0.08)",
            hovertemplate="%{x} · %{y}점<extra></extra>",
        )
    )
    fig.update_yaxes(range=[min(trend) - 5, max(trend) + 5], gridcolor=theme.LINE)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)")
    _chart(fig, height)


def voyage_stats(vessel: Dict) -> None:
    animated_stat_cards(
        [
            {"label": "총 이동거리", "value": vessel["totalDistanceKm"], "unit": "km", "size": 20},
            {"label": "조업 시간", "value": vessel["fishingHours"], "unit": "h", "size": 20},
            {"label": "추정 연료", "value": vessel["estimatedFuelKl"], "unit": "kL",
             "decimals": 1, "size": 20},
            {"label": "출항", "value": vessel["sailCalls"], "unit": "회", "size": 20},
        ]
    )


def eligibility_card(vessel: Dict, note: str = "") -> None:
    """
    자격 요건 카드.

    준법 항목(금어기·보호구역)은 점수 축이 아니라 우대 자격 요건으로만 둔다.

    카드 전체를 st.markdown 한 번으로 그린다 — Streamlit은 markdown 호출마다
    별도 컨테이너를 만들기 때문에, 여는 div와 내용을 나눠 호출하면 빈 상자가
    생기고 내용은 카드 밖으로 빠진다.
    """
    items = vessel.get("eligibility", [])
    if not items:
        return
    pills = "".join(
        f'<span class="bs-pill {"pass" if it["passed"] else "fail"}">'
        f'{"✓" if it["passed"] else "✕"} {it["label"]}</span>'
        for it in items
    )
    note_html = f'<div class="bs-note" style="margin-top:8px;">{note}</div>' if note else ""
    st.markdown(f'<div class="bs-card">{pills}{note_html}</div>', unsafe_allow_html=True)


def rate_table(current_score: float, simulated_score: Optional[float] = None) -> None:
    """은행 사전 승인 규칙표. 현재 구간과 개선 시 구간을 함께 표시한다."""
    dataset = adapter.load_dataset()
    current = theme.grade_band(current_score, dataset["rateGrades"])
    after = (
        theme.grade_band(simulated_score, dataset["rateGrades"])
        if simulated_score is not None
        else None
    )

    rows = []
    for band in dataset["rateGrades"]:
        tags = []
        if band["grade"] == current["grade"]:
            tags.append('<span class="bs-pill info" style="padding:1px 7px;">현재</span>')
        if after and band["grade"] == after["grade"] and after["grade"] != current["grade"]:
            tags.append(
                f'<span class="bs-pill" style="padding:1px 7px; '
                f'background:{theme.POSITIVE_SOFT}; color:{theme.POSITIVE};">개선 시</span>'
            )
        highlight = (
            f"background:{theme.BG};" if band["grade"] == current["grade"] else ""
        )
        bp = "우대 없음" if band["discountBp"] <= 0 else f"−{band['discountBp']} bp"
        rows.append(
            f'<div style="display:grid; grid-template-columns:28px 1fr auto auto; gap:10px;'
            f' align-items:center; padding:9px 10px; border-radius:6px; {highlight}">'
            f'<span style="font-weight:800;">{band["grade"]}</span>'
            f'<span style="color:{theme.INK_SOFT}; font-size:13px;">{band["label"]}</span>'
            f'<span>{"".join(tags)}</span>'
            f'<span class="bs-mono" style="font-size:13px;">{bp}</span></div>'
        )

    st.markdown(
        f'<div class="bs-card"><div style="font-size:13px; font-weight:700; margin-bottom:6px;">'
        f'금리 구간표 <span style="font-weight:400; color:{theme.INK_SOFT}; font-size:11.5px;">'
        f'· 은행 사전 승인</span></div>{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def provenance(compact: bool = False) -> None:
    """데이터 출처와 기준일자."""
    dataset = adapter.load_dataset()
    rows = "".join(
        f'<div>{name} <span class="d">{date}</span></div>'
        for name, date in dataset["dataFreshness"].items()
    )
    title = "" if compact else '<div class="bs-label">데이터 기준일자</div>'
    st.markdown(f'<div class="bs-prov">{title}{rows}</div>', unsafe_allow_html=True)


def explanation_source(explanation: Dict) -> None:
    """
    설명 문구가 LLM 생성인지 템플릿 폴백인지 표시한다.

    산출 경로 표시와 같은 이유다 — 시연 중 무엇이 생성이고 무엇이 대체인지
    숨기지 않는다. `source`는 "llm:openai" 또는 "fallback:<사유>" 형태다.
    """
    source = explanation.get("source", "")
    if not source:
        return

    if source.startswith("llm:"):
        label = f"AI가 생성한 문구입니다 ({source.split(':', 1)[1]})"
        color = theme.POSITIVE
        mark = "●"
    else:
        reason = source.split(":", 1)[1] if ":" in source else source
        label = f"LLM을 사용할 수 없어 기본 문구로 표시했습니다 ({reason})"
        color = theme.AXIS_B
        mark = "○"

    st.markdown(
        f'<div class="bs-note"><span style="color:{color}; font-weight:700;">{mark}</span> '
        f"{label}</div>",
        unsafe_allow_html=True,
    )


# ─── 금융기관(심사역) 화면 전용 ──────────────────────────────────────────────
def section(title: str, note: str = "") -> None:
    """
    섹션 제목. 심사 화면 전체에서 같은 리듬을 만들기 위한 것이다.

    `st.markdown("##### ...")`를 섞어 쓰면 카드마다 제목 크기·여백이 달라져
    항목이 많은 심사 화면이 흩어져 보인다. 제목은 전부 이 함수로 낸다.
    """
    note_html = f'<span class="n">{note}</span>' if note else ""
    st.markdown(f'<div class="bs-sec">{title}{note_html}</div>', unsafe_allow_html=True)


def review_summary_band(vessel: Dict, band: Dict, review: Optional[Dict] = None) -> None:
    """심사 판단에 바로 쓰는 값만 한 줄로 모은 요약 밴드."""
    peer = vessel["peerGroup"]
    passed = sum(1 for item in vessel.get("eligibility", []) if item["passed"])
    total = len(vessel.get("eligibility", []))

    cells = [
        ("BlueScore", f'{vessel["blueScore"]:g}', f'유사군 {peer["count"]}척 중 상위 {peer["topPercent"]}%'),
        ("규칙표 제안 구간", band["grade"], theme.discount_text(band).split("·")[-1].strip()),
        ("A축 자원 압력", f'{vessel["axisA"]["score"]:g}', f'상위 {vessel["axisA"]["topPercent"]}%'),
        ("B축 운항 효율", f'{vessel["axisB"]["score"]:g}', f'상위 {vessel["axisB"]["topPercent"]}%'),
        ("우대 자격 요건", f"{passed}/{total}", "충족" if passed == total else "미충족 항목 있음"),
    ]
    if review:
        decided = "승인" if review["decision"] == "approve" else "보류"
        bp = review.get("finalDiscountBp")
        cells.append(("심사 결정", decided, f"최종 −{bp}bp" if bp is not None else "금리 미확정"))

    html = "".join(
        f'<div class="cell"><div class="k">{k}</div>'
        f'<div class="v">{v}</div><div class="s">{s}</div></div>'
        for k, v, s in cells
    )
    st.markdown(
        f'<div class="bs-band" style="grid-template-columns:repeat({len(cells)}, 1fr);">'
        f'{html}</div>',
        unsafe_allow_html=True,
    )


def rate_gauge(vessel: Dict) -> None:
    """
    현재 점수가 금리 구간 경계에서 얼마나 떨어져 있는지.

    심사역이 실제로 판단하는 것은 "이 배가 몇 점인가"가 아니라 "구간을 넘기는가,
    넘긴다면 얼마나 여유 있게 넘기는가"다. 경계까지의 거리를 점수와 bp로 함께
    보여줘 금리 인하·인상 판단에 바로 쓰이게 한다.
    """
    grades = adapter.load_dataset()["rateGrades"]
    score = vessel["blueScore"]
    ordered = sorted(grades, key=lambda g: g["minScore"])
    current = theme.grade_band(score, grades)

    lo, hi = 40.0, 100.0
    pos = max(0.0, min(1.0, (score - lo) / (hi - lo))) * 100

    segs, ticks = [], []
    for i, g in enumerate(ordered):
        start = max(g["minScore"], lo)
        end = ordered[i + 1]["minScore"] if i + 1 < len(ordered) else hi
        width = max(0.0, (min(end, hi) - start) / (hi - lo) * 100)
        shade = theme.POSITIVE if g["discountBp"] >= 20 else (
            theme.AXIS_A if g["discountBp"] >= 12 else (
                theme.AXIS_B if g["discountBp"] > 0 else theme.LINE))
        segs.append(f'<span style="width:{width}%; background:{shade}; opacity:.75;"></span>')
        if g["minScore"] > lo:
            left = (g["minScore"] - lo) / (hi - lo) * 100
            ticks.append(
                f'<div class="tick" style="left:{left}%;">{g["grade"]} {g["minScore"]:g}</div>'
            )

    upper = [g for g in ordered if g["minScore"] > score]
    if upper:
        nxt = min(upper, key=lambda g: g["minScore"])
        gap = round(nxt["minScore"] - score, 1)
        extra = nxt["discountBp"] - current["discountBp"]
        headroom = (
            f'<b>{nxt["grade"]}구간</b>까지 <b>{gap:g}점</b> 남았습니다 '
            f'(도달 시 추가 <b>−{extra}bp</b>).'
        )
    else:
        headroom = "최상위 구간입니다. 위쪽 경계가 없습니다."

    lower = [g for g in ordered if g["minScore"] <= score]
    floor = max(lower, key=lambda g: g["minScore"])
    cushion = round(score - floor["minScore"], 1)
    drop = current["discountBp"] - (
        max([g for g in ordered if g["minScore"] < floor["minScore"]],
            key=lambda g: g["minScore"])["discountBp"]
        if [g for g in ordered if g["minScore"] < floor["minScore"]] else 0
    )

    # 핀을 왼쪽 끝에서 실제 위치까지 @keyframes로 슬라이드시켜 여유를 체감하게
    # 한다. transition은 초기 렌더에서 중간 상태 없이 최종값을 바로 페인트한다.
    st.markdown(
        f'<div class="bs-card">'
        f'  <style>@keyframes bs-gauge-pin-slide {{ from {{ left:-1px; }} '
        f'  to {{ left:calc({pos}% - 1px); }} }}</style>'
        f'  <div class="bs-gauge">'
        f'    <div class="track">{"".join(segs)}</div>'
        f'    <div class="pin" style="animation:bs-gauge-pin-slide 0.9s '
        f'    cubic-bezier(0.22, 1, 0.36, 1) forwards;"></div>'
        f'    {"".join(ticks)}'
        f'  </div>'
        f'  <div class="bs-note" style="margin-top:16px;">{headroom}<br>'
        f'  현재 구간 하단 경계까지 여유 <b>{cushion:g}점</b> — 이 아래로 내려가면 '
        f'  우대가 <b>{drop}bp</b> 줄어듭니다.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def factor_ledger(vessel: Dict) -> None:
    """
    금리를 내릴 근거 / 올릴 근거를 좌우로 대조한 요인 원장.

    심사역이 알아야 하는 것은 요인 목록이 아니라 **각 요인이 금리 방향에
    어떻게 작용하는가**다. 기여도 부호로 두 열로 갈라 놓으면, 줄글을 읽지 않고도
    "무엇 때문에 깎아줄 수 있고, 무엇 때문에 못 깎아주는가"가 한눈에 잡힌다.
    """
    rows = adapter.detailed_report(vessel).get("rows", [])
    if not rows:
        return

    scored = [r for r in rows if r.get("contribution") is not None]
    ups = sorted([r for r in scored if r["contribution"] > 0],
                 key=lambda r: -r["contribution"])
    downs = sorted([r for r in scored if r["contribution"] < 0],
                   key=lambda r: r["contribution"])
    widest = max([abs(r["contribution"]) for r in scored], default=1.0) or 1.0

    def _rows_html(items: List[Dict], color: str) -> str:
        if not items:
            return '<div class="bs-note">해당 요인이 없습니다.</div>'
        out = []
        for r in items:
            width = min(100.0, abs(r["contribution"]) / widest * 100)
            out.append(
                f'<div class="row">'
                f'  <div class="top">'
                f'    <span class="lab">{r["label"]}</span>'
                f'    <span class="bs-pill info" style="padding:1px 6px; font-size:10px;">'
                f'{r["axis"].upper()}축</span>'
                f'    <span class="amt" style="color:{color};">{theme.signed(r["contribution"], "")}</span>'
                f'  </div>'
                f'  <div class="bar"><i style="width:{width}%; background:{color};"></i></div>'
                f'  <div class="met">내 값 {r["selfValue"]:g}{r["unit"]} · '
                f'유사군 평균 {r["peerAverage"]:g}{r["unit"]}</div>'
                f'  <div class="say">{r["sentence"]}</div>'
                f'</div>'
            )
        return "".join(out)

    up_total = sum(r["contribution"] for r in ups)
    down_total = sum(r["contribution"] for r in downs)

    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown(
            f'<div class="bs-note" style="margin-bottom:7px;">'
            f'<b style="color:{theme.POSITIVE};">금리 인하 근거</b> · 합계 '
            f'<span class="bs-mono">{theme.signed(up_total, "")}</span></div>'
            f'<div class="bs-led">{_rows_html(ups, theme.POSITIVE)}</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f'<div class="bs-note" style="margin-bottom:7px;">'
            f'<b style="color:{theme.NEGATIVE};">금리 인하 제약 요인</b> · 합계 '
            f'<span class="bs-mono">{theme.signed(down_total, "")}</span></div>'
            f'<div class="bs-led">{_rows_html(downs, theme.NEGATIVE)}</div>',
            unsafe_allow_html=True,
        )


def reproducibility_panel(vessel: Dict) -> None:
    """산출 조건·버전·매칭 신뢰도 — 같은 결과를 다시 만들 수 있는지에 필요한 값."""
    dataset = adapter.load_dataset()
    items = [
        ("점수 산출 건", vessel["scoreRunId"]),
        ("데이터 스냅샷", vessel["dataSnapshotId"]),
        ("모델 버전", vessel["modelVersion"]),
        ("산식 버전", vessel["scoringRuleVersion"]),
        ("금리표 버전", vessel["rateTableVersion"]),
        ("산출 경로", vessel["sourceType"]),
    ]
    rows = "".join(
        f'<div style="display:grid; grid-template-columns:110px 1fr; gap:10px; padding:3px 0;">'
        f'<span class="bs-note">{k}</span>'
        f'<span class="bs-mono" style="font-size:11.5px; word-break:break-all;">{v}</span></div>'
        for k, v in items
    )
    freshness = "".join(
        f'<div style="display:grid; grid-template-columns:110px 1fr; gap:10px; padding:3px 0;">'
        f'<span class="bs-note">{name}</span>'
        f'<span class="bs-mono" style="font-size:11.5px;">{day}</span></div>'
        for name, day in dataset["dataFreshness"].items()
    )
    st.markdown(
        f'<div class="bs-card">{rows}'
        f'<div style="border-top:1px solid {theme.LINE}; margin:9px 0 7px;"></div>'
        f'{freshness}</div>',
        unsafe_allow_html=True,
    )


def backend_footer() -> None:
    """
    지금 보고 있는 숫자가 실산출인지 임시값인지 항상 표시한다.

    시연 중에 무엇이 계산이고 무엇이 목업인지 숨기지 않기 위한 것이다.
    """
    backend = adapter.scoring_backend()
    mark = "●" if backend.live else "○"
    color = theme.POSITIVE if backend.live else theme.AXIS_B
    st.markdown(
        f'<div class="bs-note" style="margin-top:24px; border-top:1px solid {theme.LINE}; '
        f'padding-top:12px;"><span style="color:{color}; font-weight:700;">{mark}</span> '
        f'산출 경로: {backend.label} · 연료 계수는 해외 선단 기준 문헌값이며 국내 어선 '
        f'보정은 후속 과제입니다. 점수는 추정치이자 제안입니다.</div>',
        unsafe_allow_html=True,
    )


def blocked_page(vessel: Dict) -> None:
    """점수를 낼 수 없는 선박에서 공통으로 보여줄 화면."""
    score_bar(vessel)
    st.markdown("#### 조업 항적")
    voyage_map(vessel)
    voyage_stats(vessel)
    backend_footer()


def peer_metric_comparison(vessel: Dict, height_per_row: int = 46) -> None:
    """
    점수리포트 탭 — 요인별 실측값을 선박 자신 값 vs 유사군 평균으로 비교한다.

    `shapFactors`(점수 기여도)와 달리 여기 쓰는 `factorMetrics`는 실제 관측값
    (시간·km·노트·% 등 단위가 있는 값)이라, "왜 그런 기여도가 나왔는지"를
    한 단계 더 구체적으로 보여준다.
    """
    metrics = vessel.get("factorMetrics", [])
    if not metrics:
        return

    fig = go.Figure()
    labels = [m["label"] for m in metrics]
    fig.add_trace(
        go.Bar(
            name="유사 선박군 평균",
            x=[m["peerAverage"] for m in metrics],
            y=labels,
            orientation="h",
            marker=dict(color=theme.LINE),
            hovertemplate="유사군 평균 %{x:g}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="이 선박",
            x=[m["selfValue"] for m in metrics],
            y=labels,
            orientation="h",
            marker=dict(color=[theme.axis_color(m["axis"]) for m in metrics]),
            hovertemplate="이 선박 %{x:g}<extra></extra>",
        )
    )
    fig.update_layout(barmode="group", showlegend=True, legend=dict(orientation="h", y=1.12))
    fig.update_xaxes(gridcolor=theme.LINE, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    _chart(fig, max(220, height_per_row * len(metrics)))
    st.markdown(
        '<div class="bs-note">막대 옆 단위는 요인마다 다릅니다(시간·km·노트·% 등). '
        '값 자체보다 <b>유사 선박군 평균과의 위치</b>를 보는 지표입니다.</div>',
        unsafe_allow_html=True,
    )


def detailed_report(vessel: Dict) -> None:
    """점수리포트 탭 — 요인별 상세 리포트.

    `explain/`이 요인별로 문장을 돌려주므로(요인 라벨이 키다) 요인 하나를
    한 줄로 묶어 그린다 — 실측값·유사군 평균·기여도·설명이 같은 줄에 있다.
    """
    report = adapter.detailed_report(vessel)
    rows = report.get("rows", [])
    if not rows:
        return

    st.markdown("##### 상세 리포트")
    st.markdown(
        '<div class="bs-note">요인 하나가 한 칸입니다. 막대는 유사 선박군 평균 대비 '
        '내 값의 위치이고, 오른쪽 숫자는 그 요인이 점수에 준 영향입니다.</div>',
        unsafe_allow_html=True,
    )

    blocks = []
    for row in rows:
        color = theme.axis_color(row["axis"])
        axis_name = "자원 압력" if row["axis"] == "a" else "운항 효율"

        # 막대 — 유사군 평균을 가운데 기준선으로 두고 내 값의 상대 위치를 그린다.
        peer, mine = row["peerAverage"], row["selfValue"]
        span = max(abs(mine - peer), abs(peer) * 0.35, 1e-6)
        ratio = max(-1.0, min(1.0, (mine - peer) / (span * 2)))
        left = 50 + ratio * 50
        lo, hi = (min(50, left), max(50, left))

        contribution = row.get("contribution")
        if contribution is None:
            contrib_html = '<span style="color:#667085; font-size:12px;">—</span>'
        else:
            contrib_html = (
                f'<span class="bs-mono" style="font-weight:700; font-size:14px; '
                f'color:{theme.direction_color(contribution)};">'
                f'{theme.signed(contribution)}</span>'
            )

        diff_text = (
            f'평균보다 {abs(row["diff"]):g}{row["unit"]} '
            f'{"높음" if row["diff"] > 0 else "낮음" if row["diff"] < 0 else "동일"}'
        )

        blocks.append(
            f'<div class="bs-card" style="padding:13px 15px; margin-bottom:9px; '
            f'border-left:3px solid {color};">'
            f'  <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;">'
            f'    <div><span style="font-weight:700; font-size:13.5px;">{row["label"]}</span>'
            f'    <span class="bs-note" style="margin-left:6px;">{axis_name}</span></div>'
            f'    {contrib_html}'
            f'  </div>'
            f'  <div style="display:flex; align-items:center; gap:9px; margin:9px 0 5px;">'
            f'    <span class="bs-mono" style="font-size:12px; color:#667085; min-width:74px;">'
            f'      평균 {peer:g}{row["unit"]}</span>'
            f'    <div style="position:relative; flex:1; height:7px; background:{theme.BG}; '
            f'         border-radius:4px;">'
            f'      <div style="position:absolute; left:50%; top:-3px; width:1px; height:13px; '
            f'           background:#98A2B3;"></div>'
            f'      <div style="position:absolute; left:{lo}%; width:{hi - lo}%; top:0; '
            f'           height:7px; background:{color}; border-radius:4px;"></div>'
            f'    </div>'
            f'    <span class="bs-mono" style="font-size:12.5px; font-weight:700; '
            f'          color:{color}; min-width:64px; text-align:right;">'
            f'      내 값 {mine:g}{row["unit"]}</span>'
            f'  </div>'
            f'  <div class="bs-note" style="margin-bottom:6px;">{diff_text}</div>'
            f'  <div style="font-size:13px; line-height:1.75;">{row["sentence"]}</div>'
            f'</div>'
        )

    st.markdown("".join(blocks), unsafe_allow_html=True)
    explanation_source(report)


def ai_qa_widget(vessel: Dict) -> None:
    """점수리포트 탭 하단 — 리포트에 대해 자유롭게 질문하는 위젯."""
    st.markdown("##### AI에게 질문하기")
    st.markdown(
        '<div class="bs-note">용어, 리포트 내용, 리포트에 없는 궁금한 점을 물어보세요.</div>',
        unsafe_allow_html=True,
    )
    key = f"qa_question_{vessel['vesselId']}"
    question = st.text_input(
        "질문", key=key, placeholder="예: 표류·대기 시간은 어떻게 계산되나요?",
        label_visibility="collapsed",
    )
    if st.button("질문하기", key=f"qa_submit_{vessel['vesselId']}"):
        if question.strip():
            st.session_state[f"qa_answer_{vessel['vesselId']}"] = adapter.ask_ai(vessel, question)

    answer = st.session_state.get(f"qa_answer_{vessel['vesselId']}")
    if answer and answer.get("text"):
        st.markdown(f'<div class="bs-card">{answer["text"]}</div>', unsafe_allow_html=True)
        explanation_source(answer)


def objection_form(vessel: Dict) -> None:
    """점수리포트 탭 하단 — 점수에 대한 이의제기 제출."""
    st.markdown("##### 이의제기")
    existing = adapter.get_objection(vessel["vesselId"])
    if existing:
        st.markdown(
            f'<div class="bs-card"><div class="bs-label">접수된 이의제기 · '
            f'{"답변 완료" if existing["status"] == "answered" else "심사역 검토 중"}</div>'
            f'<div class="bs-note"><b>{existing["reason"]}</b><br>{existing["detail"]}</div>'
            + (
                f'<div class="bs-note" style="margin-top:10px; padding-top:10px; '
                f'border-top:1px solid {theme.LINE};"><b>심사역 답변</b><br>{existing["aiResponse"]}</div>'
                if existing.get("aiResponse")
                else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="bs-note">데이터·산출 결과가 실제와 다르다고 생각되면 이의를 제기할 수 있습니다. '
        '금융기관 심사역이 근거를 확인한 뒤 답변합니다.</div>',
        unsafe_allow_html=True,
    )
    reason = st.selectbox(
        "사유",
        ["동일 해역 반복 조업 판정이 실제와 다름", "혼잡 해역 집중 판정이 실제와 다름",
         "기대 대비 연료 초과 추정이 실제와 다름", "어업종 또는 선박제원 매칭 오류",
         "기타"],
        key=f"objection_reason_{vessel['vesselId']}",
    )
    detail = st.text_area(
        "상세 내용", key=f"objection_detail_{vessel['vesselId']}",
        placeholder="구체적인 상황을 적어주시면 심사역이 확인하는 데 도움이 됩니다.",
    )
    if st.button("이의제기 제출", key=f"objection_submit_{vessel['vesselId']}"):
        adapter.submit_objection(vessel["vesselId"], reason, detail)
        st.success("이의제기가 접수되었습니다. 금융기관 심사역이 검토합니다.")
        st.rerun()


def objection_panel_bank(vessel: Dict) -> None:
    """
    이의제기 내역과 AI 답변 초안, 전달(시연용 팝업).

    이의제기가 없어도 이 패널은 화면을 막지 않는다 — 심사는 차주의 이의제기와
    무관하게 진행되며, 이의제기는 심사의 입력 중 하나일 뿐이다.
    """
    objection = adapter.get_objection(vessel["vesselId"])
    if not objection:
        st.markdown(
            '<div class="bs-card"><div class="bs-note">접수된 이의제기가 없습니다. '
            '이의제기 없이도 아래에서 심사 의견을 작성하고 최종 금리를 결정할 수 '
            '있습니다.</div></div>',
            unsafe_allow_html=True,
        )
        return

    status_label = {"submitted": "접수", "approved": "승인", "held": "보류"}.get(
        objection.get("status", ""), objection.get("status", "")
    )
    st.markdown(
        f'<div class="bs-card">'
        f'<div style="display:flex; align-items:baseline; gap:8px;">'
        f'<span class="bs-label" style="margin:0;">사유</span>'
        f'<span class="bs-pill info" style="margin-left:auto;">{status_label}</span></div>'
        f'<div style="font-weight:700; margin:2px 0 8px;">{objection["reason"]}</div>'
        f'<div class="bs-label">상세 내용</div>'
        f'<div class="bs-note">{objection["detail"] or "(추가 설명 없음)"}</div></div>',
        unsafe_allow_html=True,
    )

    if st.button("AI 답변 초안 생성", key=f"objection_ai_{vessel['vesselId']}",
                 width="stretch"):
        with st.spinner("답변 초안을 생성하는 중..."):
            adapter.objection_ai_response(vessel, objection["reason"], objection["detail"])
        st.rerun()

    refreshed = adapter.get_objection(vessel["vesselId"])
    if refreshed and refreshed.get("aiResponse"):
        st.markdown(
            f'<div class="bs-card"><div class="bs-label">AI 답변 초안 · 검토 후 전달</div>'
            f'<div style="font-size:13.5px; line-height:1.8;">{refreshed["aiResponse"]}</div></div>',
            unsafe_allow_html=True,
        )
        explanation_source({"source": refreshed["aiResponseSource"]})
        sent_key = f"objection_sent_{vessel['vesselId']}"
        if st.button("어업인에게 전달", key=f"objection_send_{vessel['vesselId']}",
                     width="stretch"):
            st.session_state[sent_key] = True
            st.toast("어업인에게 답변을 전달했습니다.", icon="✅")
        if st.session_state.get(sent_key):
            st.success(
                f'{vessel["name"]} 차주에게 답변을 전달했습니다. '
                "(시연용 표시이며 실제 발송은 이루어지지 않습니다.)"
            )


_INTEREST_PANEL_HTML = """
<style>
  * { box-sizing:border-box; }
  body { margin:0; background:transparent; font-family:__FONT_SANS__; color:__INK__; }
  .wrap { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .card {
    background:__SURFACE__; border:1px solid __LINE__; border-radius:12px; padding:14px 16px;
    opacity:0; transform:translateY(6px); animation:in .45s ease-out forwards;
  }
  .card.b { animation-delay:.08s; }
  @keyframes in { to { opacity:1; transform:none; } }
  .k { font-size:11.5px; color:__INK_SOFT__; margin-bottom:5px; }
  .rate { font-family:__FONT_MONO__; font-weight:700; font-size:26px; }
  .sub { font-size:11.5px; color:__INK_SOFT__; margin-top:3px; }
  .bars { margin-top:12px; }
  .barrow { display:flex; align-items:center; gap:9px; margin-bottom:7px; font-size:11.5px; }
  .barrow .tag { width:52px; color:__INK_SOFT__; }
  .track { flex:1; height:11px; background:__BG__; border-radius:6px; overflow:hidden; }
  .track > i { display:block; height:11px; border-radius:6px; width:0; transition:width 1s cubic-bezier(.22,1,.36,1); }
  .barrow .num { width:96px; text-align:right; font-family:__FONT_MONO__; font-weight:600; }
  .save { margin-top:12px; padding-top:11px; border-top:1px solid __LINE__; }
  .big { font-family:__FONT_MONO__; font-weight:700; font-size:24px; color:__POSITIVE__; }
</style>
<div class="wrap">
  <div class="card">
    <div class="k">적용 금리</div>
    <div style="display:flex; align-items:baseline; gap:9px;">
      <span class="rate" style="color:__INK_SOFT__; font-size:19px;"><span id="r0">0</span>%</span>
      <span style="color:__INK_SOFT__;">→</span>
      <span class="rate" style="color:__AXIS_A__;"><span id="r1">0</span>%</span>
    </div>
    <div class="sub">기준금리 <span id="base">0</span>% · 우대 <span id="bp">0</span>bp 적용</div>
    <div class="save">
      <div class="k">만기까지 이자 절감</div>
      <div class="big"><span id="tot">0</span> 만원</div>
      <div class="sub">연간 <span id="yr">0</span>만원 · <span id="pri">0</span>억 원 · <span id="trm">0</span>년 만기</div>
    </div>
  </div>
  <div class="card b">
    <div class="k">총 이자 부담 비교</div>
    <div class="bars">
      <div class="barrow">
        <span class="tag">우대 전</span>
        <span class="track"><i id="bar0" style="background:__INK_SOFT__;"></i></span>
        <span class="num"><span id="i0">0</span>만원</span>
      </div>
      <div class="barrow">
        <span class="tag">우대 후</span>
        <span class="track"><i id="bar1" style="background:__AXIS_A__;"></i></span>
        <span class="num"><span id="i1">0</span>만원</span>
      </div>
    </div>
    <div class="sub" id="note"></div>
  </div>
</div>
<script>
(function () {
  var D = __DATA__;
  function tween(id, target, decimals, dur) {
    var el = document.getElementById(id), t0 = null;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min((ts - t0) / (dur || 850), 1);
      var e = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * e).toFixed(decimals);
      if (p < 1) requestAnimationFrame(step); else el.textContent = target.toFixed(decimals);
    }
    requestAnimationFrame(step);
  }
  document.getElementById('base').textContent = D.baseRate.toFixed(2);
  document.getElementById('bp').textContent = D.finalBp;
  document.getElementById('pri').textContent = D.principalEok;
  document.getElementById('trm').textContent = D.termYears;
  tween('r0', D.baseRate, 2);
  tween('r1', D.finalRate, 2);
  tween('i0', D.interestBefore, 0);
  tween('i1', D.interestAfter, 0);
  tween('yr', D.savingYearly, 0);
  tween('tot', D.savingTotal, 0);
  var most = Math.max(D.interestBefore, 1);
  setTimeout(function () {
    document.getElementById('bar0').style.width = '100%';
    document.getElementById('bar1').style.width = (D.interestAfter / most * 100) + '%';
  }, 60);
  document.getElementById('note').textContent = D.finalBp > 0
    ? '우대 ' + D.finalBp + 'bp 적용으로 만기까지 이자 부담이 ' + D.savingTotal + '만원 줄어듭니다.'
    : '우대 없음으로 적용하면 이자 부담은 그대로입니다.';
})();
</script>
"""


def interest_impact(
    *, base_rate_percent: float, final_bp: int, principal_won: int, term_years: int,
    height: int = 210,
) -> None:
    """
    확정 금리가 실제 이자 부담을 얼마나 바꾸는지.

    심사역이 bp 하나를 조정할 때 그것이 차주에게 얼마인지 바로 보이지 않으면
    금리 결정이 숫자 놀음이 된다. 단리 근사이며 화면에도 그렇게 표기한다.
    """
    final_rate = round(base_rate_percent - final_bp / 100, 4)
    interest_before = int(principal_won * base_rate_percent / 100) * term_years
    interest_after = int(principal_won * final_rate / 100) * term_years
    yearly = int(principal_won * final_bp / 10000)

    data = {
        "baseRate": base_rate_percent,
        "finalRate": final_rate,
        "finalBp": final_bp,
        "principalEok": round(principal_won / 100_000_000, 2),
        "termYears": term_years,
        "interestBefore": interest_before // 10_000,
        "interestAfter": interest_after // 10_000,
        "savingYearly": yearly // 10_000,
        "savingTotal": (yearly * term_years) // 10_000,
    }
    html = (
        _INTEREST_PANEL_HTML
        .replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__FONT_SANS__", theme.FONT_SANS)
        .replace("__FONT_MONO__", theme.FONT_MONO)
        .replace("__INK_SOFT__", theme.INK_SOFT)
        .replace("__INK__", theme.INK)
        .replace("__SURFACE__", theme.SURFACE)
        .replace("__LINE__", theme.LINE)
        .replace("__BG__", theme.BG)
        .replace("__AXIS_A__", theme.AXIS_A)
        .replace("__POSITIVE__", theme.POSITIVE)
    )
    components_html(html, height=height, scrolling=False)
    st.markdown(
        '<div class="bs-note">단리 근사이며 예시 표기입니다. 실제 상환 방식·수수료는 '
        '여신 약정에 따릅니다.</div>',
        unsafe_allow_html=True,
    )


_ONCHAIN_CHECK_SVG = """
<svg width="22" height="22" viewBox="0 0 24 24" style="flex-shrink:0;">
  <circle class="bs-check-circle" cx="12" cy="12" r="10" />
  <polyline class="bs-check-mark" points="7,12.5 10.5,16 17,8" />
</svg>
"""


def onchain_receipt(commit: Dict) -> None:
    """온체인 커밋 영수증 — 기록된 해시와 블록 정보."""
    st.markdown(
        f'<div class="bs-card" style="border-left:3px solid {theme.POSITIVE};">'
        f'<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">'
        f'{_ONCHAIN_CHECK_SVG}'
        f'<span style="font-weight:700; color:{theme.POSITIVE};">온체인 기록 완료</span>'
        f'<span class="bs-note">{commit["committedAt"]}</span></div>'
        f'<div class="bs-label">Record ID</div>'
        f'<div class="bs-hash">{commit["recordId"]}</div>'
        f'<div class="bs-label" style="margin-top:9px;">Result hash (SHA-256)</div>'
        f'<div class="bs-hash">{commit["resultHash"]}</div>'
        f'<div class="bs-note" style="margin-top:9px;">'
        f'원장 {commit["ledgerMode"]} · 블록 {commit.get("blockNumber") or "-"}<br>'
        f'트랜잭션 {commit.get("transactionHash") or "로컬 모드"}<br>'
        f'컨트랙트 {commit.get("contractAddress") or "-"}</div></div>',
        unsafe_allow_html=True,
    )


def smart_contract_lookup_card(vessel: Dict, score: float) -> None:
    """
    최종금리결정 탭 — FastAPI의 사전 승인 규칙표 조회 결과.
    """
    with st.spinner("스마트컨트랙트에서 금리 구간 조회 중..."):
        result = adapter.rate_lookup(score)
    band = result["band"]
    st.markdown(
        f'<div class="bs-card"><div class="bs-label">사전 승인 금리 규칙 조회 · '
        f'점수 {score:g} → 금리 구간</div>'
        f'<div style="display:flex; align-items:baseline; gap:10px; margin-top:4px;">'
        f'<span style="font-size:22px; font-weight:800;">{theme.discount_text(band)}</span></div>'
        f'<div class="bs-note" style="margin-top:8px;">FastAPI의 버전 고정 은행 사전 승인 '
        f'규칙표 조회 결과입니다. 온체인에는 최종 심사 결과 해시만 기록합니다.</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
