import { FormEvent, useRef, useState } from "react";

import {
  CancellationResponsibility,
  ReservationApi,
  ReservationConflictError,
  ReservationResource,
  ReservationStatus,
  ReservationUnavailableError,
  reservationApi,
} from "./reservationClient";

export interface ReservationManagementProps {
  api?: ReservationApi;
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function cents(value: string): number {
  return Math.round(Number(value) * 100);
}

function message(error: unknown): string {
  if (error instanceof ReservationUnavailableError) return error.message;
  if (error instanceof ReservationConflictError) return error.message;
  return "The Reservation request was not completed. Review the fields and retry.";
}

function money(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value / 100);
}

export function ReservationManagement({
  api = reservationApi,
}: ReservationManagementProps) {
  const [propertyId, setPropertyId] = useState("");
  const [filter, setFilter] = useState<ReservationStatus | "">("");
  const [items, setItems] = useState<ReservationResource[]>([]);
  const [selected, setSelected] = useState<ReservationResource | null>(null);
  const [canCreate, setCanCreate] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [extensionResult, setExtensionResult] = useState("");
  const sequence = useRef(0);

  function update(resource: ReservationResource) {
    setSelected(resource);
    setItems((current) =>
      current.map((candidate) =>
        candidate.reservation_id === resource.reservation_id
          ? resource
          : candidate,
      ),
    );
  }

  function loadPage(cursor?: string) {
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Loading Reservations…");
    void api
      .list(propertyId, filter || undefined, cursor)
      .then((page) => {
        if (operation !== sequence.current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
        setCanCreate(page.can_create);
        setSelected(null);
        setNotice(
          page.items.length === 0
            ? "No Reservations matched this Property and status."
            : `${String(page.items.length)} Reservation record(s) loaded.`,
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setItems([]);
        setNextCursor(null);
        setSelected(null);
        setCanCreate(false);
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loadPage();
  }

  function open(reservationId: string) {
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Loading Reservation detail and permanent history…");
    void api
      .get(reservationId)
      .then((value) => {
        if (operation !== sequence.current) return;
        setSelected(value);
        setNotice("Reservation detail loaded.");
      })
      .catch((error: unknown) => {
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const rent = cents(formString(data, "rent"));
    const accepted = cents(formString(data, "accepted-deposit"));
    const operation = ++sequence.current;
    setBusy(true);
    setNotice(
      accepted === Math.floor((rent + 2) / 5)
        ? "Creating the Reservation with the normal 20% Security Deposit suggestion…"
        : "Submitting the explicit Security Deposit variance for authorization…",
    );
    const now = new Date().toISOString();
    void api
      .create(
        propertyId,
        {
          reservation_id: crypto.randomUUID(),
          unit_id: formString(data, "unit-id"),
          customer_id: formString(data, "customer-id"),
          reservation_date: formString(data, "reservation-date"),
          agreed_monthly_rent_usd_cents: rent,
          expiration_date: formString(data, "expiration-date"),
          acceptance_id: crypto.randomUUID(),
          accepted_initial_deposit_usd_cents: accepted,
          required_security_deposit_usd_cents: cents(
            formString(data, "required-deposit"),
          ),
          acceptance_reason: formString(data, "acceptance-reason"),
          deposit_id: crypto.randomUUID(),
          receipt_id: crypto.randomUUID(),
          payment_id: formString(data, "payment-id"),
          received_at: now,
        },
        crypto.randomUUID(),
      )
      .then((created) => {
        if (operation !== sequence.current) return;
        setItems((current) => [created, ...current]);
        setSelected(created);
        setNotice(
          "Reservation created ACTIVE with Security Deposit receipt continuity.",
        );
        form.reset();
      })
      .catch((error: unknown) => {
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function extend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Recording the one permitted Extension Notice…");
    void api
      .extend(
        selected,
        {
          notice_id: crypto.randomUUID(),
          new_expiration_date: formString(data, "new-expiration-date"),
          approved_at: new Date().toISOString(),
          reason_memo: formString(data, "extension-reason"),
        },
        crypto.randomUUID(),
      )
      .then((value) => {
        if (operation !== sequence.current) return;
        update(value);
        setNotice(
          "Extension recorded without replacing original date history.",
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function cancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const responsibility = formString(
      data,
      "responsibility",
    ) as CancellationResponsibility;
    if (
      !window.confirm(
        "Cancel this ACTIVE Reservation and apply the displayed Deposit outcome?",
      )
    ) {
      setNotice("Cancellation was not submitted.");
      return;
    }
    const operation = ++sequence.current;
    setBusy(true);
    setNotice(
      "Applying the classified cancellation and linked Deposit outcome…",
    );
    void api
      .cancel(
        selected,
        {
          event_id: crypto.randomUUID(),
          outcome_id: crypto.randomUUID(),
          reason_code: formString(data, "cancellation-reason-code"),
          responsibility,
          property_could_provide_unit: responsibility === "CUSTOMER",
          reason_memo: formString(data, "cancellation-reason"),
          coordination_reference:
            responsibility === "PROPERTY"
              ? formString(data, "coordination-reference")
              : null,
          refund_number:
            responsibility === "PROPERTY"
              ? formString(data, "refund-number")
              : null,
        },
        crypto.randomUUID(),
      )
      .then((value) => {
        if (operation !== sequence.current) return;
        update(value);
        setNotice(
          responsibility === "PROPERTY"
            ? "Reservation cancelled with an explicit linked Security Deposit Refund."
            : "Reservation cancelled with an explicit non-refundable Deposit disposition.",
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  return (
    <section aria-labelledby="reservation-management-heading" className="panel">
      <h2 id="reservation-management-heading">Reservations</h2>
      <p>
        Staff workflow for ACTIVE, CANCELLED, and COMPLETED Reservations.
        Expiration is a cancellation reason, never a separate status.
      </p>
      <form className="form-stack inline-form" onSubmit={load}>
        <label htmlFor="reservation-property-id">
          Reservation Property identifier
        </label>
        <input
          id="reservation-property-id"
          onChange={(event) => {
            sequence.current += 1;
            setPropertyId(event.currentTarget.value);
            setItems([]);
            setNextCursor(null);
            setSelected(null);
            setCanCreate(false);
          }}
          required
          value={propertyId}
        />
        <label htmlFor="reservation-status-filter">Status</label>
        <select
          id="reservation-status-filter"
          onChange={(event) => {
            setFilter(event.currentTarget.value as ReservationStatus | "");
          }}
          value={filter}
        >
          <option value="">All approved statuses</option>
          <option value="ACTIVE">ACTIVE</option>
          <option value="CANCELLED">CANCELLED</option>
          <option value="COMPLETED">COMPLETED</option>
        </select>
        <button disabled={busy} type="submit">
          Load Reservations
        </button>
      </form>
      <p aria-live="polite" data-testid="reservation-status">
        {notice}
      </p>

      {items.length > 0 && (
        <table>
          <caption>Property Reservations</caption>
          <thead>
            <tr>
              <th>Status</th>
              <th>Unit</th>
              <th>Customer</th>
              <th>Dates</th>
              <th>Deposit</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.reservation_id}>
                <td>{item.status}</td>
                <td>{item.unit_number}</td>
                <td>{item.customer_name}</td>
                <td>
                  {item.reservation_date}–{item.effective_expiration_date}
                </td>
                <td>
                  {money(item.deposit_received_usd_cents)} /{" "}
                  {money(item.deposit_required_usd_cents)}
                </td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() => {
                      open(item.reservation_id);
                    }}
                    type="button"
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {nextCursor !== null && (
        <button
          disabled={busy}
          onClick={() => {
            loadPage(nextCursor);
          }}
          type="button"
        >
          Load next page
        </button>
      )}

      {canCreate && (
        <form className="form-stack" onSubmit={create}>
          <h3>Create Reservation</h3>
          <label>
            Available Unit identifier
            <input name="unit-id" required />
          </label>
          <label>
            Customer identifier
            <input name="customer-id" required />
          </label>
          <label>
            Reservation Date
            <input name="reservation-date" required type="date" />
          </label>
          <label>
            Expiration Date (maximum initial period: 21 days)
            <input name="expiration-date" required type="date" />
          </label>
          <label>
            Agreed monthly Rent (USD)
            <input min="0.01" name="rent" required step="0.01" type="number" />
          </label>
          <label>
            Accepted initial Security Deposit (USD)
            <input
              min="0.01"
              name="accepted-deposit"
              required
              step="0.01"
              type="number"
            />
          </label>
          <label>
            Full required Security Deposit (USD)
            <input
              min="0.01"
              name="required-deposit"
              required
              step="0.01"
              type="number"
            />
          </label>
          <label>
            Deposit Payment source identifier
            <input name="payment-id" required />
          </label>
          <label>
            Acceptance reason
            <input maxLength={500} name="acceptance-reason" required />
          </label>
          <p>
            The normal suggestion is 20% of agreed monthly Rent. An authorized
            variance is preserved with its calculation trace.
          </p>
          <button disabled={busy} type="submit">
            Create ACTIVE Reservation
          </button>
        </form>
      )}

      {selected !== null && (
        <section aria-labelledby="reservation-detail-heading">
          <h3 id="reservation-detail-heading">Reservation detail</h3>
          <dl>
            <dt>Status</dt>
            <dd>{selected.status}</dd>
            <dt>Property-local expiration</dt>
            <dd>
              {selected.effective_expiration_date} (valid through the full date)
            </dd>
            <dt>Original expiration</dt>
            <dd>{selected.original_expiration_date}</dd>
            <dt>Security Deposit receipts</dt>
            <dd>
              {money(selected.deposit_received_usd_cents)} received;{" "}
              {money(selected.deposit_required_usd_cents)} required
              {selected.receipts.length === 0 ? (
                <p>No receipt records.</p>
              ) : (
                <ul>
                  {selected.receipts.map((receipt) => (
                    <li key={receipt.receipt_id}>
                      {money(receipt.amount_usd_cents)} from Payment{" "}
                      {receipt.payment_id}, recorded {receipt.occurred_at} by
                      actor {receipt.actor_id}
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            <dt>Deposit outcome</dt>
            <dd>{selected.deposit_outcome_state}</dd>
            <dt>Resulting Lease</dt>
            <dd>{selected.resulting_lease_id ?? "None"}</dd>
          </dl>
          {selected.extension_notice !== null && (
            <p>
              Extension Notice:{" "}
              {selected.extension_notice.previous_expiration_date} →{" "}
              {selected.extension_notice.new_expiration_date}. Original date
              remains preserved.
            </p>
          )}
          <h4>Permanent lifecycle and Deposit outcome history</h4>
          {selected.lifecycle_events.length === 0 ? (
            <p>No cancellation or expiration event.</p>
          ) : (
            <ul>
              {selected.lifecycle_events.map((event) => (
                <li key={event.event_id}>
                  {event.event_kind}: {event.reason_code} (
                  {event.responsibility}) on {event.business_date};
                  authorization {event.authorization_reference}; actor{" "}
                  {event.actor_id}
                </li>
              ))}
            </ul>
          )}
          {selected.deposit_outcomes.length > 0 && (
            <ul>
              {selected.deposit_outcomes.map((outcome) => (
                <li key={outcome.outcome_id}>
                  {outcome.outcome_kind}: {money(outcome.amount_usd_cents)};
                  cause {outcome.source_lifecycle_event_id}; authorization{" "}
                  {outcome.authorization_reference}; actor {outcome.actor_id};{" "}
                  {outcome.reason}
                </li>
              ))}
            </ul>
          )}
          {selected.can_extend && (
            <form className="form-stack" onSubmit={extend}>
              <h4>Extend Reservation</h4>
              <p>
                {selected.extension_days_remaining} Property-local day(s)
                remain.
              </p>
              <label>
                New Expiration Date (maximum 14 added days)
                <input
                  name="new-expiration-date"
                  onChange={(event) => {
                    setExtensionResult(event.currentTarget.value);
                  }}
                  required
                  type="date"
                />
              </label>
              <p>
                Resulting expiration date: {extensionResult || "Select a date"}
              </p>
              <label>
                Notice memo
                <input maxLength={500} name="extension-reason" />
              </label>
              <button disabled={busy} type="submit">
                Record Extension Notice
              </button>
            </form>
          )}
          {selected.can_cancel && (
            <form className="form-stack" onSubmit={cancel}>
              <h4>Cancel Reservation</h4>
              <label>
                Responsibility
                <select name="responsibility" required>
                  <option value="CUSTOMER">
                    Customer-caused / non-refundable disposition
                  </option>
                  <option value="PROPERTY">
                    Property-caused / full Refund
                  </option>
                </select>
              </label>
              <label>
                Approved reason code
                <input name="cancellation-reason-code" required />
              </label>
              <label>
                Reason and evidence
                <input maxLength={500} name="cancellation-reason" />
              </label>
              <label>
                Property coordination reference (required for Property-caused)
                <input name="coordination-reference" />
              </label>
              <label>
                Refund number (required for Property-caused)
                <input name="refund-number" />
              </label>
              <p>
                No free-form forfeiture is offered. The server derives the
                Deposit outcome from the approved responsibility classification.
                Customer responsibility creates a{" "}
                {money(selected.deposit_received_usd_cents)}
                non-refundable disposition authorized by
                reservation_deposits.dispose; Property responsibility creates a{" "}
                {money(selected.deposit_received_usd_cents)}
                Refund authorized by reservation_deposits.refund. The submitted
                reason, coordination reference, authenticated actor, and
                lifecycle event become the governing audit evidence.
              </p>
              <button disabled={busy} type="submit">
                Review and confirm cancellation
              </button>
            </form>
          )}
        </section>
      )}
    </section>
  );
}
