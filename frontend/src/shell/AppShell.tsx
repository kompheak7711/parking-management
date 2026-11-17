// V1-058 R1: the frame of the signed-in app (DESIGN.md 0.29 "Layout" and "Menu, top bar and
// search"): the green menu on the left, the top bar with Phnom Penh time and the language
// switch, and the work area. Pages are drawn by App; the shell only frames them.
//
// UI v81 side menu (owner 08/11/2026, section D; design app23.js): "Collapse menu" shrinks the
// menu to icons with the name in a fly-out on hover or focus (wide screens only, remembered on
// the device); the groups fold and unfold and show their item count when folded (the group of
// the open page opens when the page is entered); an item with tabs gets a "⌄" that lists its
// tabs as sub-items linking to the same addresses as the tabs; the user card names the person
// and the role with Sign out; on a phone the same menu is the drawer behind the ☰ button.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent as ReactFocusEvent,
  type ReactNode,
} from "react";

import logoUrl from "../assets/brand/CHETANA_Logo_Horizontal_Reverse.svg";
import type { Language } from "../signInText";
import { Icon } from "./icons";
import { PageHeadContext, type PageHeadSlots } from "./pageHead";
import { installTableFit } from "./tableFit";
import { openPageInAddress } from "./useHashPage";
import {
  MENU,
  allowedGroupsOf,
  allowedPagesOf,
  groupLabel,
  hashForPage,
  menuGroupKey,
  menuItemFor,
  menuItemName,
  pageName,
  subItemsOf,
  subTabFromHash,
  switchName,
  type MenuItem,
  type PageId,
  type SubItem,
} from "./navigation";

const TEXT = {
  menu: ["Menu", "ម៉ឺនុយ"],
  close_menu: ["Close the menu", "បិទម៉ឺនុយ"],
  property: ["CHETANA Parking", "CHETANA Parking"],
  tz: ["Phnom Penh time", "ម៉ោងភ្នំពេញ"],
  language: ["Language ភាសា", "Language ភាសា"],
  sign_out: ["Sign out", "ចាកចេញ"],
  signed_in: ["Signed in", "បានចូល"],
  // UI v81 side menu (design i18n23.js).
  collapse: ["Collapse menu", "បង្រួមម៉ឺនុយ"],
  expand: ["Expand menu", "ពង្រីកម៉ឺនុយ"],
  pages: ["{0} pages", "ទំព័រ {0}"],
  // The role on the user card (design i18n4.js role_owner, role_manager; Staff from the role
  // bundle's Khmer name).
  role_owner: ["Owner", "ម្ចាស់"],
  role_manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  role_staff: ["Staff", "បុគ្គលិក"],
} as const;

type TextKey = keyof typeof TEXT;

// What the device remembers about the menu (the same keys as the design, app23.js).
/** Pages whose tab row is their head (owner 13/11/2026 23:44): no title or sub-line on show. */
// Property fix 2 (owner 14/11/2026): Products, Stock movements and Storage locations too.
// Administration review fix 1 (owner 13/11/2026): the Ledger, Staff and Telegram tabs too.
const TABBED_HEAD: ReadonlySet<string> = new Set([
  "invoices",
  "quotations",
  "products",
  "stock",
  "locations",
  "exreqs",
  "expenses",
  "bills",
  "journal",
  "needscheck",
  "chart",
  "statements",
  "budget",
  "fassets",
  "bankcash",
  "lclose",
  "employees",
  "loans",
  "payroll",
  "attendance",
  "tglinks",
  "tgsent",
  "tgcontact",
  "tgfaq",
  "tgnotices",
  "tghealth",
  // UI v81 batch 6 (Reservations): the Long stays tabs too.
  "reservations",
  "leases",
  "moveout",
]);

/** More tabs than this and the page's buttons move under the tab row. */
const MANY_TABS = 6;

const RAIL_KEY = "chetana-rail";
const GROUPS_KEY = "chetana-navgrp";
const SUBS_KEY = "chetana-navopen";
/** Wide screens show the menu beside the page; the collapsed rail exists only there. */
const WIDE = "(min-width: 1081px)";

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function readFlags(key: string): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed: unknown = raw === null ? {} : JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
      return {};
    const flags: Record<string, boolean> = {};
    for (const [name, value] of Object.entries(parsed))
      if (typeof value === "boolean") flags[name] = value;
    return flags;
  } catch {
    return {};
  }
}

/** The flags without one name (a group opened again, a sub-list back to its default). */
function without(
  flags: Record<string, boolean>,
  name: string,
): Record<string, boolean> {
  return Object.fromEntries(
    Object.entries(flags).filter(([candidate]) => candidate !== name),
  );
}

/** The remembered key of the group that holds a page, or null for a page outside the menu. */
function groupKeyOfPage(page: PageId): string | null {
  const item = menuItemFor(page);
  if (item === null) return null;
  const group = MENU.find((candidate) => candidate.items.includes(item));
  return group === undefined ? null : menuGroupKey(group);
}

function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage is blocked: the choice lasts for this page only.
  }
}

function isWide(): boolean {
  return (
    typeof window.matchMedia === "function" && window.matchMedia(WIDE).matches
  );
}

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

export type AccountClass = "owner" | "manager" | "staff";

export interface AppShellProps {
  page: PageId;
  language: Language;
  onLanguageChange: (language: Language) => void;
  displayName: string | null;
  /** UI v81 side menu: the role on the user card; null while unknown. */
  accountClass?: AccountClass | null;
  environment: string;
  buildId: string;
  now: () => number;
  signOutDisabled: boolean;
  onSignOut: () => void;
  notice: ReactNode;
  children: ReactNode;
  /** The person's capabilities; null while unknown (then every item shows). */
  capabilities: ReadonlySet<string> | null;
  /** UI v81: the top-bar search box. */
  search?: ReactNode;
}

export function AppShell({
  page,
  language,
  onLanguageChange,
  displayName,
  accountClass = null,
  environment,
  buildId,
  now,
  signOutDisabled,
  onSignOut,
  notice,
  children,
  capabilities,
  search,
}: AppShellProps) {
  const t = (key: TextKey) => TEXT[key][language === "en" ? 0 : 1];
  const tf = (key: TextKey, value: number) =>
    t(key).replace("{0}", String(value));
  const [menuOpen, setMenuOpen] = useState(false);
  const [instant, setInstant] = useState(now);
  // UI v81 round 2: the page's sub-line and buttons sit in the head row, as in the design.
  const [headSub, setHeadSub] = useState<HTMLElement | null>(null);
  const [headActions, setHeadActions] = useState<HTMLElement | null>(null);
  // UI v81 shared layouts: a page drawn with PageHeader (a record or a form) takes the head;
  // the shell then draws no page title and no tab bar while that page is on screen.
  const [ownHead, setOwnHead] = useState(false);
  const slots: PageHeadSlots = useMemo(
    () => ({ page, sub: headSub, actions: headActions, ownHead: setOwnHead }),
    [page, headSub, headActions],
  );

  // UI v81 side menu: what the device remembers, and the address (for the current sub-tab).
  const [rail, setRail] = useState(() => readFlag(RAIL_KEY));
  // The group of the page the app opens on is always open (owner, section D point 13).
  const [folded, setFolded] = useState(() => {
    const flags = readFlags(GROUPS_KEY);
    const key = groupKeyOfPage(page);
    if (key === null || !flags[key]) return flags;
    const opened = without(flags, key);
    remember(GROUPS_KEY, JSON.stringify(opened));
    return opened;
  });
  const [subsOpen, setSubsOpen] = useState(() => readFlags(SUBS_KEY));
  const [hash, setHash] = useState(() =>
    typeof window === "undefined" ? "" : window.location.hash,
  );
  const [fly, setFly] = useState<{ page: PageId; top: number } | null>(null);

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

  useEffect(() => {
    document.documentElement.classList.toggle("shell-rail", rail);
    return () => {
      document.documentElement.classList.remove("shell-rail");
    };
  }, [rail]);

  useEffect(() => {
    const follow = () => {
      setHash(window.location.hash);
    };
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);

  // UI v81 round 3: a list page's main table scrolls in its own area and keeps its place for Back.
  useEffect(() => installTableFit(), []);

  const menuButton = useRef<HTMLButtonElement>(null);
  const firstMenuLink = useRef<HTMLAnchorElement>(null);
  const view = useRef<HTMLElement>(null);
  const shownPage = useRef(page);
  const openItem = menuItemFor(page);

  // A page change closes the slide-in menu, starts the new page at the top and moves the focus
  // to it, so keyboard and screen-reader users are not left on a link that was hidden (review
  // round 1). UI v81 side menu: entering a page opens its group and its sub-list again.
  useEffect(() => {
    if (shownPage.current === page) return;
    shownPage.current = page;
    setMenuOpen(false);
    setFly(null);
    document.documentElement.scrollTop = 0;
    view.current?.focus();
    const item = menuItemFor(page);
    if (item === null) return;
    const key = groupKeyOfPage(page);
    if (key !== null) {
      setFolded((previous) => {
        if (!previous[key]) return previous;
        const next = without(previous, key);
        remember(GROUPS_KEY, JSON.stringify(next));
        return next;
      });
    }
    setSubsOpen((previous) => {
      if (previous[item.page] !== false) return previous;
      const next = without(previous, item.page);
      remember(SUBS_KEY, JSON.stringify(next));
      return next;
    });
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

  // The fly-out of the collapsed rail closes with Escape (the focus goes back to its icon) and
  // when the window changes size.
  useEffect(() => {
    if (fly === null) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      const link = document.querySelector<HTMLAnchorElement>(
        `.shell-nitem[data-menu-page="${fly?.page ?? ""}"] > .shell-item`,
      );
      setFly(null);
      link?.focus();
    }
    function onResize() {
      setFly(null);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [fly]);

  const toggleRail = useCallback(() => {
    setRail((previous) => {
      remember(RAIL_KEY, previous ? "0" : "1");
      return !previous;
    });
    setFly(null);
  }, []);

  function toggleGroup(key: string) {
    setFolded((previous) => {
      const next = previous[key]
        ? without(previous, key)
        : { ...previous, [key]: true };
      remember(GROUPS_KEY, JSON.stringify(next));
      return next;
    });
  }

  function toggleSubs(item: MenuItem, open: boolean) {
    setSubsOpen((previous) => {
      const next = { ...previous, [item.page]: !open };
      remember(SUBS_KEY, JSON.stringify(next));
      return next;
    });
  }

  function showFly(row: HTMLElement, itemPage: PageId) {
    if (!rail || !isWide()) return;
    setFly({
      page: itemPage,
      top: Math.round(row.getBoundingClientRect().top),
    });
  }

  function hideFlyOnBlur(event: ReactFocusEvent<HTMLElement>) {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    setFly(null);
  }

  const clock = phnomPenhClock(instant, language);
  const tabs = openItem === null ? [] : allowedPagesOf(openItem, capabilities);
  // Owner 16/11/2026: a menu item with tab groups (Ledger) shows one tab per group; the open
  // group's pages are picked with a switch under the head.
  const groups =
    openItem === null ? [] : allowedGroupsOf(openItem, capabilities, language);
  const openGroup = groups.find((group) => group.pages.includes(page)) ?? null;
  const tabEntries: {
    key: string;
    target: PageId;
    label: string;
    current: boolean;
  }[] =
    groups.length > 0
      ? groups.map((group) => ({
          key: group.id,
          target: group.pages[0] ?? page,
          label: group.label,
          current: group === openGroup,
        }))
      : tabs.map((tab) => ({
          key: tab,
          target: tab,
          label: pageName(tab, language),
          current: tab === page,
        }));
  const groupSwitch =
    openGroup !== null && openGroup.pages.length > 1 ? openGroup.pages : [];
  const tabbedHead =
    (tabEntries.length > 1 || groupSwitch.length > 1) && TABBED_HEAD.has(page);
  // Administration review fix 2: the tab row slides sideways, so the open tab is brought into
  // view when the page opens (the row itself scrolls; the page does not move).
  useEffect(() => {
    const row = view.current?.querySelector<HTMLElement>(".shell-tabs");
    const open = row?.querySelector<HTMLElement>('[aria-current="page"]');
    if (
      row === undefined ||
      row === null ||
      open === null ||
      open === undefined
    )
      return;
    if (row.scrollWidth <= row.clientWidth) return;
    const at =
      open.getBoundingClientRect().left -
      row.getBoundingClientRect().left +
      row.scrollLeft;
    row.scrollLeft = Math.max(0, at - (row.clientWidth - open.offsetWidth) / 2);
  }, [page]);
  // UI v81 round 2: the title is the open page's name (the tab's), as in design v81; the tab
  // bar is named after the menu item.
  const title = pageName(page, language);
  const tabsName = openItem === null ? title : menuItemName(openItem, language);
  const subTab = subTabFromHash(hash);
  const menu = MENU.map((group) => ({
    group,
    key: menuGroupKey(group),
    items: group.items.flatMap((item) => {
      const pages = allowedPagesOf(item, capabilities);
      const first = pages[0];
      return first === undefined
        ? []
        : [
            {
              item,
              first,
              subs: subItemsOf(item, page, subTab, capabilities, language),
            },
          ];
    }),
  })).filter((entry) => entry.items.length > 0);
  const name =
    displayName !== null && displayName.trim().length > 0
      ? displayName.trim()
      : null;
  const role =
    accountClass === null ? null : t(`role_${accountClass}` as TextKey);

  function subList(subs: SubItem[], className: string): ReactNode {
    return (
      <ul className={className}>
        {subs.map((sub) => (
          <li key={sub.key}>
            <a
              aria-current={sub.current ? "page" : undefined}
              href={sub.href}
              onClick={() => {
                setFly(null);
              }}
            >
              {sub.label}
            </a>
          </li>
        ))}
      </ul>
    );
  }

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
            <span lang="en">Parking Rental</span>
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
        <button
          aria-pressed={rail}
          className="shell-railbtn"
          onClick={toggleRail}
          type="button"
        >
          <Icon name={rail ? "expand" : "collapse"} />
          <span>{t(rail ? "expand" : "collapse")}</span>
        </button>
        <nav aria-label={t("menu")}>
          {menu.map(({ group, key, items }) => {
            const holdsPage = items.some(({ item }) => item === openItem);
            // In the collapsed rail every group stays open (its header is a thin line).
            const groupOpen = group.label === null || rail || !folded[key];
            return (
              <div
                className={holdsPage ? "shell-group cur" : "shell-group"}
                key={key}
              >
                {group.label !== null && (
                  <button
                    aria-controls={`shell-grp-${key}`}
                    aria-expanded={groupOpen}
                    className="shell-grph"
                    onClick={() => {
                      toggleGroup(key);
                    }}
                    type="button"
                  >
                    <span>{groupLabel(group, language)}</span>
                    <span className="shell-cnt">{items.length}</span>
                    <Icon name="chevron" small />
                  </button>
                )}
                <div
                  className={groupOpen ? "shell-col" : "shell-col shut"}
                  hidden={!groupOpen}
                  id={`shell-grp-${key}`}
                >
                  <ul>
                    {items.map(({ item, first, subs }) => {
                      const current = item === openItem;
                      const subCurrent = subs.some((sub) => sub.current);
                      const open =
                        subs.length > 1 &&
                        (current
                          ? subsOpen[item.page] !== false
                          : subsOpen[item.page] === true);
                      const itemName = menuItemName(item, language);
                      const flying = rail && fly?.page === item.page;
                      return (
                        <li
                          className={[
                            "shell-nitem",
                            subs.length > 1 ? "has-sub" : "",
                            current ? "cur" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          data-menu-page={item.page}
                          key={item.page}
                          onBlur={hideFlyOnBlur}
                          onFocus={(event) => {
                            showFly(event.currentTarget, item.page);
                          }}
                          onMouseEnter={(event) => {
                            showFly(event.currentTarget, item.page);
                          }}
                          onMouseLeave={() => {
                            setFly(null);
                          }}
                        >
                          <a
                            ref={
                              item === menu[0]?.items[0]?.item
                                ? firstMenuLink
                                : undefined
                            }
                            aria-current={
                              current && !subCurrent ? "page" : undefined
                            }
                            aria-expanded={flying ? true : undefined}
                            className="shell-item"
                            href={hashForPage(first)}
                            onClick={() => {
                              setFly(null);
                            }}
                            title={rail ? itemName : undefined}
                          >
                            <Icon name={item.icon} />
                            <span>{itemName}</span>
                          </a>
                          {subs.length > 1 && (
                            <button
                              aria-controls={`shell-sub-${item.page}`}
                              aria-expanded={open}
                              aria-label={tf("pages", subs.length)}
                              className="shell-subtog"
                              onClick={() => {
                                toggleSubs(item, open);
                              }}
                              type="button"
                            >
                              <Icon name="chevron" small />
                            </button>
                          )}
                          {subs.length > 1 && (
                            <div
                              className={open ? "shell-col" : "shell-col shut"}
                              hidden={!open}
                              id={`shell-sub-${item.page}`}
                            >
                              {subList(subs, "shell-sub")}
                            </div>
                          )}
                          {flying && (
                            <div className="shell-fly" style={{ top: fly.top }}>
                              <a
                                aria-current={
                                  current && !subCurrent ? "page" : undefined
                                }
                                className="shell-fly-title"
                                href={hashForPage(first)}
                                onClick={() => {
                                  setFly(null);
                                }}
                              >
                                <Icon name={item.icon} />
                                <span>{itemName}</span>
                              </a>
                              {subs.length > 1 &&
                                subList(subs, "shell-fly-subs")}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>
            );
          })}
        </nav>
        <div className="shell-me">
          <span aria-hidden="true" className="shell-avatar">
            {initials(name ?? "?")}
          </span>
          <a
            aria-current={page === "account" ? "page" : undefined}
            className="shell-me-text"
            href={hashForPage("account")}
            title={pageName("account", language)}
          >
            {name !== null ? (
              <b className="signed-in-name">{name}</b>
            ) : (
              <b>{t("signed_in")}</b>
            )}
            <small>{role ?? pageName("account", language)}</small>
          </a>
          <button
            aria-label={t("sign_out")}
            className="shell-signout"
            disabled={signOutDisabled}
            onClick={onSignOut}
            title={t("sign_out")}
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
          {search}
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
          {!ownHead && tabbedHead && (
            // Owner 13/11/2026 23:44 (iPad): on Invoices and Quotations the tabs already name
            // the page, so the title is for screen readers only, the sub-line is left out and
            // the page's buttons sit at the right end of the tab row.
            // Owner 16/11/2026: with many tabs (Ledger has 11) the page's buttons sit on their
            // own row under the tab row, so the tabs keep the whole width.
            <div
              className={`shell-head shell-head-tabbed${tabEntries.length > MANY_TABS ? " shell-head-many" : ""}${groupSwitch.length > 1 ? " shell-head-grouped" : ""}`}
            >
              <h1 className="ui-sr" id="page-title">
                {title}
              </h1>
              <div className="shell-head-sub" hidden ref={setHeadSub} />
              <nav aria-label={tabsName} className="shell-tabs">
                {tabEntries.map((tab) => (
                  <a
                    aria-current={tab.current ? "page" : undefined}
                    className="shell-tab"
                    href={hashForPage(tab.target)}
                    key={tab.key}
                    onClick={(event) => {
                      if (event.metaKey || event.ctrlKey || event.shiftKey)
                        return;
                      event.preventDefault();
                      openPageInAddress(tab.target, true);
                    }}
                  >
                    {tab.label}
                  </a>
                ))}
              </nav>
              {groupSwitch.length > 1 && (
                <nav
                  aria-label={openGroup?.label ?? title}
                  className="shell-groupsw"
                >
                  {groupSwitch.map((target) => (
                    <a
                      aria-current={target === page ? "page" : undefined}
                      href={hashForPage(target)}
                      key={target}
                      onClick={(event) => {
                        if (event.metaKey || event.ctrlKey || event.shiftKey)
                          return;
                        event.preventDefault();
                        openPageInAddress(target, true);
                      }}
                    >
                      {switchName(target, language)}
                    </a>
                  ))}
                </nav>
              )}
              <div className="shell-head-actions" ref={setHeadActions} />
            </div>
          )}
          {!ownHead && !tabbedHead && (
            <div className="shell-head">
              <div className="shell-head-text">
                <h1 id="page-title">{title}</h1>
                <div className="shell-head-sub" ref={setHeadSub} />
              </div>
              <div className="shell-head-actions" ref={setHeadActions} />
            </div>
          )}
          {!ownHead && !tabbedHead && tabs.length > 1 && (
            <nav aria-label={tabsName} className="shell-tabs">
              {tabs.map((tab) => (
                <a
                  aria-current={tab === page ? "page" : undefined}
                  className="shell-tab"
                  href={hashForPage(tab)}
                  key={tab}
                  onClick={(event) => {
                    // UI v81 (B3): changing a tab replaces the address, so Back skips it.
                    if (event.metaKey || event.ctrlKey || event.shiftKey)
                      return;
                    event.preventDefault();
                    openPageInAddress(tab, true);
                  }}
                >
                  {pageName(tab, language)}
                </a>
              ))}
            </nav>
          )}
          {notice}
          <PageHeadContext value={slots}>{children}</PageHeadContext>
        </main>
      </div>
    </div>
  );
}
