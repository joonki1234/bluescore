"""
담당: 김준기, 오동규

온체인 증적용 SHA-256 해시 생성.

참고: BlueScore 프로젝트 기획서 - 온체인 증적(스코어/평가 결과 무결성 증명용 해시 생성).
해시 대상 JSON의 정규화 규칙은 CLAUDE.md "확정된 규칙" 5번을 그대로 따른다:
    - JSON은 sort_keys=True로 직렬화한다.
    - 소수점이 있는 값(float)은 둘째 자리까지 반올림한 뒤 문자열로 변환한다.
    - 빈 값(None/누락)은 값을 null로 넣지 않고 키 자체를 제외한다(재귀적으로 적용).

이 규칙대로 정규화해야, 같은 결과를 나중에 다시 만들어도 항상 같은 해시가 나와서
검증(verify)이 가능해진다. int/str/bool은 그대로 두고, dict/list는 재귀적으로
정규화한다.
"""

import hashlib
import json
from typing import Any, Dict


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _normalize_dict(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
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
    """CLAUDE.md 해시 규칙에 따라 dict를 정규화된 JSON 문자열로 직렬화한다."""
    if not isinstance(data, dict):
        raise TypeError("data는 dict여야 합니다.")
    return json.dumps(_normalize_dict(data), sort_keys=True, ensure_ascii=False)


def compute_result_hash(data: Dict[str, Any]) -> str:
    """정규화된 JSON을 SHA-256으로 해시한 hex digest(64자)를 반환한다."""
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
