// The Tenant bot while the office is away (DL-210): the relay links a tenant with the scrambled
// check codes, opens the Problem report form, answers a sent report at once, alerts the caretaker
// on shift for an urgent one, and tells the office what it said. While the office pulls, the
// relay answers nothing.

import assert from "node:assert/strict";
import { test } from "node:test";

import { handle } from "../src/index.ts";
import {
  linkCode,
  OFFICE_AWAY_SECONDS,
  phoneE164,
  typedNameForms,
  unitKey,
} from "../src/offline.ts";
import { signInForTests } from "../src/telegram.ts";
import { officeKeys, officeRequest, openSealed, testEnv } from "./fakes.ts";

const NOW = 1_793_000_000;
const LINK_KEY = "ab".repeat(32);
const keys = await officeKeys();
const TENANT = 4242;
const AUTHORIZER = 9001;
const CARETAKER_ON = 9002;
const CARETAKER_OFF = 9003;

function said(text: string, markup?: unknown) {
  return { km: { text: `km ${text}`, markup }, en: { text, markup } };
}

const TEXTS = {
  messages: {
    welcome: said("welcome"),
    hello: said("hello", { keyboard: [[{ text: "Link my Lease" }]] }),
    menu: said("menu"),
    ask_phone: said("share your phone", {
      keyboard: [[{ text: "Share", request_contact: true }]],
    }),
    ask_phone_again: said("share again"),
    ask_name: said("your name?"),
    ask_unit: said("your Unit?"),
    linked: said("linked to Unit {unit}"),
    no_match: said("no match, {tries_left} tries left"),
    blocked: said("blocked"),
    link_first: said("link first"),
    contact_ask: said("type your message"),
    contact_text_only: said("text only"),
    contact_saved: said("saved"),
    contact_saved_linked: said("saved (linked)"),
    report_kind: said("what kind?", {
      inline_keyboard: [
        [
          {
            text: "Unit Problem",
            web_app: { url: "https://relay.test/app/tenant?form=unit" },
          },
        ],
      ],
    }),
    office_away: said("office closed"),
    report_sent: said("We got your report. Our office will check it."),
    report_sent_urgent: said("We got your urgent report."),
  },
  buttons: {
    "button.khmer": ["ភាសាខ្មែរ"],
    "button.english": ["English"],
    "button.link": ["Link my Lease"],
    "button.problem": ["Problem report"],
    "button.contact": ["Contact office"],
    "button.faq": ["FAQ"],
    "button.back_menu": ["Back to menu"],
  },
  types: {
    "t-water": { name_kh: "ទឹក", always_urgent: false },
    "t-fire": { name_kh: "ភ្លើង", always_urgent: true },
  },
  places: { "p-lobby": "ផ្ទះធំ" },
  alert: {
    always: [AUTHORIZER],
    shifts: [
      [CARETAKER_ON, NOW - 3600, NOW + 3600],
      [CARETAKER_OFF, NOW + 3600, NOW + 7200],
    ],
  },
  staff_urgent: "🚨 {type} · {where}",
};

async function links() {
  const codes: Record<string, number> = {};
  for (const form of ["s:dara kim", "c:kimdara", "c:darakim"]) {
    const code = await linkCode(LINK_KEY, "+85512345678", "305", form);
    codes[code as string] = 0;
  }
  return {
    units: [
      {
        unit: "305",
        places: [{ item_id: "i-1", number: 1, name_en: "Bedroom" }],
      },
    ],
    codes,
  };
}

function telegramFake() {
  const sent: {
    bot: string;
    chat_id: number;
    text: string;
    reply_markup?: unknown;
  }[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const found = /\/bot(\d+):[^/]+\/sendMessage$/.exec(url);
    if (found) {
      const body = JSON.parse(String(init?.body));
      sent.push({ bot: found[1] === "123456" ? "TENANT" : "STAFF", ...body });
      return Response.json({ ok: true, result: { message_id: sent.length } });
    }
    return new Response("missing", { status: 404 });
  }) as typeof fetch;
  return { sent, fetcher };
}

async function setUp() {
  const env = { ...testEnv(keys.publicPem), LINK_CHECK_KEY: LINK_KEY };
  const answer = await handle(
    await officeRequest("PUT", "/office/offline/tenant", NOW - 1000, {
      texts: TEXTS,
      links: await links(),
    }),
    env,
    () => NOW - 1000,
  );
  assert.equal(answer.status, 200);
  return env;
}

function message(update: number, fields: Record<string, unknown>) {
  return {
    update_id: update,
    message: {
      message_id: update,
      from: { id: TENANT, language_code: "en" },
      chat: { id: TENANT, type: "private" },
      ...fields,
    },
  };
}

async function sendUpdate(
  env: ReturnType<typeof testEnv>,
  update: unknown,
  fetcher: typeof fetch,
  now = NOW,
) {
  return handle(
    new Request("https://relay.test/telegram/tenant", {
      method: "POST",
      headers: {
        "x-telegram-bot-api-secret-token": env.TENANT_WEBHOOK_SECRET as string,
        "content-type": "application/json",
      },
      body: JSON.stringify(update),
    }),
    env,
    () => now,
    fetcher,
  );
}

async function sealedItems(env: ReturnType<typeof testEnv>) {
  const rows = env.DB.sqlite
    .prepare("SELECT id, kind, sealed FROM items ORDER BY received_at, rowid")
    .all() as { id: string; kind: string; sealed: string }[];
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

test("the scrambled code is the office's (backend tests/test_telegram_offline.py)", async () => {
  assert.equal(
    await linkCode(LINK_KEY, "+85512345678", "Unit 305", "s:dara kim"),
    "fdfb978fb36198ac88c66beaa0b94a1d",
  );
  assert.equal(await linkCode("short", "+85512345678", "305", "s:x"), null);
});

test("phone numbers, Units and names are compared as the office does", () => {
  assert.equal(phoneE164("012 345 678"), "+85512345678");
  assert.equal(phoneE164("+855 12 345 678"), "+85512345678");
  assert.equal(phoneE164("85512345678"), "+85512345678");
  assert.equal(phoneE164("+855012345678"), "+85512345678");
  assert.equal(phoneE164("0085512345678"), "+85512345678");
  assert.equal(phoneE164("abc"), null);
  assert.equal(unitKey("Unit 305"), "305");
  assert.equal(unitKey(" room305 "), "305");
  assert.equal(unitKey("បន្ទប់ 305"), "305");
  // DL-212: the owner's Units are "U302"; a tenant types "302".
  assert.equal(unitKey("U302"), "302");
  assert.equal(unitKey("room u302"), "302");
  assert.equal(unitKey("UNIT 302"), "302");
  assert.equal(unitKey("UB12"), "UB12");
  assert.deepEqual(typedNameForms("KIM  Dara"), ["s:dara kim", "c:kimdara"]);
  assert.deepEqual(typedNameForms("DaraKim"), ["s:darakim", "c:darakim"]);
  assert.deepEqual(typedNameForms("1234"), []);
});

test("while the office pulls, the relay answers nothing and only notes the language", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  const pull = await handle(
    await officeRequest("GET", "/office/items?limit=50", NOW - 10),
    env,
    () => NOW - 10,
  );
  assert.equal(pull.status, 200);
  await sendUpdate(env, message(1, { text: "English" }), fetcher);
  await sendUpdate(env, message(2, { text: "/start" }), fetcher);
  assert.equal(sent.length, 0);
  const items = await sealedItems(env);
  assert.equal(items.length, 2);
  assert.equal(items[0].relay, undefined);
  const chat = env.DB.sqlite
    .prepare("SELECT language FROM chats WHERE user_id = ?")
    .get(TENANT) as { language: string };
  assert.equal(chat.language, "en");
});

test("the office away: a tenant links at night with phone, name and Unit, then opens the form", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  const steps: [unknown, string][] = [
    [message(1, { text: "/start" }), "km welcome"],
    [message(2, { text: "English" }), "hello"],
    [message(3, { text: "Link my Lease" }), "share your phone"],
    [
      message(4, {
        contact: { phone_number: "85512345678", user_id: TENANT },
      }),
      "your name?",
    ],
    [message(5, { text: "kim dara" }), "your Unit?"],
    [message(6, { text: "Unit 305" }), "linked to Unit 305"],
    [message(7, { text: "Problem report" }), "what kind?"],
    [message(8, { text: "FAQ" }), "office closed"],
  ];
  for (const [update, expected] of steps) {
    assert.equal((await sendUpdate(env, update, fetcher)).status, 200);
    assert.equal(sent.at(-1)?.text, expected);
  }
  assert.ok(JSON.stringify(sent[2]?.reply_markup).includes("request_contact"));
  const access = env.DB.sqlite
    .prepare(
      "SELECT role, data FROM access WHERE bot = 'TENANT' AND user_id = ?",
    )
    .get(TENANT) as { role: string; data: string };
  assert.equal(access.role, "TENANT");
  assert.equal(JSON.parse(access.data).unit, "305");
  const items = await sealedItems(env);
  assert.deepEqual(
    items.map((item) => item.relay?.step ?? null),
    [
      "language",
      "menu",
      "link.phone",
      "link.name",
      "link.unit",
      "menu",
      "menu",
      null,
    ],
  );
  assert.equal(items[1].relay.language, "en");
  assert.equal(items[4].relay.name, "kim dara");
  assert.deepEqual(items[5].relay.link, {
    outcome: "LINKED",
    name: "kim dara",
    unit: "Unit 305",
  });
  assert.equal(items[7].relay.answered, false);
  // The typed name and phone are gone once the link step is over.
  const chat = env.DB.sqlite
    .prepare("SELECT name, phone FROM chats WHERE user_id = ?")
    .get(TENANT) as { name: string | null; phone: string | null };
  assert.deepEqual({ ...chat }, { name: null, phone: null });
});

test("a forwarded contact is not the person's own phone, and 5 wrong tries block the person", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  await sendUpdate(env, message(1, { text: "English" }), fetcher);
  await sendUpdate(env, message(2, { text: "Link my Lease" }), fetcher);
  await sendUpdate(
    env,
    message(3, { contact: { phone_number: "85512345678", user_id: 1 } }),
    fetcher,
  );
  assert.equal(sent.at(-1)?.text, "share again");
  let update = 4;
  for (let left = 4; left >= 0; left -= 1) {
    await sendUpdate(
      env,
      message(update++, { text: "Link my Lease" }),
      fetcher,
    );
    await sendUpdate(
      env,
      message(update++, {
        contact: { phone_number: "85512345678", user_id: TENANT },
      }),
      fetcher,
    );
    await sendUpdate(env, message(update++, { text: "Kim Dara" }), fetcher);
    await sendUpdate(env, message(update++, { text: "999" }), fetcher);
    assert.equal(
      sent.at(-1)?.text,
      left === 0 ? "blocked" : `no match, ${left} tries left`,
    );
  }
  await sendUpdate(env, message(update++, { text: "Link my Lease" }), fetcher);
  assert.equal(sent.at(-1)?.text, "blocked");
  const items = await sealedItems(env);
  assert.equal(items.at(-2).relay.link.outcome, "NO_MATCH");
});

test("an urgent report at night: the caretaker on shift and the Authorizer get the alert, the tenant an answer", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  env.DB.sqlite
    .prepare(
      "INSERT INTO access (bot, user_id, role, data) VALUES ('TENANT', ?, 'TENANT', ?)",
    )
    .run(TENANT, JSON.stringify({ places: [], unit: "305" }));
  const signIn = await signInForTests(env.TENANT_BOT_TOKEN as string, {
    auth_date: String(NOW - 30),
    user: JSON.stringify({ id: TENANT, language_code: "en" }),
  });
  const post = (form: Record<string, unknown>) =>
    handle(
      new Request("https://relay.test/form/tenant", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ init_data: signIn, form, photos: [] }),
      }),
      env,
      () => NOW,
      fetcher,
    );
  const urgent = await post({
    kind: "UNIT",
    problem_type_id: "t-water",
    urgent: true,
  });
  assert.equal(urgent.status, 200);
  assert.deepEqual(
    sent.map((m) => [m.bot, m.chat_id, m.text]),
    [
      ["STAFF", AUTHORIZER, "🚨 ទឹក · 305"],
      ["STAFF", CARETAKER_ON, "🚨 ទឹក · 305"],
      ["TENANT", TENANT, "km We got your urgent report."],
    ],
  );
  sent.length = 0;
  await post({
    kind: "BUILDING",
    problem_type_id: "t-fire",
    problem_place_id: "p-lobby",
    floor: "2",
  });
  assert.equal(sent[0]?.text, "🚨 ភ្លើង · ផ្ទះធំ · 2");
  sent.length = 0;
  await post({ kind: "UNIT", problem_type_id: "t-water", urgent: false });
  assert.deepEqual(
    sent.map((m) => m.text),
    ["km We got your report. Our office will check it."],
  );
  const items = await sealedItems(env);
  assert.deepEqual(
    items.map((item) => item.relay),
    [
      { answered: true, alerted: true },
      { answered: true, alerted: true },
      { answered: true, alerted: false },
    ],
  );
  // With the office back, the form is only kept for it.
  sent.length = 0;
  await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    () => NOW,
  );
  await post({ kind: "UNIT", problem_type_id: "t-water", urgent: true });
  assert.equal(sent.length, 0);
});

test("the office's offline body is checked, and the office counts as away after 150 seconds", async () => {
  const env = await setUp();
  const { sent, fetcher } = telegramFake();
  const bad = await handle(
    await officeRequest("PUT", "/office/offline/tenant", NOW, { texts: [] }),
    env,
    () => NOW,
  );
  assert.equal(bad.status, 400);
  const nobody = await handle(
    await officeRequest("PUT", "/office/offline/nobody", NOW, {
      texts: {},
      links: {},
    }),
    env,
    () => NOW,
  );
  assert.equal(nobody.status, 400);
  await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    () => NOW,
  );
  await sendUpdate(
    env,
    message(1, { text: "/start" }),
    fetcher,
    NOW + OFFICE_AWAY_SECONDS,
  );
  assert.equal(sent.length, 0);
  await sendUpdate(
    env,
    message(2, { text: "/start" }),
    fetcher,
    NOW + OFFICE_AWAY_SECONDS + 1,
  );
  assert.equal(sent.length, 1);
});

test("a busy night: 60 items with photos are pulled and confirmed within the free plan's 50 queries", async () => {
  const env = testEnv(keys.publicPem);
  for (let i = 0; i < 60; i += 1) {
    env.DB.sqlite
      .prepare(
        "INSERT INTO items (id, bot, kind, received_at, sealed) VALUES (?, 'TENANT', 'form', ?, 'x')",
      )
      .run(
        `item-${String(i).padStart(3, "0")}`,
        new Date((NOW + i) * 1000).toISOString(),
      );
    env.DB.sqlite
      .prepare("INSERT INTO media (id, item_id, position) VALUES (?, ?, 0)")
      .run(`media-${i}`, `item-${String(i).padStart(3, "0")}`);
  }
  let queries = 0;
  const prepare = env.DB.prepare.bind(env.DB);
  env.DB.prepare = (query: string) => {
    queries += 1;
    return prepare(query);
  };
  const pulled = await handle(
    await officeRequest("GET", "/office/items?limit=100", NOW),
    env,
    () => NOW,
  );
  const body = (await pulled.json()) as {
    items: { id: string; media: string[] }[];
  };
  assert.equal(body.items.length, 60);
  assert.deepEqual(body.items[59]?.media, ["media-59"]);
  assert.ok(queries < 10, `pull used ${queries} queries`);
  queries = 0;
  const confirmed = await handle(
    await officeRequest("POST", "/office/confirm", NOW, {
      ids: body.items.map((item) => item.id),
    }),
    env,
    () => NOW,
  );
  assert.deepEqual(await confirmed.json(), { deleted: 60 });
  assert.ok(queries < 10, `confirm used ${queries} queries`);
  assert.equal(
    (
      env.DB.sqlite.prepare("SELECT count(*) AS n FROM media").get() as {
        n: number;
      }
    ).n,
    0,
  );
});
