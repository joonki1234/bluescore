## 담당: 김준기, 오동규

# chain TODO

- [x] SHA-256 해시 생성 함수 (기획서: 온체인 증적 - 스코어/평가 결과 무결성 증명용 해시 생성)
      — `hashing.py`. CLAUDE.md 해시 규칙(sort_keys, 소수점 둘째자리 반올림 후 문자열화,
      빈 값은 키 제외) 그대로 구현, 테스트 12개.
- [x] 해시 커밋/조회 함수 (스코프는 최소한으로) (기획서: 온체인 증적 - 해시값 기록 및 검증 기능, 최소 스코프로 한정)
      — `ledger.py`. 지금은 인메모리 원장(`HashLedger`)이며, Hardhat 연동 전까지의
      임시 구현. commit/get/verify 인터페이스는 유지한 채 나중에 내부만 스마트컨트랙트
      호출로 교체 예정. 테스트 8개.
- [~] Hardhat 테스트넷 연동 (기획서: 온체인 증적 - 테스트넷 환경에서 스마트컨트랙트 배포 및 연동)
      — `hardhat/` 참고. Node.js 설치, Hardhat 3 프로젝트 세팅, `HashRegistry.sol`
      작성(`ledger.py`의 HashLedger와 같은 규칙 — 중복 커밋 revert), 테스트 6개
      통과, 로컬 테스트넷에 실제 배포 + commit/get/verify 호출까지 확인함
      (`hardhat/scripts/verify-deployed.js`). **아직 안 한 것: Python 쪽
      (`ledger.py`)이 이 컨트랙트를 실제로 호출하도록 바꾸는 연동**(web3.py 추가
      필요) — 지금 `HashLedger`는 여전히 인메모리다. 상세는 `hardhat/README.md`.
- [x] score/ ↔ chain/ 연결부 — `commit_score_result.py`(`commit_score_result`/
      `verify_score_result`). score/가 아직 mock 폴백이라 실제로 호출하는 곳은
      없지만, 실산출 전환 시 바로 쓸 수 있게 미리 준비. record_id 정책(예:
      `f"{vesselId}:{period}"`)은 호출부(예정된 main.py)가 정함. 테스트 3개.
- [x] `ui/adapter.py`의 `score_hash()`와 `chain/hashing.py` 해시 일치 검증
      (`explain/TODO.md`의 `TODO(chain/ 김준기·오동규)` 대응) — 실제로 값이
      갈리는 걸 발견함(구분자, 리스트 안 None 처리). `chain/hashing.py`를
      `ui/adapter.py`에 맞춰 통일하고 CLAUDE.md 해시 규칙 문구도 명확히 함.
      `test_hash_matches_ui_adapter.py`로 회귀 방지. **`ui/adapter.score_hash()`를
      `chain.hashing.compute_result_hash()` 호출로 교체하는 배선은 아직 안
      했음 — 최지희님과 조율 필요(TODO 원문: "일치하는지 검증할 것"까지가
      요청 범위였고, 배선 교체는 별도 확인 후).
