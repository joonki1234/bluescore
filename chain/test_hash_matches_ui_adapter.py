"""
담당: 김준기, 오동규

chain/hashing.py의 정규화 규칙을 고정하는 회귀 테스트. ui/adapter.py의
score_hash()가 같은 규칙을 독립적으로 구현하므로, 이 값이 어긋나면 온체인
해시와 화면 표시 해시가 달라진다.
"""

from chain.hashing import canonical_json, compute_result_hash


class TestCanonicalHash:
    def test_simple_payload(self):
        payload = {"vesselId": "V1", "blueScore": 72.6}
        assert canonical_json(payload) == '{"blueScore":"72.60","vesselId":"V1"}'
        assert len(compute_result_hash(payload)) == 64

    def test_payload_with_none_field(self):
        payload = {"vesselId": "V1", "blueScore": 72.6, "note": None}
        assert canonical_json(payload) == '{"blueScore":"72.60","vesselId":"V1"}'

    def test_payload_with_none_inside_list(self):
        payload = {"vesselId": "V1", "tags": ["a", None, "b"]}
        assert canonical_json(payload) == '{"tags":["a","b"],"vesselId":"V1"}'

    def test_nested_payload(self):
        payload = {
            "vesselId": "V1",
            "axisA": {"score": 65.234, "detail": None},
            "axisB": {"score": 58.1},
        }
        assert "detail" not in canonical_json(payload)

    def test_key_order_independent(self):
        a = {"vesselId": "V1", "blueScore": 72.6}
        b = {"blueScore": 72.6, "vesselId": "V1"}
        assert compute_result_hash(a) == compute_result_hash(b)
