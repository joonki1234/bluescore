"""MOF(선박제원정보) 정규화 — 원본 XML을 조인용으로 정리.

MOF는 GFW 선박명으로 부분일치 검색한 결과라(PROCESS_LOG.md 9번), 한
쿼리에 후보가 여러 척 나올 수 있다 — 전부 보존한다(원칙1, 하나를 임의로
고르지 않음). 어느 GFW vesselId로 검색했는지는 메타데이터에서 가져온다.

raw/는 읽기만 한다. processed/에 새로 쓰며 재실행 시 덮어써도 무방.

사용법:
    python normalize_mof.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from xml.etree import ElementTree

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "mof"
OUT_PATH = Path(__file__).resolve().parent.parent / "processed" / "mof_candidates_normalized.jsonl"

FIELDS = ["vsslNo", "imoNo", "vsslKorNm", "vsslEngNm", "vsslKnd", "vsslNlty", "clsgn", "grtg", "vsslLt", "shdth"]


def _parse_items(xml_text: str) -> list:
    root = ElementTree.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        rec = {}
        for field in FIELDS:
            el = item.find(field)
            rec[field] = el.text if el is not None and el.text else None
        items.append(rec)
    return items


def run() -> None:
    files = sorted(glob.glob(str(RAW_DIR / "mof_search_*__*Z.xml")))
    if not files:
        raise SystemExit(f"MOF 원본 파일이 없습니다: {RAW_DIR}")

    # 같은 GFW vesselId를 여러 이름 후보(원본 로마자명 + 역-로마자 한글
    # 후보들)로 여러 번 질의할 수 있어(collect/mof_korean_retry.py) 파일
    # 단위가 아니라 vesselId 단위로 후보를 합쳐야 앞선 질의 결과가 뒤 파일에
    # 덮어써지지 않는다.
    by_vessel: dict = {}
    n_queries = 0
    for f in files:
        meta_path = Path(f).with_name(Path(f).name[:-4] + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        gfw_vessel_id = meta.get("gfw_vessel_id")

        items = _parse_items(Path(f).read_text(encoding="utf-8"))
        n_queries += 1
        entry = by_vessel.setdefault(gfw_vessel_id, {"queriedNames": [], "candidates": []})
        entry["queriedNames"].append(meta.get("queried_name"))
        entry["candidates"].extend(items)

    n_candidates = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for gfw_vessel_id, entry in by_vessel.items():
            # 어선번호(vsslNo) 기준 중복 후보 제거 — 같은 배가 여러 질의(원본명+
            # 역-로마자 후보들)에 반복으로 걸릴 수 있다.
            seen_no = set()
            deduped = []
            for c in entry["candidates"]:
                key = c.get("vsslNo")
                if key is not None and key in seen_no:
                    continue
                if key is not None:
                    seen_no.add(key)
                deduped.append(c)
            n_candidates += len(deduped)
            out.write(
                json.dumps(
                    {"gfwVesselId": gfw_vessel_id, "queriedNames": entry["queriedNames"], "candidates": deduped},
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(f"MOF 쿼리 {n_queries}건({len(by_vessel)}척) -> 후보 {n_candidates}건 정규화 -> {OUT_PATH}")


if __name__ == "__main__":
    run()
