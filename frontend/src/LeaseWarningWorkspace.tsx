import { useId, useState, type FormEvent } from "react";
import {
  financialId,
  financialInteger,
  type FinancialObject,
} from "./financialContracts";
import { financialUiError } from "./financialUi";
import { enforcementRows, enforcementValue } from "./leaseEnforcementContract";
import {
  useEnforcementDraft,
  useEnforcementRead,
  type EnforcementWorkflowProps,
} from "./leaseEnforcementUi";
import {
  EnforcementFacts,
  EnforcementReadStatus,
} from "./LeaseEnforcementEvidence";

export function LeaseWarningWorkspace(props: EnforcementWorkflowProps) {
  const [offset, setOffset] = useState(0);
  const history = useEnforcementRead(
    props.scope,
    props.capabilities["leases.read"]
      ? { kind: "warnings", leaseId: props.leaseId, limit: 25, offset }
      : null,
    props.revision,
    props.services,
  );
  const context = useEnforcementRead(
    props.scope,
    props.capabilities["leases.warn"]
      ? { kind: "warningContext", leaseId: props.leaseId }
      : null,
    props.revision,
    props.services,
  );
  return (
    <section aria-label="Lease violation warnings">
      <h4>Lease violation warnings</h4>
      <p>
        Record the violation, Lease provision and communication as a general
        Lease warning. Rent nonpayment Notices are handled separately.
      </p>
      {props.capabilities["leases.read"] && (
        <>
          <h5>Recorded Lease warnings</h5>
          <EnforcementReadStatus {...history} />
          {history.data && (
            <>
              {enforcementRows(history.data).length === 0 && (
                <p>No warnings on this page.</p>
              )}
              {enforcementRows(history.data).map((row) => (
                <article className="information-card" key={financialId(row.id)}>
                  <EnforcementFacts value={row} />
                </article>
              ))}
              <p>
                {enforcementValue(history.data.total)} warnings in this Lease
                history.
              </p>
              <button
                type="button"
                disabled={offset === 0 || history.busy}
                onClick={() => {
                  setOffset(Math.max(0, offset - 25));
                }}
              >
                Previous warnings
              </button>
              <button
                type="button"
                disabled={
                  history.busy ||
                  BigInt(financialInteger(history.data.total)) <=
                    BigInt(offset + 25)
                }
                onClick={() => {
                  setOffset(offset + 25);
                }}
              >
                Next warnings
              </button>
            </>
          )}
        </>
      )}
      {props.capabilities["leases.warn"] && (
        <>
          <EnforcementReadStatus {...context} />
          <WarningForm {...props} context={context.data} />
        </>
      )}
    </section>
  );
}
function WarningForm(
  props: EnforcementWorkflowProps & { context: FinancialObject | null },
) {
  const id = useId();
  const defaults = {
    warning_sequence:
      props.context === null || props.context.suggested_sequence === null
        ? ""
        : enforcementValue(props.context.suggested_sequence),
    violation_date: "",
    warning_date:
      props.context === null
        ? ""
        : enforcementValue(props.context.business_date),
    violation_description: "",
    lease_provision: "",
    communication_record: "",
    reason: "",
  };
  const [draft, setValues] = useState<typeof defaults | null>(null);
  const values = draft ?? defaults;
  const [dirty, setDirty] = useState(false),
    [error, setError] = useState<string | null>(null);
  useEnforcementDraft(dirty, props.onDirty);
  const labels: Record<keyof typeof values, string> = {
    warning_sequence: "Warning sequence",
    violation_date: "Violation date",
    warning_date: "Warning date",
    violation_description: "Violation description",
    lease_provision: "Lease provision",
    communication_record: "Communication record",
    reason: "Reason for recording warning",
  };
  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!props.context || !props.ready || props.busy) return;
    try {
      if (!/^[1-9][0-9]{0,4}$/.test(values.warning_sequence)) throw new Error();
      props.review(
        {
          operation: "leaseWarningRecord",
          target: { id: props.leaseId },
          body: {
            ...values,
            warning_sequence: Number(values.warning_sequence),
          },
        },
        null,
        () => {
          setValues(null);
          setDirty(false);
        },
      );
    } catch (failure) {
      setError(financialUiError(failure));
    }
  }
  return (
    <form
      onSubmit={submit}
      aria-label="Record Lease warning"
      hidden={props.context === null && !dirty}
    >
      <h5>Record a Lease warning</h5>
      <p>
        Dates use the Property business calendar in Asia/Phnom_Penh. Review the
        suggested sequence before recording.
      </p>
      <fieldset disabled={!props.context || !props.ready || props.busy}>
        {Object.entries(labels).map(([key, label]) => (
          <div className="form-field" key={key}>
            <label htmlFor={`${id}-${key}`}>{label}</label>
            {key.endsWith("_date") || key === "warning_sequence" ? (
              <input
                id={`${id}-${key}`}
                type={key.endsWith("_date") ? "date" : "text"}
                inputMode={key === "warning_sequence" ? "numeric" : undefined}
                value={values[key as keyof typeof values]}
                required
                onChange={(e) => {
                  setDirty(true);
                  setValues({ ...values, [key]: e.target.value });
                }}
              />
            ) : (
              <textarea
                id={`${id}-${key}`}
                value={values[key as keyof typeof values]}
                required
                maxLength={key === "reason" ? 500 : 2000}
                onChange={(e) => {
                  setDirty(true);
                  setValues({ ...values, [key]: e.target.value });
                }}
              />
            )}
          </div>
        ))}
        <button type="submit">Review Lease warning</button>
      </fieldset>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
