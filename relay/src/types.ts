// The small part of the Cloudflare Workers API the relay uses (D1 database, R2 storage), written
// out here so the relay needs no extra package. Cloudflare provides the real objects.

// Bytes held in a plain ArrayBuffer (what Web Crypto takes).
export type Bytes = Uint8Array<ArrayBuffer>;

export interface D1Result<T> {
  results: T[];
}

export interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  all<T = Record<string, unknown>>(): Promise<D1Result<T>>;
  run(): Promise<unknown>;
}

export interface D1Database {
  prepare(query: string): D1PreparedStatement;
  batch(statements: D1PreparedStatement[]): Promise<unknown[]>;
}

export interface R2ObjectBody {
  arrayBuffer(): Promise<ArrayBuffer>;
}

export interface R2Bucket {
  put(key: string, value: Bytes): Promise<unknown>;
  get(key: string): Promise<R2ObjectBody | null>;
  delete(keys: string | string[]): Promise<void>;
}

export type BotCode = "CUSTOMER" | "TENANT" | "STAFF";
export const BOTS: readonly BotCode[] = ["CUSTOMER", "TENANT", "STAFF"];

// Secrets (wrangler secret put ...) and bindings. Nothing here is ever logged.
export interface Env {
  DB: D1Database;
  MEDIA: R2Bucket;
  OFFICE_PUBLIC_KEY: string;
  OFFICE_PULL_KEY: string;
  CUSTOMER_BOT_TOKEN?: string;
  TENANT_BOT_TOKEN?: string;
  STAFF_BOT_TOKEN?: string;
  CUSTOMER_WEBHOOK_SECRET?: string;
  TENANT_WEBHOOK_SECRET?: string;
  STAFF_WEBHOOK_SECRET?: string;
  TELEGRAM_API?: string; // tests only; production uses https://api.telegram.org
}

export interface MediaRef {
  fileId: string;
  fileUniqueId: string;
  contentType: string;
  width?: number;
  height?: number;
  duration?: number;
  size?: number;
}
