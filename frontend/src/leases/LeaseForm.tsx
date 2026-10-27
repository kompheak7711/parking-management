// V1-058 R3 L2b-2: the New Lease form (DESIGN.md "Leases (round 2)", New Lease and Renew). One
// form makes a walk-in draft, a draft from a Booking (its Unit, Customer, Rent and deposit) or a
// renewal draft (the day after the old End Date, linked to the old Lease). The right column
// previews what will be billed; saving asks once more, then makes the draft and opens it.
// R7b-6c: the Services are picked by type (leaseServices.ts) and saved as the Lease's Service
// terms from the Start Date with no end of their own (the server runs them to the End Date).
// R7b-7 (owner 2026-10-26, "Meters decide"): the form says when the Unit has no electricity or
// water meter (nothing of that kind is billed), and a person with Settings access may add a
// Service here with the Settings dialog.

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import type { CustomerApi, CustomerListItem } from "../customerClient";
import type { CustomerCommandGate } from "../customers/commands";
import { NewCustomerDialog } from "../customers/CustomerDialogs";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseDraftSource,
  type LeaseResource,
} from "../leaseClient";
import { metersOn } from "../moveout/finalReadings";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import {
  failureText,
  nameOf as settingsNameOf,
  ServiceDialog,
} from "../settings/ServiceDialogs";
import {
  type ServiceSettings,
  type ServiceSettingsApi,
  ServiceSettingsError,
  serviceSettingsApi,
} from "../settings/serviceSettingsClient";
import { DateInput } from "../shell/DateInput";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress } from "../shell/useHashPage";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi, UnitResource } from "../unitClient";
import { type UtilityApi, utilityApi } from "../utilityClient";
import { addDays, initialRent } from "./leasesData";
import {
  choose,
  defaultChosen,
  type ServiceGroup,
  serviceGroups,
} from "./leaseServices";
import { lt } from "./text";

export type LeaseFormMode =
  | { kind: "new" }
  | { kind: "reservation"; reservationId: string }
  | { kind: "renew"; leaseId: string };

/** "new", "new:<Booking id>" or "renew:<Lease id>" from the page address; null otherwise. */
export function formModeOf(detail: string): LeaseFormMode | null {
  if (detail === "new") return { kind: "new" };
  const parts = detail.split(":");
  if (parts.length !== 2) return null;
  const [head = "", id = ""] = parts;
  if (id === "") return null;
  if (head === "new") return { kind: "reservation", reservationId: id };
  if (head === "renew") return { kind: "renew", leaseId: id };
  return null;
}

/** The last day of the month one year after the Start Date (BR-LEASE: a Lease ends on a month end). */
export function oneYearEnd(start: string): string {
  const [year = 0, month = 0, day = 0] = start.split("-").map(Number);
  const yearLater = new Date(Date.UTC(year + 1, month - 1, day - 1));
  const monthEnd = new Date(
    Date.UTC(yearLater.getUTCFullYear(), yearLater.getUTCMonth() + 1, 0),
  );
  return monthEnd.toISOString().slice(0, 10);
}

function monthEnd(day: string): boolean {
  const [year = 0, month = 0, date = 0] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date + 1)).getUTCDate() === 1;
}

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
function centsOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [dollars = "0", part = ""] = value.split(".");
  const cents = Number(dollars) * 100 + Number(part.padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

// Units a walk-in Lease may use (DL-066); a Reserved Unit comes only with its Booking.
const OPEN_UNITS = new Set(["VACANT", "CLEANING", "UNDER_MAINTENANCE"]);
const MAX_PAGES = 50;

async function allPages<T>(
  load: (
    cursor?: string,
  ) => Promise<{ items: T[]; next_cursor: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await load(cursor);
    items.push(...result.items);
    if (result.next_cursor === null) break;
    cursor = result.next_cursor;
  }
  return items;
}

interface Sources {
  units: UnitResource[];
  customers: CustomerListItem[];
  reservation: ReservationResource | null;
  previous: LeaseResource | null;
}

export interface LeaseFormProps {
  language: Language;
  propertyId: string;
  mode: LeaseFormMode;
  api: LeaseApi;
  unitApi: Pick<UnitApi, "list">;
  customerApi: Pick<CustomerApi, "list">;
  reservationApi: Pick<ReservationApi, "get">;
  /** The Services from Settings; the real server when not given. */
  servicesApi?: Pick<ServiceSettingsApi, "read" | "addService">;
  /** The Unit's meters; the real server when not given. */
  metersApi?: Pick<UtilityApi, "loadMeters">;
  /** V1-060 B6: New Customer beside the Primary Tenant; both are needed to show it. */
  customerCreateApi?: CustomerApi;
  customerGate?: CustomerCommandGate;
}

export function LeaseForm({
  language,
  propertyId,
  mode,
  api,
  unitApi,
  customerApi,
  reservationApi,
  servicesApi = serviceSettingsApi,
  metersApi = utilityApi,
  customerCreateApi,
  customerGate,
}: LeaseFormProps) {
  const today = todayInPhnomPenh();
  const [sources, setSources] = useState<Sources | null>(null);
  const [failed, setFailed] = useState(false);
  const [unitId, setUnitId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [signers, setSigners] = useState<string[]>([]);
  const [occupants, setOccupants] = useState<string[]>([]);
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(oneYearEnd(today));
  const [rent, setRent] = useState("");
  const [pet, setPet] = useState(false);
  // "failed": the draft waits until they are read (Retry).
  const [services, setServices] = useState<ServiceSettings | "failed" | null>(
    null,
  );
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  // The kinds of meter the chosen Unit lacks on the Start Date; null while unknown.
  const [noMeter, setNoMeter] = useState<{
    unitId: string;
    kinds: ("ELECTRICITY" | "WATER")[];
  } | null>(null);
  const [adding, setAdding] = useState(false);
  const [addingCustomer, setAddingCustomer] = useState(false);
  const [addBusy, setAddBusy] = useState(false);
  const [addProblem, setAddProblem] = useState<string | null>(null);
  const [addDone, setAddDone] = useState<string | null>(null);
  // A save the server refused because the id was used before (shown under the Services).
  const [addNote, setAddNote] = useState<string | null>(null);
  // A new Service keeps its id until the server confirms it, so a resend never adds two.
  const newServiceId = useRef<string | null>(null);
  const [petText, setPetText] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<LeaseDraftSource | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<"unknown" | "refused" | null>(null);
  // The Lease and its Signers keep their ids for the life of the form, so a second save after
  // an unknown result can never make a second draft.
  const ids = useRef({
    lease: crypto.randomUUID(),
    primarySigner: crypto.randomUUID(),
    pet: crypto.randomUUID(),
    signers: new Map<string, string>(),
    terms: new Map<string, string>(),
  });
  const request = useRef<{ fingerprint: string; key: string; event: string }>(
    null,
  );

  const servicesRead = useRef(0);
  /** Reads the Services and chooses the defaults for these dates; the newest read wins. */
  const loadServices = (
    previousLease: LeaseResource | null,
    from: string,
    until: string,
  ) => {
    const operation = ++servicesRead.current;
    setServices(null);
    setAddDone(null);
    setAddNote(null);
    servicesApi
      .read(propertyId)
      .then((found) => {
        if (operation !== servicesRead.current) return;
        setServices(found);
        setChosen(
          defaultChosen(
            found,
            from,
            until,
            previousLease === null
              ? null
              : {
                  terms: previousLease.service_terms,
                  endDate: previousLease.end_date,
                },
          ),
        );
      })
      .catch(() => {
        if (operation === servicesRead.current) setServices("failed");
      });
  };

  // The Unit's meters on the Start Date: a kind with none is not billed (owner 2026-10-26).
  // A failed read (or no right to read meters) shows nothing.
  useEffect(() => {
    if (unitId === "" || !/^\d{4}-\d{2}-\d{2}$/.test(start)) {
      setNoMeter(null);
      return;
    }
    const run = { live: true };
    setNoMeter(null);
    void (async () => {
      const found = [];
      let cursor: string | undefined;
      let complete = false;
      for (let page = 0; page < MAX_PAGES && run.live; page += 1) {
        const next = await metersApi.loadMeters(unitId, cursor);
        found.push(...next.items);
        if (next.nextCursor === null) {
          complete = true;
          break;
        }
        cursor = next.nextCursor;
      }
      // A list cut short could miss a meter: say nothing then.
      if (!complete) return;
      const on = metersOn(found, start);
      const kinds = (["ELECTRICITY", "WATER"] as const).filter(
        (kind) => !on.some((meter) => meter.utility_type === kind),
      );
      if (run.live) setNoMeter({ unitId, kinds });
    })().catch(() => {
      if (run.live) setNoMeter(null);
    });
    return () => {
      run.live = false;
    };
  }, [metersApi, unitId, start]);

  /** Reads the Services again after one was added here; the ticks stay as they are. */
  const refreshServices = () => {
    const operation = ++servicesRead.current;
    servicesApi
      .read(propertyId)
      .then((found) => {
        if (operation === servicesRead.current) setServices(found);
      })
      .catch(() => {
        // A failed re-read keeps the list shown (and an open form); the next read updates it.
      });
  };

  const load = () => {
    setFailed(false);
    void (async () => {
      const [units, customers, reservation, previous] = await Promise.all([
        allPages((cursor) =>
          unitApi.list(
            propertyId,
            cursor === undefined ? undefined : { cursor },
          ),
        ),
        allPages((cursor) =>
          customerApi.list(
            propertyId,
            cursor === undefined ? { active: true } : { active: true, cursor },
          ),
        ),
        mode.kind === "reservation"
          ? reservationApi.get(mode.reservationId)
          : Promise.resolve(null),
        mode.kind === "renew" ? api.get(mode.leaseId) : Promise.resolve(null),
      ]);
      setSources({
        units,
        customers: customers.sort((left, right) =>
          left.legal_name.localeCompare(right.legal_name),
        ),
        reservation,
        previous,
      });
      if (reservation !== null) {
        setUnitId(reservation.unit_id);
        setTenantId(reservation.customer_id);
        setRent((reservation.agreed_monthly_rent_usd_cents / 100).toFixed(2));
      }
      if (previous !== null) {
        const next =
          previous.end_date === null ? today : addDays(previous.end_date, 1);
        setUnitId(previous.unit_id);
        setTenantId(previous.primary_tenant_id);
        setStart(next);
        setEnd(oneYearEnd(next));
        if (previous.monthly_rent_usd_cents !== null)
          setRent((previous.monthly_rent_usd_cents / 100).toFixed(2));
        setSigners(
          previous.signers
            .filter((signer) => !signer.is_primary_tenant)
            .map((signer) => signer.customer_id),
        );
        const living = previous.occupancies
          .filter((occupancy) => occupancy.move_out_date === null)
          .map((occupancy) => occupancy.customer_id);
        setOccupants(
          (living.length > 0
            ? living
            : previous.planned_occupant_customer_ids
          ).filter((id) => id !== previous.primary_tenant_id),
        );
        setPet(previous.pet_deposit_required);
        setPetText(previous.pet_description ?? "");
      }
      // A renewal starts with the Services the Lease it renews still had at its end.
      const from =
        previous === null
          ? start
          : previous.end_date === null
            ? today
            : addDays(previous.end_date, 1);
      loadServices(previous, from, previous === null ? end : oneYearEnd(from));
    })().catch(() => {
      setFailed(true);
    });
  };

  useEffect(load, []);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        window.history.back();
      }}
      type="button"
    >
      <Icon name="back" small />
      {lt(language, "back")}
    </button>
  );
  const title =
    mode.kind === "renew"
      ? lt(language, "renew_title")
      : lt(language, "new_title");

  if (sources === null) {
    return (
      <>
        {back}
        {failed ? (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>{lt(language, "form_failed")}</p>
            <button className="ui-btn" onClick={load} type="button">
              {lt(language, "retry")}
            </button>
          </div>
        ) : (
          <p className="ui-muted" role="status">
            {lt(language, "loading")}
          </p>
        )}
      </>
    );
  }

  const { reservation, previous } = sources;
  if (reservation !== null && reservation.status !== "ACTIVE") {
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{lt(language, "booking_not_active", reservation.customer_name)}</p>
        </div>
      </>
    );
  }
  const fixedParty = reservation !== null || previous !== null;
  const nameOf = (id: string) =>
    sources.customers.find((customer) => customer.customer_id === id)
      ?.legal_name ??
    previous?.signers.find((signer) => signer.customer_id === id)
      ?.customer_name ??
    reservation?.customer_name ??
    "—";
  const unitOptions = sources.units
    .filter((unit) => OPEN_UNITS.has(unit.status))
    .sort((left, right) => left.unit_number.localeCompare(right.unit_number));
  const unitNumber =
    sources.units.find((unit) => unit.unit_id === unitId)?.unit_number ??
    reservation?.unit_number ??
    previous?.unit_number ??
    "";
  const cents = centsOf(rent);
  const startOk = /^\d{4}-\d{2}-\d{2}$/.test(start);
  const preview = startOk && cents !== null ? initialRent(start, cents) : null;
  const endOk = /^\d{4}-\d{2}-\d{2}$/.test(end) && end > start;
  const groups =
    services !== null && services !== "failed" && startOk && endOk
      ? serviceGroups(services, start, end)
      : [];
  const picked = groups
    .flatMap((group) => group.choices)
    .filter((choice) => chosen.has(choice.service.service_id));
  const serviceName = (choice: (typeof picked)[number]) =>
    language === "km" && choice.service.name_km !== null
      ? choice.service.name_km
      : choice.service.name_en;
  const heldDeposit =
    reservation === null
      ? null
      : {
          required: reservation.deposit_required_usd_cents,
          received: reservation.deposit_received_usd_cents,
        };

  function pick(
    list: string[],
    set: (next: string[]) => void,
    label: "other_signers" | "other_occupants",
    exclude: string[],
    limit: number,
  ) {
    const choices = sources?.customers.filter(
      (customer) => !exclude.includes(customer.customer_id),
    );
    return (
      <div className="ui-field">
        <label htmlFor={`lease-form-${label}`}>{lt(language, label)}</label>
        {list.length > 0 && (
          <ul className="ui-picked">
            {list.map((id) => (
              <li key={id}>
                <span>{nameOf(id)}</span>
                <button
                  aria-label={lt(language, "remove", nameOf(id))}
                  className="ui-btn link"
                  onClick={() => {
                    set(list.filter((item) => item !== id));
                  }}
                  type="button"
                >
                  <Icon name="x" small />
                </button>
              </li>
            ))}
          </ul>
        )}
        {list.length >= limit ? (
          <p className="help">{lt(language, "limit_reached", limit)}</p>
        ) : (
          <select
            id={`lease-form-${label}`}
            onChange={(event) => {
              const value = event.currentTarget.value;
              if (value !== "") set([...list, value]);
            }}
            value=""
          >
            <option value="">{lt(language, "add_person")}</option>
            {choices?.map((customer) => (
              <option key={customer.customer_id} value={customer.customer_id}>
                {customer.legal_name}
                {customer.phone_number ? ` · ${customer.phone_number}` : ""}
              </option>
            ))}
          </select>
        )}
      </div>
    );
  }

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (unitId === "") found.unit = lt(language, "err_unit");
    if (tenantId === "") found.tenant = lt(language, "err_tenant");
    if (!startOk) found.start = lt(language, "err_start");
    else if (
      previous?.end_date !== null &&
      previous?.end_date !== undefined &&
      start <= previous.end_date
    )
      found.start = lt(language, "err_renew_start", dayText(previous.end_date));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(end) || end <= start || !monthEnd(end))
      found.end = lt(language, "err_end");
    if (cents === null) found.rent = lt(language, "err_rent");
    if (pet && petText.trim() === "") found.pet = lt(language, "err_pet");
    if (services === null || services === "failed")
      found.services = lt(language, "err_svc_wait");
    else if (picked.some((choice) => choice.approvalPeriodId === null))
      found.services = lt(language, "err_svc_greyed");
    else if (picked.length > 20) found.services = lt(language, "err_svc_many");
    setProblems(found);
    if (cents === null || Object.keys(found).length > 0) return;
    const signerIds = ids.current.signers;
    const others = signers.filter((id) => id !== tenantId);
    setConfirm({
      lease_id: ids.current.lease,
      unit_id: unitId,
      primary_tenant_id: tenantId,
      primary_signer_id: ids.current.primarySigner,
      start_date: start,
      end_date: end,
      monthly_rent_usd_cents: cents,
      predecessor_lease_id: previous?.lease_id ?? null,
      additional_signers: others.map((customerId) => {
        const known = signerIds.get(customerId) ?? crypto.randomUUID();
        signerIds.set(customerId, known);
        return { signer_id: known, customer_id: customerId };
      }),
      // Everyone who will live there: the Primary Tenant first, then the others named.
      planned_occupant_customer_ids: [
        tenantId,
        ...occupants.filter((id) => id !== tenantId),
      ],
      service_terms: picked.map((choice) => {
        const serviceId = choice.service.service_id;
        const termId = ids.current.terms.get(serviceId) ?? crypto.randomUUID();
        ids.current.terms.set(serviceId, termId);
        return {
          term_id: termId,
          property_service_id: serviceId,
          applicable_from: start,
          applicable_through: null,
          service_approval_period_id: choice.approvalPeriodId ?? "",
          terms_reference: "Chosen on the New Lease form",
        };
      }),
      pet_term: pet
        ? {
            approval_id: ids.current.pet,
            approved_date: today,
            deposit_required_by_signed_terms: true,
            pet_description: petText.trim(),
          }
        : null,
      security_deposit_id: reservation?.deposit_id ?? null,
      event_id: "",
      reason:
        previous !== null
          ? "Renewal drafted from the New Lease form"
          : reservation !== null
            ? "Lease drafted from the Booking"
            : "Lease drafted from the New Lease form",
    });
  }

  function save() {
    if (confirm === null || busy) return;
    const fingerprint = JSON.stringify(confirm);
    if (request.current?.fingerprint !== fingerprint)
      request.current = {
        fingerprint,
        key: crypto.randomUUID(),
        event: crypto.randomUUID(),
      };
    const chosen = request.current;
    setBusy(true);
    setOutcome(null);
    void api
      .create(propertyId, { ...confirm, event_id: chosen.event }, chosen.key)
      .then((saved) => {
        openPageInAddress("leases", true, saved.lease_id);
      })
      .catch(async (error: unknown) => {
        if (error instanceof LeaseUnavailableError) {
          setOutcome("unknown");
          return;
        }
        // An earlier try whose answer was lost may have saved this Lease already (the id is
        // kept for the life of the form); then a later try is refused. Open it if it is there.
        const saved = await api.get(ids.current.lease).catch(() => null);
        if (saved !== null) {
          openPageInAddress("leases", true, saved.lease_id);
          return;
        }
        setOutcome("refused");
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const field = (
    id: string,
    label: string,
    input: ReactNode,
    problem: string | undefined,
    help?: string,
  ) => (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      {input}
      {help !== undefined && <p className="help">{help}</p>}
      {problem !== undefined && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </div>
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{title}</h2>
          <p>
            {previous !== null
              ? lt(language, "renew_sub", previous.unit_number)
              : reservation !== null
                ? lt(language, "from_booking", reservation.customer_name)
                : lt(language, "new_sub")}
          </p>
        </div>
      </div>
      <form className="ui-split ui-leaseform" noValidate onSubmit={check}>
        <section aria-labelledby="lease-form-terms" className="ui-card ui-form">
          <h2 id="lease-form-terms">{lt(language, "terms")}</h2>
          {field(
            "lease-form-unit",
            lt(language, "unit"),
            fixedParty ? (
              <input id="lease-form-unit" readOnly value={unitNumber} />
            ) : (
              <select
                aria-invalid={problems.unit !== undefined}
                id="lease-form-unit"
                onChange={(event) => {
                  setUnitId(event.currentTarget.value);
                }}
                value={unitId}
              >
                <option value="">{lt(language, "choose_unit")}</option>
                {unitOptions.map((unit) => (
                  <option key={unit.unit_id} value={unit.unit_id}>
                    {unit.unit_number}
                  </option>
                ))}
              </select>
            ),
            problems.unit,
            fixedParty ? undefined : lt(language, "unit_help"),
          )}
          {noMeter !== null &&
            noMeter.unitId === unitId &&
            noMeter.kinds.length > 0 && (
              <p className="ui-small ui-muted" role="status">
                <Icon name="zap" small />{" "}
                {lt(
                  language,
                  noMeter.kinds.length === 2
                    ? "no_meter_both"
                    : noMeter.kinds[0] === "ELECTRICITY"
                      ? "no_meter_e"
                      : "no_meter_w",
                )}
              </p>
            )}
          {field(
            "lease-form-tenant",
            lt(language, "primary"),
            fixedParty ? (
              <input id="lease-form-tenant" readOnly value={nameOf(tenantId)} />
            ) : (
              <div className="ui-pickrow">
                <select
                  aria-invalid={problems.tenant !== undefined}
                  id="lease-form-tenant"
                  onChange={(event) => {
                    setTenantId(event.currentTarget.value);
                  }}
                  value={tenantId}
                >
                  <option value="">{lt(language, "choose_customer")}</option>
                  {sources.customers.map((customer) => (
                    <option
                      key={customer.customer_id}
                      value={customer.customer_id}
                    >
                      {customer.legal_name}
                      {customer.phone_number
                        ? ` · ${customer.phone_number}`
                        : ""}
                    </option>
                  ))}
                </select>
                {customerCreateApi !== undefined &&
                  customerGate !== undefined && (
                    <button
                      aria-label={lt(language, "new_customer")}
                      className="ui-btn ui-iconbtn"
                      onClick={() => {
                        setAddingCustomer(true);
                      }}
                      title={lt(language, "new_customer")}
                      type="button"
                    >
                      <Icon name="userplus" />
                    </button>
                  )}
              </div>
            ),
            problems.tenant,
          )}
          {pick(
            signers,
            setSigners,
            "other_signers",
            [tenantId, ...signers],
            19,
          )}
          {/* At most 20 occupants with the Primary Tenant, and 19 other Signers. */}
          {pick(
            occupants,
            setOccupants,
            "other_occupants",
            [tenantId, ...occupants],
            19,
          )}
          <div className="ui-row2">
            {field(
              "lease-form-start",
              lt(language, "start"),
              <DateInput
                language={language}
                invalid={problems.start !== undefined}
                id="lease-form-start"
                onChange={(value) => {
                  setStart(value);
                  if (/^\d{4}-\d{2}-\d{2}$/.test(value))
                    setEnd(oneYearEnd(value));
                }}
                value={start}
              />,
              problems.start,
            )}
            {field(
              "lease-form-end",
              lt(language, "end"),
              <DateInput
                language={language}
                invalid={problems.end !== undefined}
                id="lease-form-end"
                onChange={(value) => {
                  setEnd(value);
                }}
                value={end}
              />,
              problems.end,
              lt(language, "end_help"),
            )}
          </div>
          {field(
            "lease-form-rent",
            lt(language, "rent"),
            <input
              aria-invalid={problems.rent !== undefined}
              id="lease-form-rent"
              inputMode="decimal"
              onChange={(event) => {
                setRent(event.currentTarget.value);
              }}
              value={rent}
            />,
            problems.rent,
          )}
          <label className="ui-chk">
            <input
              checked={pet}
              onChange={(event) => {
                setPet(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            <span>{lt(language, "pet_ok")}</span>
          </label>
          {pet &&
            field(
              "lease-form-pet",
              lt(language, "pet_what"),
              <input
                aria-invalid={problems.pet !== undefined}
                id="lease-form-pet"
                maxLength={200}
                onChange={(event) => {
                  setPetText(event.currentTarget.value);
                }}
                value={petText}
              />,
              problems.pet,
              lt(language, "pet_help"),
            )}
          <ServicesField
            added={addDone}
            addNote={addNote}
            chosen={chosen}
            groups={groups}
            language={language}
            onAdd={
              services !== null && services !== "failed" && services.can_manage
                ? () => {
                    setAddProblem(null);
                    setAddDone(null);
                    setAddNote(null);
                    setAdding(true);
                  }
                : undefined
            }
            onChange={setChosen}
            onRetry={() => {
              loadServices(previous, start, end);
            }}
            problem={problems.services}
            state={
              services === null
                ? "loading"
                : services === "failed"
                  ? "failed"
                  : startOk && endOk
                    ? "ready"
                    : "dates"
            }
          />
          <div className="ui-dlg-buttons">
            <button className="ui-btn primary" type="submit">
              {lt(language, "save_draft")}
            </button>
          </div>
        </section>
        <section aria-labelledby="lease-form-preview" className="ui-card">
          <h2 id="lease-form-preview">{lt(language, "preview")}</h2>
          {preview === null || cents === null ? (
            <p className="ui-muted">{lt(language, "preview_wait")}</p>
          ) : (
            <ul className="ui-small">
              <li>
                {lt(
                  language,
                  "pv_initial",
                  usdFromCents(preview.total),
                  dayText(preview.due),
                )}
                <span className="ui-sub2">
                  {lt(
                    language,
                    "pv_initial_how",
                    usdFromCents(cents),
                    preview.days,
                    preview.daysInMonth,
                    usdFromCents(preview.firstPart),
                  )}
                  {preview.nextMonth > 0 &&
                    ` ${lt(language, "pv_next_month", usdFromCents(preview.nextMonth))}`}
                </span>
              </li>
              <li>{lt(language, "pv_monthly", usdFromCents(cents))}</li>
              <li>
                {previous !== null
                  ? lt(language, "pv_renewal")
                  : heldDeposit === null
                    ? lt(language, "pv_deposit_walkin", usdFromCents(cents))
                    : heldDeposit.received >= heldDeposit.required
                      ? lt(
                          language,
                          "pv_deposit_full",
                          usdFromCents(heldDeposit.received),
                        )
                      : lt(
                          language,
                          "pv_deposit_booking",
                          usdFromCents(heldDeposit.received),
                          usdFromCents(heldDeposit.required),
                          usdFromCents(
                            Math.max(
                              0,
                              heldDeposit.required - heldDeposit.received,
                            ),
                          ),
                          dayText(preview.due),
                        )}
              </li>
              {picked.map((choice) => (
                <li key={choice.service.service_id}>
                  {choice.rateCents === null
                    ? lt(language, "pv_service_no_rate", serviceName(choice))
                    : lt(
                        language,
                        "pv_service",
                        serviceName(choice),
                        usdFromCents(choice.rateCents),
                      )}
                </li>
              ))}
              {pet && <li>{lt(language, "pv_pet")}</li>}
              <li>{lt(language, "pv_end", dayText(end))}</li>
            </ul>
          )}
        </section>
      </form>
      {addingCustomer &&
        customerCreateApi !== undefined &&
        customerGate !== undefined && (
          <NewCustomerDialog
            api={customerCreateApi}
            gate={customerGate}
            language={language}
            onClose={() => {
              setAddingCustomer(false);
            }}
            onSaved={(customer) => {
              setSources((current) =>
                current === null
                  ? current
                  : {
                      ...current,
                      customers: [
                        ...current.customers.filter(
                          (item) => item.customer_id !== customer.customer_id,
                        ),
                        {
                          customer_id: customer.customer_id,
                          legal_name: customer.legal_name,
                          phone_number: customer.phone_number ?? null,
                          active: true,
                          relationship_indicators: [],
                        },
                      ].sort((left, right) =>
                        left.legal_name.localeCompare(right.legal_name),
                      ),
                    },
              );
              setTenantId(customer.customer_id);
              setAddingCustomer(false);
            }}
            propertyId={propertyId}
          />
        )}
      {adding && services !== null && services !== "failed" && (
        <ServiceDialog
          busy={addBusy}
          language={language}
          onClose={() => {
            if (!addBusy) setAdding(false);
          }}
          onSave={(form) => {
            if (form.first === null) return;
            const serviceId = newServiceId.current ?? crypto.randomUUID();
            newServiceId.current = serviceId;
            const name = settingsNameOf(language, form);
            setAddBusy(true);
            setAddProblem(null);
            servicesApi
              .addService(propertyId, {
                service_id: serviceId,
                name_en: form.name_en,
                name_km: form.name_km,
                service_type_id: form.service_type_id,
                monthly_rate_usd_cents: form.first.cents,
                starts_on: form.first.starts_on,
              })
              .then(
                () => {
                  newServiceId.current = null;
                  setAdding(false);
                  setAddDone(name);
                  refreshServices();
                },
                (error: unknown) => {
                  const found =
                    error instanceof ServiceSettingsError
                      ? error.failure
                      : "unknown";
                  if (found === "id_reused") {
                    // An earlier send whose answer was lost saved other values under this id:
                    // the form closes, says so, and the list shows what was saved (as RatesTab).
                    newServiceId.current = null;
                    setAdding(false);
                    setAddDone(null);
                    setAddProblem(null);
                    setAddNote(failureText(language, found));
                    refreshServices();
                    return;
                  }
                  setAddProblem(failureText(language, found));
                  // The answer may have been lost after a save: read the list again.
                  if (found === "unknown" || found === "out_of_date") {
                    refreshServices();
                  }
                },
              )
              .finally(() => {
                setAddBusy(false);
              });
          }}
          problem={addProblem}
          service={null}
          today={services.today}
          types={services.service_types}
        />
      )}
      {confirm !== null && (
        <Dialog
          busy={busy}
          closeLabel={lt(language, "close")}
          onClose={() => {
            setConfirm(null);
            setOutcome(null);
          }}
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
          submitLabel={
            busy
              ? lt(language, "saving")
              : outcome === "unknown"
                ? lt(language, "try_again")
                : lt(language, "save_draft")
          }
          title={lt(language, "confirm_title", unitNumber)}
        >
          <p className="ui-small ui-num">
            {nameOf(tenantId)} ·{" "}
            {lt(language, "from_to", dayText(start), dayText(end))} ·{" "}
            {lt(language, "rent_month", usdFromCents(cents ?? 0))}
          </p>
          <p className="ui-small">
            {picked.length === 0
              ? lt(language, "confirm_no_services")
              : lt(
                  language,
                  "confirm_services",
                  picked.map(serviceName).join(", "),
                )}
          </p>
          <p className="ui-small">{lt(language, "confirm_note")}</p>
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>
                {lt(
                  language,
                  outcome === "unknown" ? "unknown" : "draft_refused",
                )}
              </p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}

function ServicesField({
  language,
  state,
  groups,
  chosen,
  problem,
  added,
  addNote,
  onChange,
  onRetry,
  onAdd,
}: {
  language: Language;
  state: "loading" | "failed" | "dates" | "ready";
  groups: ServiceGroup[];
  chosen: ReadonlySet<string>;
  problem: string | undefined;
  /** The name of a Service just added here. */
  added: string | null;
  /** Why the last New Service was not added as typed. */
  addNote: string | null;
  onChange: (next: Set<string>) => void;
  onRetry: () => void;
  /** Only for a person with Settings access. */
  onAdd?: () => void;
}) {
  const groupName = (group: ServiceGroup) =>
    group.nameEn === null
      ? lt(language, "svc_other")
      : language === "km" && group.nameKm !== null
        ? group.nameKm
        : group.nameEn;
  return (
    <section aria-labelledby="lease-form-services" className="ui-svcpick">
      <h3 className="ui-small" id="lease-form-services">
        {lt(language, "services_t")}
      </h3>
      {onAdd !== undefined && (
        <button className="ui-btn" onClick={onAdd} type="button">
          <Icon name="plus" small />
          {lt(language, "svc_new")}
        </button>
      )}
      {added !== null && (
        <p className="ui-small" role="status">
          {lt(language, "svc_added", added)}
        </p>
      )}
      {addNote !== null && (
        <p className="ui-small ui-muted" role="status">
          {addNote}
        </p>
      )}
      {state === "loading" && (
        <p className="ui-small ui-muted" role="status">
          {lt(language, "svc_loading")}
        </p>
      )}
      {state === "failed" && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{lt(language, "svc_failed")}</p>
          <button className="ui-btn" onClick={onRetry} type="button">
            {lt(language, "retry")}
          </button>
        </div>
      )}
      {state === "dates" && (
        <p className="ui-small ui-muted">{lt(language, "svc_dates")}</p>
      )}
      {state === "ready" && groups.length === 0 && (
        <p className="ui-small ui-muted">{lt(language, "svc_none")}</p>
      )}
      {state === "ready" &&
        groups.map((group) => {
          const name = `lease-svc-${group.typeId ?? "other"}`;
          return (
            <fieldset
              aria-describedby={
                problem === undefined ? undefined : "lease-form-services-e"
              }
              className="ui-radios"
              key={name}
            >
              <legend>
                {groupName(group)}
                <span className="ui-sub2">
                  {lt(language, group.onePerLease ? "svc_one" : "svc_many")}
                </span>
              </legend>
              {group.onePerLease && (
                <label className="ui-chk">
                  <input
                    checked={group.choices.every(
                      (choice) => !chosen.has(choice.service.service_id),
                    )}
                    name={name}
                    onChange={() => {
                      onChange(choose(chosen, group, null, true));
                    }}
                    type="radio"
                  />
                  <span>{lt(language, "svc_none_pick")}</span>
                </label>
              )}
              {group.choices.map((choice) => {
                const id = choice.service.service_id;
                const closed = choice.approvalPeriodId === null;
                const on = chosen.has(id);
                const label =
                  language === "km" && choice.service.name_km !== null
                    ? choice.service.name_km
                    : choice.service.name_en;
                return (
                  <label className={closed ? "ui-chk off" : "ui-chk"} key={id}>
                    <input
                      checked={on}
                      // A greyed Service that is still ticked can be unticked.
                      disabled={closed && !on}
                      name={name}
                      onChange={(event) => {
                        onChange(
                          choose(
                            chosen,
                            group,
                            id,
                            event.currentTarget.checked,
                          ),
                        );
                      }}
                      type={group.onePerLease ? "radio" : "checkbox"}
                    />
                    <span>
                      {label}
                      <span className="ui-sub2 ui-num">
                        {closed
                          ? choice.startsLater !== null
                            ? lt(
                                language,
                                "svc_starts",
                                dayText(choice.startsLater),
                              )
                            : lt(language, "svc_closed")
                          : choice.rateCents === null
                            ? lt(language, "svc_no_rate")
                            : lt(
                                language,
                                "svc_rate",
                                usdFromCents(choice.rateCents),
                              )}
                      </span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
          );
        })}
      {problem !== undefined && (
        <p className="ui-error" id="lease-form-services-e" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </section>
  );
}
