// 배포된 HashRegistry에 실제로 commit/get을 호출해 로컬 테스트넷 연동을 확인하는 스크립트.
import { network } from "hardhat";
import { keccak256, toUtf8Bytes } from "ethers";

const { ethers } = await network.getOrCreate("localhost");

const ADDRESS = "0x5FbDB2315678afecb367f032d93F642f64180aa3";

async function main() {
  const registry = await ethers.getContractAt("HashRegistry", ADDRESS);
  const recordId = `verify-script:${Date.now()}`;
  const resultHash = keccak256(toUtf8Bytes(JSON.stringify({ demo: true, score: 72.6 })));

  console.log(`[commit] recordId=${recordId}`);
  const tx = await registry.commit(recordId, resultHash);
  await tx.wait();

  const [storedHash, committedAt, exists] = await registry.get(recordId);
  console.log(`[get] exists=${exists} storedHash=${storedHash} committedAt=${committedAt}`);
  console.log(`[verify] matches=${await registry.verify(recordId, resultHash)}`);
  console.log(`[verify] tampered=${await registry.verify(recordId, keccak256(toUtf8Bytes("다른 값")))}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
