import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

export default buildModule("HashRegistryModule", (m) => {
  const hashRegistry = m.contract("HashRegistry");
  return { hashRegistry };
});
