// V1-058 R3 L2b-2: the New Lease form (DESIGN.md "Leases (round 2)", New Lease and Renew). One
// form makes a walk-in draft, a draft from a Booking (its Unit, Customer, Rent and deposit) or a
// renewal draft (the day after the old End Date, linked to the old Lease). The right column
// previews what will be billed; saving asks once more, then makes the draft and opens it.

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import type { CustomerApi, CustomerListItem } from "../customerClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseDraftSource,
  type LeaseResource,
} from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress } from "../shell/useHashPage";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi, UnitResource } from "../unitClient";
import { addDays, initialRent } from "./leasesData";
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
}

export function LeaseForm({
  language,
  propertyId,
  mode,
  api,
  unitApi,
  customerApi,
  reservationApi,
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
  });
  const request = useRef<{ fingerprint: string; key: string; event: string }>(
    null,
  );

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
      service_terms: [],
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
          {field(
            "lease-form-tenant",
            lt(language, "primary"),
            fixedParty ? (
              <input id="lease-form-tenant" readOnly value={nameOf(tenantId)} />
            ) : (
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
                    {customer.phone_number ? ` · ${customer.phone_number}` : ""}
                  </option>
                ))}
              </select>
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
              <input
                aria-invalid={problems.start !== undefined}
                id="lease-form-start"
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  setStart(value);
                  if (/^\d{4}-\d{2}-\d{2}$/.test(value))
                    setEnd(oneYearEnd(value));
                }}
                type="date"
                value={start}
              />,
              problems.start,
            )}
            {field(
              "lease-form-end",
              lt(language, "end"),
              <input
                aria-invalid={problems.end !== undefined}
                id="lease-form-end"
                onChange={(event) => {
                  setEnd(event.currentTarget.value);
                }}
                type="date"
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
          <p className="ui-small ui-muted">{lt(language, "services_later")}</p>
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
              {pet && <li>{lt(language, "pv_pet")}</li>}
              <li>{lt(language, "pv_end", dayText(end))}</li>
            </ul>
          )}
        </section>
      </form>
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
