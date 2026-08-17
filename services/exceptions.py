"""담당: 최지희

서비스 오류를 HTTP 상태와 분리하기 위한 예외 타입.
"""

from typing import Any, Dict, Optional


class ServiceError(RuntimeError):
    code = "service_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(ServiceError):
    code = "not_found"


class ConflictError(ServiceError):
    code = "conflict"


class InvalidStateError(ServiceError):
    code = "invalid_state"


class BackendUnavailableError(ServiceError):
    code = "backend_unavailable"

