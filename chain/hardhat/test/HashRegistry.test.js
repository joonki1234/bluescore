// 담당: 김준기, 오동규
import { expect } from "chai";
import { network } from "hardhat";
import { keccak256, toUtf8Bytes } from "ethers";

const { ethers } = await network.getOrCreate();

function hashOf(text) {
  return keccak256(toUtf8Bytes(text));
}

describe("HashRegistry", function () {
  async function deploy() {
    const factory = await ethers.getContractFactory("HashRegistry");
    return factory.deploy();
  }

  it("commit 후 get으로 같은 해시를 조회할 수 있다", async function () {
    const registry = await deploy();
    const resultHash = hashOf("V1:2026-H1");

    await registry.commit("V1:2026-H1", resultHash);
    const [storedHash, , exists] = await registry.get("V1:2026-H1");

    expect(exists).to.equal(true);
    expect(storedHash).to.equal(resultHash);
  });

  it("존재하지 않는 recordId는 exists=false", async function () {
    const registry = await deploy();
    const [, , exists] = await registry.get("ghost");
    expect(exists).to.equal(false);
  });

  it("같은 recordId를 두 번 커밋하면 revert된다", async function () {
    const registry = await deploy();
    const resultHash = hashOf("V1:2026-H1");
    await registry.commit("V1:2026-H1", resultHash);

    await expect(registry.commit("V1:2026-H1", hashOf("다른 값"))).to.be.revertedWithCustomError(
      registry,
      "AlreadyCommitted",
    );
  });

  it("빈 recordId는 revert된다", async function () {
    const registry = await deploy();
    await expect(registry.commit("", hashOf("x"))).to.be.revertedWithCustomError(registry, "EmptyRecordId");
  });

  it("verify는 일치하면 true, 다르면 false를 반환한다", async function () {
    const registry = await deploy();
    const resultHash = hashOf("V1:2026-H1");
    await registry.commit("V1:2026-H1", resultHash);

    expect(await registry.verify("V1:2026-H1", resultHash)).to.equal(true);
    expect(await registry.verify("V1:2026-H1", hashOf("변조된 값"))).to.equal(false);
  });

  it("verify는 존재하지 않는 recordId면 false를 반환한다", async function () {
    const registry = await deploy();
    expect(await registry.verify("ghost", hashOf("x"))).to.equal(false);
  });
});
