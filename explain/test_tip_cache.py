"""
담당: 최지희

개선 팁 사전 생성 캐시 테스트.

지키려는 것은 두 가지다.

1. **캐시가 있으면 LLM을 부르지 않는다.** 이게 깨지면 시뮬레이터 탭이 다시
   14초 멈춘다 — 화면은 멀쩡해 보이고 느리기만 해서 알아채기 어렵다.
2. **캐시에 폴백 문장이 굳지 않는다.** 생성이 실패한 날 만들어진 템플릿
   문장이 캐시에 박히면, 그 뒤로는 LLM이 멀쩡해도 영원히 템플릿이 나간다.

실행: pytest explain/test_tip_cache.py
"""

from __future__ import annotations

import json

import pytest

from explain import render, tip_cache
from explain.explain import generate_improvement_tip
from explain.test_explain import StubProvider, make_input

LABEL = "가장 쉬운 개선"
ACTIONS = ["어장을 오갈 때의 평균 항해 속도를 낮춘다"]
TIP_TEXT = "어장을 오갈 때 평균 항해 속도를 낮추세요. 연료를 아끼고 자원에도 도움이 됩니다."


def entry(source: str = "llm:alan", tip: str = TIP_TEXT) -> dict:
    return {
        tip_cache.cache_key(LABEL, ACTIONS): {
            "planLabel": LABEL,
            "actions": ACTIONS,
            "tip": tip,
            "source": source,
            "generatedAt": "2026-08-18T08:09:43+00:00",
        }
    }


# ─── 키 ──────────────────────────────────────────────────────────────────────
def test_행동_순서가_다르면_다른_조합이다():
    """순서가 문장 순서를 바꾸므로 같은 캐시를 쓰면 안 된다."""
    a = tip_cache.cache_key(LABEL, ["가", "나"])
    b = tip_cache.cache_key(LABEL, ["나", "가"])
    assert a != b


def test_조합_이름이_다르면_다른_조합이다():
    assert tip_cache.cache_key("가장 쉬운 개선", ACTIONS) != tip_cache.cache_key(
        "다음 우대 구간까지", ACTIONS
    )


# ─── 조회 ────────────────────────────────────────────────────────────────────
def test_캐시에_있으면_출처에_cached가_붙는다():
    result = tip_cache.lookup(LABEL, ACTIONS, entries=entry())
    assert result is not None
    assert result.text == TIP_TEXT
    assert result.source == "llm:alan-cached"
    assert result.is_fallback is False


def test_화면_출처_표시_규약을_지킨다():
    """`ui/components.py`가 `llm:` 접두사로 'AI 생성'을 판단한다."""
    result = tip_cache.lookup(LABEL, ACTIONS, entries=entry())
    assert result.source.startswith("llm:")


def test_없는_조합은_None():
    assert tip_cache.lookup("다음 우대 구간까지", ACTIONS, entries=entry()) is None
    assert tip_cache.lookup(LABEL, ["다른 행동"], entries=entry()) is None


def test_폴백_문장은_캐시에서_무시한다():
    """생성 실패한 날 굳은 템플릿이 영구히 화면에 남는 것을 막는다."""
    assert tip_cache.lookup(LABEL, ACTIONS, entries=entry(source="fallback:llm_disabled")) is None


def test_빈_문장은_무시한다():
    assert tip_cache.lookup(LABEL, ACTIONS, entries=entry(tip="   ")) is None


# ─── 파일 ────────────────────────────────────────────────────────────────────
def test_캐시_파일이_없으면_빈_캐시(tmp_path):
    assert tip_cache.load(tmp_path / "없음.json") == {}


def test_깨진_캐시_파일은_무시한다(tmp_path):
    """캐시가 깨졌다고 화면이 멈추면 안 된다. 없는 셈 치고 LLM을 부른다."""
    path = tmp_path / "깨짐.json"
    path.write_text("{ 이건 JSON이 아님", encoding="utf-8")
    assert tip_cache.load(path) == {}


def test_저장하고_다시_읽으면_같다(tmp_path):
    path = tmp_path / "cache.json"
    tip_cache.save(entry(), path)
    assert tip_cache.load(path) == entry()


def test_실제_캐시_파일이_시연_조합을_전부_덮는다():
    """
    이 테스트가 이 파일에서 제일 중요하다.

    `services/scoring.improvement_plans()`의 행동 문구가 바뀌면 캐시 키가
    빗나가는데, 화면은 멀쩡하고 느려지기만 해서(카드당 6초) 발표 중에야
    드러난다. 여기서 미리 잡고, 깨지면 `python -m explain.build_tip_cache`를
    돌리면 된다.
    """
    from explain.build_tip_cache import collect_combos

    entries = tip_cache.load()
    assert entries, "팁 캐시가 비어 있습니다 — build_tip_cache를 실행하세요"

    missing = [
        (label, list(actions))
        for (label, actions) in collect_combos()
        if tip_cache.cache_key(label, list(actions)) not in entries
    ]
    assert not missing, (
        f"캐시에 없는 조합이 있습니다: {missing} — build_tip_cache를 다시 실행하세요"
    )

    for item in entries.values():
        assert item["source"].startswith("llm:")
        assert item["tip"].strip()
        # 캐시는 한 번 만들어 계속 쓰므로, 나쁜 문장이 굳으면 발표 내내 나간다.
        assert render.find_forbidden_advice(item["tip"]) == [], (
            f"캐시된 팁에 점수를 깎는 조언이 있습니다: {item['tip']}"
        )


# ─── 생성 경로와의 연결 ──────────────────────────────────────────────────────
def test_캐시가_있으면_프로바이더를_부르지_않는다(monkeypatch):
    monkeypatch.setattr(tip_cache, "load", lambda: entry())
    stub = StubProvider(response='{"tip": "이건 쓰이면 안 됩니다"}')

    result = generate_improvement_tip(make_input(), LABEL, ACTIONS, provider=stub)

    assert result.source == "llm:alan-cached"
    assert stub.last_prompts is None, "LLM을 호출하지 않아야 한다"


def test_use_cache_False면_캐시를_건너뛴다(monkeypatch):
    monkeypatch.setattr(tip_cache, "load", lambda: entry())
    stub = StubProvider(response='{"tip": "새로 만든 문장입니다."}')

    result = generate_improvement_tip(
        make_input(), LABEL, ACTIONS, provider=stub, use_cache=False
    )

    assert result.source == "llm:stub"
    assert result.text == "새로 만든 문장입니다."


def test_캐시에_없는_조합은_평소대로_생성한다(monkeypatch):
    monkeypatch.setattr(tip_cache, "load", lambda: entry())
    stub = StubProvider(response='{"tip": "새 조합용 문장입니다."}')

    result = generate_improvement_tip(
        make_input(), "다음 우대 구간까지", ["다른 행동"], provider=stub
    )

    assert result.source == "llm:stub"


def test_LLM을_꺼도_캐시는_쓴다(monkeypatch):
    """
    시연 중 LLM을 끄더라도 팁은 앨런이 쓴 문장이 나가야 한다.

    이미 만들어 둔 문장을 읽는 것은 LLM 호출이 아니다.
    """
    monkeypatch.setattr(tip_cache, "load", lambda: entry())
    result = generate_improvement_tip(make_input(), LABEL, ACTIONS, use_llm=False)
    assert result.source == "llm:alan-cached"
