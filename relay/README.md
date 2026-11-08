# Telegram relay

A small Cloudflare Worker that stands between Telegram and the office computer
(bots plan, "The relay"). The office computer is never open to the internet: it
pulls from the relay every minute.

What it does:

1. Takes Telegram webhooks at `POST /telegram/{customer|tenant|staff}`. The
   bot's secret word must be in the `X-Telegram-Bot-Api-Secret-Token` header.
2. Serves the Mini App form pages (`GET /app/tenant?form=unit|building`, the
   Tenant bot's Problem report). The page asks `POST /form/{bot}/start` for what
   to show and sends the form to `POST /form/{bot}`. The Telegram sign-in must
   be right and less than 24 hours old. Tenant and Staff forms need the person
   on the access list the office sends.
3. Seals every item and photo with the office public key before it is stored.
   Only the office private key opens it (`backend/src/property_rental/telegram_seal.py`).
4. Gives the office its items (`GET /office/items`, `GET /office/media/{id}`),
   deletes them when the office confirms (`POST /office/confirm`), and takes
   the access lists (`PUT /office/access/{bot}`) and the form choices
   (`PUT /office/choices/{bot}`). Every office call is signed
   with the pull key and must be within 5 minutes of the relay's clock.
5. Every hour removes items not pulled in 7 days and counts them.

Limits: 30 messages a minute per person; photos up to 1600 px; voice notes up
to 60 seconds; videos up to 30 seconds; files up to 20 MB; 5 files per item.

## Tests

No packages. Node.js 22.6 or newer:

```
make relay-test        # node:test, with node:sqlite standing in for D1
make relay-typecheck   # after make frontend-install
```

## Setting it up (owner, once)

These steps come with the owner test script for the bots. Nothing here is a
real secret: every key is made on the office computer and typed into
Cloudflare, never into this repository or a chat.

1. On the office computer, make the keys:
   ```
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out office.pem
   openssl pkey -in office.pem -pubout -out office.pub.pem
   openssl rand -hex 32 > relay-pull.key
   ```
   Copy them into `/etc/prm/secrets/` (mode 0600, owner prm-ops) as
   `prm_production_relay_office_private_key` and `prm_production_relay_pull_key`.
   Each bot's token goes there too, as `prm_production_{customer|tenant|staff}_bot_token`.
   Then delete `office.pem` and `relay-pull.key` from where you made them.
2. In Cloudflare: create the D1 database `chetana-relay` and the R2 bucket
   `chetana-relay-media`. Put the database id in `wrangler.toml`.
3. Create the tables: `npx wrangler d1 execute chetana-relay --remote --file schema.sql`.
4. Set the secrets (`npx wrangler secret put NAME`, then paste the value):
   `OFFICE_PUBLIC_KEY` (all of `office.pub.pem`), `OFFICE_PULL_KEY` (the
   64 letters of `relay-pull.key`), and for each bot `{BOT}_BOT_TOKEN` and
   `{BOT}_WEBHOOK_SECRET` (a new random word, for example `openssl rand -hex 24`).
5. Deploy: `npx wrangler deploy`.
6. Point each bot at the relay with Telegram's `setWebhook`, using
   `https://chetana-relay.<account>.workers.dev/telegram/tenant` and the same
   secret word as `secret_token`.
7. In `/etc/prm/production-operations.json`, set `telegram_bots.relay_host` to
   the relay address and `telegram_bots.enabled` to `true`, then start the
   timers `prm-telegram-pull.timer` and `prm-telegram-send.timer`.

## On the Mac mini test run

For testing before the office server, `Set up Telegram test.command` (repository folder,
`scripts/local/telegram-setup.sh`) does steps 1 to 7 for the Mac mini, once:

- the keys, webhook words and bot tokens stay in `.local/telegram` (mode 0700, never
  committed); each token is pasted into Terminal with echo off and checked with Telegram;
- Cloudflare is used through `npx wrangler@4.151.3` (Cloudflare's own command line; it is
  downloaded when the setup runs and is not added to the repository); the browser asks you to
  sign in once;
- the photo bucket needs R2 turned on in the Cloudflare dashboard, which asks for a card even
  for the free use;
- the setup writes `.local/telegram/operations.json` and `jobs.env` (the Property, the Owner
  account the jobs run as, and the Staff bot's service actor).

After it, `Start test app.command` also runs the pull and send jobs every 10 seconds
(`scripts/local/telegram-jobs.sh`, log `.local/telegram.log`). Send `ping` to a bot to check
the connection. Running the setup again keeps what is there and redoes the rest.

## While the app is closed (DL-210)

When the office has not pulled for 150 seconds, the relay answers the Tenant bot itself, with
the texts, buttons and scrambled Lease check codes the office sent (`relay/src/offline.ts`):

- Start, the language, Link my Lease (own phone, name and Unit, checked against keyed hashes;
  5 wrong tries block for 24 hours), Contact office and the Problem report buttons;
- a sent report gets "We got your report. Our office will check it." at once, and an urgent one
  goes first to the Authorizers and the caretaker on shift on the Staff bot;
- My requests, FAQ, Fixed and Not fixed get "Our office is closed now" and wait for the office.

Each item tells the office what the relay said; the app saves it without answering twice. The
relay needs the `LINK_CHECK_KEY` secret (the office's `link-check.key`) to link anyone; the Mac
setup makes both. After pulling a new version, run the setup again (it keeps the bot tokens) so
the relay gets the new tables and code.
