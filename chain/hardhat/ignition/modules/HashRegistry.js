// 담당: 김준기, 오동규
import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

export default buildModule("HashRegistryModule", (m) => {
  const hashRegistry = m.contract("HashRegistry");
  return { hashRegistry };
});
