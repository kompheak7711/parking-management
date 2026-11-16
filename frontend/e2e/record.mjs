// Records the server answers of the screens in e2e/screens.ts from a running review app into
// e2e/fixtures/<fixture>.har.json, for the screen check to replay. Run by hand, signed in:
//   node e2e/record.mjs <fixture> <app url> <storage state json> [hash...]
// The cookies and every header but the content type are left out of the file.

import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const [fixture, appUrl, stateFile, ...hashes] = process.argv.slice(2);
if (!fixture || !appUrl || !stateFile || hashes.length === 0) {
  console.error(
    "usage: node e2e/record.mjs <fixture> <app url> <state json> <hash>...",
  );
  process.exit(2);
}
const file = new URL(`./fixtures/${fixture}.har.json`, import.meta.url);
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM,
  args: ["--no-proxy-server"],
});
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  storageState: stateFile,
  viewport: { width: 1366, height: 768 },
  recordHar: { path: file.pathname, content: "embed" },
});
const page = await context.newPage();
for (const hash of hashes) {
  await page.goto(`${appUrl}/${hash}`);
  await page.waitForTimeout(4000);
}
await context.close();
await browser.close();
const har = JSON.parse(readFileSync(file, "utf8"));
const API_PATH = /^\/(api|properties|units|unit-setup|reservations)\//;
har.log.entries = har.log.entries
  .filter(
    (entry) =>
      API_PATH.test(new URL(entry.request.url).pathname) &&
      entry.response.status >= 200,
  )
  .map((entry) => ({
    startedDateTime: entry.startedDateTime,
    request: { method: entry.request.method, url: entry.request.url },
    response: {
      status: entry.response.status,
      headers: entry.response.headers.filter(
        (h) => h.name.toLowerCase() === "content-type",
      ),
      content: entry.response.content,
    },
  }));
delete har.log.pages;
writeFileSync(file, JSON.stringify(har, null, 1));
console.log(`${har.log.entries.length} answers in ${file.pathname}`);
