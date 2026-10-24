// V1-058 R1: the frame of the signed-in app (DESIGN.md 0.29 "Layout" and "Menu, top bar and
// search"): the green menu on the left, the top bar with Phnom Penh time and the language
// switch, and the work area. Pages are drawn by App; the shell only frames them.

import { useEffect, useRef, useState, type ReactNode } from "react";

import logoUrl from "../assets/brand/CHETANA_Logo_Horizontal_Reverse.svg";
import type { Language } from "../signInText";
import { Icon } from "./icons";
import {
  MENU,
  allowedPagesOf,
  groupLabel,
  hashForPage,
  menuItemFor,
  menuItemName,
  pageName,
  type PageId,
} from "./navigation";

const TEXT = {
  menu: ["Menu", "ម៉ឺនុយ"],
  close_menu: ["Close the menu", "បិទម៉ឺនុយ"],
  property: ["CHETANA Residence", "CHETANA Residence"],
  tz: ["Phnom Penh time", "ម៉ោងភ្នំពេញ"],
  language: ["Language ភាសា", "Language ភាសា"],
  sign_out: ["Sign out", "ចាកចេញ"],
  signed_in: ["Signed in", "បានចូល"],
} as const;

type TextKey = keyof typeof TEXT;

const KHMER_WEEKDAYS = [
  "ថ្ងៃអាទិត្យ",
  "ថ្ងៃច័ន្ទ",
  "ថ្ងៃអង្គារ",
  "ថ្ងៃពុធ",
  "ថ្ងៃព្រហស្បតិ៍",
  "ថ្ងៃសុក្រ",
  "ថ្ងៃសៅរ៍",
];

/** Today's date and time in Phnom Penh: weekday, dd/mm/yyyy and 24-hour time. */
export function phnomPenhClock(
  instant: number,
  language: Language,
): { weekday: string; date: string; time: string } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(instant));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  // Phnom Penh is UTC+7 all year, so the weekday number follows from the shifted instant.
  const weekdayIndex = new Date(instant + 7 * 3600 * 1000).getUTCDay();
  return {
    weekday:
      language === "en"
        ? part("weekday")
        : (KHMER_WEEKDAYS[weekdayIndex] ?? ""),
    date: `${part("day")}/${part("month")}/${part("year")}`,
    time: `${part("hour")}:${part("minute")}`,
  };
}

function initials(name: string): string {
  const words = name
    .trim()
    .split(/\s+/)
    .filter((word) => word.length > 0);
  if (words.length === 0) return "?";
  return words
    .slice(0, 2)
    .map((word) => (Array.from(word)[0] ?? "").toUpperCase())
    .join("");
}

export interface AppShellProps {
  page: PageId;
  language: Language;
  onLanguageChange: (language: Language) => void;
  displayName: string | null;
  environment: string;
  buildId: string;
  now: () => number;
  signOutDisabled: boolean;
  onSignOut: () => void;
  notice: ReactNode;
  children: ReactNode;
  /** The person's capabilities; null while unknown (then every item shows). */
  capabilities: ReadonlySet<string> | null;
}

export function AppShell({
  page,
  language,
  onLanguageChange,
  displayName,
  environment,
  buildId,
  now,
  signOutDisabled,
  onSignOut,
  notice,
  children,
  capabilities,
}: AppShellProps) {
  const t = (key: TextKey) => TEXT[key][language === "en" ? 0 : 1];
  const [menuOpen, setMenuOpen] = useState(false);
  const [instant, setInstant] = useState(now);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setInstant(now());
    }, 30_000);
    return () => {
      window.clearInterval(timer);
    };
  }, [now]);

  useEffect(() => {
    document.documentElement.lang = language;
    return () => {
      document.documentElement.lang = "en";
    };
  }, [language]);

  const menuButton = useRef<HTMLButtonElement>(null);
  const firstMenuLink = useRef<HTMLAnchorElement>(null);
  const view = useRef<HTMLElement>(null);
  const shownPage = useRef(page);

  // A page change closes the slide-in menu, starts the new page at the top and moves the focus
  // to it, so keyboard and screen-reader users are not left on a link that was hidden (review
  // round 1).
  useEffect(() => {
    if (shownPage.current === page) return;
    shownPage.current = page;
    setMenuOpen(false);
    document.documentElement.scrollTop = 0;
    view.current?.focus();
  }, [page]);

  function closeMenu() {
    setMenuOpen(false);
    menuButton.current?.focus();
  }

  // The open slide-in menu acts as a dialog: the focus starts on its first link, the page
  // behind is inert, and Escape closes it.
  useEffect(() => {
    if (!menuOpen) return;
    firstMenuLink.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButton.current?.focus();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  const clock = phnomPenhClock(instant, language);
  const openItem = menuItemFor(page);
  const tabs = openItem === null ? [] : allowedPagesOf(openItem, capabilities);
  const title =
    openItem === null
      ? pageName(page, language)
      : menuItemName(openItem, language);
  const menu = MENU.map((group) => ({
    group,
    items: group.items.flatMap((item) => {
      const pages = allowedPagesOf(item, capabilities);
      const first = pages[0];
      return first === undefined ? [] : [{ item, first }];
    }),
  })).filter((entry) => entry.items.length > 0);
  const name =
    displayName !== null && displayName.trim().length > 0
      ? displayName.trim()
      : null;

  return (
    <div className="shell">
      <div className={menuOpen ? "shell-nav open" : "shell-nav"} id="shell-nav">
        {menuOpen && (
          <button
            aria-label={t("close_menu")}
            className="shell-iconbtn shell-nav-close"
            onClick={closeMenu}
            type="button"
          >
            <Icon name="x" />
          </button>
        )}
        <div className="shell-brand">
          <div className="shell-appname">
            <img alt="CHETANA" src={logoUrl} />
            <span lang="en">Residence Management</span>
          </div>
          <div className="shell-property">
            <Icon name="units" small />
            <span>{t("property")}</span>
            {environment !== "production" && (
              <span className="shell-env" lang="en">
                {environment.toUpperCase()}
              </span>
            )}
          </div>
        </div>
        <nav aria-label={t("menu")}>
          {menu.map(({ group, items }, index) => (
            <div className="shell-group" key={index}>
              {group.label !== null && (
                <span className="shell-group-label">
                  {groupLabel(group, language)}
                </span>
              )}
              <ul>
                {items.map(({ item, first }) => (
                  <li key={item.page}>
                    <a
                      ref={
                        item === menu[0]?.items[0]?.item
                          ? firstMenuLink
                          : undefined
                      }
                      aria-current={item === openItem ? "page" : undefined}
                      className="shell-item"
                      href={hashForPage(first)}
                    >
                      <Icon name={item.icon} />
                      <span>{menuItemName(item, language)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="shell-me">
          <span aria-hidden="true" className="shell-avatar">
            {initials(name ?? "?")}
          </span>
          <a
            aria-current={page === "account" ? "page" : undefined}
            className="shell-me-text"
            href={hashForPage("account")}
          >
            {name !== null ? (
              <b className="signed-in-name">{name}</b>
            ) : (
              <b>{t("signed_in")}</b>
            )}
            <small>{pageName("account", language)}</small>
          </a>
          <button
            className="shell-signout"
            disabled={signOutDisabled}
            onClick={onSignOut}
            type="button"
          >
            <Icon name="signout" small />
            <span>{t("sign_out")}</span>
          </button>
        </div>
        <p className="shell-build" lang="en">
          Build {buildId}
        </p>
      </div>
      {menuOpen && (
        <div aria-hidden="true" className="shell-scrim" onClick={closeMenu} />
      )}
      <div className="shell-main" inert={menuOpen}>
        <header className="shell-topbar">
          <button
            aria-controls="shell-nav"
            aria-expanded={menuOpen}
            aria-label={t("menu")}
            className="shell-iconbtn shell-menu-button"
            onClick={() => {
              setMenuOpen(true);
            }}
            ref={menuButton}
            type="button"
          >
            <Icon name="menu" />
          </button>
          <p className="shell-clock">
            <b>
              {clock.weekday} {clock.date} · {clock.time}
            </b>
            <br />
            {t("tz")}
          </p>
          <div aria-label={t("language")} className="shell-lang" role="group">
            <button
              aria-pressed={language === "km"}
              lang="km"
              onClick={() => {
                onLanguageChange("km");
              }}
              type="button"
            >
              ខ្មែរ
            </button>
            <button
              aria-pressed={language === "en"}
              lang="en"
              onClick={() => {
                onLanguageChange("en");
              }}
              type="button"
            >
              EN
            </button>
          </div>
        </header>
        <main
          aria-labelledby="page-title"
          className="shell-view"
          id="shell-view"
          ref={view}
          tabIndex={-1}
        >
          <div className="shell-head">
            <h1 id="page-title">{title}</h1>
          </div>
          {tabs.length > 1 && (
            <nav aria-label={title} className="shell-tabs">
              {tabs.map((tab) => (
                <a
                  aria-current={tab === page ? "page" : undefined}
                  className="shell-tab"
                  href={hashForPage(tab)}
                  key={tab}
                >
                  {pageName(tab, language)}
                </a>
              ))}
            </nav>
          )}
          {notice}
          {children}
        </main>
      </div>
    </div>
  );
}
