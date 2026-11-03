// V1-058 R7b-4, reworked in V1.1 part 2 (DL-118, mock-up rounds 20-25): Settings → Business.
// One column of cards (Property, Business, Business rules, Invoice types, Payment Methods, the
// riel rate, App preferences) with Document numbering on the right. Every value comes from the
// server: the business rules keep their history and start on a chosen day, the numbering shows
// the next number, and an Invoice type says whether it gets the late-payment charge. The time
// zone is fixed from the business location (Cambodia).

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
  type PropertySource,
} from "../propertyClient";
import { DateInput, parseDay } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import { allPages } from "../units/unitsData";
import {
  type BusinessRule,
  type BusinessRules,
  type BusinessSettingsApi,
  BusinessSettingsError,
  type InvoiceType,
  type NumberRule,
  RULE_AREAS,
  RULE_UNITS,
  type RuleArea,
  type RuleUnit,
  ruleValueFromText,
  ruleValueInput,
  ruleValueText,
} from "./businessSettingsClient";
import { type SettingsTextKey, sst } from "./text";

export interface BusinessApi {
  property: PropertyConfigurationApi;
  units: Pick<UnitApi, "list">;
  /** The riel rate comes from the confirmed exchange rates. */
  rates: Pick<EffectiveConfigurationApi, "load">;
  /** V1.1 part 2: business rules, document numbering and Invoice types. */
  settings: BusinessSettingsApi;
  /** The days after issue for other Invoices stay the V1 Property setting (DL-118). */
  dueDays: DueDaysApi;
}

interface Loaded {
  property: PropertyBusinessConfiguration;
  units: number | null;
  /** undefined: could not be read; null: none yet. */
  rate: ExchangeRate | null | undefined;
  rules: BusinessRules;
  numbers: NumberRule[];
  types: InvoiceType[];
  dueDays: DueDaysSetting;
}

type Open =
  | { kind: "property" }
  | { kind: "business" }
  | { kind: "rule"; rule: BusinessRule }
  | { kind: "add-rule" }
  | { kind: "days" }
  | { kind: "type"; type: InvoiceType }
  | { kind: "letters"; number: NumberRule }
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

/** A new rule's code from its English name: capitals, digits and _, starting with a letter. */
export function ruleCode(name: string, rules: readonly BusinessRule[]): string {
  const cleaned = name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^[_0-9]+|_+$/g, "")
    .slice(0, 50);
  const base = cleaned.length >= 2 ? cleaned : "RULE";
  const taken = new Set(rules.map((rule) => rule.code));
  let code = base;
  for (let n = 2; taken.has(code); n++) code = `${base}_${String(n)}`;
  return code;
}

function rielText(value: number): string {
  return value.toLocaleString("en-US");
}

function nameOf(
  language: Language,
  item: { name_en: string; name_kh: string },
): string {
  return language === "km" ? item.name_kh : item.name_en;
}

function documentName(language: Language, type: string): string {
  const key = `nr_${type}`;
  return key in NUMBER_NAMES ? sst(language, key as SettingsTextKey) : type;
}

const NUMBER_NAMES: Record<string, true> = {
  nr_INVOICE: true,
  nr_RECEIPT: true,
  nr_REFUND: true,
  nr_JOURNAL_ENTRY: true,
  nr_EXPENSE_REQUEST: true,
  nr_EXPENSE: true,
  nr_SUPPLIER_BILL: true,
  nr_ADJUSTING_ENTRY: true,
  nr_FIXED_ASSET: true,
  nr_MONEY_MOVEMENT: true,
};

/** The number the next document gets with these letters. */
function nextWith(number: NumberRule, letters: string): string {
  return letters + number.next_number.slice(number.letters.length);
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
      allPages(async (cursor) =>
        api.units.list(propertyId, cursor === undefined ? {} : { cursor }),
      )
        .then((units) => units.filter((unit) => unit.for_rent !== false).length)
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
      api.settings.rules(propertyId),
      api.settings.numbers(propertyId),
      api.settings.invoiceTypes(propertyId),
      api.dueDays.get(propertyId),
    ])
      .then(([property, units, rate, rules, numbers, types, dueDays]) => {
        if (operation !== sequence.current) return;
        setLoaded({ property, units, rate, rules, numbers, types, dueDays });
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setLoaded(null);
        setFailure(
          error instanceof PropertyConfigurationUnavailableError ||
            (error instanceof BusinessSettingsError && error.status === 403) ||
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

  /** `taken`: what a 409 means here (a day or letters already used); without it a 409 means
   * another change met this one. */
  function run(
    work: () => Promise<unknown>,
    done: string,
    taken?: SettingsTextKey,
  ) {
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
          error instanceof BusinessSettingsError ||
          error instanceof InvoiceClientError
            ? error.status
            : null;
        if (status === 409 && taken !== undefined) {
          setProblem(sst(language, taken));
          return undefined;
        }
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

  const { property, units, rate, rules, numbers, types, dueDays } = loaded;
  const openWith = (next: Open) => {
    setProblem(null);
    setToast(null);
    setOpen(next);
  };
  const editButton = (label: SettingsTextKey, next: Open, name: string) => (
    <button
      aria-label={`${sst(language, label)}: ${name}`}
      className="ui-btn"
      onClick={() => {
        openWith(next);
      }}
      type="button"
    >
      {(label === "pm_add" || label === "br_add") && <Icon name="plus" small />}
      {sst(language, label)}
    </button>
  );
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };
  const methods = property.payment_methods;
  const notGiven = (
    <span className="ui-muted">{sst(language, "no_address")}</span>
  );
  const areas = RULE_AREAS.filter((area) =>
    rules.rules.some((rule) => rule.area === area),
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
                [sst(language, "se20_desc"), property.description ?? notGiven],
                [sst(language, "address"), property.address_text ?? notGiven],
                [
                  sst(language, "se20_units"),
                  <>
                    <span className="ui-num">{units ?? "—"}</span>
                    <span className="ui-sub2">
                      {sst(language, "se20_units_n")}
                    </span>
                  </>,
                ],
              ]}
            />
          </Card>
          <Card
            action={editButton(
              "se_edit",
              { kind: "business" },
              sst(language, "se20_biz"),
            )}
            id="biz-business"
            title={sst(language, "se20_biz")}
          >
            <Rows
              rows={[
                [
                  sst(language, "se20_biz_name"),
                  <>
                    {property.business_name ?? notGiven}
                    <span className="ui-sub2">
                      {sst(language, "se20_biz_n")}
                    </span>
                  </>,
                ],
              ]}
            />
          </Card>
          <Card
            action={editButton(
              "br_add",
              { kind: "add-rule" },
              sst(language, "br_title"),
            )}
            id="biz-rules"
            title={sst(language, "br_title")}
          >
            <p className="ui-small ui-muted">{sst(language, "br_sub")}</p>
            {areas.map((area) => (
              <RulesTable
                area={area}
                first={
                  area === "BILLING" ? (
                    <tr>
                      <td>{sst(language, "se_misc_due")}</td>
                      <td className="ui-num">
                        {sst(
                          language,
                          "cal_misc_v",
                          dueDays.one_time_charge_due_days,
                        )}
                      </td>
                      <td className="ui-num">—</td>
                      <td>
                        <button
                          aria-label={`${sst(language, "se_edit")}: ${sst(language, "se_misc_due")}`}
                          className="ui-btn link"
                          onClick={() => {
                            openWith({ kind: "days" });
                          }}
                          type="button"
                        >
                          {sst(language, "se_edit")}
                        </button>
                      </td>
                    </tr>
                  ) : undefined
                }
                key={area}
                language={language}
                onEdit={(rule) => {
                  openWith({ kind: "rule", rule });
                }}
                rules={rules.rules.filter((rule) => rule.area === area)}
              />
            ))}
          </Card>
          <Card id="biz-types" title={sst(language, "it_title")}>
            <p className="ui-small ui-muted">{sst(language, "it_sub")}</p>
            <div className="ui-tablewrap">
              <table className="ui-table fit">
                <thead>
                  <tr>
                    <th scope="col">{sst(language, "it_type")}</th>
                    <th scope="col">{sst(language, "it_late")}</th>
                    <th scope="col">
                      <span className="ui-sr">
                        {sst(language, "it_change")}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {types.map((type) => (
                    <tr key={type.code}>
                      <td>{nameOf(language, type)}</td>
                      <td>
                        {type.late_payment ? (
                          <Chip icon="check" tone="ok">
                            {sst(language, "yes")}
                          </Chip>
                        ) : (
                          <Chip tone="neutral">{sst(language, "no")}</Chip>
                        )}
                      </td>
                      <td>
                        <button
                          aria-label={`${sst(language, "it_change")}: ${nameOf(language, type)}`}
                          className="ui-btn link"
                          onClick={() => {
                            openWith({ kind: "type", type });
                          }}
                          type="button"
                        >
                          {sst(language, "it_change")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
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
                        openWith({ kind: "method", method });
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
          <Card id="biz-app" title={sst(language, "se20_app")}>
            <Rows
              rows={[
                [
                  sst(language, "se_tz"),
                  <>
                    <span>{sst(language, "se20_tz_v")}</span>
                    <span className="ui-sub2">{sst(language, "se_tz_n")}</span>
                  </>,
                ],
                [sst(language, "se_lang"), sst(language, "se20_lang_v")],
              ]}
            />
          </Card>
        </div>
        <div className="ui-stack">
          <Card id="biz-numbers" title={sst(language, "nr_title")}>
            <p className="ui-small ui-muted">{sst(language, "nr21_sub")}</p>
            <div className="ui-tablewrap">
              <table className="ui-table fit">
                <thead>
                  <tr>
                    <th scope="col">{sst(language, "nr_doc")}</th>
                    <th scope="col">{sst(language, "nr_fmt")}</th>
                    <th scope="col">{sst(language, "nr_next")}</th>
                  </tr>
                </thead>
                <tbody>
                  {numbers.map((number) => (
                    <tr key={number.document_type}>
                      <td>
                        <button
                          aria-label={sst(
                            language,
                            "nr_edit_t",
                            documentName(language, number.document_type),
                          )}
                          className="ui-btn link"
                          onClick={() => {
                            openWith({ kind: "letters", number });
                          }}
                          type="button"
                        >
                          {documentName(language, number.document_type)}
                        </button>
                      </td>
                      <td className="ui-num" lang="en">
                        {number.format}
                      </td>
                      <td className="ui-num" lang="en">
                        {number.next_number}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ui-small ui-muted">{sst(language, "nr_note")}</p>
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
      {open?.kind === "business" && (
        <BusinessNameDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(businessName) => {
            run(
              () =>
                api.property.updateSource(property, {
                  name: property.name,
                  address_text: property.address_text,
                  business_name: businessName,
                }),
              sst(language, "se_saved"),
            );
          }}
          problem={problem}
          property={property}
        />
      )}
      {open?.kind === "rule" && (
        <RuleDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(change) => {
            run(
              () => api.settings.setRule(propertyId, open.rule.code, change),
              sst(
                language,
                "br_saved",
                nameOf(language, open.rule),
                dayText(change.effective_from),
              ),
              "br_e_taken",
            );
          }}
          problem={problem}
          rule={open.rule}
          today={rules.today}
        />
      )}
      {open?.kind === "add-rule" && (
        <AddRuleDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(rule) => {
            run(
              () =>
                api.settings.addRule(propertyId, {
                  ...rule,
                  code: ruleCode(rule.name_en, rules.rules),
                }),
              sst(
                language,
                "br_added",
                language === "km" ? rule.name_kh : rule.name_en,
              ),
              "br_e_code",
            );
          }}
          problem={problem}
          today={rules.today}
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
      {open?.kind === "type" && (
        <InvoiceTypeDialog
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(latePayment, reason) => {
            run(
              () =>
                api.settings.setLatePayment(
                  propertyId,
                  open.type.code,
                  latePayment,
                  reason,
                ),
              sst(
                language,
                "it_saved",
                nameOf(language, open.type),
                sst(language, latePayment ? "yes" : "no"),
              ),
            );
          }}
          problem={problem}
          type={open.type}
        />
      )}
      {open?.kind === "letters" && (
        <LettersDialog
          busy={busy}
          language={language}
          number={open.number}
          numbers={numbers}
          onClose={closeOpen}
          onSave={(letters) => {
            run(
              () =>
                api.settings.setLetters(
                  propertyId,
                  open.number.document_type,
                  letters,
                ),
              sst(language, "nr_saved", nextWith(open.number, letters)),
              "nr_e",
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

function RulesTable({
  language,
  area,
  rules,
  first,
  onEdit,
}: {
  language: Language;
  area: RuleArea;
  rules: BusinessRule[];
  /** A row shown before the rules (the V1 days after issue in Billing). */
  first?: ReactNode;
  onEdit: (rule: BusinessRule) => void;
}) {
  const heading = `br-area-${area}`;
  return (
    <div className="ui-tablewrap">
      <table aria-labelledby={heading} className="ui-table fit">
        <caption id={heading}>
          {sst(language, `br_area_${area}` as SettingsTextKey)}
        </caption>
        <thead>
          <tr>
            <th scope="col">{sst(language, "br_rule")}</th>
            <th scope="col">{sst(language, "br_value")}</th>
            <th scope="col">{sst(language, "br_since")}</th>
            <th scope="col">
              <span className="ui-sr">{sst(language, "se_edit")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {first}
          {rules.map((rule) => (
            <tr key={rule.code}>
              <td>
                {nameOf(language, rule)}
                {!rule.used_by_app && (
                  <>
                    {" "}
                    <span title={sst(language, "br_unused_s")}>
                      <Chip tone="neutral">{sst(language, "br_unused")}</Chip>
                    </span>
                  </>
                )}
              </td>
              <td className="ui-num">
                {rule.in_force === null ? (
                  <span className="ui-muted">{sst(language, "br_notset")}</span>
                ) : (
                  ruleValueText(rule.value_unit, rule.in_force.value, language)
                )}
                {rule.waiting !== null && (
                  <span className="ui-sub2">
                    {sst(
                      language,
                      "br_waiting",
                      dayText(rule.waiting.effective_from),
                      ruleValueText(
                        rule.value_unit,
                        rule.waiting.value,
                        language,
                      ),
                    )}
                  </span>
                )}
              </td>
              <td className="ui-num">
                {rule.in_force === null
                  ? "—"
                  : dayText(rule.in_force.effective_from)}
              </td>
              <td>
                <button
                  aria-label={`${sst(language, "se_edit")}: ${nameOf(language, rule)}`}
                  className="ui-btn link"
                  onClick={() => {
                    onEdit(rule);
                  }}
                  type="button"
                >
                  {sst(language, "se_edit")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function unitHelp(unit: RuleUnit): SettingsTextKey {
  if (
    unit === "USD_CENTS" ||
    unit === "PERCENT" ||
    unit === "TIME_OF_DAY" ||
    unit === "DAY_OF_MONTH"
  ) {
    return `bruh_${unit}`;
  }
  return "bruh_OTHER";
}

/** The value box for a rule's unit: Yes/No is a choice, every other unit is typed. */
function ValueField({
  id,
  label,
  language,
  unit,
  value,
  error,
  onChange,
}: {
  id: string;
  label: string;
  language: Language;
  unit: RuleUnit;
  value: string;
  error: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        <span className="req">{sst(language, "required")}</span>
      </label>
      {unit === "YES_NO" ? (
        <select
          id={id}
          onChange={(event) => {
            onChange(event.currentTarget.value);
          }}
          value={value}
        >
          <option value="1">{sst(language, "yes")}</option>
          <option value="0">{sst(language, "no")}</option>
        </select>
      ) : (
        <>
          <input
            aria-describedby={error === null ? `${id}-h` : `${id}-h ${id}-e`}
            aria-invalid={error !== null}
            autoComplete="off"
            id={id}
            inputMode={unit === "TIME_OF_DAY" ? "text" : "decimal"}
            maxLength={14}
            onChange={(event) => {
              onChange(event.currentTarget.value);
            }}
            value={value}
          />
          <p className="help" id={`${id}-h`}>
            {sst(language, `bru_${unit}`)} · {sst(language, unitHelp(unit))}
          </p>
        </>
      )}
      <FieldError id={`${id}-e`} text={error} />
    </div>
  );
}

function RuleDialog({
  language,
  rule,
  today,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  rule: BusinessRule;
  today: string;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (change: {
    value: number;
    effective_from: string;
    reason: string;
  }) => void;
}) {
  const shown = rule.waiting ?? rule.in_force;
  const [value, setValue] = useState(
    shown === null
      ? rule.value_unit === "YES_NO"
        ? "1"
        : ""
      : ruleValueInput(rule.value_unit, shown.value),
  );
  const [from, setFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{
    value?: string;
    from?: string;
    reason?: string;
  }>({});
  const history = [...rule.history].sort((a, b) =>
    b.effective_from.localeCompare(a.effective_from),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const number = ruleValueFromText(rule.value_unit, value);
    const day = parseDay(from);
    const found: typeof errors = {};
    if (number === null) found.value = sst(language, "br_e_val");
    if (day === "" || (today !== "" && day < today)) {
      found.from = sst(language, "br_e_date");
    }
    if (reason.trim() === "") found.reason = sst(language, "br_e_reason");
    setErrors(found);
    const first = (["value", "from", "reason"] as const).find(
      (key) => found[key] !== undefined,
    );
    if (first !== undefined || number === null) {
      document.getElementById(`br-${first ?? "value"}`)?.focus();
      return;
    }
    onSave({ value: number, effective_from: day, reason: reason.trim() });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "br_edit_t", nameOf(language, rule))}
    >
      {!rule.used_by_app && (
        <p className="ui-small ui-muted">{sst(language, "br_unused_s")}</p>
      )}
      <ValueField
        error={errors.value ?? null}
        id="br-value"
        label={sst(language, "br_new")}
        language={language}
        onChange={setValue}
        unit={rule.value_unit}
        value={value}
      />
      <div className="ui-field">
        <label htmlFor="br-from">
          {sst(language, "br_from")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <DateInput
          describedBy={errors.from === undefined ? undefined : "br-from-e"}
          id="br-from"
          invalid={errors.from !== undefined}
          language={language}
          min={today === "" ? undefined : today}
          onChange={setFrom}
          value={from}
        />
        <FieldError id="br-from-e" text={errors.from ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="br-reason">
          {sst(language, "br_reason")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            errors.reason === undefined ? undefined : "br-reason-e"
          }
          aria-invalid={errors.reason !== undefined}
          autoComplete="off"
          id="br-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        <FieldError id="br-reason-e" text={errors.reason ?? null} />
      </div>
      <h3 className="ui-small">{sst(language, "br_hist")}</h3>
      <ul aria-label={sst(language, "br_hist")} className="ui-apps">
        {history.map((row) => (
          <li key={row.effective_from}>
            <span>
              <span className="ui-num">{dayText(row.effective_from)}</span>{" "}
              <b>{ruleValueText(rule.value_unit, row.value, language)}</b>
            </span>
            {row.reason !== null && (
              <span className="ui-small ui-muted">{row.reason}</span>
            )}
          </li>
        ))}
      </ul>
      <Problem text={problem} />
    </Dialog>
  );
}

function AddRuleDialog({
  language,
  today,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  today: string;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (rule: {
    name_en: string;
    name_kh: string;
    area: RuleArea;
    value_unit: RuleUnit;
    value: number;
    effective_from: string;
    reason: string | null;
  }) => void;
}) {
  const [nameEn, setNameEn] = useState("");
  const [nameKh, setNameKh] = useState("");
  const [area, setArea] = useState<RuleArea>("OTHER");
  const [unit, setUnit] = useState<RuleUnit>("COUNT");
  const [value, setValue] = useState("");
  const [from, setFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{
    en?: string;
    kh?: string;
    value?: string;
    from?: string;
  }>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const number = ruleValueFromText(unit, value);
    const day = parseDay(from);
    const found: typeof errors = {};
    if (nameEn.trim() === "") found.en = sst(language, "br_e_name");
    if (nameKh.trim() === "") found.kh = sst(language, "br_e_name");
    if (number === null) found.value = sst(language, "br_e_val");
    if (day === "" || (today !== "" && day < today)) {
      found.from = sst(language, "br_e_date");
    }
    setErrors(found);
    const first = (["en", "kh", "value", "from"] as const).find(
      (key) => found[key] !== undefined,
    );
    if (first !== undefined || number === null) {
      document.getElementById(`ar-${first ?? "value"}`)?.focus();
      return;
    }
    onSave({
      name_en: nameEn.trim(),
      name_kh: nameKh.trim(),
      area,
      value_unit: unit,
      value: number,
      effective_from: day,
      reason: reason.trim() === "" ? null : reason.trim(),
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "br_add_t")}
    >
      <div className="ui-field">
        <label htmlFor="ar-en">
          {sst(language, "br_name_en")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={errors.en === undefined ? undefined : "ar-en-e"}
          aria-invalid={errors.en !== undefined}
          autoComplete="off"
          id="ar-en"
          lang="en"
          maxLength={200}
          onChange={(event) => {
            setNameEn(event.currentTarget.value);
          }}
          value={nameEn}
        />
        <FieldError id="ar-en-e" text={errors.en ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="ar-kh">
          {sst(language, "br_name_kh")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={errors.kh === undefined ? undefined : "ar-kh-e"}
          aria-invalid={errors.kh !== undefined}
          autoComplete="off"
          id="ar-kh"
          lang="km"
          maxLength={200}
          onChange={(event) => {
            setNameKh(event.currentTarget.value);
          }}
          value={nameKh}
        />
        <FieldError id="ar-kh-e" text={errors.kh ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="ar-area">{sst(language, "br_area")}</label>
        <select
          id="ar-area"
          onChange={(event) => {
            setArea(event.currentTarget.value as RuleArea);
          }}
          value={area}
        >
          {RULE_AREAS.map((item) => (
            <option key={item} value={item}>
              {sst(language, `br_area_${item}` as SettingsTextKey)}
            </option>
          ))}
        </select>
      </div>
      <div className="ui-field">
        <label htmlFor="ar-unit">{sst(language, "br_unit")}</label>
        <select
          id="ar-unit"
          onChange={(event) => {
            const next = event.currentTarget.value as RuleUnit;
            setUnit(next);
            if (next === "YES_NO") setValue("1");
          }}
          value={unit}
        >
          {RULE_UNITS.map((item) => (
            <option key={item} value={item}>
              {sst(language, `bru_${item}` as SettingsTextKey)}
            </option>
          ))}
        </select>
      </div>
      <ValueField
        error={errors.value ?? null}
        id="ar-value"
        label={sst(language, "br_first")}
        language={language}
        onChange={setValue}
        unit={unit}
        value={value}
      />
      <div className="ui-field">
        <label htmlFor="ar-from">
          {sst(language, "br_from")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <DateInput
          describedBy={errors.from === undefined ? undefined : "ar-from-e"}
          id="ar-from"
          invalid={errors.from !== undefined}
          language={language}
          min={today === "" ? undefined : today}
          onChange={setFrom}
          value={from}
        />
        <FieldError id="ar-from-e" text={errors.from ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="ar-reason">{sst(language, "br_reason")}</label>
        <input
          autoComplete="off"
          id="ar-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
      </div>
      <p className="ui-small ui-muted">{sst(language, "br_add_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

function InvoiceTypeDialog({
  language,
  type,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  type: InvoiceType;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (latePayment: boolean, reason: string) => void;
}) {
  const [on, setOn] = useState(type.late_payment);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ on?: string; reason?: string }>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (on === type.late_payment) found.on = sst(language, "it_same");
    if (reason.trim() === "") found.reason = sst(language, "br_e_reason");
    setErrors(found);
    if (found.on !== undefined || found.reason !== undefined) {
      document
        .getElementById(found.on !== undefined ? "it-on" : "it-reason")
        ?.focus();
      return;
    }
    onSave(on, reason.trim());
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "it_edit_t", nameOf(language, type))}
    >
      <label className="ui-chk">
        <input
          aria-describedby={errors.on === undefined ? undefined : "it-on-e"}
          checked={on}
          id="it-on"
          onChange={(event) => {
            setOn(event.currentTarget.checked);
          }}
          type="checkbox"
        />
        <span>{sst(language, "it_on")}</span>
      </label>
      <FieldError id="it-on-e" text={errors.on ?? null} />
      <div className="ui-field">
        <label htmlFor="it-reason">
          {sst(language, "br_reason")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            errors.reason === undefined ? undefined : "it-reason-e"
          }
          aria-invalid={errors.reason !== undefined}
          autoComplete="off"
          id="it-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        <FieldError id="it-reason-e" text={errors.reason ?? null} />
      </div>
      <p className="ui-small ui-muted">{sst(language, "it_sub")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

function LettersDialog({
  language,
  number,
  numbers,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  number: NumberRule;
  numbers: NumberRule[];
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (letters: string) => void;
}) {
  const [letters, setLetters] = useState(number.letters);
  const [error, setError] = useState<string | null>(null);
  const typed = letters.trim().toUpperCase();
  const fits = /^[A-Z]{2,5}$/.test(typed);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !fits ||
      numbers.some(
        (other) =>
          other.document_type !== number.document_type &&
          other.letters === typed,
      )
    ) {
      setError(sst(language, "nr_e"));
      document.getElementById("nr-letters")?.focus();
      return;
    }
    onSave(typed);
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(
        language,
        "nr_edit_t",
        documentName(language, number.document_type),
      )}
    >
      <div className="ui-field">
        <label htmlFor="nr-letters">
          {sst(language, "nr_letters")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            error === null ? "nr-letters-h" : "nr-letters-h nr-letters-e"
          }
          aria-invalid={error !== null}
          autoCapitalize="characters"
          autoComplete="off"
          id="nr-letters"
          lang="en"
          maxLength={5}
          onChange={(event) => {
            setLetters(event.currentTarget.value);
            setError(null);
          }}
          value={letters}
        />
        <p className="help ui-num" id="nr-letters-h">
          {sst(
            language,
            "nr_preview",
            nextWith(number, fits ? typed : number.letters),
          )}
        </p>
        <FieldError id="nr-letters-e" text={error} />
      </div>
      <p className="ui-small ui-muted">{sst(language, "nr_note")}</p>
      <Problem text={problem} />
    </Dialog>
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
  onSave: (source: PropertySource) => void;
}) {
  const [name, setName] = useState(property.name);
  const [description, setDescription] = useState(property.description ?? "");
  const [address, setAddress] = useState(property.address_text ?? "");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") {
      setError(sst(language, "se_e_name"));
      document.getElementById("bz-name")?.focus();
      return;
    }
    onSave({
      name: name.trim(),
      description: description.trim() || null,
      address_text: address.trim() || null,
    });
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
        <label htmlFor="bz-desc">{sst(language, "se20_desc")}</label>
        <textarea
          id="bz-desc"
          maxLength={500}
          onChange={(event) => {
            setDescription(event.currentTarget.value);
          }}
          rows={2}
          value={description}
        />
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

function BusinessNameDialog({
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
  onSave: (businessName: string | null) => void;
}) {
  const [name, setName] = useState(property.business_name ?? "");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSave(name.trim() || null);
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "se20_edit_biz")}
    >
      <div className="ui-field">
        <label htmlFor="bz-biz">{sst(language, "se20_biz_name")}</label>
        <input
          aria-describedby="bz-biz-h"
          autoComplete="off"
          id="bz-biz"
          maxLength={255}
          onChange={(event) => {
            setName(event.currentTarget.value);
          }}
          value={name}
        />
        <p className="help" id="bz-biz-h">
          {sst(language, "se20_biz_n")}
        </p>
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
