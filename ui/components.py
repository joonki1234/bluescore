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
# 축 색 체계는 그대로다 — 조업 이벤트는 A축 계열(파랑), 앰버는 보호구역 표시.
MAP_FISHING = "#60A5FA"
MAP_SAILING = "#BBD3FA"
MAP_GAP = "#EEF1F5"
MAP_MPA = "#FBBF24"

# 지리 기준점 — 지도가 어디를 보고 있는지 즉시 알 수 있게 한다.
_LANDMARKS = [
    {"lat": 37.2416, "lng": 131.8686, "name": "독도"},
    {"lat": 37.5054, "lng": 130.8642, "name": "울릉도"},
]


def _chart(fig: go.Figure, height: int) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
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

    events = []
    for idx, (gx, gy) in enumerate(track):
        lat = anchor_lat - (gy - origin_y) * _SCALE_LAT
        lng = anchor_lng + (gx - origin_x) * _SCALE_LNG
        is_fishing = any(s <= idx <= e for s, e in vessel["fishingSegments"])
        is_gap = idx == vessel.get("gapIndex", -1)
        is_mpa = idx == vessel.get("mpaIndex", -1)

        if is_gap:
            kind, color, radius = "신호두절(GAP)", MAP_GAP, 6
        elif is_fishing:
            kind, color, radius = "조업 이벤트", MAP_FISHING, 7
        else:
            kind, color, radius = "항해 이벤트", MAP_SAILING, 5

        events.append(
            {
                "lat": lat,
                "lng": lng,
                "color": color,
                "radius": radius,
                "dashed": is_gap,
                "mpa": is_mpa,
                "home": idx == 0,
                "tip": f"#{idx + 1} {kind}"
                + (" · 해양보호구역 태그" if is_mpa else ""),
            }
        )

    center, zoom = _fit_view(events, height)
    payload = {
        "events": events,
        "landmarks": _LANDMARKS,
        "center": center,
        "zoom": zoom,
        "mpaColor": MAP_MPA,
        "pathColor": MAP_SAILING,
        "tileUrl": ESRI_WORLD_IMAGERY_URL,
        "attribution": ESRI_ATTRIBUTION,
    }

    components_html(
        _leaflet_html(payload, height),
        height=height,
        scrolling=False,
    )
    st.markdown(
        '<div class="bs-note">파랑 = 조업 이벤트 · 연한 파랑 = 항해 이벤트 · '
        '회색 점선 테두리 = 신호두절 · 앰버 원 = 해양보호구역 태그<br>'
        'GFW 조업 이벤트를 이어 그린 <b>근사 경로</b>입니다. 초 단위 연속 항적이 아닙니다. '
        '점에 마우스를 올리면 상세가 표시됩니다.</div>',
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
</style>
<div id="bsmap"></div>
<script>
const D = {data};
const map = L.map('bsmap', {{ scrollWheelZoom:false, zoomControl:true }})
  .setView(D.center, D.zoom);
L.tileLayer(D.tileUrl, {{ maxZoom:16, minZoom:6, attribution:D.attribution }}).addTo(map);

D.landmarks.forEach(function(m) {{
  L.circleMarker([m.lat, m.lng], {{
    radius:4, color:'#FFFFFF', weight:1.5, fillColor:'#EAF6FF', fillOpacity:1
  }}).addTo(map).bindTooltip(m.name, {{
    permanent:true, direction:'top', offset:[0,-6], className:'geo-label'
  }});
}});

const latlngs = D.events.map(function(e) {{ return [e.lat, e.lng]; }});
L.polyline(latlngs, {{
  color:D.pathColor, weight:2, opacity:0.75, dashArray:'2 6', lineCap:'round'
}}).addTo(map);

D.events.forEach(function(e) {{
  if (e.mpa) {{
    L.circle([e.lat, e.lng], {{
      radius:900, color:D.mpaColor, weight:2, dashArray:'3 4', fill:false, opacity:0.95
    }}).addTo(map);
  }}
  L.circleMarker([e.lat, e.lng], {{
    radius:e.radius,
    color:e.dashed ? '#98A2B3' : '#FFFFFF',
    weight:e.dashed ? 1.6 : 1.2,
    dashArray:e.dashed ? '2 2' : null,
    fillColor:e.color,
    fillOpacity:e.dashed ? 0.5 : 1
  }}).addTo(map).bindTooltip(e.tip, {{ direction:'top' }});
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
    """A축·B축 분해. 시뮬레이션이 주어지면 변화 후 값을 함께 그린다."""
    dataset = adapter.load_dataset()
    weights = dataset["axisWeights"]

    rows = [
        ("A. 자원 압력", "a", vessel["axisA"], weights["a"],
         "자원에 회복 여지를 남겼는가 — 동일 격자 재방문 간격, 혼잡 어장 회피",
         simulation.axis_a if simulation else None),
        ("B. 운항 효율", "b", vessel["axisB"], weights["b"],
         "같은 조업을 덜 태우며 했는가 — 유사 선박군 기준선 대비 연료 소비 차이",
         simulation.axis_b if simulation else None),
    ]

    for name, axis, data, weight, desc, after in rows:
        color = theme.axis_color(axis)
        after_html = ""
        if after is not None and abs(after - data["score"]) >= 0.05:
            delta = after - data["score"]
            after_html = (
                f'<span style="font-size:14px; color:{theme.direction_color(delta)}; '
                f'font-weight:700; margin-left:8px;">→ {after:g} ({theme.signed(delta)})</span>'
            )
        st.markdown(
            f"""<div class="bs-card">
  <div style="display:flex; align-items:baseline; gap:10px; margin-bottom:8px;">
    <span style="font-size:15px; font-weight:700;">{name}</span>
    <span style="font-size:11px; color:{theme.INK_SOFT}; border:1px solid {theme.LINE};
      border-radius:5px; padding:2px 7px;">가중치 {int(weight * 100)}%</span>
    <span style="margin-left:auto; font-size:20px; font-weight:800;">{data['score']:g}</span>
    <span style="font-size:12px; color:{theme.INK_SOFT}; font-weight:600;">
      {theme.top_percent_text(data['topPercent'])}</span>{after_html}
  </div>
  <div style="height:8px; background:{theme.BG}; border-radius:5px; overflow:hidden;">
    <div style="height:100%; width:{data['score']}%; background:{color}; border-radius:5px;"></div>
  </div>
  <div class="bs-note" style="margin-top:8px;">{desc}</div>
</div>""",
            unsafe_allow_html=True,
        )

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

    fig.update_xaxes(title_text="BlueScore", gridcolor=theme.LINE, zeroline=False)
    fig.update_yaxes(title_text="척수", gridcolor=theme.LINE, zeroline=False)
    _chart(fig, height)
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
    cols = st.columns(4)
    stats = [
        ("총 이동거리", f"{vessel['totalDistanceKm']:,}", "km"),
        ("조업 시간", f"{vessel['fishingHours']}", "h"),
        ("추정 연료", f"{vessel['estimatedFuelKl']}", "kL"),
        ("출항", f"{vessel['sailCalls']}", "회"),
    ]
    for col, (label, value, unit) in zip(cols, stats):
        with col:
            st.markdown(
                f'<div class="bs-card"><div class="bs-label">{label}</div>'
                f'<div class="bs-value">{value}<span class="unit">{unit}</span></div></div>',
                unsafe_allow_html=True,
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
