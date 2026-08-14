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
- **Python 쪽 연동은 아직 안 함**: `chain/ledger.py`의 `HashLedger`는 여전히
  인메모리다. 이 컨트랙트를 실제로 호출하도록 바꾸려면 `web3.py`(또는 유사
  라이브러리)를 추가하고, ABI(`artifacts/contracts/HashRegistry.sol/HashRegistry.json`,
  gitignore됨 — `npx hardhat compile`로 재생성)를 읽어와 트랜잭션을 보내는
  코드가 필요하다. 다음 단계로 남겨둔다.
- `artifacts/`, `cache/`, `types/`, `ignition/deployments/`, `node_modules/`는
  로컬 빌드 산출물이라 `.gitignore`에 넣었다 — 클론 후 `npm install` +
  `npx hardhat compile`로 다시 만들 수 있다.
