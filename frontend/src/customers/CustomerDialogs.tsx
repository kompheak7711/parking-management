// V1-058 R2 step C2: Add Customer (a form page), Edit contact and Deactivate (dialogs), from
// DESIGN.md "Customers (round 2)" (owner, 13/10/2026 18:27). The saves are in commands.ts.

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import {
  CustomerConflictError,
  CustomerIdNumberInUseError,
  type CustomerApi,
  type CustomerDetail,
  type CustomerGender,
  type CustomerListItem,
  type CustomerSource,
} from "../customerClient";
import { DateInput, isDay } from "../shell/DateInput";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type CommandResult,
  type CustomerCommandGate,
  changedFields,
  cleanText,
  createCustomer,
  deactivateCustomer,
  updateCustomer,
} from "./commands";
import { ct } from "./text";

type Field =
  | "legal_name"
  | "date_of_birth"
  | "gender"
  | "nationality"
  | "id_document_number"
  | "phone_number"
  | "email_address"
  | "contact_address"
  | "memo";

type Values = Record<Field, string>;

const EMPTY: Values = {
  legal_name: "",
  date_of_birth: "",
  gender: "",
  nationality: "",
  id_document_number: "",
  phone_number: "",
  email_address: "",
  contact_address: "",
  memo: "",
};

function valuesOf(customer: CustomerDetail): Values {
  return {
    legal_name: customer.legal_name,
    date_of_birth: customer.date_of_birth ?? "",
    gender: customer.gender ?? "",
    nationality: customer.nationality ?? "",
    id_document_number: customer.id_document_number ?? "",
    phone_number: customer.phone_number ?? "",
    email_address: customer.email_address ?? "",
    contact_address: customer.contact_address ?? "",
    memo: customer.memo ?? "",
  };
}

function sourceOf(values: Values): CustomerSource {
  return {
    legal_name: cleanText(values.legal_name) ?? "",
    date_of_birth: cleanText(values.date_of_birth),
    gender:
      values.gender === "FEMALE" || values.gender === "MALE"
        ? (values.gender as CustomerGender)
        : null,
    nationality: cleanText(values.nationality),
    id_document_number: cleanText(values.id_document_number),
    phone_number: cleanText(values.phone_number),
    email_address: cleanText(values.email_address),
    contact_address: cleanText(values.contact_address),
    memo: cleanText(values.memo),
  };
}

type Problems = Partial<Record<Field, string>>;

/** The same checks the earlier form and the server make, before anything is sent. */
function check(
  language: Language,
  source: CustomerSource,
  idRequired: boolean,
): Problems {
  const problems: Problems = {};
  if (source.legal_name === "") problems.legal_name = ct(language, "e_name");
  if (idRequired && source.id_document_number == null)
    problems.id_document_number = ct(language, "e_id");
  const phone = source.phone_number;
  if (phone != null && !(/[0-9]/.test(phone) && /^[0-9+(). -]*$/.test(phone)))
    problems.phone_number = ct(language, "e_phone");
  const email = source.email_address;
  if (email != null && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))
    problems.email_address = ct(language, "e_email");
  const birth = source.date_of_birth;
  if (birth != null && !isDay(birth))
    problems.date_of_birth = ct(language, "e_dob");
  return problems;
}

function Problem({ message }: { message: string | undefined | null }) {
  if (message == null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{message}</span>
    </p>
  );
}

function CustomerFields({
  language,
  values,
  problems,
  idRequired,
  onChange,
}: {
  language: Language;
  values: Values;
  problems: Problems;
  idRequired: boolean;
  onChange: (field: Field, value: string) => void;
}) {
  const required = <span className="req">{ct(language, "required")}</span>;
  const box = (
    field: Field,
    label: ReactNode,
    input: Partial<React.InputHTMLAttributes<HTMLInputElement>> = {},
  ) => (
    <div className="ui-field">
      <label htmlFor={`customer-${field}`}>{label}</label>
      <input
        aria-invalid={problems[field] !== undefined}
        id={`customer-${field}`}
        onChange={(event) => {
          onChange(field, event.currentTarget.value);
        }}
        value={values[field]}
        {...input}
      />
      <Problem message={problems[field]} />
    </div>
  );
  return (
    <>
      {box(
        "legal_name",
        <>
          {ct(language, "name_full")}
          {required}
        </>,
        { maxLength: 255, autoComplete: "off" },
      )}
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="customer-date_of_birth">{ct(language, "dob")}</label>
          <DateInput
            language={language}
            id="customer-date_of_birth"
            invalid={problems.date_of_birth !== undefined}
            max={todayInPhnomPenh()}
            onChange={(value) => {
              onChange("date_of_birth", value);
            }}
            value={values.date_of_birth}
          />
          <Problem message={problems.date_of_birth} />
        </div>
        <div className="ui-field">
          <label htmlFor="customer-gender">{ct(language, "gender")}</label>
          <select
            id="customer-gender"
            onChange={(event) => {
              onChange("gender", event.currentTarget.value);
            }}
            value={values.gender}
          >
            <option value="">{ct(language, "not_recorded")}</option>
            <option value="FEMALE">{ct(language, "g_FEMALE")}</option>
            <option value="MALE">{ct(language, "g_MALE")}</option>
          </select>
        </div>
      </div>
      <div className="ui-row2">
        {box("nationality", ct(language, "nationality"), {
          maxLength: 64,
          placeholder: ct(language, "nationality_ph"),
        })}
        {box(
          "id_document_number",
          <>
            {ct(language, "idno")}
            {idRequired && required}
          </>,
          { maxLength: 64, autoComplete: "off" },
        )}
      </div>
      <div className="ui-row2">
        {box("phone_number", ct(language, "phone"), {
          maxLength: 100,
          inputMode: "tel",
          type: "tel",
        })}
        {box("email_address", ct(language, "email"), {
          maxLength: 320,
          type: "email",
        })}
      </div>
      {box("contact_address", ct(language, "address"), { maxLength: 1000 })}
      <div className="ui-field">
        <label htmlFor="customer-memo">{ct(language, "memo")}</label>
        <textarea
          id="customer-memo"
          maxLength={5000}
          onChange={(event) => {
            onChange("memo", event.currentTarget.value);
          }}
          rows={3}
          value={values.memo}
        />
      </div>
    </>
  );
}

/** Other Customers the server named: same phone or name (a warning), or the same ID number. */
function Matches({ matches }: { matches: CustomerListItem[] }) {
  return (
    <ul className="ui-matches">
      {matches.map((match) => (
        <li key={match.customer_id}>
          <a href={hashForPage("customers", match.customer_id)}>
            {match.legal_name}
          </a>
        </li>
      ))}
    </ul>
  );
}

/** What a finished save means for the person, in their language. */
function outcomeText(
  language: Language,
  result: Exclude<CommandResult, { kind: "saved" }>,
): string {
  if (result.kind === "blocked") return ct(language, "blocked");
  if (result.kind === "unknown") return ct(language, "unknown");
  return ct(language, "refused");
}

function Notice({
  tone,
  children,
}: {
  tone: "warn" | "err";
  children: ReactNode;
}) {
  return (
    <div className={`ui-notice ${tone === "err" ? "warn" : tone}`} role="alert">
      <Icon name="alert" />
      <div>{children}</div>
    </div>
  );
}

export interface AddCustomerProps {
  language: Language;
  api: CustomerApi;
  gate: CustomerCommandGate;
  propertyId: string;
  onCancel: () => void;
  onSaved: (customer: CustomerDetail) => void;
  onDirty: (dirty: boolean) => void;
  /** V1-060 B6: shown inside a dialog, which gives the title; no Back link or page head. */
  inDialog?: boolean;
}

/** "Add Customer" is a form page, not a dialog (owner, 13/10/2026 18:27). */
export function AddCustomerPage({
  language,
  api,
  gate,
  propertyId,
  onCancel,
  onSaved,
  onDirty,
  inDialog = false,
}: AddCustomerProps) {
  const [values, setValues] = useState<Values>(EMPTY);
  const [problems, setProblems] = useState<Problems>({});
  const [busy, setBusy] = useState(false);
  const [matches, setMatches] = useState<CustomerListItem[]>([]);
  const [distinct, setDistinct] = useState(false);
  const [idTaken, setIdTaken] = useState<CustomerListItem[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [again, setAgain] = useState<(() => Promise<CommandResult>) | null>(
    null,
  );

  useEffect(() => {
    onDirty(Object.values(values).some((value) => value !== ""));
  }, [onDirty, values]);
  // A save that ends after the person left this page must not pull them back to it.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onDirty(false);
    };
  }, [onDirty]);

  function finish(result: CommandResult) {
    if (!mounted.current) return;
    setBusy(false);
    if (result.kind === "saved") {
      onDirty(false);
      onSaved(result.customer);
      return;
    }
    setAgain(result.kind === "unknown" ? () => result.again : null);
    if (result.kind === "refused") {
      const error = result.error;
      if (error instanceof CustomerIdNumberInUseError) {
        setIdTaken(error.candidates);
        setProblems({ id_document_number: ct(language, "e_id_taken") });
        return;
      }
      if (error instanceof CustomerConflictError && error.candidates.length) {
        setMatches(error.candidates);
        setDistinct(false);
        return;
      }
    }
    setFailure(outcomeText(language, result));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    setIdTaken(null);
    if (again !== null) {
      setBusy(true);
      void again().then(finish);
      return;
    }
    const source = sourceOf(values);
    const found = check(language, source, true);
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    if (matches.length > 0 && !distinct) {
      setFailure(ct(language, "tick_distinct"));
      return;
    }
    setBusy(true);
    void createCustomer(api, gate, propertyId, {
      ...source,
      ...(matches.length > 0 ? { confirmed_distinct: true } : {}),
    }).then(finish);
  }

  return (
    <>
      {!inDialog && (
        <>
          <button className="ui-crumb" onClick={onCancel} type="button">
            <Icon name="back" small />
            {ct(language, "back")}
          </button>
          <div className="ui-head">
            <div>
              <h2>{ct(language, "add")}</h2>
              <p>{ct(language, "add_sub")}</p>
            </div>
          </div>
        </>
      )}
      <form
        aria-label={ct(language, "add")}
        className="ui-card ui-form ui-formpage"
        noValidate
        onSubmit={submit}
      >
        <CustomerFields
          idRequired
          language={language}
          onChange={(field, value) => {
            if (again !== null) return;
            setValues((current) => ({ ...current, [field]: value }));
            if (field === "legal_name" || field === "phone_number") {
              setMatches([]);
              setDistinct(false);
            }
          }}
          problems={problems}
          values={values}
        />
        {idTaken !== null && idTaken.length > 0 && (
          <Notice tone="err">
            <p>{ct(language, "id_taken_open")}</p>
            <Matches matches={idTaken} />
          </Notice>
        )}
        {matches.length > 0 && (
          <Notice tone="warn">
            <p>{ct(language, "maybe_same")}</p>
            <Matches matches={matches} />
            <label className="ui-chk">
              <input
                checked={distinct}
                onChange={(event) => {
                  setDistinct(event.currentTarget.checked);
                }}
                type="checkbox"
              />
              {ct(language, "distinct")}
            </label>
          </Notice>
        )}
        {failure !== null && (
          <Notice tone="err">
            <p>{failure}</p>
          </Notice>
        )}
        <div className="ui-dlg-buttons">
          <button
            className="ui-btn"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            {ct(language, "cancel")}
          </button>
          <button className="ui-btn primary" disabled={busy} type="submit">
            {busy
              ? ct(language, "saving")
              : again !== null
                ? ct(language, "try_again")
                : ct(language, "save_customer")}
          </button>
        </div>
      </form>
    </>
  );
}

export function EditContactDialog({
  language,
  api,
  gate,
  propertyId,
  customer,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: CustomerApi;
  gate: CustomerCommandGate;
  propertyId: string;
  customer: CustomerDetail;
  onClose: () => void;
  onSaved: (customer: CustomerDetail) => void;
  /** Someone else changed the Customer first; the page reads it again. */
  onConflict: () => void;
}) {
  const [values, setValues] = useState<Values>(() => valuesOf(customer));
  const [problems, setProblems] = useState<Problems>({});
  const [busy, setBusy] = useState(false);
  const [matches, setMatches] = useState<CustomerListItem[]>([]);
  const [distinct, setDistinct] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [again, setAgain] = useState<(() => Promise<CommandResult>) | null>(
    null,
  );

  function finish(result: CommandResult) {
    setBusy(false);
    if (result.kind === "saved") {
      onSaved(result.customer);
      return;
    }
    setAgain(result.kind === "unknown" ? () => result.again : null);
    if (result.kind === "refused") {
      const error = result.error;
      if (error instanceof CustomerIdNumberInUseError) {
        setMatches([]);
        setProblems({ id_document_number: ct(language, "e_id_taken") });
        return;
      }
      if (error instanceof CustomerConflictError) {
        if (error.candidates.length > 0) {
          setMatches(error.candidates);
          setDistinct(false);
          return;
        }
        onConflict();
        return;
      }
    }
    setFailure(outcomeText(language, result));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    if (again !== null) {
      setBusy(true);
      void again().then(finish);
      return;
    }
    const source = sourceOf(values);
    // An ID number already recorded cannot be emptied; one never recorded may stay empty.
    const found = check(language, source, customer.id_document_number !== null);
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const changed = changedFields(customer, source);
    if (Object.keys(changed).length === 0) {
      setFailure(ct(language, "nothing_changed"));
      return;
    }
    if (matches.length > 0 && !distinct) {
      setFailure(ct(language, "tick_distinct"));
      return;
    }
    setBusy(true);
    void updateCustomer(api, gate, propertyId, customer, {
      ...changed,
      ...(matches.length > 0 ? { confirmed_distinct: true } : {}),
    }).then(finish);
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ct(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? ct(language, "saving")
          : again !== null
            ? ct(language, "try_again")
            : ct(language, "save")
      }
      title={ct(language, "edit_title", customer.legal_name)}
    >
      <p className="ui-small ui-muted">{ct(language, "contact_note")}</p>
      <CustomerFields
        idRequired={customer.id_document_number !== null}
        language={language}
        onChange={(field, value) => {
          if (again !== null) return;
          setValues((current) => ({ ...current, [field]: value }));
          if (field === "legal_name" || field === "phone_number") {
            setMatches([]);
            setDistinct(false);
          }
        }}
        problems={problems}
        values={values}
      />
      {matches.length > 0 && (
        <Notice tone="warn">
          <p>{ct(language, "maybe_same")}</p>
          <Matches matches={matches} />
          <label className="ui-chk">
            <input
              checked={distinct}
              onChange={(event) => {
                setDistinct(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            {ct(language, "distinct")}
          </label>
        </Notice>
      )}
      {failure !== null && (
        <Notice tone="err">
          <p>{failure}</p>
        </Notice>
      )}
    </Dialog>
  );
}

export function DeactivateDialog({
  language,
  api,
  gate,
  propertyId,
  customer,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: CustomerApi;
  gate: CustomerCommandGate;
  propertyId: string;
  customer: CustomerDetail;
  onClose: () => void;
  onSaved: (customer: CustomerDetail) => void;
  onConflict: () => void;
}) {
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [again, setAgain] = useState<(() => Promise<CommandResult>) | null>(
    null,
  );

  function finish(result: CommandResult) {
    setBusy(false);
    if (result.kind === "saved") {
      onSaved(result.customer);
      return;
    }
    setAgain(result.kind === "unknown" ? () => result.again : null);
    if (
      result.kind === "refused" &&
      result.error instanceof CustomerConflictError
    ) {
      onConflict();
      return;
    }
    setFailure(outcomeText(language, result));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    if (again !== null) {
      setBusy(true);
      void again().then(finish);
      return;
    }
    const text = cleanText(reason);
    setMissing(text === null);
    if (text === null) return;
    setBusy(true);
    void deactivateCustomer(api, gate, propertyId, customer, text).then(finish);
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ct(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? ct(language, "saving")
          : again !== null
            ? ct(language, "try_again")
            : ct(language, "deactivate")
      }
      title={ct(language, "deactivate_title", customer.legal_name)}
    >
      <p>{ct(language, "deactivate_note")}</p>
      <div className="ui-field">
        <label htmlFor="customer-deactivation-reason">
          {ct(language, "reason")}
          <span className="req">{ct(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={missing}
          id="customer-deactivation-reason"
          maxLength={1000}
          onChange={(event) => {
            if (again === null) setReason(event.currentTarget.value);
          }}
          rows={3}
          value={reason}
        />
        <Problem message={missing ? ct(language, "e_reason") : null} />
      </div>
      {failure !== null && (
        <Notice tone="err">
          <p>{failure}</p>
        </Notice>
      )}
    </Dialog>
  );
}

/** V1-060 B6 (owner 27/10/2026): Add Customer from another form (New Lease, Make Reservation). */
export function NewCustomerDialog({
  language,
  api,
  gate,
  propertyId,
  onClose,
  onSaved,
}: {
  language: Language;
  api: CustomerApi;
  gate: CustomerCommandGate;
  propertyId: string;
  onClose: () => void;
  onSaved: (customer: CustomerDetail) => void;
}) {
  return (
    <Dialog
      closeLabel={ct(language, "cancel")}
      noButtons
      onClose={onClose}
      title={ct(language, "add")}
      wide
    >
      <AddCustomerPage
        api={api}
        gate={gate}
        inDialog
        language={language}
        onCancel={onClose}
        onDirty={() => undefined}
        onSaved={onSaved}
        propertyId={propertyId}
      />
    </Dialog>
  );
}
