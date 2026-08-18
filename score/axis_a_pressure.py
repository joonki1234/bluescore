"""
담당: 김준기, 오동규

A축(자원 압력) 지표 산출 — 동일·인접 격자 내 조업 이벤트 재방문 간격과
조업 이벤트 밀도 기반 혼잡가중압력을 계산한다.

참고: BlueScore 프로젝트 기획서(2026-08-11) 4번 "문제 해결 방안" -
① BlueScore 산출 - A축(자원 압력, 가중치 65%):
    "동일·인접 격자 내 조업 이벤트 발생 간격(같은 해역을 얼마나 짧은 주기로
    반복 조업하는가) + 조업 이벤트 밀도 기반 혼잡 가중 압력(이미 조업이
    집중된 해역에 추가적인 압력을 가하는가)"

산출 절차:
    1. 각 조업 이벤트의 위경도를 고정 크기 격자(grid cell)로 매핑한다.
    2. 재방문간격: 선박별로, 동일/인접(체비쇼프 거리 1 이내) 격자에서
       발생한 직전 이벤트와의 시간 간격을 구하고 평균낸다. 간격이 짧을수록
       압력이 높다는 방향으로 점수화한다(반비례 변환).
    3. 혼잡가중압력: 전체 이벤트를 격자별로 집계해 밀도(이벤트 수)를 구하되,
       선박 자기 자신의 이벤트는 밀도에서 제외한다 — "다른 배들이 이미
       몰려있는 곳인가"만 측정하기 위함이다 (자기 자신의 재방문 빈도는
       revisit_interval_raw가 이미 담당한다).
    4. 두 raw 값은 단위가 전혀 다르다 — revisit_interval_raw는 시간 기반
       반비례 값(실측 중앙값 0.88)이고, crowding_pressure_raw는 격자 내
       다른 배 이벤트 수를 그대로 센 값(실측 중앙값 371.83)이라 약 400배
       차이 난다. 이 상태로 가중합하면 가중치를 50/50으로 줘도 실제로는
       거의 100:0으로 작동한다(재방문압력의 실제 기여가 실측 1%대로
       묻힘). 그래서 결합 전에 두 raw 값을 population(같은 호출에서
       처리되는 전체 선박, used_event_count > 0인 선박만) 기준
       z-score로 정규화한 뒤 가중합한다:
         revisit_zscore = (revisit_raw - population_mean) / population_std
         crowding_zscore = (crowding_raw - population_mean) / population_std
         axis_a_pressure_raw = revisit_weight * revisit_zscore
                              + congestion_weight * crowding_zscore
                              + interaction_weight * revisit_zscore * crowding_zscore
       (상호작용항도 정규화된 값끼리 곱한다 — raw 값끼리 곱하면 스케일
       불균형이 그대로 남는다.) population 표준편차가 0이면(모든 값이
       동일한 극단적으로 작은 배치) z-score는 0.0으로 처리한다.
    5. raw 값·z-score·결합값을 선박 단위로 집계해 반환한다.
       `revisit_interval_raw`/`crowding_pressure_raw`/`interaction_raw`
       필드는 정규화 이전의 진짜 raw 값 그대로다(화면·진단 스크립트가
       원래 단위로 보여줄 수 있어야 하므로) — 결합에 실제로 쓰이는 값은
       `revisit_zscore`/`crowding_zscore`/`interaction_zscore` 필드다.

주의:
    - 이 모듈은 유사 선박군 내 백분위 정규화 이전의 원값(raw value) 산출까지만
      담당한다. 절대 점수가 아니며, 점수조립 단계에서 유사 선박군 내 상대값으로
      다시 정규화되어야 한다. z-score 정규화는 이 최종 백분위 변환과는 별개
      단계다 — z-score는 "재방문압력 대 혼잡압력"의 상대적 기여 균형을 맞추는
      것이고, 최종 백분위는 "이 선박이 유사군 내 어디쯤인지"를 정하는 것이다.
    - 격자 크기(GRID_CELL_SIZE_DEG=0.1도)와 재방문압력 변환 스케일
      (REVISIT_PRESSURE_SCALE_HOURS=60시간)은 확정값이다(CLAUDE.md
      "확정된 규칙" 8번 참고 — data_new/ 실측 275,782건으로 격자 후보
      0.02~1.0도를 비교해 근거를 마련함). 결합 가중치 3개(AXIS_A_REVISIT_WEIGHT,
      AXIS_A_CONGESTION_WEIGHT, AXIS_A_INTERACTION_WEIGHT)는 여전히 팀에서
      확정하지 않은 잠정값이며 검증 후 교체해야 한다 — 다만 이제는 z-score로
      스케일이 맞춰진 값에 적용되므로, 적어도 "50:50"이라는 이름이 실제
      기여비중과 크게 어긋나지는 않는다(실측: 재방문압력 평균 기여비중이
      정규화 전 1.08% → 정규화 후 약 40%로 개선됨).
    - z-score보다 더 정확한 방법은 유사군 내 백분위 정규화다(실측으로 비교
      시 기여비중이 약 48%까지 개선됨, z-score의 40%보다 낫다) — 다만 이
      방식은 결합 단계에서 유사군 정보가 필요해 지금 구조(유사군은 점수조립
      단계에서만 있음) 변경이 필요하다. 시간 대비 효과를 고려해 우선
      z-score를 택했고, 유사군 백분위 방식은 향후 개선 후보로 남겨둔다.
    - 혼잡가중압력은 "자원이 실제로 풍부해서 몰린 경우"와 "단순히 접근이 편한
      지형이라 몰린 경우"를 구분하지 못한다 (기획서 리스크 ⑥번). 추후 CPUE 등
      자원 밀도 대리지표로 보정이 필요하다.
"""

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
from shapely.geometry import Point

# 격자 한 변의 크기 (도 단위, 위경도 기준) — 확정값(CLAUDE.md
# 확정된 규칙 8번). data_new/ 실측 275,782건으로 0.02~1.0도 후보를 비교해
# 재방문 검출률·격자당 평균 이벤트 수를 근거로 정함(0.25도부터 검출률이
# 91%대로 포화되며 격자당 이벤트가 급증해 "재방문"의 의미가 흐려짐).
GRID_CELL_SIZE_DEG = 0.1

# "인접 격자"로 볼 체비쇼프 거리(칸 수). 1이면 자기 자신 + 상하좌우/대각선 8방향
ADJACENT_GRID_CHEBYSHEV_DISTANCE = 1

# 재방문간격(시간) -> 압력 점수 변환식의 파라미터.
#   revisit_pressure = REVISIT_PRESSURE_SCALE_HOURS / (interval_hours + REVISIT_INTERVAL_EPSILON_HOURS)
# interval이 REVISIT_PRESSURE_SCALE_HOURS(시간)일 때 압력이 대략 1.0이 되도록
# 스케일링한다. 0시간 나눗셈 방지를 위해 EPSILON을 더한다.
# 확정값(CLAUDE.md 확정된 규칙 8번) — GRID_CELL_SIZE_DEG=0.1도
# 기준 실측 재방문 간격 중앙값(59.1시간)에 맞춤. 기존 잠정값 24시간은 실측
# 중앙값의 1/3도 안 돼 대부분의 선박이 압력 0.1~0.3대에 몰려 변별력이 거의
# 없었다.
REVISIT_PRESSURE_SCALE_HOURS = 60.0
REVISIT_INTERVAL_EPSILON_HOURS = 1.0

# A축 raw 값 결합 시 재방문압력/혼잡압력/상호작용항 가중치 — 잠정값.
# interaction 항은 "혼잡한 곳을 반복 착취"하는 경우를 단순 합보다 더 크게
# 반영하기 위한 것 (revisit_raw * congestion_raw에 곱해짐).
AXIS_A_REVISIT_WEIGHT = 0.5
AXIS_A_CONGESTION_WEIGHT = 0.5
AXIS_A_INTERACTION_WEIGHT = 0.1

GridCell = Tuple[int, int]


@dataclass
class SkippedEvent:
    """좌표/시각 결측 등으로 계산에서 제외된 이벤트."""

    event_id: Optional[str]
    reason: str


@dataclass
class VesselAxisAResult:
    """선박 한 척에 대한 A축 raw 산출 결과."""

    vessel_id: str
    used_event_count: int
    skipped_events: List[SkippedEvent] = field(default_factory=list)
    avg_revisit_interval_hours: Optional[float] = None
    revisit_interval_raw: float = 0.0
    crowding_pressure_raw: float = 0.0
    interaction_raw: float = 0.0
    # population(같은 호출에서 처리된 전체 선박) 기준 z-score 정규화된 값.
    # axis_a_pressure_raw는 raw가 아니라 이 필드들로 결합된다 — 모듈
    # docstring 4번 참고.
    revisit_zscore: float = 0.0
    crowding_zscore: float = 0.0
    interaction_zscore: float = 0.0
    axis_a_pressure_raw: float = 0.0


def _parse_start_datetime(event: dict) -> Optional[datetime]:
    start = event.get("start")
    if not start:
        return None
    try:
        return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None


def _grid_cell_for_point(latitude: float, longitude: float, cell_size_deg: float) -> GridCell:
    """위경도를 (row, col) 격자 인덱스로 변환."""
    return (int(latitude // cell_size_deg), int(longitude // cell_size_deg))


def _neighbor_cells(
    cell: GridCell, chebyshev_distance: int = ADJACENT_GRID_CHEBYSHEV_DISTANCE
) -> List[GridCell]:
    """주어진 격자와 그 인접 격자(자기 자신 포함) 목록."""
    row, col = cell
    d = chebyshev_distance
    return [(row + dr, col + dc) for dr in range(-d, d + 1) for dc in range(-d, d + 1)]


def _prepare_events(
    events: List[dict], cell_size_deg: float
) -> Tuple[gpd.GeoDataFrame, Dict[str, List[SkippedEvent]]]:
    """
    이벤트 리스트를 (유효 이벤트를 담은 GeoDataFrame, 선박별 스킵 이벤트 목록)으로 분리한다.

    geopandas.GeoDataFrame으로 좌표를 담아 격자 인덱스(gridCell 컬럼)를 계산한다.
    """
    valid_rows = []
    skipped: Dict[str, List[SkippedEvent]] = {}

    for event in events:
        vessel_id = event.get("vesselId")
        lat = event.get("latitude")
        lon = event.get("longitude")
        start_dt = _parse_start_datetime(event)

        reason = None
        if lat is None or lon is None:
            reason = "missing_coordinates"
        elif start_dt is None:
            reason = "missing_or_invalid_start"

        if reason:
            skipped.setdefault(vessel_id, []).append(
                SkippedEvent(event_id=event.get("eventId"), reason=reason)
            )
            continue

        valid_rows.append(
            {
                "eventId": event.get("eventId"),
                "vesselId": vessel_id,
                "startDatetime": start_dt,
                "geometry": Point(lon, lat),
            }
        )

    if not valid_rows:
        empty = gpd.GeoDataFrame(columns=["eventId", "vesselId", "startDatetime", "geometry", "gridCell"])
        return empty, skipped

    gdf = gpd.GeoDataFrame(valid_rows, geometry="geometry", crs="EPSG:4326")
    gdf["gridCell"] = [_grid_cell_for_point(geom.y, geom.x, cell_size_deg) for geom in gdf.geometry]
    return gdf, skipped


def _compute_revisit_intervals_hours(vessel_events_sorted: List[dict]) -> List[float]:
    """
    선박 한 척의 시간순 정렬된 이벤트들에 대해, 동일/인접 격자에서의 직전
    방문과의 시간 간격(시간 단위) 목록을 반환한다.

    vessel_events_sorted: [{"startDatetime": datetime, "gridCell": (row, col)}, ...]
        (startDatetime 오름차순으로 정렬되어 있어야 한다)
    """
    last_visit: Dict[GridCell, datetime] = {}
    intervals: List[float] = []

    for event in vessel_events_sorted:
        cell = event["gridCell"]
        start_dt = event["startDatetime"]

        candidate_times = [
            last_visit[neighbor] for neighbor in _neighbor_cells(cell) if neighbor in last_visit
        ]
        if candidate_times:
            most_recent = max(candidate_times)
            interval_hours = (start_dt - most_recent).total_seconds() / 3600.0
            if interval_hours >= 0:
                intervals.append(interval_hours)

        if cell not in last_visit or start_dt > last_visit[cell]:
            last_visit[cell] = start_dt

    return intervals


def revisit_pressure_from_interval(
    avg_interval_hours: Optional[float],
    scale_hours: float = REVISIT_PRESSURE_SCALE_HOURS,
    epsilon_hours: float = REVISIT_INTERVAL_EPSILON_HOURS,
) -> float:
    """평균 재방문간격(시간)을 압력 점수로 변환한다. 간격이 짧을수록 값이 크다.

    재방문 이력이 없으면(avg_interval_hours가 None) 0.0을 반환한다.
    """
    if avg_interval_hours is None:
        return 0.0
    if avg_interval_hours < 0:
        raise ValueError("avg_interval_hours는 0 이상이어야 합니다.")
    return scale_hours / (avg_interval_hours + epsilon_hours)


def compute_axis_a_pressure(
    events: List[dict],
    cell_size_deg: float = GRID_CELL_SIZE_DEG,
    revisit_weight: float = AXIS_A_REVISIT_WEIGHT,
    congestion_weight: float = AXIS_A_CONGESTION_WEIGHT,
    interaction_weight: float = AXIS_A_INTERACTION_WEIGHT,
) -> Dict[str, VesselAxisAResult]:
    """
    조업 이벤트 리스트로부터 선박별 A축(자원 압력) raw 값을 산출한다.

    Args:
        events: data/gfw_client.py의 normalized event 형태 딕셔너리 리스트
            (eventId, vesselId, start, latitude, longitude 등). 여러 선박의
            이벤트가 섞여 있어야 혼잡가중압력을 제대로 계산할 수 있다.
        cell_size_deg: 격자 한 변의 크기 (도 단위)
        revisit_weight: 결합 시 재방문압력(z-score 정규화됨)에 부여할 가중치
        congestion_weight: 결합 시 혼잡압력(다른 선박 기준, z-score 정규화됨)에
            부여할 가중치
        interaction_weight: "재방문압력 × 혼잡압력"(둘 다 z-score) 상호작용항에
            부여할 가중치. 혼잡한 해역을 반복 방문하는 경우를 단순 가중합보다
            더 크게 반영한다.

    Returns:
        {vessel_id: VesselAxisAResult} 딕셔너리. 이 호출에 넘긴 events 전체가
        z-score 정규화의 population이므로, 같은 선박이라도 다른 events 집합과
        함께 호출하면 axis_a_pressure_raw 값이 달라질 수 있다.
    """
    if cell_size_deg <= 0:
        raise ValueError("cell_size_deg는 0보다 커야 합니다.")

    gdf, skipped_by_vessel = _prepare_events(events, cell_size_deg)

    vessel_ids = set(gdf["vesselId"]) if not gdf.empty else set()
    vessel_ids |= set(skipped_by_vessel.keys())
    vessel_ids.discard(None)

    density_by_cell = Counter(gdf["gridCell"]) if not gdf.empty else Counter()
    # 선박별로 자기 자신이 각 격자에 남긴 이벤트 수 — 혼잡압력 계산 시 이만큼을
    # 밀도에서 빼서 "다른 배들만의 밀도"를 구한다.
    own_vessel_cell_counts = (
        Counter(zip(gdf["vesselId"], gdf["gridCell"])) if not gdf.empty else Counter()
    )

    # 선박마다 `gdf[gdf["vesselId"] == vessel_id]`로 전체 이벤트를 다시 훑으면
    # 실제 스냅샷(약 91만 건 × 약 1만 선박)에서 요청 시간이 수 분 이상으로
    # 늘어난다. groupby 인덱스를 한 번 만든 뒤 동일한 행 묶음을 재사용한다.
    # 계산식과 행 내용은 기존과 같고, 선박별 조회 비용만 O(전체 이벤트)에서
    # O(해당 선박 이벤트)로 줄인다.
    grouped_by_vessel = gdf.groupby("vesselId", sort=False) if not gdf.empty else None
    grouped_vessel_ids = set(grouped_by_vessel.groups) if grouped_by_vessel is not None else set()
    empty_gdf = gdf.iloc[0:0]

    # 1단계: 선박별 raw 값(재방문압력/혼잡압력)만 먼저 계산한다. population
    # 통계(평균·표준편차)를 구하려면 전체 선박의 raw 값이 먼저 다 있어야
    # 하므로, 이 시점에는 아직 결합하지 않는다.
    raw_by_vessel: Dict[str, dict] = {}
    for vessel_id in vessel_ids:
        vessel_gdf = (
            grouped_by_vessel.get_group(vessel_id)
            if grouped_by_vessel is not None and vessel_id in grouped_vessel_ids
            else empty_gdf
        )
        vessel_events_sorted = sorted(
            (
                {"startDatetime": row.startDatetime, "gridCell": row.gridCell}
                for row in vessel_gdf.itertuples()
            ),
            key=lambda e: e["startDatetime"],
        )

        intervals = _compute_revisit_intervals_hours(vessel_events_sorted)
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        revisit_raw = revisit_pressure_from_interval(avg_interval)

        if vessel_events_sorted:
            other_vessel_densities = [
                density_by_cell[e["gridCell"]] - own_vessel_cell_counts[(vessel_id, e["gridCell"])]
                for e in vessel_events_sorted
            ]
            congestion_raw = sum(other_vessel_densities) / len(other_vessel_densities)
        else:
            congestion_raw = 0.0

        raw_by_vessel[vessel_id] = {
            "used_event_count": len(vessel_events_sorted),
            "avg_interval": avg_interval,
            "revisit_raw": revisit_raw,
            "congestion_raw": congestion_raw,
        }

    # 2단계: population 통계. z-score 정규화는 이벤트가 실제로 있는 선박
    # (used_event_count > 0)만 대상으로 한다 — 이벤트가 없는 선박은 raw 값이
    # 항상 0이라 population 분포를 왜곡한다.
    revisit_population = [v["revisit_raw"] for v in raw_by_vessel.values() if v["used_event_count"] > 0]
    congestion_population = [v["congestion_raw"] for v in raw_by_vessel.values() if v["used_event_count"] > 0]

    def _population_stats(values: List[float]) -> Tuple[float, float]:
        if not values:
            return 0.0, 0.0
        return statistics.mean(values), statistics.pstdev(values)

    revisit_mean, revisit_std = _population_stats(revisit_population)
    congestion_mean, congestion_std = _population_stats(congestion_population)

    def _zscore(value: float, mean: float, std: float) -> float:
        return (value - mean) / std if std > 0 else 0.0

    # 3단계: z-score로 정규화한 뒤 결합한다. revisit_interval_raw/
    # crowding_pressure_raw/interaction_raw 필드는 정규화 이전의 진짜 raw
    # 값 그대로 남긴다(화면·진단 스크립트가 원래 단위로 보여줄 수 있어야
    # 하므로) — 결합에는 z-score 필드만 쓴다.
    results: Dict[str, VesselAxisAResult] = {}
    for vessel_id, raw in raw_by_vessel.items():
        revisit_raw = raw["revisit_raw"]
        congestion_raw = raw["congestion_raw"]

        if raw["used_event_count"] > 0:
            revisit_zscore = _zscore(revisit_raw, revisit_mean, revisit_std)
            crowding_zscore = _zscore(congestion_raw, congestion_mean, congestion_std)
        else:
            revisit_zscore = 0.0
            crowding_zscore = 0.0
        interaction_zscore = revisit_zscore * crowding_zscore

        combined_raw = (
            revisit_weight * revisit_zscore
            + congestion_weight * crowding_zscore
            + interaction_weight * interaction_zscore
        )

        results[vessel_id] = VesselAxisAResult(
            vessel_id=vessel_id,
            used_event_count=raw["used_event_count"],
            skipped_events=skipped_by_vessel.get(vessel_id, []),
            avg_revisit_interval_hours=raw["avg_interval"],
            revisit_interval_raw=revisit_raw,
            crowding_pressure_raw=congestion_raw,
            interaction_raw=revisit_raw * congestion_raw,
            revisit_zscore=revisit_zscore,
            crowding_zscore=crowding_zscore,
            interaction_zscore=interaction_zscore,
            axis_a_pressure_raw=combined_raw,
        )

    return results
