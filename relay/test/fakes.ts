// Test stand-ins for Cloudflare D1 (on SQLite, with the real schema.sql) and R2 (a Map).

import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

import type {
  Bytes,
  D1Database,
  D1PreparedStatement,
  D1Result,
  Env,
  R2Bucket,
  R2ObjectBody,
} from "../src/types.ts";

type Value = string | number | null;

class Statement implements D1PreparedStatement {
  private readonly database: DatabaseSync;
  private readonly query: string;
  private readonly values: Value[];

  constructor(database: DatabaseSync, query: string, values: Value[] = []) {
    this.database = database;
    this.query = query;
    this.values = values;
  }

  bind(...values: unknown[]): D1PreparedStatement {
    return new Statement(this.database, this.query, values as Value[]);
  }

  async first<T>(): Promise<T | null> {
    const row = this.database.prepare(this.query).get(...this.values);
    return (row as T | undefined) ?? null;
  }

  async all<T>(): Promise<D1Result<T>> {
    return {
      results: this.database.prepare(this.query).all(...this.values) as T[],
    };
  }

  async run(): Promise<unknown> {
    return this.database.prepare(this.query).run(...this.values);
  }
}

export function fakeDatabase(): D1Database & { sqlite: DatabaseSync } {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  return {
    sqlite,
    prepare: (query: string) => new Statement(sqlite, query),
    batch: async (statements: D1PreparedStatement[]) => {
      sqlite.exec("BEGIN");
      try {
        const results = [];
        for (const statement of statements) {
          results.push(await statement.run());
        }
        sqlite.exec("COMMIT");
        return results;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  };
}

export function fakeBucket(): R2Bucket & { objects: Map<string, Bytes> } {
  const objects = new Map<string, Bytes>();
  return {
    objects,
    put: async (key: string, value: Bytes) => {
      objects.set(key, value);
    },
    get: async (key: string): Promise<R2ObjectBody | null> => {
      const value = objects.get(key);
      return value
        ? { arrayBuffer: async () => value.slice().buffer as ArrayBuffer }
        : null;
    },
    delete: async (keys: string | string[]) => {
      for (const key of Array.isArray(keys) ? keys : [keys]) {
        objects.delete(key);
      }
    },
  };
}

export interface TestKeys {
  publicPem: string;
  privateKey: CryptoKey;
}

export async function officeKeys(): Promise<TestKeys> {
  const pair = await crypto.subtle.generateKey(
    {
      name: "RSA-OAEP",
      modulusLength: 3072,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["encrypt", "decrypt"],
  );
  const spki = new Uint8Array(
    await crypto.subtle.exportKey("spki", pair.publicKey),
  );
  const body = Buffer.from(spki)
    .toString("base64")
    .replace(/(.{64})/g, "$1\n");
  return {
    publicPem: `-----BEGIN PUBLIC KEY-----\n${body}\n-----END PUBLIC KEY-----\n`,
    privateKey: pair.privateKey,
  };
}

// The office's opening step, as in backend/src/property_rental/telegram_seal.py.
export async function openSealed(key: CryptoKey, sealed: Bytes, id: string) {
  if (new TextDecoder().decode(sealed.subarray(0, 3)) !== "CS1") {
    throw new Error("not sealed");
  }
  const length = ((sealed[3] ?? 0) << 8) | (sealed[4] ?? 0);
  const wrapped = sealed.subarray(5, 5 + length);
  const nonce = sealed.subarray(5 + length, 17 + length);
  const body = sealed.subarray(17 + length);
  const secret = new Uint8Array(
    await crypto.subtle.decrypt({ name: "RSA-OAEP" }, key, wrapped),
  );
  const aes = await crypto.subtle.importKey("raw", secret, "AES-GCM", false, [
    "decrypt",
  ]);
  return new Uint8Array(
    await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: nonce,
        additionalData: new TextEncoder().encode(id),
      },
      aes,
      body,
    ),
  );
}

export const PULL_KEY = "11".repeat(32);

export function testEnv(publicPem: string): Env & {
  DB: ReturnType<typeof fakeDatabase>;
  MEDIA: ReturnType<typeof fakeBucket>;
} {
  return {
    DB: fakeDatabase(),
    MEDIA: fakeBucket(),
    OFFICE_PUBLIC_KEY: publicPem,
    OFFICE_PULL_KEY: PULL_KEY,
    TENANT_BOT_TOKEN: "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    TENANT_WEBHOOK_SECRET: "tenant-webhook-secret",
    STAFF_BOT_TOKEN: "654321:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    STAFF_WEBHOOK_SECRET: "staff-webhook-secret",
    TELEGRAM_API: "https://telegram.test",
  };
}

// A signed office call, as the office pull job makes it.
export async function officeRequest(
  method: string,
  pathAndQuery: string,
  now: number,
  body?: unknown,
  key = PULL_KEY,
): Promise<Request> {
  const bytes =
    body === undefined
      ? new Uint8Array()
      : new TextEncoder().encode(JSON.stringify(body));
  const digest = Buffer.from(
    await crypto.subtle.digest("SHA-256", bytes),
  ).toString("hex");
  const hmacKey = await crypto.subtle.importKey(
    "raw",
    Buffer.from(key, "hex"),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = Buffer.from(
    await crypto.subtle.sign(
      "HMAC",
      hmacKey,
      new TextEncoder().encode(`${now}\n${method}\n${pathAndQuery}\n${digest}`),
    ),
  ).toString("hex");
  return new Request(`https://relay.test${pathAndQuery}`, {
    method,
    headers: { "x-office-time": String(now), "x-office-signature": signature },
    body: body === undefined ? undefined : bytes,
  });
}
