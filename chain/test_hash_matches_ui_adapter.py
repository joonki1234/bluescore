"""
담당: 김준기, 오동규

chain/hashing.py와 ui/adapter.py(최지희 담당)의 score_hash()는 둘 다 CLAUDE.md
해시 규칙 5번을 독립적으로 구현한 것이다. 2026-08-14에 실제로 값이 갈리는 걸
발견해서(구분자, 리스트 안 None 처리) chain/hashing.py를 ui/adapter.py에 맞춰
통일했다 — 이 테스트는 두 구현이 앞으로도 계속 일치하는지 지켜보는 회귀 테스트다.
어느 한쪽만 바뀌고 다른 쪽이 안 바뀌면 여기서 바로 드러난다.
"""

from chain.hashing import compute_result_hash
from ui.adapter import score_hash


def _ui_hash_hex(payload: dict) -> str:
    return score_hash(payload)[2:]  # "0x" 접두어 제거


class TestHashMatchesUiAdapter:
    def test_simple_payload(self):
        payload = {"vesselId": "V1", "blueScore": 72.6}
        assert compute_result_hash(payload) == _ui_hash_hex(payload)

    def test_payload_with_none_field(self):
        payload = {"vesselId": "V1", "blueScore": 72.6, "note": None}
        assert compute_result_hash(payload) == _ui_hash_hex(payload)

    def test_payload_with_none_inside_list(self):
        payload = {"vesselId": "V1", "tags": ["a", None, "b"]}
        assert compute_result_hash(payload) == _ui_hash_hex(payload)

    def test_nested_payload(self):
        payload = {
            "vesselId": "V1",
            "axisA": {"score": 65.234, "detail": None},
            "axisB": {"score": 58.1},
        }
        assert compute_result_hash(payload) == _ui_hash_hex(payload)

    def test_key_order_independent(self):
        a = {"vesselId": "V1", "blueScore": 72.6}
        b = {"blueScore": 72.6, "vesselId": "V1"}
        assert compute_result_hash(a) == _ui_hash_hex(b)
