import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { captureFinancialScope, type FinancialScope } from "./financialClient";
import {
  captureFinancialRequest,
  commandBody,
  financialId,
  financialObject,
  invalidFinancial,
  isEnforcementCommand,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  decodeFinancialIntent,
  type FinancialRecoveryState,
  type PendingFinancialCommand,
} from "./financialRecovery";
import {
  validateFinancialReply,
  type FinancialReply,
} from "./financialResponse";
import {
  confirmedFinancialRequest,
  financialMoney,
  financialUiError,
  prepareFinancialCommand,
  type FinancialCommandRequest,
  type PreparedFinancialCommand,
} from "./financialUi";
import { useFinancialTask } from "./financialUiContext";
import { FinancialConfirmation } from "./FinancialConfirmation";
import { FinancialFacts } from "./FinancialEvidence";
import {
  FINANCIAL_ACTION_LABELS,
  FinancialRecoveryNotice,
} from "./FinancialRecoveryNotice";
import { readEnforcement } from "./leaseEnforcementClient";
import {
  enforcementGrants,
  enforcementRows,
  enforcementValue,
  type EnforcementCapabilities,
} from "./leaseEnforcementContract";
import {
  defaultEnforcementServices,
  enforcementAllowed,
  useEnforcementRead,
  type EnforcementServices,
} from "./leaseEnforcementUi";
import {
  EnforcementFacts,
  EnforcementReadStatus,
} from "./LeaseEnforcementEvidence";
import { LeaseWarningWorkspace } from "./LeaseWarningWorkspace";
import { RentNonpaymentWorkspace } from "./RentNonpaymentWorkspace";

export interface LeaseEnforcementManagementProps {
  actorId: string;
  services?: EnforcementServices;
  onDirtyStateChange?: (dirty: boolean) => void;
}
export function LeaseEnforcementManagement({
  actorId,
  services = defaultEnforcementServices,
  onDirtyStateChange,
}: LeaseEnforcementManagementProps) {
  return (
    <EnforcementActor
      key={actorId}
      actorId={actorId}
      services={services}
      onDirtyStateChange={onDirtyStateChange}
    />
  );
}
function EnforcementActor({
  actorId,
  services,
  onDirtyStateChange,
}: LeaseEnforcementManagementProps & { services: EnforcementServices }) {
  const id = useId(),
    [properties, setProperties] = useState<FinancialObject[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [page, setPage] = useState<string | undefined>(),
    [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const dirty = useRef(false),
    notify = useRef(onDirtyStateChange),
    active = useRef<AbortController | null>(null),
    mounted = useRef(false),
    sequence = useRef(0);
  useLayoutEffect(() => {
    notify.current = onDirtyStateChange;
    onDirtyStateChange?.(dirty.current);
  }, [onDirtyStateChange]);
  const reportDirty = useCallback((value: boolean) => {
    dirty.current = value;
    notify.current?.(value);
  }, []);
  const confirmDiscard = useCallback(
    () =>
      !dirty.current ||
      window.confirm(
        "Discard unsaved Lease warning or nonpayment form values?",
      ),
    [],
  );
  useLayoutEffect(() => {
    mounted.current = true;
    const unload = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault();
      }
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      mounted.current = false;
      sequence.current++;
      active.current?.abort();
      window.removeEventListener("beforeunload", unload);
      notify.current?.(false);
    };
  }, []);
  const load = useCallback(
    (after?: string) => {
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      const ticket = ++sequence.current;
      setProperties([]);
      setSelected("");
      setCursor(null);
      setPage(after);
      setBusy(true);
      setError(null);
      void readEnforcement(
        { actorId, propertyId: null, signal: controller.signal },
        { kind: "workspaces", limit: 50, ...(after ? { cursor: after } : {}) },
        services.reads,
      )
        .then((data) => {
          if (
            mounted.current &&
            ticket === sequence.current &&
            !controller.signal.aborted
          ) {
            setProperties(enforcementRows(data));
            setCursor(
              data.next_cursor === null ? null : financialId(data.next_cursor),
            );
          }
        })
        .catch((failure: unknown) => {
          if (
            mounted.current &&
            ticket === sequence.current &&
            !controller.signal.aborted
          )
            setError(financialUiError(failure));
        })
        .finally(() => {
          if (
            mounted.current &&
            ticket === sequence.current &&
            !controller.signal.aborted
          )
            setBusy(false);
        });
    },
    [actorId, services],
  );
  useEffect(() => {
    load();
    return () => {
      active.current?.abort();
    };
  }, [load]);
  const property = properties.find((row) => row.property_id === selected);
  return (
    <section
      id="lease-enforcement-management"
      className="panel financial-management"
      aria-labelledby={`${id}-heading`}
    >
      <h2 id={`${id}-heading`}>Lease warnings and Rent nonpayment</h2>
      <p>
        Review general Lease warnings, Rent-only alerts, case histories and
        explicitly authorized actions.
      </p>
      <label htmlFor={`${id}-property`}>Lease enforcement Property</label>
      <select
        id={`${id}-property`}
        value={selected}
        disabled={busy}
        onChange={(e) => {
          if (confirmDiscard()) setSelected(e.target.value);
        }}
      >
        <option value="">Select an authorized Property</option>
        {properties.map((row) => (
          <option
            key={financialId(row.property_id)}
            value={financialId(row.property_id)}
          >
            {enforcementValue(row.name)}
          </option>
        ))}
      </select>
      <EnforcementReadStatus busy={busy} error={error} />
      {!busy && !error && properties.length === 0 && (
        <p>No Lease warning or Rent nonpayment Property access is available.</p>
      )}
      <div className="button-row">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (confirmDiscard()) load();
          }}
        >
          Refresh Lease enforcement access
        </button>
        {page && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (confirmDiscard()) load();
            }}
          >
            First enforcement Property page
          </button>
        )}
        {cursor && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (confirmDiscard()) load(cursor);
            }}
          >
            Next enforcement Property page
          </button>
        )}
      </div>
      {property && (
        <EnforcementProperty
          key={selected}
          actorId={actorId}
          property={property}
          services={services}
          onDirty={reportDirty}
          confirmDiscard={confirmDiscard}
        />
      )}
    </section>
  );
}
function EnforcementProperty({
  actorId,
  property,
  services,
  onDirty,
  confirmDiscard,
}: {
  actorId: string;
  property: FinancialObject;
  services: EnforcementServices;
  onDirty: (value: boolean) => void;
  confirmDiscard: () => boolean;
}) {
  const propertyId = financialId(property.property_id),
    [scope, setScope] = useState<FinancialScope | null>(null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setScope(
      captureFinancialScope({ actorId, propertyId, signal: controller.signal }),
    );
    setGeneration((value) => value + 1);
    return () => {
      controller.abort();
      onDirty(false);
    };
  }, [actorId, propertyId, onDirty]);
  if (
    !scope ||
    scope.signal.aborted ||
    scope.actorId !== actorId ||
    scope.propertyId !== propertyId
  )
    return <p role="status">Opening authorized Lease workspace…</p>;
  return (
    <EnforcementWorkspace
      key={generation}
      scope={scope}
      propertyName={enforcementValue(property.name)}
      capabilities={enforcementGrants(property.capabilities)}
      services={services}
      onDirty={onDirty}
      confirmDiscard={confirmDiscard}
    />
  );
}
type Confirmation =
  | {
      kind: "new";
      prepared: PreparedFinancialCommand;
      source: FinancialObject | null;
      recorded: () => void;
    }
  | { kind: "replay"; command: PendingFinancialCommand };
function EnforcementWorkspace({
  scope,
  propertyName,
  capabilities,
  services,
  onDirty,
  confirmDiscard,
}: {
  scope: FinancialScope;
  propertyName: string;
  capabilities: EnforcementCapabilities;
  services: EnforcementServices;
  onDirty: (value: boolean) => void;
  confirmDiscard: () => boolean;
}) {
  const id = useId(),
    noticeId = `${id}-recovery`;
  const warnings = capabilities["leases.read"] || capabilities["leases.warn"],
    nonpayment =
      capabilities["rent_nonpayment.read"] ||
      capabilities["rent_nonpayment.case_manage"] ||
      capabilities["rent_nonpayment.event_post"];
  const [purpose, setPurpose] = useState<"WARNINGS" | "NONPAYMENT">(
      warnings ? "WARNINGS" : "NONPAYMENT",
    ),
    [lease, setLease] = useState(""),
    [cursor, setCursor] = useState<string | undefined>();
  const [revision, setRevision] = useState(0),
    [recovery, setRecovery] = useState<FinancialRecoveryState | null>(null),
    [confirmation, setConfirmation] = useState<Confirmation | null>(null),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<FinancialReply | null>(null);
  const busyRef = useRef(false),
    mounted = useRef(false);
  const unresolvedDraft = useRef<{ key: string; recorded: () => void } | null>(
    null,
  );
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onDirty(false);
    };
  }, [onDirty]);
  const recoveryTask = useFinancialTask(scope),
    { run: loadRecovery } = recoveryTask;
  const refreshRecovery = useCallback(() => {
    setRecovery(null);
    void loadRecovery((s) => services.recovery.load(s), setRecovery);
  }, [loadRecovery, services]);
  useEffect(() => {
    refreshRecovery();
  }, [refreshRecovery]);
  const leases = useEnforcementRead(
    scope,
    { kind: "leases", purpose, limit: 25, ...(cursor ? { cursor } : {}) },
    revision,
    services,
  );
  const leaseRows = enforcementRows(leases.data);
  const alive = () => mounted.current && !scope.signal.aborted;
  function review(
    request: FinancialCommandRequest,
    source: FinancialObject | null,
    recorded: () => void,
  ) {
    if (
      !alive() ||
      busyRef.current ||
      recovery?.kind !== "ready" ||
      !isEnforcementCommand(request.operation) ||
      !enforcementAllowed(capabilities, request.operation)
    )
      return;
    const prepared = prepareFinancialCommand(scope, request);
    const snapshot =
      source === null
        ? null
        : financialObject(parseFinancialJson(stringifyFinancialJson(source)));
    setConfirmation({ kind: "new", prepared, source: snapshot, recorded });
  }
  function reviewPending() {
    if (!alive() || busyRef.current || recovery?.kind !== "pending") return;
    try {
      const command = decodeFinancialIntent(
        {
          plaintext: stringifyFinancialJson(recovery.command),
          requestKey: recovery.command.key,
        },
        scope.actorId,
      );
      if (
        !command ||
        command.propertyId !== scope.propertyId ||
        !isEnforcementCommand(command.operation)
      )
        invalidFinancial();
      setConfirmation({ kind: "replay", command });
    } catch (failure) {
      setNotice(financialUiError(failure));
    }
  }
  async function confirm() {
    if (!confirmation || busyRef.current || !alive()) return;
    const original = confirmation;
    const request =
      original.kind === "new"
        ? confirmedFinancialRequest(scope, original.prepared)
        : ({
            operation: original.command.operation,
            target: original.command.target,
            body: commandBody(
              original.command.operation,
              original.command.wireBody,
            ),
          } as FinancialCommandRequest);
    if (
      !isEnforcementCommand(request.operation) ||
      !enforcementAllowed(capabilities, request.operation)
    ) {
      setConfirmation(null);
      setNotice(
        "Current access does not allow this action. Refresh Lease enforcement access.",
      );
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const result =
        original.kind === "new"
          ? await services.recovery.submit(scope, request)
          : await services.recovery.replay(scope, original.command.key);
      if (!alive()) return;
      if (original.kind === "new") {
        const sent = captureFinancialRequest(request);
        const saved =
          result.kind === "pending"
            ? result.command
            : result.kind === "blocked" && result.state.kind === "pending"
              ? result.state.command
              : null;
        if (
          saved?.actorId === scope.actorId &&
          saved.propertyId === scope.propertyId &&
          saved.operation === request.operation &&
          saved.target.id === sent.target.id &&
          saved.wireBody === sent.wireBody
        )
          unresolvedDraft.current = {
            key: saved.key,
            recorded: original.recorded,
          };
      }
      if (result.kind === "success") {
        const reply = validateFinancialReply(
          {
            data: result.reply.data,
            meta: {
              request_id: result.reply.requestId,
              property_id: result.reply.propertyId,
            },
          },
          captureFinancialRequest(request),
          scope.propertyId,
          original.kind === "replay"
            ? original.command.key
            : financialId(result.reply.requestId),
          scope.actorId,
        );
        setOutcome(reply);
        if (original.kind === "new") original.recorded();
        else if (unresolvedDraft.current?.key === original.command.key)
          unresolvedDraft.current.recorded();
        unresolvedDraft.current = null;
        setNotice(
          "The original action is confirmed as recorded. Its original evidence is shown below; current records are being refreshed.",
        );
      } else if (result.kind === "pending")
        setNotice(
          "This action has an unresolved outcome. Its exact original details are saved. Review the saved action before retrying; new actions remain blocked.",
        );
      else if (result.kind === "rejected")
        setNotice(
          `The new action was rejected before recording. ${financialUiError(result.error)}`,
        );
      else if (result.kind === "blocked")
        setNotice(
          "A saved action or unavailable recovery storage blocks this action. Review recovery before continuing.",
        );
    } catch (failure) {
      if (alive()) setNotice(financialUiError(failure));
    } finally {
      if (alive()) {
        setConfirmation(null);
        setRecovery(null);
        try {
          const state = await services.recovery.load(scope);
          if (alive()) setRecovery(state);
        } catch {
          if (alive()) setRecovery({ kind: "unavailable" });
        }
        if (alive()) {
          busyRef.current = false;
          setBusy(false);
          setRevision((value) => value + 1);
        }
      }
    }
  }
  const pending = confirmation?.kind === "replay" ? confirmation.command : null;
  const operation =
    confirmation?.kind === "new"
      ? confirmation.prepared.request.operation
      : pending?.operation;
  const body =
    confirmation?.kind === "new"
      ? confirmation.prepared.request.body
      : pending
        ? commandBody(pending.operation, pending.wireBody)
        : null;
  const target =
    confirmation?.kind === "new"
      ? confirmation.prepared.request.target
      : pending?.target;
  const confirmedCase =
    outcome === null
      ? null
      : (financialObject(outcome.data).rent_nonpayment_case_id ??
        (financialObject(outcome.data).assessment === undefined
          ? null
          : financialObject(outcome.data).id));
  const foreignPending =
    recovery?.kind === "pending" &&
    !isEnforcementCommand(recovery.command.operation);
  return (
    <section aria-label={`Lease enforcement Property ${propertyName}`}>
      <h3>{propertyName}</h3>
      <FinancialRecoveryNotice
        id={noticeId}
        state={recovery}
        busy={busy}
        onReviewPending={reviewPending}
        pendingLink={
          foreignPending
            ? {
                href: "#financial-management-heading",
                label: "Review this saved action in Financial records",
              }
            : undefined
        }
      />
      <EnforcementReadStatus {...recoveryTask} />
      <button
        type="button"
        disabled={busy || recoveryTask.busy}
        onClick={() => {
          setConfirmation(null);
          refreshRecovery();
          setRevision((value) => value + 1);
        }}
      >
        Refresh enforcement records and recovery
      </button>
      {notice && <p role="status">{notice}</p>}
      {outcome && (
        <section
          className="information-card"
          aria-label="Original confirmed enforcement action"
        >
          <h4>Original confirmed action</h4>
          <p>Request reference: {outcome.requestId}</p>
          <EnforcementFacts value={financialObject(outcome.data)} />
          {confirmedCase !== null &&
            (capabilities["rent_nonpayment.read"] ||
              capabilities["rent_nonpayment.event_post"]) && (
              <CurrentConfirmedCase
                key={`${outcome.requestId}:${String(revision)}`}
                scope={scope}
                services={services}
                capabilities={capabilities}
                caseId={financialId(confirmedCase)}
                revision={revision}
              />
            )}
        </section>
      )}
      <label htmlFor={`${id}-purpose`}>Lease workflow</label>
      <select
        id={`${id}-purpose`}
        value={purpose}
        disabled={busy}
        onChange={(e) => {
          if (confirmDiscard()) {
            setPurpose(e.target.value as "WARNINGS" | "NONPAYMENT");
            setLease("");
            setCursor(undefined);
            setConfirmation(null);
          }
        }}
      >
        {warnings && <option value="WARNINGS">General Lease warnings</option>}
        {nonpayment && <option value="NONPAYMENT">Rent nonpayment</option>}
      </select>
      {purpose === "NONPAYMENT" && capabilities["rent_nonpayment.read"] && (
        <RentAlerts
          scope={scope}
          services={services}
          revision={revision}
          busy={busy}
          onSelect={(leaseId) => {
            if (confirmDiscard()) {
              setLease(leaseId);
              setConfirmation(null);
            }
          }}
        />
      )}
      {purpose === "NONPAYMENT" && capabilities["rent_nonpayment.read"] && (
        <InitialRentAlerts
          scope={scope}
          services={services}
          revision={revision}
          busy={busy}
          onSelect={(leaseId) => {
            if (confirmDiscard()) {
              setLease(leaseId);
              setConfirmation(null);
            }
          }}
        />
      )}
      <EnforcementReadStatus {...leases} />
      <label htmlFor={`${id}-lease`}>
        Lease for{" "}
        {purpose === "WARNINGS" ? "general warnings" : "Rent nonpayment"}
      </label>
      <select
        id={`${id}-lease`}
        value={lease}
        disabled={busy || leases.busy}
        onChange={(e) => {
          if (confirmDiscard()) {
            setLease(e.target.value);
            setConfirmation(null);
          }
        }}
      >
        <option value="">Select an authorized Lease</option>
        {lease && !leaseRows.some((row) => row.id === lease) && (
          <option value={lease}>Lease {lease} selected from Rent alert</option>
        )}
        {leaseRows.map((row) => (
          <option key={financialId(row.id)} value={financialId(row.id)}>
            Parking {enforcementValue(row.unit_number)} ·{" "}
            {enforcementValue(row.start_date)} to{" "}
            {enforcementValue(row.end_date)} · {enforcementValue(row.status)}
          </option>
        ))}
      </select>
      {leases.data && (
        <div className="button-row">
          <button
            type="button"
            disabled={busy || leases.busy || cursor === undefined}
            onClick={() => {
              if (confirmDiscard()) {
                setLease("");
                setCursor(undefined);
              }
            }}
          >
            First Lease page
          </button>
          <button
            type="button"
            disabled={busy || leases.busy || leases.data.next_cursor === null}
            onClick={() => {
              if (confirmDiscard()) {
                setLease("");
                setCursor(financialId(leases.data?.next_cursor));
              }
            }}
          >
            Next Lease page
          </button>
        </div>
      )}
      {lease &&
        (purpose === "WARNINGS" ? (
          <LeaseWarningWorkspace
            key={`${lease}:${purpose}`}
            scope={scope}
            capabilities={capabilities}
            services={services}
            leaseId={lease}
            revision={revision}
            ready={recovery?.kind === "ready"}
            busy={busy}
            review={review}
            onDirty={onDirty}
            confirmDiscard={confirmDiscard}
          />
        ) : (
          <RentNonpaymentWorkspace
            key={`${lease}:${purpose}`}
            scope={scope}
            capabilities={capabilities}
            services={services}
            leaseId={lease}
            revision={revision}
            ready={recovery?.kind === "ready"}
            busy={busy}
            review={review}
            onDirty={onDirty}
            confirmDiscard={confirmDiscard}
          />
        ))}
      {confirmation && operation && body && target && (
        <FinancialConfirmation
          title={
            pending
              ? "Review original unresolved enforcement action"
              : `Confirm: ${FINANCIAL_ACTION_LABELS[operation]}`
          }
          consequence={
            pending
              ? "Send only this saved original action again with its original request reference. A changed balance or eligibility does not replace its original intent."
              : "Record this explicit action and its audit evidence. Review the Property, Lease or case, and source references before confirming."
          }
          actionLabel={
            pending
              ? "Send original enforcement action again"
              : FINANCIAL_ACTION_LABELS[operation]
          }
          noticeId={noticeId}
          busy={busy}
          confirmDisabled={
            !isEnforcementCommand(operation) ||
            !enforcementAllowed(capabilities, operation)
          }
          onCancel={() => {
            if (!busyRef.current) setConfirmation(null);
          }}
          onConfirm={() => {
            void confirm();
          }}
        >
          <FinancialFacts
            rows={[
              ["Action", FINANCIAL_ACTION_LABELS[operation]],
              ["Property", propertyName],
              ["Property reference", scope.propertyId],
              ["Acting account reference", scope.actorId],
              [
                operation === "rentNonpaymentEvent"
                  ? "Case reference"
                  : "Lease reference",
                financialId(financialObject(target).id),
              ],
              ...(pending
                ? [["Original request reference", pending.key] as const]
                : []),
            ]}
          />
          <EnforcementFacts value={body} />
          {confirmation.kind === "new" && confirmation.source && (
            <EnforcementFacts value={confirmation.source} current />
          )}
          {isEnforcementCommand(operation) &&
            !enforcementAllowed(capabilities, operation) && (
              <p>
                Current access does not allow sending this original action.
                Refresh access after an authorized access change.
              </p>
            )}
        </FinancialConfirmation>
      )}
    </section>
  );
}
function CurrentConfirmedCase({
  scope,
  services,
  capabilities,
  caseId,
  revision,
}: {
  scope: FinancialScope;
  services: EnforcementServices;
  capabilities: EnforcementCapabilities;
  caseId: string;
  revision: number;
}) {
  const read = useEnforcementRead(
    scope,
    {
      kind: capabilities["rent_nonpayment.read"] ? "case" : "eventContext",
      caseId,
    },
    revision,
    services,
  );
  return (
    <section aria-label="Current case after confirmation">
      <h5>Current case after confirmation</h5>
      <EnforcementReadStatus {...read} />
      {read.data && <EnforcementFacts value={read.data} current />}
    </section>
  );
}
function RentAlerts({
  scope,
  services,
  revision,
  busy,
  onSelect,
}: {
  scope: FinancialScope;
  services: EnforcementServices;
  revision: number;
  busy: boolean;
  onSelect: (leaseId: string) => void;
}) {
  const [cursor, setCursor] = useState<string | undefined>();
  const read = useEnforcementRead(
    scope,
    { kind: "alerts", limit: 25, ...(cursor ? { cursor } : {}) },
    revision,
    services,
  );
  return (
    <section aria-label="Current Rent nonpayment alerts">
      <h4>Current Rent alerts</h4>
      <p>
        Issued Rent lines with a positive balance at least 20 calendar days
        overdue. Viewing these alerts does not open cases or record Notices.
      </p>
      <EnforcementReadStatus {...read} />
      {read.data && (
        <>
          {enforcementRows(read.data).length === 0 && (
            <p>No applicable Rent alerts on this page.</p>
          )}
          {enforcementRows(read.data).map((row) => (
            <article
              className="information-card"
              key={financialId(row.rent_invoice_line_id)}
            >
              <EnforcementFacts value={row} current />
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  onSelect(financialId(row.lease_id));
                }}
              >
                Review this Lease
              </button>
            </article>
          ))}
          <button
            type="button"
            disabled={busy || read.busy || cursor === undefined}
            onClick={() => {
              setCursor(undefined);
            }}
          >
            First Rent alert page
          </button>
          <button
            type="button"
            disabled={busy || read.busy || read.data.next_cursor === null}
            onClick={() => {
              setCursor(financialId(read.data?.next_cursor));
            }}
          >
            Next Rent alert page
          </button>
        </>
      )}
    </section>
  );
}
function InitialRentAlerts({
  scope,
  services,
  revision,
  busy,
  onSelect,
}: {
  scope: FinancialScope;
  services: EnforcementServices;
  revision: number;
  busy: boolean;
  onSelect: (leaseId: string) => void;
}) {
  const [cursor, setCursor] = useState<string | undefined>();
  const read = useEnforcementRead(
    scope,
    { kind: "initialRentAlerts", limit: 25, ...(cursor ? { cursor } : {}) },
    revision,
    services,
  );
  return (
    <section aria-label="Unpaid Initial Rent alerts">
      <h4>Unpaid Initial Rent alerts</h4>
      <p>
        Issued Initial Rent Invoices with an unpaid balance, listed from the day
        after their Due Date. This is a management alert only. It does not open
        a case, record a Notice, add a late fee or end the Lease.
      </p>
      <EnforcementReadStatus {...read} />
      {read.data && (
        <>
          {enforcementRows(read.data).length === 0 && (
            <p>No unpaid Initial Rent alerts on this page.</p>
          )}
          {enforcementRows(read.data).map((row) => {
            const remaining = row.remaining as { minor_units: unknown };
            return (
              <article
                className="information-card"
                key={financialId(row.invoice_id)}
              >
                <FinancialFacts
                  rows={[
                    ["Invoice number", enforcementValue(row.invoice_number)],
                    ["Invoice status", enforcementValue(row.invoice_status)],
                    ["Initial Rent Due Date", enforcementValue(row.due_date)],
                    ["Alert from", enforcementValue(row.alert_date)],
                    ["Unpaid balance", financialMoney(remaining.minor_units)],
                    ["Lease reference", enforcementValue(row.lease_id)],
                    ["Customer reference", enforcementValue(row.customer_id)],
                  ]}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    onSelect(financialId(row.lease_id));
                  }}
                >
                  Review this Lease
                </button>
              </article>
            );
          })}
          <button
            type="button"
            disabled={busy || read.busy || cursor === undefined}
            onClick={() => {
              setCursor(undefined);
            }}
          >
            First Initial Rent alert page
          </button>
          <button
            type="button"
            disabled={busy || read.busy || read.data.next_cursor === null}
            onClick={() => {
              setCursor(financialId(read.data?.next_cursor));
            }}
          >
            Next Initial Rent alert page
          </button>
        </>
      )}
    </section>
  );
}
