// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title HashRegistry
/// @notice BlueScore 산출 결과의 SHA-256 해시를 온체인에 기록/조회하는 최소 스코프
/// 컨트랙트. Python 쪽 chain/ledger.py의 HashLedger와 같은 규칙을 그대로 옮긴다:
/// 한 번 커밋된 recordId는 덮어쓸 수 없다 — 증적(evidence)이라는 목적상 같은 산출
/// 결과에 대해 나중에 값이 바뀌어 보이면 안 되기 때문이다.
contract HashRegistry {
    struct Record {
        bytes32 resultHash;
        uint256 committedAt;
        bool exists;
    }

    mapping(string => Record) private records;

    event HashCommitted(string indexed recordId, bytes32 resultHash, uint256 committedAt);

    error EmptyRecordId();
    error EmptyResultHash();
    error AlreadyCommitted(string recordId);

    /// @notice recordId에 대한 해시를 커밋한다. 이미 커밋된 recordId면 되돌린다(revert).
    function commit(string calldata recordId, bytes32 resultHash) external {
        if (bytes(recordId).length == 0) revert EmptyRecordId();
        if (resultHash == bytes32(0)) revert EmptyResultHash();
        if (records[recordId].exists) revert AlreadyCommitted(recordId);

        records[recordId] = Record({resultHash: resultHash, committedAt: block.timestamp, exists: true});
        emit HashCommitted(recordId, resultHash, block.timestamp);
    }

    /// @notice recordId로 커밋된 해시와 커밋 시각을 조회한다. 없으면 exists=false.
    function get(string calldata recordId) external view returns (bytes32 resultHash, uint256 committedAt, bool exists) {
        Record memory record = records[recordId];
        return (record.resultHash, record.committedAt, record.exists);
    }

    /// @notice recordId에 커밋된 해시가 expectedHash와 일치하는지 확인한다.
    function verify(string calldata recordId, bytes32 expectedHash) external view returns (bool) {
        Record memory record = records[recordId];
        if (!record.exists) return false;
        return record.resultHash == expectedHash;
    }
}
