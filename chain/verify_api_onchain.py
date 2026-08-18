"""

FastAPI 업무 흐름이 실제 로컬 HashRegistry까지 이어지는지 확인하는 실행 스크립트.
Hardhat 노드와 컨트랙트를 먼저 띄운 뒤 실행한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from chain.ledger import OnChainHashLedger


RPC_URL = "http://127.0.0.1:8545"
CONTRACT_ADDRESS = "0x5FbDB2315678afecb367f032d93F642f64180aa3"


def main() -> None:
    ledger = OnChainHashLedger(rpc_url=RPC_URL, contract_address=CONTRACT_ADDRESS)
    with tempfile.TemporaryDirectory(prefix="bluescore-onchain-") as directory:
        client = TestClient(
            create_app(Path(directory) / "verify.db", ledger=ledger, seed_if_empty=True)
        )
        score = client.get("/vessels/VESSEL_B/score").json()
        appeal = client.post(
            "/appeals",
            json={
                "scoreRunId": score["scoreRunId"],
                "reason": "온체인 통합 검증",
                "detail": "가명 시연 데이터의 API 배선을 확인합니다.",
            },
        ).json()
        reviewed = client.post(
            f"/appeals/{appeal['appealId']}/review",
            json={"decision": "approve", "reason": "통합 검증", "reviewer": "검증 스크립트"},
        )
        reviewed.raise_for_status()
        committed = client.post(f"/reports/{score['scoreRunId']}/commit")
        committed.raise_for_status()
        body = committed.json()
        looked_up = client.get(f"/chain/records/{body['recordId']}")
        looked_up.raise_for_status()
        assert body["ledgerMode"] == "onchain"
        assert body["transactionHash"]
        assert body["blockNumber"] is not None
        assert body["contractAddress"].lower() == CONTRACT_ADDRESS.lower()
        assert looked_up.json()["resultHash"] == body["resultHash"]
        print(
            f"온체인 API 검증 통과 · recordId={body['recordId']} · "
            f"block={body['blockNumber']} · tx={body['transactionHash']}"
        )


if __name__ == "__main__":
    main()
