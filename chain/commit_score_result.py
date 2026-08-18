"""
담당: 김준기, 오동규

score/ 최종 결과를 온체인 증적(chain/)에 커밋/검증하는 연결부.

**(2026-08-18 현황 정리)**
- `commit_score_result()`는 이제 실제로는 `services/workflow.py`의
  `commit_report()`가 대체하고 있다 — 그쪽은 중복 커밋 시 DB-원장 불일치
  복구 등 더 정교한 예외처리가 있어서, 이 단순 버전으로 억지로 바꿔치기하지
  않았다(둘 다 살아있는 게 아니라, workflow.py 쪽이 사실상의 구현이라는 뜻).
- `verify_score_result()`는 여전히 아무도 안 씀 — 다만 죽은 코드가 아니라
  **아직 안 만들어진 기능(해시 위조 검증 API/UI, 최지희님이 처음에 "가장
  임팩트 있는 한 장면"으로 꼽았던 것)이 생기면 바로 쓰일 자리**다. 원문을
  고친 뒤 재해시해서 커밋 당시 해시와 비교하는 로직이 정확히 이 함수다.

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
