// Sealing with the office's public key (bots plan, "The relay", job 3).
//
// Every message and photo is sealed before it is stored, so only the office computer, which
// holds the private key, can open what waits here. Not even Cloudflare can read it.
//
// Format (opened by backend/src/property_rental/telegram_seal.py):
//   "CS1" | wrapped key length (2 bytes, big-endian) | AES key wrapped with RSA-OAEP SHA-256
//         | nonce (12 bytes) | AES-256-GCM ciphertext and tag
// The AES-GCM associated data is the item's own id, so a sealed item cannot move to another id.

import type { Bytes } from "./types.ts";

const MAGIC = new TextEncoder().encode("CS1");

function pemToDer(pem: string): Bytes {
  const body = pem
    .replace(/-----BEGIN PUBLIC KEY-----/, "")
    .replace(/-----END PUBLIC KEY-----/, "")
    .replace(/\s+/g, "");
  if (!/^[A-Za-z0-9+/=]+$/.test(body)) {
    throw new Error("office_key_invalid");
  }
  return Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
}

export async function importOfficeKey(pem: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "spki",
    pemToDer(pem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
}

export async function seal(
  officeKey: CryptoKey,
  plain: Bytes,
  itemId: string,
): Promise<Bytes> {
  const secret = crypto.getRandomValues(new Uint8Array(32));
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const aesKey = await crypto.subtle.importKey(
    "raw",
    secret,
    "AES-GCM",
    false,
    ["encrypt"],
  );
  const body = new Uint8Array(
    await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv: nonce,
        additionalData: new TextEncoder().encode(itemId),
      },
      aesKey,
      plain,
    ),
  );
  const wrapped = new Uint8Array(
    await crypto.subtle.encrypt({ name: "RSA-OAEP" }, officeKey, secret),
  );
  secret.fill(0);
  const out = new Uint8Array(
    MAGIC.length + 2 + wrapped.length + nonce.length + body.length,
  );
  let at = 0;
  out.set(MAGIC, at);
  at += MAGIC.length;
  out[at] = (wrapped.length >> 8) & 0xff;
  out[at + 1] = wrapped.length & 0xff;
  at += 2;
  out.set(wrapped, at);
  at += wrapped.length;
  out.set(nonce, at);
  at += nonce.length;
  out.set(body, at);
  return out;
}

export function toBase64(bytes: Bytes): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(text);
}

export async function sha256Hex(bytes: Bytes): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}
