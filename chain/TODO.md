## 담당: 김준기, 오동규

# chain TODO

## 현재 상태 (2026-08-18)

해시 생성·인메모리 원장·Hardhat 실배포·Python(web3.py) 연동·FastAPI 업무 흐름
배선까지 전부 완료했다. `WorkflowService`가 `chain.hashing.compute_result_hash()`와
`LedgerLike`(인메모리 `HashLedger` 또는 온체인 `OnChainHashLedger`)를 사용한다.

---

- [x] SHA-256 해시 생성 — `hashing.py`. CLAUDE.md 해시 규칙(sort_keys, 소수점
      둘째자리 반올림 후 문자열화, 빈 값은 키 제외) 그대로 구현.
- [x] 해시 커밋/조회 — `ledger.py`의 `HashLedger`(인메모리)와 `OnChainHashLedger`
      (web3.py 기반, `HashRegistry.sol` 호출). commit/get/verify 인터페이스는
      두 구현이 동일해 호출부가 어느 쪽을 쓰든 코드를 바꿀 필요가 없다.
- [x] Hardhat 로컬 네트워크 연동 — `hardhat/`의 `HashRegistry.sol`(중복 커밋
      revert)을 Hardhat 3 프로젝트로 빌드·배포하고, 실제 로컬 노드에 대고
      commit→get→verify→중복커밋 revert까지 end-to-end로 검증했다. 상세는
      `hardhat/README.md`. `OnChainHashLedger`는 로컬 노드가 떠 있지 않으면
      해당 테스트가 자동 skip되므로 평소 개발 시 Node 실행 없이도 테스트가 돈다.
- [x] score/ ↔ chain/ 연결부 — `commit_score_result.py`. 실제 서비스 경로는
      더 정교한 예외처리를 포함한 `services/workflow.py::commit_report()`가
      대체해서 쓴다.
- [x] 해시 위조 검증 API/UI — **구현하지 않기로 결정(2026-08-18)**.
      `verify_score_result()`는 재계산·비교 로직 자체는 남겨 두되, 이를
      호출하는 별도 엔드포인트나 화면은 만들지 않는다.
- [x] FastAPI 업무 흐름 연결 — `WorkflowService.commit_report()`가 승인/보류
      뒤 온체인 커밋하고 트랜잭션 해시·블록번호·기록시각·컨트랙트 주소를
      SQLite에 저장한다. 금융기관 화면은 Record ID 조회 API 결과만 표시한다.
