"""

chain/ledger.py 단위 테스트.
"""

import pytest

from chain.ledger import HashLedger


class TestHashLedger:
    def test_commit_then_get_returns_same_hash(self):
        ledger = HashLedger()
        ledger.commit("vessel-A-2026-08", "abc123")
        record = ledger.get("vessel-A-2026-08")
        assert record is not None
        assert record.result_hash == "abc123"

    def test_get_unknown_id_returns_none(self):
        ledger = HashLedger()
        assert ledger.get("does-not-exist") is None

    def test_duplicate_commit_raises(self):
        ledger = HashLedger()
        ledger.commit("vessel-A-2026-08", "abc123")
        with pytest.raises(ValueError):
            ledger.commit("vessel-A-2026-08", "def456")

    def test_empty_record_id_raises(self):
        ledger = HashLedger()
        with pytest.raises(ValueError):
            ledger.commit("", "abc123")

    def test_empty_hash_raises(self):
        ledger = HashLedger()
        with pytest.raises(ValueError):
            ledger.commit("vessel-A-2026-08", "")

    def test_verify_true_for_matching_hash(self):
        ledger = HashLedger()
        ledger.commit("vessel-A-2026-08", "abc123")
        assert ledger.verify("vessel-A-2026-08", "abc123") is True

    def test_verify_false_for_mismatched_hash(self):
        ledger = HashLedger()
        ledger.commit("vessel-A-2026-08", "abc123")
        assert ledger.verify("vessel-A-2026-08", "wrong") is False

    def test_verify_false_for_unknown_id(self):
        ledger = HashLedger()
        assert ledger.verify("does-not-exist", "abc123") is False
