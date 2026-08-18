"""
담당: 김준기, 오동규

온체인 증적용 SHA-256 해시 생성.

참고: BlueScore 프로젝트 기획서 - 온체인 증적(스코어/평가 결과 무결성 증명용 해시 생성).
정규화 규칙(sort_keys, 소수점 둘째 자리 반올림 후 문자열화, None 재귀적 제외, 압축
구분자)은 CLAUDE.md "확정된 규칙" 5번을 따른다.

이 함수가 해시를 생성하는 유일한 지점이다 — WorkflowService가 호출하고, UI는 결과
해시를 그대로 표시한다(중복 구현 금지). ui/adapter.py의 score_hash()가 같은 규칙을
독립적으로 구현하므로, 이 파일을 고치면 그쪽도 맞춰야 한다
(chain/test_hash_matches_ui_adapter.py가 두 구현의 일치를 검증한다).
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
