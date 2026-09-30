// UNTESTED IN THIS REPOSITORY'S OFFLINE ENVIRONMENT. It follows the genlayer-js 1.1.8 API used by the
// frontend (createClient / createAccount / deployContract / waitForTransactionReceipt).
// The recommended path is to paste contracts/agenttrust.py into GenLayer Studio (docs/DEPLOYMENT.md).
//
//   cd scripts/deploy && npm install
//   PRIVATE_KEY=0x... node deploy.mjs            # studionet
//   PRIVATE_KEY=0x... CONTRACT=../../build/agenttrust_short_window.py node deploy.mjs   # short windows, testing only
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const here = dirname(fileURLToPath(import.meta.url));
const file = resolve(process.env.CONTRACT || resolve(here, "../../contracts/agenttrust.py"));
const key = process.env.PRIVATE_KEY;
if (!key || !/^0x[0-9a-fA-F]{64}$/.test(key)) {
  console.error("Set PRIVATE_KEY to a 0x-prefixed 32-byte hex key of a funded Studio account.");
  process.exit(2);
}

const code = readFileSync(file, "utf8");
if (code.split("\n")[0].trim() !== "# v0.2.16") {
  console.error("Refusing to deploy: the first line of the contract is not the expected '# v0.2.16' header.");
  process.exit(2);
}

const account = createAccount(key);
const client = createClient({ chain: studionet, account });
console.log("deploying", file, "(" + code.length + " bytes) from", account.address);

const hash = await client.deployContract({ code, args: [], leaderOnly: false });
console.log("deployment transaction:", hash);
const receipt = await client.waitForTransactionReceipt({ hash, status: "ACCEPTED", interval: 5000, retries: 120 });
const address = receipt?.data?.contract_address ?? receipt?.txDataDecoded?.contractAddress ?? receipt?.to_address;
if (!address) {
  console.error("Deployed, but the contract address was not found in the receipt. Read it from Studio and continue by hand.");
  console.error(JSON.stringify(receipt, (k, v) => (typeof v === "bigint" ? v.toString() : v)).slice(0, 2000));
  process.exit(1);
}
console.log("contract address:", address);

const info = await client.readContract({ address, functionName: "get_protocol_info", args: [] });
console.log("protocol:", info instanceof Map ? Object.fromEntries(info) : info);
console.log("\nPut the address in frontend/assets/config.js (contractAddress) or paste it into Settings on the page.");
