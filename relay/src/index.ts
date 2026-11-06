// The CHETANA Telegram relay (bots plan 03/11/2026, "The relay"). A small Cloudflare Worker
// that is always on, even when the office power or internet is off. Its five jobs:
//   1. receive from Telegram (webhooks, checked with each bot's secret word);
//   2. check who it is (Mini App sign-ins, checked with the bot key and the access list), and
//      serve the Mini App form pages (the Tenant bot's Problem report);
//   3. seal every message and photo with the office's public key;
//   4. hand over to the office (signed pull, then delete after the office confirms);
//   5. (step 2) the urgent ping to the caretaker group.
// It never decides money, never stores the record, never reads the office database, and never
// answers in place of staff.

import { importOfficeKey, seal, sha256Hex, toBase64 } from "./seal.ts";
import {
  checkSignIn,
  downloadFile,
  MAX_FILE_BYTES,
  MAX_MEDIA_PER_ITEM,
  readUpdate,
} from "./telegram.ts";
import { tenantAppPage } from "./tenant_app.ts";
import { BOTS, type BotCode, type Bytes, type Env } from "./types.ts";

export const KEEP_DAYS = 7;
export const RATE_PER_MINUTE = 30;
export const OFFICE_CLOCK_SKEW_SECONDS = 300;
export const MAX_PERSON_DATA_CHARS = 8192;
export const MAX_CHOICES_CHARS = 65536;
const FORM_FILE_TYPES = [
  "image/jpeg",
  "audio/ogg",
  "audio/mp4",
  "audio/webm",
] as const;
const DEFAULT_API = "https://api.telegram.org";

type Clock = () => number;

function json(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function botFromPath(name: string | undefined): BotCode | undefined {
  const code = (name ?? "").toUpperCase();
  return (BOTS as readonly string[]).includes(code)
    ? (code as BotCode)
    : undefined;
}

function sameText(a: string, b: string): boolean {
  let difference = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    difference |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return difference === 0;
}

function hexToBytes(text: string): Bytes | undefined {
  if (!/^[0-9a-f]{64}$/.test(text)) {
    return undefined;
  }
  return Uint8Array.from(text.match(/../g) ?? [], (pair) => parseInt(pair, 16));
}

// The office's calls carry X-Office-Time and X-Office-Signature (see
// backend/src/property_rental/telegram_relay_client.py).
async function officeSigned(
  request: Request,
  body: Bytes,
  env: Env,
  now: number,
) {
  const key = hexToBytes(env.OFFICE_PULL_KEY ?? "");
  const moment = Number(request.headers.get("x-office-time"));
  const given = request.headers.get("x-office-signature") ?? "";
  if (!key || !Number.isSafeInteger(moment) || !/^[0-9a-f]{64}$/.test(given)) {
    return false;
  }
  if (Math.abs(now - moment) > OFFICE_CLOCK_SKEW_SECONDS) {
    return false;
  }
  const url = new URL(request.url);
  const message = `${moment}\n${request.method}\n${url.pathname}${url.search}\n${await sha256Hex(body)}`;
  const imported = await crypto.subtle.importKey(
    "raw",
    key,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const signature = hexToBytes(given);
  return signature !== undefined
    ? crypto.subtle.verify(
        "HMAC",
        imported,
        signature,
        new TextEncoder().encode(message),
      )
    : false;
}

async function overLimit(
  env: Env,
  userId: number,
  now: number,
): Promise<boolean> {
  const minute = Math.floor(now / 60);
  await env.DB.prepare(
    "INSERT INTO rate (user_id, minute, count) VALUES (?, ?, 1) " +
      "ON CONFLICT (user_id, minute) DO UPDATE SET count = count + 1",
  )
    .bind(userId, minute)
    .run();
  const row = await env.DB.prepare(
    "SELECT count FROM rate WHERE user_id = ? AND minute = ?",
  )
    .bind(userId, minute)
    .first<{ count: number }>();
  return (row?.count ?? 0) > RATE_PER_MINUTE;
}

interface SealedMedia {
  id: string;
  content_type: string;
  sha256: string;
  size: number;
  width?: number;
  height?: number;
  duration?: number;
  file_unique_id?: string;
}

async function keepMedia(
  env: Env,
  officeKey: CryptoKey,
  itemId: string,
  position: number,
  bytes: Bytes,
  described: Omit<SealedMedia, "id" | "sha256" | "size">,
): Promise<SealedMedia> {
  const id = crypto.randomUUID();
  await env.MEDIA.put(`m/${id}`, await seal(officeKey, bytes, id));
  await env.DB.prepare(
    "INSERT INTO media (id, item_id, position) VALUES (?, ?, ?)",
  )
    .bind(id, itemId, position)
    .run();
  return {
    id,
    sha256: await sha256Hex(bytes),
    size: bytes.length,
    ...described,
  };
}

async function keepItem(
  env: Env,
  officeKey: CryptoKey,
  itemId: string,
  bot: BotCode,
  kind: string,
  plain: Record<string, unknown>,
  now: number,
): Promise<void> {
  const sealed = await seal(
    officeKey,
    new TextEncoder().encode(JSON.stringify(plain)),
    itemId,
  );
  await env.DB.prepare(
    "INSERT INTO items (id, bot, kind, received_at, sealed) VALUES (?, ?, ?, ?, ?)",
  )
    .bind(
      itemId,
      bot,
      kind,
      new Date(now * 1000).toISOString(),
      toBase64(sealed),
    )
    .run();
}

async function webhook(
  request: Request,
  env: Env,
  bot: BotCode,
  now: number,
  fetcher: typeof fetch,
) {
  const secret = env[`${bot}_WEBHOOK_SECRET`];
  const token = env[`${bot}_BOT_TOKEN`];
  const given = request.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!secret || !token || !sameText(secret, given)) {
    return new Response("not found", { status: 404 });
  }
  let update: Record<string, unknown>;
  try {
    update = (await request.json()) as Record<string, unknown>;
  } catch {
    return new Response("ok");
  }
  const facts = readUpdate(update);
  if (facts.userId !== undefined && (await overLimit(env, facts.userId, now))) {
    return new Response("ok"); // more than 30 a minute: dropped quietly
  }
  const officeKey = await importOfficeKey(env.OFFICE_PUBLIC_KEY);
  const itemId = crypto.randomUUID();
  const media: SealedMedia[] = [];
  if (!facts.refused) {
    const api = env.TELEGRAM_API ?? DEFAULT_API;
    for (const [position, ref] of facts.media
      .slice(0, MAX_MEDIA_PER_ITEM)
      .entries()) {
      try {
        const bytes = await downloadFile(api, token, ref.fileId, fetcher);
        media.push(
          await keepMedia(env, officeKey, itemId, position, bytes, {
            content_type: ref.contentType,
            width: ref.width,
            height: ref.height,
            duration: ref.duration,
            file_unique_id: ref.fileUniqueId,
          }),
        );
      } catch {
        facts.refused = "file_not_fetched";
      }
    }
  }
  await keepItem(
    env,
    officeKey,
    itemId,
    bot,
    "update",
    {
      v: 1,
      update_id: facts.updateId,
      telegram_user_id: facts.userId,
      chat_id: facts.chatId,
      language_code: facts.languageCode,
      refused: facts.refused,
      payload: update,
      media,
    },
    now,
  );
  return new Response("ok");
}

function corsHeaders(request: Request): Record<string, string> {
  // The Mini App pages are on Cloudflare Pages; the sign-in, not the origin, proves who it is.
  const origin = request.headers.get("origin");
  return origin && /^https:\/\/[a-z0-9.-]+\.pages\.dev$/.test(origin)
    ? {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "POST",
        "access-control-allow-headers": "content-type",
        vary: "origin",
      }
    : {};
}

interface FormCaller {
  body: Record<string, unknown>;
  userId: number;
  languageCode?: string;
  role: string | null;
  data: string | null;
}

// Who sends a form: a Telegram sign-in under 24 hours old, signed with this bot's key, and for
// the Tenant and Staff bots a person on the access list the office sent.
async function formCaller(
  request: Request,
  env: Env,
  bot: BotCode,
  now: number,
  cors: Record<string, string>,
): Promise<FormCaller | Response> {
  const token = env[`${bot}_BOT_TOKEN`];
  if (!token) {
    return json({ ok: false, error: "not_set_up" }, 404, cors);
  }
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return json({ ok: false, error: "not_json" }, 400, cors);
  }
  if (typeof body !== "object" || body === null) {
    return json({ ok: false, error: "not_json" }, 400, cors);
  }
  const signIn =
    typeof body.init_data === "string"
      ? await checkSignIn(body.init_data, token, now)
      : undefined;
  if (!signIn) {
    return json({ ok: false, error: "sign_in_refused" }, 401, cors);
  }
  const access = await env.DB.prepare(
    "SELECT role, data FROM access WHERE bot = ? AND user_id = ?",
  )
    .bind(bot, signIn.userId)
    .first<{ role: string; data: string | null }>();
  // Customer bot forms (an inquiry) are open to anyone; Tenant and Staff forms need a link.
  if (bot !== "CUSTOMER" && !access) {
    return json({ ok: false, error: "not_allowed" }, 403, cors);
  }
  if (await overLimit(env, signIn.userId, now)) {
    return json({ ok: false, error: "too_many" }, 429, cors);
  }
  return {
    body,
    userId: signIn.userId,
    languageCode: signIn.languageCode,
    role: access?.role ?? null,
    data: access?.data ?? null,
  };
}

// What the form shows: the bot's choices and this person's own data (for a tenant, the places
// in their Unit).
async function formStart(
  request: Request,
  env: Env,
  bot: BotCode,
  now: number,
) {
  const cors = corsHeaders(request);
  const caller = await formCaller(request, env, bot, now, cors);
  if (caller instanceof Response) {
    return caller;
  }
  const choices = await env.DB.prepare("SELECT body FROM choices WHERE bot = ?")
    .bind(bot)
    .first<{ body: string }>();
  return json(
    {
      ok: true,
      choices: choices ? JSON.parse(choices.body) : null,
      mine: caller.data ? JSON.parse(caller.data) : null,
    },
    200,
    cors,
  );
}

async function form(request: Request, env: Env, bot: BotCode, now: number) {
  const cors = corsHeaders(request);
  const caller = await formCaller(request, env, bot, now, cors);
  if (caller instanceof Response) {
    return caller;
  }
  const { body } = caller;
  const fields = body.form;
  const photos = Array.isArray(body.photos) ? body.photos : [];
  if (
    typeof fields !== "object" ||
    fields === null ||
    photos.length > MAX_MEDIA_PER_ITEM
  ) {
    return json({ ok: false, error: "form_not_complete" }, 400, cors);
  }
  const officeKey = await importOfficeKey(env.OFFICE_PUBLIC_KEY);
  const itemId = crypto.randomUUID();
  const media: SealedMedia[] = [];
  for (const [position, photo] of photos.entries()) {
    const entry = photo as Record<string, unknown>;
    const type = entry?.content_type;
    if (
      typeof entry?.data !== "string" ||
      !(FORM_FILE_TYPES as readonly string[]).includes(String(type))
    ) {
      return json({ ok: false, error: "file_not_allowed" }, 400, cors);
    }
    let bytes: Bytes;
    try {
      bytes = Uint8Array.from(atob(entry.data), (c) => c.charCodeAt(0));
    } catch {
      return json({ ok: false, error: "file_not_allowed" }, 400, cors);
    }
    if (bytes.length === 0 || bytes.length > MAX_FILE_BYTES) {
      return json({ ok: false, error: "file_too_big" }, 413, cors);
    }
    // A voice note says how long it is (the form stops recording at 1 minute).
    const duration = entry.duration;
    media.push(
      await keepMedia(env, officeKey, itemId, position, bytes, {
        content_type: String(type),
        duration:
          Number.isSafeInteger(duration) &&
          (duration as number) >= 0 &&
          (duration as number) <= 600
            ? (duration as number)
            : undefined,
      }),
    );
  }
  await keepItem(
    env,
    officeKey,
    itemId,
    bot,
    "form",
    {
      v: 1,
      telegram_user_id: caller.userId,
      chat_id: caller.userId,
      language_code: caller.languageCode,
      payload: { form: fields, role: caller.role },
      media,
    },
    now,
  );
  return json({ ok: true }, 200, cors);
}

async function office(request: Request, env: Env, now: number, path: string[]) {
  const body = new Uint8Array(await request.arrayBuffer());
  if (!(await officeSigned(request, body, env, now))) {
    return json({ error: "signature" }, 401);
  }
  const [what, which] = path;
  if (what === "items" && request.method === "GET") {
    const limit = Math.max(
      1,
      Math.min(
        100,
        Number(new URL(request.url).searchParams.get("limit")) || 50,
      ),
    );
    const rows = await env.DB.prepare(
      "SELECT id, bot, kind, received_at, sealed FROM items ORDER BY received_at, id LIMIT ?",
    )
      .bind(limit)
      .all<{
        id: string;
        bot: string;
        kind: string;
        received_at: string;
        sealed: string;
      }>();
    const items = [];
    for (const row of rows.results) {
      const media = await env.DB.prepare(
        "SELECT id FROM media WHERE item_id = ? ORDER BY position",
      )
        .bind(row.id)
        .all<{ id: string }>();
      items.push({ ...row, media: media.results.map((m) => m.id) });
    }
    const waiting = await env.DB.prepare(
      "SELECT count(*) AS waiting, min(received_at) AS oldest FROM items",
    ).first<{ waiting: number; oldest: string | null }>();
    const since = new Date((now - KEEP_DAYS * 86400) * 1000)
      .toISOString()
      .slice(0, 10);
    const dropped = await env.DB.prepare(
      "SELECT coalesce(sum(count), 0) AS dropped FROM dropped WHERE day >= ?",
    )
      .bind(since)
      .first<{ dropped: number }>();
    return json({
      items,
      waiting: waiting?.waiting ?? 0,
      oldest_at: waiting?.oldest ?? null,
      dropped: dropped?.dropped ?? 0,
    });
  }
  if (
    what === "media" &&
    request.method === "GET" &&
    which &&
    /^[A-Za-z0-9_-]{8,64}$/.test(which)
  ) {
    const object = await env.MEDIA.get(`m/${which}`);
    if (!object) {
      return json({ error: "not_found" }, 404);
    }
    return new Response(await object.arrayBuffer(), {
      headers: { "content-type": "application/octet-stream" },
    });
  }
  if (what === "confirm" && request.method === "POST") {
    let ids: unknown;
    try {
      ids = (JSON.parse(new TextDecoder().decode(body)) as { ids?: unknown })
        .ids;
    } catch {
      return json({ error: "not_json" }, 400);
    }
    if (
      !Array.isArray(ids) ||
      ids.length > 100 ||
      !ids.every((id) => typeof id === "string")
    ) {
      return json({ error: "ids" }, 400);
    }
    let deleted = 0;
    for (const id of ids as string[]) {
      deleted += await removeItem(env, id);
    }
    return json({ deleted });
  }
  if (what === "access" && request.method === "PUT") {
    const bot = botFromPath(which);
    let users: unknown;
    try {
      users = (
        JSON.parse(new TextDecoder().decode(body)) as { users?: unknown }
      ).users;
    } catch {
      return json({ error: "not_json" }, 400);
    }
    const personData = (user: { data?: unknown }) =>
      user.data === undefined || user.data === null
        ? null
        : JSON.stringify(user.data);
    const valid =
      bot !== undefined &&
      Array.isArray(users) &&
      users.every(
        (user) =>
          typeof user === "object" &&
          user !== null &&
          Number.isSafeInteger((user as { id?: unknown }).id) &&
          typeof (user as { role?: unknown }).role === "string" &&
          /^[A-Z_]{2,20}$/.test((user as { role: string }).role) &&
          ((user as { data?: unknown }).data === undefined ||
            (user as { data?: unknown }).data === null ||
            (typeof (user as { data?: unknown }).data === "object" &&
              (personData(user as { data?: unknown }) ?? "").length <=
                MAX_PERSON_DATA_CHARS)),
      );
    if (!valid) {
      return json({ error: "access_list" }, 400);
    }
    // The whole list is replaced at once: a link ended in the app stops here within a minute.
    const statements = [
      env.DB.prepare("DELETE FROM access WHERE bot = ?").bind(bot),
    ];
    for (const user of users as {
      id: number;
      role: string;
      data?: unknown;
    }[]) {
      statements.push(
        env.DB.prepare(
          "INSERT INTO access (bot, user_id, role, data) VALUES (?, ?, ?, ?)",
        ).bind(bot, user.id, user.role, personData(user)),
      );
    }
    await env.DB.batch(statements);
    return json({ count: (users as unknown[]).length });
  }
  if (what === "choices" && request.method === "PUT") {
    const bot = botFromPath(which);
    let choices: unknown;
    try {
      choices = (
        JSON.parse(new TextDecoder().decode(body)) as { choices?: unknown }
      ).choices;
    } catch {
      return json({ error: "not_json" }, 400);
    }
    const text = JSON.stringify(choices ?? null);
    if (
      bot === undefined ||
      typeof choices !== "object" ||
      choices === null ||
      Array.isArray(choices) ||
      text.length > MAX_CHOICES_CHARS
    ) {
      return json({ error: "choices" }, 400);
    }
    await env.DB.prepare(
      "INSERT INTO choices (bot, body, updated_at) VALUES (?, ?, ?) " +
        "ON CONFLICT (bot) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
    )
      .bind(bot, text, new Date(now * 1000).toISOString())
      .run();
    return json({ saved: true });
  }
  return json({ error: "not_found" }, 404);
}

async function removeItem(env: Env, id: string): Promise<number> {
  const media = await env.DB.prepare("SELECT id FROM media WHERE item_id = ?")
    .bind(id)
    .all<{ id: string }>();
  if (media.results.length > 0) {
    await env.MEDIA.delete(media.results.map((m) => `m/${m.id}`));
  }
  await env.DB.prepare("DELETE FROM media WHERE item_id = ?").bind(id).run();
  const before = await env.DB.prepare(
    "SELECT count(*) AS n FROM items WHERE id = ?",
  )
    .bind(id)
    .first<{ n: number }>();
  await env.DB.prepare("DELETE FROM items WHERE id = ?").bind(id).run();
  return before?.n ?? 0;
}

// Every hour: anything not pulled in 7 days is removed and counted for the health page.
export async function cleanUp(env: Env, now: number): Promise<number> {
  const limit = new Date((now - KEEP_DAYS * 86400) * 1000).toISOString();
  const old = await env.DB.prepare("SELECT id FROM items WHERE received_at < ?")
    .bind(limit)
    .all<{ id: string }>();
  for (const row of old.results) {
    await removeItem(env, row.id);
  }
  if (old.results.length > 0) {
    await env.DB.prepare(
      "INSERT INTO dropped (day, count) VALUES (?, ?) " +
        "ON CONFLICT (day) DO UPDATE SET count = count + excluded.count",
    )
      .bind(new Date(now * 1000).toISOString().slice(0, 10), old.results.length)
      .run();
  }
  await env.DB.prepare("DELETE FROM rate WHERE minute < ?")
    .bind(Math.floor(now / 60) - 60)
    .run();
  return old.results.length;
}

export async function handle(
  request: Request,
  env: Env,
  clock: Clock = () => Math.floor(Date.now() / 1000),
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname.split("/").filter(Boolean);
  const now = clock();
  if (path[0] === "telegram" && request.method === "POST") {
    const bot = botFromPath(path[1]);
    return bot
      ? webhook(request, env, bot, now, fetcher)
      : new Response("not found", { status: 404 });
  }
  if (path[0] === "form") {
    const bot = botFromPath(path[1]);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }
    if (!bot || request.method !== "POST" || path.length > 3) {
      return new Response("not found", { status: 404 });
    }
    if (path[2] === "start") {
      return formStart(request, env, bot, now);
    }
    return path.length === 2
      ? form(request, env, bot, now)
      : new Response("not found", { status: 404 });
  }
  // The Mini App pages (the Tenant bot's Problem report form). They hold no data: the page asks
  // /form/<bot>/start with the person's Telegram sign-in for what to show.
  if (
    path[0] === "app" &&
    path[1] === "tenant" &&
    path.length === 2 &&
    request.method === "GET"
  ) {
    return new Response(tenantAppPage(), {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "content-security-policy":
          "default-src 'none'; script-src 'self' 'unsafe-inline' https://telegram.org; " +
          "style-src 'unsafe-inline'; img-src blob: data:; media-src blob:; " +
          "connect-src 'self'; base-uri 'none'; form-action 'none'",
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
      },
    });
  }
  if (path[0] === "office") {
    return office(request, env, now, path.slice(1));
  }
  return new Response("not found", { status: 404 });
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handle(request, env);
  },
  async scheduled(_event: unknown, env: Env): Promise<void> {
    await cleanUp(env, Math.floor(Date.now() / 1000));
  },
};
