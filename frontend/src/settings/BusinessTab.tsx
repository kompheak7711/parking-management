// V1-058 R7b-4: Settings → Business (mock-up round 9, DL-075): the Property, the billing
// calendar, Reservations, Payment Methods, the riel exchange rate and the document numbers. The
// server stores the Property name and address, the Payment Methods and the days after issue for
// other Invoices; the other values follow the business rules until a later server step stores
// them (DL-075 "Build in"), so they show with "Set by the business rules".

import {
  type FormEvent,
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  EffectiveConfigurationApi,
  ExchangeRate,
} from "../configurationClient";
import {
  type DueDaysApi,
  type DueDaysSetting,
  InvoiceClientError,
} from "../invoiceClient";
import {
  type PaymentMethodConfiguration,
  type PropertyBusinessConfiguration,
  type PropertyConfigurationApi,
  PropertyConfigurationError,
  PropertyConfigurationUnavailableError,
  PropertySavedReadFailedError,
} from "../propertyClient";
import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import { allPages } from "../units/unitsData";
import { type SettingsTextKey, sst } from "./text";

export interface BusinessApi {
  property: PropertyConfigurationApi;
  dueDays: DueDaysApi;
  units: Pick<UnitApi, "list">;
  /** The riel rate comes from the confirmed exchange rates. */
  rates: Pick<EffectiveConfigurationApi, "load">;
}

// DL-075 defaults, kept by the business rules until the server stores them.
const READING_DAY = 24;
const ISSUE_DAY = 25;
const DUE_DAY = 5;
const LATE_PERCENT = 10;
const RESERVATION_DAYS = 21;
const EXTENSION_DAYS = 14;
const SUGGESTED_DEPOSIT_PERCENT = 20;

interface Loaded {
  property: PropertyBusinessConfiguration;
  dueDays: DueDaysSetting;
  units: number | null;
  /** undefined: could not be read; null: none yet. */
  rate: ExchangeRate | null | undefined;
}

type Open =
  | { kind: "property" }
  | { kind: "days" }
  | { kind: "method"; method: PaymentMethodConfiguration | null };

function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv ui-is">
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function Card({
  id,
  title,
  action,
  children,
}: {
  id: string;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="ui-card">
      <header className="ui-chead">
        <h2 id={id}>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export function FieldError({ id, text }: { id: string; text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" id={id} role="alert">
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

export function Problem({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{text}</p>
    </div>
  );
}

/** A new method's code: its English name in capitals, A to Z, 0 to 9 and _, not taken yet. */
export function methodCode(
  name: string,
  methods: readonly PaymentMethodConfiguration[],
): string {
  const base =
    name
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 40) || "METHOD";
  const taken = new Set(methods.map((method) => method.code));
  let code = base;
  for (let n = 2; taken.has(code); n++) code = `${base}_${String(n)}`;
  return code;
}

function rielText(value: number): string {
  return value.toLocaleString("en-US");
}

export function BusinessTab({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: BusinessApi;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);

  const load = useCallback((): Promise<void> => {
    if (propertyId === "") return Promise.resolve();
    const operation = ++sequence.current;
    setFailure(null);
    return Promise.all([
      api.property.load(propertyId),
      api.dueDays.get(propertyId),
      allPages(async (cursor) =>
        api.units.list(propertyId, cursor === undefined ? {} : { cursor }),
      )
        .then((units) => units.length)
        .catch(() => null),
      api.rates
        .load(propertyId)
        .then((snapshot) =>
          snapshot.exchangeRates.reduce<ExchangeRate | null>(
            (latest, rate) =>
              latest === null || rate.applicable_at > latest.applicable_at
                ? rate
                : latest,
            null,
          ),
        )
        .catch(() => undefined),
    ])
      .then(([property, dueDays, units, rate]) => {
        if (operation !== sequence.current) return;
        setLoaded({ property, dueDays, units, rate });
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setLoaded(null);
        setFailure(
          error instanceof PropertyConfigurationUnavailableError ||
            (error instanceof InvoiceClientError && error.status === 403)
            ? "not_allowed"
            : "failed",
        );
      });
  }, [api, propertyId]);

  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    setLoaded(null);
    setFailure(null);
    setOpen(null);
    setProblem(null);
    setToast(null);
    setBusy(false);
  }, [propertyId]);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  function run(work: () => Promise<unknown>, done: string) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    // Busy stays on until the new versions are read, so a quick second save
    // never sends an old version.
    const saved = () => {
      if (shownProperty.current !== asked) return undefined;
      setOpen(null);
      setToast({ ok: true, text: done });
      return load();
    };
    work()
      .then(saved, (error: unknown) => {
        if (shownProperty.current !== asked) return undefined;
        if (error instanceof PropertySavedReadFailedError) return saved();
        const status =
          error instanceof PropertyConfigurationError ||
          error instanceof InvoiceClientError
            ? error.status
            : null;
        if (status === 409 || status === 412) {
          // The form held the old version, so it closes; everything is read again.
          setOpen(null);
          setToast({ ok: false, text: sst(language, "biz_changed") });
          return load();
        }
        if (
          error instanceof PropertyConfigurationUnavailableError ||
          status === 403
        ) {
          setProblem(sst(language, "no_tab"));
        } else if (status === 422) {
          setProblem(sst(language, "refused"));
        } else {
          setProblem(sst(language, "unknown"));
          return load();
        }
        return undefined;
      })
      .finally(() => {
        if (shownProperty.current === asked) setBusy(false);
      });
  }

  if (failure !== null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{sst(language, failure === "failed" ? "biz_failed" : "no_tab")}</p>
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
        {sst(language, "biz_loading")}
      </p>
    );
  }

  const { property, dueDays, units, rate } = loaded;
  const fixed = (
    <Chip icon="lock" tone="neutral">
      {sst(language, "se_fixed")}
    </Chip>
  );
  const editButton = (label: SettingsTextKey, next: Open, name: string) => (
    <button
      aria-label={`${sst(language, label)}: ${name}`}
      className="ui-btn"
      onClick={() => {
        setProblem(null);
        setToast(null);
        setOpen(next);
      }}
      type="button"
    >
      {label === "pm_add" && <Icon name="plus" small />}
      {sst(language, label)}
    </button>
  );
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };
  const methods = property.payment_methods;

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
      <div className="ui-split">
        <div className="ui-stack">
          <Card
            action={editButton(
              "se_edit",
              { kind: "property" },
              sst(language, "se_prop"),
            )}
            id="biz-property"
            title={sst(language, "se_prop")}
          >
            <Rows
              rows={[
                [sst(language, "se_prop_name"), property.name],
                [
                  sst(language, "address"),
                  property.address_text ?? (
                    <span className="ui-muted">
                      {sst(language, "no_address")}
                    </span>
                  ),
                ],
                [
                  sst(language, "se_units"),
                  <span className="ui-num" key="units">
                    {units ?? "—"}
                  </span>,
                ],
                [
                  sst(language, "se_tz"),
                  <>
                    <span lang="en">Asia/Phnom_Penh (UTC+7)</span>
                    <span className="ui-sub2">{sst(language, "se_tz_n")}</span>
                  </>,
                ],
                [sst(language, "se_lang"), sst(language, "se_lang_v")],
              ]}
            />
          </Card>
          <Card
            action={editButton(
              "se_edit",
              { kind: "days" },
              sst(language, "se_misc_due"),
            )}
            id="biz-billing"
            title={sst(language, "se_billing")}
          >
            <Rows
              rows={[
                [
                  sst(language, "se_read_day"),
                  <>
                    <span className="ui-num">
                      {sst(language, "day_n", READING_DAY)}
                    </span>{" "}
                    {fixed}
                  </>,
                ],
                [
                  sst(language, "se_issue_day"),
                  <>
                    <span className="ui-num">
                      {sst(language, "day_n", ISSUE_DAY)}
                    </span>{" "}
                    {fixed}
                  </>,
                ],
                [
                  sst(language, "se_due_day"),
                  <>
                    <span className="ui-num">
                      {sst(language, "day_n", DUE_DAY)}
                    </span>{" "}
                    {fixed}
                  </>,
                ],
                [
                  sst(language, "se_misc_due"),
                  sst(language, "cal_misc_v", dueDays.one_time_charge_due_days),
                ],
                [
                  sst(language, "se_late"),
                  <>
                    {sst(language, "late_v", LATE_PERCENT)} {fixed}
                  </>,
                ],
              ]}
            />
            <p className="ui-small ui-muted">
              {sst(language, "misc_note")} {sst(language, "fixed_note")}
            </p>
          </Card>
          <Card id="biz-reservations" title={sst(language, "se_res")}>
            <Rows
              rows={[
                [
                  sst(language, "se_res_days"),
                  sst(language, "rs_days_v", RESERVATION_DAYS),
                ],
                [
                  sst(language, "se_res_ext"),
                  sst(language, "rs_ext_v", EXTENSION_DAYS),
                ],
                [
                  sst(language, "se_res_dep"),
                  sst(language, "rs_dep_v", SUGGESTED_DEPOSIT_PERCENT),
                ],
              ]}
            />
            <p className="ui-small ui-muted">{fixed}</p>
          </Card>
        </div>
        <div className="ui-stack">
          <Card
            action={editButton(
              "pm_add",
              { kind: "method", method: null },
              sst(language, "se_methods"),
            )}
            id="biz-methods"
            title={sst(language, "se_methods")}
          >
            <ul className="ui-apps">
              {methods.map((method) => (
                <li key={method.code}>
                  <span>
                    {method.display_name}
                    <small className="ui-num" lang="en">
                      {method.code}
                    </small>
                  </span>
                  <span className="ui-actions">
                    {method.accepted ? (
                      <Chip icon="check" tone="ok">
                        {sst(language, "se_active")}
                      </Chip>
                    ) : (
                      <Chip tone="neutral">{sst(language, "pm_off")}</Chip>
                    )}
                    <button
                      aria-label={`${sst(language, "se_edit")}: ${method.display_name}`}
                      className="ui-btn link"
                      onClick={() => {
                        setProblem(null);
                        setToast(null);
                        setOpen({ kind: "method", method });
                      }}
                      type="button"
                    >
                      {sst(language, "se_edit")}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <p className="ui-small ui-muted">{sst(language, "pm_note")}</p>
          </Card>
          <Card id="biz-fx" title={sst(language, "se_fx")}>
            {rate === undefined ? (
              <p className="ui-muted">{sst(language, "fx_cannot")}</p>
            ) : rate === null ? (
              <p className="ui-muted">{sst(language, "fx_none")}</p>
            ) : (
              <>
                <p className="ui-num">
                  <b>
                    {sst(
                      language,
                      "fx_last",
                      rielText(rate.system_rate_khr_per_usd),
                    )}
                  </b>
                </p>
                <p className="ui-small ui-muted">
                  {sst(
                    language,
                    rate.rate_source === "ABA_AUTOMATIC"
                      ? "fx_auto"
                      : "fx_hand_v",
                    momentText(rate.applicable_at),
                  )}
                </p>
              </>
            )}
            <p className="ui-small ui-muted">{sst(language, "fx_note")}</p>
          </Card>
          <Card id="biz-numbers" title={sst(language, "se_numbers")}>
            <Rows
              rows={[
                [
                  sst(language, "se_inv_no"),
                  sst(language, "no_v2", "INV", "INV260001"),
                ],
                [
                  sst(language, "se_rcp_no"),
                  sst(language, "no_v2", "RCP", "RCP260001"),
                ],
                [
                  sst(language, "se_rfd_no"),
                  sst(language, "no_v2", "RFD", "RFD260001"),
                ],
              ]}
            />
            <p className="ui-small ui-muted">{fixed}</p>
          </Card>
        </div>
      </div>

      {open?.kind === "property" && (
        <PropertyDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(source) => {
            run(
              () => api.property.updateSource(property, source),
              sst(language, "se_saved"),
            );
          }}
          problem={problem}
          property={property}
        />
      )}
      {open?.kind === "days" && (
        <DaysDialog
          busy={busy}
          current={dueDays.one_time_charge_due_days}
          language={language}
          onClose={closeOpen}
          onSave={(days, reason) => {
            run(
              () =>
                api.dueDays.set(
                  propertyId,
                  days,
                  reason,
                  // The days share the Property's version.
                  dueDays.version,
                  crypto.randomUUID(),
                ),
              sst(language, "se_saved"),
            );
          }}
          problem={problem}
        />
      )}
      {open?.kind === "method" && (
        <MethodDialog
          busy={busy}
          language={language}
          method={open.method}
          methods={methods}
          onClose={closeOpen}
          onSave={(next) => {
            const list =
              open.method === null
                ? [...methods, next]
                : methods.map((method) =>
                    method.code === next.code ? next : method,
                  );
            run(
              () => api.property.updatePaymentMethods(property, list),
              sst(language, "sv_saved", next.display_name),
            );
          }}
          problem={problem}
        />
      )}
    </>
  );
}

function PropertyDialog({
  language,
  property,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  property: PropertyBusinessConfiguration;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (source: { name: string; address_text: string | null }) => void;
}) {
  const [name, setName] = useState(property.name);
  const [address, setAddress] = useState(property.address_text ?? "");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") {
      setError(sst(language, "se_e_name"));
      document.getElementById("bz-name")?.focus();
      return;
    }
    onSave({ name: name.trim(), address_text: address.trim() || null });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "se_prop")}
    >
      <div className="ui-field">
        <label htmlFor="bz-name">
          {sst(language, "se_prop_name")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={error === null ? undefined : "bz-name-e"}
          aria-invalid={error !== null}
          autoComplete="off"
          id="bz-name"
          maxLength={255}
          onChange={(event) => {
            setName(event.currentTarget.value);
            setError(null);
          }}
          value={name}
        />
        <FieldError id="bz-name-e" text={error} />
      </div>
      <div className="ui-field">
        <label htmlFor="bz-address">{sst(language, "address")}</label>
        <textarea
          id="bz-address"
          maxLength={2000}
          onChange={(event) => {
            setAddress(event.currentTarget.value);
          }}
          rows={3}
          value={address}
        />
      </div>
      <Problem text={problem} />
    </Dialog>
  );
}

function DaysDialog({
  language,
  current,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  current: number;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (days: number, reason: string) => void;
}) {
  const [days, setDays] = useState(String(current));
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ days?: string; reason?: string }>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = Number(days.trim());
    const found: { days?: string; reason?: string } = {};
    if (!/^\d{1,2}$/.test(days.trim()) || value < 1 || value > 90) {
      found.days = sst(language, "e_days");
    }
    if (reason.trim() === "") found.reason = sst(language, "ua_e_reason");
    setErrors(found);
    if (found.days !== undefined || found.reason !== undefined) {
      document
        .getElementById(found.days !== undefined ? "bz-days" : "bz-reason")
        ?.focus();
      return;
    }
    onSave(value, reason.trim());
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "se_misc_due")}
    >
      <div className="ui-field">
        <label htmlFor="bz-days">{sst(language, "days_n")}</label>
        <input
          aria-describedby={
            errors.days === undefined ? "bz-days-h" : "bz-days-h bz-days-e"
          }
          aria-invalid={errors.days !== undefined}
          autoComplete="off"
          id="bz-days"
          inputMode="numeric"
          maxLength={2}
          onChange={(event) => {
            setDays(event.currentTarget.value);
          }}
          value={days}
        />
        <p className="help" id="bz-days-h">
          {sst(language, "days_h")}
        </p>
        <FieldError id="bz-days-e" text={errors.days ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="bz-reason">
          {sst(language, "ur_reason")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            errors.reason === undefined ? undefined : "bz-reason-e"
          }
          aria-invalid={errors.reason !== undefined}
          autoComplete="off"
          id="bz-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        <FieldError id="bz-reason-e" text={errors.reason ?? null} />
      </div>
      <p className="ui-small ui-muted">{sst(language, "misc_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

function MethodDialog({
  language,
  method,
  methods,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  method: PaymentMethodConfiguration | null;
  methods: readonly PaymentMethodConfiguration[];
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (method: PaymentMethodConfiguration) => void;
}) {
  const [name, setName] = useState(method?.display_name ?? "");
  const [accepted, setAccepted] = useState(method?.accepted ?? true);
  const [errors, setErrors] = useState<{ name?: string; on?: string }>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const shown = name.trim();
    const found: { name?: string; on?: string } = {};
    if (shown === "") found.name = sst(language, "se_e_name");
    else if (
      methods.some(
        (other) =>
          other.code !== method?.code &&
          other.display_name.toLowerCase() === shown.toLowerCase(),
      )
    ) {
      found.name = sst(language, "cf_e_dup", shown);
    }
    if (
      !accepted &&
      !methods.some((other) => other.code !== method?.code && other.accepted)
    ) {
      found.on = sst(language, "pm_e_last");
    }
    setErrors(found);
    if (found.name !== undefined || found.on !== undefined) {
      document
        .getElementById(found.name !== undefined ? "pm-name" : "pm-on")
        ?.focus();
      return;
    }
    onSave({
      code: method?.code ?? methodCode(shown, methods),
      display_name: shown,
      accepted,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, method === null ? "pm_add" : "pm_edit")}
    >
      <div className="ui-field">
        <label htmlFor="pm-name">
          {sst(language, "pm_name")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={errors.name === undefined ? undefined : "pm-name-e"}
          aria-invalid={errors.name !== undefined}
          autoComplete="off"
          id="pm-name"
          lang="en"
          maxLength={255}
          onChange={(event) => {
            setName(event.currentTarget.value);
          }}
          value={name}
        />
        <FieldError id="pm-name-e" text={errors.name ?? null} />
      </div>
      <label className="ui-chk">
        <input
          aria-describedby={errors.on === undefined ? undefined : "pm-on-e"}
          aria-invalid={errors.on !== undefined}
          checked={accepted}
          id="pm-on"
          onChange={(event) => {
            setAccepted(event.currentTarget.checked);
          }}
          type="checkbox"
        />
        <span>{sst(language, "pm_on")}</span>
      </label>
      <FieldError id="pm-on-e" text={errors.on ?? null} />
      <p className="ui-small ui-muted">{sst(language, "pm_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}
