// The Customer bot and the Staff bot answered by the relay (DL-213, owner 11/11/2026: "let's
// make CHETANA Residence and CHETANA Staff work without rely on Property rental management app
// open"; DL-219: "all telegram bot has to reply immediately even app open or close"). As for the
// Tenant bot (offline.ts), the relay answers every message at once with the texts and buttons
// the office sent, and tells the office what it answered (inside the sealed item) so the app
// saves the same steps when it collects the items (every 150 seconds).
//
// Customer bot: Start and language, FAQ (the questions the Owner approved), Contact office and
// every Send an inquiry question, as telegram_customer_bot.py asks them. The relay never gives a
// request number (only the app does): it says "We received your request" and the app sends the
// number when it opens.
//
// Staff bot: a linked person gets the Reports button (the forms already work without the
// office); a new person who shares their phone hears "your request was sent" (the Owner or a
// Manager approves in the app). A form gets "received" at once: the check-in or check-out keeps
// the time the relay received it, and the app sends the result when it opens. An urgent Problem
// report goes to the caretaker on shift and the Authorizers at once, as for a tenant's report.

import {
  CHAT_STEP_SECONDS,
  FAQ_NUMBER,
  fill,
  message,
  object,
  saveChat,
  tappedButton,
  type Chat,
  type FaqEntry,
  type Outgoing,
  type Said,
} from "./offline.ts";
import type { Env } from "./types.ts";

type Json = Record<string, unknown>;

export interface CustomerTexts {
  messages: Record<string, Record<string, Said>>;
  buttons: Record<string, string[]>;
  words: Record<string, Record<string, string>>;
  unit_types: { code: string; name_en: string; name_km: string }[];
  faq: FaqEntry[];
  weekdays: Record<string, string[]>;
  months: Record<string, string[]>;
  utc_offset_minutes: number;
  rules: {
    first_day: number;
    last_day: number;
    days_shown: number;
    months_shown: number;
    month_ahead_days: number;
    max_name: number;
    max_email: number;
    max_note: number;
    max_choices: number;
    max_choice_chars: number;
  };
}

export interface StaffTexts {
  messages: Record<string, Record<string, Said>>;
  buttons: Record<string, string[]>;
  types: Record<string, { name_kh: string; always_urgent: boolean }>;
  places: Record<string, string>;
  alert: { always: number[]; shifts: [number, number, number][] };
  staff_urgent: string;
}

// What the relay did for a Customer or Staff bot chat, sealed inside the item for the office.
export interface BotFacts {
  answered: boolean;
  step?: string;
  language?: string;
  request?: Json;
  contact?: boolean;
  inquiry?: Json;
  alerted?: boolean;
}

export async function offlineBody<T>(env: Env, bot: string): Promise<T | null> {
  const row = await env.DB.prepare("SELECT body FROM offline WHERE bot = ?")
    .bind(bot)
    .first<{ body: string }>();
  return row ? (JSON.parse(row.body) as T) : null;
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const TYPED_DAY = /(\d{1,2})\s*\/\s*(\d{1,2})/;
const HOW: Record<string, string> = {
  "button.by_telegram": "TELEGRAM",
  "button.by_email": "EMAIL",
  "button.by_phone": "PHONE",
  "button.by_whatsapp": "WHATSAPP",
};
const PART: Record<string, string> = {
  "button.morning": "MORNING",
  "button.afternoon": "AFTERNOON",
};

function privateMessage(update: Json): { message: Json; user: number } | null {
  const found = object(update.message);
  const sender = object(found?.from);
  const chat = object(found?.chat);
  const user = sender?.id;
  if (
    !found ||
    typeof user !== "number" ||
    chat?.type !== "private" ||
    chat.id !== user
  ) {
    return null;
  }
  return { message: found, user };
}

function ownContact(message: Json, user: number): Json | null {
  const contact = object(message.contact);
  return contact && contact.user_id === user ? contact : null;
}

async function savedChat(
  env: Env,
  bot: string,
  user: number,
): Promise<Chat | null> {
  return env.DB.prepare(
    "SELECT language, step, name, phone, updated_at FROM chats WHERE bot = ? AND user_id = ?",
  )
    .bind(bot, user)
    .first<Chat>();
}

// ---- The Property's calendar (telegram_customer_bot.py: _visit_days, _months).

interface Day {
  year: number;
  month: number; // 1 to 12
  day: number;
  weekday: number; // Monday 0 to Sunday 6, as Python's weekday()
}

function dayOf(epochDays: number): Day {
  const at = new Date(epochDays * 86400000);
  return {
    year: at.getUTCFullYear(),
    month: at.getUTCMonth() + 1,
    day: at.getUTCDate(),
    weekday: (at.getUTCDay() + 6) % 7,
  };
}

function epochDay(year: number, month: number, day: number): number | null {
  const at = Date.UTC(year, month - 1, day);
  const back = new Date(at);
  return back.getUTCFullYear() === year &&
    back.getUTCMonth() === month - 1 &&
    back.getUTCDate() === day
    ? at / 86400000
    : null;
}

function iso(day: Day): string {
  return `${day.year}-${String(day.month).padStart(2, "0")}-${String(day.day).padStart(2, "0")}`;
}

export function propertyToday(texts: CustomerTexts, now: number): number {
  return Math.floor((now + texts.utc_offset_minutes * 60) / 86400);
}

export function visitDays(texts: CustomerTexts, today: number): number[] {
  const days: number[] = [];
  for (
    let ahead = texts.rules.first_day;
    ahead <= texts.rules.last_day;
    ahead++
  ) {
    if (dayOf(today + ahead).weekday !== 6) {
      days.push(today + ahead);
    }
  }
  return days;
}

function dayLabel(texts: CustomerTexts, day: number, language: string): string {
  const found = dayOf(day);
  const names = texts.weekdays[language === "km" ? "km" : "en"] ?? [];
  return `${names[found.weekday] ?? ""} ${String(found.day).padStart(2, "0")}/${String(found.month).padStart(2, "0")}`;
}

export function typedDay(
  texts: CustomerTexts,
  typed: string,
  today: number,
): number | null {
  const found = TYPED_DAY.exec(typed);
  if (!found) {
    return null;
  }
  const day = Number(found[1]);
  const month = Number(found[2]);
  const allowed = visitDays(texts, today);
  const year = dayOf(today).year;
  for (const candidate of [year, year + 1]) {
    const chosen = epochDay(candidate, month, day);
    if (chosen === null) {
      return null;
    }
    if (allowed.includes(chosen)) {
      return chosen;
    }
  }
  return null;
}

export function moveMonths(
  texts: CustomerTexts,
  today: number,
): { year: number; month: number }[] {
  const first = dayOf(today + texts.rules.month_ahead_days);
  const months: { year: number; month: number }[] = [];
  let year = first.year;
  let month = first.month;
  for (let index = 0; index < texts.rules.months_shown; index++) {
    months.push({ year, month });
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return months;
}

function monthLabel(
  texts: CustomerTexts,
  value: { year: number; month: number },
  language: string,
): string {
  const names = texts.months[language === "km" ? "km" : "en"] ?? [];
  return `${names[value.month - 1] ?? ""} ${value.year}`;
}

function typeName(
  item: CustomerTexts["unit_types"][number],
  language: string,
): string {
  return (language === "km" ? item.name_km : item.name_en) || item.name_en;
}

// ---- The Customer bot.

export async function customerAnswer(
  env: Env,
  texts: CustomerTexts,
  update: Json,
  now: number,
): Promise<{ facts: BotFacts; out: Outgoing[] }> {
  const found = privateMessage(update);
  if (!found) {
    return { facts: { answered: false }, out: [] };
  }
  const { message: incoming, user } = found;
  const typed = typeof incoming.text === "string" ? incoming.text.trim() : "";
  if (["ping", "/ping"].includes(typed.toLowerCase())) {
    return { facts: { answered: false }, out: [] }; // the office answers the setup test
  }
  const tapped = typed ? tappedButton(texts, typed) : null;
  const saved = await savedChat(env, "CUSTOMER", user);
  const fresh = saved !== null && now - saved.updated_at <= CHAT_STEP_SECONDS;
  let language = saved?.language ?? null;
  let phone = fresh ? (saved?.phone ?? null) : null;
  const stored = await env.DB.prepare(
    "SELECT data, updated_at FROM chat_requests WHERE bot = 'CUSTOMER' AND user_id = ?",
  )
    .bind(user)
    .first<{ data: string; updated_at: number }>();
  let request: Json =
    stored && now - stored.updated_at <= CHAT_STEP_SECONDS
      ? ((object(JSON.parse(stored.data)) ?? {}) as Json)
      : {};
  const today = propertyToday(texts, now);
  const limits = texts.rules;
  const out: Outgoing[] = [];
  const answer = async (
    name: string,
    step: string,
    facts: Omit<BotFacts, "answered" | "step" | "request"> = {},
    details: Record<string, string> = {},
    choices: string[] = [],
  ): Promise<{ facts: BotFacts; out: Outgoing[] }> => {
    const said = message(
      texts,
      name,
      language ?? "km",
      details,
      choices,
      limits,
    );
    if (!said) {
      return { facts: { answered: false }, out: [] };
    }
    out.push({ bot: "CUSTOMER", chatId: user, said });
    await saveChat(env, user, { language, step, phone }, now, "CUSTOMER");
    if (step.startsWith("ask.")) {
      await env.DB.prepare(
        "INSERT INTO chat_requests (bot, user_id, data, updated_at) VALUES ('CUSTOMER', ?, ?, ?) " +
          "ON CONFLICT (bot, user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
      )
        .bind(user, JSON.stringify(request), now)
        .run();
    } else {
      await env.DB.prepare(
        "DELETE FROM chat_requests WHERE bot = 'CUSTOMER' AND user_id = ?",
      )
        .bind(user)
        .run();
    }
    return {
      facts: {
        answered: true,
        step,
        ...(step.startsWith("ask.") ? { request } : {}),
        ...facts,
      },
      out,
    };
  };
  const faqChoices = () =>
    texts.faq.map(
      (entry) =>
        `${entry.number}. ${language === "km" ? entry.question_km : entry.question_en}`,
    );
  const typeChoices = () =>
    texts.unit_types.map((item) => typeName(item, language ?? "km"));
  const dayChoices = () =>
    visitDays(texts, today)
      .slice(0, limits.days_shown)
      .map((day) => dayLabel(texts, day, language ?? "km"));
  const monthChoices = () =>
    moveMonths(texts, today).map((value) =>
      monthLabel(texts, value, language ?? "km"),
    );

  if (
    typed.startsWith("/start") ||
    (language === null &&
      tapped !== "button.khmer" &&
      tapped !== "button.english")
  ) {
    return answer("welcome", "language");
  }
  if (tapped === "button.khmer" || tapped === "button.english") {
    language = tapped === "button.khmer" ? "km" : "en";
    return answer("menu", "menu", { language });
  }
  const step = fresh ? (saved?.step ?? "menu") : "menu";
  const contact = ownContact(incoming, user);
  if (contact) {
    phone = String(contact.phone_number ?? "").slice(0, 20) || phone;
  }
  if (tapped === "button.back_menu") {
    return answer("menu", "menu");
  }
  if (tapped === "button.contact") {
    return phone
      ? answer("contact_ask", "contact")
      : answer("contact_phone", "contact.phone");
  }
  if (step === "contact.phone") {
    return contact
      ? answer("contact_ask", "contact")
      : answer("phone_again", "contact.phone");
  }
  if (step === "contact" && tapped === null) {
    return typed
      ? answer("contact_saved", "menu", { contact: true })
      : answer("contact_text_only", "contact");
  }
  if (tapped === "button.faq" || (step === "faq" && tapped === null && typed)) {
    if (texts.faq.length === 0) {
      return answer("faq_none", "menu");
    }
    const asked = tapped === null ? FAQ_NUMBER.exec(typed) : null;
    const entry = asked
      ? texts.faq.find((item) => item.number === Number(asked[1]))
      : undefined;
    if (entry) {
      return answer(
        "faq_answer",
        "faq",
        {},
        {
          question: language === "km" ? entry.question_km : entry.question_en,
          answer: language === "km" ? entry.answer_km : entry.answer_en,
        },
        faqChoices(),
      );
    }
    return answer("faq_list", "faq", {}, {}, faqChoices());
  }
  if (tapped === "button.inquiry" && step !== "ask.check") {
    request = {};
    return answer("ask_how", "ask.how");
  }
  if (!step.startsWith("ask.")) {
    return answer("menu", "menu");
  }
  const plain = tapped === null ? typed : "";
  const afterPhone = () =>
    request.contact_by === "EMAIL"
      ? answer("ask_email", "ask.email")
      : answer("ask_name", "ask.name");
  if (step === "ask.how") {
    const how = tapped ? HOW[tapped] : undefined;
    if (!how) {
      return answer("ask_how", "ask.how");
    }
    request.contact_by = how;
    return phone ? afterPhone() : answer("ask_phone", "ask.phone");
  }
  if (step === "ask.phone") {
    return contact ? afterPhone() : answer("phone_again", "ask.phone");
  }
  if (step === "ask.email") {
    if (plain.length > limits.max_email || !EMAIL.test(plain)) {
      return answer("email_again", "ask.email");
    }
    request.email = plain;
    return answer("ask_name", "ask.name");
  }
  if (step === "ask.name") {
    if (!plain) {
      return answer("ask_name", "ask.name");
    }
    request.name = plain.slice(0, limits.max_name).trim();
    return answer("ask_type", "ask.type", {}, {}, typeChoices());
  }
  if (step === "ask.type") {
    const chosen = plain
      ? texts.unit_types.find(
          (item) => plain === item.name_en || plain === item.name_km,
        )
      : undefined;
    if (!chosen) {
      return answer("type_again", "ask.type", {}, {}, typeChoices());
    }
    request.unit_type = chosen.code;
    return answer("ask_day", "ask.day", {}, {}, dayChoices());
  }
  if (step === "ask.day") {
    if (tapped === "button.skip") {
      request.visit_on = null;
      request.visit_part = null;
      return answer("ask_move", "ask.move", {}, {}, monthChoices());
    }
    const chosen = typedDay(texts, plain, today);
    if (chosen === null) {
      return answer("day_again", "ask.day", {}, {}, dayChoices());
    }
    request.visit_on = iso(dayOf(chosen));
    return answer("ask_part", "ask.part");
  }
  if (step === "ask.part") {
    const part = tapped ? PART[tapped] : undefined;
    if (!part) {
      return answer("ask_part", "ask.part");
    }
    request.visit_part = part;
    return answer("ask_move", "ask.move", {}, {}, monthChoices());
  }
  if (step === "ask.move") {
    if (tapped === "button.later") {
      request.move_in = "LATER";
    } else {
      const chosen = moveMonths(texts, today).find(
        (value) =>
          plain === monthLabel(texts, value, "en") ||
          plain === monthLabel(texts, value, "km"),
      );
      if (!chosen) {
        return answer("ask_move", "ask.move", {}, {}, monthChoices());
      }
      request.move_in = `${chosen.year}-${String(chosen.month).padStart(2, "0")}`;
    }
    return answer("ask_note", "ask.note");
  }
  if (step === "ask.note") {
    if (tapped === "button.skip") {
      request.note = null;
    } else if (plain) {
      request.note = plain.slice(0, limits.max_note).trim();
    } else {
      return answer("ask_note", "ask.note");
    }
    return answer(
      "check",
      "ask.check",
      {},
      summary(texts, request, phone, language ?? "km"),
    );
  }
  const needed = ["contact_by", "name", "unit_type", "move_in"];
  if (step === "ask.check" && tapped === "button.inquiry") {
    if (needed.some((field) => !request[field])) {
      request = {};
      return answer("ask_how", "ask.how");
    }
    const sent = request;
    request = {};
    return answer("received", "menu", { inquiry: sent });
  }
  return answer(
    "check",
    "ask.check",
    {},
    summary(texts, request, phone, language ?? "km"),
  );
}

function summary(
  texts: CustomerTexts,
  request: Json,
  phone: string | null,
  language: string,
): Record<string, string> {
  const word = (code: string) =>
    texts.words[code]?.[language] ?? texts.words[code]?.km ?? "";
  const howCode = Object.entries(HOW).find(
    ([, value]) => value === request.contact_by,
  )?.[0];
  let contact = howCode ? word(howCode) : "";
  if (typeof request.email === "string" && request.email) {
    contact = `${contact} (${request.email})`;
  }
  const type = texts.unit_types.find((item) => item.code === request.unit_type);
  let visit = word("customer.no_day");
  if (typeof request.visit_on === "string") {
    const [year, month, day] = request.visit_on.split("-").map(Number);
    const chosen = epochDay(year ?? 0, month ?? 0, day ?? 0);
    if (chosen !== null) {
      visit = dayLabel(texts, chosen, language);
      const partCode = Object.entries(PART).find(
        ([, value]) => value === request.visit_part,
      )?.[0];
      if (partCode) {
        visit = `${visit}, ${word(partCode)}`;
      }
    }
  }
  let move = word("button.later");
  if (typeof request.move_in === "string" && request.move_in !== "LATER") {
    const [year, month] = request.move_in.split("-").map(Number);
    move = monthLabel(texts, { year: year ?? 0, month: month ?? 1 }, language);
  }
  return {
    name: String(request.name ?? ""),
    phone: phone ?? "",
    contact,
    type: type ? typeName(type, language) : "",
    visit,
    move,
    note: typeof request.note === "string" && request.note ? request.note : "-",
  };
}

// ---- The Staff bot.

export async function staffAnswer(
  env: Env,
  texts: StaffTexts,
  update: Json,
): Promise<{ facts: BotFacts; out: Outgoing[] }> {
  const found = privateMessage(update);
  if (!found) {
    return { facts: { answered: false }, out: [] };
  }
  const { message: incoming, user } = found;
  const typed = typeof incoming.text === "string" ? incoming.text.trim() : "";
  if (["ping", "/ping"].includes(typed.toLowerCase())) {
    return { facts: { answered: false }, out: [] };
  }
  const access = await env.DB.prepare(
    "SELECT data FROM access WHERE bot = 'STAFF' AND user_id = ?",
  )
    .bind(user)
    .first<{ data: string | null }>();
  let said: Said | null;
  if (access) {
    const data = object(access.data ? JSON.parse(access.data) : null);
    const name = String(data?.name_km ?? data?.name_en ?? "").trim();
    said = message(texts, "hello", "km", { name });
  } else if (ownContact(incoming, user)) {
    said = message(texts, "waiting", "km");
  } else {
    said = message(texts, "ask_phone", "km");
  }
  return said
    ? {
        facts: { answered: true, step: "menu" },
        out: [{ bot: "STAFF", chatId: user, said }],
      }
    : { facts: { answered: false }, out: [] };
}

// A Staff form (DL-213, DL-219): "received" to the person and, for an urgent
// Problem report, the alert to the caretaker on shift and the Authorizers.
export function staffFormAnswers(
  texts: StaffTexts,
  user: number,
  form: Json,
  choices: Json | null,
  now: number,
): { person: Outgoing | null; alerts: Outgoing[] } {
  const type = texts.types[String(form.problem_type_id ?? "")];
  const urgent = form.type === "REPORT" && type?.always_urgent === true;
  const name =
    form.type === "CHECK" || form.type === "CARD"
      ? "check"
      : urgent
        ? "urgent"
        : "form";
  const said = message(texts, name, "km");
  const person = said ? { bot: "STAFF" as const, chatId: user, said } : null;
  if (!urgent || !texts.staff_urgent) {
    return { person, alerts: [] };
  }
  let where = "";
  if (form.kind === "UNIT") {
    const units = Array.isArray(choices?.units) ? choices.units : [];
    const unit = units
      .map((item) => object(item))
      .find((item) => item?.id === form.unit_id);
    where = String(unit?.number ?? "");
  } else {
    where = [texts.places[String(form.problem_place_id ?? "")], form.floor]
      .filter((part) => typeof part === "string" && part !== "")
      .join(" · ");
  }
  const people = new Set<number>(texts.alert.always);
  for (const [someone, starts, ends] of texts.alert.shifts) {
    if (now >= starts && now < ends) {
      people.add(someone);
    }
  }
  people.delete(user);
  const text = fill(
    { text: texts.staff_urgent },
    { type: type?.name_kh ?? "", where },
  );
  return {
    person,
    alerts: [...people].map((someone) => ({
      bot: "STAFF" as const,
      chatId: someone,
      said: text,
    })),
  };
}
