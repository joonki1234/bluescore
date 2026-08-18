"""담당: 최지희

Streamlit이 사용하는 BlueScore REST 클라이언트.

이 모듈은 HTTP 전송과 오류 변환만 담당한다. 점수·설명·시뮬레이션·업무 상태는
FastAPI 뒤의 서비스와 SQLite가 소유한다.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


class ApiClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BlueScoreApiClient:
    #: 요약+요인별 상세 리포트를 처음 만들 때 LLM 호출이 두 번 나가고 실측
    #: 7.7~8.0초가 걸린다. 기존 기본값 8.0초는 그 경계에 정확히 걸려서,
    #: 저장된 리포트가 없는 선박을 처음 누르면 타임아웃으로 떨어졌다.
    #: 시연 전 워밍업(`?refresh=true`)을 하면 0.01초로 끝나지만, 워밍업을
    #: 빠뜨렸을 때 화면이 에러로 죽지 않도록 여유를 준다.
    DEFAULT_TIMEOUT_SECONDS = 30.0

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None) -> None:
        self.base_url = (base_url or os.getenv("BLUESCORE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT_SECONDS

    def _request(self, method: str, path: str, *, json: Optional[Dict[str, Any]] = None) -> Dict:
        try:
            response = requests.request(
                method, f"{self.base_url}{path}", json=json, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ApiClientError(
                f"BlueScore API에 연결할 수 없습니다: {self.base_url}"
            ) from exc
        if not response.ok:
            try:
                message = response.json().get("message") or response.text
            except ValueError:
                message = response.text
            raise ApiClientError(message or "API 요청에 실패했습니다.", status_code=response.status_code)
        if response.status_code == 204:
            return {}
        return response.json()

    def health(self) -> Dict:
        return self._request("GET", "/health")

    def config(self) -> Dict:
        return self._request("GET", "/config")

    def list_vessels(self, source_type: str = "demo") -> Dict:
        return self._request("GET", f"/vessels?sourceType={source_type}")

    def score(self, vessel_id: str, source_type: str = "demo") -> Dict:
        return self._request("GET", f"/vessels/{vessel_id}/score?sourceType={source_type}")

    def simulate(self, vessel_id: str, revisit_count: int, speed_knots: float) -> Dict:
        return self._request(
            "POST", f"/vessels/{vessel_id}/simulate",
            json={"revisitCount": revisit_count, "speedKnots": speed_knots},
        )

    def simulation_surface(self, vessel_id: str) -> Dict:
        return self._request("GET", f"/vessels/{vessel_id}/simulation-surface")

    def explanation(self, vessel_id: str) -> Dict:
        return self._request("GET", f"/vessels/{vessel_id}/explanation")

    def ask(self, vessel_id: str, question: str) -> Dict:
        return self._request(
            "POST", f"/vessels/{vessel_id}/questions", json={"question": question}
        )

    def create_appeal(self, score_run_id: str, reason: str, detail: str) -> Dict:
        return self._request(
            "POST", "/appeals",
            json={"scoreRunId": score_run_id, "reason": reason, "detail": detail},
        )

    def list_appeals(self, status: Optional[str] = None) -> Dict:
        suffix = f"?status={status}" if status else ""
        return self._request("GET", f"/appeals{suffix}")

    def appeal(self, appeal_id: str) -> Dict:
        return self._request("GET", f"/appeals/{appeal_id}")

    def draft_appeal_response(self, appeal_id: str, refresh: bool = False) -> Dict:
        return self._request(
            "POST", f"/appeals/{appeal_id}/draft-response", json={"refresh": refresh}
        )

    def review_appeal(self, appeal_id: str, decision: str, reason: str, reviewer: str) -> Dict:
        return self._request(
            "POST", f"/appeals/{appeal_id}/review",
            json={"decision": decision, "reason": reason, "reviewer": reviewer},
        )

    def review_score_run(
        self,
        score_run_id: str,
        decision: str,
        reason: str,
        reviewer: str,
        final_discount_bp: Optional[int] = None,
    ) -> Dict:
        """이의제기 유무와 무관하게 산출 건에 심사 결정을 남긴다."""
        return self._request(
            "POST", f"/score-runs/{score_run_id}/review",
            json={
                "decision": decision,
                "reason": reason,
                "reviewer": reviewer,
                "finalDiscountBp": final_discount_bp,
            },
        )

    def review_for_score_run(self, score_run_id: str) -> Optional[Dict]:
        result = self._request("GET", f"/score-runs/{score_run_id}/review")
        return result or None

    def rate_lookup(self, score: float) -> Dict:
        return self._request("GET", f"/rates/lookup?score={score}")

    def commit_report(self, score_run_id: str) -> Dict:
        return self._request("POST", f"/reports/{score_run_id}/commit")

    def report_commit(self, score_run_id: str) -> Optional[Dict]:
        try:
            return self._request("GET", f"/reports/{score_run_id}/commit")
        except ApiClientError as exc:
            if exc.status_code == 404:
                return None
            raise

    def chain_record(self, record_id: str) -> Dict:
        return self._request("GET", f"/chain/records/{record_id}")
