"""
담당: 김준기, 오동규

유사 선박군 그룹핑 + 표본 수 판정.

참고: CLAUDE.md "확정된 규칙" 3번 - 혼잡압력 비교 대상은 유사 선박군(톤수대 ×
어업종 × 해역 × 계절) 기준. 이 모듈은 그 그룹 키를 만들고, 그룹별 표본이
충분한지 판정한다. 표본이 부족하면 백분위 정규화가 의미 없어지므로(집단이
몇 척 안 되는데 "상위 17%"라고 말하는 건 과장이다) — score 조립 단계에서
이 판정 결과로 status(예: `insufficientSample`, `data/mock/README_mock_data
제안.md` 5번 참고)를 정한다.

주의 (미확정 파라미터, CLAUDE.md "미확정 항목" 참고):
    - 톤수대 폭(TONNAGE_BAND_WIDTH) — 여전히 잠정값.
    - 유사군 최소 표본 기준(MIN_PEER_GROUP_SAMPLE_SIZE) — 2026-08-18 20→10으로
      확정(CLAUDE.md 확정된 규칙 참고). data_new/ 실측(1,079개 그룹, 중앙값
      2척) 기준 20척은 커버리지 42.6%, 10척은 61.0%였다 — 명확한 "무릎점"은
      없어 순수 데이터로는 정답이 안 나오는 트레이드오프였고, 해커톤 완성품
      제출 시한 압박 속에서 "통계적으로 최소 방어 가능한 하한(10척=10%
      해상도)"과 "실산출 커버리지"를 절충해 팀이 결정했다. 근본 원인(그룹이
      과도하게 잘게 쪼개지는 것)은 gearType 처리 방식과 얽혀 있어(같은 날
      다른 항목 참고), 이후 개선 여지가 크다.

주의 (해역/계절 키의 임시성):
    "해역" 키는 GFW 이벤트에 깨끗한 EEZ/해역 필드가 아직 없어서(data/gfw_client.py
    참고 — regions는 mpa 존재 여부 판정에만 씀), 넓은 격자(REGION_GRID_SIZE_DEG)로
    대신 근사한다. axis_a_pressure.py의 GRID_CELL_SIZE_DEG(0.05, 조업압력 촘촘
    격자)와는 목적이 달라 더 넓게 잡았다. 정식 해역 taxonomy가 확보되면 교체
    필요.
    "계절" 키는 상반기/하반기(1~6월/7~12월)로 근사한다. data/rules_common.md
    5번에서 폐기된 "자동 조회기간 계산" 규칙과는 무관하다 — 이건 수집 범위가
    아니라 이미 모인 이벤트를 그룹화하는 기준일 뿐이다.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 톤수대 폭(톤) — 잠정값
TONNAGE_BAND_WIDTH = 10.0

# 유사군 최소 표본 기준(척) — 2026-08-18 확정(10척). 이보다 적으면 백분위
# 정규화 대신 insufficientSample로 판정한다. 근거는 모듈 docstring 참고.
MIN_PEER_GROUP_SAMPLE_SIZE = 10

# "해역" 근사용 격자 크기(도 단위) — 잠정값.
REGION_GRID_SIZE_DEG = 1.0

PeerGroupKey = Tuple[Optional[int], Optional[str], Optional[Tuple[int, int]], Optional[str]]


@dataclass
class PeerGroup:
    key: PeerGroupKey
    vessel_ids: List[str] = field(default_factory=list)

    @property
    def sample_size(self) -> int:
        return len(self.vessel_ids)

    def has_sufficient_sample(self, min_size: int = MIN_PEER_GROUP_SAMPLE_SIZE) -> bool:
        return self.sample_size >= min_size


def tonnage_band(tonnage: Optional[float], band_width: float = TONNAGE_BAND_WIDTH) -> Optional[int]:
    """톤수를 밴드 하한값(정수)으로 변환한다. 톤수가 없으면 그룹을 만들 수
    없으므로 None을 반환한다."""
    if tonnage is None:
        return None
    if tonnage < 0:
        raise ValueError("tonnage는 0 이상이어야 합니다.")
    return int(tonnage // band_width * band_width)


def gear_type_key(fishing_type) -> Optional[str]:
    """GFW fishingType(gear type 리스트)에서 그룹핑용 대표 키를 뽑는다.
    리스트가 여러 개면 정렬해 첫 값을 대표로 쓴다 — 원본 리스트의 순서가
    그룹핑 결과에 영향을 주면 안 되기 때문."""
    if not fishing_type:
        return None
    if isinstance(fishing_type, str):
        return fishing_type
    values = sorted(v for v in fishing_type if v)
    return values[0] if values else None


def region_key(
    latitude: Optional[float], longitude: Optional[float], grid_size_deg: float = REGION_GRID_SIZE_DEG
) -> Optional[Tuple[int, int]]:
    if latitude is None or longitude is None:
        return None
    return (int(latitude // grid_size_deg), int(longitude // grid_size_deg))


def season_key(start) -> Optional[str]:
    """이벤트 시작 시각으로부터 상반기/하반기 키(예: "2026-H1")를 만든다."""
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(start, datetime):
        return None
    return f"{start.year}-H1" if start.month <= 6 else f"{start.year}-H2"


def _representative_event(events_for_vessel: List[dict]) -> Optional[dict]:
    """선박 한 척의 이벤트들 중 해역/계절 키의 대표값으로 쓸 이벤트를 고른다.
    가장 최근 이벤트를 대표로 쓴다 — 최신 조업 위치/시기가 지금 평가 기간과
    가장 관련 있기 때문이다."""
    valid = [e for e in events_for_vessel if e.get("start")]
    if not valid:
        return None
    return max(valid, key=lambda e: e["start"])


def build_peer_groups(
    vessels: List[dict],
    events: List[dict],
    band_width: float = TONNAGE_BAND_WIDTH,
    grid_size_deg: float = REGION_GRID_SIZE_DEG,
) -> Tuple[Dict[PeerGroupKey, PeerGroup], Dict[str, PeerGroupKey]]:
    """선박 목록 + 이벤트 목록으로부터 유사 선박군(톤수대×어업종×해역×계절)을 만든다.

    Args:
        vessels: data/build_enriched_vessel_population.py 산출물 형태의 딕셔너리
            리스트 (vesselId, tonnage, fishingType 등).
        events: data/gfw_client.py 정규화 이벤트 형태 (vesselId, start, latitude,
            longitude).

    Returns:
        (groups, vessel_to_key) — groups는 {그룹 키: PeerGroup}, vessel_to_key는
        {vesselId: 그룹 키}. vessel_to_key를 별도로 반환하는 이유는 특정 선박이
        속한 그룹을 찾을 때 매번 전체 그룹을 순회하지 않기 위함이다.
    """
    events_by_vessel: Dict[str, List[dict]] = defaultdict(list)
    for event in events:
        vessel_id = event.get("vesselId")
        if vessel_id:
            events_by_vessel[vessel_id].append(event)

    groups: Dict[PeerGroupKey, PeerGroup] = {}
    vessel_to_key: Dict[str, PeerGroupKey] = {}

    for vessel in vessels:
        vessel_id = vessel.get("vesselId")
        if not vessel_id:
            continue

        representative = _representative_event(events_by_vessel.get(vessel_id, []))

        key: PeerGroupKey = (
            tonnage_band(vessel.get("tonnage"), band_width),
            gear_type_key(vessel.get("fishingType")),
            region_key(
                representative.get("latitude") if representative else None,
                representative.get("longitude") if representative else None,
                grid_size_deg,
            ),
            season_key(representative.get("start") if representative else None),
        )

        groups.setdefault(key, PeerGroup(key=key)).vessel_ids.append(vessel_id)
        vessel_to_key[vessel_id] = key

    return groups, vessel_to_key


def peer_group_for_vessel(
    vessel_id: str,
    groups: Dict[PeerGroupKey, PeerGroup],
    vessel_to_key: Dict[str, PeerGroupKey],
) -> Optional[PeerGroup]:
    """build_peer_groups()의 반환값으로 특정 선박이 속한 그룹을 조회한다."""
    key = vessel_to_key.get(vessel_id)
    if key is None:
        return None
    return groups.get(key)
