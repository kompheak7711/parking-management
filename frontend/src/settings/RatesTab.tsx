// V1-058 R7b-5: Settings → Rates and services (mock-up round 9, DL-075): the Utility Rates and the
// Services with their monthly rates. Both are effective-dated and kept forever: a change is a new
// rate from a later day, never an edit. The server asks when and how the tenants were told of a
// new Utility Rate, so the form asks too. R7b-6b adds Services (with a first rate), their names
// and type, and the Service types; R7b-6d the move-out cleaning rates by Unit Type.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type ConfigurationCapabilities,
  type ConfigurationPage,
  type ConfiguredService,
  type EffectiveConfigurationApi,
  EffectiveConfigurationConflictError,
  EffectiveConfigurationError,
  EffectiveConfigurationUnavailableError,
  type ServiceRate,
  type UtilityRate,
} from "../configurationClient";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { Problem } from "./BusinessTab";
import { CleaningRatesCard } from "./CleaningRates";
import {
  failureText,
  Field,
  focusFirst,
  nameOf,
  ServiceDialog,
  ServiceTypesCard,
  TypeDialog,
} from "./ServiceDialogs";
import {
  type CleaningSettingsApi,
  cleaningSettingsApi,
  type ServiceSetting,
  ServiceSettingsError,
  type ServiceSettings,
  type ServiceSettingsApi,
  serviceSettingsApi,
  type ServiceType,
} from "./serviceSettingsClient";
import { sst } from "./text";

export type RatesApi = Pick<
  EffectiveConfigurationApi,
  | "load"
  | "loadConfiguredServices"
  | "loadServiceRates"
  | "loadUtilityRates"
  | "createServiceRate"
  | "createUtilityRate"
>;

type Kind = UtilityRate["utility_type"];

const KINDS: readonly Kind[] = ["ELECTRICITY", "WATER"];
const KIND_TEXT = { ELECTRICITY: "k_EL", WATER: "k_WA" } as const;
const KIND_UNIT = { ELECTRICITY: "kWh", WATER: "m³" } as const;
// DL-075 and the mock-up: a new Utility Rate starts on a reading day.
const READING_DAY = 24;

interface Loaded {
  capabilities: ConfigurationCapabilities;
  services: ConfiguredService[];
  serviceRates: ServiceRate[];
  utilityRates: UtilityRate[];
}

type Open =
  | { kind: "utility" }
  | { kind: "service"; service: ConfiguredService }
  | { kind: "add_service" }
  | { kind: "edit_service"; setting: ServiceSetting }
  | { kind: "type"; type: ServiceType | null }
  | { kind: "remove_type"; type: ServiceType };

/** Every page after the first one, so no rate is missed when choosing the current one. */
async function rest<Item>(
  first: Item[],
  cursor: string | null,
  next: (cursor: string) => Promise<ConfigurationPage<Item>>,
): Promise<Item[]> {
  const items = [...first];
  const seen = new Set<string>();
  for (let at = cursor; at !== null; ) {
    // A cursor that comes back again would never end.
    if (seen.has(at)) throw new EffectiveConfigurationError();
    seen.add(at);
    const page = await next(at);
    items.push(...page.items);
    at = page.nextCursor;
  }
  return items;
}

/** "0.25000000" → "$0.25"; at least two decimals, no trailing zeros after them. */
export function ratePerUnit(value: string): string {
  const [whole = "0", part = ""] = value.split(".");
  const trimmed = part.replace(/0+$/, "").padEnd(2, "0");
  return `$${Number(whole).toLocaleString("en-US")}.${trimmed}`;
}

/** The first day after today that is the given day of a month ("2026-11-24" for 24). */
export function nextMonthDay(today: string, day: number): string {
  const [year = 0, month = 1, date = 1] = today.split("-").map(Number);
  const next =
    date < day
      ? new Date(Date.UTC(year, month - 1, day))
      : new Date(Date.UTC(year, month, day));
  return next.toISOString().slice(0, 10);
}

function dayBefore(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

/** For each Service: the rate on today, and the next one set for later. */
export function serviceNow(
  rates: readonly ServiceRate[],
  serviceId: string,
  today: string,
): { now: ServiceRate | null; next: ServiceRate | null } {
  const own = rates
    .filter((rate) => rate.property_service_id === serviceId)
    .sort((a, b) => a.effective_date.localeCompare(b.effective_date));
  let now: ServiceRate | null = null;
  let next: ServiceRate | null = null;
  for (const rate of own) {
    if (rate.effective_date <= today) now = rate;
    else next ??= rate;
  }
  return { now, next };
}

/** Utility Rates newest first, each with the day before the next one of its kind. */
export function utilityRows(
  rates: readonly UtilityRate[],
): { rate: UtilityRate; until: string | null }[] {
  const rows: { rate: UtilityRate; until: string | null }[] = [];
  for (const kind of KINDS) {
    const own = rates
      .filter((rate) => rate.utility_type === kind)
      .sort((a, b) => a.effective_date.localeCompare(b.effective_date));
    own.forEach((rate, index) => {
      const after = own[index + 1];
      rows.push({
        rate,
        until: after === undefined ? null : dayBefore(after.effective_date),
      });
    });
  }
  return rows.sort(
    (a, b) =>
      b.rate.effective_date.localeCompare(a.rate.effective_date) ||
      a.rate.utility_type.localeCompare(b.rate.utility_type),
  );
}

export function RatesTab({
  language,
  propertyId,
  active,
  api,
  services: servicesApi = serviceSettingsApi,
  cleaning = cleaningSettingsApi,
  today: fixedToday,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: RatesApi;
  /** The Services and Service types; the real server when not given. */
  services?: ServiceSettingsApi;
  /** The move-out cleaning rates; the real server when not given. */
  cleaning?: CleaningSettingsApi;
  /** For tests; otherwise today in Phnom Penh. */
  today?: string;
}) {
  const today = fixedToday ?? todayInPhnomPenh();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // "failed": the rates still show, but Services cannot be added or changed.
  const [settings, setSettings] = useState<ServiceSettings | "failed" | null>(
    null,
  );
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);
  // One key per form opening, so a retry after a lost answer is not saved twice.
  const key = useRef<{ body: string; key: string } | null>(null);
  // The id of a new Service or Service type (the client chooses it). It is kept until the
  // server confirms that record, even across closing and opening the form again, so a resend
  // after a lost answer can never add a second one: the same values answer the same record,
  // other values are refused and the lists are read again.
  const pending = useRef<{ service: string | null; type: string | null }>({
    service: null,
    type: null,
  });

  const load = useCallback((): Promise<void> => {
    if (propertyId === "") return Promise.resolve();
    const operation = ++sequence.current;
    setFailure(null);
    const read = servicesApi.read(propertyId).catch(() => "failed" as const);
    return api
      .load(propertyId)
      .then(async (snapshot) => {
        const [services, serviceRates, utilityRates] = await Promise.all([
          rest(
            snapshot.configuredServices,
            snapshot.configuredServiceNextCursor,
            (cursor) => api.loadConfiguredServices(propertyId, cursor),
          ),
          rest(snapshot.serviceRates, snapshot.serviceNextCursor, (cursor) =>
            api.loadServiceRates(propertyId, cursor),
          ),
          rest(snapshot.utilityRates, snapshot.utilityNextCursor, (cursor) =>
            api.loadUtilityRates(propertyId, cursor),
          ),
        ]);
        if (operation !== sequence.current) return;
        setLoaded({
          capabilities: snapshot.capabilities,
          services,
          serviceRates,
          utilityRates,
        });
        // The rates show without waiting for the Services read; the load ends when it lands,
        // so a form stays busy until the newest versions are in. A failed read again keeps the
        // lists read before, so an open form is not lost.
        return read.then((found) => {
          if (operation !== sequence.current) return;
          setSettings((before) =>
            found === "failed" && before !== null && before !== "failed"
              ? before
              : found,
          );
        });
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setLoaded(null);
        setFailure(
          error instanceof EffectiveConfigurationUnavailableError
            ? "not_allowed"
            : "failed",
        );
      });
  }, [api, servicesApi, propertyId]);

  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    setLoaded(null);
    setSettings(null);
    pending.current = { service: null, type: null };
    setFailure(null);
    setOpen(null);
    setProblem(null);
    setToast(null);
    setBusy(false);
  }, [propertyId]);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  function start(next: Open) {
    key.current = null;
    setProblem(null);
    setToast(null);
    setOpen(next);
  }

  function run(
    body: object,
    work: (idempotencyKey: string) => Promise<unknown>,
    done: string,
  ) {
    const asked = propertyId;
    // The same key only for the same values: a retry after a lost answer is never saved twice,
    // and changed values are a new request.
    const sent = JSON.stringify(body);
    if (key.current?.body !== sent) {
      key.current = { body: sent, key: crypto.randomUUID() };
    }
    const idempotencyKey = key.current.key;
    setBusy(true);
    setProblem(null);
    work(idempotencyKey)
      .then(
        () => {
          if (shownProperty.current !== asked) return undefined;
          setOpen(null);
          setToast({ ok: true, text: done });
          return load();
        },
        (error: unknown) => {
          if (shownProperty.current !== asked) return undefined;
          if (error instanceof EffectiveConfigurationConflictError) {
            // The form stays open with what was typed; the lists are read again, so the
            // day check sees the other rate.
            setProblem(sst(language, "rates_changed"));
            return load();
          }
          const status =
            error instanceof EffectiveConfigurationError ? error.status : null;
          if (error instanceof EffectiveConfigurationUnavailableError) {
            setProblem(sst(language, "no_tab"));
          } else if (status !== null && status < 500) {
            setProblem(sst(language, "rates_refused"));
          } else {
            setProblem(sst(language, "rates_unknown"));
          }
          return undefined;
        },
      )
      .finally(() => {
        if (shownProperty.current === asked) setBusy(false);
      });
  }

  /** The id for a new record of this kind: the same until the server confirms one. */
  function newRecordId(kind: "service" | "type"): string {
    const id = pending.current[kind] ?? crypto.randomUUID();
    pending.current[kind] = id;
    return id;
  }

  function runService(
    work: () => Promise<unknown>,
    done: string,
    adding?: "service" | "type",
  ) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    work()
      .then(
        () => {
          if (shownProperty.current !== asked) return undefined;
          if (adding !== undefined) pending.current[adding] = null;
          setOpen(null);
          setToast({ ok: true, text: done });
          return load();
        },
        (error: unknown) => {
          if (shownProperty.current !== asked) return undefined;
          const found =
            error instanceof ServiceSettingsError ? error.failure : "unknown";
          // The id stays after any other failure: an earlier send that got no answer may have
          // saved it, so sending again must never add a second record.
          if (found === "id_reused" && adding !== undefined) {
            pending.current[adding] = null;
          }
          if (
            found === "id_reused" ||
            found === "type_has_services" ||
            found === "not_found"
          ) {
            // Saved before (the list shows it now), cannot be removed, or gone (removed by
            // another person or by a send that got no answer): the form has nothing more to do.
            setOpen(null);
            setToast({ ok: false, text: failureText(language, found) });
            return load();
          }
          setProblem(failureText(language, found));
          // Someone else changed it first, or the answer was lost: read the lists again, so
          // they show what was saved.
          if (found === "out_of_date" || found === "unknown") return load();
          return undefined;
        },
      )
      .finally(() => {
        if (shownProperty.current === asked) setBusy(false);
      });
  }

  if (failure !== null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{sst(language, failure === "failed" ? "rates_failed" : "no_tab")}</p>
        {failure === "failed" && (
          <button
            className="ui-btn"
            onClick={() => {
              void load();
            }}
            type="button"
          >
            {sst(language, "retry")}
          </button>
        )}
      </div>
    );
  }
  if (loaded === null) {
    return (
      <p className="ui-muted" role="status">
        {sst(language, "rates_loading")}
      </p>
    );
  }

  const { capabilities, services, serviceRates, utilityRates } = loaded;
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };
  const serviceName = (id: string) =>
    services.find((service) => service.id === id)?.display_name ?? "";
  const ready = settings !== null && settings !== "failed" ? settings : null;
  const manageServices = ready?.can_manage === true;
  const settingOf = new Map(
    (ready?.services ?? []).map((item) => [item.service_id, item]),
  );
  const typeOf = new Map(
    (ready?.service_types ?? []).map((item) => [item.service_type_id, item]),
  );
  const history = [...serviceRates].sort(
    (a, b) =>
      serviceName(a.property_service_id).localeCompare(
        serviceName(b.property_service_id),
      ) || b.effective_date.localeCompare(a.effective_date),
  );

  return (
    <>
      <div aria-live="polite" role="status">
        {toast !== null && (
          <div className={toast.ok ? "ui-notice ok" : "ui-notice warn"}>
            <Icon name={toast.ok ? "check" : "alert"} />
            <p>{toast.text}</p>
          </div>
        )}
      </div>
      <div className="ui-stack">
        <section aria-labelledby="rates-utility" className="ui-card pad0">
          <header className="ui-chead pad">
            <h2 id="rates-utility">{sst(language, "se_util")}</h2>
            {capabilities.manage_utility_rates && (
              <button
                className="ui-btn"
                onClick={() => {
                  start({ kind: "utility" });
                }}
                type="button"
              >
                <Icon name="plus" small />
                {sst(language, "se_util_add")}
              </button>
            )}
          </header>
          {utilityRates.length === 0 ? (
            <p className="pad ui-muted">{sst(language, "util_none")}</p>
          ) : (
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{sst(language, "ro_kind")}</th>
                    <th className="r" scope="col">
                      {sst(language, "ro_rate")}
                    </th>
                    <th scope="col">{sst(language, "ro_since")}</th>
                    <th scope="col">{sst(language, "ro_until")}</th>
                    <th scope="col">{sst(language, "ro_told")}</th>
                  </tr>
                </thead>
                <tbody>
                  {utilityRows(utilityRates).map(({ rate, until }) => (
                    <tr key={rate.id}>
                      <td>{sst(language, KIND_TEXT[rate.utility_type])}</td>
                      <td className="r ui-num">
                        {ratePerUnit(rate.rate_usd_per_unit)} /{" "}
                        {KIND_UNIT[rate.utility_type]}
                      </td>
                      <td className="ui-num">{dayText(rate.effective_date)}</td>
                      <td>
                        {rate.effective_date > today ? (
                          <Chip icon="clock" tone="info">
                            {sst(language, "se_sched")}
                          </Chip>
                        ) : until === null ? (
                          <Chip icon="check" tone="ok">
                            {sst(language, "se_active")}
                          </Chip>
                        ) : (
                          <span className="ui-num">{dayText(until)}</span>
                        )}
                      </td>
                      <td>
                        <span className="ui-num">
                          {dayText(rate.notice_at.slice(0, 10))}
                        </span>
                        <span className="ui-sub2">{rate.notice_evidence}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="ui-tfoot">
            <span>{sst(language, "se_util_n")}</span>
          </div>
        </section>

        <section aria-labelledby="rates-services" className="ui-card pad0">
          <header className="ui-chead pad">
            <h2 id="rates-services">{sst(language, "se_svc")}</h2>
            {manageServices && (
              <button
                className="ui-btn"
                onClick={() => {
                  start({ kind: "add_service" });
                }}
                type="button"
              >
                <Icon name="plus" small />
                {sst(language, "sv_add")}
              </button>
            )}
          </header>
          {settings === "failed" && (
            <div className="ui-notice warn pad" role="status">
              <Icon name="alert" />
              <p>{sst(language, "sv_read_failed")}</p>
            </div>
          )}
          {services.length === 0 ? (
            <p className="pad ui-muted">{sst(language, "sv_none")}</p>
          ) : (
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{sst(language, "se_svc_name")}</th>
                    {ready !== null && (
                      <th scope="col">{sst(language, "sv_type")}</th>
                    )}
                    <th className="r" scope="col">
                      {sst(language, "sv_rate_now")}
                    </th>
                    <th scope="col">{sst(language, "sv_next")}</th>
                    {ready !== null && (
                      <th className="r" scope="col">
                        {sst(language, "sv_leases")}
                      </th>
                    )}
                    {(capabilities.manage_service_rates || manageServices) && (
                      <th scope="col">
                        <span className="ui-sr">
                          {sst(language, "actions")}
                        </span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {services.map((service) => {
                    const { now, next } = serviceNow(
                      serviceRates,
                      service.id,
                      today,
                    );
                    const setting = settingOf.get(service.id);
                    const type =
                      setting?.service_type_id == null
                        ? undefined
                        : typeOf.get(setting.service_type_id);
                    const name =
                      setting === undefined
                        ? service.display_name
                        : nameOf(language, setting);
                    return (
                      <tr key={service.id}>
                        <td>
                          <b>{name}</b>
                          {setting?.name_km != null && language !== "km" && (
                            <span className="ui-sub2" lang="km">
                              {setting.name_km}
                            </span>
                          )}
                        </td>
                        {ready !== null && (
                          <td>
                            {type === undefined
                              ? sst(language, "sv_no_type")
                              : nameOf(language, type)}
                          </td>
                        )}
                        <td className="r ui-num">
                          {now !== null ? (
                            usdFromCents(now.monthly_rate_usd_cents)
                          ) : next !== null ? (
                            <Chip icon="clock" tone="info">
                              {sst(
                                language,
                                "se_svc_not_yet",
                                dayText(next.effective_date),
                              )}
                            </Chip>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="ui-num">
                          {next === null
                            ? "—"
                            : `${usdFromCents(next.monthly_rate_usd_cents)} · ${dayText(next.effective_date)}`}
                        </td>
                        {ready !== null && (
                          <td className="r ui-num">
                            {setting?.leases_using ?? "—"}
                          </td>
                        )}
                        {(capabilities.manage_service_rates ||
                          manageServices) && (
                          <td>
                            <span className="ui-actions">
                              {manageServices && setting !== undefined && (
                                <button
                                  aria-label={`${sst(language, "cf_edit")}: ${name}`}
                                  className="ui-btn link"
                                  onClick={() => {
                                    start({ kind: "edit_service", setting });
                                  }}
                                  type="button"
                                >
                                  {sst(language, "cf_edit")}
                                </button>
                              )}
                              {capabilities.manage_service_rates && (
                                <button
                                  aria-label={`${sst(language, "sv_new")}: ${name}`}
                                  className="ui-btn link"
                                  onClick={() => {
                                    start({ kind: "service", service });
                                  }}
                                  type="button"
                                >
                                  {sst(language, "sv_new")}
                                </button>
                              )}
                            </span>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {history.length > 0 && (
            <details className="ui-hist">
              <summary>{sst(language, "sv_hist")}</summary>
              <div className="ui-tablewrap">
                <table className="ui-table">
                  <thead>
                    <tr>
                      <th scope="col">{sst(language, "se_svc_name")}</th>
                      <th className="r" scope="col">
                        {sst(language, "se_svc_rate_h")}
                      </th>
                      <th scope="col">{sst(language, "ro_since")}</th>
                      <th scope="col">{sst(language, "note_l")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((rate) => (
                      <tr key={rate.id}>
                        <td>
                          {serviceName(rate.property_service_id) ||
                            rate.display_name}
                        </td>
                        <td className="r ui-num">
                          {usdFromCents(rate.monthly_rate_usd_cents)}
                        </td>
                        <td className="ui-num">
                          {dayText(rate.effective_date)}
                        </td>
                        <td>{rate.source_memo ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <div className="ui-tfoot">
            <span>{sst(language, "se_svc_n")}</span>
          </div>
        </section>

        {ready !== null && (
          <ServiceTypesCard
            language={language}
            manage={manageServices}
            onAdd={() => {
              start({ kind: "type", type: null });
            }}
            onEdit={(type) => {
              start({ kind: "type", type });
            }}
            onRemove={(type) => {
              start({ kind: "remove_type", type });
            }}
            types={ready.service_types}
          />
        )}
        <CleaningRatesCard
          active={active}
          api={cleaning}
          language={language}
          propertyId={propertyId}
        />
      </div>

      {open?.kind === "utility" && (
        <UtilityDialog
          busy={busy}
          existing={utilityRates}
          language={language}
          onClose={closeOpen}
          onSave={(input) => {
            const body = {
              utility_type: input.kind,
              measurement_unit_code:
                input.kind === "ELECTRICITY" ? "KWH" : "M3",
              rate_usd_per_unit: input.rate,
              effective_date: input.day,
              // Noon in Phnom Penh on the day the tenants were told.
              notice_at: `${input.toldOn}T12:00:00+07:00`,
              notice_evidence: input.how,
              source_memo: null,
            };
            run(
              body,
              (idempotencyKey) =>
                api.createUtilityRate(propertyId, body, idempotencyKey),
              sst(
                language,
                "se_util_saved",
                sst(language, KIND_TEXT[input.kind]),
                dayText(input.day),
              ),
            );
          }}
          problem={problem}
          today={today}
        />
      )}
      {ready !== null &&
        (open?.kind === "add_service" || open?.kind === "edit_service") && (
          <ServiceDialog
            busy={busy}
            language={language}
            onClose={closeOpen}
            onSave={(form) => {
              if (open.kind === "edit_service") {
                // The newest read: after "someone changed this first" the next Save uses it.
                const setting =
                  settingOf.get(open.setting.service_id) ?? open.setting;
                runService(
                  () =>
                    servicesApi.changeService(propertyId, setting.service_id, {
                      name_en: form.name_en,
                      name_km: form.name_km,
                      service_type_id: form.service_type_id,
                      version: setting.version,
                    }),
                  sst(language, "sv_changed", nameOf(language, form)),
                );
                return;
              }
              if (form.first === null) return;
              const values = {
                name_en: form.name_en,
                name_km: form.name_km,
                service_type_id: form.service_type_id,
                monthly_rate_usd_cents: form.first.cents,
                starts_on: form.first.starts_on,
              };
              const serviceId = newRecordId("service");
              runService(
                () =>
                  servicesApi.addService(propertyId, {
                    service_id: serviceId,
                    ...values,
                  }),
                sst(language, "sv_added", nameOf(language, form)),
                "service",
              );
            }}
            problem={problem}
            service={open.kind === "edit_service" ? open.setting : null}
            types={ready.service_types}
            today={today}
          />
        )}
      {open?.kind === "type" && (
        <TypeDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(form) => {
            const type =
              open.type === null
                ? null
                : (typeOf.get(open.type.service_type_id) ?? open.type);
            if (type !== null) {
              runService(
                () =>
                  servicesApi.changeType(propertyId, type.service_type_id, {
                    ...form,
                    version: type.version,
                  }),
                sst(language, "sv_changed", nameOf(language, form)),
              );
              return;
            }
            const typeId = newRecordId("type");
            runService(
              () =>
                servicesApi.addType(propertyId, {
                  service_type_id: typeId,
                  ...form,
                }),
              sst(language, "sv_added", nameOf(language, form)),
              "type",
            );
          }}
          problem={problem}
          type={open.type}
        />
      )}
      {open?.kind === "remove_type" && (
        <Dialog
          actions={
            <button
              className="ui-btn danger"
              disabled={busy}
              onClick={() => {
                const type = typeOf.get(open.type.service_type_id) ?? open.type;
                runService(
                  () =>
                    servicesApi.removeType(
                      propertyId,
                      type.service_type_id,
                      type.version,
                    ),
                  sst(language, "set_removed", nameOf(language, type)),
                );
              }}
              type="button"
            >
              {sst(language, "set_remove")}
            </button>
          }
          busy={busy}
          closeLabel={sst(language, "cancel")}
          onClose={closeOpen}
          title={`${sst(language, "set_remove")} · ${nameOf(language, open.type)}`}
        >
          <p>{sst(language, "set_remove_q", nameOf(language, open.type))}</p>
          <Problem text={problem} />
        </Dialog>
      )}
      {open?.kind === "service" && (
        <ServiceRateDialog
          busy={busy}
          current={serviceNow(serviceRates, open.service.id, today).now}
          existing={serviceRates.filter(
            (rate) => rate.property_service_id === open.service.id,
          )}
          language={language}
          onClose={closeOpen}
          onSave={(input) => {
            const body = {
              property_service_id: open.service.id,
              monthly_rate_usd_cents: input.cents,
              effective_date: input.day,
              source_memo: input.note,
            };
            run(
              body,
              (idempotencyKey) =>
                api.createServiceRate(propertyId, body, idempotencyKey),
              sst(language, "sv_saved", open.service.display_name),
            );
          }}
          problem={problem}
          service={open.service}
          today={today}
        />
      )}
    </>
  );
}

function UtilityDialog({
  language,
  existing,
  today,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  existing: readonly UtilityRate[];
  today: string;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (input: {
    kind: Kind;
    rate: string;
    day: string;
    toldOn: string;
    how: string;
  }) => void;
}) {
  const [kind, setKind] = useState<Kind>("ELECTRICITY");
  const [rate, setRate] = useState("");
  const [day, setDay] = useState("");
  const [toldOn, setToldOn] = useState(today);
  const [how, setHow] = useState("");
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string | undefined> = {};
    const value = rate.trim();
    if (!/^\d{1,4}(\.\d{1,8})?$/.test(value) || Number(value) <= 0) {
      found["ur-rate"] = sst(language, "e_util_rate");
    }
    if (!isDay(day) || Number(day.slice(8)) !== READING_DAY || day <= today) {
      found["ur-day"] = sst(language, "se_e_read");
    } else if (
      existing.some(
        (other) => other.utility_type === kind && other.effective_date === day,
      )
    ) {
      found["ur-day"] = sst(language, "se_e_same");
    }
    if (!isDay(toldOn) || toldOn > today || (day !== "" && toldOn >= day)) {
      found["ur-told"] = sst(language, "e_told");
    }
    if (how.trim() === "") found["ur-how"] = sst(language, "e_told_how");
    setErrors(found);
    if (focusFirst(found, ["ur-rate", "ur-day", "ur-told", "ur-how"])) return;
    onSave({ kind, rate: value, day, toldOn, how: how.trim() });
  }

  const required = sst(language, "required");
  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "se_util_add")}
    >
      <div className="ui-field">
        <label htmlFor="ur-kind">{sst(language, "ro_kind")}</label>
        <select
          id="ur-kind"
          onChange={(event) => {
            setKind(event.currentTarget.value as Kind);
          }}
          value={kind}
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {sst(language, KIND_TEXT[option])} ({KIND_UNIT[option]})
            </option>
          ))}
        </select>
      </div>
      <div className="ui-row2">
        <Field
          error={errors["ur-rate"]}
          id="ur-rate"
          label={sst(language, "se_util_per")}
          required={required}
        >
          {(describedBy) => (
            <div className="ui-money">
              <span aria-hidden="true">$</span>
              <input
                aria-describedby={describedBy}
                aria-invalid={errors["ur-rate"] !== undefined}
                autoComplete="off"
                id="ur-rate"
                inputMode="decimal"
                onChange={(event) => {
                  setRate(event.currentTarget.value);
                }}
                value={rate}
              />
            </div>
          )}
        </Field>
        <Field
          error={errors["ur-day"]}
          help={sst(language, "se_util_day_help")}
          id="ur-day"
          label={sst(language, "se_starts")}
          required={required}
        >
          {(describedBy) => (
            <DateInput
              language={language}
              describedBy={describedBy}
              invalid={errors["ur-day"] !== undefined}
              id="ur-day"
              min={nextMonthDay(today, READING_DAY)}
              onChange={(value) => {
                setDay(value);
              }}
              value={day}
            />
          )}
        </Field>
      </div>
      <Field
        error={errors["ur-told"]}
        help={sst(language, "told_h")}
        id="ur-told"
        label={sst(language, "told_on")}
        required={required}
      >
        {(describedBy) => (
          <DateInput
            language={language}
            describedBy={describedBy}
            invalid={errors["ur-told"] !== undefined}
            id="ur-told"
            max={today}
            onChange={(value) => {
              setToldOn(value);
            }}
            value={toldOn}
          />
        )}
      </Field>
      <Field
        error={errors["ur-how"]}
        help={sst(language, "told_how_h")}
        id="ur-how"
        label={sst(language, "told_how")}
        required={required}
      >
        {(describedBy) => (
          <input
            aria-describedby={describedBy}
            aria-invalid={errors["ur-how"] !== undefined}
            autoComplete="off"
            id="ur-how"
            maxLength={500}
            onChange={(event) => {
              setHow(event.currentTarget.value);
            }}
            value={how}
          />
        )}
      </Field>
      <p className="ui-small ui-muted">{sst(language, "se_util_n")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

function ServiceRateDialog({
  language,
  service,
  current,
  existing,
  today,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  service: ConfiguredService;
  current: ServiceRate | null;
  existing: readonly ServiceRate[];
  today: string;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (input: { cents: number; day: string; note: string | null }) => void;
}) {
  const [amount, setAmount] = useState(
    current === null ? "" : (current.monthly_rate_usd_cents / 100).toFixed(2),
  );
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string | undefined> = {};
    const value = amount.trim();
    const cents = /^\d{1,7}(\.\d{1,2})?$/.test(value)
      ? Math.round(Number(value) * 100)
      : 0;
    if (cents <= 0) found["sr-amt"] = sst(language, "err_amount");
    if (!(isDay(day) && day.endsWith("-01")) || day <= today) {
      found["sr-day"] = sst(language, "se_e_first");
    } else if (existing.some((rate) => rate.effective_date === day)) {
      found["sr-day"] = sst(language, "se_e_same");
    }
    setErrors(found);
    if (focusFirst(found, ["sr-amt", "sr-day"])) return;
    onSave({ cents, day, note: note.trim() || null });
  }

  const required = sst(language, "required");
  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={`${sst(language, "sv_new")} · ${service.display_name}`}
    >
      <div className="ui-row2">
        <Field
          error={errors["sr-amt"]}
          help={sst(language, "sv_rate_h")}
          id="sr-amt"
          label={sst(language, "se_svc_rate_h")}
          required={required}
        >
          {(describedBy) => (
            <div className="ui-money">
              <span aria-hidden="true">$</span>
              <input
                aria-describedby={describedBy}
                aria-invalid={errors["sr-amt"] !== undefined}
                autoComplete="off"
                id="sr-amt"
                inputMode="decimal"
                onChange={(event) => {
                  setAmount(event.currentTarget.value);
                }}
                value={amount}
              />
            </div>
          )}
        </Field>
        <Field
          error={errors["sr-day"]}
          help={sst(language, "set_from_help")}
          id="sr-day"
          label={sst(language, "se_starts")}
          required={required}
        >
          {(describedBy) => (
            <DateInput
              language={language}
              describedBy={describedBy}
              invalid={errors["sr-day"] !== undefined}
              id="sr-day"
              min={nextMonthDay(today, 1)}
              onChange={(value) => {
                setDay(value);
              }}
              value={day}
            />
          )}
        </Field>
      </div>
      <Field
        id="sr-note"
        label={sst(language, "note_l")}
        required={sst(language, "optional")}
        error={undefined}
      >
        {(describedBy) => (
          <input
            aria-describedby={describedBy}
            autoComplete="off"
            id="sr-note"
            maxLength={500}
            onChange={(event) => {
              setNote(event.currentTarget.value);
            }}
            value={note}
          />
        )}
      </Field>
      <Problem text={problem} />
    </Dialog>
  );
}
