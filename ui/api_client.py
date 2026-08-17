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
    def __init__(self, base_url: Optional[str] = None, timeout: float = 8.0) -> None:
        self.base_url = (base_url or os.getenv("BLUESCORE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = timeout

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
