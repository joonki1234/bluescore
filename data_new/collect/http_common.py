"""공통 수집 유틸 — 재시도 HTTP 호출, 스냅샷 저장/조회, .env 로딩.

수집 원칙(PROCESS_LOG.md 4번 표) 구현체:
- 재시도: 429/500/502/503/524는 2s->4s->8s 백오프로 최대 3회, 그 외 즉시 실패
- 스냅샷: 재조회해도 기존 파일을 덮어쓰지 않음, 파일명에 조회시각 포함
- 메타데이터: 요청 파라미터를 본문과 별도 파일로 저장
- 인증키: 코드에 하드코딩하지 않고 .env에서 로딩
"""

from __future__ import annotations

import glob
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Windows 콘솔 기본 인코딩(cp949)은 em dash 등 일부 유니코드 문자를 못 받아
# print()가 죽는다 — 모든 수집 스크립트가 이 모듈을 import하니 여기서 한 번에 고침.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

RETRYABLE_STATUS = {429, 500, 502, 503, 524}
# 원래 2s->4s->8s(3회)였으나, 실규모 본수집 중 네트워크가 반복적으로
# 30초 타임아웃 나는 것이 확인되어 재시도 강도를 올림(원칙 재조정,
# PROCESS_LOG.md 27번 기록).
RETRY_DELAYS_SEC = [2, 4, 8, 16, 30]
USER_AGENT = "Mozilla/5.0 (bluescore-data-collector)"


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """일시적 에러만 재시도한다. 요청 자체가 잘못된 경우(4xx 등)는 그대로 반환해
    호출부가 원인(에러 메시지)을 보고 판단하게 한다.

    네트워크 자체가 끊기는 경우(타임아웃, 연결 실패)도 일시적 에러로 보고
    같은 정책으로 재시도한다 — HTTP 상태코드가 아예 안 오는 경우라 status_code
    분기만으로는 못 잡음."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)

    last_exc = None
    for delay in [0] + RETRY_DELAYS_SEC:
        if delay:
            time.sleep(delay)
        try:
            resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            continue
        if resp.status_code not in RETRYABLE_STATUS:
            return resp
        last_exc = None
    if last_exc:
        raise last_exc
    return resp


def save_snapshot(raw_dir: Path, prefix: str, body: bytes, meta: dict, ext: str = "json") -> Path:
    """원본을 스냅샷 파일로 저장한다. 같은 시각에 겹치면 접미사를 붙여 절대
    덮어쓰지 않는다. 메타데이터(요청 파라미터 등)는 본문과 별도 파일.
    ext: 응답 형식에 맞는 확장자(예: MOF는 xml) — 기본값 json."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
    path = raw_dir / f"{prefix}__{ts}.{ext}"
    suffix = 0
    while path.exists():
        suffix += 1
        path = raw_dir / f"{prefix}__{ts}-{suffix}.{ext}"
    path.write_bytes(body)
    meta_path = path.with_name(path.name[: -(len(ext) + 1)] + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def find_latest(raw_dir: Path, glob_pattern: str) -> Optional[Path]:
    """스냅샷이 여러 개 쌓여도 항상 가장 최근 파일을 찾는다 — 파일명을
    고정해서 읽으면 새 스냅샷이 생겨도 옛 데이터를 계속 읽게 되는 걸 방지."""
    matches = sorted(glob.glob(str(raw_dir / glob_pattern)))
    return Path(matches[-1]) if matches else None


def load_progress(progress_path: Path, current_params: dict) -> int:
    """중단 후 재개용 진행상태를 읽어 이어서 시작할 offset을 반환한다.
    조회 조건(params)이 지난 실행과 다르면 이어받지 않고 0부터 새로 시작한다."""
    if progress_path.exists():
        saved = json.loads(progress_path.read_text(encoding="utf-8"))
        if saved.get("params") == current_params:
            return saved.get("next_offset", 0)
    return 0


def save_progress(
    progress_path: Path, current_params: dict, next_offset: int, total: int, completed: bool
) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps(
            {
                "params": current_params,
                "next_offset": next_offset,
                "total": total,
                "completed": completed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def check_files_valid_and_secret_free(raw_dir: Path, glob_pattern, secret: str) -> tuple:
    """검증 게이트 공통부: 각 파일이 유효한 JSON인지, 인증키가 노출됐는지
    확인한다. (문제 목록, {파일경로: 파싱된 JSON} 딕셔너리)를 반환한다 —
    호출부가 응답 모양(목록형 entries냐 단일 객체냐)에 맞춰 추가 검증하도록
    파싱 결과를 같이 넘겨준다. glob_pattern은 문자열 하나 또는 리스트
    (예: 파일명 규칙이 실행 중간에 바뀐 경우 둘 다 잡아야 함)."""
    problems = []
    parsed = {}
    patterns = [glob_pattern] if isinstance(glob_pattern, str) else glob_pattern
    files = sorted({f for p in patterns for f in glob.glob(str(raw_dir / p))})
    for f in files:
        text = Path(f).read_text(encoding="utf-8")
        if secret and secret in text:
            problems.append(f"인증키 노출: {f}")
        try:
            parsed[f] = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"원본 구조 깨짐(JSON 파싱 실패): {f}")
            continue

        meta_file = Path(f).with_suffix("").with_suffix(".meta.json")
        if meta_file.exists() and secret and secret in meta_file.read_text(encoding="utf-8"):
            problems.append(f"인증키 노출(메타): {meta_file}")
    return problems, parsed


def validate_snapshots(raw_dir: Path, glob_pattern: str, expected_total: int, secret: str) -> list:
    """목록형(entries) 응답 전용 검증 게이트: 건수 일치·원본구조 보존·
    인증키 비노출. 문제 목록을 반환하며, 비어 있으면 통과."""
    problems, parsed = check_files_valid_and_secret_free(raw_dir, glob_pattern, secret)
    total_entries = 0
    for f, data in parsed.items():
        if "entries" not in data:
            problems.append(f"원본 구조 이상('entries' 키 없음): {f}")
            continue
        total_entries += len(data["entries"])

    if total_entries != expected_total:
        problems.append(f"건수 불일치: 저장된 {total_entries}건 vs API total {expected_total}건")
    return problems
