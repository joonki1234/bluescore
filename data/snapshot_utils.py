"""
담당: 김태윤

data/rules_common.md 2번(스냅샷 원칙 — 재조회해도 기존 파일을 덮어쓰지
않음)의 부작용을 막기 위한 공통 헬퍼. 스냅샷 파일명에 타임스탬프/날짜를
붙이는 원칙 때문에, 그 파일을 읽는 쪽 코드가 파일명을 문자열로 고정해두면
새 스냅샷이 생겨도 계속 옛날 파일을 읽는 문제가 있었다(2026-08-15 발견 —
`match_tac_vessels.py`, `build_enriched_vessel_population.py`,
`attach_event_weather.py`, `collect_event_weather.py`,
`collect_vessel_spec_candidates.py` 등 7곳에서 실제로 이 패턴이 있었음).

`merge_tac_into_enriched.py`의 `find_latest_confirmed_tac()`가 이미 쓰고
있던 "glob으로 가장 최근 스냅샷을 찾는다" 패턴을 공통 함수로 뽑아서
전체에 적용한다.
"""

from pathlib import Path


def find_latest(directory: Path, glob_pattern: str) -> Path:
    """directory에서 glob_pattern에 맞는 파일 중 가장 최근 스냅샷을 반환한다.

    파일명 문자열 기준으로 정렬한다(수정시각(mtime)이 아님) — 이 프로젝트의
    스냅샷 파일명은 전부 날짜/타임스탬프를 포함하고 있어서 문자열 정렬이
    곧 시간 순서와 일치하고, 파일을 복사하거나 git이 mtime을 바꿔도
    안정적이기 때문이다.
    """
    matches = sorted(directory.glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"{directory}에서 '{glob_pattern}' 패턴에 맞는 파일을 찾지 못했습니다."
        )
    return matches[-1]
