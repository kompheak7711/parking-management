// V1-061 Fix 3 (owner bug list 29/10/2026): "Back or reload must ask before leaving a money
// window." While a money window is open, reload or closing the tab gets the browser's own
// "Leave site?" question, and Back or Forward asks first; if the person stays, the address goes
// back to the money window and the page does not change. A page opened from code (a link the
// app follows itself) is not asked about, nor is the address the money window opened at.

import { useEffect } from "react";

import type { Language } from "../signInText";

const TEXT = {
  leave_money: [
    "Leave this page? A money window is open. Anything not saved yet is lost. If you pressed Save and got no answer, look in Payments before you receive the money again.",
    "ចាកចេញពីទំព័រនេះឬ? ផ្ទាំងប្រាក់កំពុងបើក។ អ្វីដែលមិនទាន់រក្សាទុកនឹងបាត់។ ប្រសិនបើអ្នកបានចុចរក្សាទុក ហើយមិនទទួលបានចម្លើយ សូមមើលក្នុងការបង់ប្រាក់ មុនពេលទទួលប្រាក់ម្តងទៀត។",
  ],
} as const;

const open = new Map<symbol, { message: string; hash: string }>();

function latest(): { message: string; hash: string } | undefined {
  return [...open.values()].at(-1);
}

// Installed when this module loads, before any page listens to the address, so that staying
// stops the page from following the address.
window.addEventListener("hashchange", (event: HashChangeEvent) => {
  const guard = latest();
  if (
    guard === undefined ||
    event.oldURL === "" ||
    window.location.hash === guard.hash
  )
    return;
  if (window.confirm(guard.message)) return;
  event.stopImmediatePropagation();
  window.history.pushState(null, "", new URL(event.oldURL).hash || "#/");
});
window.addEventListener("beforeunload", (event: BeforeUnloadEvent) => {
  if (latest() === undefined) return;
  event.preventDefault();
});

/** Asks before Back, Forward or reload while `active` (a money window is open). */
export function useLeaveGuard(active: boolean, language: Language): void {
  const message = TEXT.leave_money[language === "en" ? 0 : 1];
  useEffect(() => {
    if (!active) return;
    const id = Symbol("money window");
    open.set(id, { message, hash: window.location.hash });
    return () => {
      open.delete(id);
    };
  }, [active, message]);
}
