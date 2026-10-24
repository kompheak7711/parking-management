import {
  FormEvent,
  ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  BillingCommand,
  BillingJournal,
  BillingRun,
  ChargeCorrectionInput,
  DecisionOutcome,
  DueDaysSetting,
  InvoiceApi,
  InvoiceCategory,
  InvoiceClientError,
  InitialRentDueDateOverride,
  InvoiceFilters,
  InvoiceResource,
  InvoiceStatus,
  JsonValue,
  LatePaymentCharge,
  LatePaymentDecision,
  LatePaymentReview,
  OneTimeChargeCategory,
  OneTimeChargeRecord,
  PendingBillingCommand,
  billingJournal,
  billingRunRetry,
  requestMoney,
  executeBilling,
  formatUsd,
  money,
  parseUsd,
  terminalChargeConflict,
} from "./invoiceClient";

import { RunDiagnostics } from "./BillingRunDiagnostics";

export interface InvoiceManagementProps {
  api: InvoiceApi;
  actorId: string;
  propertyId?: string;
  journal?: BillingJournal;
}
function EvidenceView({ value }: { value: JsonValue }) {
  if (value === null) return <span>None</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ol>
        {value.map((item, index) => (
          <li key={index}>
            <EvidenceView value={item} />
          </li>
        ))}
      </ol>
    ) : (
      <span>None</span>
    );
  if ("currency" in value && "minor_units" in value) {
    try {
      return <span>{formatUsd(money(value))}</span>;
    } catch {
      return <span>Invalid monetary evidence</span>;
    }
  }
  return (
    <dl className="billing-evidence">
      {Object.entries(value).map(([key, child]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>
            <EvidenceView value={child} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
function ConfirmationDialog({
  children,
  onCancel,
  opener,
}: {
  children: ReactNode;
  onCancel: () => void;
  opener: HTMLElement | null;
}) {
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    dialog.current?.focus();
    return () => {
      if (opener?.isConnected && !opener.matches(":disabled")) opener.focus();
      else document.getElementById("billing-notice")?.focus();
    };
  }, [opener]);
  return (
    <section
      ref={dialog}
      role="dialog"
      aria-modal="true"
      aria-label="Confirm billing action"
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
        if (event.key !== "Tab") return;
        const controls = [
          ...(dialog.current?.querySelectorAll<HTMLElement>("*") ?? []),
        ].filter(
          (control) =>
            control.matches(
              'button, summary, [href], input, select, [tabindex="0"]',
            ) && !control.matches(":disabled"),
        );
        const first = controls[0],
          last = controls.at(-1);
        if (!first) {
          event.preventDefault();
          dialog.current?.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === dialog.current)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === dialog.current)
        ) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      {children}
    </section>
  );
}
const fieldAliases: Record<string, string> = {
  authorized_nonrecurring_obligation_id: "obligation",
  invoice_line_id: "line",
  adjustment_type: "direction",
  amount: "amount",
  approved_amount: "amount",
  source_reference: "source",
  reverses_correction_id: "source",
  reason: "reason",
  outcome: "outcome",
  kind: "kind",
  logical_run_key: "logical",
  business_date: "business",
  period_start: "start",
  period_end: "end",
  category: "category",
  customer_id: "customer",
  lease_id: "lease",
  inspection_damage_finding_id: "finding",
  description: "description",
  amount_usd_cents: "amount",
  evidence_reference: "evidence",
  days: "days",
  due_date: "dueDate",
  due_date_reason: "dueDateReason",
};
function Field({
  name,
  label,
  type = "text",
  required = true,
  maxLength = 500,
  pattern,
}: {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  maxLength?: number;
  pattern?: string;
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        type={type}
        required={required}
        maxLength={maxLength}
        pattern={pattern}
      />
    </label>
  );
}
function value(data: FormData, name: string) {
  const field = data.get(name);
  return typeof field === "string" ? field.trim() : "";
}
function positive(data: FormData, name = "amount") {
  const amount = parseUsd(value(data, name));
  if (amount.minor_units === 0)
    throw new Error(
      "Enter a positive USD amount with at most two decimal places.",
    );
  return amount;
}
const categories: InvoiceCategory[] = [
  "RENT",
  "UTILITIES",
  "SERVICE_CHARGES",
  "DAMAGE_CHARGES",
  "MISCELLANEOUS_CHARGES",
];
const statuses: InvoiceStatus[] = [
  "DRAFT",
  "UNPAID",
  "PARTIALLY_PAID",
  "PAID",
  "VOID",
];

export function InvoiceManagement({
  api,
  actorId,
  propertyId = "",
  journal = billingJournal,
}: InvoiceManagementProps) {
  const [manualProperty, setManualProperty] = useState("");
  const scope = propertyId || manualProperty;
  return (
    <section className="panel" aria-labelledby="billing-heading">
      <h2 id="billing-heading">Billing and Invoices</h2>
      <p>
        Approved source obligations only. Financial history is preserved;
        late-payment charges are separate from invoices.
      </p>
      {!propertyId && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setManualProperty(
              value(new FormData(event.currentTarget), "property"),
            );
          }}
        >
          <Field name="property" label="Billing Property ID" />
          <button type="submit">Open billing Property</button>
        </form>
      )}
      {scope && actorId ? (
        <BillingWorkspace
          key={actorId + ":" + scope}
          api={api}
          actorId={actorId}
          propertyId={scope}
          journal={journal}
        />
      ) : (
        <p>Select an authorized Property to load billing.</p>
      )}
    </section>
  );
}
function BillingWorkspace({
  api,
  actorId,
  propertyId,
  journal,
}: {
  api: InvoiceApi;
  actorId: string;
  propertyId: string;
  journal: BillingJournal;
}) {
  const [items, setItems] = useState<InvoiceResource[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [capabilityError, setCapabilityError] =
    useState<InvoiceClientError | null>(null);
  const [capabilityLoading, setCapabilityLoading] = useState(false);
  const [capabilityRetry, setCapabilityRetry] = useState(0);
  const [filters, setFilters] = useState<InvoiceFilters>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const [invoice, setInvoice] = useState<InvoiceResource | null>(null);
  const [assessment, setAssessment] = useState<LatePaymentReview | null>(null);
  const [decision, setDecision] = useState<LatePaymentDecision | null>(null);
  const [charge, setCharge] = useState<LatePaymentCharge | null>(null);
  const [run, setRun] = useState<BillingRun | null>(null);
  const [recorded, setRecorded] = useState<OneTimeChargeRecord | null>(null);
  const [initialOverride, setInitialOverride] =
    useState<InitialRentDueDateOverride | null>(null);
  const [dueDays, setDueDays] = useState<DueDaysSetting | null>(null);
  const [lastRun, setLastRun] = useState<PendingBillingCommand | null>(null);
  const [preview, setPreview] = useState<{
    pending: PendingBillingCommand;
    context: JsonValue;
  } | null>(null);
  const [pending, setPending] = useState<PendingBillingCommand | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("Checking billing recovery…");
  const [failed, setFailed] = useState(false);
  const [validation, setValidation] = useState<InvoiceClientError | null>(null);
  const errorForm = useRef<HTMLFormElement | null>(null);
  const confirmationOpener = useRef<HTMLElement | null>(null);
  const transmission = useRef(new AbortController());
  const alive = useRef(true),
    lock = useRef(false);
  function stillMounted() {
    return alive.current;
  }
  const can = (capability: string) => capabilities.includes(capability);
  const blocked = busy || !ready || pending !== null || preview !== null;
  useLayoutEffect(() => {
    alive.current = true;
    transmission.current = new AbortController();
    void journal
      .load(actorId)
      .then((saved) => {
        if (!stillMounted()) return;
        setPending(saved);
        setReady(true);
        setNotice(
          saved
            ? "An earlier command needs reconciliation. Retry its exact saved request; no new financial action is allowed."
            : "Load authorized invoices to begin.",
        );
      })
      .catch(() => {
        if (stillMounted()) {
          setNotice(
            "Billing recovery unavailable. Financial actions remain blocked.",
          );
          setFailed(true);
        }
      });
    return () => {
      alive.current = false;
      transmission.current.abort();
    };
  }, [actorId, journal]);
  useEffect(() => {
    if (!api.capabilities) return;
    let active = true;
    setCapabilityLoading(true);
    setCapabilityError(null);
    setCapabilities([]);
    void api
      .capabilities(propertyId)
      .then((grants) => {
        if (active) {
          setCapabilities(grants);
          setCapabilityLoading(false);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setCapabilities([]);
          setCapabilityLoading(false);
          setCapabilityError(
            error instanceof InvoiceClientError
              ? error
              : new InvoiceClientError(null, "CAPABILITIES_UNAVAILABLE", false),
          );
        }
      });
    return () => {
      active = false;
    };
  }, [api, propertyId, capabilityRetry]);
  useEffect(() => {
    const fields = validation?.fields ?? [];
    const controls: Element[] = [];
    fields.forEach((field, index) => {
      const name = fieldAliases[field.split(".")[0] ?? ""];
      if (!name) return;
      const control = errorForm.current?.elements.namedItem(name);
      if (control instanceof HTMLElement) {
        control.setAttribute("aria-invalid", "true");
        control.setAttribute(
          "aria-describedby",
          "billing-field-error-" + String(index),
        );
        controls.push(control);
      }
    });
    return () => {
      controls.forEach((control) => {
        control.removeAttribute("aria-invalid");
        control.removeAttribute("aria-describedby");
      });
    };
  }, [validation]);
  function message(error: unknown, action?: BillingCommand["action"]) {
    if (
      action === "adjust" &&
      error instanceof InvoiceClientError &&
      !error.outcomeUnknown &&
      error.status === 422
    )
      return "The Adjustment was refused. A debit needs a remaining balance on the line, and a credit cannot exceed the line's adjusted obligation. Check the amount and direction.";
    return error instanceof InvoiceClientError
      ? error.message
      : "The billing request could not be verified. Reload or reconcile before continuing.";
  }
  async function read(task: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setFailed(false);
    setValidation(null);
    errorForm.current = null;
    try {
      await task();
    } catch (error) {
      if (stillMounted()) {
        setNotice(message(error));
        setValidation(error instanceof InvoiceClientError ? error : null);
        setFailed(true);
      }
    } finally {
      lock.current = false;
      if (stillMounted()) setBusy(false);
    }
  }
  async function load(nextFilters: InvoiceFilters, append = false) {
    if (!api.capabilities) setCapabilities([]);
    await read(async () => {
      const page = await api.list(propertyId, nextFilters);
      if (!stillMounted()) return;
      if (page.items.some((item) => item.property_id !== propertyId))
        throw new Error("Property scope mismatch");
      setItems((old) =>
        append
          ? [
              ...old,
              ...page.items.filter(
                (item) => !old.some((existing) => existing.id === item.id),
              ),
            ]
          : page.items,
      );
      setCursor(page.next_cursor);
      if (!api.capabilities) setCapabilities(page.capabilities);
      setFilters(nextFilters);
      setLoaded(true);
      setNotice(
        page.items.length
          ? "Authorized invoices loaded."
          : "No invoices match these filters.",
      );
    });
  }
  async function openInvoice(id: string) {
    setInvoice(null);
    setAssessment(null);
    setDecision(null);
    setCharge(null);
    await read(async () => {
      const result = await api.get(id);
      if (!stillMounted()) return;
      if (result.property_id !== propertyId || result.id !== id)
        throw new Error("Invoice scope mismatch");
      setInvoice(result);
      setNotice("Invoice and immutable history loaded.");
    });
  }
  function review(
    command: BillingCommand,
    context: JsonValue = null,
    form: HTMLFormElement | null = null,
  ) {
    setValidation(null);
    errorForm.current = form;
    if (blocked || lock.current) return;
    if (command.action === "adjust" && invoice?.id === command.id) {
      const line = invoice.lines.find(
        (item) => item.id === command.input.invoice_line_id,
      );
      if (!line) throw new Error("Invoice line unavailable");
      const delta =
        BigInt(command.input.amount.minor_units) *
        (command.input.adjustment_type === "DEBIT" ? 1n : -1n);
      const adjusted = BigInt(invoice.adjusted_total.minor_units) + delta;
      const applied = BigInt(invoice.active_application_total.minor_units);
      if (
        BigInt(line.adjusted_amount.minor_units) + delta < 0n ||
        adjusted < applied ||
        adjusted > (1n << 63n) - 1n
      ) {
        throw new Error("Adjustment outside displayed balance bounds");
      }
      const outstanding = adjusted - applied;
      context = {
        reviewed_invoice: context,
        estimated_adjusted_total: {
          currency: "USD",
          minor_units: adjusted,
        },
        estimated_outstanding_balance: {
          currency: "USD",
          minor_units: outstanding,
        },
        estimated_status:
          outstanding === 0n
            ? "PAID"
            : applied > 0n
              ? "PARTIALLY_PAID"
              : "UNPAID",
        notice:
          "Snapshot estimate only. The server validates the current version, line balance and status at confirmation.",
      };
    }
    if (command.action === "correctCharge" && charge?.id === command.id) {
      const current = BigInt(charge.adjusted_obligation.minor_units);
      const remaining = BigInt(charge.remaining_balance.minor_units);
      let delta: bigint;
      if (command.input.kind === "REDUCTION") {
        delta = -BigInt(command.input.amount.minor_units);
        if (delta >= 0n || -delta >= current)
          throw new Error("Invalid reduction");
      } else if (command.input.kind === "CHARGE_REVERSAL") delta = -current;
      else {
        const id = command.input.reverses_correction_id;
        const source = charge.corrections.find(
          (item) =>
            item.id === id && item.kind === "REDUCTION" && item.active === true,
        );
        if (
          !source ||
          charge.corrections.some((item) => item.reverses_correction_id === id)
        )
          throw new Error(
            "Active reduction unavailable; reload charge history",
          );
        delta = BigInt(money(source.amount).minor_units);
        if (delta <= 0n) throw new Error("Invalid reduction evidence");
      }
      const resulting = current + delta,
        balance = remaining + delta;
      if (
        resulting < 0n ||
        resulting > BigInt(charge.original_amount.minor_units) ||
        balance < 0n
      )
        throw new Error(
          "Correction requires application reversal or exceeds the obligation",
        );
      context = {
        reviewed_charge: context,
        estimated_effect: { currency: "USD", minor_units: delta },
        estimated_resulting_obligation: {
          currency: "USD",
          minor_units: resulting,
        },
        estimated_remaining_balance: { currency: "USD", minor_units: balance },
        notice:
          "Snapshot estimate only. The server validates current authority, active applications and correction history. This appends an immutable correction; the original charge, final decision and source invoice remain in history.",
      };
    }
    if (command.action === "void")
      context = {
        reviewed_invoice: context,
        estimated_status: "VOID",
        notice:
          "Voiding ends this obligation and records an immutable void event and reason. Original invoice history is preserved. The server checks current authority, version and unresolved dependencies.",
      };
    setFailed(false);
    // Capture before rendering disables the fieldset and the browser blurs it.
    confirmationOpener.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setPreview({ pending: { key: crypto.randomUUID(), command }, context });
    setNotice("Review the exact action and evidence, then explicitly confirm.");
  }
  function formReview(
    event: FormEvent<HTMLFormElement>,
    build: (data: FormData) => BillingCommand,
    context: JsonValue = null,
  ) {
    event.preventDefault();
    errorForm.current = event.currentTarget;
    setValidation(null);
    try {
      review(
        build(new FormData(event.currentTarget)),
        context,
        event.currentTarget,
      );
    } catch {
      setFailed(true);
      setNotice(
        "Check required fields. Use an exact positive USD amount with at most two decimal places.",
      );
    }
  }
  async function submit(intent: PendingBillingCommand, retry: boolean) {
    if (lock.current || !ready || intent.command.propertyId !== propertyId)
      return;
    lock.current = true;
    setBusy(true);
    setFailed(false);
    setValidation(null);
    if (retry) errorForm.current = null;
    let saved = retry;
    const signal = transmission.current.signal;
    try {
      if (!retry) {
        await journal.begin(actorId, intent);
        saved = true;
      }
      if (!stillMounted() || signal.aborted) return;
      // Persist before sending; no authentication token is stored with the intent.
      if (stillMounted()) {
        setPending(intent);
        setNotice("Submitting the confirmed billing command…");
      }
      const result = await executeBilling(api, intent, { actorId, signal });
      if (
        intent.command.action === "decide" &&
        (!("source_invoice" in result) ||
          result.source_invoice.id !== intent.command.id)
      ) {
        throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      }
      if (
        intent.command.action === "run" &&
        (!("run_kind" in result) ||
          result.run_kind.toLowerCase() !== intent.command.kind ||
          result.logical_run_key !== intent.command.input.logical_run_key ||
          result.business_date !== intent.command.input.business_date ||
          result.period.start !== intent.command.input.period_start ||
          result.period.end !== intent.command.input.period_end)
      ) {
        throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      }
      if (intent.command.action === "oneTimeCharge") {
        const sent = intent.command.input;
        if (
          !("obligation_id" in result) ||
          result.obligation_id !== sent.charge_id ||
          result.category !== sent.category ||
          result.customer_id !== sent.customer_id ||
          result.lease_id !== sent.lease_id ||
          BigInt(result.amount.minor_units) !== BigInt(sent.amount.minor_units)
        )
          throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      } else if (intent.command.action === "initialRentDueDate") {
        const sent = intent.command.input;
        if (
          !("override_id" in result) ||
          result.property_id !== propertyId ||
          result.override_id !== sent.override_id ||
          result.lease_id !== intent.command.leaseId ||
          result.due_date !== sent.due_date
        )
          throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      } else if (intent.command.action === "dueDays") {
        if (
          !("one_time_charge_due_days" in result) ||
          result.property_id !== propertyId ||
          result.one_time_charge_due_days !== intent.command.days ||
          result.version < intent.command.propertyVersion
        )
          throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      } else if (
        !("property_id" in result) ||
        result.property_id !== propertyId ||
        ("id" in intent.command &&
          intent.command.action !== "decide" &&
          (!("id" in result) || result.id !== intent.command.id))
      ) {
        throw new InvoiceClientError(null, "RESOURCE_MISMATCH", true);
      }
      await journal.clear(actorId, intent.key);
      if (!stillMounted()) return;
      setPending(null);
      if ("obligation_id" in result) {
        setRecorded(result);
      } else if ("override_id" in result) {
        setInitialOverride(result);
      } else if ("one_time_charge_due_days" in result) {
        setDueDays(result);
      } else if ("invoice_number" in result) {
        setInvoice(result);
        setAssessment(null);
        setDecision(null);
        setCharge(null);
        setItems((old) =>
          old.map((item) => (item.id === result.id ? result : item)),
        );
      } else if ("run_kind" in result) {
        setRun(result);
        setLastRun(intent);
      } else if ("outcome" in result) {
        setDecision(result);
        setAssessment(null);
        setCharge(null);
      } else {
        setCharge(result);
      }
      setNotice(
        "Command confirmed. History is preserved. Reload the list separately to refresh filters; do not repeat a successful command.",
      );
    } catch (error) {
      const terminalDecision =
        error instanceof InvoiceClientError &&
        !error.outcomeUnknown &&
        error.status === 409 &&
        error.code === "CONFLICT" &&
        intent.command.action === "decide" &&
        error.currentDecision?.property_id === propertyId &&
        error.currentDecision.source_invoice.id === intent.command.id
          ? error.currentDecision
          : null;
      const terminalCharge =
        error instanceof InvoiceClientError &&
        !error.outcomeUnknown &&
        error.status === 409 &&
        error.code === "CONFLICT" &&
        intent.command.action === "correctCharge" &&
        error.currentCharge?.property_id === propertyId &&
        error.currentCharge.id === intent.command.id &&
        terminalChargeConflict(error.currentCharge, intent.command.input)
          ? error.currentCharge
          : null;
      if (!saved) {
        try {
          const other = await journal.load(actorId);
          if (stillMounted()) setPending(other);
        } catch {
          if (stillMounted()) setReady(false);
        }
      } else if (terminalDecision || terminalCharge) {
        try {
          // Successful receipts precede final-decision conflicts on the server.
          // Clear only this rejected key, never an ambiguous or foreign outcome.
          await journal.clear(actorId, intent.key);
          if (stillMounted()) {
            setPending(null);
            if (terminalDecision) {
              setDecision(terminalDecision);
              setCharge(null);
            } else if (terminalCharge) setCharge(terminalCharge);
            setAssessment(null);
          }
        } catch {
          /* Unconfirmed clearance retains the durable recovery gate. */
        }
      } else if (
        error instanceof InvoiceClientError &&
        !error.outcomeUnknown &&
        ((!retry &&
          error.status !== null &&
          [400, 412, 422].includes(error.status)) ||
          (error.status === 412 &&
            error.code === "PRECONDITION_FAILED" &&
            error.currentVersion !== null &&
            ("version" in intent.command ||
              "propertyVersion" in intent.command)))
      ) {
        try {
          await journal.clear(actorId, intent.key);
          if (stillMounted()) {
            setPending(null);
            // Preserve reviewed inputs; any subsequent review uses a freshly loaded resource.
            if ("version" in intent.command) {
              const current = await api.get(intent.command.id);
              if (
                stillMounted() &&
                current.property_id === propertyId &&
                current.id === intent.command.id
              )
                setInvoice(current);
              else if (stillMounted()) setInvoice(null);
            }
          }
        } catch {
          if (stillMounted()) setInvoice(null);
          /* Keep the durable gate when clearance is not confirmed. */
        }
      }
      if (stillMounted()) {
        setFailed(true);
        setValidation(error instanceof InvoiceClientError ? error : null);
        setNotice(message(error, intent.command.action));
      }
    } finally {
      lock.current = false;
      if (stillMounted()) {
        setBusy(false);
        setPreview(null);
      }
    }
  }
  async function lateReview() {
    if (!invoice) return;
    const id = invoice.id;
    setAssessment(null);
    setDecision(null);
    setCharge(null);
    await read(async () => {
      const result = await api.lateReview(id);
      if (!stillMounted()) return;
      if (result.property_id !== propertyId || result.invoice_id !== id)
        throw new Error("Assessment scope mismatch");
      setAssessment(result);
      if (result.prior_decision !== null) {
        const prior = await api.lateDecision(id);
        if (!stillMounted()) return;
        if (prior.property_id !== propertyId || prior.source_invoice.id !== id)
          throw new Error("Decision scope mismatch");
        setDecision(prior);
      }
      setNotice(
        "Late-payment review loaded. The server determines eligibility and the exact default amount.",
      );
    });
  }
  return (
    <div className="billing-workspace">
      {capabilityLoading && (
        <p role="status">Loading billing action availability…</p>
      )}
      {capabilityError && (
        <section aria-label="Billing action availability" role="alert">
          <p>
            Billing action availability could not be loaded.{" "}
            {capabilityError.message}
          </p>
          {capabilityError.requestId && (
            <p>Support request ID: {capabilityError.requestId}</p>
          )}
          <button
            type="button"
            disabled={capabilityLoading}
            onClick={() => {
              setCapabilityRetry((value) => value + 1);
            }}
          >
            Retry billing action availability
          </button>
        </section>
      )}
      <p id="billing-notice" tabIndex={-1} role={failed ? "alert" : "status"}>
        {notice}
      </p>
      {validation && (
        <div aria-live="polite">
          {validation.requestId && (
            <p>Support request ID: {validation.requestId}</p>
          )}
          {validation.fields.map((field, index) => (
            <p key={field} id={"billing-field-error-" + String(index)}>
              {field.replaceAll("_", " ")}: Check this value.
            </p>
          ))}
        </div>
      )}
      {pending && (
        <section aria-label="Billing reconciliation">
          <h3>Reconcile saved billing command</h3>
          <p>
            Request {pending.key}. A lost response is not a failed transaction.
            Do not create a replacement command.
          </p>
          {pending.command.propertyId === propertyId ? (
            <>
              <EvidenceView value={pending.command as unknown as JsonValue} />
              <button
                type="button"
                disabled={busy || !ready || preview !== null}
                onClick={() => void submit(pending, true)}
              >
                Retry exact saved request
              </button>
            </>
          ) : (
            <p>
              The saved request belongs to another Property. Open that Property
              to reconcile it first.
            </p>
          )}
        </section>
      )}
      <fieldset disabled={busy || preview !== null}>
        <legend>Find invoices</legend>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            void load({
              status: (value(data, "status") || undefined) as
                | InvoiceStatus
                | undefined,
              category: (value(data, "category") || undefined) as
                | InvoiceCategory
                | undefined,
              customer_id: value(data, "customer") || undefined,
              lease_id: value(data, "lease") || undefined,
            });
          }}
        >
          <label>
            Invoice status
            <select name="status">
              <option value="">All statuses</option>
              {statuses.map((status) => (
                <option key={status}>{status}</option>
              ))}
            </select>
          </label>
          <label>
            Invoice category
            <select name="category">
              <option value="">All categories</option>
              {categories.map((category) => (
                <option key={category}>{category}</option>
              ))}
            </select>
          </label>
          <Field
            name="customer"
            label="Invoice Customer ID filter"
            required={false}
          />
          <Field
            name="lease"
            label="Invoice Lease ID filter"
            required={false}
          />
          <button type="submit">Load invoices</button>
        </form>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void openInvoice(value(new FormData(event.currentTarget), "id"));
          }}
        >
          <Field name="id" label="Invoice ID to inspect" />
          <button type="submit">Open invoice by ID</button>
        </form>
      </fieldset>
      {loaded &&
        (items.length ? (
          <div className="table-scroll">
            <table>
              <caption>Invoices for this Property</caption>
              <thead>
                <tr>
                  {[
                    "Invoice",
                    "Customer",
                    "Lease",
                    "Category",
                    "Invoice date",
                    "Due date",
                    "Original",
                    "Adjusted",
                    "Outstanding",
                    "Status",
                  ].map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <button
                        type="button"
                        disabled={busy || preview !== null}
                        onClick={() => void openInvoice(item.id)}
                      >
                        {item.invoice_number}
                      </button>
                    </td>
                    <td>{item.customer_id}</td>
                    <td>{item.lease_id ?? "None"}</td>
                    <td>{item.category}</td>
                    <td>{item.invoice_date}</td>
                    <td>{item.due_date ?? "Set when issued"}</td>
                    <td>{formatUsd(item.original_total)}</td>
                    <td>{formatUsd(item.adjusted_total)}</td>
                    <td>{formatUsd(item.outstanding_balance)}</td>
                    <td>{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No matching invoices.</p>
        ))}
      {cursor && (
        <button
          type="button"
          disabled={busy || preview !== null}
          onClick={() => void load({ ...filters, cursor }, true)}
        >
          Load more invoices
        </button>
      )}
      <fieldset disabled={blocked}>
        <legend>Authorized billing actions</legend>
        {can("invoices.create") && (
          <form
            onSubmit={(event) => {
              formReview(event, (data) => ({
                action: "create",
                propertyId,
                obligationId: value(data, "obligation"),
              }));
            }}
          >
            <h3>Create draft from approved source</h3>
            <p>
              Only an existing authorized nonrecurring obligation may supply the
              Customer, approved category, lines and amount. Rent and Utilities
              use billing runs.
            </p>
            <Field name="obligation" label="Authorized obligation ID" />
            <button type="submit">Review draft creation</button>
          </form>
        )}
        {(can("damage_charges.bill") || can("invoices.create")) && (
          <form
            onSubmit={(event) => {
              formReview(event, (data) => {
                const category = value(
                  data,
                  "category",
                ) as OneTimeChargeCategory;
                if (
                  !can(
                    category === "DAMAGE_CHARGES"
                      ? "damage_charges.bill"
                      : "invoices.create",
                  )
                )
                  throw new Error("Category not authorized");
                return {
                  action: "oneTimeCharge",
                  propertyId,
                  input: {
                    charge_id: crypto.randomUUID(),
                    category,
                    customer_id: value(data, "customer"),
                    lease_id: value(data, "lease") || null,
                    inspection_damage_finding_id:
                      value(data, "finding") || null,
                    description: value(data, "description"),
                    amount: positive(data),
                    reason: value(data, "reason"),
                    evidence_reference: value(data, "evidence"),
                  },
                };
              });
            }}
          >
            <h3>Record a one-time charge</h3>
            <p>
              A manual Damage or Miscellaneous charge needs a reason and an
              evidence reference. No photo is stored here. Recording the source
              does not bill the Customer; create a draft Invoice from it next.
            </p>
            <label>
              One-time charge category
              <select name="category">
                {can("damage_charges.bill") && (
                  <option value="DAMAGE_CHARGES">DAMAGE_CHARGES</option>
                )}
                {can("invoices.create") && (
                  <option value="MISCELLANEOUS_CHARGES">
                    MISCELLANEOUS_CHARGES
                  </option>
                )}
              </select>
            </label>
            <Field name="customer" label="One-time charge Customer ID" />
            <Field
              name="lease"
              label="One-time charge Lease ID (optional)"
              required={false}
            />
            <Field
              name="finding"
              label="Damage inspection finding ID (optional)"
              required={false}
            />
            <Field
              name="description"
              label="One-time charge description"
              maxLength={1000}
            />
            <Field
              name="amount"
              label="One-time charge amount (USD)"
              pattern="(0|[1-9][0-9]*)(\.[0-9]{1,2})?"
            />
            <Field name="reason" label="One-time charge reason" />
            <Field name="evidence" label="One-time charge evidence reference" />
            <button type="submit">Review one-time charge</button>
          </form>
        )}
        {recorded && (
          <section aria-label="Recorded one-time charge">
            <h3>Recorded one-time charge</h3>
            <p>
              {recorded.category} for Customer {recorded.customer_id}:{" "}
              {formatUsd(recorded.amount)}. Authorized obligation ID{" "}
              {recorded.obligation_id}.
            </p>
            <EvidenceView value={recorded.evidence} />
            {can("invoices.create") && (
              <button
                type="button"
                onClick={() => {
                  review({
                    action: "create",
                    propertyId,
                    obligationId: recorded.obligation_id,
                  });
                }}
              >
                Review draft from this charge
              </button>
            )}
          </section>
        )}
        {can("invoices.issue") && (
          <section aria-label="Initial Rent Due Date">
            <h3>Initial Rent Due Date</h3>
            <p>
              Set an authorized Due Date for a Lease&apos;s Initial Rent Invoice
              before that Invoice is issued. The reason is mandatory and the
              standard date stays in the history. The server checks the Lease
              and the date.
            </p>
            <form
              onSubmit={(event) => {
                formReview(event, (data) => {
                  const dueDate = value(data, "dueDate");
                  if (
                    !/^\d{4}-\d{2}-\d{2}$/.test(dueDate) ||
                    Number.isNaN(Date.parse(dueDate)) ||
                    !value(data, "lease") ||
                    !value(data, "reason")
                  )
                    throw new Error("Lease, Due Date and reason required");
                  return {
                    action: "initialRentDueDate",
                    propertyId,
                    leaseId: value(data, "lease"),
                    input: {
                      override_id: crypto.randomUUID(),
                      due_date: dueDate,
                      reason: value(data, "reason"),
                    },
                  };
                });
              }}
            >
              <Field name="lease" label="Initial Rent Lease ID" />
              <Field
                name="dueDate"
                label="Initial Rent authorized Due Date"
                type="date"
              />
              <Field name="reason" label="Initial Rent Due Date reason" />
              <button type="submit">Review Initial Rent Due Date</button>
            </form>
            {initialOverride && (
              <article aria-label="Recorded Initial Rent Due Date">
                <h4>Recorded Initial Rent Due Date</h4>
                <p>
                  Lease {initialOverride.lease_id}: due{" "}
                  {initialOverride.due_date} (standard date{" "}
                  {initialOverride.proposed_due_date}).
                </p>
                <EvidenceView value={initialOverride.evidence} />
              </article>
            )}
          </section>
        )}
        {can("settings.manage") && (
          <section aria-label="One-time charge due days">
            <h3>One-time charge due days</h3>
            <p>
              Days from issue to the Due Date of a one-time charge Invoice.
              Invoices already issued keep their fixed Due Dates.
              {dueDays &&
                " Current setting: " +
                  String(dueDays.one_time_charge_due_days) +
                  " days, Property version " +
                  String(dueDays.version) +
                  "."}
            </p>
            <form
              key={dueDays?.version ?? 0}
              onSubmit={(event) => {
                formReview(event, (data) => {
                  const days = Number(value(data, "days"));
                  const propertyVersion = Number(value(data, "version"));
                  if (
                    !/^[1-9][0-9]?$/.test(value(data, "days")) ||
                    days > 90 ||
                    !/^[1-9][0-9]{0,9}$/.test(value(data, "version")) ||
                    propertyVersion > 2_147_483_647
                  )
                    throw new Error("Invalid due days or Property version");
                  return {
                    action: "dueDays",
                    propertyId,
                    days,
                    reason: value(data, "reason"),
                    propertyVersion,
                  };
                });
              }}
            >
              <label>
                Due days for one-time charges (1 to 90)
                <input
                  name="days"
                  type="number"
                  min={1}
                  max={90}
                  step={1}
                  required
                  defaultValue={dueDays?.one_time_charge_due_days}
                />
              </label>
              <label>
                Current Property version
                <input
                  name="version"
                  type="number"
                  min={1}
                  step={1}
                  required
                  defaultValue={dueDays?.version}
                />
              </label>
              <Field name="reason" label="Due days change reason" />
              <button type="submit">Review due days change</button>
            </form>
          </section>
        )}
        {invoice && (
          <section aria-label="Invoice detail">
            <h3>Invoice {invoice.invoice_number}</h3>
            <p>
              Customer {invoice.customer_id} · Lease{" "}
              {invoice.lease_id ?? "None"} · {invoice.status} · Version{" "}
              {invoice.version}
            </p>
            <p>
              Original {formatUsd(invoice.original_total)} · Adjusted{" "}
              {formatUsd(invoice.adjusted_total)} · Active applications{" "}
              {formatUsd(invoice.active_application_total)} · Outstanding{" "}
              {formatUsd(invoice.outstanding_balance)}
            </p>
            <p>
              Invoice date {invoice.invoice_date}; due{" "}
              {invoice.due_date ?? "set when issued"}.
            </p>
            <h4>Immutable lines and source evidence</h4>
            {invoice.lines.map((line) => (
              <article key={line.id}>
                <h5>{line.description}</h5>
                <p>
                  {line.category}: original {formatUsd(line.original_amount)},
                  adjusted {formatUsd(line.adjusted_amount)}, outstanding{" "}
                  {formatUsd(line.outstanding_balance)}
                </p>
                <EvidenceView
                  value={{
                    source: line.source,
                    calculation: line.calculation_evidence,
                    period: line.period,
                  }}
                />
              </article>
            ))}
            <details>
              <summary>
                Complete invoice, application, adjustment, void and audit
                history
              </summary>
              <EvidenceView value={invoice.evidence} />
            </details>
            {invoice.status === "DRAFT" && (
              <>
                {can("invoices.create") && (
                  <form
                    onSubmit={(event) => {
                      formReview(
                        event,
                        (data) => ({
                          action: "correct",
                          propertyId,
                          id: invoice.id,
                          version: invoice.version,
                          obligationId: value(data, "obligation"),
                          reason: value(data, "reason"),
                        }),
                        invoice.evidence,
                      );
                    }}
                  >
                    <Field
                      name="obligation"
                      label="Corrected authorized obligation ID"
                    />
                    <Field name="reason" label="Draft correction reason" />
                    <button type="submit">Review draft correction</button>
                  </form>
                )}
                {can("invoices.issue") && (
                  <button
                    type="button"
                    onClick={() => {
                      review(
                        {
                          action: "issue",
                          propertyId,
                          id: invoice.id,
                          version: invoice.version,
                        },
                        invoice.evidence,
                      );
                    }}
                  >
                    Review invoice issuance
                  </button>
                )}
                {can("invoices.issue") && (
                  <form
                    onSubmit={(event) => {
                      formReview(
                        event,
                        (data) => {
                          const dueDate = value(data, "dueDate");
                          if (!value(data, "dueDateReason"))
                            throw new Error("Due Date reason required");
                          if (
                            !/^\d{4}-\d{2}-\d{2}$/.test(dueDate) ||
                            Number.isNaN(Date.parse(dueDate))
                          )
                            throw new Error("Due Date required");
                          return {
                            action: "issue",
                            propertyId,
                            id: invoice.id,
                            version: invoice.version,
                            dueDate: {
                              due_date: dueDate,
                              due_date_reason: value(data, "dueDateReason"),
                            },
                          };
                        },
                        invoice.evidence,
                      );
                    }}
                  >
                    <h4>Issue with an authorized Due Date</h4>
                    <p>
                      Use this only when the Due Date must differ from the
                      standard rule. The reason is mandatory and is recorded
                      with the issue. The server decides whether the date is
                      allowed.
                    </p>
                    <Field
                      name="dueDate"
                      label="Authorized Due Date"
                      type="date"
                    />
                    <Field name="dueDateReason" label="Due Date reason" />
                    <button type="submit">
                      Review invoice issuance with Due Date
                    </button>
                  </form>
                )}
              </>
            )}
            {invoice.status !== "DRAFT" && invoice.status !== "VOID" && (
              <>
                {can("invoices.adjust") && (
                  <form
                    onSubmit={(event) => {
                      formReview(
                        event,
                        (data) => ({
                          action: "adjust",
                          propertyId,
                          id: invoice.id,
                          version: invoice.version,
                          input: {
                            invoice_line_id: value(data, "line"),
                            adjustment_type: value(data, "direction") as
                              | "DEBIT"
                              | "CREDIT",
                            amount: positive(data),
                            source_reference: value(data, "source"),
                            reason: value(data, "reason"),
                          },
                        }),
                        invoice.evidence,
                      );
                    }}
                  >
                    <h4>Append an adjustment</h4>
                    <p>
                      Debit increases the obligation; credit decreases it. The
                      server validates the resulting balance and status without
                      editing issued lines.
                    </p>
                    <label>
                      Adjustment line
                      <select name="line">
                        {invoice.lines.map((line) => (
                          <option key={line.id} value={line.id}>
                            {line.description}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Adjustment direction
                      <select name="direction">
                        <option>DEBIT</option>
                        <option>CREDIT</option>
                      </select>
                    </label>
                    <Field
                      name="amount"
                      label="Adjustment amount (USD)"
                      pattern="(0|[1-9][0-9]*)(\.[0-9]{1,2})?"
                    />
                    <Field name="source" label="Adjustment source reference" />
                    <Field name="reason" label="Adjustment reason" />
                    <button type="submit">Review adjustment</button>
                  </form>
                )}
              </>
            )}{" "}
            {invoice.status !== "VOID" && can("invoices.void") && (
              <form
                onSubmit={(event) => {
                  formReview(
                    event,
                    (data) => ({
                      action: "void",
                      propertyId,
                      id: invoice.id,
                      version: invoice.version,
                      reason: value(data, "reason"),
                    }),
                    invoice.evidence,
                  );
                }}
              >
                <h4>Exceptional invoice void</h4>
                <p>
                  Void preserves history and ends this obligation. Active
                  applications must be reversed through their authorized
                  workflow first.
                </p>
                <Field name="reason" label="Invoice void reason" />
                <button
                  type="submit"
                  disabled={invoice.active_application_total.minor_units > 0}
                >
                  Review invoice void
                </button>
              </form>
            )}
            {can("late_payment.review") && (
              <button type="button" onClick={() => void lateReview()}>
                Review late payment
              </button>
            )}
          </section>
        )}
        {assessment && (
          <section aria-label="Late-payment assessment">
            <h3>Late-payment review</h3>
            <p>
              Overdue {formatUsd(assessment.overdue_balance)} · Default 10% ·
              Calculated default{" "}
              {formatUsd(assessment.calculated_default_amount)}
            </p>
            <p>
              {assessment.eligible
                ? "Eligible for one final decision."
                : "Not eligible: " + assessment.blocking_conditions.join(", ")}
            </p>
            <EvidenceView value={assessment.prior_decision} />
            {assessment.eligible &&
              assessment.prior_decision === null &&
              can("late_payment.final_decision") && (
                <form
                  onSubmit={(event) => {
                    formReview(
                      event,
                      (data) => {
                        const outcome = value(
                          data,
                          "outcome",
                        ) as DecisionOutcome;
                        const amount =
                          outcome === "WAIVED"
                            ? parseUsd("0")
                            : outcome === "CONFIRMED_DEFAULT"
                              ? assessment.calculated_default_amount
                              : positive(data);
                        if (
                          outcome === "REDUCED" &&
                          amount.minor_units >=
                            assessment.calculated_default_amount.minor_units
                        )
                          throw new Error("Reduction must be below default.");
                        return {
                          action: "decide",
                          propertyId,
                          id: assessment.invoice_id,
                          outcome,
                          amount: requestMoney(amount),
                          reason: value(data, "reason"),
                        };
                      },
                      {
                        overdue:
                          assessment.overdue_balance as unknown as JsonValue,
                        default_amount:
                          assessment.calculated_default_amount as unknown as JsonValue,
                      },
                    );
                  }}
                >
                  <p>
                    This decision is final. A positive amount creates a separate
                    Late-payment Charge; a waiver creates no charge. The source
                    invoice is unchanged.
                  </p>
                  <label>
                    Final decision
                    <select name="outcome">
                      <option>CONFIRMED_DEFAULT</option>
                      <option>REDUCED</option>
                      <option>WAIVED</option>
                    </select>
                  </label>
                  <Field
                    name="amount"
                    label="Exact reduced amount (USD; REDUCED only)"
                    required={false}
                  />
                  <Field name="reason" label="Late-payment decision reason" />
                  <button type="submit">Review final decision</button>
                </form>
              )}
          </section>
        )}
        {decision && (
          <section aria-label="Final late-payment decision">
            <h3>Final decision: {decision.outcome}</h3>
            <p>
              Approved {formatUsd(decision.approved_amount)}. This is not an
              invoice adjustment.
            </p>
            <EvidenceView value={decision.evidence} />
            {decision.charge && can("late_payment.review") && (
              <button
                type="button"
                onClick={() =>
                  void read(async () => {
                    const target = decision.charge;
                    if (!target) return;
                    const result = await api.charge(target.id);
                    if (!stillMounted()) return;
                    if (
                      result.property_id !== propertyId ||
                      result.id !== target.id ||
                      result.customer_id !== decision.customer_id
                    )
                      throw new Error("Charge scope mismatch");
                    setCharge(result);
                    setNotice("Separate charge and correction history loaded.");
                  })
                }
              >
                Open separate Late-payment Charge
              </button>
            )}
          </section>
        )}
        {charge && (
          <section aria-label="Late-payment charge">
            <h3>Separate Late-payment Charge</h3>
            <p>
              Original {formatUsd(charge.original_amount)} · Adjusted{" "}
              {formatUsd(charge.adjusted_obligation)} · Remaining{" "}
              {formatUsd(charge.remaining_balance)}
            </p>
            <EvidenceView value={charge.evidence} />
            {can("late_payment.charge_correction") && (
              <form
                onSubmit={(event) => {
                  formReview(
                    event,
                    (data) => {
                      const kind = value(
                          data,
                          "kind",
                        ) as ChargeCorrectionInput["kind"],
                        reason = value(data, "reason");
                      const input: ChargeCorrectionInput =
                        kind === "REDUCTION"
                          ? { kind, amount: positive(data), reason }
                          : kind === "REDUCTION_REVERSAL"
                            ? {
                                kind,
                                reverses_correction_id: value(data, "source"),
                                reason,
                              }
                            : { kind, reason };
                      if (
                        kind === "REDUCTION_REVERSAL" &&
                        !value(data, "source")
                      )
                        throw new Error("Source correction required");
                      return {
                        action: "correctCharge",
                        propertyId,
                        id: charge.id,
                        input,
                      };
                    },
                    charge.evidence,
                  );
                }}
              >
                <p>
                  Append-only correction. Original charge, source invoice and
                  applications remain in history. Required application reversals
                  are enforced by the server.
                </p>
                <label>
                  Charge correction kind
                  <select name="kind">
                    <option>REDUCTION</option>
                    <option>CHARGE_REVERSAL</option>
                    <option>REDUCTION_REVERSAL</option>
                  </select>
                </label>
                <Field
                  name="amount"
                  label="Charge reduction amount (USD)"
                  required={false}
                />
                <Field
                  name="source"
                  label="Reduction correction ID to reverse"
                  required={false}
                />
                <Field name="reason" label="Charge correction reason" />
                <button type="submit">Review charge correction</button>
              </form>
            )}
          </section>
        )}
        {can("billing.generate") && (
          <section aria-label="Billing runs">
            <h3>Billing runs</h3>
            <form
              onSubmit={(event) => {
                formReview(event, (data) => {
                  const input = {
                    logical_run_key: value(data, "logical"),
                    business_date: value(data, "business"),
                    period_start: value(data, "start"),
                    period_end: value(data, "end"),
                  };
                  if (input.period_end < input.period_start)
                    throw new Error("Period order");
                  return {
                    action: "run",
                    propertyId,
                    kind: value(data, "kind") as "rent" | "utilities",
                    input,
                  };
                });
              }}
            >
              <p>
                The server resolves eligible leases and approved sources. Use
                the same logical identity and period to reconcile a run; do not
                invent a new key to bypass duplicate protection.
              </p>
              <label>
                Billing run kind
                <select name="kind">
                  <option value="rent">Rent</option>
                  <option value="utilities">Utilities</option>
                </select>
              </label>
              <Field
                name="logical"
                label="Logical billing run key"
                maxLength={200}
              />
              <Field
                name="business"
                label="Billing business date"
                type="date"
              />
              <Field name="start" label="Billing period start" type="date" />
              <Field name="end" label="Billing period end" type="date" />
              <button type="submit">Review billing run</button>
            </form>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const id = value(new FormData(event.currentTarget), "run");
                void read(async () => {
                  const result = await api.getRun(id);
                  if (!stillMounted()) return;
                  if (result.property_id !== propertyId || result.id !== id)
                    throw new Error("Run scope mismatch");
                  setRun(result);
                  setLastRun(billingRunRetry(result, actorId, propertyId));
                  setNotice("Billing run evidence loaded.");
                });
              }}
            >
              <Field name="run" label="Billing run ID" />
              <button type="submit">Inspect billing run</button>
            </form>
            {run && (
              <article>
                <h4>
                  Run {run.logical_run_key}: {run.status}
                </h4>
                <p>
                  {run.period.start} to {run.period.end}; business date{" "}
                  {run.business_date}
                </p>
                <RunDiagnostics run={run} />
                <EvidenceView value={run.evidence} />
                {run.attempts
                  .flatMap((attempt) =>
                    Array.isArray(attempt.items) ? attempt.items : [],
                  )
                  .map((item, index) =>
                    item !== null &&
                    typeof item === "object" &&
                    !Array.isArray(item) &&
                    typeof item.invoice_id === "string" ? (
                      <button
                        type="button"
                        key={index}
                        onClick={() =>
                          void openInvoice(item.invoice_id as string)
                        }
                      >
                        Open generated invoice {item.invoice_id}
                      </button>
                    ) : null,
                  )}
                {lastRun && run.status === "RETRYABLE" && (
                  <button
                    type="button"
                    onClick={(event) => {
                      setValidation(null);
                      errorForm.current = null;
                      setFailed(false);
                      confirmationOpener.current = event.currentTarget;
                      setPreview({ pending: lastRun, context: run.evidence });
                      setNotice(
                        "Review the exact action and evidence, then explicitly confirm.",
                      );
                    }}
                  >
                    Review retry of same billing run
                  </button>
                )}
              </article>
            )}
          </section>
        )}
      </fieldset>
      {preview && (
        <ConfirmationDialog
          opener={confirmationOpener.current}
          onCancel={() => {
            if (!busy) {
              setPreview(null);
              setNotice("Action cancelled; nothing was sent.");
            }
          }}
        >
          <h3>Confirm {preview.pending.command.action}</h3>
          <p>
            Only this exact request will be sent. Review the Customer, source,
            period, due date, original and adjusted amounts below. The server
            validates current authority and financial invariants.
          </p>
          <EvidenceView
            value={preview.pending.command as unknown as JsonValue}
          />
          {preview.context !== null && (
            <details open>
              <summary>Evidence reviewed for this action</summary>
              <EvidenceView value={preview.context} />
            </details>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void submit(preview.pending, false)}
          >
            Confirm billing action
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setPreview(null);
              setNotice("Action cancelled; nothing was sent.");
            }}
          >
            Cancel billing action
          </button>
        </ConfirmationDialog>
      )}
    </div>
  );
}
