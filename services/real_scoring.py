"""담당: 최지희

버전 고정 GFW 스냅샷을 실제 A축·B축 산출 파이프라인에 연결한다.

B축은 `score/real_axis_b_scoring.py`가 B축 raw(잔차)를 내고, 여기서 A축과 같은
유사 선박군으로 백분위 변환한다. **알려진 한계(화면에 정직하게 표기할 것)**:
해양기상 단위(풍속 m/s)는 공식 확인이 아니라 정황 추정, 유속 단위는 추정
근거조차 없음, gearType은 TAC 매칭된 선박만 채워짐, 톤수 매칭 커버리지
43.4%뿐이라 B축 자체가 대부분 선박에서 계산되지 않음(그 경우 A축만 `partial`
로 유지되고 이전과 동일하게 동작 — B축 연결이 A축 단독 경로를 깨지 않는다).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from score.axis_a_pressure import compute_axis_a_pressure
from score.axis_b_baseline import VesselAxisBResult
from score.peer_grouping import MIN_PEER_GROUP_SAMPLE_SIZE, build_peer_groups, peer_group_for_vessel
from score.real_axis_b_scoring import compute_axis_b_results
from score.score_assembly import raw_to_score, score_status_for_group
from score.shap_factors import axis_a_factor_shares


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# data_new/ 스냅샷을 쓴다 — 구 data/보다 매칭 정밀도가 높다(data_new/README.md
# 참고). 선박은 score/scripts/convert_data_new_vessels.py로 이 모듈이 기대하는
# 평평한 스키마(vesselId/tonnage/fishingType)로 미리 변환해둔 파생 파일이다 —
# 원본 final_vessel_matches.jsonl은 톤수가 중첩·문자열이라 그대로 못 쓴다.
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
    # B축 연결 필드 — 전부 기본값 있어 기존 호출부는 안 건드려도 됨.
    axis_b_score: Optional[float] = None
    axis_b_raw: Optional[float] = None
    axis_b_used_row_count: Optional[int] = None
    # B축 SHAP 대신 쓰는 산출 근거 두 값(실측 추정 vs 기준선 예측 연료, kg).
    # axis_b_raw = estimated - expected와 정확히 같다.
    axis_b_estimated_fuel_kg: Optional[float] = None
    axis_b_expected_fuel_kg: Optional[float] = None
    # A축 요인 기여도(SHAP)만 연결한다. B축은 score/shap_factors.py 모듈
    # docstring 참고 — "점수"가 아니라 "기준선 조건"만 설명 가능한 의미론적
    # 제약으로 B축 SHAP 자체를 들어냈다.
    shap_factors: List[dict] = field(default_factory=list)


def _axis_b_score_for_vessel(
    vessel_id: str,
    group,
    axis_b_results: Optional[Dict[str, VesselAxisBResult]],
    min_peer_size: int,
):
    """B축 raw(잔차)를 같은 유사 선박군 안에서 백분위로 바꾸고, 그 잔차를
    만든 두 값(실측 기반 추정 연료 vs 유사조건 기준선 예측 연료)도 같이 낸다.

    A축 상태(group)는 이미 확정된 뒤 호출되므로, 여기서는 "B축 표본이 그
    그룹 안에서 따로 충분한가"만 별도로 판단한다 — 톤수 매칭 커버리지가
    43.4%뿐이라 A축 표본은 충분해도 B축 표본은 부족한 그룹이 많다.

    estimated_fuel_kg/expected_fuel_kg는 peer 표본 부족·group=None이어도
    이 선박 하나의 물리식/LightGBM 계산 결과라 항상 낼 수 있다 — B축 SHAP을
    못 쓰는 대신(순환성 문제, score/shap_factors.py 참고) 점수 대신 근거가
    된 두 숫자를 그대로 보여준다.
    """
    if not axis_b_results:
        return None, None, None, None, None

    this_result = axis_b_results.get(vessel_id)
    if this_result is None or this_result.used_row_count == 0:
        return None, None, None, None, None

    estimated_fuel_kg = this_result.estimated_fuel_kg
    expected_fuel_kg = this_result.expected_fuel_kg

    if group is None:
        return None, this_result.residual_raw, this_result.used_row_count, estimated_fuel_kg, expected_fuel_kg

    peer_raws = [
        axis_b_results[peer_id].residual_raw
        for peer_id in group.vessel_ids
        if peer_id in axis_b_results and axis_b_results[peer_id].used_row_count > 0
    ]
    if len(peer_raws) < min_peer_size:
        return (
            None, this_result.residual_raw, this_result.used_row_count,
            estimated_fuel_kg, expected_fuel_kg,
        )

    axis_b_score = raw_to_score(this_result.residual_raw, peer_raws)
    return (
        axis_b_score, this_result.residual_raw, this_result.used_row_count,
        estimated_fuel_kg, expected_fuel_kg,
    )


def compute_axis_a_for_vessel(
    vessel_id: str,
    vessels: List[dict],
    events: List[dict],
    *,
    min_peer_size: int = MIN_PEER_GROUP_SAMPLE_SIZE,
    axis_b_results: Optional[Dict[str, VesselAxisBResult]] = None,
) -> RealAxisAResult:
    """메모리의 스냅샷 레코드를 A축(+가능하면 B축)→유사군→백분위 점수까지 연결한다."""
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
        axis_b_results=axis_b_results,
    )


def _result_from_context(
    vessel_id: str,
    vessel_by_id: Dict[str, dict],
    axis_results: dict,
    groups: dict,
    vessel_to_key: dict,
    *,
    min_peer_size: int,
    axis_b_results: Optional[Dict[str, VesselAxisBResult]] = None,
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
    axis_b_score, axis_b_raw, axis_b_used_row_count, axis_b_estimated_fuel_kg, axis_b_expected_fuel_kg = (
        _axis_b_score_for_vessel(
            vessel_id, group if status == "success" else None, axis_b_results, min_peer_size
        )
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
        axis_b_score=axis_b_score,
        axis_b_raw=axis_b_raw,
        axis_b_used_row_count=axis_b_used_row_count,
        axis_b_estimated_fuel_kg=axis_b_estimated_fuel_kg,
        axis_b_expected_fuel_kg=axis_b_expected_fuel_kg,
        # status(insufficientSample 포함)와 무관하게 채운다 — raw 분해
        # 자체는 유사군 표본과 무관하게 항상 계산 가능하다.
        shap_factors=axis_a_factor_shares(axis_result),
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

    @lru_cache(maxsize=1)
    def status_ranked_vessels(self) -> List[Tuple[bool, dict, str]]:
        """전체 스냅샷의 산출 상태를 선박별로 한 번만 계산해, BlueScore까지
        완전 산출되는 선박(전체의 15.2%)이 앞쪽에 오도록 정렬해 둔다.
        선박당 계산은 가벼워도 5,000여 척 전체를 매 API 호출마다 다시 돌리면
        수십 초가 걸려(측정: 약 21초) 목록 화면이 매번 멈춘 것처럼 보인다.
        """
        scored: List[Tuple[bool, dict, str]] = []
        for vessel in self.list_vessels():
            vessel_id = vessel.get("vesselId")
            if not vessel_id:
                continue
            result = self.score(vessel_id)
            full_success = result.status == "partial" and result.axis_b_score is not None
            status = "success" if full_success else result.status
            scored.append((full_success, vessel, status))
        scored.sort(key=lambda item: not item[0])
        return scored

    @lru_cache(maxsize=128)
    def score(self, vessel_id: str) -> RealAxisAResult:
        vessel_by_id, axis_results, groups, vessel_to_key, axis_b_results = self._computed_context()
        return _result_from_context(
            vessel_id,
            vessel_by_id,
            axis_results,
            groups,
            vessel_to_key,
            min_peer_size=MIN_PEER_GROUP_SAMPLE_SIZE,
            axis_b_results=axis_b_results,
        )

    @lru_cache(maxsize=1)
    def _computed_context(self) -> tuple:
        """전체 스냅샷 계산은 프로세스 최초 한 번만 수행하고 선박 조회가 공유한다."""
        vessels, events = self._records()
        vessel_by_id = {v.get("vesselId"): v for v in vessels if v.get("vesselId")}
        axis_results = compute_axis_a_pressure(events)
        groups, vessel_to_key = build_peer_groups(vessels, events)
        # B축은 실패해도(입력 파일 없음 등) A축 단독 경로가 죽지 않게 예외를
        # 흡수한다 — B축 연결은 "있으면 더 좋은 것"이지 A축의 전제조건이 아니다.
        try:
            axis_b_results = compute_axis_b_results()
        except (FileNotFoundError, ValueError):
            axis_b_results = None
        return vessel_by_id, axis_results, groups, vessel_to_key, axis_b_results
