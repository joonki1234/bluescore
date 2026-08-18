"""담당: 최지희

버전 고정 GFW 스냅샷을 실제 A축 산출 파이프라인에 연결한다.

B축은 실데이터 검증이 끝나지 않았으므로 이 어댑터가 총점이나 금리구간을 만들지
않는다. 호출자는 A축만 `real`, B축은 `unavailable`, 전체 상태는 `partial`로
표시해야 한다.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from score.axis_a_pressure import compute_axis_a_pressure
from score.peer_grouping import MIN_PEER_GROUP_SAMPLE_SIZE, build_peer_groups, peer_group_for_vessel
from score.score_assembly import raw_to_score, score_status_for_group


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 2026-08-18: data_new/(김태윤) 스냅샷으로 전환 — 구 data/의 31,605척(확정매칭
# 순도 9.5%) 대신 EEZ 제한 모집단 5,323척(사람 라벨링 실측 정밀도 약 75%,
# data_new/README.md 참고)을 쓴다. 이벤트는 data_new/processed/의 산출물을
# 그대로 쓰고, 선박은 score/scripts/convert_data_new_vessels.py로 미리 평판화
# 해둔 파생 파일을 쓴다(vesselId/tonnage/fishingType 등 이 모듈이 기대하는
# 평평한 스키마로 변환 — 원본 final_vessel_matches.jsonl은 톤수가
# tac.tonnageGtTac처럼 중첩·문자열이라 그대로 못 씀).
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"
DEFAULT_VESSELS_PATH = PROJECT_ROOT / "data_new" / "processed" / "vessels_for_score.jsonl.gz"


@dataclass(frozen=True)
class RealAxisAResult:
    vessel_id: str
    status: str
    axis_a_score: Optional[float]
    axis_a_raw: Optional[float]
    peer_count: int
    used_event_count: int
    skipped_event_count: int
    vessel: dict
    matching_method: str
    matching_reason: Optional[str]


def compute_axis_a_for_vessel(
    vessel_id: str,
    vessels: List[dict],
    events: List[dict],
    *,
    min_peer_size: int = MIN_PEER_GROUP_SAMPLE_SIZE,
) -> RealAxisAResult:
    """메모리의 스냅샷 레코드를 A축→유사군→백분위 점수까지 연결한다."""
    vessel_by_id = {v.get("vesselId"): v for v in vessels if v.get("vesselId")}
    axis_results = compute_axis_a_pressure(events)
    groups, vessel_to_key = build_peer_groups(vessels, events)
    return _result_from_context(
        vessel_id,
        vessel_by_id,
        axis_results,
        groups,
        vessel_to_key,
        min_peer_size=min_peer_size,
    )


def _result_from_context(
    vessel_id: str,
    vessel_by_id: Dict[str, dict],
    axis_results: dict,
    groups: dict,
    vessel_to_key: dict,
    *,
    min_peer_size: int,
) -> RealAxisAResult:
    vessel = vessel_by_id.get(vessel_id)
    if vessel is None:
        raise KeyError(vessel_id)

    axis_result = axis_results.get(vessel_id)
    if axis_result is None:
        return RealAxisAResult(
            vessel_id=vessel_id,
            status="matchingFailed",
            axis_a_score=None,
            axis_a_raw=None,
            peer_count=0,
            used_event_count=0,
            skipped_event_count=0,
            vessel=vessel,
            matching_method="snapshotVesselId",
            matching_reason="스냅샷에 해당 선박의 유효 조업 이벤트가 없습니다.",
        )

    group = peer_group_for_vessel(vessel_id, groups, vessel_to_key)
    peer_count = group.sample_size if group else 0
    status = score_status_for_group(group, min_peer_size) if group else "insufficientSample"

    peer_raws = []
    if group:
        peer_raws = [
            axis_results[peer_id].axis_a_pressure_raw
            for peer_id in group.vessel_ids
            if peer_id in axis_results
        ]
    if len(peer_raws) < min_peer_size:
        status = "insufficientSample"

    axis_score = (
        raw_to_score(axis_result.axis_a_pressure_raw, peer_raws)
        if status == "success"
        else None
    )
    has_specs = vessel.get("tonnage") is not None and bool(vessel.get("fishingType"))
    return RealAxisAResult(
        vessel_id=vessel_id,
        status="partial" if status == "success" else status,
        axis_a_score=axis_score,
        axis_a_raw=axis_result.axis_a_pressure_raw,
        peer_count=peer_count,
        used_event_count=axis_result.used_event_count,
        skipped_event_count=len(axis_result.skipped_events),
        vessel=vessel,
        matching_method="snapshotVesselId",
        matching_reason=None if has_specs else "톤수 또는 어업종 메타데이터가 비어 있습니다.",
    )


def _load_jsonl_gz(path: Path) -> List[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


class RealAxisAAdapter:
    def __init__(
        self,
        events_path: Path = DEFAULT_EVENTS_PATH,
        vessels_path: Path = DEFAULT_VESSELS_PATH,
    ) -> None:
        self.events_path = Path(events_path)
        self.vessels_path = Path(vessels_path)

    @property
    def available(self) -> bool:
        return self.events_path.exists() and self.vessels_path.exists()

    @lru_cache(maxsize=1)
    def _vessel_records(self) -> List[dict]:
        if not self.vessels_path.exists():
            raise FileNotFoundError(str(self.vessels_path))
        return _load_jsonl_gz(self.vessels_path)

    @lru_cache(maxsize=1)
    def _event_records(self) -> List[dict]:
        if not self.events_path.exists():
            raise FileNotFoundError(str(self.events_path))
        return _load_jsonl_gz(self.events_path)

    @lru_cache(maxsize=1)
    def _records(self) -> tuple:
        return self._vessel_records(), self._event_records()

    @lru_cache(maxsize=1)
    def list_vessels(self) -> List[dict]:
        return self._vessel_records()

    @lru_cache(maxsize=128)
    def score(self, vessel_id: str) -> RealAxisAResult:
        vessel_by_id, axis_results, groups, vessel_to_key = self._computed_context()
        return _result_from_context(
            vessel_id,
            vessel_by_id,
            axis_results,
            groups,
            vessel_to_key,
            min_peer_size=MIN_PEER_GROUP_SAMPLE_SIZE,
        )

    @lru_cache(maxsize=1)
    def _computed_context(self) -> tuple:
        """전체 스냅샷 계산은 프로세스 최초 한 번만 수행하고 선박 조회가 공유한다."""
        vessels, events = self._records()
        vessel_by_id = {v.get("vesselId"): v for v in vessels if v.get("vesselId")}
        axis_results = compute_axis_a_pressure(events)
        groups, vessel_to_key = build_peer_groups(vessels, events)
        return vessel_by_id, axis_results, groups, vessel_to_key
