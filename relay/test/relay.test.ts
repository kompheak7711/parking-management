// Relay tests (bots plan, "Testing": a wrong signature, an old sign-in, an unknown caller and a
// too-big file are refused; sealed items open only with the office key; items are deleted after
// the office confirms).

import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanUp, handle, KEEP_DAYS } from "../src/index.ts";
import { importOfficeKey, seal } from "../src/seal.ts";
import { checkSignIn, readUpdate, signInForTests } from "../src/telegram.ts";
import { officeKeys, officeRequest, openSealed, testEnv } from "./fakes.ts";

const NOW = 1_793_000_000;
const clock = () => NOW;
const keys = await officeKeys();

function webhookRequest(bot: string, secret: string, update: unknown): Request {
  return new Request(`https://relay.test/telegram/${bot}`, {
    method: "POST",
    headers: {
      "x-telegram-bot-api-secret-token": secret,
      "content-type": "application/json",
    },
    body: JSON.stringify(update),
  });
}

const PHOTO = new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3, 4, 5]);

const telegram = (async (input: RequestInfo | URL) => {
  const url = String(input);
  if (url.includes("/getFile")) {
    return Response.json({
      ok: true,
      result: { file_path: "photos/file_1.jpg" },
    });
  }
  if (url.endsWith("/photos/file_1.jpg")) {
    return new Response(PHOTO);
  }
  return new Response("missing", { status: 404 });
}) as typeof fetch;

function textUpdate(id: number, text: string) {
  return {
    update_id: id,
    message: {
      message_id: 5,
      from: { id: 777, language_code: "km" },
      chat: { id: 777, type: "private" },
      text,
    },
  };
}

async function openItem(item: { id: string; sealed: string }) {
  const bytes = await openSealed(
    keys.privateKey,
    Buffer.from(item.sealed, "base64"),
    item.id,
  );
  return JSON.parse(new TextDecoder().decode(bytes));
}

test("a sealed item opens only with the office key and only under its own id", async () => {
  const officeKey = await importOfficeKey(keys.publicPem);
  const sealed = await seal(
    officeKey,
    new TextEncoder().encode("hello"),
    "item-0001",
  );
  const opened = await openSealed(keys.privateKey, sealed, "item-0001");
  assert.equal(new TextDecoder().decode(opened), "hello");
  await assert.rejects(openSealed(keys.privateKey, sealed, "item-0002"));
  const other = await officeKeys();
  await assert.rejects(openSealed(other.privateKey, sealed, "item-0001"));
  const changed = sealed.slice();
  changed[changed.length - 1] = (changed.at(-1) ?? 0) ^ 1;
  await assert.rejects(openSealed(keys.privateKey, changed, "item-0001"));
});

test("a webhook without the bot's secret word is refused and stores nothing", async () => {
  const env = testEnv(keys.publicPem);
  const answer = await handle(
    webhookRequest("tenant", "wrong", textUpdate(1, "hi")),
    env,
    clock,
  );
  assert.equal(answer.status, 404);
  const unknown = await handle(
    webhookRequest("other", "x", textUpdate(1, "hi")),
    env,
    clock,
  );
  assert.equal(unknown.status, 404);
  const count = await env.DB.prepare("SELECT count(*) AS n FROM items").first<{
    n: number;
  }>();
  assert.equal(count?.n, 0);
});

test("a webhook is sealed, pulled, then deleted after the office confirms", async () => {
  const env = testEnv(keys.publicPem);
  const update = {
    update_id: 10,
    message: {
      message_id: 6,
      from: { id: 777, language_code: "en" },
      chat: { id: 777, type: "private" },
      photo: [
        {
          file_id: "small",
          file_unique_id: "u-small",
          width: 90,
          height: 60,
          file_size: 900,
        },
        {
          file_id: "fit",
          file_unique_id: "u-fit",
          width: 1280,
          height: 960,
          file_size: 8,
        },
        {
          file_id: "huge",
          file_unique_id: "u-huge",
          width: 2560,
          height: 1920,
          file_size: 9000,
        },
      ],
    },
  };
  const request = webhookRequest("tenant", "tenant-webhook-secret", update);
  assert.equal((await handle(request, env, clock, telegram)).status, 200);
  const stored = await env.DB.prepare("SELECT sealed FROM items").first<{
    sealed: string;
  }>();
  assert.ok(
    stored && !stored.sealed.includes("777"),
    "nothing readable waits in the relay",
  );

  const pulled = await handle(
    await officeRequest("GET", "/office/items?limit=10", NOW),
    env,
    clock,
  );
  assert.equal(pulled.status, 200);
  const batch = (await pulled.json()) as {
    items: {
      id: string;
      bot: string;
      kind: string;
      sealed: string;
      media: string[];
    }[];
    waiting: number;
    dropped: number;
  };
  assert.equal(batch.waiting, 1);
  assert.equal(batch.dropped, 0);
  const item = batch.items[0];
  assert.ok(item);
  assert.equal(item.bot, "TENANT");
  assert.equal(item.kind, "update");
  assert.equal(item.media.length, 1);
  const plain = await openItem(item);
  assert.equal(plain.v, 1);
  assert.equal(plain.update_id, 10);
  assert.equal(plain.telegram_user_id, 777);
  assert.equal(plain.chat_id, 777);
  assert.equal(plain.language_code, "en");
  assert.equal(
    plain.media[0].file_unique_id,
    "u-fit",
    "the biggest photo up to 1600 px",
  );
  assert.equal(plain.media[0].size, PHOTO.length);

  const mediaId = item.media[0];
  assert.ok(mediaId);
  const media = await handle(
    await officeRequest("GET", `/office/media/${mediaId}`, NOW),
    env,
    clock,
  );
  const sealedPhoto = new Uint8Array(await media.arrayBuffer());
  assert.deepEqual(
    await openSealed(keys.privateKey, sealedPhoto, mediaId),
    PHOTO,
  );

  const confirm = await officeRequest("POST", "/office/confirm", NOW, {
    ids: [item.id],
  });
  assert.deepEqual(await (await handle(confirm, env, clock)).json(), {
    deleted: 1,
  });
  assert.equal(env.MEDIA.objects.size, 0);
  const again = await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    clock,
  );
  assert.equal(((await again.json()) as { items: unknown[] }).items.length, 0);
});

test("office calls with a wrong key, an old time or a changed body are refused", async () => {
  const env = testEnv(keys.publicPem);
  const wrongKey = await officeRequest(
    "GET",
    "/office/items",
    NOW,
    undefined,
    "22".repeat(32),
  );
  assert.equal((await handle(wrongKey, env, clock)).status, 401);
  const old = await officeRequest("GET", "/office/items", NOW - 301);
  assert.equal((await handle(old, env, clock)).status, 401);
  const signed = await officeRequest("POST", "/office/confirm", NOW, {
    ids: [],
  });
  const changed = new Request(signed.url, {
    method: "POST",
    headers: signed.headers,
    body: JSON.stringify({ ids: ["x"] }),
  });
  assert.equal((await handle(changed, env, clock)).status, 401);
  const unsigned = new Request("https://relay.test/office/items");
  assert.equal((await handle(unsigned, env, clock)).status, 401);
});

test("a too-big file or a too-long voice note is not fetched; the item says why", async () => {
  const env = testEnv(keys.publicPem);
  const voice = {
    update_id: 11,
    message: {
      from: { id: 778 },
      chat: { id: 778 },
      voice: {
        file_id: "v",
        file_unique_id: "uv",
        duration: 75,
        mime_type: "audio/ogg",
      },
    },
  };
  await handle(
    webhookRequest("tenant", "tenant-webhook-secret", voice),
    env,
    clock,
    telegram,
  );
  const big = {
    update_id: 12,
    message: {
      from: { id: 778 },
      chat: { id: 778 },
      video: {
        file_id: "big",
        file_unique_id: "ub",
        duration: 10,
        file_size: 25 * 1024 * 1024,
      },
    },
  };
  await handle(
    webhookRequest("tenant", "tenant-webhook-secret", big),
    env,
    clock,
    telegram,
  );
  assert.equal(env.MEDIA.objects.size, 0);
  const answer = await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    clock,
  );
  const pulled = (await answer.json()) as {
    items: { id: string; sealed: string; media: string[] }[];
  };
  const reasons = [];
  for (const item of pulled.items) {
    assert.equal(item.media.length, 0);
    reasons.push((await openItem(item)).refused);
  }
  assert.deepEqual(reasons.sort(), ["file_too_big", "voice_too_long"]);
});

test("more than 30 messages a minute from one person are dropped", async () => {
  const env = testEnv(keys.publicPem);
  for (let i = 0; i < 35; i += 1) {
    const update = textUpdate(100 + i, "hi");
    await handle(
      webhookRequest("tenant", "tenant-webhook-secret", update),
      env,
      clock,
    );
  }
  const count = await env.DB.prepare("SELECT count(*) AS n FROM items").first<{
    n: number;
  }>();
  assert.equal(count?.n, 30);
});

test("Mini App forms: signed, under 24 hours old, only for people on the access list", async () => {
  const env = testEnv(keys.publicPem);
  const token = env.STAFF_BOT_TOKEN as string;
  const user = JSON.stringify({ id: 4242, language_code: "km" });
  const fresh = await signInForTests(token, {
    auth_date: String(NOW - 60),
    user,
    query_id: "q",
  });
  const formRequest = (initData: string) =>
    new Request("https://relay.test/form/staff", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "https://chetana-forms.pages.dev",
      },
      body: JSON.stringify({
        init_data: initData,
        form: { kind: "clean", tasks: [1, 2] },
      }),
    });
  assert.equal((await handle(formRequest(fresh), env, clock)).status, 403);

  const list = { users: [{ id: 4242, role: "CLEANER" }] };
  const access = await handle(
    await officeRequest("PUT", "/office/access/staff", NOW, list),
    env,
    clock,
  );
  assert.equal(access.status, 200);
  const ok = await handle(formRequest(fresh), env, clock);
  assert.equal(ok.status, 200);
  assert.equal(
    ok.headers.get("access-control-allow-origin"),
    "https://chetana-forms.pages.dev",
  );

  const old = await signInForTests(token, {
    auth_date: String(NOW - 25 * 3600),
    user,
  });
  assert.equal((await handle(formRequest(old), env, clock)).status, 401);
  const forged = fresh.replace(/hash=[0-9a-f]{4}/, "hash=0000");
  assert.equal((await handle(formRequest(forged), env, clock)).status, 401);
  const tenantToken = env.TENANT_BOT_TOKEN as string;
  const otherBot = await signInForTests(tenantToken, {
    auth_date: String(NOW),
    user,
  });
  assert.equal((await handle(formRequest(otherBot), env, clock)).status, 401);

  const answer = await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    clock,
  );
  const pulled = (await answer.json()) as {
    items: { id: string; kind: string; sealed: string }[];
  };
  assert.equal(pulled.items.length, 1);
  const form = pulled.items[0];
  assert.ok(form);
  assert.equal(form.kind, "form");
  const plain = await openItem(form);
  assert.deepEqual(plain.payload, {
    form: { kind: "clean", tasks: [1, 2] },
    role: "CLEANER",
  });

  // A new list replaces the old one at once.
  await handle(
    await officeRequest("PUT", "/office/access/staff", NOW, { users: [] }),
    env,
    clock,
  );
  assert.equal((await handle(formRequest(fresh), env, clock)).status, 403);
});

test("items not pulled in 7 days are removed and counted", async () => {
  const env = testEnv(keys.publicPem);
  const then = NOW - KEEP_DAYS * 86400 - 10;
  const secret = "tenant-webhook-secret";
  await handle(
    webhookRequest("tenant", secret, textUpdate(1, "old")),
    env,
    () => then,
  );
  await handle(
    webhookRequest("tenant", secret, textUpdate(2, "new")),
    env,
    clock,
  );
  assert.equal(await cleanUp(env, NOW), 1);
  const answer = await handle(
    await officeRequest("GET", "/office/items", NOW),
    env,
    clock,
  );
  const pulled = (await answer.json()) as { items: unknown[]; dropped: number };
  assert.equal(pulled.items.length, 1);
  assert.equal(pulled.dropped, 1);
});

test("sign-in check and update reading", async () => {
  assert.equal(await checkSignIn("no-hash=1", "1:x", NOW), undefined);
  const facts = readUpdate({
    update_id: 3,
    callback_query: { from: { id: 9 }, message: { chat: { id: -100 } } },
  });
  assert.equal(facts.userId, 9);
  assert.equal(facts.chatId, -100);
  assert.deepEqual(facts.media, []);
});

test("the Tenant bot form: the page, its choices and the person's places, then the form with a voice note", async () => {
  const env = testEnv(keys.publicPem);
  const token = env.TENANT_BOT_TOKEN as string;
  const user = JSON.stringify({ id: 5151, language_code: "en" });
  const signIn = await signInForTests(token, {
    auth_date: String(NOW - 30),
    user,
  });
  const page = await handle(
    new Request("https://relay.test/app/tenant?form=unit&lang=en"),
    env,
    clock,
  );
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-type") ?? "", /^text\/html/);
  assert.match(
    page.headers.get("content-security-policy") ?? "",
    /connect-src 'self'/,
  );
  assert.match(await page.text(), /\/form\/tenant\/start/);
  assert.equal(
    (await handle(new Request("https://relay.test/app/nobody"), env, clock))
      .status,
    404,
  );

  const start = () =>
    handle(
      new Request("https://relay.test/form/tenant/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ init_data: signIn }),
      }),
      env,
      clock,
    );
  assert.equal((await start()).status, 403);

  const places = {
    places: [{ item_id: "i-1", number: 2, name_en: "Bedroom" }],
  };
  // DL-219: My requests and the repair to check are for the chat, not the form.
  const list = {
    users: [
      {
        id: 5151,
        role: "TENANT",
        data: { ...places, requests: { en: "UP1" }, check: "UP1" },
      },
    ],
  };
  assert.equal(
    (
      await handle(
        await officeRequest("PUT", "/office/access/tenant", NOW, list),
        env,
        clock,
      )
    ).status,
    200,
  );
  const choices = { types: [{ id: "t-1", code: "WATER" }], open_building: [] };
  assert.equal(
    (
      await handle(
        await officeRequest("PUT", "/office/choices/tenant", NOW, { choices }),
        env,
        clock,
      )
    ).status,
    200,
  );
  const started = await start();
  assert.equal(started.status, 200);
  assert.deepEqual(await started.json(), { ok: true, choices, mine: places });

  // Wrong lists are refused: an unsigned call, a list that is not a list, too much data.
  const unsigned = new Request("https://relay.test/office/choices/tenant", {
    method: "PUT",
    body: JSON.stringify({ choices }),
  });
  assert.equal((await handle(unsigned, env, clock)).status, 401);
  for (const [path, body] of [
    ["/office/choices/tenant", { choices: [1, 2] }],
    ["/office/choices/nobody", { choices }],
    [
      "/office/access/tenant",
      { users: [{ id: 1, role: "TENANT", data: { text: "x".repeat(9000) } }] },
    ],
    [
      "/office/access/tenant",
      { users: [{ id: 1, role: "TENANT", data: "x" }] },
    ],
  ] as const) {
    const answer = await handle(
      await officeRequest("PUT", path, NOW, body),
      env,
      clock,
    );
    assert.equal(answer.status, 400, path);
  }

  const voice = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 9, 9, 9]);
  const sent = await handle(
    new Request("https://relay.test/form/tenant", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        init_data: signIn,
        form: { kind: "UNIT", problem_type_id: "t-1", description: null },
        photos: [
          {
            content_type: "audio/webm",
            data: Buffer.from(voice).toString("base64"),
            duration: 21,
          },
        ],
      }),
    }),
    env,
    clock,
  );
  assert.equal(sent.status, 200);
  const pulled = (await (
    await handle(await officeRequest("GET", "/office/items", NOW), env, clock)
  ).json()) as { items: { id: string; kind: string; sealed: string }[] };
  const item = pulled.items[0];
  assert.ok(item);
  const plain = await openItem(item);
  assert.equal(plain.payload.role, "TENANT");
  assert.equal(plain.media.length, 1);
  assert.equal(plain.media[0].content_type, "audio/webm");
  assert.equal(plain.media[0].duration, 21);
  assert.equal(plain.media[0].size, voice.length);
});

test("the Staff forms: the page, the person's name, roles and shift, then a card scan with its photo", async () => {
  const env = testEnv(keys.publicPem);
  const token = env.STAFF_BOT_TOKEN as string;
  const signIn = await signInForTests(token, {
    auth_date: String(NOW - 30),
    user: JSON.stringify({ id: 6161, language_code: "km" }),
  });
  const page = await handle(
    new Request("https://relay.test/app/staff?form=home&lang=km"),
    env,
    clock,
  );
  assert.equal(page.status, 200);
  assert.match(
    page.headers.get("content-security-policy") ?? "",
    /connect-src 'self'/,
  );
  const html = await page.text();
  assert.match(html, /\/form\/staff\/start/);
  assert.match(html, /showScanQrPopup/);
  assert.match(html, /LocationManager/);
  // Step 4b: Report a problem (everyone) and Close job (Technicians).
  assert.match(html, /type: "REPORT"/);
  assert.match(html, /type: "CLOSE"/);
  assert.match(html, /MediaRecorder/);
  assert.match(html, /type: "METER"/);
  assert.match(html, /type: "METER_CHECK"/);
  assert.match(html, /type: "CHECKLIST"/);
  assert.match(html, /type: "PATROL"/);
  assert.match(html, /type: "UNIT_CHECK"/);
  assert.match(html, /type: "MAINT_CHECK"/);

  const mine = {
    name_km: "ពេជ ភក្រក្ដី",
    roles: ["CARETAKER"],
    shift_code: "MORNING",
    shift_km: "វេនព្រឹក",
  };
  const list = { users: [{ id: 6161, role: "STAFF", data: mine }] };
  assert.equal(
    (
      await handle(
        await officeRequest("PUT", "/office/access/staff", NOW, list),
        env,
        clock,
      )
    ).status,
    200,
  );
  const started = await handle(
    new Request("https://relay.test/form/staff/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ init_data: signIn }),
    }),
    env,
    clock,
  );
  assert.equal(started.status, 200);
  assert.deepEqual(await started.json(), { ok: true, choices: null, mine });

  const photo = new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3]);
  const sent = await handle(
    new Request("https://relay.test/form/staff", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        init_data: signIn,
        form: {
          type: "CARD",
          mode: "IN",
          card: "CHETANA-E-x",
          reason: "NO_PHONE",
        },
        photos: [
          {
            content_type: "image/jpeg",
            data: Buffer.from(photo).toString("base64"),
          },
        ],
      }),
    }),
    env,
    clock,
  );
  assert.equal(sent.status, 200);
  const pulled = (await (
    await handle(await officeRequest("GET", "/office/items", NOW), env, clock)
  ).json()) as {
    items: { id: string; bot: string; kind: string; sealed: string }[];
  };
  const item = pulled.items[0];
  assert.ok(item);
  assert.equal(item.bot, "STAFF");
  assert.equal(item.kind, "form");
  const plain = await openItem(item);
  assert.equal(plain.payload.role, "STAFF");
  assert.equal(plain.payload.form.type, "CARD");
  assert.equal(plain.media[0].content_type, "image/jpeg");
  assert.equal(plain.media[0].size, photo.length);
});
