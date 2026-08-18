"""

chain/commit_score_result.py 단위 테스트.
"""

from chain.commit_score_result import commit_score_result, verify_score_result
from chain.ledger import HashLedger


class TestCommitScoreResult:
    def test_commit_then_verify_true(self):
        ledger = HashLedger()
        result = {"vesselId": "V1", "blueScore": 72.6}
        commit_score_result(ledger, "V1:2026-H1", result)
        assert verify_score_result(ledger, "V1:2026-H1", result) is True

    def test_verify_false_if_result_changed_after_commit(self):
        ledger = HashLedger()
        result = {"vesselId": "V1", "blueScore": 72.6}
        commit_score_result(ledger, "V1:2026-H1", result)
        tampered = {"vesselId": "V1", "blueScore": 99.9}
        assert verify_score_result(ledger, "V1:2026-H1", tampered) is False

    def test_key_order_does_not_affect_verification(self):
        ledger = HashLedger()
        commit_score_result(ledger, "V1:2026-H1", {"vesselId": "V1", "blueScore": 72.6})
        reordered = {"blueScore": 72.6, "vesselId": "V1"}
        assert verify_score_result(ledger, "V1:2026-H1", reordered) is True
