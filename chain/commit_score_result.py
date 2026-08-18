"""
담당: 김준기, 오동규

score/ 최종 결과를 온체인 증적(chain/)에 커밋/검증하는 연결부.

`commit_score_result()`는 실제로는 `services/workflow.py`의 `commit_report()`가
대체해서 쓰인다(중복 커밋 시 DB-원장 불일치 복구 등 더 정교한 예외처리가 있어서).
`verify_score_result()`는 아직 호출부가 없지만 죽은 코드는 아니다 — 해시 위조 검증
API/UI가 생기면 바로 쓰일 자리다(원문을 재해시해 커밋 당시 해시와 비교).

ledger 인자는 `HashLedger`(인메모리)든 `OnChainHashLedger`(실제 컨트랙트 호출)든
상관없다 — 둘 다 `LedgerLike`(commit/get/verify) 인터페이스를 만족한다.
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
