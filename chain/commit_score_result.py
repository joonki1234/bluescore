"""
담당: 김준기, 오동규

score/ 최종 결과를 온체인 증적(chain/)에 커밋/검증하는 연결부.

score/가 아직 mock 폴백 상태라 지금은 아무도 호출하지 않지만, score/가
실산출로 전환되는 순간 바로 쓸 수 있도록 미리 준비해둔다. record_id는
호출하는 쪽(예: main.py 시스템 통합, 아직 없음)이 정책에 맞게 정한다 —
여기서는 강제하지 않는다(예: f"{vesselId}:{period}").

ledger 인자는 `chain.ledger.HashLedger`(인메모리)든 `OnChainHashLedger`
(2026-08-14 추가, 실제 컨트랙트 호출)든 상관없다 — 둘 다 `LedgerLike`
(commit/get/verify) 인터페이스를 만족한다.
"""

from typing import Dict

from chain.hashing import compute_result_hash
from chain.ledger import HashRecord, LedgerLike


def commit_score_result(ledger: LedgerLike, record_id: str, result: Dict) -> HashRecord:
    """score/ 최종 결과 dict를 CLAUDE.md 해시 규칙대로 해시화해 ledger에 커밋한다."""
    result_hash = compute_result_hash(result)
    return ledger.commit(record_id, result_hash)


def verify_score_result(ledger: LedgerLike, record_id: str, result: Dict) -> bool:
    """result를 다시 해시화해서, 커밋 당시의 해시와 일치하는지 확인한다."""
    result_hash = compute_result_hash(result)
    return ledger.verify(record_id, result_hash)
