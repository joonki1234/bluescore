"""
담당: 김준기, 오동규

chain/ledger.py의 OnChainHashLedger 단위 테스트.

이 컴퓨터엔 Node.js가 없어 로컬 Hardhat 노드를 띄울 수 없다 — 그래서 아래 테스트는
크게 두 그룹으로 나뉜다:
    - 네트워크 없이 검증 가능한 순수 로직(hex<->bytes32 변환, revert 셀렉터 판별,
      생성자 검증, mock으로 대체한 컨트랙트 호출) — 기본 `pytest -q`에서 항상 돈다.
    - 실제 로컬 Hardhat 노드가 떠 있을 때만 도는 end-to-end 테스트 — RPC 연결이
      안 되면 스스로 skip한다. 실제로 이 경로가 도는지는 Node가 있는 컴퓨터에서
      별도로 확인해야 한다.
"""

from unittest.mock import MagicMock

import pytest

web3 = pytest.importorskip("web3", reason="web3 패키지가 설치돼 있지 않습니다.")

from web3.exceptions import ContractLogicError  # noqa: E402

from chain.ledger import HashRecord, OnChainHashLedger, _error_selector  # noqa: E402

VALID_ADDRESS = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
VALID_HASH = "a" * 64  # 64 hex문자 = 32바이트


def _make_ledger(**overrides) -> OnChainHashLedger:
    kwargs = dict(rpc_url="http://127.0.0.1:1", contract_address=VALID_ADDRESS)
    kwargs.update(overrides)
    return OnChainHashLedger(**kwargs)


class TestConstructorValidation:
    def test_missing_rpc_url_raises(self, monkeypatch):
        monkeypatch.delenv("BLUESCORE_CHAIN_RPC_URL", raising=False)
        with pytest.raises(ValueError):
            OnChainHashLedger(contract_address=VALID_ADDRESS)

    def test_missing_contract_address_raises(self, monkeypatch):
        monkeypatch.delenv("BLUESCORE_HASH_REGISTRY_ADDRESS", raising=False)
        with pytest.raises(ValueError):
            OnChainHashLedger(rpc_url="http://127.0.0.1:1")

    def test_valid_args_construct_without_network_call(self):
        # 생성자는 실제 RPC 접속을 하지 않는다 — 도달 불가능한 주소를 줘도 예외가 나면 안 된다.
        ledger = _make_ledger()
        assert ledger is not None


class TestHexBytes32Conversion:
    def test_round_trip(self):
        raw = OnChainHashLedger._hex_to_bytes32(VALID_HASH)
        assert len(raw) == 32
        assert OnChainHashLedger._bytes32_to_hex(raw) == VALID_HASH

    def test_accepts_0x_prefix(self):
        raw = OnChainHashLedger._hex_to_bytes32("0x" + VALID_HASH)
        assert len(raw) == 32

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError):
            OnChainHashLedger._hex_to_bytes32("abcd")


class TestErrorSelectors:
    """셀렉터는 keccak256(시그니처)[:4]라 네트워크 없이 순수 계산으로 검증 가능하다."""

    def test_selectors_are_four_bytes_and_distinct(self):
        selectors = {
            _error_selector("AlreadyCommitted(string)"),
            _error_selector("EmptyRecordId()"),
            _error_selector("EmptyResultHash()"),
        }
        assert all(len(s) == 4 for s in selectors)
        assert len(selectors) == 3


class TestMapRevertToValueError:
    def _make_exc(self, selector: bytes) -> ContractLogicError:
        exc = ContractLogicError("execution reverted")
        exc.data = "0x" + selector.hex()
        return exc

    def test_already_committed(self):
        ledger = _make_ledger()
        exc = self._make_exc(_error_selector("AlreadyCommitted(string)"))
        result = ledger._map_revert_to_value_error(exc, "vessel-A")
        assert isinstance(result, ValueError)
        assert "vessel-A" in str(result)
        assert "이미 커밋" in str(result)

    def test_empty_record_id(self):
        ledger = _make_ledger()
        exc = self._make_exc(_error_selector("EmptyRecordId()"))
        result = ledger._map_revert_to_value_error(exc, "vessel-A")
        assert "record_id" in str(result)

    def test_empty_result_hash(self):
        ledger = _make_ledger()
        exc = self._make_exc(_error_selector("EmptyResultHash()"))
        result = ledger._map_revert_to_value_error(exc, "vessel-A")
        assert "result_hash" in str(result)

    def test_unknown_selector_falls_back_to_generic_message(self):
        ledger = _make_ledger()
        exc = self._make_exc(b"\x00\x00\x00\x00")
        result = ledger._map_revert_to_value_error(exc, "vessel-A")
        assert isinstance(result, ValueError)
        assert "vessel-A" in str(result)


class TestCommitWithMockedContract:
    def test_empty_record_id_raises_before_touching_contract(self):
        ledger = _make_ledger()
        ledger._contract = MagicMock()
        with pytest.raises(ValueError):
            ledger.commit("", VALID_HASH)
        ledger._contract.functions.commit.assert_not_called()

    def test_empty_result_hash_raises_before_touching_contract(self):
        ledger = _make_ledger()
        ledger._contract = MagicMock()
        with pytest.raises(ValueError):
            ledger.commit("vessel-A", "")
        ledger._contract.functions.commit.assert_not_called()

    def test_already_committed_revert_maps_to_value_error(self):
        ledger = _make_ledger()
        ledger._w3 = MagicMock()
        ledger._w3.eth.accounts = ["0x1111111111111111111111111111111111111111"]

        mock_call = MagicMock()
        exc = ContractLogicError("execution reverted")
        exc.data = "0x" + _error_selector("AlreadyCommitted(string)").hex()
        mock_call.call.side_effect = exc
        ledger._contract = MagicMock()
        ledger._contract.functions.commit.return_value = mock_call

        with pytest.raises(ValueError, match="이미 커밋"):
            ledger.commit("vessel-A", VALID_HASH)

    def test_successful_commit_via_unlocked_account_sends_transaction(self):
        ledger = _make_ledger()
        ledger._w3 = MagicMock()
        sender = "0x1111111111111111111111111111111111111111"
        ledger._w3.eth.accounts = [sender]
        ledger._w3.eth.wait_for_transaction_receipt.return_value = {"blockNumber": 1}
        ledger._w3.eth.get_block.return_value = {"timestamp": 1755100000}

        commit_call = MagicMock()
        commit_call.call.return_value = None  # 시뮬레이션 성공 = revert 없음
        commit_call.transact.return_value = "0xdeadbeef"
        ledger._contract = MagicMock()
        ledger._contract.functions.commit.return_value = commit_call

        record = ledger.commit("vessel-A", VALID_HASH)

        assert isinstance(record, HashRecord)
        assert record.record_id == "vessel-A"
        assert record.result_hash == VALID_HASH
        assert record.ledger_mode == "onchain"
        assert record.block_number == 1
        assert record.contract_address == ledger._contract.address
        commit_call.transact.assert_called_once_with({"from": sender})


class TestGetWithMockedContract:
    def test_returns_none_when_not_exists(self):
        ledger = _make_ledger()
        get_call = MagicMock()
        get_call.call.return_value = (b"\x00" * 32, 0, False)
        ledger._contract = MagicMock()
        ledger._contract.functions.get.return_value = get_call

        assert ledger.get("does-not-exist") is None

    def test_returns_record_when_exists(self):
        ledger = _make_ledger()
        raw_hash = bytes.fromhex(VALID_HASH)
        get_call = MagicMock()
        get_call.call.return_value = (raw_hash, 1755100000, True)
        ledger._contract = MagicMock()
        ledger._contract.functions.get.return_value = get_call

        record = ledger.get("vessel-A")
        assert record is not None
        assert record.result_hash == VALID_HASH


class TestVerifyWithMockedContract:
    def test_delegates_to_contract_verify(self):
        ledger = _make_ledger()
        verify_call = MagicMock()
        verify_call.call.return_value = True
        ledger._contract = MagicMock()
        ledger._contract.functions.verify.return_value = verify_call

        assert ledger.verify("vessel-A", VALID_HASH) is True
        ledger._contract.functions.verify.assert_called_once()


class TestLiveHardhatNodeIfAvailable:
    """실제 로컬 Hardhat 노드(npx hardhat node, 기본 포트 8545)가 떠 있고
    HashRegistry가 배포돼 있을 때만 도는 end-to-end 확인. 안 떠 있으면 skip한다
    — 이 컴퓨터엔 Node가 없어 항상 skip된다."""

    DEFAULT_RPC_URL = "http://127.0.0.1:8545"
    DEFAULT_ADDRESS = VALID_ADDRESS  # Hardhat 로컬 네트워크 첫 배포 주소(결정론적)

    def test_commit_get_verify_round_trip(self):
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(self.DEFAULT_RPC_URL))
        try:
            is_connected = w3.is_connected()
        except Exception:
            is_connected = False
        if not is_connected:
            pytest.skip("로컬 Hardhat 노드(http://127.0.0.1:8545)에 연결할 수 없습니다.")

        ledger = OnChainHashLedger(rpc_url=self.DEFAULT_RPC_URL, contract_address=self.DEFAULT_ADDRESS)
        record_id = f"pytest-onchain-ledger:{id(self)}"
        result_hash = "b" * 64

        record = ledger.commit(record_id, result_hash)
        assert record.result_hash == result_hash

        fetched = ledger.get(record_id)
        assert fetched is not None
        assert fetched.result_hash == result_hash

        assert ledger.verify(record_id, result_hash) is True
        assert ledger.verify(record_id, "c" * 64) is False

        with pytest.raises(ValueError, match="이미 커밋"):
            ledger.commit(record_id, result_hash)
