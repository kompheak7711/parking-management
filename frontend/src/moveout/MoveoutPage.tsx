// V1-058 R3 Move-out: the Move-out tab of Leases (DESIGN.md "Move-out (round 3)"). "#/moveout"
// shows the list; "#/moveout/<Lease id>" shows the steps of one Lease. This step builds the
// list, the page and the Hand-back step; final readings, inspection and charges, the Final
// Settlement and corrections after closure come next. The list cannot yet tell a closed Final
// Settlement apart (the server has no read of it), so "To confirm" and "Closed" come later.

import "../shell/screens.css";

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import type { DepositApi, DepositResource } from "../depositClient";
import type { InvoiceApi, InvoiceResource } from "../invoiceClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
  type LeaseTimelineEvent,
} from "../leaseClient";
import { loadLeasesData } from "../leases/leasesData";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import type { UtilityApi } from "../utilityClient";
import type { EvidenceRecord, UtilityLeaseApi } from "../utilityLeaseClient";
import { daysBetween } from "../reservations/reservationsData";
import {
  type FinalInputs,
  currentFinalInputs,
  finalInvoiceOf,
  latestInputsId,
} from "./finalReadings";
import { FinalReadingsDialog } from "./FinalReadingsDialog";
import { HandBackDialog, rentRuleText } from "./HandBackDialog";
import {
  MoveOutUnavailableError,
  type MoveOutApi,
  type MoveOutPage,
  type MoveOutRecord,
} from "./moveoutClient";
import {
  type HeldCell,
  type MoveOutStage,
  type MoveOutStep,
  endOf,
  handedBackOn,
  loadHeld,
  signedRenewalOf,
  stageOf,
  stepOf,
  terminationOf,
} from "./moveoutData";
import { conditionText, mt } from "./text";

const STEP_CHIPS: Record<MoveOutStep, [Tone, ShellIcon]> = {
  soon: ["warn", "clock"],
  in: ["warn", "clock"],
  out: ["info", "door"],
  skip: ["info", "door"],
};

export function MoveOutChip({
  language,
  step,
}: {
  language: Language;
  step: MoveOutStep;
}) {
  const [tone, icon] = STEP_CHIPS[step];
  return (
    <Chip icon={icon} tone={tone}>
      {mt(language, `s_${step}`)}
    </Chip>
  );
}

function ago(language: Language, today: string, day: string): string {
  const days = daysBetween(today, day);
  if (days === 0) return mt(language, "today");
  if (days === 1) return mt(language, "in1");
  if (days === -1) return mt(language, "ago1");
  return days > 0 ? mt(language, "in_days", days) : mt(language, "ago", -days);
}

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv">
      {rows.map(([term, value], index) => (
        <div key={`${String(index)}:${term}`} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface MoveoutPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  today: string;
  leaseApi: Pick<LeaseApi, "list" | "get" | "timeline" | "terminate">;
  depositApi: Pick<DepositApi, "leaseDeposits">;
  unitApi: Pick<UnitApi, "get">;
  moveOutApi: MoveOutApi;
  utilityApi: Pick<UtilityApi, "loadMeters" | "loadReadings" | "recordReading">;
  utilityLeaseApi: Pick<
    UtilityLeaseApi,
    "readFinalInputs" | "recordFinalInputs" | "createFinalInvoice"
  >;
  invoiceApi: Pick<InvoiceApi, "list">;
  capabilities: ReadonlySet<string> | null;
}

export function MoveoutPage(props: MoveoutPageProps) {
  const detail = useHashDetail("moveout");
  if (props.propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{mt(props.language, "no_property")}</p>
      </div>
    );
  }
  if (detail !== null)
    return (
      <MoveoutDetail
        {...props}
        key={`${detail}:${props.propertyId}`}
        leaseId={detail}
      />
    );
  return <MoveoutList {...props} />;
}

interface Row {
  lease: LeaseResource;
  step: MoveOutStep;
}

function MoveoutList({
  language,
  propertyId,
  active,
  today,
  leaseApi,
  depositApi,
  capabilities,
}: MoveoutPageProps) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [held, setHeld] = useState<Map<string, HeldCell> | null>(null);
  const [failed, setFailed] = useState(false);
  const [card, setCard] = useState<MoveOutStage | "all">("all");
  const sequence = useRef(0);
  const mayDeposits =
    capabilities === null || capabilities.has("deposits.read");

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void loadLeasesData(leaseApi, propertyId)
      .then(async ({ leases }) => {
        if (operation !== sequence.current) return;
        const renewed = signedRenewalOf(leases);
        const found = leases.flatMap((lease) => {
          const step = stepOf(lease, today, renewed.has(lease.lease_id));
          return step === null ? [] : [{ lease, step }];
        });
        setRows(found);
        const cells = await loadHeld(
          depositApi,
          found.map((row) => row.lease),
          mayDeposits,
        );
        if (operation === sequence.current) setHeld(cells);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [leaseApi, depositApi, propertyId, today, mayDeposits]);

  // Another Property never shows the move-outs of the one before.
  useEffect(() => {
    setRows(null);
    setHeld(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{mt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {mt(language, "retry")}
      </button>
    </div>
  );
  if (rows === null)
    return (
      failure || (
        <p className="ui-muted" role="status">
          {mt(language, "loading")}
        </p>
      )
    );

  // Handed back first (work to finish), then the soonest end.
  const order = (row: Row) => (stageOf(row.step) === "out" ? 0 : 1);
  const shown = rows
    .filter((row) => card === "all" || stageOf(row.step) === card)
    .sort(
      (left, right) =>
        order(left) - order(right) ||
        (endOf(left.lease) ?? "").localeCompare(endOf(right.lease) ?? "") ||
        left.lease.unit_number.localeCompare(right.lease.unit_number),
    );
  const open = (id: string) => {
    openPageInAddress("moveout", false, id);
  };
  const cards: [MoveOutStage, ShellIcon, Tone][] = [
    ["soon", "clock", "warn"],
    ["out", "door", "info"],
  ];

  return (
    <>
      {failure}
      <div className="ui-head">
        <p>{mt(language, "sub")}</p>
      </div>
      <div className="ui-kpis">
        {cards.map(([value, icon, tone]) => (
          <CountCard
            icon={icon}
            key={value}
            label={mt(language, `c_${value}`)}
            note={mt(language, `c_${value}_s`)}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={rows.filter((row) => stageOf(row.step) === value).length}
          />
        ))}
      </div>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {mt(language, "showing", mt(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {mt(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">{mt(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{mt(language, "col_unit")}</th>
                    <th scope="col">{mt(language, "col_cust")}</th>
                    <th scope="col">{mt(language, "col_end")}</th>
                    <th scope="col">{mt(language, "col_hb")}</th>
                    <th scope="col">{mt(language, "col_step")}</th>
                    <th className="r" scope="col">
                      {mt(language, "col_dep")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(({ lease, step }) => {
                    const id = lease.lease_id;
                    const end = endOf(lease);
                    const back = handedBackOn(lease);
                    const cell = held?.get(id);
                    return (
                      <tr
                        className="ui-row"
                        key={id}
                        onClick={() => {
                          open(id);
                        }}
                      >
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("moveout", id)}
                            onClick={(event) => {
                              event.stopPropagation();
                              if (
                                event.button !== 0 ||
                                event.metaKey ||
                                event.ctrlKey ||
                                event.shiftKey ||
                                event.altKey
                              )
                                return;
                              event.preventDefault();
                              open(id);
                            }}
                          >
                            {lease.unit_number}
                          </a>
                        </td>
                        <td>{lease.primary_tenant_name}</td>
                        <td className="ui-num">
                          {dayText(end)}
                          {lease.actual_termination_date !== null &&
                            lease.end_date !== null && (
                              <span className="ui-sub2">
                                {mt(language, "was", dayText(lease.end_date))}
                              </span>
                            )}
                        </td>
                        <td className="ui-num">
                          {back !== null ? (
                            dayText(back)
                          ) : step === "skip" ? (
                            <span className="ui-muted">
                              {mt(language, "skip")}
                            </span>
                          ) : (
                            <span className="ui-muted">—</span>
                          )}
                        </td>
                        <td>
                          <MoveOutChip language={language} step={step} />
                          {stageOf(step) === "soon" && end !== null && (
                            <span className="ui-sub2">
                              {ago(language, today, end)}
                            </span>
                          )}
                          <span className="ui-sub2">
                            {mt(
                              language,
                              step === "out"
                                ? "next_final"
                                : step === "skip"
                                  ? "next_settle"
                                  : "next_hb",
                            )}
                          </span>
                        </td>
                        <td className="r ui-num">
                          {cell?.state === "shown" ? (
                            usdFromCents(cell.held)
                          ) : (
                            <span className="ui-muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot ui-tfoot-row">
              <span>
                {shown.length === 1
                  ? mt(language, "n1")
                  : mt(language, "n", shown.length)}
              </span>
              <span>{mt(language, "rule_note")}</span>
            </div>
          </>
        )}
      </div>
    </>
  );
}

type Mark = "done" | "now" | "todo" | "skip";

function Step({
  language,
  number,
  mark,
  title,
  children,
  actions,
}: {
  language: Language;
  number: number;
  mark: Mark;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const tone: Tone =
    mark === "done" ? "ok" : mark === "now" ? "info" : "neutral";
  return (
    <li className={`ui-mstep s-${mark}`}>
      <span aria-hidden="true" className={`ui-mark ${mark}`}>
        {mark === "done" ? (
          <Icon name="check" small />
        ) : mark === "skip" ? (
          "–"
        ) : (
          ""
        )}
      </span>
      <div className="ui-mbody">
        <div className="ui-mhead">
          <h3>
            {number}. {title}
          </h3>
          <Chip tone={tone}>{mt(language, mark)}</Chip>
        </div>
        {children}
        {actions !== undefined && <div className="ui-actions">{actions}</div>}
      </div>
    </li>
  );
}

// The timeline is read oldest first; a long one has more pages.
const MAX_TIMELINE_PAGES = 20;

// The Lease's Utility Invoices are read a page at a time.
const MAX_INVOICE_PAGES = 10;

type FinalState =
  | { state: "none" | "loading" | "failed" }
  | {
      state: "shown";
      inputs: FinalInputs | null;
      /** The newest final inputs of the Lease, which new ones replace. */
      latest: string | null;
      /** null: none yet; "unknown": the Invoices could not be read. */
      invoice: InvoiceResource | null | "unknown";
    };

type DepositsState =
  | { state: "loading" | "hidden" | "failed" }
  | { state: "shown"; items: DepositResource[] };

function MoveoutDetail({
  language,
  propertyId,
  today,
  leaseApi,
  depositApi,
  unitApi,
  moveOutApi,
  utilityApi,
  utilityLeaseApi,
  invoiceApi,
  capabilities,
  leaseId,
}: MoveoutPageProps & { leaseId: string }) {
  const [lease, setLease] = useState<LeaseResource | null>(null);
  const [timeline, setTimeline] = useState<LeaseTimelineEvent[]>([]);
  const [page, setPage] = useState<MoveOutPage | null>(null);
  const [deposits, setDeposits] = useState<DepositsState>({
    state: "loading",
  });
  const [missing, setMissing] = useState(false);
  const [renewed, setRenewed] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [dialog, setDialog] = useState<"handback" | "final" | null>(null);
  const [final, setFinal] = useState<FinalState>({ state: "none" });
  const [notice, setNotice] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const sequence = useRef(0);
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayDeposits = may("deposits.read");
  const mayInvoices = may("invoices.read");

  const load = useCallback(() => {
    const operation = ++sequence.current;
    const current = () => operation === sequence.current;
    setLoadFailed(false);
    void (async () => {
      const loaded = await leaseApi.get(leaseId);
      if (!current()) return;
      if (loaded.property_id !== propertyId) {
        setMissing(true);
        return;
      }
      const events = [...loaded.timeline];
      let cursor = loaded.timeline_next_cursor;
      for (
        let count = 0;
        cursor !== null && count < MAX_TIMELINE_PAGES;
        count += 1
      ) {
        const next = await leaseApi.timeline(leaseId, cursor);
        events.push(...next.items);
        cursor = next.next_cursor;
      }
      // A signed renewal continues the Occupancies: no hand-back. A successor that cannot be
      // read counts as renewed, so nothing is ended by mistake.
      let continued = false;
      for (const event of events) {
        if (
          event.event_kind !== "lease.renewal_successor" ||
          event.source_reference === null
        )
          continue;
        const successor = await leaseApi
          .get(event.source_reference)
          .catch(() => null);
        if (
          successor === null ||
          successor.status === "SIGNED" ||
          successor.status === "TERMINATED"
        )
          continued = true;
      }
      const records = await moveOutApi.read(propertyId, leaseId);
      if (!current()) return;
      setRenewed(continued);
      setLease(loaded);
      setTimeline(events);
      setPage(records);
      setMissing(false);
      // After the hand-back: the final readings and the final Utility Invoice.
      const handed = records.items.find(
        (item) => item.event_status !== "SUPERSEDED",
      );
      if (handed === undefined || records.open_occupancies.length > 0) {
        setFinal({ state: "none" });
        return;
      }
      setFinal({ state: "loading" });
      const read = await utilityLeaseApi
        .readFinalInputs(propertyId, leaseId)
        .catch(() => undefined);
      if (!current()) return;
      if (read === undefined) {
        setFinal({ state: "failed" });
        return;
      }
      const inputs = currentFinalInputs(read, handed.event_id);
      const latest = latestInputsId(read);
      let invoice: InvoiceResource | null | "unknown" = null;
      if (inputs !== null) {
        invoice = "unknown";
        if (mayInvoices) {
          try {
            const found: InvoiceResource[] = [];
            let cursor: string | undefined;
            for (let count = 0; count < MAX_INVOICE_PAGES; count += 1) {
              const next = await invoiceApi.list(propertyId, {
                lease_id: leaseId,
                category: "UTILITIES",
                ...(cursor === undefined ? {} : { cursor }),
              });
              found.push(...next.items);
              if (next.next_cursor === null) break;
              cursor = next.next_cursor;
            }
            invoice = finalInvoiceOf(found, inputs);
          } catch {
            invoice = "unknown";
          }
        }
      }
      if (current()) setFinal({ state: "shown", inputs, latest, invoice });
    })().catch((error: unknown) => {
      if (!current()) return;
      // No answer is not "not found": keep what is shown and offer Retry.
      if (
        error instanceof LeaseUnavailableError ||
        error instanceof MoveOutUnavailableError
      )
        setLoadFailed(true);
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
  }, [
    leaseApi,
    depositApi,
    moveOutApi,
    utilityLeaseApi,
    invoiceApi,
    leaseId,
    propertyId,
    mayDeposits,
    mayInvoices,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("moveout");
      }}
      type="button"
    >
      <Icon name="back" small />
      {mt(language, "back")}
    </button>
  );
  const failure = loadFailed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{mt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {mt(language, "retry")}
      </button>
    </div>
  );
  if (missing)
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{mt(language, "missing")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {mt(language, "retry")}
          </button>
        </div>
      </>
    );
  if (lease === null || page === null)
    return (
      <>
        {back}
        {failure || (
          <p className="ui-muted" role="status">
            {mt(language, "loading")}
          </p>
        )}
      </>
    );

  // A renewal is not a move-out; the Lease page shows it.
  const step = stepOf(lease, today, renewed);
  const termination = terminationOf(timeline);
  const terminated = lease.status === "TERMINATED";
  const current = page.items.find((item) => item.event_status !== "SUPERSEDED");
  const neverIn = terminated && lease.occupancies.length === 0;
  const open = page.open_occupancies;
  const ended =
    terminated || (lease.end_date !== null && lease.end_date <= today);
  const handedBack = current !== undefined && open.length === 0;
  // A Lease running to its End Date also ends here, which needs leases.terminate too.
  // A terminated Lease names its termination; without it the hand-back cannot be recorded.
  const mayHandBack =
    step !== null &&
    may("leases.move_out") &&
    (terminated ? termination !== null : may("leases.terminate"));
  const names = new Map(
    lease.occupancies.map((occupancy) => [
      occupancy.customer_id,
      occupancy.customer_name,
    ]),
  );

  const mark1: Mark = ended ? "done" : "now";
  const mark2: Mark = handedBack
    ? "done"
    : neverIn
      ? "skip"
      : ended && open.length > 0
        ? "now"
        : "todo";
  const inputs = final.state === "shown" ? final.inputs : null;
  const invoice = final.state === "shown" ? final.invoice : null;
  const issued = inputs !== null && invoice !== null && invoice !== "unknown";
  const mark3: Mark = neverIn
    ? "skip"
    : issued
      ? "done"
      : handedBack
        ? "now"
        : "todo";
  const mayRead =
    may("leases.move_out") &&
    may("utility_readings.record") &&
    may("utility.read");
  const mayIssue = may("invoices.issue") && may("utility.calculate");
  // Readings first; then the Invoice, for a person who may issue it.
  const finalButton =
    current !== undefined &&
    handedBack &&
    final.state === "shown" &&
    !issued &&
    (inputs === null
      ? mayRead
      : mayIssue && invoice !== "unknown" && inputs.unresolved === 0) ? (
      <button
        className="ui-btn primary"
        onClick={() => {
          setNotice(null);
          setWarning(null);
          setDialog("final");
        }}
        type="button"
      >
        <Icon name="meter" />
        {mt(language, inputs === null ? "st3_btn" : "st3_issue_btn")}
      </button>
    ) : undefined;
  const later = <p className="ui-small ui-muted">{mt(language, "later")}</p>;

  const security =
    deposits.state === "shown"
      ? deposits.items.filter((item) => item.deposit_type === "SECURITY")
      : [];
  const pets =
    deposits.state === "shown"
      ? deposits.items.filter((item) => item.deposit_type === "PET")
      : [];
  const history: { id: string; at: string; text: string; note: string }[] = [
    ...timeline.map((event) => ({
      id: event.event_id,
      at: event.occurred_at,
      text:
        event.event_kind === "lease.terminate"
          ? mt(language, "st1_term", dayText(lease.actual_termination_date))
          : event.event_kind.replace(/^lease\./, "").replace(/_/g, " "),
      note: event.reason,
    })),
    ...(inputs === null
      ? []
      : [
          {
            id: inputs.event_id,
            at: inputs.occurred_at,
            text: mt(language, "mh_readings"),
            note: "",
          },
        ]),
    ...(invoice === null || invoice === "unknown"
      ? []
      : [
          {
            id: invoice.id,
            at: `${invoice.invoice_date}T23:59:59Z`,
            text: mt(language, "mh_final", invoice.invoice_number),
            note: "",
          },
        ]),
    ...page.items.map((item: MoveOutRecord) => ({
      id: item.event_id,
      at: item.occurred_at,
      text: mt(
        language,
        item.supersedes_event_id === null ? "mh_hb" : "mh_hb_fixed",
        dayText(item.actual_move_out_date),
        conditionText(language, item.resulting_unit_status),
      ),
      note: item.reason,
    })),
  ].sort((left, right) => right.at.localeCompare(left.at));

  return (
    <>
      {back}
      {failure}
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {warning !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{warning}</p>
        </div>
      )}
      {step === null && (
        <div className="ui-notice" role="status">
          <Icon name="info" />
          <p>{mt(language, renewed ? "renewed_note" : "not_yet_note")}</p>
        </div>
      )}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">
              {mt(language, "moveout_of", lease.unit_number)}
            </h2>
            {step !== null && <MoveOutChip language={language} step={step} />}
          </div>
          <p>
            {lease.primary_tenant_name} ·{" "}
            <span className="ui-num">
              {dayText(lease.start_date)} – {dayText(lease.end_date)}
            </span>
          </p>
        </div>
        <div className="ui-actions">
          <a className="ui-btn" href={hashForPage("leases", lease.lease_id)}>
            <Icon name="lease" />
            {mt(language, "open_lease")}
          </a>
          <a className="ui-btn" href={hashForPage("units", lease.unit_id)}>
            <Icon name="units" />
            {mt(language, "open_unit")}
          </a>
        </div>
      </div>
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="mo-steps" className="ui-card">
            <h2 id="mo-steps">{mt(language, "steps_t")}</h2>
            <ol className="ui-msteps">
              <Step
                language={language}
                mark={mark1}
                number={1}
                title={mt(language, "st1_t")}
              >
                {terminated ? (
                  <>
                    <p>
                      {mt(
                        language,
                        "st1_term",
                        dayText(lease.actual_termination_date),
                      )}
                    </p>
                    {termination !== null &&
                      termination.reason.trim() !== "" && (
                        <p className="ui-small">
                          {mt(language, "st1_reason", termination.reason)}
                        </p>
                      )}
                  </>
                ) : (
                  <p>{mt(language, "st1_normal", dayText(lease.end_date))}</p>
                )}
              </Step>
              <Step
                actions={
                  mark2 === "now" && mayHandBack ? (
                    <button
                      className="ui-btn primary"
                      onClick={() => {
                        setNotice(null);
                        setWarning(null);
                        setDialog("handback");
                      }}
                      type="button"
                    >
                      <Icon name="door" />
                      {mt(language, "st2_btn")}
                    </button>
                  ) : undefined
                }
                language={language}
                mark={mark2}
                number={2}
                title={mt(language, "st2_t")}
              >
                {current !== undefined && handedBack ? (
                  <>
                    <p>
                      {mt(
                        language,
                        "st2_done",
                        dayText(current.actual_move_out_date),
                        conditionText(language, current.resulting_unit_status),
                      )}
                    </p>
                    <p className="ui-small">{current.evidence_reference}</p>
                    <p className="ui-small">
                      {rentRuleText(language, current.actual_move_out_date)}
                    </p>
                  </>
                ) : neverIn ? (
                  <p>{mt(language, "st2_skip")}</p>
                ) : !ended && lease.end_date !== null ? (
                  <p>{mt(language, "st2_wait", dayText(lease.end_date))}</p>
                ) : (
                  <>
                    <p>{mt(language, "st2_todo")}</p>
                    {!mayHandBack && step !== null && (
                      <p className="ui-small ui-muted">
                        {mt(
                          language,
                          !terminated
                            ? "st2_manager"
                            : termination === null
                              ? "st2_no_term"
                              : "st2_not_allowed",
                        )}
                      </p>
                    )}
                  </>
                )}
              </Step>
              <Step
                actions={finalButton}
                language={language}
                mark={mark3}
                number={3}
                title={mt(language, "st3_t")}
              >
                {neverIn || !handedBack ? (
                  <p>{mt(language, neverIn ? "st2_skip" : "st3_wait")}</p>
                ) : final.state === "failed" ? (
                  <p className="ui-muted">{mt(language, "failed")}</p>
                ) : final.state !== "shown" ? (
                  <p className="ui-muted" role="status">
                    {mt(language, "st3_reading_step")}
                  </p>
                ) : inputs === null ? (
                  <>
                    <p>{mt(language, "st3_todo")}</p>
                    {!mayRead && (
                      <p className="ui-small ui-muted">
                        {mt(language, "st3_not_allowed")}
                      </p>
                    )}
                  </>
                ) : invoice !== null && invoice !== "unknown" ? (
                  <p>
                    {mt(
                      language,
                      "st3_done",
                      dayText(inputs.actual_move_out_date),
                      invoice.invoice_number,
                      usdFromCents(Number(invoice.adjusted_total.minor_units)),
                    )}{" "}
                    <a href={hashForPage("invoices", `inv:${invoice.id}`)}>
                      {mt(language, "open_invoice")}
                    </a>
                  </p>
                ) : (
                  <>
                    <p>
                      {mt(
                        language,
                        "st3_inputs",
                        dayText(inputs.actual_move_out_date),
                      )}
                    </p>
                    {invoice === "unknown" && (
                      <p className="ui-small ui-muted">
                        {mt(language, "st3_no_invoices")}
                      </p>
                    )}
                    {inputs.unresolved > 0 && (
                      <p className="ui-small ui-muted">
                        {mt(language, "st3_unresolved")}
                      </p>
                    )}
                    {!mayIssue && (
                      <p className="ui-small ui-muted">
                        {mt(language, "st3_no_issue")}
                      </p>
                    )}
                  </>
                )}
              </Step>
              <Step
                language={language}
                mark={neverIn ? "skip" : "todo"}
                number={4}
                title={mt(language, "st4_t")}
              >
                <p>{mt(language, neverIn ? "st2_skip" : "st4_todo")}</p>
              </Step>
              <Step
                language={language}
                mark={neverIn ? "now" : "todo"}
                number={5}
                title={mt(language, "st5_t")}
              >
                <p>{mt(language, neverIn ? "st5_todo" : "st5_wait")}</p>
                {neverIn && later}
              </Step>
              <Step
                language={language}
                mark="todo"
                number={6}
                title={mt(language, "st6_t")}
              >
                <p className="ui-small ui-muted">{mt(language, "st6_note")}</p>
              </Step>
            </ol>
          </section>
        </div>
        <div className="ui-stack">
          <section aria-labelledby="mo-deps" className="ui-card">
            <h2 id="mo-deps">{mt(language, "deps_t")}</h2>
            {deposits.state === "hidden" ? (
              <p className="ui-muted">{mt(language, "dep_hidden")}</p>
            ) : deposits.state === "failed" ? (
              <p className="ui-muted">{mt(language, "dep_failed")}</p>
            ) : deposits.state === "loading" ? (
              <p className="ui-muted">…</p>
            ) : (
              <>
                <Kv
                  rows={[...security, ...pets].map((deposit) => [
                    mt(language, `dep_${deposit.deposit_type}`),
                    <span className="ui-num">
                      {mt(
                        language,
                        "dep_held",
                        usdFromCents(deposit.held_refundable_usd_cents),
                      )}
                      <span className="ui-sub2">
                        {mt(
                          language,
                          "dep_received",
                          usdFromCents(deposit.received_usd_cents),
                        )}
                      </span>
                    </span>,
                  ])}
                />
                {pets.length === 0 && (
                  <p className="ui-small ui-muted">
                    {mt(language, "dep_none")}
                  </p>
                )}
              </>
            )}
          </section>
          <section aria-labelledby="mo-history" className="ui-card">
            <h2 id="mo-history">{mt(language, "history_t")}</h2>
            {history.length === 0 ? (
              <p className="ui-muted">{mt(language, "h_none")}</p>
            ) : (
              <ol className="ui-timeline">
                {history.map((item) => (
                  <li key={item.id}>
                    <div>
                      {item.text}
                      {item.note.trim() !== "" && (
                        <span className="ui-sub2">{item.note}</span>
                      )}
                      <small className="ui-num">{momentText(item.at)}</small>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
      {dialog === "final" && current !== undefined && (
        <FinalReadingsDialog
          day={current.actual_move_out_date}
          inputsEventId={inputs?.event_id ?? null}
          supersedesEventId={
            inputs === null && final.state === "shown" ? final.latest : null
          }
          language={language}
          lease={lease}
          mayIssue={mayIssue}
          moveOutEventId={current.event_id}
          onClose={() => {
            setDialog(null);
            // Readings may have been saved before the answer was lost: show them.
            load();
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(mt(language, "conflict"));
            load();
          }}
          onSaved={(created: EvidenceRecord | null) => {
            setDialog(null);
            const issuedInvoice =
              created !== null &&
              typeof created.invoice === "object" &&
              created.invoice !== null
                ? (created.invoice as EvidenceRecord)
                : null;
            setNotice(
              created === null
                ? mt(language, "st3_toast_only")
                : mt(
                    language,
                    "st3_toast",
                    typeof issuedInvoice?.invoice_number === "string"
                      ? issuedInvoice.invoice_number
                      : "",
                  ),
            );
            load();
          }}
          utilityApi={utilityApi}
          utilityLeaseApi={utilityLeaseApi}
        />
      )}
      {dialog === "handback" && (
        <HandBackDialog
          language={language}
          lease={lease}
          leaseApi={leaseApi}
          moveOutApi={moveOutApi}
          names={names}
          onClose={() => {
            setDialog(null);
            // A first step may have been saved (the Lease ended): show it.
            load();
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(mt(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setNotice(
              mt(
                language,
                "st2_toast",
                lease.unit_number,
                conditionText(language, saved.resulting_unit_status),
              ),
            );
            load();
          }}
          open={open}
          terminationEventId={
            terminated ? (termination?.event_id ?? null) : null
          }
          today={today}
          unitApi={unitApi}
        />
      )}
    </>
  );
}
