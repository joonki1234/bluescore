"""MOF 선박제원정보 조회 — GFW에서 찾은 선박명으로 국내 등록정보 후보를
찾는다 (조인키 설계 2~3단계의 "이름" 신호 원자재 수집).

MOF Info3 API는 이름 부분일치(포함) 검색이라(사용자 제공 활용가이드로 확인,
PROCESS_LOG.md 9번) 결과에 동명이배가 여러 척 섞여 나온다. 여기서는 후보
전부를 원본 그대로 저장하고, 실제 매칭 판단(가공)은 이후 단계로 미룬다
(원칙1). 응답은 XML(공식 스펙, JSON 옵션 없음).

입력: gfw_vessels.py로 받은 선박 상세에서 이름을 뽑는다 — registryInfo
이름이 있으면 그걸(더 신뢰도 높음), 없으면 selfReportedInfo 이름을 쓴다.

사용법:
    python mof.py [--limit N]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
from pathlib import Path
from xml.etree import ElementTree

from http_common import request_with_retry, save_snapshot

# 이 API(data.go.kr)는 동시요청 15개로 60건을 4초에 처리해도 에러 0건
# (resultCode 전부 00) — 순차 대비 대폭 단축. PROCESS_LOG.md 33번 참고.
# 네트워크 요청만 병렬화하고, 파일 저장(save_snapshot)은 타임스탬프
# 충돌(TOCTOU) 방지를 위해 메인 스레드에서 순차로 한다.
MAX_WORKERS = 15

VESSELS_DIR = Path(__file__).resolve().parent.parent / "raw" / "gfw" / "vessels"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "mof"
MOF_URL = "http://apis.data.go.kr/1192000/SicsVsslManp3/Info3"


def extract_candidate_names() -> dict:
    """GFW 선박 상세 스냅샷에서 {gfw_vessel_id: 검색후보명}을 뽑는다."""
    candidates = {}
    for f in glob.glob(str(VESSELS_DIR / "vessel_*__*Z.json")):
        gfw_id = Path(f).name.split("__")[0][len("vessel_") :]
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        name = None
        if data.get("registryInfo"):
            name = data["registryInfo"][0].get("shipname")
        if not name and data.get("selfReportedInfo"):
            name = data["selfReportedInfo"][0].get("shipname")
        if name:
            candidates[gfw_id] = name
    return candidates


def already_queried() -> set:
    done = set()
    for f in glob.glob(str(RAW_DIR / "mof_search_*__*Z.xml")):
        stem = Path(f).name.split("__")[0]
        done.add(stem[len("mof_search_") :])
    return done


def collect(api_key: str, limit: int = None) -> None:
    candidates = extract_candidate_names()
    done = already_queried()
    todo = {k: v for k, v in candidates.items() if k not in done}
    print(f"GFW 선박 {len(candidates)}척 중 검색후보명 있음, 이미 조회 {len(done)}척, 남은 것 {len(todo)}척")

    items = list(todo.items())
    if limit is not None:
        items = items[:limit]
        print(f"--limit {limit} 적용 — 이번 실행은 {len(items)}척만 처리")

    def fetch(item):
        gfw_id, name = item
        resp = request_with_retry(
            "GET",
            MOF_URL,
            params={"serviceKey": api_key, "pageNo": "1", "numOfRows": "10", "vsslNm": name},
        )
        return gfw_id, name, resp

    failed = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, (gfw_id, name, resp) in enumerate(ex.map(fetch, items)):
            # resp.url엔 serviceKey가 그대로(URL인코딩된 채로) 박혀있어 메타에 못 씀
            # (원칙4 위반) — 요청 파라미터를 직접 구성해서 키만 가린다.
            meta = {
                "request_params": {"pageNo": "1", "numOfRows": "10", "vsslNm": name, "serviceKey": "REDACTED"},
                "status_code": resp.status_code,
                "gfw_vessel_id": gfw_id,
                "queried_name": name,
            }
            if not resp.ok:
                failed.append((gfw_id, name, resp.status_code))
                save_snapshot(RAW_DIR, f"mof_search_{gfw_id}_FAILED", resp.content, meta, ext="xml")
                continue

            path = save_snapshot(RAW_DIR, f"mof_search_{gfw_id}", resp.content, meta, ext="xml")
            if (i + 1) % 50 == 0 or (i + 1) == len(items):
                print(f"{i + 1}/{len(items)} name={name!r} -> {path.name}")

    print(f"완료. 신규 {len(items) - len(failed)}건, 실패 {len(failed)}건.")
    if failed:
        print(f"실패 목록: {failed}")

    problems = _validate_xml_snapshots(api_key)
    if problems:
        print("검증 게이트 위반:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("검증 게이트 통과.")


def _validate_xml_snapshots(secret: str) -> list:
    """XML 응답 전용 검증: 유효한 XML인지 + 인증키 비노출인지.
    (건수 일치는 여기선 의미 없음 — 쿼리마다 독립 조회라 total 개념이 없음.)"""
    problems = []
    for f in glob.glob(str(RAW_DIR / "mof_search_*__*Z.xml")):
        text = Path(f).read_text(encoding="utf-8")
        if secret and secret in text:
            problems.append(f"인증키 노출: {f}")
        try:
            ElementTree.fromstring(text)
        except ElementTree.ParseError:
            problems.append(f"원본 구조 깨짐(XML 파싱 실패): {f}")

        meta_file = Path(f).with_name(Path(f).name[: -4] + ".meta.json")
        if meta_file.exists() and secret and secret in meta_file.read_text(encoding="utf-8"):
            problems.append(f"인증키 노출(메타): {meta_file}")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="검증용으로 N건만 처리(미지정 시 전부)")
    args = parser.parse_args()

    key = os.environ.get("VESSEL_SPEC_API_KEY")
    if not key:
        raise SystemExit("VESSEL_SPEC_API_KEY가 .env에 없습니다.")
    collect(key, limit=args.limit)
