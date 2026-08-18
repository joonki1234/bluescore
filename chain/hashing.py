"""
담당: 김준기, 오동규

결과를 결정론적으로 직렬화해 온체인 증적용 SHA-256 해시를 생성한다.
정규화 규칙을 바꾸면 기존 온체인 기록과 호환되지 않는다.
"""

import hashlib
import json
from typing import Any, Dict, List, Union

JsonValue = Union[Dict[str, Any], List[Any], str, int, float, bool, None]


def _normalize_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return _normalize_dict(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value if item is not None]
    if isinstance(value, float):
        return f"{round(value, 2):.2f}"
    return value


def _normalize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    for key, value in data.items():
        if value is None:
            continue
        normalized[key] = _normalize_value(value)
    return normalized


def canonical_json(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        raise TypeError("data는 dict여야 합니다.")
    return json.dumps(
        _normalize_dict(data), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def compute_result_hash(data: Dict[str, Any]) -> str:
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
