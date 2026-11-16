// Replays recorded server answers (a HAR file made by e2e/record.mjs) for the built app, so the
// screen check needs no database and no API. A request is matched by method and path with its
// query, then by method and path alone; anything else gets 404.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Page } from "@playwright/test";

interface HarEntry {
  request: { method: string; url: string };
  response: {
    status: number;
    headers: { name: string; value: string }[];
    content: { mimeType?: string; text?: string; encoding?: string };
  };
}

interface Har {
  log: { entries: HarEntry[] };
}

export const API_PATH = /^\/(api|properties|units|unit-setup|reservations)\//;

function keyOf(method: string, url: URL, withQuery: boolean): string {
  return `${method} ${url.pathname}${withQuery ? url.search : ""}`;
}

export function loadFixture(name: string): Map<string, HarEntry> {
  const file = join(import.meta.dirname, "fixtures", `${name}.har.json`);
  const har = JSON.parse(readFileSync(file, "utf8")) as Har;
  const answers = new Map<string, HarEntry>();
  for (const entry of har.log.entries) {
    const url = new URL(entry.request.url);
    if (!API_PATH.test(url.pathname)) continue;
    // The first answer of an address wins (the sign-in calls are recorded once each).
    for (const withQuery of [true, false]) {
      const key = keyOf(entry.request.method, url, withQuery);
      if (!answers.has(key)) answers.set(key, entry);
    }
  }
  return answers;
}

/** The recorded session answer with its activity and expiry times moved to now. */
export function freshSession(body: string): string {
  const now = Date.now();
  const at = (offsetMs: number) =>
    JSON.stringify(new Date(now + offsetMs).toISOString());
  return body
    .replace(/"last_activity_at"\s*:\s*"[^"]*"/, `"last_activity_at":${at(0)}`)
    .replace(
      /"idle_expires_at"\s*:\s*"[^"]*"/,
      `"idle_expires_at":${at(30 * 60_000)}`,
    )
    .replace(
      /"absolute_expires_at"\s*:\s*"[^"]*"/,
      `"absolute_expires_at":${at(24 * 3_600_000)}`,
    );
}

export async function replay(page: Page, fixture: string): Promise<void> {
  const answers = loadFixture(fixture);
  await page.route(
    (url) => API_PATH.test(url.pathname),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const entry =
        answers.get(keyOf(request.method(), url, true)) ??
        answers.get(keyOf(request.method(), url, false));
      if (entry === undefined) {
        await route.fulfill({ status: 404, body: "not recorded" });
        return;
      }
      const { content } = entry.response;
      let body =
        content.text === undefined
          ? ""
          : content.encoding === "base64"
            ? Buffer.from(content.text, "base64")
            : content.text;
      // The money clients check the answer's headers and that it names their own request id,
      // which is new on every call: the replay answers with the id of the request it gets.
      const requestId = request.headers()["x-request-id"];
      // The recorded session would have run out by now (it ends 30 minutes after the last
      // activity): the replay moves its times to the present, as a live server would.
      if (typeof body === "string" && url.pathname.endsWith("/auth/session"))
        body = freshSession(body);
      const headers: Record<string, string> = {
        "cache-control": "private, no-store",
        vary: "Cookie",
      };
      if (requestId !== undefined) {
        headers["x-request-id"] = requestId;
        if (typeof body === "string")
          body = body.replace(
            /"request_id"\s*:\s*"[^"]*"/,
            `"request_id":${JSON.stringify(requestId)}`,
          );
      }
      await route.fulfill({
        status: entry.response.status,
        contentType: content.mimeType ?? "application/json",
        headers,
        body,
      });
    },
  );
}
