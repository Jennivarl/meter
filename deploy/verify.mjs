// Check that the live contracts run the code in this repo.
//
//   node deploy/verify.mjs            every contract
//   node deploy/verify.mjs proof      just one
//
// The deploy transaction carries each contract's source, so this needs no
// trust in the addresses, the explorer or the README: it fetches what was
// deployed, hashes it, and compares that with the bundle on disk.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { reader } from "./chain.mjs";

const live = JSON.parse(readFileSync(new URL("./live.json", import.meta.url), "utf8"));
const only = process.argv[2];
const names = Object.keys(live.deployTx ?? {}).filter((n) => !only || n === only);
if (!names.length) throw new Error("no such contract in live.json: " + (only ?? "(none deployed)"));

const client = reader();
const sha = (text) => createHash("sha256").update(text, "utf8").digest("hex");
let allMatch = true;

for (const name of names) {
  const tx = await client.getTransaction({ hash: live.deployTx[name] });
  const deployed = Buffer.from(tx.data.contract_code, "base64").toString("utf8");
  const local = readFileSync(new URL(`../contracts/${name}_bundle.py`, import.meta.url), "utf8");
  const same = deployed === local;
  allMatch = allMatch && same;
  console.log(`${name.padEnd(6)} ${live[name]}`);
  console.log(`       on chain  ${String(deployed.length).padStart(6)} bytes  sha256 ${sha(deployed)}`);
  console.log(`       this repo ${String(local.length).padStart(6)} bytes  sha256 ${sha(local)}`);
  console.log(`       ${same ? "IDENTICAL" : "DIFFERENT: rebuild with python -m deploy.build_bundle"}`);
}
// exitCode rather than exit(), so Node closes its sockets cleanly on Windows.
process.exitCode = allMatch ? 0 : 1;
