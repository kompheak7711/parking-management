// Seals one text with a public key file, for the backend test that opens it in Python
// (backend/tests/test_telegram_seal.py). Usage: node seal-cli.ts <public.pem> <item id> <text>

import { readFileSync } from "node:fs";

import { importOfficeKey, seal, toBase64 } from "../src/seal.ts";

const [pemPath, itemId, text] = process.argv.slice(2);
if (pemPath === undefined || itemId === undefined || text === undefined) {
  throw new Error("usage: node seal-cli.ts <public.pem> <item id> <text>");
}
const key = await importOfficeKey(readFileSync(pemPath, "utf8"));
process.stdout.write(
  toBase64(await seal(key, new TextEncoder().encode(text), itemId)),
);
