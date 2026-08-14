# chain/hardhat

담당: 김준기, 오동규

`chain/hashing.py` / `chain/ledger.py`(파이썬)와 별개로, 실제 온체인 증적을 위한
Hardhat 프로젝트다. `HashRegistry.sol`은 `HashLedger`(Python)와 같은 규칙을
Solidity로 옮긴 것 — 한 번 커밋된 recordId는 덮어쓸 수 없다.

## 실행

```bash
cd chain/hardhat
npm install

# 컴파일 + 테스트(시뮬레이션 네트워크, 순식간에 끝남)
npx hardhat test

# 로컬 테스트넷을 띄워두고 실제로 배포/호출해보기
npx hardhat node                                            # 터미널 1
npx hardhat ignition deploy ignition/modules/HashRegistry.js --network localhost   # 터미널 2
npx hardhat run scripts/verify-deployed.js --network localhost                     # 터미널 2
```

## 현재 상태 (2026-08-14)

- 컨트랙트 작성 + 컴파일 + 테스트(6개) 완료
- 로컬 Hardhat 테스트넷에 실제 배포 + commit/get/verify 호출까지 확인함
  (`scripts/verify-deployed.js`)
- **Python 쪽 연동 완료**: `chain/ledger.py`의 `OnChainHashLedger`가 web3.py로
  이 컨트랙트를 실제로 호출한다(`chain/hash_registry_abi.json`에 ABI를 손으로
  작성해 커밋해둠 — `artifacts/`가 gitignore라 컴파일 없이 Python만으로 쓰려면
  이 방법이 필요했다). `BLUESCORE_CHAIN_RPC_URL` / `BLUESCORE_HASH_REGISTRY_ADDRESS`
  환경변수로 접속 정보를 받는다.
  **2026-08-14 end-to-end 확인 완료**: Node 설치 → `npm install` → 로컬 노드 →
  `npx hardhat ignition deploy` → `python -m pytest chain/test_onchain_ledger.py -v`
  순서로 실제 커밋/조회/검증/중복커밋 revert까지 전부 확인함
  (`TestLiveHardhatNodeIfAvailable::test_commit_get_verify_round_trip` PASS).
- `artifacts/`, `cache/`, `types/`, `ignition/deployments/`, `node_modules/`는
  로컬 빌드 산출물이라 `.gitignore`에 넣었다 — 클론 후 `npm install` +
  `npx hardhat compile`로 다시 만들 수 있다.
