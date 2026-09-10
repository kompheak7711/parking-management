import {
  useCallback,
  useId,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  captureFinancialScope,
  financialTransport,
  type FinancialScope,
} from "./financialClient";
import {
  commandBody,
  isEnforcementCommand,
  financialId,
  financialObject,
  type FinancialCommandOperation,
  type FinancialObject,
} from "./financialContracts";
import {
  FINANCIAL_CAPABILITIES,
  financialReferenceClient,
  type FinancialCapabilities,
} from "./financialReferenceClient";
import {
  financialRecovery,
  type FinancialRecoveryState,
  type PendingFinancialCommand,
} from "./financialRecovery";
import type { FinancialReply } from "./financialResponse";
import { stringifyFinancialJson } from "./financialJson";
import { FinancialConfirmation } from "./FinancialConfirmation";
import {
  FINANCIAL_ACTION_LABELS,
  FinancialRecoveryNotice,
} from "./FinancialRecoveryNotice";
import {
  ActionContextEvidence,
  PaymentEvidence,
  PaymentReversalEvidence,
  ReceiptIdentityEvidence,
  RefundSourceEvidence,
  FinancialCommandEvidence,
  FinancialFacts,
  FinancialOutcomeEvidence,
} from "./FinancialEvidence";
import { FinancialAllocationReceiptWorkspace } from "./FinancialAllocationReceiptWorkspace";
import type { FinancialReceiptHandoff } from "./financialUi";
import { FinancialPaymentWorkspace } from "./FinancialPaymentWorkspace";
import { FinancialCreditWorkspace } from "./FinancialCreditWorkspace";
import { FinancialRefundWorkspace } from "./FinancialRefundWorkspace";
import {
  useFinancialTask,
  loadFinancialActionContext,
  loadPaymentReversalContext,
  readFinancialRecord,
} from "./financialUiContext";
import type { FinancialActionPurpose } from "./financialActionContext";
import {
  financialCommandAllowed,
  FinancialInputError,
  confirmedFinancialRequest,
  financialLabel,
  financialUiError,
  prepareFinancialCommand,
  type FinancialCommandReview,
  type FinancialUiServices,
  type FinancialWorkspaceProps,
  type PreparedFinancialCommand,
} from "./financialUi";

export const defaultFinancialUiServices: FinancialUiServices = {
  references: financialReferenceClient,
  transport: financialTransport,
  recovery: financialRecovery,
};
export interface FinancialManagementProps {
  actorId: string;
  services?: FinancialUiServices;
  onDirtyStateChange?: (dirty: boolean) => void;
}
type Confirmation =
  | {
      kind: "new";
      prepared: PreparedFinancialCommand;
      review: FinancialCommandReview;
    }
  | { kind: "replay"; command: PendingFinancialCommand };

/** Remount the entire discovery and workspace lifecycle on an authenticated actor change. */
export function FinancialManagement({
  actorId,
  services = defaultFinancialUiServices,
  onDirtyStateChange,
}: FinancialManagementProps) {
  return (
    <FinancialActor
      key={actorId}
      actorId={actorId}
      services={services}
      onDirtyStateChange={onDirtyStateChange}
    />
  );
}
function FinancialActor({
  actorId,
  services,
  onDirtyStateChange,
}: FinancialManagementProps & { services: FinancialUiServices }) {
  const propertySelectId = useId();
  const dirty = useRef(false);
  const notifyDirty = useRef(onDirtyStateChange);
  useLayoutEffect(() => {
    notifyDirty.current = onDirtyStateChange;
    onDirtyStateChange?.(dirty.current);
  }, [onDirtyStateChange]);
  const reportDirty = useCallback((value: boolean) => {
    dirty.current = value;
    notifyDirty.current?.(value);
  }, []);
  const confirmDiscard = useCallback(
    () =>
      !dirty.current ||
      window.confirm("Discard unsaved financial form values?"),
    [],
  );
  useLayoutEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      reportDirty(false);
    };
  }, [reportDirty]);
  const [properties, setProperties] = useState<FinancialObject[]>([]);
  const [selected, setSelected] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0),
    active = useRef<AbortController | null>(null),
    propertyRows = useRef<FinancialObject[]>([]);
  const load = useCallback(
    (after?: string) => {
      const ticket = ++generation.current;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      setBusy(true);
      setError(null);
      if (!after) {
        propertyRows.current = [];
        setProperties([]);
        setSelected("");
        setCursor(null);
      }
      void (async () => {
        try {
          const reply = await services.references.read(
            { actorId: financialId(actorId), signal: controller.signal },
            {
              operation: "workspaces",
              limit: 100,
              ...(after ? { cursor: after } : {}),
            },
          );
          if (controller.signal.aborted || generation.current !== ticket)
            return;
          if (!Array.isArray(reply.data) || !reply.page)
            throw new FinancialInputError(
              "Financial Properties are unavailable.",
            );
          const rows = reply.data.map(financialObject);
          const merged = after ? [...propertyRows.current, ...rows] : rows;
          stringifyFinancialJson(merged, 8_388_608);
          propertyRows.current = merged;
          setProperties(merged);
          setCursor(reply.page.nextCursor);
        } catch (failure) {
          if (!controller.signal.aborted && generation.current === ticket)
            setError(financialUiError(failure));
        } finally {
          if (!controller.signal.aborted && generation.current === ticket)
            setBusy(false);
        }
      })();
    },
    [actorId, services.references],
  );
  useEffect(() => {
    load();
    return () => {
      generation.current++;
      active.current?.abort();
    };
  }, [load]);
  const property = properties.find((row) => row.property_id === selected);
  return (
    <section
      className="panel financial-management"
      aria-labelledby="financial-management-heading"
    >
      <h2 id="financial-management-heading">Financial records</h2>
      <p>Payments, Allocations, Receipts, Customer Credit and USD Refunds.</p>
      <label htmlFor={propertySelectId}>Financial Property</label>
      <select
        id={propertySelectId}
        value={selected}
        onChange={(e) => {
          if (e.target.value !== selected && confirmDiscard())
            setSelected(e.target.value);
        }}
      >
        <option value="">Select an authorized Property</option>
        {properties.map((row) => (
          <option
            key={financialLabel(row.property_id)}
            value={financialLabel(row.property_id)}
          >
            {financialLabel(row.name)}
          </option>
        ))}
      </select>
      {busy && <p role="status">Loading authorized financial Properties…</p>}
      {error && <p role="alert">{error}</p>}
      {!busy && !error && properties.length === 0 && (
        <p>No financial Property access is available for this account.</p>
      )}
      <div className="button-row">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (confirmDiscard()) load();
          }}
        >
          Refresh financial Properties
        </button>
        {cursor && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              load(cursor);
            }}
          >
            More financial Properties
          </button>
        )}
      </div>
      {property && (
        <FinancialProperty
          key={selected}
          actorId={actorId}
          property={property}
          services={services}
          onDirtyStateChange={reportDirty}
          confirmDiscard={confirmDiscard}
        />
      )}
    </section>
  );
}
function FinancialProperty({
  actorId,
  property,
  services,
  onDirtyStateChange,
  confirmDiscard,
}: {
  actorId: string;
  property: FinancialObject;
  services: FinancialUiServices;
  onDirtyStateChange: (dirty: boolean) => void;
  confirmDiscard: () => boolean;
}) {
  const propertyId = financialId(property.property_id);
  const [entry, setEntry] = useState<{
    scope: FinancialScope;
    generation: number;
  } | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    const next = captureFinancialScope({
      actorId,
      propertyId,
      signal: controller.signal,
    });
    setEntry({ scope: next, generation: ++generation.current });
    return () => {
      controller.abort();
    };
  }, [actorId, propertyId]);
  const scope = entry?.scope;
  if (
    !scope ||
    scope.signal.aborted ||
    scope.actorId !== actorId ||
    scope.propertyId !== propertyId
  )
    return <p role="status">Opening financial Property…</p>;
  return (
    <FinancialPropertyWorkspace
      key={entry.generation}
      scope={scope}
      propertyName={financialLabel(property.name)}
      services={services}
      onDirtyStateChange={onDirtyStateChange}
      confirmDiscard={confirmDiscard}
    />
  );
}
function FinancialPropertyWorkspace({
  scope,
  propertyName,
  services,
  onDirtyStateChange,
  confirmDiscard,
}: {
  scope: FinancialScope;
  propertyName: string;
  services: FinancialUiServices;
  onDirtyStateChange: (dirty: boolean) => void;
  confirmDiscard: () => boolean;
}) {
  const [capabilities, setCapabilities] =
    useState<FinancialCapabilities | null>(null);
  const [recovery, setRecovery] = useState<FinancialRecoveryState | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false),
    busyRef = useRef(false);
  const [revision, setRevision] = useState(0);
  const [receiptHandoff, setReceiptHandoff] =
    useState<FinancialReceiptHandoff | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<ConfirmedFinancialAction | null>(
    null,
  );
  const mounted = useRef(false);
  const preparationGeneration = useRef(0);
  const dirtyForms = useRef(new Set<string>());
  const pendingDraft = useRef<{ key: string; onRecorded: () => void } | null>(
    null,
  );
  const draftChanges = useMemo(() => {
    const update = (name: string) => (value: boolean) => {
      if (value) dirtyForms.current.add(name);
      else dirtyForms.current.delete(name);
      onDirtyStateChange(dirtyForms.current.size > 0);
    };
    return {
      payment: update("payment"),
      allocation: update("allocation"),
      credit: update("credit"),
      refund: update("refund"),
    };
  }, [onDirtyStateChange]);
  const current = useRef({ capabilities, recovery });
  useLayoutEffect(() => {
    current.current = { capabilities, recovery };
  }, [capabilities, recovery]);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      preparationGeneration.current++;
    };
  }, []);
  const accessTask = useFinancialTask(scope),
    recoveryTask = useFinancialTask(scope);
  const { run: readAccess } = accessTask,
    { run: readRecovery } = recoveryTask;
  const refresh = useCallback(() => {
    if (busyRef.current) return;
    preparationGeneration.current++;
    setConfirmation(null);
    setReceiptHandoff(null);
    setCapabilities(null);
    setRecovery(null);
    setRevision((n) => n + 1);
    void readAccess(async (s) => {
      const reply = await services.references.read(s, {
        operation: "capabilities",
      });
      const grants = financialObject(financialObject(reply.data).capabilities);
      return Object.fromEntries(
        FINANCIAL_CAPABILITIES.map((key) => {
          if (typeof grants[key] !== "boolean")
            throw new FinancialInputError("Financial access is unavailable.");
          return [key, grants[key]];
        }),
      ) as FinancialCapabilities;
    }, setCapabilities);
    void readRecovery(
      async (s) => await services.recovery.load(s),
      setRecovery,
    );
  }, [readAccess, readRecovery, services]);
  useEffect(() => {
    refresh();
  }, [refresh]);
  const invalidate = useCallback(() => {
    preparationGeneration.current++;
    if (!busyRef.current) setConfirmation(null);
  }, []);
  const openReceipt = useCallback(
    (receiptId: string) => {
      if (
        busyRef.current ||
        !mounted.current ||
        scope.signal.aborted ||
        (!current.current.capabilities?.["receipts.read"] &&
          !current.current.capabilities?.["receipts.reprint"])
      )
        return;
      setReceiptHandoff(
        Object.freeze({ scope, receiptId: financialId(receiptId) }),
      );
    },
    [scope],
  );
  const beginReview = useCallback<
    FinancialWorkspaceProps["commands"]["beginReview"]
  >(() => {
    invalidate();
    const generation = preparationGeneration.current;
    const isCurrent = () =>
      mounted.current &&
      !scope.signal.aborted &&
      generation === preparationGeneration.current &&
      !busyRef.current;
    return Object.freeze<
      ReturnType<FinancialWorkspaceProps["commands"]["beginReview"]>
    >({
      isCurrent,
      review: (request, details) => {
        if (!isCurrent()) return;
        if (
          current.current.recovery?.kind !== "ready" ||
          !financialCommandAllowed(
            current.current.capabilities,
            request.operation,
          )
        )
          throw new FinancialInputError(
            "Review the current access and unresolved financial action before continuing.",
          );
        const prepared = prepareFinancialCommand(scope, request);
        // A completed preparation cannot publish a second confirmation.
        preparationGeneration.current++;
        setConfirmation({ kind: "new", prepared, review: details });
      },
    });
  }, [scope, invalidate]);
  const commands = useMemo(
    () => ({
      ready: recovery?.kind === "ready" && !busy,
      busy,
      revision,
      beginReview,
      invalidate,
    }),
    [recovery, busy, revision, beginReview, invalidate],
  );
  const alive = () => mounted.current && !scope.signal.aborted;
  async function confirm() {
    if (busyRef.current || !confirmation || !alive()) return;
    const selected = confirmation;
    preparationGeneration.current++;
    setReceiptHandoff(null);
    const operation =
      selected.kind === "new"
        ? selected.prepared.request.operation
        : selected.command.operation;
    if (!financialCommandAllowed(current.current.capabilities, operation)) {
      setConfirmation(null);
      setNotice(
        "Current access does not allow this financial action. Refresh access before continuing.",
      );
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const result =
        selected.kind === "new"
          ? await services.recovery.submit(
              scope,
              confirmedFinancialRequest(scope, selected.prepared),
            )
          : await services.recovery.replay(scope, selected.command.key);
      if (!alive()) return;
      if (result.kind === "success") {
        if (selected.kind === "new") selected.review.onRecorded?.();
        else if (pendingDraft.current?.key === selected.command.key)
          pendingDraft.current.onRecorded();
        pendingDraft.current = null;
        setConfirmed({
          operation,
          reply: result.reply,
          target:
            selected.kind === "new"
              ? selected.prepared.request.target
              : selected.command.target,
          wireBody:
            selected.kind === "new"
              ? selected.prepared.wireBody
              : selected.command.wireBody,
        });
        setNotice("The financial action is recorded.");
      } else if (result.kind === "rejected") {
        setNotice(
          `The new action was rejected before recording. ${financialUiError(result.error)}${result.error.requestId ? ` Reference: ${result.error.requestId}` : ""}`,
        );
      } else if (result.kind === "pending") {
        if (selected.kind === "new" && selected.review.onRecorded)
          pendingDraft.current = {
            key: result.command.key,
            onRecorded: selected.review.onRecorded,
          };
        setRecovery({ kind: "pending", command: result.command });
        setNotice(
          `The outcome is unresolved. Review the original action before sending it again.${result.error?.requestId ? ` Reference: ${result.error.requestId}` : ""}`,
        );
      } else if (result.kind === "blocked") {
        setRecovery(result.state);
        setNotice(
          "A new financial action could not begin. Review its recovery state.",
        );
      } else
        setNotice(
          "This financial workspace changed. Reopen its current records.",
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
          setRevision((n) => n + 1);
          busyRef.current = false;
          setBusy(false);
        }
      }
    }
  }
  function reviewPending() {
    if (busyRef.current || recovery?.kind !== "pending") return;
    preparationGeneration.current++;
    setConfirmation({ kind: "replay", command: recovery.command });
  }
  const pending = confirmation?.kind === "replay" ? confirmation.command : null;
  const operation =
    confirmation?.kind === "new"
      ? confirmation.prepared.request.operation
      : pending?.operation;
  const request =
    confirmation?.kind === "new"
      ? confirmation.prepared.request
      : pending
        ? {
            operation: pending.operation,
            target: pending.target,
            body: commandBody(pending.operation, pending.wireBody),
          }
        : null;
  const noticeId = `financial-notice-${scope.propertyId}`;
  return (
    <section aria-label={`Financial Property ${propertyName}`}>
      <h3>{propertyName}</h3>
      <p>Asia/Phnom_Penh · USD accounting; KHR incoming evidence only.</p>
      <FinancialRecoveryNotice
        id={noticeId}
        state={recovery}
        busy={busy}
        onReviewPending={reviewPending}
        pendingLink={
          recovery?.kind === "pending" &&
          isEnforcementCommand(recovery.command.operation)
            ? {
                href: "#lease-enforcement-management",
                label:
                  "Review this saved action in Lease warnings and Rent nonpayment",
              }
            : undefined
        }
      />
      <button
        type="button"
        disabled={busy || accessTask.busy || recoveryTask.busy}
        onClick={() => {
          if (confirmDiscard()) refresh();
        }}
      >
        Refresh financial access and recovery
      </button>
      {accessTask.busy && <p role="status">Checking financial permissions…</p>}
      {accessTask.error && <p role="alert">{accessTask.error}</p>}
      {recoveryTask.error && <p role="alert">{recoveryTask.error}</p>}
      {notice && <p role="status">{notice}</p>}
      {confirmed && (
        <FinancialOutcomeEvidence
          operation={confirmed.operation}
          reply={confirmed.reply}
        />
      )}
      {confirmed && capabilities && !busy && (
        <FinancialCurrentAfterConfirmation
          key={confirmed.reply.requestId}
          scope={scope}
          capabilities={capabilities}
          services={services}
          confirmed={confirmed}
        />
      )}
      {capabilities && (
        <>
          <FinancialPaymentWorkspace
            onDirtyStateChange={draftChanges.payment}
            onOpenReceipt={openReceipt}
            scope={scope}
            capabilities={capabilities}
            services={services}
            commands={commands}
          />
          <FinancialAllocationReceiptWorkspace
            onDirtyStateChange={draftChanges.allocation}
            receiptHandoff={receiptHandoff}
            scope={scope}
            capabilities={capabilities}
            services={services}
            commands={commands}
          />
          <FinancialCreditWorkspace
            onDirtyStateChange={draftChanges.credit}
            scope={scope}
            capabilities={capabilities}
            services={services}
            commands={commands}
          />
          <FinancialRefundWorkspace
            onDirtyStateChange={draftChanges.refund}
            scope={scope}
            capabilities={capabilities}
            services={services}
            commands={commands}
          />
        </>
      )}
      {confirmation && request && operation && (
        <FinancialConfirmation
          title={
            pending
              ? "Review original unresolved action"
              : `Confirm: ${FINANCIAL_ACTION_LABELS[operation]}`
          }
          consequence={
            confirmation.kind === "new"
              ? confirmation.review.consequence
              : "Send this original action again using its saved exact details and original request key. Its earlier outcome may already be recorded. New financial actions remain blocked until that outcome is established."
          }
          actionLabel={
            pending
              ? "Send original action again"
              : FINANCIAL_ACTION_LABELS[operation]
          }
          noticeId={noticeId}
          busy={busy}
          confirmDisabled={!financialCommandAllowed(capabilities, operation)}
          onCancel={invalidate}
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
              ...(pending
                ? [["Original request key", pending.key] as const]
                : []),
            ]}
          />
          <FinancialCommandEvidence request={request} />
          {confirmation.kind === "new" && confirmation.review.evidence}
          {!financialCommandAllowed(capabilities, operation) && (
            <p>Current access does not allow sending this original action.</p>
          )}
        </FinancialConfirmation>
      )}
    </section>
  );
}

export interface ConfirmedFinancialAction {
  operation: FinancialCommandOperation;
  reply: FinancialReply;
  target: Readonly<Record<string, string>>;
  wireBody: string;
}
interface CurrentFinancialFacts {
  kind: "payment" | "action" | "refundSource" | "reversal";
  data: FinancialObject;
}
/** Refresh only authorized read facts after a validated success, including original-key replay. */
export function FinancialCurrentAfterConfirmation({
  scope,
  capabilities,
  services,
  confirmed,
}: Pick<FinancialWorkspaceProps, "scope" | "capabilities" | "services"> & {
  confirmed: ConfirmedFinancialAction;
}) {
  const task = useFinancialTask(scope),
    { run, cancel } = task;
  const [facts, setFacts] = useState<CurrentFinancialFacts | null>(null);
  useEffect(() => {
    setFacts(null);
    if (confirmed.reply.propertyId !== scope.propertyId) return;
    void run(async (s): Promise<CurrentFinancialFacts | null> => {
      const { operation, target } = confirmed;
      if (operation === "paymentRecord") {
        if (!capabilities["payments.read"]) return null;
        const id = financialId(
          financialObject(financialObject(confirmed.reply.data).payment).id,
        );
        return {
          kind: "payment",
          data: financialObject(
            (
              await readFinancialRecord(
                s,
                { operation: "paymentGet", target: { id } },
                services.transport,
              )
            ).data,
          ),
        };
      }
      if (!financialCommandAllowed(capabilities, operation)) return null;
      if (operation === "paymentReverse")
        return {
          kind: "reversal",
          data: await loadPaymentReversalContext(
            s,
            financialId(target.id),
            "result",
            services.references,
          ),
        };
      if (operation === "refundCreate") {
        const body = commandBody(operation, confirmed.wireBody),
          sourceType = body.source_type;
        if (
          sourceType !== "PAYMENT" &&
          sourceType !== "CREDIT" &&
          sourceType !== "PET_DEPOSIT"
        )
          throw new FinancialInputError(
            "The confirmed Refund source is unavailable.",
          );
        return {
          kind: "refundSource",
          data: financialObject(
            (
              await readFinancialRecord(
                s,
                {
                  operation: "refundSource",
                  target: { sourceType, id: financialId(body.source_id) },
                  ...(sourceType === "PET_DEPOSIT"
                    ? {
                        query: {
                          pet_refund_review_id: financialId(
                            body.pet_refund_review_id,
                          ),
                        },
                      }
                    : {}),
                },
                services.transport,
              )
            ).data,
          ),
        };
      }
      const purposes: Partial<
        Record<FinancialCommandOperation, FinancialActionPurpose>
      > = {
        allocationPost: "allocation",
        allocationReverse: "allocation_reversal",
        receiptReprint: "receipt_reprint",
        creditRecognize: "credit_recognition",
        creditReverse: "credit_reversal",
        creditApply: "credit_application",
        creditApplicationReverse: "credit_application_reversal",
        refundReturn: "refund_return",
        refundReturnReverse: "refund_correction_reversal",
      };
      const purpose = purposes[operation];
      if (!purpose)
        throw new FinancialInputError(
          "Current related financial facts are unavailable.",
        );
      return {
        kind: "action",
        data: await loadFinancialActionContext(
          s,
          {
            operation: "financialActionContext",
            purpose,
            source_id: financialId(
              operation === "refundReturnReverse"
                ? target.correctionId
                : target.id,
            ),
            ...(operation === "refundReturnReverse"
              ? { refund_id: financialId(target.id) }
              : {}),
          },
          services.references,
        ),
      };
    }, setFacts);
    return cancel;
  }, [confirmed, scope.propertyId, capabilities, services, run, cancel]);
  const printable =
    facts?.kind === "action" &&
    confirmed.operation === "receiptReprint" &&
    capabilities["receipts.reprint"];
  if (!facts && !task.busy && !task.error) return null;
  return (
    <section aria-label="Related facts refreshed after confirmation">
      <h3>Related facts after the recorded action</h3>
      <p>
        The recorded result above remains the confirmed outcome. These
        separately fetched facts can change after later operations.
      </p>
      {task.busy && <p role="status">Refreshing authorized related facts…</p>}
      {task.error && (
        <p role="alert">
          The action is recorded. Current related facts could not be loaded.{" "}
          {task.error}
        </p>
      )}
      {facts &&
        (facts.kind === "payment" ? (
          <PaymentEvidence resource={facts.data} />
        ) : facts.kind === "refundSource" ? (
          <RefundSourceEvidence value={facts.data} />
        ) : facts.kind === "reversal" ? (
          <PaymentReversalEvidence value={facts.data} />
        ) : printable ? (
          <>
            <div
              className="financial-receipt-print"
              aria-label="Confirmed original Receipt copy"
            >
              <ReceiptIdentityEvidence
                value={financialObject(facts.data.context).receipt}
              />
              <PaymentEvidence
                resource={facts.data.payment_resource}
                showPosition={false}
              />
              <p>
                Copy of the original Receipt. Reprint reference:{" "}
                {financialLabel(
                  financialObject(financialObject(confirmed.reply.data).reprint)
                    .id,
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                if (!scope.signal.aborted) window.print();
              }}
            >
              Print original Receipt copy
            </button>
          </>
        ) : (
          <ActionContextEvidence value={facts.data} />
        ))}
    </section>
  );
}
