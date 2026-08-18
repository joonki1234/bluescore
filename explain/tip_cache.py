"""

개선 팁 사전 생성 캐시.

왜 캐시하나
----------
팁은 개선 시뮬레이터의 추천 카드에 붙는 문장인데, 카드가 두 장이라 화면 한
번에 LLM 호출이 두 번 나간다. 앨런은 호출당 약 5.8초라 카드 렌더가 14초쯤
멈췄다 — 발표 중에는 못 쓸 시간이다.

그런데 팁이 실제로 의존하는 것은 **개선 조합 이름과 바꿀 행동 목록뿐**이다
(`prompt.build_compact_improvement_tip_prompt` 참고 — 선박 데이터를 아예
받지 않는다). 그래서 경우의 수가 선박 수와 무관하게 고정돼 있고, 시연 데이터
전체를 훑어보면 실제로 등장하는 조합은 두 개뿐이다. 미리 만들어 두면 발표
중 앨런 호출이 0이 되고 카드가 즉시 뜬다.

캐시에 없는 조합이 들어오면 막지 않고 평소대로 LLM을 부른다 — 캐시는 빠른
길이지 유일한 길이 아니다.

만드는 법
--------
    python -m explain.build_tip_cache          # 없는 조합만 생성
    python -m explain.build_tip_cache --force  # 전부 다시 생성

`source`는 원래 프로바이더를 보존하고 뒤에 `-cached`를 붙인다. 화면이
"AI가 생성한 문구입니다 (alan-cached)"로 표시하므로, 누가 썼는지도 미리
만들어 둔 것인지도 숨기지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from explain.contract import TextOutput

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).with_name("tip_cache.json")

#: 캐시에서 나온 문장임을 `source`에 남기는 접미사.
CACHED_SUFFIX = "-cached"


def cache_key(plan_label: str, actions: List[str]) -> str:
    """
    조합 하나를 가리키는 키.

    행동 순서가 문장 순서를 바꾸므로 정렬하지 않는다 — 순서가 다르면 다른
    조합으로 본다.
    """
    return json.dumps([plan_label, list(actions)], ensure_ascii=False, sort_keys=False)


def load(path: Path = CACHE_PATH) -> Dict[str, dict]:
    """캐시 파일을 읽는다. 없거나 깨졌으면 빈 캐시로 취급한다."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # 캐시가 깨졌다고 화면이 멈추면 안 된다. 없는 셈 치고 LLM을 부른다.
        logger.warning("팁 캐시를 읽지 못해 무시합니다: %s", exc)
        return {}
    entries = raw.get("entries")
    return entries if isinstance(entries, dict) else {}


def save(entries: Dict[str, dict], path: Path = CACHE_PATH) -> None:
    payload = {
        "note": (
            "개선 팁 사전 생성 결과. 직접 고치지 말고 "
            "`python -m explain.build_tip_cache --force`로 다시 만드세요."
        ),
        "entries": entries,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def lookup(
    plan_label: str, actions: List[str], entries: Optional[Dict[str, dict]] = None
) -> Optional[TextOutput]:
    """캐시에 있으면 `TextOutput`으로, 없으면 None."""
    if entries is None:
        entries = load()
    entry = entries.get(cache_key(plan_label, actions))
    if not entry:
        return None
    text, source = entry.get("tip"), entry.get("source")
    if not isinstance(text, str) or not text.strip():
        return None
    if not isinstance(source, str) or not source.startswith("llm:"):
        # 폴백 문장까지 캐시에 굳혀 두면 템플릿이 영구히 화면에 남는다.
        return None
    return TextOutput(text=text, source=f"{source}{CACHED_SUFFIX}")
