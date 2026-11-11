-- The relay's waiting list (Cloudflare D1). It holds sealed items only until the office pulls
-- them, then deletes them; nothing waits longer than 7 days. No names, no phone numbers: only
-- sealed bytes, Telegram account numbers and roles.
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  kind TEXT NOT NULL,
  received_at TEXT NOT NULL,
  sealed TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_received ON items (received_at);

-- Photos, videos and voice notes of an item; the sealed bytes are in R2 under "m/<id>".
CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY,
  item_id TEXT NOT NULL,
  position INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS media_item ON media (item_id);

-- Who may send forms, sent by the office app (linked tenants, approved staff and their roles).
-- "data" is what that person's form shows (for a tenant, the places in their Unit, such as
-- "Bedroom 2"; never a name, a phone number or a Unit number).
CREATE TABLE IF NOT EXISTS access (
  bot TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  data TEXT,
  PRIMARY KEY (bot, user_id)
);

-- What a bot's forms show to everyone on its access list, sent by the office app (problem
-- types, shared places, the open Building problems by number and place).
CREATE TABLE IF NOT EXISTS choices (
  bot TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Items removed after 7 days without a pull, per day, for the health page.
CREATE TABLE IF NOT EXISTS dropped (
  day TEXT PRIMARY KEY,
  count INTEGER NOT NULL
);

-- Messages per person per minute (at most 30).
CREATE TABLE IF NOT EXISTS rate (
  user_id INTEGER NOT NULL,
  minute INTEGER NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (user_id, minute)
);

-- When the office last pulled (DL-210). The relay answers a Tenant bot chat itself only while
-- the office has not pulled for a while (the app on the office computer is closed).
CREATE TABLE IF NOT EXISTS office_seen (
  what TEXT PRIMARY KEY,
  at INTEGER NOT NULL
);

-- What the relay needs to answer while the office is away (DL-210), sent by the office app as
-- one body per bot: the bot's texts and buttons, the scrambled Lease check codes (keyed hashes,
-- never a name or a phone number) with each Unit's number and places, and who gets an urgent
-- alert (Telegram account numbers and shift times only).
CREATE TABLE IF NOT EXISTS offline (
  bot TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- The relay's own chat step while it answers for the office (DL-210). The typed name and the
-- shared phone are kept only between the link steps and wiped after 30 minutes.
CREATE TABLE IF NOT EXISTS chats (
  bot TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  language TEXT,
  step TEXT,
  name TEXT,
  phone TEXT,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (bot, user_id)
);

-- Lease link tries that did not match while the relay answered (5 in 24 hours = 24 h block).
CREATE TABLE IF NOT EXISTS link_tries (
  user_id INTEGER NOT NULL,
  at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS link_tries_user ON link_tries (user_id, at);

-- A customer's request while the relay asks the Send an inquiry questions for the office
-- (DL-213): the answers given so far, until the request is sent or 30 minutes pass.
CREATE TABLE IF NOT EXISTS chat_requests (
  bot TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  data TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (bot, user_id)
);
