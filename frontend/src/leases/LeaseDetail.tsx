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
  type OccupancyResource,
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
import type { UnitApi } from "../unitClient";
import type { CustomerApi } from "../customerClient";
import type { CustomerCommandGate } from "../customers/commands";
import type { LettersApi } from "../letters/lettersClient";
import type { ReservationApi } from "../reservationClient";
import { leftText } from "../reservations/ReservationsList";
import {
  AddOccupantDialog,
  livingSigners,
  MoveOutOccupantDialog,
  CancelDraftDialog,
  EditDraftDialog,
  MoveInDialog,
} from "./LeaseDialogs";
import { LeaseDraftPrint } from "./LeaseDraftPrint";
import { SignDialog, type SigningApi } from "./SignLeaseDialog";
import { LeaseChip } from "./LeasesList";
import {
  RecordNoticeDialog,
  TerminateDialog,
  terminateDraft,
  type TerminateDraft,
} from "./TerminateDialogs";
import { stepOf } from "../moveout/moveoutData";
import {
  paymentsApi as defaultPaymentsApi,
  type PaymentsApi,
} from "../payments/paymentsClient";
import {
  settlementApi as defaultSettlementApi,
  type SettlementApi,
} from "../settlementClient";
import { ReceiveDepositDialog } from "./ReceiveDepositDialog";
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
  reservationApi: Pick<ReservationApi, "list">;
  customerApi: Pick<CustomerApi, "get" | "list">;
  lettersApi: Pick<LettersApi, "warnings" | "notices" | "recordNotice">;
  capabilities: ReadonlySet<string> | null;
  /** Letters opens the Lease with the Terminate dialog on the Rent ground. */
  terminateOnOpen?: boolean;
  /** V1-060 B6: Receive Security Deposit, the draft's planned deposit and signing with money. */
  settlementApi?: SigningApi &
    Pick<
      SettlementApi,
      "planSecurityDeposit" | "createSecurityDeposit" | "receiveIntoDeposit"
    >;
  paymentsApi?: PaymentsApi;
  /** V1-060 B6 (DL-102): New Customer from Add occupant; left out, the button is not shown. */
  customerCreateApi?: CustomerApi;
  customerGate?: CustomerCommandGate;
  /** V1-061 (DL-110): Edit draft reads the Unit's default Rent. */
  unitApi?: Pick<UnitApi, "get">;
}

export function LeaseDetail({
  language,
  leaseId,
  propertyId,
  api,
  depositApi,
  reservationApi,
  customerApi,
  lettersApi,
  capabilities,
  terminateOnOpen = false,
  settlementApi = defaultSettlementApi,
  paymentsApi = defaultPaymentsApi,
  customerCreateApi,
  customerGate,
  unitApi,
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
  const [dialog, setDialog] = useState<
    | "sign"
    | "edit"
    | "cancel"
    | "movein"
    | "terminate"
    | "notice"
    | "deposit"
    | "print"
    | "occupant"
    | "moveout"
    | null
  >(terminateOnOpen ? "terminate" : null);
  // V1-061 (DL-111): the Occupancy that Move out is for.
  const [leaving, setLeaving] = useState<OccupancyResource | null>(null);
  const [draft, setDraft] = useState<TerminateDraft>(() =>
    terminateDraft(terminateOnOpen ? "RENT" : null),
  );
  const [notice, setNotice] = useState<string | null>(null);
  // V1-060 B6 (DL-100, DL-101): the draft's recorded Security Deposit and, for a draft from a
  // Booking, the Reservation's Security Deposit; undefined until read.
  const [planned, setPlanned] = useState<number | null | undefined>(undefined);
  const [held, setHeld] = useState<{
    required: number;
    received: number;
  } | null>(null);
  // V1-060 B7: while the draft's deposit is being read, or could not be read, the page says so
  // and never "none".
  const [preview, setPreview] = useState<"reading" | "failed" | "shown">(
    "reading",
  );
  const [warning, setWarning] = useState<string | null>(null);
  const sequence = useRef(0);
  const today = todayInPhnomPenh();
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayDeposits = may("deposits.read");

  const draftKey =
    lease !== null && lease.status === "DRAFTED"
      ? `${lease.lease_id}/${String(lease.version)}`
      : null;
  useEffect(() => {
    if (draftKey === null || lease === null) return;
    let live = true;
    setPreview("reading");
    settlementApi
      .signingPreview(lease.lease_id)
      .then((found) => {
        if (!live) return;
        setPlanned(found.planned_security_deposit_usd_cents);
        setPreview("shown");
        const reservation = found.held_security_deposit;
        setHeld(
          reservation === null
            ? null
            : {
                required: reservation.required_usd_cents,
                received: reservation.received_usd_cents,
              },
        );
      })
      .catch(() => {
        if (!live) return;
        // V1-060 B7: not known is not "none": Edit draft then hides the deposit box.
        setPlanned(undefined);
        setHeld(null);
        setPreview("failed");
      });
    return () => {
      live = false;
    };
  }, [draftKey]);

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
  const mayTerminate =
    signed &&
    lease.can_terminate &&
    lease.actual_termination_date === null &&
    may("leases.terminate");
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
  // A draft that is not a renewal records its Security Deposit (DL-100, DL-101): a walk-in
  // draft's is made at signing, a Booking's is the Reservation's until the Lease is signed.
  const depositDraft =
    lease.status === "DRAFTED" && lease.predecessor_lease_id === null;
  const draftDeposit = planned ?? held?.required ?? null;
  const pet =
    deposits.state === "shown"
      ? (deposits.items.find((item) => item.deposit_type === "PET") ?? null)
      : null;
  // A signed Lease still running takes its Security Deposit here: a walk-in Lease that has
  // none yet (a renewal keeps the earlier one), or one not fully received.
  const mayReceiveDeposit =
    signed &&
    lease.actual_termination_date === null &&
    deposits.state === "shown" &&
    may("payments.record") &&
    may("payments.allocate") &&
    (security === null
      ? lease.predecessor_lease_id === null &&
        lease.security_deposit_id === null &&
        may("deposits.manage")
      : security.outstanding_required_usd_cents > 0);
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
  // V1-060 B6 (DL-102): Add occupant on a draft or a running Lease. A renewal without its own
  // move-in keeps the earlier Lease's Occupancies, so it shows no button.
  const mayAddOccupant =
    may("reservations.complete") &&
    may("customers.read") &&
    (lease.status === "DRAFTED" ||
      (signed &&
        lease.actual_termination_date === null &&
        (lease.end_date === null || today <= lease.end_date))) &&
    (movedIn ? stillIn : lease.predecessor_lease_id === null);
  // V1-061 (owner 2026-10-29, DL-111): Move out one person of a running Lease. Never the Primary
  // Tenant; a Signer only while another Signer still lives there.
  const running = signed && lease.actual_termination_date === null;
  const living = livingSigners(lease);
  const moveOutState = (occupancy: OccupancyResource) => {
    if (occupancy.move_out_date !== null) return null;
    if (occupancy.customer_id === lease.primary_tenant_id) return "primary";
    if (
      living.includes(occupancy.customer_id) &&
      living.filter((id) => id !== occupancy.customer_id).length === 0
    )
      return "last";
    return may("reservations.complete") && running ? "may" : null;
  };
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

  // Letters opens "#/leases/terminate:<id>"; once the dialog is done a reload shows the Lease.
  function leaveTerminateAddress() {
    if (/terminate(:|%3A)/i.test(window.location.hash))
      window.history.replaceState(
        null,
        "",
        hashForPage("leases", lease?.lease_id ?? leaseId),
      );
  }

  function open(
    which:
      | "sign"
      | "edit"
      | "cancel"
      | "movein"
      | "terminate"
      | "notice"
      | "deposit"
      | "print"
      | "occupant"
      | "moveout",
  ) {
    setNotice(null);
    setWarning(null);
    setDialog(which);
  }
  const dialogProps = {
    language,
    api,
    onClose: () => {
      setDialog(null);
    },
    onConflict: () => {
      setDialog(null);
      setWarning(lt(language, "conflict"));
      load();
    },
  };

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
        <div className="ui-actions">
          {lease.status === "DRAFTED" && lease.can_sign && (
            <button
              className="ui-btn primary"
              onClick={() => {
                open("sign");
              }}
              type="button"
            >
              <Icon name="lease" />
              {lt(language, "sign")}
            </button>
          )}
          {lease.status === "DRAFTED" && (
            <button
              className="ui-btn"
              onClick={() => {
                open("print");
              }}
              type="button"
            >
              <Icon name="print" />
              {lt(language, "lp_button")}
            </button>
          )}
          {lease.status === "DRAFTED" && lease.can_edit && (
            <button
              className="ui-btn"
              onClick={() => {
                open("edit");
              }}
              type="button"
            >
              {lt(language, "edit_draft")}
            </button>
          )}
          {lease.status === "DRAFTED" && lease.can_edit && (
            <button
              className="ui-btn"
              onClick={() => {
                open("cancel");
              }}
              type="button"
            >
              {lt(language, "cancel_draft")}
            </button>
          )}
          {signed && lease.can_renew && successorId === null && (
            <a
              className="ui-btn"
              href={hashForPage("leases", `renew:${lease.lease_id}`)}
            >
              {lt(language, "renew")}
            </a>
          )}
          {mayTerminate && (
            <button
              className="ui-btn"
              onClick={() => {
                setDraft(terminateDraft(null));
                open("terminate");
              }}
              type="button"
            >
              {lt(language, "terminate")}
              <span className="ui-badge">{lt(language, "manager")}</span>
            </button>
          )}
          {/* A renewal continues the earlier Lease's Occupancies, and a move-in is recorded
              from the Start Date, so neither shows the button. */}
          {signed &&
            lease.can_move_in &&
            !movedIn &&
            lease.actual_termination_date === null &&
            lease.predecessor_lease_id === null &&
            lease.start_date !== null &&
            lease.start_date <= today && (
              <button
                className="ui-btn primary"
                onClick={() => {
                  open("movein");
                }}
                type="button"
              >
                <Icon name="home" />
                {lt(language, "record_move_in")}
              </button>
            )}
          {stepOf(lease, today, successorId !== null) !== null && (
            <a
              className="ui-btn primary"
              href={hashForPage("moveout", lease.lease_id)}
            >
              <Icon name="moveout" />
              {lt(language, "open_moveout")}
            </a>
          )}
        </div>
      </div>
      {failure}
      {warning !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{warning}</p>
        </div>
      )}
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
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
            <div className="ui-chead">
              <h2 id="lease-occupants">{lt(language, "occupants")}</h2>
              {mayAddOccupant && (
                <button
                  className="ui-btn"
                  onClick={() => {
                    open("occupant");
                  }}
                  type="button"
                >
                  <Icon name="plus" />
                  {lt(language, "add_occ")}
                </button>
              )}
            </div>
            {lease.occupancies.length === 0 &&
            lease.planned_occupants.length > 0 ? (
              <ul className="ui-plain">
                {lease.planned_occupants.map((person) => (
                  <li className="ui-line" key={person.customer_id}>
                    <span>
                      {customerLink(person.customer_id, person.customer_name)}
                      <span className="ui-sub2">
                        {lt(
                          language,
                          person.customer_id === lease.primary_tenant_id
                            ? "primary_tag"
                            : "occ_tag",
                        )}
                      </span>
                    </span>
                    <span className="ui-small">
                      {lt(language, "in_pending")}
                    </span>
                  </li>
                ))}
              </ul>
            ) : lease.occupancies.length === 0 ? (
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
                    {moveOutState(occupancy) === "may" && (
                      <button
                        className="ui-btn"
                        onClick={() => {
                          setLeaving(occupancy);
                          open("moveout");
                        }}
                        type="button"
                      >
                        {lt(language, "mo_button")}
                      </button>
                    )}
                    {running &&
                      may("reservations.complete") &&
                      (moveOutState(occupancy) === "last" ||
                        moveOutState(occupancy) === "primary") && (
                        <span className="ui-small ui-muted">
                          {lt(
                            language,
                            moveOutState(occupancy) === "last"
                              ? "mo_last_signer"
                              : "mo_primary",
                          )}
                        </span>
                      )}
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
                {mayReceiveDeposit && (
                  <div className="ui-actions">
                    <button
                      className="ui-btn primary"
                      onClick={() => {
                        open("deposit");
                      }}
                      type="button"
                    >
                      <Icon name="plus" small />
                      {lt(language, "rd_button")}
                    </button>
                  </div>
                )}
                <h3>{lt(language, "dep_sec")}</h3>
                {security === null && depositDraft && preview !== "shown" ? (
                  <p className="ui-muted" role="status">
                    {lt(
                      language,
                      preview === "reading"
                        ? "dep_term_reading"
                        : "dep_term_failed",
                    )}
                  </p>
                ) : security === null &&
                  depositDraft &&
                  draftDeposit !== null ? (
                  <>
                    <p>
                      {lt(language, "dep_term", usdFromCents(draftDeposit))}
                    </p>
                    {held !== null && (
                      <p className="ui-muted">
                        {held.received >= draftDeposit
                          ? lt(language, "dep_term_paid")
                          : lt(
                              language,
                              "dep_term_booking",
                              usdFromCents(held.received),
                              usdFromCents(draftDeposit - held.received),
                            )}
                      </p>
                    )}
                  </>
                ) : security === null ? (
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
      {dialog === "sign" && lease.status === "DRAFTED" && (
        <SignDialog
          language={language}
          lease={lease}
          mayCollect={may("payments.record") && may("payments.allocate")}
          mayCreateDeposit={may("deposits.manage")}
          // V1-060 B7: after a lost answer the Lease may be signed: read it again.
          onClose={() => {
            setDialog(null);
            load();
          }}
          onConflict={dialogProps.onConflict}
          onSaved={(message) => {
            setDialog(null);
            setNotice(message);
            load();
          }}
          paymentsApi={paymentsApi}
          propertyId={propertyId}
          reservationApi={reservationApi}
          signingApi={settlementApi}
        />
      )}
      {dialog === "print" && lease.status === "DRAFTED" && (
        <LeaseDraftPrint
          language={language}
          lease={lease}
          onClose={() => {
            setDialog(null);
          }}
          signingApi={settlementApi}
        />
      )}
      {dialog === "cancel" && lease.status === "DRAFTED" && (
        <CancelDraftDialog
          {...dialogProps}
          lease={lease}
          onSaved={(saved) => {
            setDialog(null);
            setLease(saved);
            setNotice(lt(language, "cancelled_toast"));
            load();
          }}
        />
      )}
      {dialog === "movein" && signed && (
        <MoveInDialog
          {...dialogProps}
          customerApi={may("customers.read") ? customerApi : null}
          lease={lease}
          onSaved={(saved) => {
            setDialog(null);
            setLease(saved);
            setNotice(lt(language, "moved_in_toast"));
            load();
          }}
        />
      )}
      {dialog === "occupant" && mayAddOccupant && (
        <AddOccupantDialog
          {...dialogProps}
          customerApi={customerApi}
          lease={lease}
          newCustomer={
            customerCreateApi !== undefined && customerGate !== undefined
              ? { api: customerCreateApi, gate: customerGate }
              : null
          }
          onSaved={(saved, message) => {
            setDialog(null);
            setLease(saved);
            setNotice(message);
            load();
          }}
        />
      )}
      {dialog === "moveout" && leaving !== null && (
        <MoveOutOccupantDialog
          {...dialogProps}
          lease={lease}
          occupancy={leaving}
          onSaved={(saved, message) => {
            setDialog(null);
            setLeaving(null);
            setLease(saved);
            setNotice(message);
            load();
          }}
        />
      )}
      {dialog === "terminate" && mayTerminate && (
        <TerminateDialog
          {...dialogProps}
          lease={lease}
          lettersApi={lettersApi}
          onClose={() => {
            leaveTerminateAddress();
            setDialog(null);
          }}
          onRecordNotice={(typed) => {
            setDraft(typed);
            setDialog("notice");
          }}
          onSaved={(saved, message) => {
            leaveTerminateAddress();
            setDialog(null);
            setLease(saved);
            setNotice(message);
            load();
          }}
          draft={draft}
        />
      )}
      {dialog === "notice" && mayTerminate && (
        <RecordNoticeDialog
          language={language}
          lease={lease}
          lettersApi={lettersApi}
          onClose={() => {
            setDialog("terminate");
          }}
          onConflict={dialogProps.onConflict}
          onSaved={(message) => {
            // Back to Terminate with what was typed; it reads the notices again.
            setDialog("terminate");
            setNotice(message);
          }}
        />
      )}
      {dialog === "deposit" && mayReceiveDeposit && (
        <ReceiveDepositDialog
          language={language}
          lease={lease}
          onClose={() => {
            // V1-060 B7 (third review): the money may be saved, so read the Lease again.
            setDialog(null);
            load();
          }}
          onSaved={(message) => {
            setDialog(null);
            setNotice(message);
            load();
          }}
          paymentsApi={paymentsApi}
          propertyId={propertyId}
          security={security}
          settlementApi={settlementApi}
        />
      )}
      {dialog === "edit" && lease.status === "DRAFTED" && (
        <EditDraftDialog
          {...dialogProps}
          lease={lease}
          planned={depositDraft && planned !== undefined ? planned : undefined}
          held={held}
          mayLowerRent={
            capabilities === null
              ? null
              : capabilities.has("rent.below_default")
          }
          signingApi={settlementApi}
          unitApi={unitApi}
          // The dates and Rent may be saved without the Security Deposit (B7): read again.
          onClose={() => {
            setDialog(null);
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setLease(saved);
            setNotice(lt(language, "draft_saved"));
            load();
          }}
        />
      )}
    </>
  );
}
