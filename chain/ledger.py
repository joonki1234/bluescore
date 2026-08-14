"""
담당: 김준기, 오동규

해시 커밋/조회 — 최소 스코프(minimal scope)의 인메모리 원장(ledger).

참고: BlueScore 프로젝트 기획서 - 온체인 증적(해시값 기록 및 검증 기능, 최소 스코프로
한정). Hardhat 테스트넷 연동 전까지 임시로 쓰는 구현이다. 연동 후에는 이 모듈의
commit/get/verify 인터페이스는 유지한 채, 내부 저장소만 스마트컨트랙트 호출로 교체할
예정이다 (TODO).

한 번 커밋된 record_id는 덮어쓸 수 없다 — 증적(evidence)이라는 목적상 같은 산출
결과에 대해 나중에 값이 바뀌어 보이면 안 되기 때문이다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass(frozen=True)
class HashRecord:
    record_id: str
    result_hash: str
    committed_at: datetime


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
