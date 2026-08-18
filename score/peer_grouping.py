"""톤수대·어업종·해역·계절별 유사 선박군을 만들고 표본 수를 판정한다.

최소 표본은 10척이며, 미만이면 백분위 정규화 대신 `insufficientSample`로
처리한다. 톤수대 폭은 잠정값이다. 해역은 전용 필드가 없어 넓은 격자로,
계절은 상반기/하반기로 근사한다.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 톤수대 폭(톤) — 잠정값
TONNAGE_BAND_WIDTH = 10.0

# 유사군 최소 표본 기준(척, 10). 이보다 적으면 백분위 정규화 대신
# insufficientSample로 판정한다. 근거는 모듈 docstring 참고.
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
