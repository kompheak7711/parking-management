// The Customer bot and the Staff bot answered by the relay (DL-213; DL-219: every message at
// once, app open or closed): the relay asks every Send an inquiry question, answers FAQ and
// Contact office, says "received" to a staff form, alerts the caretaker on shift for an urgent
// staff report, and tells the office what it did.

import assert from "node:assert/strict";
import { test } from "node:test";

import { handle } from "../src/index.ts";
import {
  moveMonths,
  propertyToday,
  typedDay,
  visitDays,
  type CustomerTexts,
} from "../src/offline_bots.ts";
import { signInForTests } from "../src/telegram.ts";
import { officeKeys, officeRequest, openSealed, testEnv } from "./fakes.ts";

// Wednesday 11 November 2026, 03:00 UTC (10:00 in Phnom Penh).
const NOW = Date.UTC(2026, 10, 11, 3, 0, 0) / 1000;
const keys = await officeKeys();
const CUSTOMER = 5151;
const STAFF = 6161;
const NEW_STAFF = 6262;
const AUTHORIZER = 9001;
const CARETAKER_ON = 9002;

function said(text: string, markup?: unknown, choices = false) {
  const one = { text, markup, ...(choices ? { choices: true } : {}) };
  return { km: { ...one, text: `km ${text}` }, en: one };
}

const BACK = { keyboard: [[{ text: "Back to menu" }]], resize_keyboard: true };

const CUSTOMER_TEXTS: CustomerTexts = {
  messages: {
    welcome: said("welcome"),
    menu: said("menu"),
    contact_phone: said("share your phone"),
    contact_ask: said("type your message"),
    contact_text_only: said("text only"),
    contact_saved: said("message saved"),
    faq_none: said("no questions"),
    faq_list: said("questions", BACK, true),
    faq_answer: said("{question} = {answer}", BACK, true),
    ask_how: said("how?"),
    ask_phone: said("phone?"),
    phone_again: said("phone again"),
    ask_email: said("email?"),
    email_again: said("email again"),
    ask_name: said("name?"),
    ask_type: said("type?", BACK, true),
    type_again: said("type again", BACK, true),
    ask_day: said("day?", BACK, true),
    day_again: said("day again", BACK, true),
    ask_part: said("part?"),
    ask_move: said("move?", BACK, true),
    ask_note: said("note?"),
    check: said("{name}|{phone}|{contact}|{type}|{visit}|{move}|{note}"),
    received: said("received, number later"),
  },
  buttons: {
    "button.khmer": ["ភាសាខ្មែរ"],
    "button.english": ["English"],
    "button.back_menu": ["Back to menu"],
    "button.contact": ["Contact office"],
    "button.faq": ["FAQ"],
    "button.inquiry": ["Send an inquiry"],
    "button.share_phone": ["Share my phone number"],
    "button.by_telegram": ["Telegram"],
    "button.by_email": ["Email"],
    "button.by_phone": ["Phone call"],
    "button.by_whatsapp": ["WhatsApp"],
    "button.morning": ["Morning"],
    "button.afternoon": ["Afternoon"],
    "button.skip": ["Skip"],
    "button.later": ["Later"],
  },
  words: {
    "button.by_telegram": { km: "តេឡេក្រាម", en: "Telegram" },
    "button.by_email": { km: "អ៊ីមែល", en: "Email" },
    "button.by_phone": { km: "ទូរស័ព្ទ", en: "Phone call" },
    "button.by_whatsapp": { km: "WhatsApp", en: "WhatsApp" },
    "button.morning": { km: "ព្រឹក", en: "Morning" },
    "button.afternoon": { km: "រសៀល", en: "Afternoon" },
    "button.later": { km: "ពេលក្រោយ", en: "Later" },
    "customer.no_day": { km: "មិនទាន់កំណត់", en: "No day yet" },
  },
  unit_types: [{ code: "STUDIO", name_en: "Studio", name_km: "ស្ទូឌីយោ" }],
  faq: [
    {
      number: 1,
      question_en: "Where are you?",
      question_km: "នៅឯណា?",
      answer_en: "Phnom Penh",
      answer_km: "ភ្នំពេញ",
    },
  ],
  weekdays: {
    en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    km: ["ច", "អ", "ព", "ព្រ", "សុ", "សៅ", "អា"],
  },
  months: {
    en: [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ],
    km: Array.from({ length: 12 }, (_, index) => `ខែ${index + 1}`),
  },
  utc_offset_minutes: 420,
  rules: {
    first_day: 2,
    last_day: 30,
    days_shown: 6,
    months_shown: 3,
    month_ahead_days: 14,
    max_name: 120,
    max_email: 120,
    max_note: 500,
    max_choices: 30,
    max_choice_chars: 60,
  },
};

const STAFF_TEXTS = {
  messages: {
    hello: said("hello {name}", {
      inline_keyboard: [[{ text: "Reports", web_app: { url: "x" } }]],
    }),
    ask_phone: said("share your phone to join"),
    waiting: said("request sent, wait for approval"),
    check: said("scan received"),
    form: said("form received"),
    urgent: said("urgent received"),
  },
  buttons: { "button.share_phone": ["Share my phone number"] },
  types: {
    "t-water": { name_kh: "ទឹក", always_urgent: false },
    "t-fire": { name_kh: "ភ្លើង", always_urgent: true },
  },
  places: { "p-lobby": "ផ្ទះធំ" },
  alert: {
    always: [AUTHORIZER],
    // Two covering shifts for one caretaker (Night and Morning overlap): still one alert.
    shifts: [
      [CARETAKER_ON, NOW - 3600, NOW + 3600],
      [CARETAKER_ON, NOW - 30000, NOW + 60],
    ],
  },
  staff_urgent: "🚨 {type} · {where}",
};

function telegramFake() {
  const sent: {
    bot: string;
    chat_id: number;
    text: string;
    reply_markup?: { keyboard?: { text: string }[][] };
  }[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const found = /\/bot(\d+):[^/]+\/sendMessage$/.exec(String(input));
    if (found) {
      const body = JSON.parse(String(init?.body));
      const bot =
        found[1] === "777777"
          ? "CUSTOMER"
          : found[1] === "654321"
            ? "STAFF"
            : "TENANT";
      sent.push({ bot, ...body });
      return Response.json({ ok: true, result: { message_id: sent.length } });
    }
    return new Response("missing", { status: 404 });
  }) as typeof fetch;
  return { sent, fetcher };
}

async function setUp() {
  const env = {
    ...testEnv(keys.publicPem),
    CUSTOMER_BOT_TOKEN: "777777:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
    CUSTOMER_WEBHOOK_SECRET: "customer-webhook-secret",
  };
  for (const [bot, texts] of [
    ["customer", CUSTOMER_TEXTS],
    ["staff", STAFF_TEXTS],
  ] as const) {
    const answer = await handle(
      await officeRequest("PUT", `/office/offline/${bot}`, NOW - 1000, {
        texts,
        links: {},
      }),
      env,
      () => NOW - 1000,
    );
    assert.equal(answer.status, 200);
  }
  return env;
}

let updateId = 0;

function message(user: number, fields: Record<string, unknown>) {
  updateId += 1;
  return {
    update_id: updateId,
    message: {
      message_id: updateId,
      from: { id: user, language_code: "en" },
      chat: { id: user, type: "private" },
      ...fields,
    },
  };
}

async function sendUpdate(
  env: Awaited<ReturnType<typeof setUp>>,
  bot: "customer" | "staff",
  update: unknown,
  fetcher: typeof fetch,
  now = NOW,
) {
  const secret =
    bot === "customer"
      ? env.CUSTOMER_WEBHOOK_SECRET
      : (env.STAFF_WEBHOOK_SECRET as string);
  const answer = await handle(
    new Request(`https://relay.test/telegram/${bot}`, {
      method: "POST",
      headers: {
        "x-telegram-bot-api-secret-token": secret,
        "content-type": "application/json",
      },
      body: JSON.stringify(update),
    }),
    env,
    () => now,
    fetcher,
  );
  assert.equal(answer.status, 200);
}

async function sealedItems(env: Awaited<ReturnType<typeof setUp>>) {
  const rows = env.DB.sqlite
    .prepare("SELECT id, sealed FROM items ORDER BY received_at, rowid")
    .all() as { id: string; sealed: string }[];
  const opened = [];
  for (const row of rows) {
    const bytes = await openSealed(
      keys.privateKey,
      Buffer.from(row.sealed, "base64"),
      row.id,
    );
    opened.push(JSON.parse(new TextDecoder().decode(bytes)));
  }
  return opened;
}

test("the Property's calendar: visit days skip Sunday, typed days and move-in months", () => {
  const today = propertyToday(CUSTOMER_TEXTS, NOW);
  const days = visitDays(CUSTOMER_TEXTS, today);
  // Wednesday 11/11: Friday 13/11 is the first visit day; Sunday 15/11 is skipped.
  assert.equal(
    new Date(days[0]! * 86400000).toISOString().slice(0, 10),
    "2026-11-13",
  );
  assert.equal(
    new Date(days[2]! * 86400000).toISOString().slice(0, 10),
    "2026-11-16",
  );
  assert.equal(typedDay(CUSTOMER_TEXTS, "16/11", today), days[2]);
  assert.equal(typedDay(CUSTOMER_TEXTS, "15/11", today), null); // a Sunday
  assert.equal(typedDay(CUSTOMER_TEXTS, "12/11", today), null); // tomorrow is too soon
  assert.equal(typedDay(CUSTOMER_TEXTS, "31/11", today), null);
  assert.deepEqual(moveMonths(CUSTOMER_TEXTS, today), [
    { year: 2026, month: 11 },
    { year: 2026, month: 12 },
    { year: 2027, month: 1 },
  ]);
  // 23:30 UTC is already the next day in Phnom Penh.
  assert.equal(
    propertyToday(CUSTOMER_TEXTS, Date.UTC(2026, 10, 11, 17, 30) / 1000),
    today + 1,
  );
});

test("a customer sends an inquiry at night: every question, then 'received', and the office gets the request", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  const say = (fields: Record<string, unknown>) =>
    sendUpdate(env, "customer", message(CUSTOMER, fields), fetcher);
  await say({ text: "/start" });
  await say({ text: "English" });
  await say({ text: "FAQ" });
  await say({ text: "1. Where are you?" });
  await say({ text: "Send an inquiry" });
  await say({ text: "Telegram" });
  await say({ text: "hello" }); // not the share button
  await say({
    contact: { user_id: CUSTOMER, phone_number: "+85512000111" },
  });
  await say({ text: "Sok Dara" });
  await say({ text: "Penthouse" }); // not a Unit Type
  await say({ text: "Studio" });
  await say({ text: "Fri 13/11" });
  await say({ text: "Morning" });
  await say({ text: "December 2026" });
  await say({ text: "Skip" });
  await say({ text: "Send an inquiry" });
  assert.deepEqual(
    sent.map((m) => m.text),
    [
      "km welcome",
      "menu",
      "questions",
      "Where are you? = Phnom Penh",
      "how?",
      "phone?",
      "phone again",
      "name?",
      "type?",
      "type again",
      "day?",
      "part?",
      "move?",
      "note?",
      "Sok Dara|+85512000111|Telegram|Studio|Fri 13/11, Morning|December 2026|-",
      "received, number later",
    ],
  );
  assert.deepEqual(
    sent[8]?.reply_markup?.keyboard?.map((row) => row[0]?.text),
    ["Studio", "Back to menu"],
  );
  assert.deepEqual(
    sent[10]?.reply_markup?.keyboard?.map((row) => row[0]?.text),
    [
      "Fri 13/11",
      "Sat 14/11",
      "Mon 16/11",
      "Tue 17/11",
      "Wed 18/11",
      "Thu 19/11",
      "Back to menu",
    ],
  );
  const items = await sealedItems(env);
  assert.equal(items.length, 16);
  assert.deepEqual(items[1].relay, {
    answered: true,
    step: "menu",
    language: "en",
  });
  assert.deepEqual(items.at(-1).relay, {
    answered: true,
    step: "menu",
    inquiry: {
      contact_by: "TELEGRAM",
      name: "Sok Dara",
      unit_type: "STUDIO",
      visit_on: "2026-11-13",
      visit_part: "MORNING",
      move_in: "2026-12",
      note: null,
    },
  });
  assert.equal(items.at(-2).relay.step, "ask.check");
  assert.equal(items.at(-2).relay.request.name, "Sok Dara");
  // The request is gone from the relay once sent.
  assert.equal(
    env.DB.sqlite.prepare("SELECT count(*) AS n FROM chat_requests").get()?.n,
    0,
  );
});

test("Contact office at night: the phone first, then the message, saved for the office", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  const say = (fields: Record<string, unknown>) =>
    sendUpdate(env, "customer", message(CUSTOMER, fields), fetcher);
  await say({ text: "ភាសាខ្មែរ" });
  await say({ text: "Contact office" });
  await say({
    contact: { user_id: CUSTOMER, phone_number: "+85512000111" },
  });
  await say({ text: "Is a studio free in December?" });
  assert.deepEqual(
    sent.map((m) => m.text),
    [
      "km menu",
      "km share your phone",
      "km type your message",
      "km message saved",
    ],
  );
  const items = await sealedItems(env);
  assert.equal(items.at(-1).relay.contact, true);
  assert.equal(items.at(-1).relay.step, "menu");
});

test("staff at night: a linked person gets Reports, a new person's join request is sent", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  env.DB.sqlite
    .prepare(
      "INSERT INTO access (bot, user_id, role, data) VALUES ('STAFF', ?, 'STAFF', ?)",
    )
    .run(STAFF, JSON.stringify({ name_km: "សុខ" }));
  await sendUpdate(env, "staff", message(STAFF, { text: "/start" }), fetcher);
  await sendUpdate(
    env,
    "staff",
    message(NEW_STAFF, { text: "/start" }),
    fetcher,
  );
  await sendUpdate(
    env,
    "staff",
    message(NEW_STAFF, {
      contact: { user_id: NEW_STAFF, phone_number: "+85512000222" },
    }),
    fetcher,
  );
  assert.deepEqual(
    sent.map((m) => [m.chat_id, m.text]),
    [
      [STAFF, "km hello សុខ"],
      [NEW_STAFF, "km share your phone to join"],
      [NEW_STAFF, "km request sent, wait for approval"],
    ],
  );
  const items = await sealedItems(env);
  assert.deepEqual(
    items.map((item) => item.relay),
    [
      { answered: true, step: "menu" },
      { answered: true, step: "menu" },
      { answered: true, step: "menu" },
    ],
  );
});

test("staff forms at night: 'received' at once, and an urgent report reaches the caretaker on shift", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  env.DB.sqlite
    .prepare(
      "INSERT INTO access (bot, user_id, role, data) VALUES ('STAFF', ?, 'STAFF', ?)",
    )
    .run(STAFF, JSON.stringify({ name_km: "សុខ" }));
  env.DB.sqlite
    .prepare(
      "INSERT INTO choices (bot, body, updated_at) VALUES ('STAFF', ?, 'x')",
    )
    .run(JSON.stringify({ units: [{ id: "u-1", number: "U302" }] }));
  const signIn = await signInForTests(env.STAFF_BOT_TOKEN as string, {
    auth_date: String(NOW - 30),
    user: JSON.stringify({ id: STAFF, language_code: "km" }),
  });
  const post = (form: Record<string, unknown>, now = NOW) =>
    handle(
      new Request("https://relay.test/form/staff", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ init_data: signIn, form, photos: [] }),
      }),
      env,
      () => now,
      fetcher,
    );
  assert.equal(
    (await post({ type: "CHECK", mode: "IN", qr: "q", location: {} })).status,
    200,
  );
  await post({ type: "METER", readings: [] });
  await post({
    type: "REPORT",
    kind: "UNIT",
    unit_id: "u-1",
    problem_type_id: "t-fire",
  });
  await post({
    type: "REPORT",
    kind: "BUILDING",
    problem_place_id: "p-lobby",
    floor: "2",
    problem_type_id: "t-water",
  });
  assert.deepEqual(
    sent.map((m) => [m.chat_id, m.text]),
    [
      [STAFF, "km scan received"],
      [STAFF, "km form received"],
      [AUTHORIZER, "🚨 ភ្លើង · U302"],
      [CARETAKER_ON, "🚨 ភ្លើង · U302"],
      [STAFF, "km urgent received"],
      [STAFF, "km form received"],
    ],
  );
  const items = await sealedItems(env);
  assert.deepEqual(
    items.map((item) => item.relay),
    [
      { answered: true, alerted: false },
      { answered: true, alerted: false },
      { answered: true, alerted: true },
      { answered: true, alerted: false },
    ],
  );
  // DL-219: with the office open (it pulled a moment ago), the relay still answers at once.
  sent.length = 0;
  await handle(
    await officeRequest("GET", "/office/items", NOW + 10),
    env,
    () => NOW + 10,
  );
  await post(
    { type: "REPORT", kind: "UNIT", unit_id: "u-1", problem_type_id: "t-fire" },
    NOW + 20,
  );
  await sendUpdate(
    env,
    "staff",
    message(STAFF, { text: "/start" }),
    fetcher,
    NOW + 20,
  );
  await sendUpdate(
    env,
    "customer",
    message(CUSTOMER, { text: "/start" }),
    fetcher,
    NOW + 20,
  );
  assert.deepEqual(
    sent.map((m) => m.chat_id),
    [AUTHORIZER, CARETAKER_ON, STAFF, STAFF, CUSTOMER],
  );
  assert.equal((await sealedItems(env)).at(-1).relay.answered, true);
});
