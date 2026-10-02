import { BillingRun, JsonValue } from "./invoiceClient";

const DIAGNOSTICS: Record<string, string> = {
  ACTIVE_INVOICE_ALREADY_EXISTS:
    "An active Invoice already exists for this source and period, so nothing was generated.",
  SOURCE_NO_LONGER_ELIGIBLE:
    "The source was no longer eligible when the run reached it.",
  NOT_MOVED_IN:
    "The Customer had not moved in yet. The period was skipped; bill it later with an explicit catch-up.",
  PROPERTY_BORNE_CONSUMPTION:
    "No Lease is responsible for this consumption, so the Property bears it and nothing was billed.",
  ITEM_FAILURE:
    "This item failed. Review the evidence and retry the same run; do not start a new key.",
};

export function runDiagnosticText(code: string | null): string {
  if (code === null) return "";
  return (
    DIAGNOSTICS[code] ??
    (/^[A-Z0-9_]{1,80}$/.test(code)
      ? `Diagnostic code ${code}.`
      : "A diagnostic was recorded.")
  );
}

const OUTCOMES: Record<string, string> = {
  GENERATED: "Generated",
  SKIPPED: "Skipped",
  FAILED: "Failed",
  RUNNING: "Running",
  SUCCEEDED: "Succeeded",
  RETRYABLE: "Needs retry",
};

function outcomeText(value: string): string {
  return OUTCOMES[value] ?? value;
}

function record(value: JsonValue | undefined): Record<string, JsonValue> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : {};
}

function text(value: JsonValue | undefined): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : "";
}

export interface RunItemDiagnostic {
  attempt: string;
  source: string;
  period: string;
  outcome: string;
  why: string;
}

export function runDiagnostics(run: BillingRun) {
  const counts = new Map<string, number>();
  const items: RunItemDiagnostic[] = [];
  const attempts = run.attempts.map((attempt) => {
    const number = text(attempt.attempt_number);
    const rows = Array.isArray(attempt.items) ? attempt.items : [];
    for (const raw of rows) {
      const item = record(raw);
      const outcome = text(item.outcome);
      counts.set(outcome, (counts.get(outcome) ?? 0) + 1);
      items.push({
        attempt: number,
        source: `${text(item.source_kind)} ${text(item.source_id)}`.trim(),
        period: `${text(item.period_start)} to ${text(item.period_end)}`,
        outcome: outcomeText(outcome),
        why: runDiagnosticText(
          typeof item.diagnostic_code === "string"
            ? item.diagnostic_code
            : null,
        ),
      });
    }
    return {
      number,
      outcome: outcomeText(text(attempt.outcome)),
      why: runDiagnosticText(
        typeof attempt.diagnostic_code === "string"
          ? attempt.diagnostic_code
          : null,
      ),
    };
  });
  return {
    attempts,
    items,
    counts: [...counts.entries()].map(
      ([outcome, count]) => `${outcomeText(outcome)} ${String(count)}`,
    ),
  };
}

export function RunDiagnostics({ run }: { run: BillingRun }) {
  const diagnostics = runDiagnostics(run);
  return (
    <section aria-label="Run diagnostics">
      <h5>Run diagnostics</h5>
      {diagnostics.attempts.length === 0 ? (
        <p>No attempt has been recorded for this run yet.</p>
      ) : (
        <>
          <p>
            {diagnostics.items.length === 0
              ? "No source items were recorded."
              : `Items: ${diagnostics.counts.join(", ")}.`}
          </p>
          <ul>
            {diagnostics.attempts.map((attempt) => (
              <li key={attempt.number}>
                Attempt {attempt.number}: {attempt.outcome}
                {attempt.why && ` — ${attempt.why}`}
              </li>
            ))}
          </ul>
          {diagnostics.items.length > 0 && (
            <div className="table-scroll">
              <table>
                <caption>Run item outcomes</caption>
                <thead>
                  <tr>
                    {["Attempt", "Source", "Period", "Outcome", "Why"].map(
                      (label) => (
                        <th key={label} scope="col">
                          {label}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {diagnostics.items.map((item, index) => (
                    <tr key={index}>
                      <td>{item.attempt}</td>
                      <td>{item.source}</td>
                      <td>{item.period}</td>
                      <td>{item.outcome}</td>
                      <td>{item.why || "None"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
