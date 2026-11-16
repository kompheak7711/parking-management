// V1-058 R7b: Settings (DESIGN.md "Settings", mock-up round 9): five tabs, each shown only to
// a person who may use it. System health is rebuilt here (R7b-1); a tab not rebuilt yet keeps
// the earlier forms, folded, until its own step.

import "../shell/screens.css";

import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { momentText, todayInPhnomPenh } from "../shell/format";
import { SiteCalendars } from "../shortstays/SiteCalendars";
import {
  type ShortStaysApi,
  shortStaysApi,
} from "../shortstays/shortStaysClient";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage, pageName } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip, SubTabPanel, SubTabs, useSubTab } from "../shell/ui";
import type { ReauthenticationRequest } from "../authClient";
import type { Language } from "../signInText";
import {
  type HealthApi,
  HealthNotAllowedError,
  type HealthRecord,
  type HealthStatus,
} from "./healthClient";
import { type SettingsTextKey, sst } from "./text";
import { type BusinessApi, BusinessTab } from "./BusinessTab";
import { type RatesApi, RatesTab } from "./RatesTab";
import { type SetupApi, UnitSetupTab } from "./UnitSetupTab";
import { AccessHistory } from "./AccessHistory";
import { type StaffLookup, type UsersApi, UsersTab } from "./UsersTab";
import type { RolesApi } from "../access/rolesClient";
import { TabHead } from "../shell/layouts";

export type SettingsTab =
  | "business"
  | "rates"
  | "services"
  | "units"
  | "users"
  | "sites"
  | "health";

/** UI v81: the sub-tabs of the Users and access page (moved out of Settings). */
export type AccessTab = "users" | "roles" | "signin" | "history";

const ACCESS_TAB_IDS: readonly AccessTab[] = [
  "users",
  "roles",
  "signin",
  "history",
];
const ACCESS_TABS: readonly { tab: AccessTab; label: SettingsTextKey }[] = [
  { tab: "users", label: "ac_users" },
  { tab: "roles", label: "ac_roles" },
  { tab: "signin", label: "ac_signin" },
  { tab: "history", label: "ac_history" },
];

const TABS: readonly {
  tab: SettingsTab;
  label: SettingsTextKey;
  icon: ShellIcon;
  needs: readonly string[];
}[] = [
  {
    tab: "business",
    label: "se_tab_biz",
    icon: "settings",
    needs: ["settings.manage"],
  },
  {
    tab: "rates",
    label: "se_tab_rates",
    icon: "payments",
    needs: ["settings.manage"],
  },
  {
    tab: "services",
    label: "se_tab_msvc",
    icon: "list",
    needs: ["settings.manage"],
  },
  {
    tab: "units",
    label: "se_tab_units",
    icon: "units",
    needs: ["settings.manage"],
  },
  // Owner 13/11/2026 (Leasing thread): the booking sites' calendar links, set up once, moved
  // here from Short stays. For the Owner and the Manager, as before.
  {
    tab: "sites",
    label: "se_tab_sites",
    icon: "calendar",
    needs: ["short_stays.approve"],
  },
  {
    tab: "health",
    label: "se_tab_health",
    icon: "check",
    needs: ["operations.status.read"],
  },
];

export interface SettingsPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  unitApi: SetupApi;
  capabilities: ReadonlySet<string> | null;
  healthApi: HealthApi;
  usersApi: UsersApi;
  rolesApi: RolesApi;
  businessApi: BusinessApi;
  ratesApi: RatesApi;
  /** The employee list, for the employee line of each app user (HRIS phase 6). */
  staff?: StaffLookup;
  /** The signed-in person. */
  myUserId: string | null;
  /** The password and sign-in code again, for an action that changes who may use the app. */
  reauthenticate: (request: ReauthenticationRequest) => Promise<void>;
  /** The earlier forms of the tabs not rebuilt yet (English only). */
  earlier: Partial<Record<SettingsTab, ReactNode>>;
  /** UI v81: "access" draws the Users and access page instead of Settings. */
  mode?: "settings" | "access";
  /** These screens are a test app (not the real install): System health says so calmly. */
  testApp?: boolean;
  /** The Booking sites tab (tests pass a fake). */
  stayApi?: ShortStaysApi;
}

function Earlier({
  language,
  note,
  children,
}: {
  language: Language;
  note: SettingsTextKey;
  children: ReactNode;
}) {
  return (
    <>
      <div className="ui-notice info" role="note">
        <Icon name="info" />
        <p>{sst(language, note)}</p>
      </div>
      <details className="ui-records">
        <summary lang={language}>
          <span className="ui-records-title">{sst(language, "earlier")}</span>
        </summary>
        <div lang="en">{children}</div>
      </details>
    </>
  );
}

/** The server's note that this computer has no health records (operations_status_api.py). */
const NOT_SET_UP = "operations_status_not_set_up";

/** "Not yet", or the time of the last success, or when it last failed. */
function recordText(language: Language, record: HealthRecord | null): string {
  if (record === null) return sst(language, "never");
  const success = record.last_success_at ?? null;
  if (record.last_outcome === "failed") {
    return sst(
      language,
      "failed_at",
      momentText(record.last_attempt_at ?? success),
    );
  }
  return success === null
    ? sst(language, "never")
    : sst(language, "ok_at", momentText(success));
}

function HealthTab({
  language,
  active,
  api,
  testApp,
}: {
  language: Language;
  active: boolean;
  api: HealthApi;
  testApp: boolean;
}) {
  const [status, setStatus] = useState<HealthStatus | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailure(null);
    api
      .status()
      .then((loaded) => {
        if (operation === sequence.current) setStatus(loaded);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        // An old answer could say "Healthy" about a computer that is not any more.
        setStatus(null);
        setFailure(
          error instanceof HealthNotAllowedError ? "not_allowed" : "failed",
        );
      });
  }, [api]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (failure !== null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>
          {sst(language, failure === "failed" ? "health_failed" : "no_tab")}
        </p>
        {failure === "failed" && (
          <button className="ui-btn" onClick={load} type="button">
            {sst(language, "retry")}
          </button>
        )}
      </div>
    );
  }
  if (status === null) {
    return (
      <p className="ui-muted" role="status">
        {sst(language, "health_loading")}
      </p>
    );
  }

  // Owner 12/11/2026: on a test computer the health records are not set up, and that is normal:
  // the real install sets them up. There the page says so calmly instead of "Needs attention".
  // `testApp` is the screens' own label (the "DEVELOPMENT" mark in the menu): the local server
  // always calls itself "production". On the real computer the same note still needs attention.
  const testComputer =
    testApp && status.warnings.some((warning) => warning.code === NOT_SET_UP);
  const warnings = testComputer
    ? status.warnings.filter((warning) => warning.code !== NOT_SET_UP)
    : status.warnings;
  const healthy = status.database === "ok" && warnings.length === 0;
  const critical = warnings.some((warning) => warning.critical);
  const time = (value: string | null) =>
    value === null ? sst(language, "never") : momentText(value);
  const rows: [SettingsTextKey, string][] = [
    ["se_version", status.build_version ?? "—"],
    [
      "se_db",
      sst(
        language,
        status.database === "ok"
          ? "db_ok"
          : status.database === "unavailable"
            ? "db_down"
            : "db_none",
      ),
    ],
    [
      "se_migration",
      status.schema_revision ??
        status.migration?.revision ??
        status.migration?.schema_revision ??
        "—",
    ],
    ["se_backup", recordText(language, status.backup)],
    [
      "offsite",
      sst(
        language,
        "offsite_v",
        recordText(language, status.offhost_daily),
        recordText(language, status.offhost_weekly),
      ),
    ],
    ["restore", recordText(language, status.restore_test)],
    ["se_last_bill", time(status.scheduled_jobs.billing_last_success_at)],
    [
      "se_last_exp",
      time(status.scheduled_jobs.reservation_expiration_last_success_at),
    ],
    [
      "alerts",
      !status.telegram.configured
        ? sst(language, "alerts_off")
        : status.telegram.last_attempt_at === null
          ? sst(language, "alerts_on_never")
          : sst(
              language,
              "alerts_on",
              momentText(status.telegram.last_attempt_at),
            ),
    ],
    ["last_check", time(status.last_check_at)],
  ];

  return (
    <>
      <section aria-labelledby="settings-health" className="ui-card">
        <header className="ui-chead">
          <h2 id="settings-health">{sst(language, "se_health")}</h2>
          {healthy && testComputer ? (
            <Chip icon="info" tone="info">
              {sst(language, "health_test")}
            </Chip>
          ) : healthy ? (
            <Chip icon="check" tone="ok">
              {sst(language, "se_ok")}
            </Chip>
          ) : (
            <Chip icon="alert" tone={critical ? "err" : "warn"}>
              {sst(language, "se_warn")}
            </Chip>
          )}
        </header>
        <dl className="ui-kv ui-is">
          {rows.map(([label, value]) => (
            <Fragment key={label}>
              <dt>{sst(language, label)}</dt>
              <dd className="ui-num">{value}</dd>
            </Fragment>
          ))}
        </dl>
        <p className="ui-small ui-muted">
          {sst(language, "checked_at", momentText(status.generated_at))}
        </p>
      </section>
      {testComputer && (
        <div className="ui-notice info" role="note">
          <Icon name="info" />
          <p>{sst(language, "health_test_n")}</p>
        </div>
      )}
      {warnings.length > 0 && (
        <section aria-labelledby="settings-health-warn" className="ui-card">
          <h2 id="settings-health-warn">{sst(language, "warn_h")}</h2>
          {language === "km" && (
            <p className="ui-small ui-muted">{sst(language, "warn_lang")}</p>
          )}
          <ul className="ui-apps">
            {warnings.map((warning) => (
              <li key={warning.code}>
                <span lang="en">{warning.message}</span>
                <Chip icon="alert" tone={warning.critical ? "err" : "warn"}>
                  {sst(language, "se_warn")}
                </Chip>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="ui-notice info" role="note">
        <Icon name="info" />
        <p>{sst(language, "se_health_n")}</p>
      </div>
    </>
  );
}

export function SettingsPage({
  language,
  propertyId,
  active,
  unitApi,
  capabilities,
  healthApi,
  usersApi,
  rolesApi,
  businessApi,
  ratesApi,
  staff,
  myUserId,
  reauthenticate,
  earlier,
  mode = "settings",
  testApp = false,
  stayApi = shortStaysApi,
}: SettingsPageProps) {
  const detail = useHashDetail(mode === "access" ? "access" : "settings");
  const [accessTab] = useSubTab<AccessTab>(ACCESS_TAB_IDS, "users");
  // UI v81: Users and sign-in moved to its own menu item; an old address goes there.
  useEffect(() => {
    if (mode === "settings" && active && detail === "users")
      window.location.replace(hashForPage("access"));
  }, [mode, active, detail]);

  const allowed = TABS.filter(
    (item) =>
      capabilities === null ||
      item.needs.some((capability) => capabilities.has(capability)),
  );
  const tab =
    allowed.find((item) => item.tab === detail)?.tab ?? allowed[0]?.tab;
  // Every tab but Health reads the open Property.
  const noProperty = propertyId === "" && tab !== undefined && tab !== "health";

  return (
    <>
      {mode === "access" && (
        <AccessPage
          active={active}
          language={language}
          myUserId={myUserId}
          propertyId={propertyId}
          reauthenticate={reauthenticate}
          rolesApi={rolesApi}
          staff={
            capabilities === null || capabilities.has("hr.employees.read")
              ? staff
              : undefined
          }
          usersApi={usersApi}
        />
      )}
      {/* The earlier forms stay mounted, as before, so what was typed survives a page change
          (open question in 01_UI_AUDIT_REPORT.md). Administration review fix 10 (owner
          13/11/2026): the new tabs do everything they did, so they show only at the foot of the
          History tab, closed, until the old screens are removed. */}
      {earlier.users !== undefined && (
        <div hidden={mode !== "access" || accessTab !== "history"}>
          <Earlier language={language} note="earlier_kept">
            {earlier.users}
          </Earlier>
        </div>
      )}
      {/* One wrapper, so the earlier forms stay mounted; "ui-settings" keeps the normal space
        between its cards and notes (owner 12/11/2026). */}
      <div className="ui-settings" hidden={mode === "access"}>
        <OwnHead
          own={mode === "settings"}
          tabs={
            allowed.length > 1 && (
              <nav aria-label={sst(language, "tabs")} className="ui-subtabs">
                {allowed.map((item) => (
                  <a
                    aria-current={item.tab === tab ? "page" : undefined}
                    href={hashForPage("settings", item.tab)}
                    key={item.tab}
                  >
                    <Icon name={item.icon} small />
                    {sst(language, item.label)}
                  </a>
                ))}
              </nav>
            )
          }
          title={pageName("settings", language)}
        >
          {tab === undefined && (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{sst(language, "no_tab")}</p>
            </div>
          )}
          {tab === "health" && (
            <HealthTab
              active={active}
              api={healthApi}
              language={language}
              testApp={testApp}
            />
          )}
          {tab !== undefined && tab !== "health" && (
            <p className="ui-small ui-muted">{sst(language, "set_who")}</p>
          )}
          {noProperty && (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{sst(language, "no_property")}</p>
            </div>
          )}
          {tab === "sites" && !noProperty && (
            <SiteCalendars
              api={stayApi}
              key={propertyId}
              language={language}
              propertyId={propertyId}
              today={todayInPhnomPenh()}
            />
          )}
          {tab === "units" && !noProperty && (
            <UnitSetupTab
              active={active}
              api={unitApi}
              language={language}
              propertyId={propertyId}
            />
          )}
          {tab === "business" && !noProperty && (
            <BusinessTab
              active={active}
              api={businessApi}
              language={language}
              propertyId={propertyId}
            />
          )}
          {(tab === "rates" || tab === "services") && !noProperty && (
            <RatesTab
              active={active}
              api={ratesApi}
              language={language}
              part={tab === "rates" ? "utility" : "services"}
              propertyId={propertyId}
            />
          )}
          {/* The earlier forms stay mounted, so what was typed in one survives a tab change; each
          checks its own rights with the server. */}
          {TABS.map(
            (item) =>
              earlier[item.tab] !== undefined && (
                <div
                  className="ui-earlier"
                  hidden={item.tab !== tab}
                  key={item.tab}
                >
                  <Earlier
                    language={language}
                    note={
                      item.tab === "business"
                        ? "earlier_same"
                        : item.tab === "rates"
                          ? "earlier_rates"
                          : "earlier_note"
                    }
                  >
                    {earlier[item.tab]}
                  </Earlier>
                </div>
              ),
          )}
        </OwnHead>
      </div>
    </>
  );
}

/**
 * Administration review fix 1 (owner 13/11/2026): Settings and Users and access take the same
 * head as Invoices and Utilities: the tab row is the head, with no title line and no sub-line.
 * `own` is false for the copy of Settings that sits hidden on the Users and access page, so it
 * never takes that page's head.
 */
function OwnHead({
  own,
  title,
  tabs,
  children,
}: {
  own: boolean;
  title: string;
  tabs: ReactNode;
  children: ReactNode;
}) {
  if (!own) return <>{children}</>;
  return (
    <TabHead tabs={tabs} title={title}>
      {children}
    </TabHead>
  );
}

/** UI v81 (B4): Users and access, its own menu item: Users, Roles, Sign-in and security, History. */
function AccessPage({
  language,
  propertyId,
  active,
  usersApi,
  rolesApi,
  staff,
  myUserId,
  reauthenticate,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  usersApi: UsersApi;
  rolesApi: RolesApi;
  staff?: StaffLookup;
  myUserId: string | null;
  reauthenticate: (request: ReauthenticationRequest) => Promise<void>;
}) {
  // Administration review 13/11/2026: follow the address, so the side menu's sub-items
  // (Roles, Sign-in and security, History) switch the tab when this page is already open.
  const [tab, setTab] = useSubTab<AccessTab>(ACCESS_TAB_IDS, "users");
  return (
    <TabHead
      tabs={
        <SubTabs
          current={tab}
          idPrefix="access"
          label={sst(language, "ac_tabs")}
          onChange={(id) => {
            setTab(id as AccessTab);
          }}
          tabs={ACCESS_TABS.map((item) => ({
            id: item.tab,
            label: sst(language, item.label),
          }))}
        />
      }
      title={pageName("access", language)}
    >
      {propertyId === "" ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{sst(language, "no_property")}</p>
        </div>
      ) : (
        <SubTabPanel id={tab} idPrefix="access">
          {tab === "history" ? (
            <AccessHistory
              active={active}
              api={usersApi}
              language={language}
              myUserId={myUserId}
              propertyId={propertyId}
            />
          ) : (
            <UsersTab
              active={active}
              api={usersApi}
              language={language}
              myUserId={myUserId}
              part={tab}
              propertyId={propertyId}
              reauthenticate={reauthenticate}
              rolesApi={rolesApi}
              staff={staff}
            />
          )}
        </SubTabPanel>
      )}
    </TabHead>
  );
}
