// What the relay reads from Telegram: webhook updates and Mini App sign-ins.

import type { Bytes, MediaRef } from "./types.ts";

export const MAX_PHOTO_SIDE = 1600; // bots plan: photos are kept at about 1600 px
export const MAX_MEDIA_PER_ITEM = 5; // bots plan: at most 5 photos per request
export const MAX_FILE_BYTES = 20 * 1024 * 1024; // bots plan: 20 MB per file
export const MAX_VIDEO_SECONDS = 30;
export const MAX_VOICE_SECONDS = 60; // owner 03/11: voice notes up to 1 minute
export const SIGN_IN_MAX_AGE_SECONDS = 24 * 60 * 60;

type Json = Record<string, unknown>;

function object(value: unknown): Json | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : undefined;
}

function whole(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value)
    ? value
    : undefined;
}

export interface UpdateFacts {
  updateId?: number;
  userId?: number;
  chatId?: number;
  languageCode?: string;
  media: MediaRef[];
  refused?: string;
}

// The person, the chat and the photos, video or voice note of one update.
export function readUpdate(update: Json): UpdateFacts {
  const message =
    object(update.message) ??
    object(update.edited_message) ??
    object(update.channel_post);
  const callback = object(update.callback_query);
  const sender =
    object(message?.from) ??
    object(callback?.from) ??
    object(object(update.my_chat_member)?.from);
  const chat = object(message?.chat) ?? object(object(callback?.message)?.chat);
  const facts: UpdateFacts = {
    updateId: whole(update.update_id),
    userId: whole(sender?.id),
    chatId: whole(chat?.id),
    languageCode:
      typeof sender?.language_code === "string"
        ? sender.language_code
        : undefined,
    media: [],
  };
  if (!message) {
    return facts;
  }
  const photos = Array.isArray(message.photo) ? message.photo.map(object) : [];
  if (photos.length > 0) {
    // Telegram sends each photo in several sizes; keep the biggest one up to 1600 px.
    const sizes = photos.filter((p): p is Json => p !== undefined);
    const fitting = sizes.filter(
      (p) =>
        Math.max(whole(p.width) ?? 0, whole(p.height) ?? 0) <= MAX_PHOTO_SIDE,
    );
    const pick = (fitting.length > 0 ? fitting : sizes).reduce((best, p) =>
      (whole(p.width) ?? 0) > (whole(best.width) ?? 0) ? p : best,
    );
    facts.media.push({
      fileId: String(pick.file_id),
      fileUniqueId: String(pick.file_unique_id),
      contentType: "image/jpeg",
      width: whole(pick.width),
      height: whole(pick.height),
      size: whole(pick.file_size),
    });
  }
  const voice = object(message.voice);
  if (voice) {
    if ((whole(voice.duration) ?? 0) > MAX_VOICE_SECONDS) {
      facts.refused = "voice_too_long";
    }
    facts.media.push({
      fileId: String(voice.file_id),
      fileUniqueId: String(voice.file_unique_id),
      contentType:
        voice.mime_type === "audio/mpeg" ? "audio/mpeg" : "audio/ogg",
      duration: whole(voice.duration),
      size: whole(voice.file_size),
    });
  }
  const video = object(message.video) ?? object(message.video_note);
  if (video) {
    if ((whole(video.duration) ?? 0) > MAX_VIDEO_SECONDS) {
      facts.refused = "video_too_long";
    }
    facts.media.push({
      fileId: String(video.file_id),
      fileUniqueId: String(video.file_unique_id),
      contentType: "video/mp4",
      width: whole(video.width) ?? whole(video.length),
      height: whole(video.height) ?? whole(video.length),
      duration: whole(video.duration),
      size: whole(video.file_size),
    });
  }
  if (facts.media.some((m) => (m.size ?? 0) > MAX_FILE_BYTES)) {
    facts.refused = "file_too_big";
  }
  return facts;
}

// Fetch one file from Telegram (getFile, then the file address). The key stays in this call.
export async function downloadFile(
  api: string,
  token: string,
  fileId: string,
  fetcher: typeof fetch = fetch,
): Promise<Bytes> {
  const info = await fetcher(
    `${api}/bot${token}/getFile?file_id=${encodeURIComponent(fileId)}`,
  );
  if (!info.ok) {
    throw new Error("telegram_get_file_failed");
  }
  const document = object(await info.json());
  const path = object(document?.result)?.file_path;
  if (
    document?.ok !== true ||
    typeof path !== "string" ||
    !/^[A-Za-z0-9_./-]+$/.test(path)
  ) {
    throw new Error("telegram_get_file_failed");
  }
  const file = await fetcher(`${api}/file/bot${token}/${path}`);
  if (!file.ok) {
    throw new Error("telegram_download_failed");
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length === 0 || bytes.length > MAX_FILE_BYTES) {
    throw new Error("file_too_big");
  }
  return bytes;
}

async function hmac(key: Bytes, data: string): Promise<Bytes> {
  const imported = await crypto.subtle.importKey(
    "raw",
    key,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(
    await crypto.subtle.sign("HMAC", imported, new TextEncoder().encode(data)),
  );
}

function hex(bytes: Bytes): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export interface SignIn {
  userId: number;
  languageCode?: string;
  authDate: number;
}

// A Mini App sign-in (Telegram.WebApp.initData), checked with the bot key as Telegram documents:
// secret = HMAC-SHA256("WebAppData", key); hash = HMAC-SHA256(secret, the sorted fields).
// Older than 24 hours is refused (bots plan, "Checks who it is").
export async function checkSignIn(
  initData: string,
  token: string,
  nowSeconds: number,
): Promise<SignIn | undefined> {
  const fields = new URLSearchParams(initData);
  const hash = fields.get("hash");
  if (!hash || !/^[0-9a-f]{64}$/.test(hash)) {
    return undefined;
  }
  fields.delete("hash");
  const lines = [...fields.entries()]
    .map(([name, value]) => `${name}=${value}`)
    .sort()
    .join("\n");
  const secret = await hmac(new TextEncoder().encode("WebAppData"), token);
  const expected = hex(await hmac(secret, lines));
  let difference = expected.length ^ hash.length;
  for (let i = 0; i < Math.min(expected.length, hash.length); i += 1) {
    difference |= expected.charCodeAt(i) ^ hash.charCodeAt(i);
  }
  if (difference !== 0) {
    return undefined;
  }
  const authDate = Number(fields.get("auth_date"));
  if (
    !Number.isSafeInteger(authDate) ||
    nowSeconds - authDate > SIGN_IN_MAX_AGE_SECONDS
  ) {
    return undefined;
  }
  let user: Json | undefined;
  try {
    user = object(JSON.parse(fields.get("user") ?? ""));
  } catch {
    return undefined;
  }
  const userId = whole(user?.id);
  if (userId === undefined || userId <= 0) {
    return undefined;
  }
  return {
    userId,
    authDate,
    languageCode:
      typeof user?.language_code === "string" ? user.language_code : undefined,
  };
}

// Used by the tests to make a signed sign-in the way Telegram does.
export async function signInForTests(
  token: string,
  fields: Record<string, string>,
): Promise<string> {
  const lines = Object.entries(fields)
    .map(([name, value]) => `${name}=${value}`)
    .sort()
    .join("\n");
  const secret = await hmac(new TextEncoder().encode("WebAppData"), token);
  const hash = hex(await hmac(secret, lines));
  return new URLSearchParams({ ...fields, hash }).toString();
}
