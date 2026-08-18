"""사람 라벨링 결과 분석 — analysis/generate_labeling_sample.py로 뽑은 80쌍을
팀원이 직접 맞음/틀림/애매로 판정한 결과(`match_precision_labels.json`)를
분석한다.

48번(MOF vsslKnd 교차검증)과 결과가 크게 다르게 나온 이유 확인 포함:
48번의 "검증 가능" 대상은 GFW 자기신고명이 MOF 검색에도 걸리는 선박만이라,
구조적으로 흔하고 짧은 영단어 이름(MOF 상선 데이터베이스와 우연히
겹치기 쉬운 이름)에 편중된 표본이었을 가능성이 있다 — 이번 80쌍은
점수구간별 층화 랜덤추출이라 그 편향이 없다.

읽기전용(raw/·processed/ 안 건드림, match_precision_labels.json도 읽기만).

사용법:
    python analyze_human_labels.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

LABELS_PATH = Path(__file__).resolve().parent.parent / "match_precision_labels.json"
OUT_PATH = Path(__file__).resolve().parent / "output" / "human_label_analysis.json"


def _stats(rows: list) -> dict:
    c = Counter(r["humanLabel"] for r in rows)
    n = len(rows)
    correct, wrong, unsure = c["correct"], c["wrong"], c["unsure"]
    decided = correct + wrong
    precision = round(correct / decided, 3) if decided else None
    return {"n": n, "correct": correct, "wrong": wrong, "unsure": unsure, "precision_excl_unsure": precision}


def run() -> None:
    rows = json.loads(LABELS_PATH.read_text(encoding="utf-8"))

    by_group = {g: _stats([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})}

    matched = [r for r in rows if r["group"].startswith("matched")]
    unmatched = [r for r in rows if r["group"].startswith("unmatched")]

    by_numflag_matched = {f: _stats([r for r in matched if r["numFlag"] == f]) for f in ("match", "mismatch", "unknown")}
    by_numflag_unmatched = {f: _stats([r for r in unmatched if r["numFlag"] == f]) for f in ("match", "mismatch", "unknown")}

    result = {
        "total": len(rows),
        "by_score_band": by_group,
        "matched_overall": _stats(matched),
        "unmatched_nearmiss_overall": _stats(unmatched),
        "numeric_prefix_signal": {
            "matched": by_numflag_matched,
            "unmatched_nearmiss": by_numflag_unmatched,
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"matched 전체 정밀도(애매제외): {result['matched_overall']['precision_excl_unsure']}")
    print(f"unmatched 근접점수 정밀도(애매제외, 구제시): {result['unmatched_nearmiss_overall']['precision_excl_unsure']}")
    print("numFlag=match(숫자접두어 일치) matched 정밀도:", by_numflag_matched["match"]["precision_excl_unsure"])
    print("numFlag=mismatch matched 정밀도:", by_numflag_matched["mismatch"]["precision_excl_unsure"])
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    run()
