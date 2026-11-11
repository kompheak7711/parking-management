// The Tenant bot answered by the relay (DL-210, owner 07/11/2026: "I want tenant report 24/7";
// DL-219, owner 11/11/2026: "all telegram bot has to reply immediately even app open or close").
// The relay answers every Tenant bot message at once, app open or closed:
//   1. Start and language, and links a tenant to their Lease with the scrambled check codes or
//      the one-time QR codes the office sent;
//   2. opens the Problem report form (it already works without the office);
//   3. answers a sent report at once: "We got your report. Our office will check it.";
//   4. sends an urgent report to the caretaker on shift and the Authorizers on the Staff bot;
//   5. FAQ (the questions the Owner approved), My requests and Fixed or Not fixed, from what the
//      office sent for each linked person, and Contact office;
//   6. tells the office what it answered (inside the sealed item), so the app saves the same
//      steps when it collects the items (every 150 seconds), without answering twice.
// Everything the relay says comes from the office (texts, buttons, codes, each tenant's
// requests); nothing here decides money or keeps a record.

import { sha256Hex } from "./seal.ts";
import type { BotCode, Env } from "./types.ts";

export const CHAT_STEP_SECONDS = 30 * 60; // a link step left for 30 minutes starts again
export const LINK_TRIES = 5; // owner rule (2 Nov 2026): 5 wrong tries = 24 hours blocked
export const LINK_BLOCK_SECONDS = 24 * 60 * 60;
// The Start of a QR scan (DL-214): 40 lower-case hex letters made by the office's database.
const START_CODE = /^\/start\s+([0-9a-f]{40})$/;
const CODE_CHARS = 32;
// A FAQ button reads "3. Question...": the number before the dot names the question.
export const FAQ_NUMBER = /^\s*(\d{1,3})(?:[.)]|\s*$)/;

type Json = Record<string, unknown>;

export interface Said {
  text: string;
  markup?: unknown;
  // The keyboard starts with choices (FAQ questions, ...): the relay puts them above its rows.
  choices?: boolean;
}

export interface FaqEntry {
  number: number;
  question_en: string;
  question_km: string;
  answer_en: string;
  answer_km: string;
}

// One offline body per bot, as sent by the office (backend telegram_offline.py).
export interface OfflineTexts {
  messages: Record<string, Record<string, Said>>;
  buttons: Record<string, string[]>;
  types: Record<string, { name_kh: string; always_urgent: boolean }>;
  places: Record<string, string>;
  alert: { always: number[]; shifts: [number, number, number][] };
  staff_urgent: string;
  // DL-219: the FAQ the Owner approved for the Tenant bot.
  faq?: FaqEntry[];
}

export interface OfflineLinks {
  units: { unit: string; places: unknown }[];
  codes: Record<string, number>;
  // DL-214: the SHA-256 of each unused QR code -> [its Unit, the second it stops working].
  start_codes?: Record<string, [number, number]>;
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
  code?: { outcome: "LINKED" | "BAD" };
  // DL-219: Fixed or Not fixed, and the report the relay named (null: nothing to check).
  check?: { fixed: boolean; number: string | null };
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

export function message(
  texts: { messages: Record<string, Record<string, Said>> },
  name: string,
  language: string,
  details: Record<string, string> = {},
  choices: string[] = [],
  limits: { max_choices: number; max_choice_chars: number } = {
    max_choices: 30,
    max_choice_chars: 60,
  },
): Said | null {
  const found = texts.messages[name];
  const said = found?.[language] ?? found?.km;
  if (!said) {
    return null;
  }
  const filled = fill({ text: said.text, markup: said.markup }, details);
  if (said.choices) {
    const markup = object(said.markup) ?? {};
    const fixed = Array.isArray(markup.keyboard) ? markup.keyboard : [];
    const rows = choices
      .slice(0, limits.max_choices)
      .filter((choice) => choice.trim() !== "")
      .map((choice) => [{ text: choice.slice(0, limits.max_choice_chars) }]);
    filled.markup = { ...markup, keyboard: [...rows, ...fixed] };
  }
  return filled;
}

function say(
  texts: OfflineTexts,
  name: string,
  language: string,
  details: Record<string, string> = {},
  choices: string[] = [],
): Said | null {
  return message(texts, name, language, details, choices);
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

// One Tenant bot chat message (DL-219: every one, app open or closed): what to answer and what
// to tell the office. Only private chats; anything else is left for the office.
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
  const access = await env.DB.prepare(
    "SELECT data FROM access WHERE bot = 'TENANT' AND user_id = ?",
  )
    .bind(user)
    .first<{ data: string | null }>();
  const linked = access !== null;
  const out: Outgoing[] = [];
  const answer = async (
    name: string,
    next: Partial<Chat> & { step: string },
    facts: Omit<RelayFacts, "answered" | "step"> = {},
    details: Record<string, string> = {},
    choices: string[] = [],
  ): Promise<{ facts: RelayFacts; out: Outgoing[] }> => {
    const said = say(texts, name, language ?? "km", details, choices);
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
  const started = START_CODE.exec(typed);
  if (started) {
    const done = await codeTry(env, user, started[1] ?? "", now, answer);
    if (language === null) {
      // A new person also chooses the language after the QR links them.
      const welcome = say(texts, "welcome", "km");
      if (welcome) {
        done.out.push({ bot: "TENANT", chatId: user, said: welcome });
      }
      await saveChat(env, user, { language, step: "language" }, now);
      done.facts.step = "language";
    }
    return done;
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
  const person = personData(access?.data ?? null);
  const faq = texts.faq ?? [];
  if (tapped === "button.faq" || (step === "faq" && tapped === null && typed)) {
    if (faq.length === 0) {
      return answer("faq_none", { step: "menu" });
    }
    const km = (language ?? "km") === "km";
    const choices = faq.map(
      (entry) =>
        `${entry.number}. ${km ? entry.question_km : entry.question_en}`,
    );
    const asked = tapped === null ? FAQ_NUMBER.exec(typed) : null;
    const entry = asked
      ? faq.find((item) => item.number === Number(asked[1]))
      : undefined;
    if (entry) {
      return answer(
        "faq_answer",
        { step: "faq" },
        {},
        {
          question: km ? entry.question_km : entry.question_en,
          answer: km ? entry.answer_km : entry.answer_en,
        },
        choices,
      );
    }
    return answer("faq_list", { step: "faq" }, {}, {}, choices);
  }
  if (tapped === "button.problem") {
    return answer("report_kind", { step: "menu" });
  }
  if (tapped === "button.fixed" || tapped === "button.not_fixed") {
    // The newest repair marked done on the person's Lease, as the office sent it. The relay says
    // it once; the office closes or reopens the report when it collects the message.
    const fixed = tapped === "button.fixed";
    const number = typeof person.check === "string" ? person.check : null;
    if (number !== null) {
      await env.DB.prepare(
        "UPDATE access SET data = json_set(data, '$.check', NULL) " +
          "WHERE bot = 'TENANT' AND user_id = ? AND json_valid(data)",
      )
        .bind(user)
        .run();
    }
    return number === null
      ? answer("check_nothing", { step: "menu" }, { check: { fixed, number } })
      : answer(
          fixed ? "check_fixed" : "check_not_fixed",
          { step: "menu" },
          { check: { fixed, number } },
          { number },
        );
  }
  if (tapped === "button.my_requests") {
    const lines = object(person.requests)?.[language ?? "km"];
    return typeof lines === "string" && lines !== ""
      ? answer(
          "my_requests",
          { step: "menu" },
          {},
          { unit: String(person.unit ?? ""), list: lines },
        )
      : answer("my_none", { step: "menu" });
  }
  // Anything else a linked person types: the menu again, as the office answers.
  return answer("menu", { step: "menu" });
}

// What the office sent for one linked person (the access list): the Unit, the places, and since
// DL-219 My requests in both languages and the number of a repair waiting for Fixed or Not fixed.
function personData(data: string | null): Json {
  if (data === null) {
    return {};
  }
  try {
    return object(JSON.parse(data)) ?? {};
  } catch {
    return {};
  }
}

type Answer = (
  name: string,
  next: Partial<Chat> & { step: string },
  facts?: Omit<RelayFacts, "answered" | "step">,
  details?: Record<string, string>,
  choices?: string[],
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
  if (!links || !env.LINK_CHECK_KEY) {
    // Without the check list or its key the relay cannot tell: the office answers this one.
    await saveChat(env, user, { step: "menu" }, now);
    return { facts: { answered: false }, out: [] };
  }
  let found: { unit: string; places: unknown } | undefined;
  if (unitKey(unit) !== "") {
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

// A QR scan (DL-214): an unused, unexpired code the office sent links the person at once; the
// office links them again from the same code when it collects the message.
async function codeTry(
  env: Env,
  user: number,
  code: string,
  now: number,
  answer: Answer,
) {
  const hash = await sha256Hex(new TextEncoder().encode(code));
  const links = await offlineLinks(env);
  const entry = links?.start_codes?.[hash];
  const used = await env.DB.prepare(
    "SELECT user_id FROM start_codes_used WHERE code_hash = ?",
  )
    .bind(hash)
    .first<{ user_id: number }>();
  const found = entry && entry[1] > now ? entry : undefined;
  const unit = found ? links?.units[found[0]] : undefined;
  if (!unit || (used !== null && used.user_id !== user)) {
    return answer("code_bad", { step: "menu" }, { code: { outcome: "BAD" } });
  }
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO access (bot, user_id, role, data) VALUES ('TENANT', ?, 'TENANT', ?) " +
        "ON CONFLICT (bot, user_id) DO UPDATE SET role = excluded.role, data = excluded.data",
    ).bind(user, JSON.stringify({ places: unit.places, unit: unit.unit })),
    env.DB.prepare(
      "INSERT INTO start_codes_used (code_hash, user_id, used_at) VALUES (?, ?, ?) " +
        "ON CONFLICT (code_hash) DO NOTHING",
    ).bind(hash, user, now),
  ]);
  return answer(
    "linked",
    { step: "menu" },
    { code: { outcome: "LINKED" } },
    { unit: unit.unit },
  );
}

// A Problem report form (DL-210, DL-219): the answer to the tenant and, when it is
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
