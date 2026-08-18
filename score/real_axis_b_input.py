"""
담당: 김준기, 오동규

`data_new/`(김태윤이 재구축한 데이터 파이프라인)의 실제 산출물
(`events_with_weather.jsonl.gz`, `final_vessel_matches.jsonl`)을
`score/axis_b_baseline.py`가 요구하는 평평한 row 형태로 변환한다.

배경: `axis_b_baseline.py`(`fit_baseline_model`/`compute_axis_b_efficiency`)는
이벤트 1건당 `tonnageGt`/`averageSpeedKnots`/`durationHours`/`seaSurfaceTempC`/
`windSpeedMs`/`currentSpeedMs`/`gearType`/`seaArea`/`season`이 **한 딕셔너리
안에 평평하게** 모여있는 `rows`를 요구하는데, `data_new/`의 산출물은 이 필드들이
서로 다른 두 파일에 흩어져 있고 이름·구조도 다르다(`data_new/PROCESS_LOG.md`
47번, `score/TODO.md` "B축 입력 병합 스크립트" 항목 참고). 이 모듈이 그 이어주는
역할을 한다.

**`data_new/processed/`의 원본 파일·필드명은 여기서 절대 바꾸지 않는다** —
그대로 읽어서 score/가 원하는 이름으로 새로 변환만 한다
(`data/vessel_spec_client.py`가 MOF 원본 필드를 그대로 받아 자체 정규화하는
것, `services/real_scoring.py`가 GFW 원본 필드를 그대로 읽어 A축을 계산하는
것과 같은 패턴 — 2026-08-18 오동규·김태윤 논의 결론).

필드별 처리 방침 (전부 2026-08-18 오동규·김태윤 논의로 확정 — `score/TODO.md`
"B축 입력 병합 스크립트" 항목에 논의 경과 전체 기록):
    - `tonnageGt`: `final_vessel_matches.jsonl`의 `tac.tonnageGtTac` 또는
      `mof.tonnageGtMof`(둘 다 문자열, 중첩) 중 있는 쪽을 float로 변환해서 쓴다.
      **실측 확인함(2026-08-18): `tac`와 `mof`가 동시에 채워진 행은 0건**이라
      우선순위/충돌 로직은 필요 없다 — 있는 쪽 하나만 쓰면 된다.
    - `windSpeedMs`(`weather_WIND_SPEED`에서 변환): **m/s로 추정**한다. 이 API
      문서를 직접 확인한 근거는 아니고, (1) 한국 기상청·해양수산부가 풍속
      단위로 m/s를 공식 표준으로 쓰는 관행, (2) 같은 레코드의 다른 필드
      샘플값과의 정황 대조(기압 표본값이 표준대기압 1013hPa 근처, 기온
      표본값이 4월 초 한국 연안 기온으로 섭씨 기준 타당함)로 추정한 것이다.
      **공식 확인 아님 — 확인되면 이 주석과 함께 교체할 것.**
    - `seaSurfaceTempC`(`weather_WATER_TEMPER`에서 변환): 섭씨(°C)로 보는 게
      타당하다는 정황(위와 동일 근거)만 있고 마찬가지로 공식 확인은 아니다.
    - `currentSpeedMs`(`weather_SURFACE_CURR_SPEED`에서 변환): **단위 추정
      근거조차 없다. 완전 미확인 상태다.**
    - `seaArea`/`season`: 데이터팀 태그(`population_tags.jsonl`, 2026-08-18
      기준 아직 생성 안 됨)를 기다리지 않고, `score/peer_grouping.py`의
      `region_key()`/`season_key()`를 그대로 재사용한다 — 이벤트 자체의
      위경도·시작시각만 있으면 계산되고 이미 `events_with_weather.jsonl.gz`에
      들어있어서 즉시 채울 수 있다. **단, `region_key()`가 주는 `(row, col)`
      튜플은 `"{row}_{col}"` 문자열로 바꿔서 쓴다** — 튜플을 그대로 LightGBM
      범주형 피처에 넣으면 학습↔예측 사이 카테고리 왕복 과정에서 numpy가
      같은 길이의 튜플들을 2차원 배열로 오인해 리스트로 망가뜨리는 바람에
      예측 단계에서 `TypeError: unhashable type: 'list'`가 난다(2026-08-18
      실행 중 실제로 발견, `_sea_area_label()` 참고).
    - `gearType`: 이번 배치에서는 `None`으로 둔다(옵션 c로 확정, 나중에 별도
      논의 — 후보는 `population_tags.jsonl`의 뭉뚱그린 태그를 쓰거나
      `data/gear_type_mapping_draft.py`의 TAC 19종 매핑까지 동원하는 것).
    - 매칭 안 된 선박·날씨 없는 이벤트: 여기서 걸러내지 않는다. `None`인 채로
      그냥 내보내면 `axis_b_baseline.py`의 `_prepare_valid_rows()`가 필수
      3종(`tonnageGt`/`averageSpeedKnots`/`durationHours`) 결측을 이미
      알아서 skip하므로, 이 모듈에서 같은 판단을 중복할 필요가 없다.

`"미제공"`(해양기상 결측 마커)과 빈 문자열은 `None`으로, 그 외 문자열은
float로 변환한다. 변환 실패(비수치 문자열 등)도 `None`으로 처리한다.
"""

import gzip
import json
from pathlib import Path
from typing import Dict, List, Optional

from score.peer_grouping import region_key, season_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "data_new" / "processed" / "events_with_weather.jsonl.gz"
DEFAULT_MATCHES_PATH = PROJECT_ROOT / "data_new" / "processed" / "final_vessel_matches.jsonl"

# 해양기상 원본의 결측 마커 — "미제공"은 값을 안 준다는 뜻이지 0이 아니다.
MISSING_WEATHER_MARKER = "미제공"


def _to_float(value) -> Optional[float]:
    """문자열/숫자/None을 float 또는 None으로 정규화한다.

    "미제공"·빈 문자열·변환 실패는 전부 None으로 취급한다 — 값을 지어내지 않는다.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == MISSING_WEATHER_MARKER:
            return None
        value = stripped
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_vessel_tonnage_index(matches_path: Path = DEFAULT_MATCHES_PATH) -> Dict[str, Optional[float]]:
    """`final_vessel_matches.jsonl`을 읽어 gfwVesselId -> 톤수(GT) 조회 테이블을 만든다.

    `tac.tonnageGtTac`가 있으면 그 값, 없고 `mof.tonnageGtMof`가 있으면 그 값,
    둘 다 없으면 None. tac/mof가 동시에 채워진 행은 실측 확인 결과 0건이라
    우선순위·충돌 로직은 없다(모듈 docstring 참고).
    """
    index: Dict[str, Optional[float]] = {}
    with matches_path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            vessel_id = record.get("gfwVesselId")
            if vessel_id is None:
                continue

            tac = record.get("tac")
            mof = record.get("mof")
            if tac:
                index[vessel_id] = _to_float(tac.get("tonnageGtTac"))
            elif mof:
                index[vessel_id] = _to_float(mof.get("tonnageGtMof"))
            else:
                index[vessel_id] = None
    return index


def _load_events(events_path: Path) -> List[dict]:
    with gzip.open(events_path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _sea_area_label(latitude, longitude) -> Optional[str]:
    """region_key()의 (row, col) 튜플을 문자열로 바꾼다.

    2026-08-18 실행 중 발견: 튜플을 LightGBM 범주형 피처 값으로 그대로 쓰면
    안 된다 — 학습 시 LightGBM이 카테고리 목록을 내부적으로 numpy 배열을
    거쳐 저장하는데, 길이가 같은 튜플들(예: 전부 2튜플)은 numpy가 2차원
    배열로 해석해버려서 `.tolist()`를 거치면 튜플이 아니라 **리스트**가
    되고, 리스트는 해시가 안 돼서 예측 단계에서
    `TypeError: unhashable type: 'list'`로 죽는다(실제로 겪음). 문자열로
    바꾸면 이 문제가 없다.
    """
    key = region_key(latitude, longitude)
    if key is None:
        return None
    row, col = key
    return f"{row}_{col}"


def _event_to_axis_b_row(event: dict, tonnage_gt: Optional[float]) -> dict:
    """이벤트 1건 + 조회된 톤수를 axis_b_baseline.py가 요구하는 row로 변환한다."""
    latitude = event.get("latitude")
    longitude = event.get("longitude")
    start = event.get("start")

    return {
        "vesselId": event.get("vesselId"),
        "tonnageGt": tonnage_gt,
        "averageSpeedKnots": event.get("averageSpeedKnots"),
        "durationHours": event.get("durationHours"),
        "totalDistanceKm": event.get("totalDistanceKm"),
        "windSpeedMs": _to_float(event.get("weather_WIND_SPEED")),
        "seaSurfaceTempC": _to_float(event.get("weather_WATER_TEMPER")),
        "currentSpeedMs": _to_float(event.get("weather_SURFACE_CURR_SPEED")),
        "seaArea": _sea_area_label(latitude, longitude),
        "season": season_key(start),
        "gearType": None,
    }


def build_axis_b_rows(
    events_path: Path = DEFAULT_EVENTS_PATH,
    matches_path: Path = DEFAULT_MATCHES_PATH,
) -> List[dict]:
    """`events_with_weather.jsonl.gz` + `final_vessel_matches.jsonl`을 조인해서
    `axis_b_baseline.py`(`fit_baseline_model`/`compute_axis_b_efficiency`)에
    바로 넣을 수 있는 row 리스트를 만든다.

    매칭 안 된 선박·날씨 없는 이벤트도 걸러내지 않고 그대로 낸다 — 모듈
    docstring의 "매칭 안 된 선박·날씨 없는 이벤트" 항목 참고.
    """
    tonnage_index = load_vessel_tonnage_index(matches_path)
    events = _load_events(events_path)
    return [
        _event_to_axis_b_row(event, tonnage_index.get(event.get("vesselId")))
        for event in events
    ]
