import { FormEvent, useRef, useState } from "react";

import {
  LeaseApi,
  LeaseConflictError,
  LeasePeriodFilter,
  LeaseResource,
  LeaseStatus,
  LeaseUnavailableError,
  leaseApi,
} from "./leaseClient";

export interface LeaseManagementProps {
  api?: LeaseApi;
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function optional(value: string): string | null {
  return value === "" ? null : value;
}

function optionalFilter(value: string): string | undefined {
  return value === "" ? undefined : value;
}

function cents(value: string): number | null {
  return value === "" ? null : Math.round(Number(value) * 100);
}

function identifiers(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

interface DraftServiceTerm {
  key: string;
  propertyServiceId: string;
  applicableFrom: string;
  applicableThrough: string;
  approvalPeriodId: string;
  termsReference: string;
}

function money(value: number | null): string {
  if (value === null) return "Not recorded";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value / 100);
}

function message(error: unknown): string {
  if (
    error instanceof LeaseUnavailableError ||
    error instanceof LeaseConflictError
  ) {
    return error.message;
  }
  return "The Lease request was not completed. Review the evidence and retry.";
}

export function LeaseManagement({ api = leaseApi }: LeaseManagementProps) {
  const [propertyId, setPropertyId] = useState("");
  const [items, setItems] = useState<LeaseResource[]>([]);
  const [selected, setSelected] = useState<LeaseResource | null>(null);
  const [canCreate, setCanCreate] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [signatureReason, setSignatureReason] = useState("");
  const [draftServiceTerms, setDraftServiceTerms] = useState<
    DraftServiceTerm[]
  >([]);
  const [petApproved, setPetApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const sequence = useRef(0);

  function update(value: LeaseResource) {
    setSelected(value);
    setItems((current) =>
      current.map((candidate) =>
        candidate.lease_id === value.lease_id ? value : candidate,
      ),
    );
  }

  function loadPage(cursor?: string) {
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Loading bounded Lease records…");
    void api
      .list(propertyId, {
        status: optionalFilter(filters.status ?? "") as LeaseStatus | undefined,
        unit_id: optionalFilter(filters.unit_id ?? ""),
        customer_id: optionalFilter(filters.customer_id ?? ""),
        starts_on_or_after: optionalFilter(filters.starts_on_or_after ?? ""),
        ends_on_or_before: optionalFilter(filters.ends_on_or_before ?? ""),
        period: optionalFilter(filters.period ?? "") as
          | LeasePeriodFilter
          | undefined,
        as_of: optionalFilter(filters.as_of ?? ""),
        approaching_days:
          filters.approaching_days === undefined ||
          filters.approaching_days === ""
            ? undefined
            : Number(filters.approaching_days),
        cursor,
      })
      .then((page) => {
        if (operation !== sequence.current) return;
        setItems(page.items);
        setCanCreate(page.can_create);
        setNextCursor(page.next_cursor);
        setSelected(null);
        setNotice(
          page.items.length === 0
            ? "No Leases matched the selected Property and filters."
            : `${String(page.items.length)} Lease record(s) loaded.`,
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setItems([]);
        setSelected(null);
        setCanCreate(false);
        setNextCursor(null);
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const next = {
      status: formString(data, "status"),
      unit_id: formString(data, "unit-id"),
      customer_id: formString(data, "customer-id"),
      starts_on_or_after: formString(data, "starts-on-or-after"),
      ends_on_or_before: formString(data, "ends-on-or-before"),
      period: formString(data, "period"),
      as_of: formString(data, "as-of"),
      approaching_days: formString(data, "approaching-days"),
    };
    setFilters(next);
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Loading bounded Lease records…");
    void api
      .list(propertyId, {
        status: optionalFilter(next.status) as LeaseStatus | undefined,
        unit_id: optionalFilter(next.unit_id),
        customer_id: optionalFilter(next.customer_id),
        starts_on_or_after: optionalFilter(next.starts_on_or_after),
        ends_on_or_before: optionalFilter(next.ends_on_or_before),
        period: optionalFilter(next.period) as LeasePeriodFilter | undefined,
        as_of: optionalFilter(next.as_of),
        approaching_days:
          next.approaching_days === ""
            ? undefined
            : Number(next.approaching_days),
      })
      .then((page) => {
        if (operation !== sequence.current) return;
        setItems(page.items);
        setCanCreate(page.can_create);
        setNextCursor(page.next_cursor);
        setSelected(null);
        setNotice(`${String(page.items.length)} Lease record(s) loaded.`);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function open(leaseId: string) {
    const operation = ++sequence.current;
    setBusy(true);
    setNotice(
      "Loading Lease terms, Signers, Occupants, and permanent timeline…",
    );
    void api
      .get(leaseId)
      .then((value) => {
        if (operation !== sequence.current) return;
        setSelected(value);
        setNotice("Lease detail loaded.");
      })
      .catch((error: unknown) => {
        setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function loadMoreTimeline() {
    const cursor = selected?.timeline_next_cursor;
    if (!cursor) return;
    const current = selected;
    const operation = ++sequence.current;
    setBusy(true);
    setNotice("Loading the next bounded Lease timeline page…");
    void api
      .timeline(current.lease_id, cursor)
      .then((page) => {
        if (operation !== sequence.current) return;
        update({
          ...current,
          timeline: [...current.timeline, ...page.items],
          timeline_next_cursor: page.next_cursor,
        });
        setNotice(
          `${String(page.items.length)} more timeline event(s) loaded.`,
        );
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function command(
    description: string,
    action: () => Promise<LeaseResource>,
    success: string,
    onSuccess?: () => void,
  ) {
    const operation = ++sequence.current;
    setBusy(true);
    setNotice(description);
    void action()
      .then((value) => {
        if (operation !== sequence.current) return;
        update(value);
        onSuccess?.();
        setNotice(success);
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const leaseId = crypto.randomUUID();
    command(
      "Creating a DRAFTED Lease without automatic month-to-month behavior…",
      () =>
        api.create(
          propertyId,
          {
            lease_id: leaseId,
            unit_id: formString(data, "unit-id"),
            primary_tenant_id: formString(data, "primary-tenant-id"),
            primary_signer_id: crypto.randomUUID(),
            start_date: optional(formString(data, "start-date")),
            end_date: optional(formString(data, "end-date")),
            monthly_rent_usd_cents: cents(formString(data, "rent")),
            predecessor_lease_id: null,
            additional_signers: identifiers(
              formString(data, "additional-signer-ids"),
            ).map((customerId) => ({
              signer_id: crypto.randomUUID(),
              customer_id: customerId,
            })),
            planned_occupant_customer_ids: identifiers(
              formString(data, "planned-occupant-ids"),
            ),
            service_terms: draftServiceTerms.map((term) => ({
              term_id: crypto.randomUUID(),
              property_service_id: term.propertyServiceId.trim(),
              applicable_from: term.applicableFrom,
              applicable_through: optional(term.applicableThrough),
              service_approval_period_id: term.approvalPeriodId.trim(),
              terms_reference: term.termsReference.trim(),
            })),
            pet_term:
              data.get("pet-approved") === "yes"
                ? {
                    approval_id: crypto.randomUUID(),
                    approved_date: formString(data, "pet-approved-date"),
                    deposit_required_by_signed_terms:
                      data.get("pet-deposit-required") === "yes",
                    pet_description: optional(
                      formString(data, "pet-description"),
                    ),
                  }
                : null,
            security_deposit_id: optional(
              formString(data, "security-deposit-id"),
            ),
            event_id: crypto.randomUUID(),
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Lease draft created with stable identity and source history.",
      () => {
        form.reset();
        setDraftServiceTerms([]);
        setPetApproved(false);
      },
    );
  }

  function updateDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    command(
      "Applying the optimistic Lease draft correction…",
      () =>
        api.update(
          selected,
          {
            event_id: crypto.randomUUID(),
            start_date: optional(formString(data, "start-date")),
            end_date: optional(formString(data, "end-date")),
            monthly_rent_usd_cents: cents(formString(data, "rent")),
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Draft terms updated; the earlier revision remains preserved.",
    );
  }

  function addSigner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    command(
      "Adding a distinct Lease Signer without inferring Occupancy…",
      () =>
        api.addSigner(
          selected,
          {
            signer_id: crypto.randomUUID(),
            customer_id: formString(data, "customer-id"),
            event_id: crypto.randomUUID(),
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Signer added with joint-responsibility history.",
    );
  }

  function recordSignature(signerId: string) {
    if (selected === null) return;
    const reason = signatureReason.trim();
    if (reason === "") {
      setNotice("Signature evidence reason is required.");
      return;
    }
    command(
      "Recording the attributed Signer signature…",
      () =>
        api.recordSignature(
          selected,
          signerId,
          {
            event_id: crypto.randomUUID(),
            signed_at: new Date().toISOString(),
            reason,
          },
          crypto.randomUUID(),
        ),
      "Signer signature recorded without changing Occupant responsibility.",
    );
    setSignatureReason("");
  }

  function sign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    if (
      !window.confirm(
        "Sign this Lease after reviewing all source terms and Signers?",
      )
    )
      return;
    command(
      "Revalidating parties, terms, and non-overlapping Unit periods…",
      () =>
        api.sign(
          selected,
          {
            event_id: crypto.randomUUID(),
            signed_at: new Date().toISOString(),
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Lease signed through an explicit audited command.",
    );
  }

  function renew(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    command(
      "Creating a non-overlapping successor Lease draft…",
      () =>
        api.renew(
          selected,
          {
            lease_id: crypto.randomUUID(),
            primary_signer_id: crypto.randomUUID(),
            event_id: crypto.randomUUID(),
            start_date: formString(data, "start-date"),
            end_date: formString(data, "end-date"),
            monthly_rent_usd_cents: cents(formString(data, "rent")) ?? 0,
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Successor Lease created; no automatic month-to-month state was inferred.",
    );
  }

  function terminate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    if (
      !window.confirm(
        "Apply this authorized termination boundary to the signed Lease?",
      )
    )
      return;
    command(
      "Applying the authorized termination boundary…",
      () =>
        api.terminate(
          selected,
          {
            event_id: crypto.randomUUID(),
            actual_termination_date: formString(data, "actual-date"),
            occurred_at: new Date().toISOString(),
            governing_event_reference: formString(data, "reference"),
            reason: formString(data, "reason"),
          },
          crypto.randomUUID(),
        ),
      "Lease terminated with permanent governing evidence; move-out remains separate.",
    );
  }

  function completeMoveIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    if (
      !window.confirm(
        "Complete the coordinated Reservation, Lease, Unit, and Occupancy transition?",
      )
    ) {
      return;
    }
    const operation = ++sequence.current;
    setBusy(true);
    setNotice(
      "The server is validating every move-in prerequisite atomically…",
    );
    void api
      .completeMoveIn(
        formString(data, "reservation-id"),
        Number(formString(data, "reservation-version")),
        {
          event_id: crypto.randomUUID(),
          lease_id: selected.lease_id,
          expected_lease_version: selected.version,
          expected_unit_version: Number(formString(data, "unit-version")),
          actual_move_in_date: formString(data, "move-in-date"),
          occupants: identifiers(formString(data, "occupant-customer-ids")).map(
            (customerId) => ({
              occupancy_id: crypto.randomUUID(),
              customer_id: customerId,
            }),
          ),
          reason: formString(data, "reason"),
        },
        crypto.randomUUID(),
      )
      .then((result) => {
        if (operation !== sequence.current) return;
        setNotice(
          `Move-in completed atomically. Reservation version ${String(result.reservation_version)}, Unit version ${String(result.unit_version)}, and Deposit ${result.deposit_id} remain linked.`,
        );
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setNotice(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  return (
    <section aria-labelledby="lease-management-heading" className="panel">
      <h2 id="lease-management-heading">Leases and move-in</h2>
      <p>
        Accessible staff workflow for Lease drafting, Signers, Occupants,
        signing, renewal, termination boundaries, and atomic move-in. Billing
        and move-out are separate.
      </p>
      <form className="form-stack" onSubmit={load}>
        <h3>Find Leases</h3>
        <label>
          Lease Property identifier
          <input
            onChange={(event) => {
              sequence.current += 1;
              setPropertyId(event.currentTarget.value);
              setItems([]);
              setSelected(null);
            }}
            required
            value={propertyId}
          />
        </label>
        <label>
          Status
          <select name="status">
            <option value="">All statuses</option>
            <option value="DRAFTED">DRAFTED</option>
            <option value="SIGNED">SIGNED</option>
            <option value="CANCELLED">CANCELLED</option>
            <option value="TERMINATED">TERMINATED</option>
          </select>
        </label>
        <label>
          Unit identifier
          <input name="unit-id" />
        </label>
        <label>
          Primary Customer identifier
          <input name="customer-id" />
        </label>
        <label>
          Starts on or after
          <input name="starts-on-or-after" type="date" />
        </label>
        <label>
          Ends on or before
          <input name="ends-on-or-before" type="date" />
        </label>
        <label>
          Period view
          <select name="period">
            <option value="">Any period</option>
            <option value="current">Current</option>
            <option value="future">Future or renewal</option>
            <option value="historical">Historical</option>
            <option value="approaching_end">Approaching End Date</option>
          </select>
        </label>
        <label>
          Property business date for period view
          <input name="as-of" type="date" />
        </label>
        <label>
          Approaching-End-Date days
          <input max="365" min="1" name="approaching-days" type="number" />
        </label>
        <button disabled={busy} type="submit">
          Load Leases
        </button>
      </form>
      <p aria-live="polite" data-testid="lease-status">
        {notice}
      </p>

      {items.length > 0 && (
        <table>
          <caption>Property Leases</caption>
          <thead>
            <tr>
              <th>Status</th>
              <th>Unit</th>
              <th>Primary Tenant</th>
              <th>Period</th>
              <th>Rent</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.lease_id}>
                <td>{item.status}</td>
                <td>{item.unit_number}</td>
                <td>{item.primary_tenant_name}</td>
                <td>
                  {item.start_date ?? "Unset"}–{item.end_date ?? "Unset"}
                  {item.predecessor_lease_id !== null && (
                    <strong> Successor</strong>
                  )}
                </td>
                <td>{money(item.monthly_rent_usd_cents)}</td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() => {
                      open(item.lease_id);
                    }}
                    type="button"
                  >
                    View Lease
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
          Load next Lease page
        </button>
      )}

      {canCreate && (
        <form className="form-stack" onSubmit={create}>
          <h3>Create Lease draft</h3>
          <label>
            Unit identifier
            <input name="unit-id" required />
          </label>
          <label>
            Primary Tenant Customer identifier
            <input name="primary-tenant-id" required />
          </label>
          <label>
            Contract Start Date
            <input name="start-date" type="date" />
          </label>
          <label>
            Contract End Date
            <input name="end-date" type="date" />
          </label>
          <label>
            Monthly Rent (USD)
            <input min="0.01" name="rent" step="0.01" type="number" />
          </label>
          <label>
            Additional Signer Customer identifiers (one per line)
            <textarea name="additional-signer-ids" rows={3} />
          </label>
          <label>
            Planned Occupant Customer identifiers (one per line)
            <textarea name="planned-occupant-ids" rows={3} />
          </label>
          <fieldset>
            <legend>Approved fixed Service terms</legend>
            {draftServiceTerms.length === 0 && (
              <p>No configured Service term applies to this Lease draft.</p>
            )}
            {draftServiceTerms.map((term, index) => (
              <fieldset key={term.key}>
                <legend>Service term {index + 1}</legend>
                <label>
                  Configured Property Service identifier
                  <input
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setDraftServiceTerms((current) =>
                        current.map((value) =>
                          value.key === term.key
                            ? {
                                ...value,
                                propertyServiceId: nextValue,
                              }
                            : value,
                        ),
                      );
                    }}
                    required
                    value={term.propertyServiceId}
                  />
                </label>
                <label>
                  Applicable From
                  <input
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setDraftServiceTerms((current) =>
                        current.map((value) =>
                          value.key === term.key
                            ? {
                                ...value,
                                applicableFrom: nextValue,
                              }
                            : value,
                        ),
                      );
                    }}
                    required
                    type="date"
                    value={term.applicableFrom}
                  />
                </label>
                <label>
                  Applicable Through
                  <input
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setDraftServiceTerms((current) =>
                        current.map((value) =>
                          value.key === term.key
                            ? {
                                ...value,
                                applicableThrough: nextValue,
                              }
                            : value,
                        ),
                      );
                    }}
                    type="date"
                    value={term.applicableThrough}
                  />
                </label>
                <label>
                  Owner-approved Service period identifier
                  <input
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setDraftServiceTerms((current) =>
                        current.map((value) =>
                          value.key === term.key
                            ? {
                                ...value,
                                approvalPeriodId: nextValue,
                              }
                            : value,
                        ),
                      );
                    }}
                    required
                    value={term.approvalPeriodId}
                  />
                </label>
                <label>
                  Approved terms reference
                  <input
                    maxLength={500}
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setDraftServiceTerms((current) =>
                        current.map((value) =>
                          value.key === term.key
                            ? {
                                ...value,
                                termsReference: nextValue,
                              }
                            : value,
                        ),
                      );
                    }}
                    required
                    value={term.termsReference}
                  />
                </label>
                <button
                  onClick={() => {
                    setDraftServiceTerms((current) =>
                      current.filter((value) => value.key !== term.key),
                    );
                  }}
                  type="button"
                >
                  Remove Service term
                </button>
              </fieldset>
            ))}
            <button
              disabled={draftServiceTerms.length >= 20}
              onClick={() => {
                setDraftServiceTerms((current) => [
                  ...current,
                  {
                    key: crypto.randomUUID(),
                    propertyServiceId: "",
                    applicableFrom: "",
                    applicableThrough: "",
                    approvalPeriodId: "",
                    termsReference: "",
                  },
                ]);
              }}
              type="button"
            >
              Add approved Service term
            </button>
          </fieldset>
          <fieldset>
            <legend>Approved pet terms</legend>
            <label>
              <input
                checked={petApproved}
                name="pet-approved"
                onChange={(event) => {
                  setPetApproved(event.currentTarget.checked);
                }}
                type="checkbox"
                value="yes"
              />
              Approved pet terms apply
            </label>
            <label>
              Pet approval date
              <input
                disabled={!petApproved}
                name="pet-approved-date"
                required={petApproved}
                type="date"
              />
            </label>
            <label>
              Pet description
              <input
                disabled={!petApproved}
                maxLength={500}
                name="pet-description"
              />
            </label>
            <label>
              <input
                name="pet-deposit-required"
                disabled={!petApproved}
                type="checkbox"
                value="yes"
              />
              Signed terms require a distinct Pet Deposit
            </label>
          </fieldset>
          <label>
            Approved Security Deposit source identifier
            <input name="security-deposit-id" />
          </label>
          <label>
            Approved source reason
            <input maxLength={500} name="reason" required />
          </label>
          <p>
            Service, Deposit, pet, Signer, and planned Occupant evidence remains
            distinct. Empty optional evidence means no approved source was
            recorded; this form creates no default fee, month-to-month behavior,
            or financial event.
          </p>
          <button disabled={busy} type="submit">
            Create DRAFTED Lease
          </button>
        </form>
      )}

      {selected !== null && (
        <section aria-labelledby="lease-detail-heading">
          <h3 id="lease-detail-heading">Lease detail</h3>
          <dl>
            <dt>Status and version</dt>
            <dd>
              {selected.status}, version {selected.version}
            </dd>
            <dt>Unit</dt>
            <dd>
              {selected.unit_number} ({selected.unit_id})
            </dd>
            <dt>Primary Tenant</dt>
            <dd>{selected.primary_tenant_name}</dd>
            <dt>Contract period</dt>
            <dd>
              {selected.start_date ?? "Unset"}–{selected.end_date ?? "Unset"}
            </dd>
            <dt>Rent</dt>
            <dd>{money(selected.monthly_rent_usd_cents)}</dd>
            <dt>Predecessor Lease</dt>
            <dd>{selected.predecessor_lease_id ?? "None"}</dd>
          </dl>
          <h4>Approved fixed Service terms</h4>
          {selected.service_terms.length === 0 ? (
            <p>No configured fixed Service applies to this Lease.</p>
          ) : (
            <ul>
              {selected.service_terms.map((term) => (
                <li key={term.term_id}>
                  {term.service_name}: {term.applicable_from}–
                  {term.applicable_through ?? "Lease End Date"}; approval{" "}
                  {term.service_approval_period_id}; source{" "}
                  {term.terms_reference}
                </li>
              ))}
            </ul>
          )}
          <h4>Approved Deposit terms</h4>
          <p>
            Security Deposit source:{" "}
            {selected.security_deposit_id ?? "No approved source recorded"}. Pet
            Deposit remains a distinct conditional obligation.
          </p>
          <h4>Conditional Pet Deposit</h4>
          {selected.pet_deposit_required ? (
            <p>
              Required by approved signed pet terms
              {selected.pet_description === null
                ? "."
                : ` for ${selected.pet_description}.`}
            </p>
          ) : (
            <p>
              Not required by the recorded signed pet terms. Possible future pet
              ownership creates no requirement.
            </p>
          )}

          {selected.can_edit && (
            <form className="form-stack" onSubmit={updateDraft}>
              <h4>Edit DRAFTED source terms</h4>
              <label>
                Start Date
                <input
                  defaultValue={selected.start_date ?? ""}
                  name="start-date"
                  type="date"
                />
              </label>
              <label>
                End Date
                <input
                  defaultValue={selected.end_date ?? ""}
                  name="end-date"
                  type="date"
                />
              </label>
              <label>
                Monthly Rent (USD)
                <input
                  defaultValue={
                    selected.monthly_rent_usd_cents === null
                      ? ""
                      : selected.monthly_rent_usd_cents / 100
                  }
                  min="0.01"
                  name="rent"
                  step="0.01"
                  type="number"
                />
              </label>
              <label>
                Correction reason
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Update Lease draft
              </button>
            </form>
          )}

          <h4>Signers and joint responsibility</h4>
          <p>
            Signers are separate from Occupants. Occupancy alone grants no
            signing responsibility.
          </p>
          <label>
            Signature evidence reason
            <input
              maxLength={500}
              onChange={(event) => {
                setSignatureReason(event.currentTarget.value);
              }}
              required
              value={signatureReason}
            />
          </label>
          <ul>
            {selected.signers.map((signer) => (
              <li key={signer.signer_id}>
                {signer.customer_name}
                {signer.is_primary_tenant
                  ? " — Primary Tenant"
                  : " — Joint Signer"}
                ; {signer.signed_at ?? "Not signed"}
                {selected.can_sign && signer.signed_at === null && (
                  <button
                    disabled={busy || signatureReason.trim() === ""}
                    onClick={() => {
                      recordSignature(signer.signer_id);
                    }}
                    type="button"
                  >
                    Record attributed signature
                  </button>
                )}
              </li>
            ))}
          </ul>
          {selected.can_manage_signers && (
            <form className="form-stack" onSubmit={addSigner}>
              <label>
                Additional Signer Customer identifier
                <input name="customer-id" required />
              </label>
              <label>
                Joint-responsibility reason
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Add Lease Signer
              </button>
            </form>
          )}
          {selected.can_sign && (
            <form className="form-stack confirmation-panel" onSubmit={sign}>
              <h4>Pre-signing summary</h4>
              <p>
                {selected.signers.length} Signer(s); Unit {selected.unit_number}
                ; {selected.start_date}–{selected.end_date};{" "}
                {money(selected.monthly_rent_usd_cents)} monthly. The server
                rechecks required parties, source terms, and non-overlap.
              </p>
              <label>
                Signing reason and evidence
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Review and sign Lease
              </button>
            </form>
          )}

          <h4>Occupants</h4>
          <p>
            Planned Occupant Customer identifiers:{" "}
            {selected.planned_occupant_customer_ids.length === 0
              ? "None recorded"
              : selected.planned_occupant_customer_ids.join(", ")}
            . Actual Occupancy remains separate and begins only at move-in.
          </p>
          {selected.occupancies.length === 0 ? (
            <p>No Occupancy has begun.</p>
          ) : (
            <ul>
              {selected.occupancies.map((value) => (
                <li key={value.occupancy_id}>
                  {value.customer_name}: {value.move_in_date}–
                  {value.move_out_date ?? "present"}; non-signer unless
                  separately listed above
                </li>
              ))}
            </ul>
          )}

          {selected.can_renew && (
            <form className="form-stack" onSubmit={renew}>
              <h4>Create successor renewal Lease</h4>
              <p>
                This creates a linked future draft and never an automatic
                month-to-month Lease.
              </p>
              <label>
                Successor Start Date
                <input name="start-date" required type="date" />
              </label>
              <label>
                Successor End Date
                <input name="end-date" required type="date" />
              </label>
              <label>
                Monthly Rent (USD)
                <input
                  min="0.01"
                  name="rent"
                  required
                  step="0.01"
                  type="number"
                />
              </label>
              <label>
                Renewal source reason
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Create successor Lease draft
              </button>
            </form>
          )}

          {selected.can_move_in && (
            <form
              className="form-stack confirmation-panel"
              onSubmit={completeMoveIn}
            >
              <h4>Move-in checklist and confirmation</h4>
              <ul>
                <li>Lease is SIGNED.</li>
                <li>
                  Reservation and Unit identities and versions will be
                  server-validated.
                </li>
                <li>
                  Required Security and conditional Pet Deposit balances will be
                  server-validated.
                </li>
                <li>Signer and Occupant identities remain distinct.</li>
              </ul>
              <label>
                Reservation identifier
                <input name="reservation-id" required />
              </label>
              <label>
                Reservation version
                <input
                  min="1"
                  name="reservation-version"
                  required
                  type="number"
                />
              </label>
              <label>
                Unit version
                <input min="1" name="unit-version" required type="number" />
              </label>
              <label>
                Actual Move-in Date
                <input name="move-in-date" required type="date" />
              </label>
              <label>
                Occupant Customer identifiers (one per line, maximum 20)
                <textarea
                  defaultValue={selected.planned_occupant_customer_ids.join(
                    "\n",
                  )}
                  name="occupant-customer-ids"
                  required
                  rows={4}
                />
              </label>
              <label>
                Move-in evidence reason
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Complete move-in atomically
              </button>
            </form>
          )}

          {selected.can_terminate && (
            <form
              className="form-stack confirmation-panel"
              onSubmit={terminate}
            >
              <h4>Authorized termination boundary</h4>
              <label>
                Actual termination date
                <input name="actual-date" required type="date" />
              </label>
              <label>
                Governing event reference
                <input maxLength={255} name="reference" required />
              </label>
              <label>
                Termination reason
                <input maxLength={500} name="reason" required />
              </label>
              <button disabled={busy} type="submit">
                Apply authorized termination
              </button>
              <p>
                Move-out and final financial handling remain separate workflows.
              </p>
            </form>
          )}

          <h4>Permanent Lease timeline</h4>
          {selected.timeline.length === 0 ? (
            <p>No timeline events loaded.</p>
          ) : (
            <ol>
              {selected.timeline.map((event) => (
                <li id={`timeline-${event.event_id}`} key={event.event_id}>
                  {event.occurred_at}: {event.event_kind} — {event.reason}
                  {event.source_reference !== null && (
                    <>
                      ; source{" "}
                      {event.source_href === null ? (
                        event.source_reference
                      ) : (
                        <a href={event.source_href}>{event.source_reference}</a>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ol>
          )}
          {selected.timeline_next_cursor !== null && (
            <button disabled={busy} onClick={loadMoreTimeline} type="button">
              Load more timeline events
            </button>
          )}
        </section>
      )}
    </section>
  );
}
