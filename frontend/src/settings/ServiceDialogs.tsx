// V1-058 R7b-6b: the Service and Service type parts of Settings → Rates and services (DESIGN.md
// "Rates and services"; DL-075). Add a Service with its first rate, change its names and type,
// and keep the Service types ("Only one per Lease" or "One or more per Lease"). The server checks
// every rule again: a type with Services is never removed, and a change that would leave a Lease
// with two Services of an "Only one" type is refused.

import { type FormEvent, type ReactNode, useState } from "react";

import { centsOf } from "../invoices/invoicesData";
import { DateInput, isDay } from "../shell/DateInput";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { FieldError, Problem } from "./BusinessTab";
import type {
  ServiceSetting,
  ServiceSettingsFailure,
  ServiceType,
} from "./serviceSettingsClient";
import { type SettingsTextKey, sst } from "./text";

export function Field({
  id,
  label,
  required,
  help,
  error,
  children,
}: {
  id: string;
  label: string;
  required: string | null;
  help?: string;
  error: string | undefined;
  children: (describedBy: string | undefined) => ReactNode;
}) {
  const ids = [
    help === undefined ? null : `${id}-h`,
    error === undefined ? null : `${id}-e`,
  ]
    .filter((value) => value !== null)
    .join(" ");
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        {required !== null && <span className="req">{required}</span>}
      </label>
      {children(ids === "" ? undefined : ids)}
      {help !== undefined && (
        <p className="help" id={`${id}-h`}>
          {help}
        </p>
      )}
      <FieldError id={`${id}-e`} text={error ?? null} />
    </div>
  );
}

export function focusFirst(
  errors: Record<string, string | undefined>,
  order: readonly string[],
) {
  const first = order.find((id) => errors[id] !== undefined);
  if (first !== undefined) document.getElementById(first)?.focus();
  return first !== undefined;
}

const FAILURE_TEXT: Record<ServiceSettingsFailure, SettingsTextKey> = {
  not_allowed: "no_tab",
  invalid: "rates_refused",
  not_found: "f_gone",
  out_of_date: "f_out_of_date",
  id_reused: "f_id_reused",
  lease_holds_two: "f_lease_two",
  type_has_services: "f_type_has",
  needs_rate: "f_needs_rate",
  name_taken: "rs_name_taken",
  used_this_year: "rs_used_refused",
  unknown: "rates_unknown",
};

export function failureText(
  language: Language,
  failure: ServiceSettingsFailure,
): string {
  return sst(language, FAILURE_TEXT[failure]);
}

/** The name in the reader's language when there is one. */
export function nameOf(
  language: Language,
  item: { name_en: string; name_km: string | null },
): string {
  return language === "km" && item.name_km !== null
    ? item.name_km
    : item.name_en;
}

/** Whole letters, so a Khmer name is not cut in the middle of a letter. */
function letters(value: string): number {
  return Array.from(value).length;
}

export function NameFields({
  language,
  prefix,
  nameEn,
  nameKm,
  errors,
  onEn,
  onKm,
}: {
  language: Language;
  prefix: string;
  nameEn: string;
  nameKm: string;
  errors: Record<string, string | undefined>;
  onEn: (value: string) => void;
  onKm: (value: string) => void;
}) {
  return (
    <div className="ui-row2">
      <Field
        error={errors[`${prefix}-en`]}
        id={`${prefix}-en`}
        label={sst(language, "cf_en")}
        required={sst(language, "required")}
      >
        {(describedBy) => (
          <input
            aria-describedby={describedBy}
            aria-invalid={errors[`${prefix}-en`] !== undefined}
            autoComplete="off"
            id={`${prefix}-en`}
            lang="en"
            maxLength={100}
            onChange={(event) => {
              onEn(event.currentTarget.value);
            }}
            value={nameEn}
          />
        )}
      </Field>
      <Field
        error={errors[`${prefix}-km`]}
        id={`${prefix}-km`}
        label={sst(language, "cf_kh")}
        required={sst(language, "optional")}
      >
        {(describedBy) => (
          <input
            aria-describedby={describedBy}
            aria-invalid={errors[`${prefix}-km`] !== undefined}
            autoComplete="off"
            id={`${prefix}-km`}
            lang="km"
            onChange={(event) => {
              onKm(event.currentTarget.value);
            }}
            value={nameKm}
          />
        )}
      </Field>
    </div>
  );
}

export function nameErrors(
  language: Language,
  prefix: string,
  nameEn: string,
  nameKm: string,
): Record<string, string | undefined> {
  const found: Record<string, string | undefined> = {};
  const en = letters(nameEn.trim());
  if (en < 1 || en > 100) found[`${prefix}-en`] = sst(language, "e_name");
  if (letters(nameKm.trim()) > 100) {
    found[`${prefix}-km`] = sst(language, "e_name");
  }
  return found;
}

export interface ServiceForm {
  name_en: string;
  name_km: string | null;
  service_type_id: string | null;
  /** Only when adding: the first rate and the day it starts. */
  first: { cents: number; starts_on: string } | null;
}

/** Add a Service (with its first rate) or change one's names and type. */
export function ServiceDialog({
  language,
  service,
  types,
  today,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  /** null: a new Service. */
  service: ServiceSetting | null;
  types: readonly ServiceType[];
  today: string;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (form: ServiceForm) => void;
}) {
  const [nameEn, setNameEn] = useState(service?.name_en ?? "");
  const [nameKm, setNameKm] = useState(service?.name_km ?? "");
  const [typeId, setTypeId] = useState(service?.service_type_id ?? "");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState("");
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  // A removed type can still be the one a Service has; it is shown but not offered to others.
  const choices = types.filter(
    (type) =>
      !type.removed || type.service_type_id === service?.service_type_id,
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = nameErrors(language, "sv", nameEn, nameKm);
    let first: ServiceForm["first"] = null;
    if (service === null) {
      const cents = centsOf(amount);
      if (cents === null || cents <= 0) {
        found["sv-amt"] = sst(language, "err_amount");
      }
      // Decided by Claude (no money rule): a new Service starts on the 1st of this month or
      // a later one, never in a month already billed.
      if (
        !(isDay(day) && day.endsWith("-01")) ||
        day < `${today.slice(0, 7)}-01`
      ) {
        found["sv-day"] = sst(language, "e_first_now");
      }
      if (cents !== null && cents > 0) first = { cents, starts_on: day };
    }
    setErrors(found);
    if (focusFirst(found, ["sv-en", "sv-km", "sv-amt", "sv-day"])) return;
    onSave({
      name_en: nameEn.trim(),
      name_km: nameKm.trim() === "" ? null : nameKm.trim(),
      service_type_id: typeId === "" ? null : typeId,
      first,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={
        service === null
          ? sst(language, "sv_add")
          : `${sst(language, "cf_edit")} · ${nameOf(language, service)}`
      }
    >
      <NameFields
        errors={errors}
        language={language}
        nameEn={nameEn}
        nameKm={nameKm}
        onEn={setNameEn}
        onKm={setNameKm}
        prefix="sv"
      />
      <div className="ui-field">
        <label htmlFor="sv-type">{sst(language, "sv_type")}</label>
        <select
          id="sv-type"
          onChange={(event) => {
            setTypeId(event.currentTarget.value);
          }}
          value={typeId}
        >
          <option value="">{sst(language, "sv_no_type")}</option>
          {choices.map((type) => (
            <option key={type.service_type_id} value={type.service_type_id}>
              {nameOf(language, type)} ·{" "}
              {sst(language, type.one_per_lease ? "st_one" : "st_many")}
            </option>
          ))}
        </select>
      </div>
      {service === null ? (
        <div className="ui-row2">
          <Field
            error={errors["sv-amt"]}
            help={sst(language, "sv_first_h")}
            id="sv-amt"
            label={sst(language, "se_svc_rate_h")}
            required={sst(language, "required")}
          >
            {(describedBy) => (
              <div className="ui-money">
                <span aria-hidden="true">$</span>
                <input
                  aria-describedby={describedBy}
                  aria-invalid={errors["sv-amt"] !== undefined}
                  autoComplete="off"
                  className="ui-num"
                  id="sv-amt"
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
            error={errors["sv-day"]}
            id="sv-day"
            label={sst(language, "se_starts")}
            required={sst(language, "required")}
          >
            {(describedBy) => (
              <DateInput
                language={language}
                describedBy={describedBy}
                invalid={errors["sv-day"] !== undefined}
                id="sv-day"
                min={`${today.slice(0, 7)}-01`}
                onChange={(value) => {
                  setDay(value);
                }}
                value={day}
              />
            )}
          </Field>
        </div>
      ) : (
        <p className="ui-small ui-muted">{sst(language, "sv_name_note")}</p>
      )}
      <Problem text={problem} />
    </Dialog>
  );
}

export interface TypeForm {
  name_en: string;
  name_km: string | null;
  one_per_lease: boolean;
}

export function TypeDialog({
  language,
  type,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  /** null: a new Service type. */
  type: ServiceType | null;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (form: TypeForm) => void;
}) {
  const [nameEn, setNameEn] = useState(type?.name_en ?? "");
  const [nameKm, setNameKm] = useState(type?.name_km ?? "");
  const [one, setOne] = useState(type?.one_per_lease ?? true);
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = nameErrors(language, "st", nameEn, nameKm);
    setErrors(found);
    if (focusFirst(found, ["st-en", "st-km"])) return;
    onSave({
      name_en: nameEn.trim(),
      name_km: nameKm.trim() === "" ? null : nameKm.trim(),
      one_per_lease: one,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={
        type === null
          ? sst(language, "st_add")
          : `${sst(language, "cf_edit")} · ${nameOf(language, type)}`
      }
    >
      <NameFields
        errors={errors}
        language={language}
        nameEn={nameEn}
        nameKm={nameKm}
        onEn={setNameEn}
        onKm={setNameKm}
        prefix="st"
      />
      <fieldset className="ui-radios">
        <legend>{sst(language, "st_rule")}</legend>
        {([true, false] as const).map((value) => (
          <label className="ui-chk" key={String(value)}>
            <input
              checked={one === value}
              name="st-rule"
              onChange={() => {
                setOne(value);
              }}
              type="radio"
            />
            {sst(language, value ? "st_one" : "st_many")}
          </label>
        ))}
      </fieldset>
      <p className="ui-small ui-muted">{sst(language, "st_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

export function ServiceTypesCard({
  language,
  types,
  manage,
  onAdd,
  onEdit,
  onRemove,
}: {
  language: Language;
  types: readonly ServiceType[];
  manage: boolean;
  onAdd: () => void;
  onEdit: (type: ServiceType) => void;
  onRemove: (type: ServiceType) => void;
}) {
  const shown = types.filter((type) => !type.removed);
  return (
    <section aria-labelledby="rates-types" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="rates-types">{sst(language, "st_title")}</h2>
        {manage && (
          <button className="ui-btn" onClick={onAdd} type="button">
            <Icon name="plus" small />
            {sst(language, "st_add")}
          </button>
        )}
      </header>
      {shown.length === 0 ? (
        <p className="pad ui-muted">{sst(language, "st_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{sst(language, "sv_type")}</th>
                <th scope="col">{sst(language, "st_rule")}</th>
                <th className="r" scope="col">
                  {sst(language, "st_count")}
                </th>
                {manage && (
                  <th scope="col">
                    <span className="ui-sr">{sst(language, "cf_edit")}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {shown.map((type) => {
                const name = nameOf(language, type);
                return (
                  <tr key={type.service_type_id}>
                    <td>
                      <b>{name}</b>
                    </td>
                    <td>
                      <Chip tone={type.one_per_lease ? "info" : "neutral"}>
                        {sst(
                          language,
                          type.one_per_lease ? "st_one" : "st_many",
                        )}
                      </Chip>
                    </td>
                    <td className="r ui-num">{type.services}</td>
                    {manage && (
                      <td>
                        <span className="ui-actions">
                          <button
                            aria-label={`${sst(language, "cf_edit")}: ${name}`}
                            className="ui-btn link"
                            onClick={() => {
                              onEdit(type);
                            }}
                            type="button"
                          >
                            {sst(language, "cf_edit")}
                          </button>
                          {type.services === 0 ? (
                            <button
                              aria-label={`${sst(language, "set_remove")}: ${name}`}
                              className="ui-btn link"
                              onClick={() => {
                                onRemove(type);
                              }}
                              type="button"
                            >
                              {sst(language, "set_remove")}
                            </button>
                          ) : (
                            <span className="ui-small ui-muted">
                              {type.services === 1
                                ? sst(language, "st_used1")
                                : sst(language, "st_used", type.services)}
                            </span>
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
      <div className="ui-tfoot">
        <span>{sst(language, "st_note")}</span>
      </div>
    </section>
  );
}
