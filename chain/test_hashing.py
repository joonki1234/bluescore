"""
담당: 김준기, 오동규

chain/hashing.py 단위 테스트.
"""

import json

import pytest

from chain.hashing import canonical_json, compute_result_hash


class TestCanonicalJson:
    def test_rejects_non_dict(self):
        with pytest.raises(TypeError):
            canonical_json([1, 2, 3])

    def test_key_order_does_not_affect_output(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b

    def test_none_values_are_excluded_not_nulled(self):
        result = canonical_json({"score": 72.0, "note": None})
        assert "note" not in result
        assert "null" not in result

    def test_none_excluded_recursively_in_nested_dict(self):
        result = canonical_json({"axisA": {"score": 80.0, "detail": None}})
        parsed = json.loads(result)
        assert "detail" not in parsed["axisA"]

    def test_float_rounded_to_two_decimals_and_stringified(self):
        result = canonical_json({"score": 72.666})
        parsed = json.loads(result)
        assert parsed["score"] == "72.67"

    def test_float_keeps_trailing_zero(self):
        result = canonical_json({"score": 72.5})
        parsed = json.loads(result)
        assert parsed["score"] == "72.50"

    def test_int_stays_int_not_stringified(self):
        result = canonical_json({"count": 5})
        parsed = json.loads(result)
        assert parsed["count"] == 5

    def test_normalizes_dicts_inside_lists(self):
        result = canonical_json({"events": [{"value": 1.5, "note": None}]})
        parsed = json.loads(result)
        assert parsed["events"] == [{"value": "1.50"}]


class TestComputeResultHash:
    def test_returns_64_char_hex_digest(self):
        digest = compute_result_hash({"score": 72.6})
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_same_content_different_key_order_same_hash(self):
        h1 = compute_result_hash({"vesselId": "V1", "score": 72.6})
        h2 = compute_result_hash({"score": 72.6, "vesselId": "V1"})
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_result_hash({"score": 72.6})
        h2 = compute_result_hash({"score": 72.7})
        assert h1 != h2

    def test_none_field_does_not_change_hash(self):
        h1 = compute_result_hash({"score": 72.6})
        h2 = compute_result_hash({"score": 72.6, "note": None})
        assert h1 == h2
