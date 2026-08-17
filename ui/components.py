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

# 어두운 위성 배경 위에서 읽히도록 조정한 지도 전용 색.
# 축 색 체계는 그대로다 — 조업 이벤트는 A축 계열(파랑), 보호구역은 방향색
# 체계의 감점색(theme.NEGATIVE)을 그대로 써서 "감점 요인"임을 색으로도 전달한다.
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
# Streamlit이 재실행마다 DOM을 새로 그리는 방식이라, CSS 트랜지션은 브라우저가
# 중간 상태를 그리지 않고 최종값을 바로 페인트해버려 재생을 보장하지 못한다.
# 그래서 숫자 카운트업·막대 채움처럼 "임팩트가 중요한" 요소는 지도와 같은
# components.v1.html(iframe) 안에서 진짜 JS로 애니메이션한다. iframe은 페이지의
# 공용 CSS(theme.inject())를 못 받으므로, bs-card 스타일을 최소한으로 복제해
# 여기 한 곳에만 정의하고 여러 컴포넌트가 재사용한다.
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
    """
    숫자 카드 여러 개를 한 행에 0→값 카운트업 애니메이션과 함께 그린다.

    `stats` 각 항목: {"label","value","unit","color","decimals","signed"}. `value`가
    문자열이면(예: 등급 텍스트) 애니메이션 없이 그대로 표시한다.
    기존 st.columns + bs-card 조합을 대체하는 자리에 쓴다 — 표시값은 동일하고
    애니메이션만 더해진다.
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
    """
    "72.6 → 76.3" 같은 전후 비교 카드. 시뮬레이터·개선 추천 카드에서 반복되는
    패턴이라 공용으로 뺐다. before/after가 숫자면 그 구간을 카운트업하고,
    문자열(등급 텍스트 등)이면 애니메이션 없이 페이드인만 한다.
    """
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


def score_bar(vessel: Dict, *, show_grade: bool = True) -> None:
    """
    화면 최상단에 항상 붙는 점수 띠.

    어느 탭에 있든 점수가 보이게 해서 시뮬레이터에서 "72.6이 몇 점으로" 라는
    변화가 시야에서 사라지지 않게 한다.
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

    st.markdown(
        f"""<div class="bs-scorebar">
  <div class="seg">
    <div class="bs-label">BlueScore</div>
    <div class="big">{vessel['blueScore']}</div>
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
</div>""",
        unsafe_allow_html=True,
    )


def voyage_map(vessel: Dict, height: int = 380) -> None:
    """
    조업 이벤트 지도.

    CLAUDE.md 확정 규칙 1번 — GFW는 연속 항적이 아니라 이산 이벤트만 제공하므로
    점선 보간 + 이벤트 지점 강조로 그린다. 이어진 선은 항적선이 아니라 이벤트
    순서 보조선이다.

    조업 이벤트를 파랑(A축 색)으로 칠한다. 조업 위치와 재방문이 만들어내는 값이
    A축이기 때문이며, 앰버는 연료·효율(B축)에만 남긴다.
    """
    track = vessel["track"]
    if not track:
        st.info("표시할 조업 이벤트가 없습니다.")
        return

    origin_x, origin_y = track[0]
    anchor_lat, anchor_lng = vessel["anchor"]

    # 동일 구역 반복조업 히트 — 격자좌표를 셀 단위로 묶어 재방문 횟수를 센다.
    # 값이 클수록 같은 자리를 자주 긁는다는 뜻이라 A축(자원 압력) 감점 신호다.
    # 히트맵 레이어의 가중치로 쓴다(GFW의 조업강도 히트맵과 같은 접근).
    cell_size = 40
    visit_counts: Dict[tuple, int] = {}
    for gx, gy in track:
        cell = (gx // cell_size, gy // cell_size)
        visit_counts[cell] = visit_counts.get(cell, 0) + 1

    shap_by_axis = {"a": [], "b": []}
    for factor in vessel.get("shapFactors", []):
        shap_by_axis.setdefault(factor["axis"], []).append(factor)
    top_a_factor = max(shap_by_axis["a"], key=lambda f: abs(f["value"]), default=None)
    top_b_factor = max(shap_by_axis["b"], key=lambda f: abs(f["value"]), default=None)

    events = []
    heat_points = []
    for idx, (gx, gy) in enumerate(track):
        lat = anchor_lat - (gy - origin_y) * _SCALE_LAT
        lng = anchor_lng + (gx - origin_x) * _SCALE_LNG
        is_fishing = any(s <= idx <= e for s, e in vessel["fishingSegments"])
        is_gap = idx == vessel.get("gapIndex", -1)
        is_mpa = idx == vessel.get("mpaIndex", -1)
        cell = (gx // cell_size, gy // cell_size)
        revisits = visit_counts[cell]

        if is_gap:
            kind, radius = "신호두절(GAP)", 5
        elif is_fishing:
            kind, radius = "조업 이벤트", 6
            heat_points.append([lat, lng, min(1.0, 0.35 + 0.25 * revisits)])
        else:
            kind, radius = "항해 이벤트", 4

        tip = f"#{idx + 1} {kind}"
        if is_fishing and revisits > 1:
            tip += f" · 이 구역 재방문 {revisits}회"
            if top_a_factor:
                tip += f" · 자원압력 요인: {top_a_factor['label']} ({top_a_factor['value']:+.1f})"
        elif not is_fishing and top_b_factor:
            tip += f" · 운항효율 요인: {top_b_factor['label']} ({top_b_factor['value']:+.1f})"
        if is_mpa:
            tip += " · 해양보호구역 태그"

        events.append(
            {
                "lat": lat,
                "lng": lng,
                "radius": radius,
                "fishing": is_fishing,
                "dashed": is_gap,
                "mpa": is_mpa,
                "home": idx == 0,
                "tip": tip,
            }
        )

    center, zoom = _fit_view(events, height)
    payload = {
        "events": events,
        "heatPoints": heat_points,
        "landmarks": _LANDMARKS,
        "center": center,
        "zoom": zoom,
        "fishingColor": MAP_FISHING,
        "mpaColor": MAP_MPA,
        "pathColor": MAP_SAILING,
        "gapColor": MAP_GAP,
        "tileUrl": ESRI_WORLD_IMAGERY_URL,
        "attribution": ESRI_ATTRIBUTION,
    }

    components_html(
        _leaflet_html(payload, height),
        height=height,
        scrolling=False,
    )
    st.markdown(
        '<div class="bs-note">파란 히트맵 = 동일 구역 반복조업(진할수록 재방문 잦음) · '
        '점선 = 이벤트를 이은 근사 경로 · 회색 점선 원 = 신호두절 · 빨간 원 = 해양보호구역 태그<br>'
        'GFW는 연속 항적이 아니라 이산 이벤트만 제공해, 이벤트 지점을 점선으로 이어 '
        '근사 경로를 표시합니다. 점에 마우스를 올리면 이 지점이 점수에 준 영향이 함께 '
        '표시됩니다.<br>해양보호구역 최신 현황은 '
        '<a href="https://www.meis.go.kr/mes/marineSanctuary/situation.do" target="_blank">'
        '해양수산부 해양보호구역 통합정보시스템</a>에서 확인할 수 있습니다.</div>',
        unsafe_allow_html=True,
    )


def _fit_view(events: List[Dict], height: int) -> tuple:
    """
    항적이 화면에 알맞게 들어오는 중심 좌표와 줌을 계산한다.

    Leaflet의 fitBounds에 맡기지 않는 이유 — iframe 안에서는 지도 컨테이너 크기가
    확정되기 전에 스크립트가 실행될 수 있어 잘못된 줌이 잡힌다. 파이썬에서 미리
    계산해 넘기면 그 경합이 사라진다.
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
    """
    Leaflet + Esri World Imagery 위성 지도를 iframe 안에 그린다.

    pydeck을 쓰지 않는 이유 — Streamlit의 deck.gl 컴포넌트에서 Carto/Mapbox
    베이스맵이 뜨지 않았다(키 없이는 배경이 비어 나옴). Leaflet + Esri 조합은
    API 키가 필요 없고, 발표용 목업(blue_score_dashboard_3.html)에서 이미
    정상 동작을 확인한 방식이다.

    iframe으로 격리돼 있어 Streamlit이 다른 위젯 때문에 재실행돼도 지도 상태가
    Streamlit 위젯 트리에 얽히지 않는다.
    """
    data = json.dumps(payload, ensure_ascii=False)
    return f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js"></script>
<style>
  html, body {{ margin:0; padding:0; }}
  #bsmap {{ width:100%; height:{height}px; border-radius:8px; background:#0B1B2B; }}
  .geo-label {{
    background:rgba(16,24,40,.78) !important; border:none !important; box-shadow:none !important;
    color:#FFFFFF !important; font-size:11px !important; padding:2px 6px !important;
  }}
  .geo-label::before {{ display:none !important; }}
  .leaflet-container {{ font-family:{theme.FONT_SANS}; }}
  .leaflet-control-attribution {{ font-size:9.5px; }}
  .bs-heat-layer {{ opacity:0; transition:opacity 1.1s ease-out; }}
  .bs-glow-dot {{ filter:drop-shadow(0 0 4px var(--dot-color)); }}
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

const latlngs = D.events.map(function(e) {{ return [e.lat, e.lng]; }});
L.polyline(latlngs, {{
  color:D.pathColor, weight:2, opacity:0.7, dashArray:'2 6', lineCap:'round'
}}).addTo(map);

D.events.forEach(function(e) {{
  if (e.mpa) {{
    L.circle([e.lat, e.lng], {{
      radius:900, color:D.mpaColor, weight:2, dashArray:'3 4', fill:false, opacity:0.95
    }}).addTo(map);
  }}
  if (e.dashed) {{
    L.circleMarker([e.lat, e.lng], {{
      radius:e.radius, color:'#98A2B3', weight:1.6, dashArray:'2 2',
      fillColor:D.gapColor, fillOpacity:0.5
    }}).addTo(map).bindTooltip(e.tip, {{ direction:'top' }});
  }} else {{
    const color = e.fishing ? D.fishingColor : D.pathColor;
    const marker = L.circleMarker([e.lat, e.lng], {{
      radius:e.radius, color:'#FFFFFF', weight:1.3, fillColor:color, fillOpacity:1,
      className:'bs-glow-dot'
    }}).addTo(map).bindTooltip(e.tip, {{ direction:'top' }});
    if (marker._path) {{ marker._path.style.setProperty('--dot-color', color); }}
  }}
  if (e.home) {{
    L.circleMarker([e.lat, e.lng], {{ radius:0, opacity:0 }}).addTo(map)
      .bindTooltip('모항', {{ permanent:true, direction:'right', offset:[8,0], className:'geo-label' }});
  }}
}});

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
        f'color:{theme.INK_SOFT};">{adapter.formula_text(vessel["axisA"]["score"], vessel["axisB"]["score"])}</span>'
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
    """점수리포트 탭 — 요인별 실측값을 근거로 한 LLM 상세 리포트."""
    report = adapter.detailed_report(vessel)
    if not report.get("text"):
        return
    st.markdown("##### 상세 리포트")
    st.markdown(
        f'<div class="bs-card"><div style="font-size:13.5px; line-height:1.85;">'
        f'{report["text"]}</div></div>',
        unsafe_allow_html=True,
    )
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


def improvement_recommendation_cards(vessel: Dict) -> None:
    """개선 시뮬레이터 탭 상단 — 가장 쉬운 개선 / 최고의 인센티브 두 카드."""
    easiest = adapter.easiest_improvement(vessel)
    best = adapter.best_incentive_improvement(vessel)
    dataset = adapter.load_dataset()
    before_band = theme.grade_band(vessel["blueScore"], dataset["rateGrades"])

    left, right = st.columns(2, gap="medium")
    for col, title, sim, desc in [
        (left, "🟢 지금 할 수 있는 가장 쉬운 개선", easiest, "한 걸음만 바꿔도 되는 조합"),
        (right, "🏆 최고의 인센티브를 위한 개선", best, "다음 우대 구간까지 필요한 조합"),
    ]:
        after_band = theme.grade_band(sim.score, dataset["rateGrades"])
        with col:
            st.markdown(
                f'<div class="bs-label" style="margin-bottom:2px;">{title}</div>'
                f'<div class="bs-note" style="margin-bottom:6px;">{desc}</div>',
                unsafe_allow_html=True,
            )
            animated_transition_card(
                "BlueScore", vessel["blueScore"], sim.score,
                note_html=f'{theme.discount_text(before_band)} → <b>{theme.discount_text(after_band)}</b>',
            )


def objection_panel_bank(vessel: Dict) -> None:
    """최종금리결정 탭 — 어업인 이의제기 내역과 AI 답변 초안, 가짜 발송 팝업."""
    st.markdown("##### 이의제기 내역")
    objection = adapter.get_objection(vessel["vesselId"])
    if not objection:
        st.markdown(
            '<div class="bs-card"><div class="bs-note">제기된 이의가 없습니다.</div></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="bs-card"><div class="bs-label">사유</div>'
        f'<div style="font-weight:700; margin-bottom:6px;">{objection["reason"]}</div>'
        f'<div class="bs-label">상세 내용</div>'
        f'<div class="bs-note">{objection["detail"] or "(추가 설명 없음)"}</div></div>',
        unsafe_allow_html=True,
    )

    if st.button("AI 답변 초안 생성", key=f"objection_ai_{vessel['vesselId']}"):
        result = adapter.objection_ai_response(vessel, objection["reason"], objection["detail"])
        adapter.resolve_objection(vessel["vesselId"], result["text"], result["source"])
        st.rerun()

    refreshed = adapter.get_objection(vessel["vesselId"])
    if refreshed and refreshed.get("aiResponse"):
        st.markdown(
            f'<div class="bs-card"><div class="bs-label">AI 답변 초안 (검토 후 전달)</div>'
            f'<div style="font-size:13.5px; line-height:1.8;">{refreshed["aiResponse"]}</div></div>',
            unsafe_allow_html=True,
        )
        explanation_source({"source": refreshed["aiResponseSource"]})
        if st.button("어업인에게 전달", key=f"objection_send_{vessel['vesselId']}"):
            st.toast("어업인에게 답변을 전달했습니다.", icon="✅")


def smart_contract_lookup_card(vessel: Dict, score: float) -> None:
    """
    최종금리결정 탭 — 점수→금리 조회 연출.

    지금은 `adapter.rate_lookup()`이 규칙표를 감싼 mock이다. 실제 온체인
    컨트랙트가 배포되면 이 컴포넌트는 그대로 두고 `rate_lookup()` 내부만
    바뀐다.
    """
    with st.spinner("스마트컨트랙트에서 금리 구간 조회 중..."):
        result = adapter.rate_lookup(score)
    band = result["band"]
    st.markdown(
        f'<div class="bs-card"><div class="bs-label">스마트컨트랙트 조회 결과 · '
        f'점수 {score:g} → 금리 구간</div>'
        f'<div style="display:flex; align-items:baseline; gap:10px; margin-top:4px;">'
        f'<span style="font-size:22px; font-weight:800;">{theme.discount_text(band)}</span></div>'
        f'<div class="bs-note" style="margin-top:8px;">현재는 은행 사전 승인 규칙표를 조회한 '
        f'결과입니다. 점수→금리 매핑 온체인 컨트랙트는 팀 검토 후 이 조회를 대체할 예정입니다.</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
