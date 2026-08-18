"""
담당: 최지희

개선 팁 사전 생성 스크립트.

    python -m explain.build_tip_cache            # 캐시에 없는 조합만 생성
    python -m explain.build_tip_cache --force    # 전부 다시 생성
    python -m explain.build_tip_cache --dry-run  # 무엇을 만들지만 보여준다

무엇을 만들지는 **시연 데이터에서 직접 뽑는다.** 조합 목록을 손으로 적어두면
`services/scoring.improvement_plans()`의 행동 문구가 바뀔 때 캐시가 조용히
빗나가고, 발표 중에야 14초 지연으로 드러난다. 그래서 실제 화면이 요청하는
것과 같은 경로로 조합을 수집한다.

라이브러리 코드가 아니라 빌드 스크립트라서 `services/`를 임포트해도 된다 —
`explain/`의 런타임 코드는 여전히 `services/`를 모른다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from explain import tip_cache
from explain.explain import generate_improvement_tip
from explain.contract import ExplainInput

logger = logging.getLogger(__name__)

Combo = Tuple[str, Tuple[str, ...]]

# 검증에 걸렸을 때 다시 뽑아 보는 횟수.
MAX_ATTEMPTS = 5


def collect_combos() -> Dict[Combo, Tuple[ExplainInput, List[str]]]:
    """
    시연 데이터 전체를 훑어 실제로 등장하는 (조합 이름, 행동 목록)을 모은다.

    같은 조합이 여러 선박에서 나오면 하나로 합친다 — 팁 문장은 선박 데이터를
    쓰지 않으므로 선박이 달라도 결과가 같다.
    """
    from services.scoring import ScoringService  # 빌드 시점에만 필요

    service = ScoringService()
    combos: Dict[Combo, Tuple[ExplainInput, List[str]]] = {}
    for vessel in service._demo_data()["vessels"]:
        if vessel["status"] != "success":
            continue
        explain_input = service._explain_input(vessel)
        for plan in service.improvement_plans(vessel["vesselId"], use_llm=False):
            label = "가장 쉬운 개선" if plan.key == "easiest" else "다음 우대 구간까지"
            combos.setdefault(
                (label, tuple(plan.actions)), (explain_input, list(plan.actions))
            )
    return combos


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="개선 팁을 미리 생성해 캐시에 저장합니다.")
    parser.add_argument("--force", action="store_true", help="이미 있는 조합도 다시 생성")
    parser.add_argument("--dry-run", action="store_true", help="생성하지 않고 목록만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    # 단독 실행이라 앱 진입점을 거치지 않는다. 키를 직접 읽어야 한다.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - 환경 의존
        pass

    entries = {} if args.force else tip_cache.load()
    combos = collect_combos()
    print(f"시연 데이터에서 찾은 조합: {len(combos)}개")

    created = skipped = failed = 0
    for (label, actions_tuple), (explain_input, actions) in combos.items():
        key = tip_cache.cache_key(label, actions)
        if key in entries and not args.force:
            print(f"  건너뜀  {label} + {list(actions_tuple)}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  생성예정 {label} + {list(actions_tuple)}")
            created += 1
            continue

        # use_cache=False가 없으면 --force가 캐시를 그대로 읽어 와 아무것도
        # 다시 만들지 않는다.
        #
        # 검증(숫자 창작·금지 조언)에 걸리면 폴백이 오는데, 팁은 온도가 있어
        # 다시 뽑으면 통과하는 경우가 많다. 캐시는 한 번 만들어 두고 계속
        # 쓰는 것이라 여기서 몇 번 더 시도할 값어치가 있다.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result = generate_improvement_tip(
                explain_input, label, actions, use_cache=False
            )
            if not result.is_fallback and result.source.startswith("llm:"):
                break
            print(f"  재시도  {label} ({attempt}/{MAX_ATTEMPTS}) — {result.source}")
        if result.is_fallback or not result.source.startswith("llm:"):
            # 폴백 문장을 캐시에 굳히면 템플릿이 화면에 영구히 남는다.
            print(f"  실패    {label} + {list(actions_tuple)}  ({result.source})")
            failed += 1
            continue

        entries[key] = {
            "planLabel": label,
            "actions": list(actions),
            "tip": result.text,
            "source": result.source,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(f"  생성    {label} + {list(actions_tuple)}")
        print(f"          [{result.source}] {result.text}")
        created += 1

    if args.dry_run:
        print(f"\n(dry-run) 생성 예정 {created}개 · 건너뜀 {skipped}개")
        return 0

    tip_cache.save(entries)
    print(f"\n생성 {created} · 건너뜀 {skipped} · 실패 {failed}")
    print(f"저장: {tip_cache.CACHE_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
