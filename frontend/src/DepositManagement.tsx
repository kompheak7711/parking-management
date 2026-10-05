import { FormEvent, useRef, useState } from "react";

import {
  DepositApi,
  DepositLedgerEvent,
  DepositRequestError,
  DepositResource,
  DepositUnavailableError,
  PetDepartureResource,
  PetRefundReviewResource,
  depositApi,
} from "./depositClient";

export interface DepositManagementProps {
  api?: DepositApi;
}

type DepositCommandKind = "create" | "reverse" | "departure" | "review";

interface PendingDepositCommand {
  fingerprint: string;
  eventId: string;
  idempotencyKey: string;
  replacementId: string | null;
}

function text(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function cents(value: string): number {
  const match = /^(0|[1-9][0-9]{0,12})(?:\.([0-9]{1,2}))?$/.exec(value);
  if (match === null) throw new DepositRequestError();
  const dollars = match[1];
  if (dollars === undefined) throw new DepositRequestError();
  const minor =
    BigInt(dollars) * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
  if (minor > BigInt(Number.MAX_SAFE_INTEGER)) throw new DepositRequestError();
  return Number(minor);
}

function money(value: number): string {
  if (!Number.isSafeInteger(value)) return "Unsupported amount";
  const negative = value < 0;
  const minor = BigInt(Math.abs(value));
  const whole = (minor / 100n).toLocaleString("en-US");
  const fraction = (minor % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}$${whole}.${fraction}`;
}

function errorMessage(error: unknown): string {
  if (
    error instanceof DepositUnavailableError ||
    error instanceof DepositRequestError
  ) {
    return error.message;
  }
  return "The Deposit request was not completed. Review the evidence and retry.";
}

export function DepositManagement({
  api = depositApi,
}: DepositManagementProps) {
  const [items, setItems] = useState<DepositResource[]>([]);
  const [selected, setSelected] = useState<DepositResource | null>(null);
  const [ledger, setLedger] = useState<DepositLedgerEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [departures, setDepartures] = useState<PetDepartureResource[]>([]);
  const [review, setReview] = useState<PetRefundReviewResource | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const selectionSequence = useRef(0);
  const pendingCommands = useRef(
    new Map<DepositCommandKind, PendingDepositCommand>(),
  );

  function commandIdentity(
    kind: DepositCommandKind,
    fingerprint: string,
    needsReplacement = false,
  ): PendingDepositCommand {
    const existing = pendingCommands.current.get(kind);
    if (existing?.fingerprint === fingerprint) return existing;
    const created = {
      fingerprint,
      eventId: crypto.randomUUID(),
      idempotencyKey: crypto.randomUUID(),
      replacementId: needsReplacement ? crypto.randomUUID() : null,
    };
    pendingCommands.current.set(kind, created);
    return created;
  }

  function completeCommand(
    kind: DepositCommandKind,
    identity: PendingDepositCommand,
  ) {
    if (pendingCommands.current.get(kind) === identity) {
      pendingCommands.current.delete(kind);
    }
  }

  function updateResource(value: DepositResource) {
    setSelected(value);
    setItems((current) =>
      current.map((candidate) =>
        candidate.deposit_id === value.deposit_id ? value : candidate,
      ),
    );
  }

  function operation<T>(
    message: string,
    value: Promise<T>,
    done: (result: T) => void,
  ) {
    setBusy(true);
    setNotice(message);
    void value
      .then(done)
      .catch((error: unknown) => {
        setNotice(errorMessage(error));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function clearSelectionEvidence() {
    setSelected(null);
    setLedger([]);
    setNextCursor(null);
    setDepartures([]);
    setReview(null);
  }

  function select(
    valueRequest: Promise<DepositResource>,
    replaceItems = false,
  ) {
    const sequence = selectionSequence.current + 1;
    selectionSequence.current = sequence;
    clearSelectionEvidence();
    setBusy(true);
    setNotice("Loading Deposit and permanent source history…");
    void valueRequest
      .then(async (value) => {
        if (selectionSequence.current !== sequence) return null;
        if (replaceItems) setItems([value]);
        else updateResource(value);
        setCanManage(value.can_manage);
        setSelected(value);
        const departureRequest =
          value.lease_id !== null && value.pet_departure_id !== null
            ? api.departures(value.lease_id)
            : Promise.resolve([]);
        const reviewRequest =
          value.pet_refund_review_id === null
            ? Promise.resolve(null)
            : api.review(value.pet_refund_review_id);
        const [page, authoritativeDepartures, authoritativeReview] =
          await Promise.all([
            api.ledger(value.deposit_id),
            departureRequest,
            reviewRequest,
          ]);
        return { value, page, authoritativeDepartures, authoritativeReview };
      })
      .then((result) => {
        if (result === null || selectionSequence.current !== sequence) return;
        setLedger(result.page.items);
        setNextCursor(result.page.next_cursor);
        setDepartures(result.authoritativeDepartures);
        setReview(result.authoritativeReview);
        setNotice("Deposit and source history loaded.");
      })
      .catch((error: unknown) => {
        if (selectionSequence.current !== sequence) return;
        clearSelectionEvidence();
        setNotice(errorMessage(error));
      })
      .finally(() => {
        if (selectionSequence.current === sequence) setBusy(false);
      });
  }

  function loadSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const sourceType = text(data, "source-type");
    const sourceId = text(data, "source-id");
    selectionSequence.current += 1;
    clearSelectionEvidence();
    const request =
      sourceType === "reservation"
        ? api.reservationDeposits(sourceId)
        : api.leaseDeposits(sourceId);
    operation(
      "Loading separate Security and Pet Deposit liabilities…",
      request,
      (page) => {
        setItems(page.items);
        setCanManage(page.can_manage);
        setNotice(
          page.items.length === 0
            ? "No Deposits are recorded for this source."
            : `${String(page.items.length)} separate Deposit liability record(s) loaded.`,
        );
      },
    );
  }

  function loadDeposit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = text(new FormData(event.currentTarget), "deposit-id");
    select(api.get(id), true);
  }

  function createPetDeposit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    let requiredAmount: number;
    try {
      requiredAmount = cents(text(data, "required-amount"));
    } catch {
      setNotice(
        "Enter an exact USD amount with no more than two decimal places.",
      );
      return;
    }
    const leaseId = text(data, "lease-id");
    const petApprovalId = text(data, "pet-approval-id");
    const effectiveDate = text(data, "effective-date");
    const reason = text(data, "reason");
    const identity = commandIdentity(
      "create",
      JSON.stringify([
        leaseId,
        petApprovalId,
        requiredAmount,
        effectiveDate,
        reason,
      ]),
    );
    operation(
      "Verifying approved pet and signed Lease terms…",
      api.createPetDeposit(
        leaseId,
        {
          deposit_id: identity.eventId,
          pet_approval_id: petApprovalId,
          required_usd_cents: requiredAmount,
          required_effective_date: effectiveDate,
          reason,
        },
        identity.idempotencyKey,
      ),
      (value) => {
        completeCommand("create", identity);
        setItems((current) => [...current, value]);
        setSelected(value);
        setLedger([]);
        setNextCursor(null);
        setDepartures([]);
        setReview(null);
        setNotice(
          "Pet Deposit liability created. Receipt creation remains deferred until authoritative Payment persistence.",
        );
        form.reset();
      },
    );
  }

  function reverse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const eventId = text(data, "event-id");
    const sourceEvent = ledger.find(
      (candidate) => candidate.event_id === eventId,
    );
    if (
      sourceEvent === undefined ||
      (sourceEvent.event_kind !== "RECEIPT" &&
        sourceEvent.event_kind !== "DISPOSITION")
    ) {
      setNotice("Select an available Deposit ledger event to reverse.");
      return;
    }
    const kind = sourceEvent.event_kind;
    const reason = text(data, "reason");
    const evidenceReference = text(data, "evidence-reference");
    const reservationCorrection =
      kind === "DISPOSITION" &&
      sourceEvent.governing_source_kind === "RESERVATION";
    if (reservationCorrection && selected?.reservation_version === null) {
      setNotice(
        "Reload the Reservation Deposit before correcting its disposition.",
      );
      return;
    }
    if (kind === "DISPOSITION" && evidenceReference === "") {
      setNotice(
        "Enter the verified evidence reference for a disposition reversal.",
      );
      return;
    }
    const identity = commandIdentity(
      "reverse",
      JSON.stringify([
        eventId,
        kind,
        reason,
        kind === "DISPOSITION" ? evidenceReference : null,
        reservationCorrection ? selected?.reservation_version : null,
      ]),
      reservationCorrection,
    );
    if (
      !window.confirm(
        `Reverse ${kind} ${eventId}? Authoritative amount: ${sourceEvent.amount_usd_cents === null ? "no money movement" : money(sourceEvent.amount_usd_cents)}. Source: ${sourceEvent.source_id ?? "none"}. This creates a new immutable correction event and changes the held Deposit balance; the original remains visible. Reason: ${reason}`,
      )
    ) {
      setNotice("Deposit reversal was not submitted.");
      return;
    }
    const request =
      kind === "RECEIPT"
        ? api.reverseReceipt(
            eventId,
            { reversal_id: identity.eventId, reason },
            identity.idempotencyKey,
          )
        : api.reverseDisposition(
            eventId,
            {
              reversal_id: identity.eventId,
              reason,
              evidence_reference: evidenceReference,
              replacement_disposition_id: reservationCorrection
                ? identity.replacementId
                : null,
              expected_reservation_version: reservationCorrection
                ? (selected?.reservation_version ?? null)
                : null,
            },
            identity.idempotencyKey,
          );
    operation(
      "Recording a linked correction without rewriting history…",
      request,
      (value) => {
        completeCommand("reverse", identity);
        updateResource(value);
        setLedger([]);
        setNextCursor(null);
        setNotice(
          "Linked Deposit correction recorded; reopen history to view the original and correction together.",
        );
      },
    );
  }

  function recordDeparture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const leaseId = selected.lease_id;
    if (leaseId === null) return;
    const data = new FormData(event.currentTarget);
    const departureDate = text(data, "departure-date");
    const reason = text(data, "reason");
    const identity = commandIdentity(
      "departure",
      JSON.stringify([leaseId, selected.deposit_id, departureDate, reason]),
    );
    operation(
      "Recording permanent pet departure without terminating the Lease…",
      api.recordDeparture(
        leaseId,
        {
          departure_id: identity.eventId,
          deposit_id: selected.deposit_id,
          permanently_left_date: departureDate,
          reason,
        },
        identity.idempotencyKey,
      ),
      (value) => {
        completeCommand("departure", identity);
        updateResource(value);
        setNotice(
          "Permanent pet departure recorded; no Refund is authorized yet.",
        );
      },
    );
  }

  function loadDepartures() {
    if (selected?.lease_id === null || selected?.lease_id === undefined) return;
    operation(
      "Loading pet departure and review history…",
      api.departures(selected.lease_id),
      (values) => {
        setDepartures(values);
        setNotice("Pet departure history loaded.");
      },
    );
  }

  function qualify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const departureId = selected.pet_departure_id;
    if (departureId === null) {
      setNotice(
        "Record the permanent pet departure before qualifying a Refund review.",
      );
      return;
    }
    let obligationsReviewed: number;
    try {
      obligationsReviewed = cents(text(data, "obligations-reviewed"));
    } catch {
      setNotice(
        "Enter an exact USD amount with no more than two decimal places.",
      );
      return;
    }
    const reason = text(data, "reason");
    const reviewFindings = text(data, "review-findings");
    const resolutionReference = text(data, "resolution-reference");
    if (
      !window.confirm(
        `Qualify the active-Lease Pet Deposit review for departure ${departureId}, with ${money(obligationsReviewed)} reviewed obligations? This creates an immutable review event and may authorize a later explicit Refund. Reason: ${reason}`,
      )
    ) {
      setNotice("Pet Deposit Refund qualification was not submitted.");
      return;
    }
    const identity = commandIdentity(
      "review",
      JSON.stringify([
        departureId,
        selected.deposit_id,
        obligationsReviewed,
        reviewFindings,
        resolutionReference,
        reason,
      ]),
    );
    const reviewId = identity.eventId;
    operation(
      "Verifying resolved pet obligations and refundable held balance…",
      api
        .qualifyReview(
          departureId,
          {
            review_id: reviewId,
            deposit_id: selected.deposit_id,
            obligations_reviewed_usd_cents: obligationsReviewed,
            review_findings: reviewFindings,
            resolution_reference: resolutionReference,
            reason,
          },
          identity.idempotencyKey,
        )
        .then(async (value) => ({ value, review: await api.review(reviewId) })),
      ({ value, review: authoritativeReview }) => {
        completeCommand("review", identity);
        updateResource(value);
        setReview(authoritativeReview);
        setNotice(
          "Pet Deposit Refund qualification recorded. Continue through the later explicit Refund workflow.",
        );
      },
    );
  }

  const reversibleEvents = ledger.filter((event) => event.can_reverse);

  return (
    <section
      aria-labelledby="deposit-management-heading"
      className="workspace-section"
    >
      <h3 id="deposit-management-heading">Deposit management</h3>
      <p className="panel-help">
        Security and Pet Deposits remain separate liabilities. Receipt creation
        waits for authoritative Payment persistence; existing receipts and every
        linked correction remain visible.
      </p>
      {notice !== null && <p aria-live="polite">{notice}</p>}

      <form className="form-stack" onSubmit={loadSource}>
        <label>
          Source type
          <select name="source-type">
            <option value="reservation">Reservation</option>
            <option value="lease">Lease</option>
          </select>
        </label>
        <label>
          Reservation or Lease identifier
          <input name="source-id" required />
        </label>
        <button disabled={busy} type="submit">
          Load Deposits
        </button>
      </form>
      <form className="form-stack" onSubmit={loadDeposit}>
        <label>
          Deposit identifier
          <input name="deposit-id" required />
        </label>
        <button disabled={busy} type="submit">
          Load one Deposit
        </button>
      </form>

      {items.length > 0 && (
        <table>
          <caption>Separate Deposit liabilities</caption>
          <thead>
            <tr>
              <th>Type</th>
              <th>Required</th>
              <th>Received</th>
              <th>Held</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.deposit_id}>
                <td>{item.deposit_type}</td>
                <td>{money(item.required_usd_cents)}</td>
                <td>{money(item.received_usd_cents)}</td>
                <td>{money(item.held_refundable_usd_cents)}</td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() => {
                      select(api.get(item.deposit_id));
                    }}
                    type="button"
                  >
                    Open history
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected !== null && (
        <div className="information-card">
          <h4>{selected.deposit_type} Deposit</h4>
          <p>
            Required {money(selected.required_usd_cents)}; received{" "}
            {money(selected.received_usd_cents)}; refundable held balance{" "}
            {money(selected.held_refundable_usd_cents)}.
          </p>
          {review !== null && review.deposit_id === selected.deposit_id && (
            <section aria-labelledby="pet-refund-review-result">
              <h5 id="pet-refund-review-result">Authoritative Refund review</h5>
              <p>
                Review {review.review_id}; qualified refundable balance{" "}
                {money(review.refundable_usd_cents)}; current held refundable
                balance {money(review.current_refundable_usd_cents)}; reviewed
                by {review.reviewed_by} at {review.reviewed_at}.
              </p>
              <p>
                Findings: {review.review_findings}. Resolution:{" "}
                {review.resolution_reference}. Authorization:{" "}
                {review.authorization_reference}. Reason: {review.reason}.
              </p>
            </section>
          )}
          <p>
            Customer Credit and ordinary Invoice payment remain separate. Final
            Settlement disposition is deferred to the Settlement workflow.
          </p>
          <h5>Permanent source history</h5>
          {ledger.length === 0 ? (
            <p>No ledger events loaded.</p>
          ) : (
            <ol>
              {ledger.map((event) => (
                <li key={event.event_id}>
                  {event.event_kind} —{" "}
                  {event.amount_usd_cents === null
                    ? "no money movement"
                    : money(event.amount_usd_cents)}{" "}
                  — {event.occurred_at}
                  {event.effective_date === null
                    ? ""
                    : ` — effective ${event.effective_date}`}
                  {event.source_id === null
                    ? ""
                    : ` — source ${event.source_id}`}
                  {event.governing_source_kind === null ||
                  event.governing_source_id === null
                    ? ""
                    : ` — governing ${event.governing_source_kind.toLowerCase().replace(/_/g, " ")} ${event.governing_source_id}`}
                  {event.source_lifecycle_event_id === null
                    ? ""
                    : ` — lifecycle event ${event.source_lifecycle_event_id}`}
                  {event.reason === null ? "" : ` — reason ${event.reason}`}
                  {event.evidence_reference === null
                    ? ""
                    : ` — evidence ${event.evidence_reference}`}
                  {` — actor ${event.actor_id}`}
                  {event.authorization_reference === null
                    ? ""
                    : ` — authorization ${event.authorization_reference}`}
                  {event.currency === null || event.amount_minor === null
                    ? ""
                    : ` — original ${event.currency} ${String(event.amount_minor)} minor units`}
                  {event.reference_number === null
                    ? ""
                    : ` — reference ${event.reference_number}`}
                </li>
              ))}
            </ol>
          )}
          {nextCursor !== null && (
            <button
              disabled={busy}
              onClick={() => {
                operation(
                  "Loading older Deposit history…",
                  api.ledger(selected.deposit_id, nextCursor),
                  (page) => {
                    setLedger((current) => [...current, ...page.items]);
                    setNextCursor(page.next_cursor);
                    setNotice("Older Deposit history loaded.");
                  },
                );
              }}
              type="button"
            >
              Load older history
            </button>
          )}

          {reversibleEvents.length > 0 && (
            <form className="form-stack" onSubmit={reverse}>
              <h5>Record linked correction</h5>
              <label>
                Permanent ledger event
                <select name="event-id">
                  {reversibleEvents.map((event) => (
                    <option key={event.event_id} value={event.event_id}>
                      {event.event_kind} — {event.event_id} —{" "}
                      {event.amount_usd_cents === null
                        ? "no money movement"
                        : money(event.amount_usd_cents)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reason
                <input name="reason" required />
              </label>
              <label>
                Verified evidence reference (required for dispositions)
                <input name="evidence-reference" />
              </label>
              {reversibleEvents.some(
                (event) =>
                  event.event_kind === "DISPOSITION" &&
                  event.governing_source_kind === "RESERVATION",
              ) && (
                <p>
                  Correcting a Reservation disposition atomically records the
                  linked reversal and an authorized replacement disposition. The
                  cancelled Reservation never loses its classified outcome.
                </p>
              )}
              <button disabled={busy} type="submit">
                Record reversal
              </button>
            </form>
          )}

          {selected.deposit_type === "PET" &&
            selected.can_qualify_pet_refund && (
              <>
                {selected.pet_departure_id === null && (
                  <form className="form-stack" onSubmit={recordDeparture}>
                    <h5>Record permanent pet departure</h5>
                    <label>
                      Permanent departure date
                      <input name="departure-date" required type="date" />
                    </label>
                    <label>
                      Reason
                      <input name="reason" required />
                    </label>
                    <button disabled={busy} type="submit">
                      Record departure only
                    </button>
                  </form>
                )}
                <button disabled={busy} onClick={loadDepartures} type="button">
                  Load departure reviews
                </button>
                {departures.map((departure) => (
                  <p key={departure.departure_id}>
                    Departure {departure.departure_id} on{" "}
                    {departure.permanently_left_date}; review{" "}
                    {departure.refund_review_id ?? "not yet recorded"}.
                  </p>
                ))}
                {selected.pet_departure_id !== null &&
                  selected.pet_refund_review_id === null && (
                    <form className="form-stack" onSubmit={qualify}>
                      <h5>Qualify active-Lease Pet Deposit Refund</h5>
                      <p>Departure {selected.pet_departure_id}</p>
                      <label>
                        Pet obligations reviewed (USD)
                        <input
                          min="0"
                          inputMode="decimal"
                          name="obligations-reviewed"
                          pattern="[0-9]+(?:\.[0-9]{1,2})?"
                          required
                          type="text"
                        />
                      </label>
                      <label>
                        Resolved findings
                        <textarea name="review-findings" required />
                      </label>
                      <label>
                        Resolution reference
                        <input name="resolution-reference" required />
                      </label>
                      <label>
                        Authorization reason
                        <input name="reason" required />
                      </label>
                      <button disabled={busy} type="submit">
                        Record qualifying review
                      </button>
                    </form>
                  )}
              </>
            )}
        </div>
      )}

      {canManage && (
        <form className="form-stack" onSubmit={createPetDeposit}>
          <h4>Approved conditional Pet Deposit liability</h4>
          <label>
            Signed Lease identifier
            <input name="lease-id" required />
          </label>
          <label>
            Approved pet identifier
            <input name="pet-approval-id" required />
          </label>
          <label>
            Required amount (USD)
            <input
              min="0.01"
              inputMode="decimal"
              name="required-amount"
              pattern="[0-9]+(?:\.[0-9]{1,2})?"
              required
              type="text"
            />
          </label>
          <label>
            Effective date
            <input name="effective-date" required type="date" />
          </label>
          <label>
            Reason
            <input name="reason" required />
          </label>
          <button disabled={busy} type="submit">
            Create Pet Deposit liability
          </button>
        </form>
      )}
    </section>
  );
}
