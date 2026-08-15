"""
담당: 김태윤

data/rules_common.md 3번(재시도 정책 — 429/500/502/503/524는 최대 3회,
2s/4s/8s 백오프, 401 등 인증/요청 오류는 즉시 실패) 공통 구현.

GFW/해양기상/연안AIS 클라이언트가 각자 같은 재시도 루프를 복붙해서 갖고
있던 것을 여기로 모았다(2026-08-14) — 재시도 표가 바뀌면 한 곳만 고치면
되게 하기 위함.
"""

import time

import requests

RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 524}
MAX_RETRIES = 3
BACKOFF_SECONDS = [2, 4, 8]


def request_with_retry(
    method: str,
    url: str,
    *,
    retryable_status_codes=RETRYABLE_HTTP_STATUS_CODES,
    max_retries=MAX_RETRIES,
    backoff_seconds=BACKOFF_SECONDS,
    timeout=30,
    **kwargs,
) -> requests.Response:
    """재시도 대상 상태코드(retryable_status_codes)의 응답은 재시도 끝에
    마지막 Response를 그대로 반환한다 — 호출자가 response.ok로 성공/실패를
    판단한다. 네트워크 오류(requests.exceptions.RequestException)는
    재시도해도 실패하면 그대로 다시 raise한다 — 호출자가 자기 도메인
    예외로 감싸면 된다.
    """
    response = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.RequestException:
            if attempt < max_retries:
                time.sleep(backoff_seconds[attempt])
                continue
            raise
        if response.ok or response.status_code not in retryable_status_codes or attempt >= max_retries:
            return response
        time.sleep(backoff_seconds[attempt])
    return response
