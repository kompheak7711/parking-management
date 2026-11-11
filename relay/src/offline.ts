// The Tenant bot while the office is away (DL-210, owner 07/11/2026: "I want tenant report 24/7"
// and "I don't want to open application 24/7"). When the office has not pulled for a while, the
// relay answers the Tenant bot itself:
//   1. links a tenant to their Lease with the scrambled check codes the office sent;
//   2. opens the Problem report form (it already works without the office);
//   3. answers a sent report at once: "We got your report. Our office will check it.";
//   4. sends an urgent report to the caretaker on shift and the Authorizers on the Staff bot;
//   5. tells the office what it answered (inside the sealed item), so the app saves the same
//      steps when it opens, without answering twice.
// Everything the relay says comes from the office (texts, buttons, codes); nothing here decides
// money or keeps a record. Other questions (My requests, FAQ, Fixed or Not fixed) get "our office
// is closed now" and the office answers them when it opens.

import type { BotCode, Env } from "./types.ts";

export const OFFICE_AWAY_SECONDS = 150; // the office pulls every 10 s (Mac) or 60 s (server)
export const CHAT_STEP_SECONDS = 30 * 60; // a link step left for 30 minutes starts again
export const LINK_TRIES = 5; // owner rule (2 Nov 2026): 5 wrong tries = 24 hours blocked
export const LINK_BLOCK_SECONDS = 24 * 60 * 60;
const CODE_CHARS = 32;

type Json = Record<string, unknown>;

export interface Said {
  text: string;
  markup?: unknown;
}

// One offline body per bot, as sent by the office (backend telegram_offline.py).
export interface OfflineTexts {
  messages: Record<string, Record<string, Said>>;
  buttons: Record<string, string[]>;
  types: Record<string, { name_kh: string; always_urgent: boolean }>;
  places: Record<string, string>;
  alert: { always: number[]; shifts: [number, number, number][] };
  staff_urgent: string;
}

export interface OfflineLinks {
  units: { unit: string; places: unknown }[];
  codes: Record<string, number>;
}

// What the relay did, sealed inside the item for the office.
export interface RelayFacts {
  answered: boolean;
  step?: string;
  language?: string;
  name?: string;
  link?: {
    outcome: "LINKED" | "NO_MATCH" | "BLOCKED";
    name: string;
    unit: string;
  };
  contact?: boolean;
  alerted?: boolean;
}

export interface Outgoing {
  bot: BotCode;
  chatId: number;
  said: Said;
}

// ---- The office's matching rules, as in migration 20270520_282 (app.phone_e164,
// app.tenant_name_words, app.tenant_unit_key) and backend telegram_phone.py.

export function phoneE164(text: string | undefined | null): string | null {
  const value = (text ?? "").trim();
  if (value === "") {
    return null;
  }
  const plus = value.startsWith("+");
  const digits = (plus ? value.slice(1) : value).replace(/[\s().-]/g, "");
  if (!/^[0-9]+$/.test(digits)) {
    return null;
  }
  let result: string;
  if (plus) {
    result = `+${digits}`;
  } else if (digits.startsWith("00")) {
    result = `+${digits.slice(2)}`;
  } else if (digits.startsWith("0")) {
    result = `+855${digits.slice(1)}`;
  } else {
    result = `+${digits}`;
  }
  if (result.startsWith("+8550")) {
    result = `+855${result.slice(5)}`;
  }
  return /^\+[1-9][0-9]{6,14}$/.test(result) ? result : null;
}

export function nameWords(name: string): string[] {
  return name
    .toLowerCase()
    .replace(/[\p{P}\p{S}\p{N}\s]+/gu, " ")
    .trim()
    .split(" ")
    .filter((word) => word !== "");
}

export function unitKey(unit: string): string {
  return unit
    .replace(/\s+/g, "")
    .toUpperCase()
    .replace(/^(UNIT|ROOM|NO\.?|#|បន្ទប់)/u, "")
    .replace(/^U(?=[0-9])/u, "");
}

// The two forms of a typed name the office compares: the words in any order, and the words
// written together (the office also tries the Lease name backwards, so it sends that form too).
export function typedNameForms(name: string): string[] {
  const words = nameWords(name);
  if (words.length === 0) {
    return [];
  }
  return [`s:${[...words].sort().join(" ")}`, `c:${words.join("")}`];
}

export async function linkCode(
  keyHex: string,
  phone: string,
  unit: string,
  nameForm: string,
): Promise<string | null> {
  if (!/^[0-9a-f]{64}$/.test(keyHex)) {
    return null;
  }
  const key = await crypto.subtle.importKey(
    "raw",
    Uint8Array.from(keyHex.match(/../g) ?? [], (pair) => parseInt(pair, 16)),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = new Uint8Array(
    await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(`${phone}\n${unitKey(unit)}\n${nameForm}`),
    ),
  );
  return Array.from(signed, (byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, CODE_CHARS);
}

// ---- When the office was last seen.

export async function noteOfficePull(env: Env, now: number): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO office_seen (what, at) VALUES ('pull', ?) " +
      "ON CONFLICT (what) DO UPDATE SET at = excluded.at",
  )
    .bind(now)
    .run();
}

export async function officeAway(env: Env, now: number): Promise<boolean> {
  const row = await env.DB.prepare(
    "SELECT at FROM office_seen WHERE what = 'pull'",
  ).first<{ at: number }>();
  return row === null || now - row.at > OFFICE_AWAY_SECONDS;
}

export async function offlineTexts(
  env: Env,
  bot: BotCode,
): Promise<OfflineTexts | null> {
  const row = await env.DB.prepare("SELECT body FROM offline WHERE bot = ?")
    .bind(bot)
    .first<{ body: string }>();
  return row ? (JSON.parse(row.body) as OfflineTexts) : null;
}

async function offlineLinks(env: Env): Promise<OfflineLinks | null> {
  const row = await env.DB.prepare(
    "SELECT body FROM offline WHERE bot = 'TENANT:LINKS'",
  ).first<{ body: string }>();
  return row ? (JSON.parse(row.body) as OfflineLinks) : null;
}

export function object(value: unknown): Json | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : undefined;
}

export function fill(said: Said, details: Record<string, string>): Said {
  return {
    ...said,
    text: said.text.replace(/\{([a-z_]+)\}/g, (whole, name: string) =>
      name in details ? (details[name] ?? "") : whole,
    ),
  };
}

function say(
  texts: OfflineTexts,
  name: string,
  language: string,
  details: Record<string, string> = {},
): Said | null {
  const message = texts.messages[name];
  const said = message?.[language] ?? message?.km;
  return said ? fill(said, details) : null;
}

export function tappedButton(
  texts: Pick<OfflineTexts, "buttons">,
  typed: string,
): string | null {
  for (const [code, labels] of Object.entries(texts.buttons)) {
    if (labels.includes(typed)) {
      return code;
    }
  }
  return null;
}

export interface Chat {
  language: string | null;
  step: string | null;
  name: string | null;
  phone: string | null;
  updated_at: number;
}

export async function saveChat(
  env: Env,
  user: number,
  chat: Partial<Chat>,
  now: number,
  bot: BotCode = "TENANT",
): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO chats (bot, user_id, language, step, name, phone, updated_at) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (bot, user_id) DO UPDATE SET " +
      "language = COALESCE(excluded.language, chats.language), step = excluded.step, " +
      "name = excluded.name, phone = excluded.phone, updated_at = excluded.updated_at",
  )
    .bind(
      bot,
      user,
      chat.language ?? null,
      chat.step ?? null,
      chat.name ?? null,
      chat.phone ?? null,
      now,
    )
    .run();
}

// The relay remembers the language a person picked, even while the office answers (one write
// for each language tap), so it can answer them in their language later.
export async function noteLanguage(
  env: Env,
  texts: Pick<OfflineTexts, "buttons"> | null,
  update: Json,
  now: number,
  bot: BotCode = "TENANT",
): Promise<void> {
  const message = object(update.message);
  const user = object(message?.from)?.id;
  const typed = typeof message?.text === "string" ? message.text.trim() : "";
  if (!texts || typeof user !== "number" || typed === "") {
    return;
  }
  const tapped = tappedButton(texts, typed);
  const language =
    tapped === "button.khmer"
      ? "km"
      : tapped === "button.english"
        ? "en"
        : null;
  if (language) {
    await env.DB.prepare(
      "INSERT INTO chats (bot, user_id, language, updated_at) VALUES (?, ?, ?, ?) " +
        "ON CONFLICT (bot, user_id) DO UPDATE SET language = excluded.language",
    )
      .bind(bot, user, language, now)
      .run();
  }
}

async function failedTries(env: Env, user: number, now: number) {
  const row = await env.DB.prepare(
    "SELECT count(*) AS n FROM link_tries WHERE user_id = ? AND at > ?",
  )
    .bind(user, now - LINK_BLOCK_SECONDS)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

// One Tenant bot chat message while the office is away: what to answer and what to tell the
// office. Only private chats; anything else is left for the office.
export async function tenantAnswer(
  env: Env,
  texts: OfflineTexts,
  update: Json,
  now: number,
): Promise<{ facts: RelayFacts; out: Outgoing[] }> {
  const message = object(update.message);
  const sender = object(message?.from);
  const chat = object(message?.chat);
  const user = sender?.id;
  if (
    !message ||
    typeof user !== "number" ||
    chat?.type !== "private" ||
    chat.id !== user
  ) {
    return { facts: { answered: false }, out: [] };
  }
  const typed = typeof message.text === "string" ? message.text.trim() : "";
  if (["ping", "/ping"].includes(typed.toLowerCase())) {
    return { facts: { answered: false }, out: [] }; // the office answers the setup test
  }
  const tapped = typed ? tappedButton(texts, typed) : null;
  const saved = await env.DB.prepare(
    "SELECT language, step, name, phone, updated_at FROM chats WHERE bot = 'TENANT' AND user_id = ?",
  )
    .bind(user)
    .first<Chat>();
  const fresh = saved !== null && now - saved.updated_at <= CHAT_STEP_SECONDS;
  const step = fresh ? saved.step : null;
  let language = saved?.language ?? null;
  const linked =
    (await env.DB.prepare(
      "SELECT 1 AS yes FROM access WHERE bot = 'TENANT' AND user_id = ?",
    )
      .bind(user)
      .first()) !== null;
  const out: Outgoing[] = [];
  const answer = async (
    name: string,
    next: Partial<Chat> & { step: string },
    facts: Omit<RelayFacts, "answered" | "step"> = {},
    details: Record<string, string> = {},
  ): Promise<{ facts: RelayFacts; out: Outgoing[] }> => {
    const said = say(texts, name, language ?? "km", details);
    if (!said) {
      return { facts: { answered: false }, out: [] };
    }
    out.push({ bot: "TENANT", chatId: user, said });
    await saveChat(env, user, { language, ...next }, now);
    return {
      facts: { answered: true, step: next.step, ...facts },
      out,
    };
  };

  if (tapped === "button.khmer" || tapped === "button.english") {
    language = tapped === "button.khmer" ? "km" : "en";
    return answer(linked ? "menu" : "hello", { step: "menu" }, { language });
  }
  if (typed.startsWith("/start") || language === null) {
    return answer("welcome", { step: "language" });
  }
  if (tapped === "button.link") {
    if ((await failedTries(env, user, now)) >= LINK_TRIES) {
      return answer("blocked", { step: "menu" });
    }
    return answer("ask_phone", { step: "link.phone" });
  }
  const contact = object(message.contact);
  if (step === "link.phone" || (contact && !linked)) {
    const phone =
      contact && contact.user_id === user
        ? phoneE164(String(contact.phone_number ?? ""))
        : null;
    return phone
      ? answer("ask_name", { step: "link.name", phone })
      : answer("ask_phone_again", { step: "link.phone" });
  }
  if (step === "link.name" && typed && !tapped && saved?.phone) {
    const name = typed.slice(0, 120);
    return answer(
      "ask_unit",
      { step: "link.unit", name, phone: saved.phone },
      { name },
    );
  }
  if (step === "link.unit" && typed && !tapped && saved?.phone && saved.name) {
    return linkTry(
      env,
      texts,
      user,
      saved.phone,
      saved.name,
      typed.slice(0, 20),
      now,
      answer,
    );
  }
  if (tapped === "button.contact") {
    return answer("contact_ask", { step: "contact" });
  }
  if (step === "contact" && !tapped) {
    if (!typed) {
      return answer("contact_text_only", { step: "contact" });
    }
    return answer(
      linked ? "contact_saved_linked" : "contact_saved",
      { step: "menu" },
      { contact: true },
    );
  }
  if (!linked) {
    return answer("link_first", { step: "menu" });
  }
  if (tapped === "button.back_menu") {
    return answer("menu", { step: "menu" });
  }
  if (tapped === "button.problem") {
    return answer("report_kind", { step: "menu" });
  }
  // FAQ, My requests, Fixed or Not fixed, or a typed message: the office answers when it opens.
  const said = say(texts, "office_away", language ?? "km");
  return {
    facts: { answered: false },
    out: said ? [{ bot: "TENANT", chatId: user, said }] : [],
  };
}

type Answer = (
  name: string,
  next: Partial<Chat> & { step: string },
  facts?: Omit<RelayFacts, "answered" | "step">,
  details?: Record<string, string>,
) => Promise<{ facts: RelayFacts; out: Outgoing[] }>;

async function linkTry(
  env: Env,
  texts: OfflineTexts,
  user: number,
  phone: string,
  name: string,
  unit: string,
  now: number,
  answer: Answer,
) {
  const tries = await failedTries(env, user, now);
  if (tries >= LINK_TRIES) {
    return answer(
      "blocked",
      { step: "menu" },
      { link: { outcome: "BLOCKED", name, unit } },
    );
  }
  const links = await offlineLinks(env);
  let found: { unit: string; places: unknown } | undefined;
  if (links && env.LINK_CHECK_KEY && unitKey(unit) !== "") {
    for (const form of typedNameForms(name)) {
      const code = await linkCode(env.LINK_CHECK_KEY, phone, unit, form);
      const index = code === null ? undefined : links.codes[code];
      if (index !== undefined) {
        found = links.units[index];
        break;
      }
    }
  }
  if (found) {
    // The person may send the Problem report form at once; the office's next list replaces it.
    await env.DB.prepare(
      "INSERT INTO access (bot, user_id, role, data) VALUES ('TENANT', ?, 'TENANT', ?) " +
        "ON CONFLICT (bot, user_id) DO UPDATE SET role = excluded.role, data = excluded.data",
    )
      .bind(user, JSON.stringify({ places: found.places, unit: found.unit }))
      .run();
    return answer(
      "linked",
      { step: "menu" },
      { link: { outcome: "LINKED", name, unit } },
      { unit: found.unit },
    );
  }
  await env.DB.prepare("INSERT INTO link_tries (user_id, at) VALUES (?, ?)")
    .bind(user, now)
    .run();
  const left = Math.max(0, LINK_TRIES - tries - 1);
  return left === 0
    ? answer(
        "blocked",
        { step: "menu" },
        { link: { outcome: "NO_MATCH", name, unit } },
      )
    : answer(
        "no_match",
        { step: "menu" },
        { link: { outcome: "NO_MATCH", name, unit } },
        { tries_left: String(left) },
      );
}

// A Problem report form sent while the office is away: the answer to the tenant and, when it is
// urgent, the alert to the caretaker on shift and the Authorizers.
export function formAnswers(
  texts: OfflineTexts,
  user: number,
  language: string,
  form: Json,
  mine: Json | null,
  now: number,
): { tenant: Outgoing | null; alerts: Outgoing[] } {
  const type = texts.types[String(form.problem_type_id ?? "")];
  const urgent = form.urgent === true || type?.always_urgent === true;
  const said = say(
    texts,
    urgent ? "report_sent_urgent" : "report_sent",
    language,
  );
  const tenant = said ? { bot: "TENANT" as const, chatId: user, said } : null;
  if (!urgent || !texts.staff_urgent) {
    return { tenant, alerts: [] };
  }
  const where =
    form.kind === "BUILDING"
      ? [texts.places[String(form.problem_place_id ?? "")], form.floor]
          .filter((part) => typeof part === "string" && part !== "")
          .join(" · ")
      : String(mine?.unit ?? "");
  const people = new Set<number>(texts.alert.always);
  for (const [person, starts, ends] of texts.alert.shifts) {
    if (now >= starts && now < ends) {
      people.add(person);
    }
  }
  people.delete(user);
  const text = fill(
    { text: texts.staff_urgent },
    { type: type?.name_kh ?? "", where },
  );
  return {
    tenant,
    alerts: [...people].map((person) => ({
      bot: "STAFF" as const,
      chatId: person,
      said: text,
    })),
  };
}

// Telegram's sendMessage with the bot's key; true when Telegram took it.
export async function send(
  env: Env,
  message: Outgoing,
  fetcher: typeof fetch,
): Promise<boolean> {
  const token = env[`${message.bot}_BOT_TOKEN`];
  if (!token) {
    return false;
  }
  const api = env.TELEGRAM_API ?? "https://api.telegram.org";
  try {
    const answer = await fetcher(`${api}/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: message.chatId,
        text: message.said.text,
        ...(message.said.markup ? { reply_markup: message.said.markup } : {}),
      }),
    });
    return answer.ok;
  } catch {
    return false;
  }
}
