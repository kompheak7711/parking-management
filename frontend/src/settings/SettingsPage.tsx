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

import { momentText } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip } from "../shell/ui";
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
import { type UsersApi, UsersTab } from "./UsersTab";

export type SettingsTab = "business" | "rates" | "units" | "users" | "health";

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
    tab: "units",
    label: "se_tab_units",
    icon: "units",
    needs: ["settings.manage"],
  },
  {
    tab: "users",
    label: "se_tab_users",
    icon: "customers",
    needs: ["identity.manage_access"],
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
  businessApi: BusinessApi;
  ratesApi: RatesApi;
  /** The signed-in person. */
  myUserId: string | null;
  /** The password and sign-in code again, for an action that changes who may use the app. */
  reauthenticate: (request: ReauthenticationRequest) => Promise<void>;
  /** The earlier forms of the tabs not rebuilt yet (English only). */
  earlier: Partial<Record<SettingsTab, ReactNode>>;
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
}: {
  language: Language;
  active: boolean;
  api: HealthApi;
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

  const healthy = status.database === "ok" && status.warnings.length === 0;
  const critical = status.warnings.some((warning) => warning.critical);
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
          {healthy ? (
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
      {status.warnings.length > 0 && (
        <section aria-labelledby="settings-health-warn" className="ui-card">
          <h2 id="settings-health-warn">{sst(language, "warn_h")}</h2>
          {language === "km" && (
            <p className="ui-small ui-muted">{sst(language, "warn_lang")}</p>
          )}
          <ul className="ui-apps">
            {status.warnings.map((warning) => (
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
  businessApi,
  ratesApi,
  myUserId,
  reauthenticate,
  earlier,
}: SettingsPageProps) {
  const detail = useHashDetail("settings");
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
      <div className="ui-head">
        <p>{sst(language, "se_sub")}</p>
      </div>
      {allowed.length > 1 && (
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
      )}
      {tab === undefined && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{sst(language, "no_tab")}</p>
        </div>
      )}
      {tab === "health" && (
        <HealthTab active={active} api={healthApi} language={language} />
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
      {tab === "rates" && !noProperty && (
        <RatesTab
          active={active}
          api={ratesApi}
          language={language}
          propertyId={propertyId}
        />
      )}
      {tab === "users" && !noProperty && (
        <UsersTab
          active={active}
          api={usersApi}
          language={language}
          myUserId={myUserId}
          propertyId={propertyId}
          reauthenticate={reauthenticate}
        />
      )}
      {/* The earlier forms stay mounted, so what was typed in one survives a tab change; each
          checks its own rights with the server. */}
      {TABS.map(
        (item) =>
          earlier[item.tab] !== undefined && (
            <div hidden={item.tab !== tab} key={item.tab}>
              <Earlier
                language={language}
                note={
                  item.tab === "users"
                    ? "earlier_kept"
                    : item.tab === "business"
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
    </>
  );
}
