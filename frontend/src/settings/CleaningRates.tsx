// V1-058 R7b-6d: the move-out cleaning rates of Settings → Rates and services (DESIGN.md "Rates and
// services"; DL-075). One rate covers one or more Unit Types and each Unit Type has one rate;
// ticking a Unit Type that is in another rate moves it here. A Unit Type that has Units is never
// left without a rate: the form says so before sending, and the server refuses it too.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { centsOf } from "../invoices/invoicesData";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { FieldError, Problem } from "./BusinessTab";
import {
  failureText,
  Field,
  focusFirst,
  NameFields,
  nameErrors,
  nameOf,
} from "./ServiceDialogs";
import {
  type CleaningRate,
  type CleaningRateForm,
  type CleaningSettings,
  type CleaningSettingsApi,
  type CleaningUnitType,
  ServiceSettingsError,
} from "./serviceSettingsClient";
import { sst } from "./text";

type Open =
  | { kind: "edit"; rate: CleaningRate | null }
  | {
      kind: "remove";
      rate: CleaningRate;
    };

/** The first Unit Type with Units that would be left without a rate, or null. */
export function leftWithout(
  rate: CleaningRate | null,
  ticked: ReadonlySet<string>,
  types: readonly CleaningUnitType[],
): CleaningUnitType | null {
  if (rate === null) return null;
  return (
    types.find(
      (type) =>
        type.units > 0 &&
        rate.unit_types.includes(type.code) &&
        !ticked.has(type.code),
    ) ?? null
  );
}

function CleaningRateDialog({
  language,
  rate,
  settings,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  /** null: a new rate. */
  rate: CleaningRate | null;
  settings: CleaningSettings;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (form: CleaningRateForm) => void;
}) {
  const [nameEn, setNameEn] = useState(rate?.name_en ?? "");
  const [nameKm, setNameKm] = useState(rate?.name_km ?? "");
  const [amount, setAmount] = useState(
    rate === null ? "" : (rate.rate_usd_cents / 100).toFixed(2),
  );
  const [ticked, setTicked] = useState<Set<string>>(
    () => new Set(rate?.unit_types ?? []),
  );
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const rateName = new Map(
    settings.cleaning_rates.map((item) => [
      item.cleaning_rate_id,
      nameOf(language, item),
    ]),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = nameErrors(language, "cl", nameEn, nameKm);
    const cents = centsOf(amount);
    if (cents === null) found["cl-amt"] = sst(language, "err_amount");
    const left = leftWithout(rate, ticked, settings.unit_types);
    if (left !== null) {
      found["cl-types"] = sst(language, "cl_needs", nameOf(language, left));
    }
    setErrors(found);
    if (focusFirst(found, ["cl-en", "cl-km", "cl-amt", "cl-types"])) return;
    if (cents === null) return;
    onSave({
      name_en: nameEn.trim(),
      name_km: nameKm.trim() || null,
      rate_usd_cents: cents,
      // In the order of the Unit setup list.
      unit_types: settings.unit_types
        .map((type) => type.code)
        .filter((code) => ticked.has(code)),
    });
  }

  const typesError = errors["cl-types"];
  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={
        rate === null
          ? sst(language, "cl_add")
          : `${sst(language, "cf_edit")} · ${nameOf(language, rate)}`
      }
    >
      <NameFields
        errors={errors}
        language={language}
        nameEn={nameEn}
        nameKm={nameKm}
        onEn={setNameEn}
        onKm={setNameKm}
        prefix="cl"
      />
      <Field
        error={errors["cl-amt"]}
        id="cl-amt"
        label={sst(language, "cl_rate")}
        required={sst(language, "required")}
      >
        {(describedBy) => (
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              aria-describedby={describedBy}
              aria-invalid={errors["cl-amt"] !== undefined}
              autoComplete="off"
              id="cl-amt"
              inputMode="decimal"
              onChange={(event) => {
                setAmount(event.currentTarget.value);
              }}
              value={amount}
            />
          </div>
        )}
      </Field>
      <fieldset
        aria-describedby={typesError === undefined ? undefined : "cl-types-e"}
        className="ui-radios"
        id="cl-types"
        tabIndex={-1}
      >
        <legend>{sst(language, "cl_types")}</legend>
        {settings.unit_types.map((type) => {
          const elsewhere =
            type.cleaning_rate_id !== null &&
            type.cleaning_rate_id !== rate?.cleaning_rate_id
              ? (rateName.get(type.cleaning_rate_id) ?? null)
              : null;
          const id = `cl-t-${type.code}`;
          return (
            <div key={type.code}>
              <label className="ui-chk" htmlFor={id}>
                <input
                  aria-describedby={elsewhere === null ? undefined : `${id}-h`}
                  checked={ticked.has(type.code)}
                  id={id}
                  onChange={(event) => {
                    const on = event.currentTarget.checked;
                    setTicked((before) => {
                      const next = new Set(before);
                      if (on) next.add(type.code);
                      else next.delete(type.code);
                      return next;
                    });
                  }}
                  type="checkbox"
                />
                {nameOf(language, type)}
                <small className="ui-muted ui-num">
                  {type.units === 0
                    ? sst(language, "set_none_units")
                    : type.units === 1
                      ? sst(language, "set_n_unit1")
                      : sst(language, "set_n_units", type.units)}
                </small>
              </label>
              {elsewhere !== null && (
                <p className="help" id={`${id}-h`}>
                  {sst(language, "cl_moves", elsewhere)}
                </p>
              )}
            </div>
          );
        })}
        <FieldError id="cl-types-e" text={typesError ?? null} />
      </fieldset>
      <p className="ui-small ui-muted">{sst(language, "cl_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

export function CleaningRatesCard({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: CleaningSettingsApi;
}) {
  // "failed": nothing to show or change until a read works.
  const [settings, setSettings] = useState<CleaningSettings | "failed" | null>(
    null,
  );
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);
  // The id of a new rate stays until the server confirms it, so a resend after a lost answer
  // never adds a second rate.
  const pending = useRef<string | null>(null);

  const load = useCallback((): Promise<void> => {
    if (propertyId === "") return Promise.resolve();
    const operation = ++sequence.current;
    return api.read(propertyId).then(
      (found) => {
        if (operation === sequence.current) setSettings(found);
      },
      () => {
        if (operation !== sequence.current) return;
        // A failed read again keeps what was read before, so an open form is not lost.
        setSettings((before) =>
          before !== null && before !== "failed" ? before : "failed",
        );
      },
    );
  }, [api, propertyId]);

  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    pending.current = null;
    setSettings(null);
    setOpen(null);
    setProblem(null);
    setToast(null);
    setBusy(false);
  }, [propertyId]);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  function run(work: () => Promise<unknown>, done: string, adding: boolean) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    work()
      .then(
        () => {
          if (shownProperty.current !== asked) return undefined;
          if (adding) pending.current = null;
          setOpen(null);
          setToast({ ok: true, text: done });
          return load();
        },
        (error: unknown) => {
          if (shownProperty.current !== asked) return undefined;
          const found =
            error instanceof ServiceSettingsError ? error.failure : "unknown";
          if (found === "id_reused" && adding) pending.current = null;
          if (found === "id_reused" || found === "not_found") {
            // Saved before (the list shows it now), or gone: the form has nothing more to do.
            setOpen(null);
            setToast({ ok: false, text: failureText(language, found) });
            return load();
          }
          setProblem(failureText(language, found));
          if (
            found === "out_of_date" ||
            found === "needs_rate" ||
            found === "unknown"
          ) {
            return load();
          }
          return undefined;
        },
      )
      .finally(() => {
        if (shownProperty.current === asked) setBusy(false);
      });
  }

  if (settings === null) return null;
  if (settings === "failed") {
    return (
      <section aria-labelledby="rates-cleaning" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="rates-cleaning">{sst(language, "cl_title")}</h2>
        </header>
        <div className="ui-notice warn pad" role="status">
          <Icon name="alert" />
          <p>{sst(language, "cl_read_failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              void load();
            }}
            type="button"
          >
            {sst(language, "retry")}
          </button>
        </div>
      </section>
    );
  }

  const manage = settings.can_manage;
  const typeName = new Map(
    settings.unit_types.map((type) => [type.code, nameOf(language, type)]),
  );
  const missing = settings.unit_types.filter(
    (type) => type.cleaning_rate_id === null,
  );
  const latest = (rate: CleaningRate) =>
    settings.cleaning_rates.find(
      (item) => item.cleaning_rate_id === rate.cleaning_rate_id,
    ) ?? rate;
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };
  const removing = open?.kind === "remove" ? latest(open.rate) : null;
  const blocked =
    removing === null
      ? null
      : leftWithout(removing, new Set(), settings.unit_types);

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
      <section aria-labelledby="rates-cleaning" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="rates-cleaning">{sst(language, "cl_title")}</h2>
          {manage && (
            <button
              className="ui-btn"
              onClick={() => {
                setProblem(null);
                setToast(null);
                setOpen({ kind: "edit", rate: null });
              }}
              type="button"
            >
              <Icon name="plus" small />
              {sst(language, "cl_add")}
            </button>
          )}
        </header>
        {missing.length > 0 && (
          <div className="ui-notice warn pad" role="note">
            <Icon name="alert" />
            <p>
              {sst(
                language,
                "cl_missing",
                missing.map((type) => nameOf(language, type)).join(", "),
              )}
            </p>
          </div>
        )}
        {settings.cleaning_rates.length === 0 ? (
          <p className="pad ui-muted">{sst(language, "cl_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{sst(language, "cl_name")}</th>
                  <th scope="col">{sst(language, "cl_types")}</th>
                  <th className="r" scope="col">
                    {sst(language, "cl_rate")}
                  </th>
                  {manage && (
                    <th scope="col">
                      <span className="ui-sr">{sst(language, "actions")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {settings.cleaning_rates.map((rate) => {
                  const name = nameOf(language, rate);
                  return (
                    <tr key={rate.cleaning_rate_id}>
                      <td>
                        <b>{name}</b>
                      </td>
                      <td>
                        {rate.unit_types.length === 0
                          ? "—"
                          : rate.unit_types
                              .map((code) => typeName.get(code) ?? code)
                              .join(", ")}
                      </td>
                      <td className="r ui-num">
                        {usdFromCents(rate.rate_usd_cents)}
                      </td>
                      {manage && (
                        <td>
                          <span className="ui-actions">
                            <button
                              aria-label={`${sst(language, "cf_edit")}: ${name}`}
                              className="ui-btn link"
                              onClick={() => {
                                setProblem(null);
                                setToast(null);
                                setOpen({ kind: "edit", rate });
                              }}
                              type="button"
                            >
                              {sst(language, "cf_edit")}
                            </button>
                            <button
                              aria-label={`${sst(language, "set_remove")}: ${name}`}
                              className="ui-btn link"
                              onClick={() => {
                                setProblem(null);
                                setToast(null);
                                setOpen({ kind: "remove", rate });
                              }}
                              type="button"
                            >
                              {sst(language, "set_remove")}
                            </button>
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
        <div className="ui-tfoot">
          <span>{sst(language, "cl_note")}</span>
        </div>
      </section>

      {open?.kind === "edit" && (
        <CleaningRateDialog
          // A newer version (another person changed the rate, or moved a type out of it) starts
          // the form again from what is saved, so a Save never takes a moved type back.
          key={
            open.rate === null
              ? "new"
              : `${open.rate.cleaning_rate_id}-${String(latest(open.rate).version)}`
          }
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(form) => {
            if (open.rate !== null) {
              // The newest read: after a newer version the form restarts from it.
              const rate = latest(open.rate);
              run(
                () =>
                  api.change(propertyId, rate.cleaning_rate_id, {
                    ...form,
                    version: rate.version,
                  }),
                sst(language, "sv_changed", nameOf(language, form)),
                false,
              );
              return;
            }
            const rateId = pending.current ?? crypto.randomUUID();
            pending.current = rateId;
            run(
              () => api.add(propertyId, { cleaning_rate_id: rateId, ...form }),
              sst(language, "sv_added", nameOf(language, form)),
              true,
            );
          }}
          problem={problem}
          rate={open.rate === null ? null : latest(open.rate)}
          settings={settings}
        />
      )}
      {removing !== null && (
        <Dialog
          actions={
            blocked === null ? (
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  run(
                    () =>
                      api.remove(
                        propertyId,
                        removing.cleaning_rate_id,
                        removing.version,
                      ),
                    sst(language, "set_removed", nameOf(language, removing)),
                    false,
                  );
                }}
                type="button"
              >
                {sst(language, "set_remove")}
              </button>
            ) : undefined
          }
          busy={busy}
          closeLabel={sst(language, "cancel")}
          onClose={closeOpen}
          title={`${sst(language, "set_remove")} · ${nameOf(language, removing)}`}
        >
          {blocked === null ? (
            <p>{sst(language, "set_remove_q", nameOf(language, removing))}</p>
          ) : (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{sst(language, "cl_needs", nameOf(language, blocked))}</p>
            </div>
          )}
          <Problem text={problem} />
        </Dialog>
      )}
    </>
  );
}
