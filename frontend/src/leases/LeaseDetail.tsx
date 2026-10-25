// V1-058 R3: the Lease page (DESIGN.md "Leases (round 2)"): the head with the chip, period and
// Rent; notices for drafts, Leases without a move-in and Leases ending soon; the Lease facts,
// Signers, Occupants, Rent and services, Deposits, Termination and History. The actions come
// with the next step; until then they stay in the earlier forms under the page.

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import type { DepositApi, DepositResource } from "../depositClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
  type LeaseTimelineEvent,
} from "../leaseClient";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { leftText } from "../reservations/ReservationsList";
import { LeaseChip } from "./LeasesList";
import { daysBetween, initialRent, kindOf } from "./leasesData";
import { hasLeaseText, lt } from "./text";

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv">
      {rows.map(([term, value]) => (
        <div key={term} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function eventName(language: Language, kind: string): string {
  const key = `e_${kind}`;
  return hasLeaseText(key) ? lt(language, key) : lt(language, "e_other");
}

// The timeline is read oldest first; a long one has more pages.
const MAX_TIMELINE_PAGES = 20;

type DepositsState =
  | { state: "loading" | "hidden" | "failed" }
  | { state: "shown"; items: DepositResource[] };

export interface LeaseDetailProps {
  language: Language;
  leaseId: string;
  /** A Lease of another Property is not shown. */
  propertyId: string;
  api: LeaseApi;
  depositApi: DepositApi;
  capabilities: ReadonlySet<string> | null;
}

export function LeaseDetail({
  language,
  leaseId,
  propertyId,
  api,
  depositApi,
  capabilities,
}: LeaseDetailProps) {
  const [lease, setLease] = useState<LeaseResource | null>(null);
  const [timeline, setTimeline] = useState<LeaseTimelineEvent[]>([]);
  const [deposits, setDeposits] = useState<DepositsState>({
    state: "loading",
  });
  const [missing, setMissing] = useState(false);
  const [successorId, setSuccessorId] = useState<string | null>(null);
  const [historyIncomplete, setHistoryIncomplete] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const sequence = useRef(0);
  const today = todayInPhnomPenh();
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayDeposits = may("deposits.read");

  const load = useCallback(() => {
    const operation = ++sequence.current;
    const current = () => operation === sequence.current;
    void api
      .get(leaseId)
      .then(async (loaded) => {
        if (!current()) return;
        setLoadFailed(false);
        if (loaded.property_id !== propertyId) {
          setLease(null);
          setMissing(true);
          return;
        }
        setLease(loaded);
        setMissing(false);
        setTimeline(loaded.timeline);
        setHistoryIncomplete(false);
        let cursor = loaded.timeline_next_cursor;
        const events = [...loaded.timeline];
        // A later page that cannot be read leaves the page as it is, with a note.
        try {
          for (
            let page = 0;
            cursor !== null && page < MAX_TIMELINE_PAGES;
            page += 1
          ) {
            const next = await api.timeline(leaseId, cursor);
            if (!current()) return;
            events.push(...next.items);
            cursor = next.next_cursor;
            setTimeline([...events]);
          }
          if (cursor !== null) setHistoryIncomplete(true);
        } catch {
          if (current()) setHistoryIncomplete(true);
        }
        // A renewal counts only while it is not a cancelled draft (newest first).
        const successors = events
          .filter((event) => event.event_kind === "lease.renewal_successor")
          .flatMap((event) =>
            event.source_reference === null ? [] : [event.source_reference],
          )
          .reverse();
        for (const id of successors) {
          try {
            const next = await api.get(id);
            if (!current()) return;
            if (next.status !== "CANCELLED") {
              setSuccessorId(id);
              return;
            }
          } catch {
            // Not readable: it is not shown as the renewal.
          }
        }
        if (current()) setSuccessorId(null);
      })
      .catch((error: unknown) => {
        if (!current()) return;
        // No answer is not "not found": keep what is shown and offer Retry.
        if (error instanceof LeaseUnavailableError) setLoadFailed(true);
        else setMissing(true);
      });
    if (!mayDeposits) {
      setDeposits({ state: "hidden" });
      return;
    }
    void depositApi
      .leaseDeposits(leaseId)
      .then((loaded) => {
        if (current()) setDeposits({ state: "shown", items: loaded.items });
      })
      .catch(() => {
        if (current()) setDeposits({ state: "failed" });
      });
  }, [api, depositApi, leaseId, propertyId, mayDeposits]);

  useEffect(() => {
    setLease(null);
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("leases");
      }}
      type="button"
    >
      <Icon name="back" small />
      {lt(language, "back")}
    </button>
  );
  const failure = loadFailed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{lt(language, "load_failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {lt(language, "retry")}
      </button>
    </div>
  );

  if (missing) {
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{lt(language, "missing")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {lt(language, "retry")}
          </button>
        </div>
      </>
    );
  }
  if (lease === null) {
    return (
      <>
        {back}
        {failure || (
          <p className="ui-muted" role="status">
            {lt(language, "loading_one")}
          </p>
        )}
      </>
    );
  }

  const kind = kindOf(lease, today, successorId !== null);
  // An approved change of the Initial Rent Due Date: the Invoice shows the date.
  const dueChanged = timeline.some(
    (event) => event.event_kind === "lease.initial_rent_due_date_override",
  );
  const signed = lease.status === "SIGNED";
  const rent = lease.monthly_rent_usd_cents;
  const movedIn = lease.occupancies.length > 0;
  const left =
    lease.end_date === null ? null : daysBetween(today, lease.end_date);
  const initial =
    lease.start_date !== null && rent !== null
      ? initialRent(lease.start_date, rent)
      : null;
  const security =
    deposits.state === "shown"
      ? (deposits.items.find((item) => item.deposit_type === "SECURITY") ??
        null)
      : null;
  const pet =
    deposits.state === "shown"
      ? (deposits.items.find((item) => item.deposit_type === "PET") ?? null)
      : null;
  const history = [...timeline].sort((left_, right) =>
    right.occurred_at.localeCompare(left_.occurred_at),
  );
  const movedOut = lease.occupancies
    .map((occupancy) => occupancy.move_out_date)
    .filter((date) => date !== null)
    .sort()
    .at(-1);
  const stillIn = lease.occupancies.some(
    (occupancy) => occupancy.move_out_date === null,
  );
  const customerLink = (id: string, name: string) =>
    may("customers.read") ? (
      <a className="ui-no" href={hashForPage("customers", id)}>
        {name}
      </a>
    ) : (
      name
    );
  const period = (from: string | null, to: string | null) => (
    <span className="ui-num ui-nowrap">
      {lt(language, "from_to", dayText(from), dayText(to))}
    </span>
  );

  function depositRows(deposit: DepositResource): [string, ReactNode][] {
    const outstanding = deposit.outstanding_required_usd_cents;
    return [
      [
        lt(language, "dep_req"),
        <span className="ui-num">
          {usdFromCents(deposit.required_usd_cents)}
        </span>,
      ],
      [
        lt(language, "dep_rcv"),
        <b className="ui-num">{usdFromCents(deposit.received_usd_cents)}</b>,
      ],
      [
        lt(language, "dep_out"),
        <span>
          <span className="ui-num">{usdFromCents(outstanding)}</span>
          <span className="ui-sub2">
            {outstanding === 0
              ? lt(language, "dep_full")
              : initial !== null && deposit.deposit_type === "SECURITY"
                ? lt(
                    language,
                    "dep_rest_due",
                    usdFromCents(outstanding),
                    dayText(initial.due),
                  )
                : ""}
          </span>
        </span>,
      ],
    ];
  }

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">
              {lt(language, "title", lease.unit_number)}
            </h2>
            <LeaseChip kind={kind} language={language} />
          </div>
          <p>
            {lease.primary_tenant_name} ·{" "}
            <span className="ui-num">
              {lt(
                language,
                "from_to",
                dayText(lease.start_date),
                dayText(lease.end_date),
              )}
            </span>
            {rent !== null && (
              <>
                {" · "}
                <span className="ui-num">
                  {lt(language, "rent_month", usdFromCents(rent))}
                </span>
              </>
            )}
          </p>
        </div>
      </div>
      {failure}
      {lease.status === "DRAFTED" && (
        <div className="ui-notice" role="status">
          <Icon name="info" />
          <p>{lt(language, "draft_banner")}</p>
        </div>
      )}
      {signed && !movedIn && (
        <div className="ui-notice warn" role="status">
          <Icon name="door" />
          <p>{lt(language, "no_movein_banner", dayText(lease.start_date))}</p>
        </div>
      )}
      {kind === "ending" && left !== null && lease.end_date !== null && (
        <div className="ui-notice warn" role="status">
          <Icon name="clock" />
          <p>
            {lt(
              language,
              "ending_banner",
              dayText(lease.end_date),
              leftText(language, left),
            )}
          </p>
        </div>
      )}
      {successorId !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{lt(language, "renewed_banner")}</p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="lease-facts" className="ui-card">
            <h2 id="lease-facts">{lt(language, "details")}</h2>
            <Kv
              rows={[
                [
                  lt(language, "unit"),
                  may("units.read") ? (
                    <a
                      className="ui-no ui-num"
                      href={hashForPage("units", lease.unit_id)}
                    >
                      {lease.unit_number}
                    </a>
                  ) : (
                    lease.unit_number
                  ),
                ],
                [
                  lt(language, "primary"),
                  customerLink(
                    lease.primary_tenant_id,
                    lease.primary_tenant_name,
                  ),
                ],
                [
                  lt(language, "start"),
                  <span className="ui-num ui-nowrap">
                    {dayText(lease.start_date)}
                  </span>,
                ],
                [
                  lt(language, "end"),
                  <span>
                    <span className="ui-num ui-nowrap">
                      {dayText(lease.end_date)}
                    </span>
                    {lease.actual_termination_date !== null && (
                      <span className="ui-sub2 warn">
                        {lt(
                          language,
                          "ended_on",
                          dayText(lease.actual_termination_date),
                        )}
                      </span>
                    )}
                  </span>,
                ],
                [
                  lt(language, "rent"),
                  rent === null ? (
                    <span className="ui-muted">
                      {lt(language, "not_recorded")}
                    </span>
                  ) : (
                    <span>
                      <span className="ui-num">{usdFromCents(rent)}</span>
                      {signed && (
                        <span className="ui-sub2">
                          {lt(language, "rent_fixed")}
                        </span>
                      )}
                    </span>
                  ),
                ],
                [
                  lt(language, "signed_on"),
                  lease.signed_at === null ? (
                    <span className="ui-muted">
                      {lt(language, "not_signed")}
                    </span>
                  ) : (
                    <span className="ui-num ui-nowrap">
                      {momentText(lease.signed_at)}
                    </span>
                  ),
                ],
                ...(lease.predecessor_lease_id !== null
                  ? ([
                      [
                        lt(language, "renewal_of"),
                        <a
                          className="ui-no"
                          href={hashForPage(
                            "leases",
                            lease.predecessor_lease_id,
                          )}
                        >
                          {lt(language, "title", lease.unit_number)}
                        </a>,
                      ],
                    ] as [string, ReactNode][])
                  : []),
                ...(successorId !== null
                  ? ([
                      [
                        lt(language, "renewed_by"),
                        <a
                          className="ui-no"
                          href={hashForPage("leases", successorId)}
                        >
                          {lt(language, "title", lease.unit_number)}
                        </a>,
                      ],
                    ] as [string, ReactNode][])
                  : []),
              ]}
            />
            {signed && (
              <p className="ui-small ui-muted">{lt(language, "end_note")}</p>
            )}
          </section>
          <section aria-labelledby="lease-signers" className="ui-card">
            <h2 id="lease-signers">{lt(language, "signers")}</h2>
            <ul className="ui-plain">
              {lease.signers.map((signer) => (
                <li className="ui-line" key={signer.signer_id}>
                  <span>
                    {customerLink(signer.customer_id, signer.customer_name)}
                    {signer.is_primary_tenant && (
                      <span className="ui-sub2">
                        {lt(language, "primary_tag")}
                      </span>
                    )}
                  </span>
                  {signer.signed_at !== null ? (
                    <Chip icon="check" tone="ok">
                      {lt(
                        language,
                        "signed_at",
                        dayText(todayInPhnomPenh(new Date(signer.signed_at))),
                      )}
                    </Chip>
                  ) : lease.status === "DRAFTED" ? (
                    <Chip tone="warn">{lt(language, "to_sign")}</Chip>
                  ) : lease.signed_at !== null ? (
                    <Chip icon="check" tone="ok">
                      {lt(language, "signed")}
                    </Chip>
                  ) : null}
                </li>
              ))}
            </ul>
            <p className="ui-small ui-muted">
              {lt(language, "signers_note")}{" "}
              {lease.status === "DRAFTED" && lt(language, "signers_draft")}
            </p>
          </section>
          <section aria-labelledby="lease-occupants" className="ui-card">
            <h2 id="lease-occupants">{lt(language, "occupants")}</h2>
            {lease.occupancies.length === 0 ? (
              <p className="ui-muted">
                {lease.planned_occupant_customer_ids.length > 0
                  ? lt(
                      language,
                      "planned",
                      lease.planned_occupant_customer_ids.length,
                    )
                  : lt(language, "no_movein_yet")}
              </p>
            ) : (
              <ul className="ui-plain">
                {lease.occupancies.map((occupancy) => (
                  <li className="ui-line" key={occupancy.occupancy_id}>
                    {customerLink(
                      occupancy.customer_id,
                      occupancy.customer_name,
                    )}
                    <span className="ui-small ui-num">
                      {lt(
                        language,
                        "in_since",
                        dayText(occupancy.move_in_date),
                      )}
                      {occupancy.move_out_date !== null &&
                        ` · ${lt(language, "out_on", dayText(occupancy.move_out_date))}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="ui-small ui-muted">
              {lt(language, "occupants_note")}
            </p>
          </section>
          <section aria-labelledby="lease-rent" className="ui-card">
            <h2 id="lease-rent">{lt(language, "rent_t")}</h2>
            {initial !== null &&
              rent !== null &&
              lease.status !== "CANCELLED" && (
                <Kv
                  rows={[
                    [
                      lt(language, "initial_rent"),
                      <span>
                        <span className="ui-num">
                          {initial.days === initial.daysInMonth
                            ? lt(language, "full_month", usdFromCents(rent))
                            : lt(
                                language,
                                "prorated",
                                usdFromCents(rent),
                                initial.days,
                                initial.daysInMonth,
                                usdFromCents(initial.firstPart),
                              )}
                        </span>
                        {initial.nextMonth > 0 && (
                          <span className="ui-sub2 ui-num">
                            {lt(
                              language,
                              "plus_next",
                              usdFromCents(initial.nextMonth),
                            )}
                          </span>
                        )}
                        <b className="ui-sub2 ui-num">
                          {dueChanged
                            ? lt(
                                language,
                                "initial_total_changed",
                                usdFromCents(initial.total),
                              )
                            : lt(
                                language,
                                "initial_total",
                                usdFromCents(initial.total),
                                dayText(initial.due),
                              )}
                        </b>
                        {!dueChanged && (
                          <span className="ui-sub2">
                            {lt(language, "initial_due_note")}
                          </span>
                        )}
                      </span>,
                    ],
                  ]}
                />
              )}
            <p className="ui-small">
              <b>{lt(language, "then")}:</b> {lt(language, "recurring")}
            </p>
            <h3>{lt(language, "services")}</h3>
            {lease.service_terms.length === 0 ? (
              <p className="ui-muted">{lt(language, "no_services")}</p>
            ) : (
              <ul className="ui-plain">
                {lease.service_terms.map((term) => (
                  <li className="ui-line" key={term.term_id}>
                    {term.service_name}
                    <span className="ui-small">
                      {term.applicable_through === null
                        ? lt(
                            language,
                            "from_date",
                            dayText(term.applicable_from),
                          )
                        : period(term.applicable_from, term.applicable_through)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="ui-small ui-muted">{lt(language, "services_note")}</p>
          </section>
        </div>
        <div className="ui-stack">
          <section aria-labelledby="lease-deposits" className="ui-card">
            <h2 id="lease-deposits">{lt(language, "deposits")}</h2>
            {deposits.state === "hidden" && (
              <p className="ui-muted">{lt(language, "deposits_hidden")}</p>
            )}
            {deposits.state === "failed" && (
              <p className="ui-muted">{lt(language, "deposits_failed")}</p>
            )}
            {deposits.state === "shown" && (
              <>
                <h3>{lt(language, "dep_sec")}</h3>
                {security === null ? (
                  <p className="ui-muted">{lt(language, "no_deposit")}</p>
                ) : (
                  <Kv rows={depositRows(security)} />
                )}
                {pet !== null ? (
                  <>
                    <h3>{lt(language, "dep_pet")}</h3>
                    <Kv rows={depositRows(pet)} />
                  </>
                ) : lease.pet_deposit_required ? (
                  <>
                    <h3>{lt(language, "dep_pet")}</h3>
                    <p className="ui-muted">
                      {lt(
                        language,
                        "pet_approved",
                        lease.pet_description ?? "",
                      )}
                    </p>
                  </>
                ) : (
                  <p className="ui-muted">{lt(language, "no_pet")}</p>
                )}
              </>
            )}
            <div className="ui-notice">
              <Icon name="info" />
              <p>{lt(language, "dep_note")}</p>
            </div>
          </section>
          {lease.status === "TERMINATED" && (
            <section aria-labelledby="lease-termination" className="ui-card">
              <h2 id="lease-termination">{lt(language, "term_t")}</h2>
              <Kv
                rows={[
                  [
                    lt(language, "term_date"),
                    <span className="ui-num ui-nowrap">
                      {dayText(lease.actual_termination_date)}
                    </span>,
                  ],
                  [
                    lt(language, "term_recorded"),
                    <span className="ui-num ui-nowrap">
                      {momentText(lease.terminated_at)}
                    </span>,
                  ],
                  [
                    lt(language, "moveout_on"),
                    stillIn || movedOut === undefined ? (
                      <span className="ui-muted">
                        {stillIn
                          ? lt(language, "still_in")
                          : lt(language, "no_movein_yet")}
                      </span>
                    ) : (
                      <span className="ui-num ui-nowrap">
                        {dayText(movedOut)}
                      </span>
                    ),
                  ],
                ]}
              />
            </section>
          )}
          <section aria-labelledby="lease-history" className="ui-card">
            <h2 id="lease-history">{lt(language, "history")}</h2>
            {historyIncomplete && (
              <p className="ui-small ui-muted">
                {lt(language, "history_incomplete")}
              </p>
            )}
            {history.length === 0 ? (
              <p className="ui-muted">{lt(language, "h_none")}</p>
            ) : (
              <ol className="ui-timeline">
                {history.map((event) => (
                  <li key={event.event_id}>
                    <div>
                      {eventName(language, event.event_kind)}
                      {event.reason.trim() !== "" && (
                        <span className="ui-sub2">{event.reason}</span>
                      )}
                      <small className="ui-num">
                        {momentText(event.occurred_at)}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
