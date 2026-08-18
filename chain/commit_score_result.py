"""
담당: 김준기, 오동규

점수 결과 해시를 원장에 기록하고 검증한다.
실제 커밋은 `WorkflowService.commit_report()`에서 처리한다.
"""

from typing import Dict

from chain.hashing import compute_result_hash
from chain.ledger import HashRecord, LedgerLike


def commit_score_result(ledger: LedgerLike, record_id: str, result: Dict) -> HashRecord:
    result_hash = compute_result_hash(result)
    return ledger.commit(record_id, result_hash)


def verify_score_result(ledger: LedgerLike, record_id: str, result: Dict) -> bool:  
    result_hash = compute_result_hash(result)
    return ledger.verify(record_id, result_hash)
