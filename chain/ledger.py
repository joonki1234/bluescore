"""
담당: 김준기, 오동규

해시 커밋/조회 — 최소 스코프(minimal scope)의 원장(ledger).

참고: BlueScore 프로젝트 기획서 - 온체인 증적(해시값 기록 및 검증 기능, 최소 스코프로
한정).

한 번 커밋된 record_id는 덮어쓸 수 없다 — 증적(evidence)이라는 목적상 같은 산출
결과에 대해 나중에 값이 바뀌어 보이면 안 되기 때문이다.

이 파일엔 같은 commit/get/verify 인터페이스를 가진 구현이 두 개 있다:
    - `HashLedger`: 인메모리. Node/Hardhat 없이 어디서나 동작하고, 이 프로젝트의
      기본 pytest 스위트가 이걸로 돈다.
    - `OnChainHashLedger`: `chain/hardhat/`에 배포된
      `HashRegistry.sol`을 web3.py로 실제 호출한다. `HashLedger`를 대체하는 게
      아니라 나란히 두는 것 — 로컬에 Hardhat 노드를 안 띄운 컴퓨터에서도 기존
      테스트가 그대로 통과해야 하기 때문이다. 실제 사용은 호출부가 어느 클래스를
      쓸지 선택하면 된다(`chain/commit_score_result.py`는 둘 다 받는다, `LedgerLike`
      참고).
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class HashRecord:
    record_id: str
    result_hash: str
    committed_at: datetime
    ledger_mode: str = "local"
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    contract_address: Optional[str] = None


class HashLedger:
    """해시 커밋/조회를 위한 최소 스코프 인메모리 원장."""

    def __init__(self) -> None:
        self._records: Dict[str, HashRecord] = {}

    def commit(self, record_id: str, result_hash: str) -> HashRecord:
        if not record_id:
            raise ValueError("record_id는 비어 있을 수 없습니다.")
        if not result_hash:
            raise ValueError("result_hash는 비어 있을 수 없습니다.")
        if record_id in self._records:
            raise ValueError(f"record_id '{record_id}'는 이미 커밋되어 있습니다.")

        record = HashRecord(
            record_id=record_id,
            result_hash=result_hash,
            committed_at=datetime.now(timezone.utc),
        )
        self._records[record_id] = record
        return record

    def get(self, record_id: str) -> Optional[HashRecord]:
        return self._records.get(record_id)

    def verify(self, record_id: str, expected_hash: str) -> bool:
        record = self.get(record_id)
        if record is None:
            return False
        return record.result_hash == expected_hash


try:
    from typing import Protocol
except ImportError:  # pragma: no cover - Python < 3.8은 이 프로젝트에서 안 씀
    Protocol = object  # type: ignore[assignment, misc]


class LedgerLike(Protocol):
    """`HashLedger`/`OnChainHashLedger` 둘 다 만족하는 구조적 타입 — 호출부가
    어느 구현인지 신경 쓰지 않게 하려는 용도(`chain/commit_score_result.py` 참고)."""

    def commit(self, record_id: str, result_hash: str) -> HashRecord: ...
    def get(self, record_id: str) -> Optional[HashRecord]: ...
    def verify(self, record_id: str, expected_hash: str) -> bool: ...


_ABI_PATH = Path(__file__).resolve().parent / "hash_registry_abi.json"

# HashRegistry.sol의 커스텀 에러 셀렉터(keccak256(시그니처)[:4]) — 트랜잭션이
# revert됐을 때 어떤 에러인지 판별하는 데 쓴다. 이 값 자체는 순수 계산이라
# 네트워크 없이도 검증 가능하다(chain/test_onchain_ledger.py 참고).
def _error_selector(signature: str) -> bytes:
    from web3 import Web3

    return Web3.keccak(text=signature)[:4]


class OnChainHashLedger:
    """`HashLedger`와 같은 commit/get/verify 인터페이스를 갖는, 실제 배포된
    `HashRegistry` 스마트컨트랙트(web3.py) 기반 구현.

    로컬 Hardhat 노드(`npx hardhat node` + `chain/hardhat/ignition/modules/
    HashRegistry.js` 배포)가 떠 있어야 실제로 동작한다. 이 프로젝트엔 Node가
    없는 컴퓨터도 있을 수 있어, 생성자에서 네트워크에 바로 접속하지는 않는다 —
    실제 RPC 호출은 commit/get/verify를 부를 때 처음 일어난다.

    서명 방식은 두 가지를 지원한다:
        - private_key(또는 BLUESCORE_CHAIN_PRIVATE_KEY)를 주면 그 키로 직접
          서명해서 보낸다 — 공개 테스트넷 등 어디서나 동작.
        - 안 주면 `w3.eth.accounts[0]`(연결된 노드가 잠금 해제해서 제공하는
          첫 계정)을 보내는 사람으로 쓴다 — 로컬 Hardhat 노드 전용 지름길이다.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        contract_address: Optional[str] = None,
        private_key: Optional[str] = None,
    ) -> None:
        rpc_url = rpc_url or os.environ.get("BLUESCORE_CHAIN_RPC_URL")
        contract_address = contract_address or os.environ.get("BLUESCORE_HASH_REGISTRY_ADDRESS")
        if not rpc_url:
            raise ValueError("rpc_url이 필요합니다 (인자로 주거나 BLUESCORE_CHAIN_RPC_URL 환경변수로 설정).")
        if not contract_address:
            raise ValueError(
                "contract_address가 필요합니다 (인자로 주거나 BLUESCORE_HASH_REGISTRY_ADDRESS 환경변수로 설정)."
            )

        from web3 import Web3

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        abi = json.loads(_ABI_PATH.read_text(encoding="utf-8"))
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=abi
        )

        self._private_key = private_key or os.environ.get("BLUESCORE_CHAIN_PRIVATE_KEY")
        self._account = self._w3.eth.account.from_key(self._private_key) if self._private_key else None

    @staticmethod
    def _hex_to_bytes32(result_hash: str) -> bytes:
        hex_part = result_hash[2:] if result_hash.startswith("0x") else result_hash
        raw = bytes.fromhex(hex_part)
        if len(raw) != 32:
            raise ValueError(
                f"result_hash는 32바이트(64 hex 문자)여야 합니다 — 받은 값은 {len(raw)}바이트입니다."
            )
        return raw

    @staticmethod
    def _bytes32_to_hex(value: bytes) -> str:
        return value.hex()

    def _sender_address(self) -> str:
        if self._account is not None:
            return self._account.address
        accounts = self._w3.eth.accounts
        if not accounts:
            raise ValueError(
                "서명에 쓸 계정이 없습니다 — private_key를 주거나, 연결된 노드가 계정을 "
                "잠금 해제해서 제공해야 합니다(로컬 Hardhat 노드는 기본으로 그렇게 합니다)."
            )
        return accounts[0]

    def _map_revert_to_value_error(self, exc: Exception, record_id: str) -> ValueError:
        data = getattr(exc, "data", None)
        selector: Optional[bytes] = None
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 10:
            selector = bytes.fromhex(data[2:10])
        elif isinstance(data, (bytes, bytearray)) and len(data) >= 4:
            selector = bytes(data[:4])

        if selector == _error_selector("AlreadyCommitted(string)"):
            return ValueError(f"record_id '{record_id}'는 이미 커밋되어 있습니다.")
        if selector == _error_selector("EmptyRecordId()"):
            return ValueError("record_id는 비어 있을 수 없습니다.")
        if selector == _error_selector("EmptyResultHash()"):
            return ValueError("result_hash는 비어 있을 수 없습니다.")
        return ValueError(f"온체인 커밋 실패 (record_id='{record_id}'): {exc}")

    def commit(self, record_id: str, result_hash: str) -> HashRecord:
        if not record_id:
            raise ValueError("record_id는 비어 있을 수 없습니다.")
        if not result_hash:
            raise ValueError("result_hash는 비어 있을 수 없습니다.")

        from web3.exceptions import ContractLogicError

        result_hash_bytes = self._hex_to_bytes32(result_hash)
        sender = self._sender_address()

        # 먼저 call()로 시뮬레이션해서 revert 여부를 gas 없이 확인한다 — 실패하면
        # 여기서 HashLedger와 같은 ValueError로 바꿔서 던지고, 실제 트랜잭션은
        # 보내지 않는다.
        try:
            self._contract.functions.commit(record_id, result_hash_bytes).call({"from": sender})
        except ContractLogicError as exc:
            raise self._map_revert_to_value_error(exc, record_id) from exc

        if self._account is not None:
            tx = self._contract.functions.commit(record_id, result_hash_bytes).build_transaction(
                {
                    "from": self._account.address,
                    "nonce": self._w3.eth.get_transaction_count(self._account.address),
                }
            )
            signed = self._account.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        else:
            tx_hash = self._contract.functions.commit(record_id, result_hash_bytes).transact(
                {"from": sender}
            )

        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash)
        block = self._w3.eth.get_block(receipt["blockNumber"])
        return HashRecord(
            record_id=record_id,
            result_hash=result_hash,
            committed_at=datetime.fromtimestamp(block["timestamp"], tz=timezone.utc),
            ledger_mode="onchain",
            transaction_hash=tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash),
            block_number=int(receipt["blockNumber"]),
            contract_address=self._contract.address,
        )

    def get(self, record_id: str) -> Optional[HashRecord]:
        result_hash_bytes, committed_at, exists = self._contract.functions.get(record_id).call()
        if not exists:
            return None
        return HashRecord(
            record_id=record_id,
            result_hash=self._bytes32_to_hex(result_hash_bytes),
            committed_at=datetime.fromtimestamp(committed_at, tz=timezone.utc),
            ledger_mode="onchain",
            contract_address=self._contract.address,
        )

    def verify(self, record_id: str, expected_hash: str) -> bool:
        expected_hash_bytes = self._hex_to_bytes32(expected_hash)
        return self._contract.functions.verify(record_id, expected_hash_bytes).call()
