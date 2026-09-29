import { useState } from "react";
import { FinancialClientError, type FinancialScope } from "./financialClient";
import { financialObject, type FinancialObject } from "./financialContracts";
import type { FinancialDueSourcesInput } from "./financialDueSources";
import { loadFinancialDueSources } from "./financialDueSourcesLoader";
import {
  dueAmountText,
  dueSourceKey,
  selectedDueSources,
  type FinancialDueSelection,
} from "./financialDueSelection";
import { financialReferenceClient } from "./financialReferenceClient";
import {
  financialLabel,
  financialMoney,
  financialTimestamp,
  financialUiError,
} from "./financialUi";
import { useFinancialTask } from "./financialUiContext";

interface Origin {
  scope: FinancialScope;
  input: FinancialDueSourcesInput;
}
function sameOrigin(
  origin: Origin,
  scope: FinancialScope,
  input: FinancialDueSourcesInput,
): boolean {
  return (
    origin.scope.actorId === scope.actorId &&
    origin.scope.propertyId === scope.propertyId &&
    origin.scope.signal === scope.signal &&
    !scope.signal.aborted &&
    Object.is(origin.input.operation, input.operation) &&
    origin.input.purpose === input.purpose &&
    origin.input.source_id === input.source_id &&
    origin.input.invoice_id === input.invoice_id &&
    origin.input.invoice_line_id === input.invoice_line_id &&
    (origin.input.limit ?? 50) === (input.limit ?? 50) &&
    origin.input.cursor === input.cursor
  );
}
function snapshot(
  scope: FinancialScope,
  input: FinancialDueSourcesInput,
): Origin {
  return { scope: { ...scope }, input: { ...input } };
}

/** One bounded editor; applying chooses source parts but never posts a command. */
export function FinancialDueSourcePicker({
  scope,
  input,
  initial,
  references = financialReferenceClient,
  onDirty,
  onApply,
  onDiscard,
}: {
  scope: FinancialScope;
  input: FinancialDueSourcesInput;
  initial?: FinancialDueSelection;
  references?: Pick<typeof financialReferenceClient, "read">;
  onDirty: () => void;
  onApply: (selection: FinancialDueSelection) => void;
  onDiscard: () => void;
}) {
  const task = useFinancialTask(scope);
  const [loaded, setLoaded] = useState<{
    origin: Origin;
    data: FinancialObject;
  } | null>(null);
  const [draft, setDraft] = useState(() => ({
    origin: snapshot(scope, input),
    values: Object.fromEntries(
      (initial?.parts ?? []).map(
        (part) =>
          [dueSourceKey(part), dueAmountText(part.amount_usd_cents)] as const,
      ),
    ),
  }));
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const data =
    loaded && sameOrigin(loaded.origin, scope, input) ? loaded.data : null;
  const values: Record<string, string> = sameOrigin(draft.origin, scope, input)
    ? draft.values
    : {};
  const rows =
    data && Array.isArray(data.items) ? data.items.map(financialObject) : [];
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(rows.length / 50) - 1),
  );
  function load() {
    const origin = snapshot(scope, input);
    setLoaded(null);
    setError(null);
    setPage(0);
    void task.run(
      async (current) => ({
        origin,
        data: await loadFinancialDueSources(current, origin.input, references),
      }),
      setLoaded,
    );
  }
  function edit(key: string, value: string) {
    task.cancel();
    setError(null);
    onDirty();
    setDraft({
      origin: snapshot(scope, input),
      values: { ...values, [key]: value },
    });
  }
  return (
    <section
      aria-label={`Choose dated sources for Invoice line ${input.invoice_line_id}`}
    >
      <h4>Choose dated sources for this Invoice line</h4>
      <p>
        Select only the amounts the Customer designated. Apply or discard these
        edits before reviewing the financial action. The server will recheck
        them in the confirmation preview.
      </p>
      <button
        type="button"
        disabled={task.busy || scope.signal.aborted}
        onClick={load}
      >
        Load approved dated amounts
      </button>
      {task.busy && <p role="status">Loading approved dated amounts…</p>}
      {(error ?? task.error) && <p role="alert">{error ?? task.error}</p>}
      {data && rows.length === 0 && (
        <p>No unpaid dated amounts remain for this line.</p>
      )}
      {data && rows.length > 0 && (
        <div className="financial-table-scroll">
          <table>
            <caption>
              Available dated sources · {rows.length} loaded · page{" "}
              {currentPage + 1}
            </caption>
            <thead>
              <tr>
                <th>Source</th>
                <th>Approved due date</th>
                <th>Source recorded at</th>
                <th>Remaining USD</th>
                <th>Selected USD</th>
              </tr>
            </thead>
            <tbody>
              {rows
                .slice(currentPage * 50, currentPage * 50 + 50)
                .map((row) => {
                  const key = dueSourceKey(row);
                  return (
                    <tr key={key}>
                      <td>
                        {row.source_kind === "ORIGINAL_LINE"
                          ? "Original Invoice line"
                          : "Debit Adjustment"}
                        <br />
                        {financialLabel(row.source_id)}
                      </td>
                      <td>{financialLabel(row.approved_due_date)}</td>
                      <td>{financialTimestamp(row.source_occurred_at)}</td>
                      <td>{financialMoney(row.remaining_usd_cents)}</td>
                      <td>
                        <label>
                          Selected USD for dated source {key}
                          <input
                            inputMode="decimal"
                            value={values[key] ?? ""}
                            onChange={(event) => {
                              edit(key, event.target.value);
                            }}
                          />
                        </label>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
          {rows.length > 50 && (
            <div className="button-row">
              <button
                type="button"
                disabled={currentPage === 0}
                onClick={() => {
                  setPage(currentPage - 1);
                }}
              >
                Previous dated sources
              </button>
              <button
                type="button"
                disabled={(currentPage + 1) * 50 >= rows.length}
                onClick={() => {
                  setPage(currentPage + 1);
                }}
              >
                Next dated sources
              </button>
            </div>
          )}
        </div>
      )}
      <div className="button-row">
        <button
          type="button"
          disabled={task.busy || data === null}
          onClick={() => {
            try {
              if (
                data === null ||
                loaded === null ||
                !sameOrigin(loaded.origin, scope, input)
              )
                throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
              onApply(selectedDueSources(data, values));
              setError(null);
            } catch (failure) {
              setError(financialUiError(failure));
            }
          }}
        >
          Use selected dated amounts
        </button>
        <button
          type="button"
          disabled={task.busy || data === null}
          onClick={() => {
            task.cancel();
            setError(null);
            onDirty();
            setDraft({ origin: snapshot(scope, input), values: {} });
          }}
        >
          Clear dated selections
        </button>
        <button
          type="button"
          onClick={() => {
            task.cancel();
            onDiscard();
          }}
        >
          Discard source edits
        </button>
      </div>
    </section>
  );
}
