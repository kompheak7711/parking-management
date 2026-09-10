import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  financialId,
  financialInteger,
  financialObject,
  type FinancialObject,
} from "./financialContracts";
import { financialMoney, financialUiError } from "./financialUi";
import {
  ENFORCEMENT_EVENTS,
  enforcementRows,
  enforcementValue,
  type EnforcementEvent,
} from "./leaseEnforcementContract";
import {
  useEnforcementDraft,
  useEnforcementRead,
  type EnforcementWorkflowProps,
} from "./leaseEnforcementUi";
import {
  EnforcementFacts,
  EnforcementReadStatus,
} from "./LeaseEnforcementEvidence";

export function RentNonpaymentWorkspace(props: EnforcementWorkflowProps) {
  const id = useId(),
    [offset, setOffset] = useState(0),
    [cursor, setCursor] = useState<string | undefined>(),
    [selected, setSelected] = useState("");
  const dirtyForms = useRef(new Set<string>());
  const notify = props.onDirty;
  const dirty = useMemo(
    () =>
      Object.fromEntries(
        ["open", "event"].map((name) => [
          name,
          (value: boolean) => {
            if (value) dirtyForms.current.add(name);
            else dirtyForms.current.delete(name);
            notify(dirtyForms.current.size > 0);
          },
        ]),
      ) as Record<"open" | "event", (value: boolean) => void>,
    [notify],
  );
  const readable = props.capabilities["rent_nonpayment.read"],
    postable = props.capabilities["rent_nonpayment.event_post"];
  const cases = useEnforcementRead(
    props.scope,
    readable
      ? { kind: "cases", leaseId: props.leaseId, limit: 25, offset }
      : postable
        ? {
            kind: "actionCases",
            leaseId: props.leaseId,
            limit: 25,
            ...(cursor ? { cursor } : {}),
          }
        : null,
    props.revision,
    props.services,
  );
  const rows = enforcementRows(cases.data);
  const selection = rows.find((row) => row.id === selected);
  function changePage(next: () => void) {
    if (!props.busy && props.confirmDiscard()) {
      setSelected("");
      next();
    }
  }
  return (
    <section aria-label="Rent nonpayment cases">
      <h4>Rent nonpayment</h4>
      <p>
        Each case belongs to one issued Rent line. Eligibility and remaining
        Rent are calculated by the server. Recording an event does not terminate
        a Lease or move a Customer out.
      </p>
      {(readable || postable) && (
        <>
          <EnforcementReadStatus {...cases} />
          <label htmlFor={`${id}-case`}>
            {readable
              ? "Recorded Rent case"
              : "Rent case available for an event"}
          </label>
          <select
            id={`${id}-case`}
            disabled={props.busy || cases.busy}
            value={selection ? selected : ""}
            onChange={(e) => {
              if (props.confirmDiscard()) setSelected(e.target.value);
            }}
          >
            <option value="">Select a Rent case</option>
            {rows.map((row) => (
              <option key={financialId(row.id)} value={financialId(row.id)}>
                Due {enforcementValue(row.due_date_snapshot)} · Rent line{" "}
                {enforcementValue(row.rent_invoice_line_id)}
              </option>
            ))}
          </select>
          {cases.data && (
            <div className="button-row">
              <button
                type="button"
                disabled={
                  props.busy ||
                  cases.busy ||
                  (offset === 0 && cursor === undefined)
                }
                onClick={() => {
                  changePage(() => {
                    setOffset(0);
                    setCursor(undefined);
                  });
                }}
              >
                First case page
              </button>
              <button
                type="button"
                disabled={
                  props.busy ||
                  cases.busy ||
                  (readable
                    ? BigInt(financialInteger(cases.data.total)) <=
                      BigInt(offset + 25)
                    : cases.data.next_cursor === null)
                }
                onClick={() => {
                  changePage(() => {
                    if (readable) setOffset(offset + 25);
                    else setCursor(financialId(cases.data?.next_cursor));
                  });
                }}
              >
                Next case page
              </button>
            </div>
          )}
          {cases.data && rows.length === 0 && (
            <p>No Rent cases on this page.</p>
          )}
          {selection && (
            <CaseWorkspace
              key={`${selected}:${String(props.revision)}`}
              {...props}
              caseId={selected}
              onDirty={dirty.event}
            />
          )}
        </>
      )}
      {props.capabilities["rent_nonpayment.case_manage"] && (
        <OpenCaseWorkspace {...props} onDirty={dirty.open} />
      )}
    </section>
  );
}
function OpenCaseWorkspace(props: EnforcementWorkflowProps) {
  const id = useId(),
    [cursor, setCursor] = useState<string | undefined>(),
    [selected, setSelected] = useState(""),
    [reason, setReason] = useState(""),
    [error, setError] = useState<string | null>(null);
  const sources = useEnforcementRead(
    props.scope,
    {
      kind: "sources",
      leaseId: props.leaseId,
      limit: 25,
      ...(cursor ? { cursor } : {}),
    },
    props.revision,
    props.services,
  );
  const rows = enforcementRows(sources.data),
    source = rows.find((row) => row.rent_invoice_line_id === selected);
  useEnforcementDraft(reason !== "", props.onDirty);
  const recorded = useCallback(() => {
    setReason("");
    setSelected("");
  }, []);
  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!source || !props.ready || props.busy) return;
    try {
      props.review(
        {
          operation: "rentNonpaymentOpen",
          target: { id: props.leaseId },
          body: {
            rent_invoice_line_id: financialId(source.rent_invoice_line_id),
            reason,
          },
        },
        source,
        recorded,
      );
    } catch (failure) {
      setError(financialUiError(failure));
    }
  }
  return (
    <section aria-label="Open Rent nonpayment case">
      <h5>Open a Rent case</h5>
      <EnforcementReadStatus {...sources} />
      <label htmlFor={`${id}-source`}>Issued Rent line without a case</label>
      <select
        id={`${id}-source`}
        value={source ? selected : ""}
        disabled={props.busy || sources.busy}
        onChange={(e) => {
          setSelected(e.target.value);
          setError(null);
        }}
      >
        <option value="">Select an issued Rent line</option>
        {rows.map((row) => (
          <option
            key={financialId(row.rent_invoice_line_id)}
            value={financialId(row.rent_invoice_line_id)}
          >
            {enforcementValue(row.invoice_number)} · due{" "}
            {enforcementValue(row.due_date)} ·{" "}
            {financialMoney(
              financialObject(financialObject(row.assessment).remaining_rent)
                .minor_units,
            )}
          </option>
        ))}
      </select>
      {sources.data && (
        <div className="button-row">
          <button
            type="button"
            disabled={props.busy || sources.busy || cursor === undefined}
            onClick={() => {
              if (props.confirmDiscard()) {
                setSelected("");
                setReason("");
                setCursor(undefined);
              }
            }}
          >
            First Rent source page
          </button>
          <button
            type="button"
            disabled={
              props.busy || sources.busy || sources.data.next_cursor === null
            }
            onClick={() => {
              if (props.confirmDiscard()) {
                setSelected("");
                setReason("");
                setCursor(financialId(sources.data?.next_cursor));
              }
            }}
          >
            Next Rent source page
          </button>
        </div>
      )}
      {sources.data && rows.length === 0 && (
        <p>No applicable Rent lines without a case on this page.</p>
      )}
      {source && <EnforcementFacts value={source} current />}
      <form onSubmit={submit} aria-label="Open selected Rent case">
        <fieldset disabled={!source || !props.ready || props.busy}>
          <label htmlFor={`${id}-reason`}>Reason for opening case</label>
          <textarea
            id={`${id}-reason`}
            required
            maxLength={500}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <button type="submit">Review Rent case opening</button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
function CaseWorkspace(props: EnforcementWorkflowProps & { caseId: string }) {
  const readable = props.capabilities["rent_nonpayment.read"];
  const record = useEnforcementRead(
    props.scope,
    { kind: readable ? "case" : "eventContext", caseId: props.caseId },
    props.revision,
    props.services,
  );
  const [offset, setOffset] = useState(0);
  const events = useEnforcementRead(
    props.scope,
    readable
      ? { kind: "events", caseId: props.caseId, limit: 25, offset }
      : null,
    props.revision,
    props.services,
  );
  // A case selected under this Lease must remain bound to it even with an injected reader.
  const data = record.data?.lease_id === props.leaseId ? record.data : null;
  return (
    <section aria-label="Selected Rent case">
      <h5>Selected Rent case</h5>
      <EnforcementReadStatus {...record} />
      {record.data && !data && (
        <p role="alert">This case does not belong to the selected Lease.</p>
      )}
      {data && <EnforcementFacts value={data} current />}
      {readable && (
        <>
          <h5>Recorded nonpayment events</h5>
          <EnforcementReadStatus {...events} />
          {events.data && (
            <>
              {enforcementRows(events.data).length === 0 && (
                <p>No events on this page.</p>
              )}
              {enforcementRows(events.data).map((row) => (
                <article className="information-card" key={financialId(row.id)}>
                  <EnforcementFacts value={row} />
                </article>
              ))}
              <button
                type="button"
                disabled={events.busy || offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - 25));
                }}
              >
                Previous events
              </button>
              <button
                type="button"
                disabled={
                  events.busy ||
                  BigInt(financialInteger(events.data.total)) <=
                    BigInt(offset + 25)
                }
                onClick={() => {
                  setOffset(offset + 25);
                }}
              >
                Next events
              </button>
            </>
          )}
        </>
      )}
      {data && props.capabilities["rent_nonpayment.event_post"] && (
        <EventForm {...props} source={data} />
      )}
    </section>
  );
}
function EventForm(
  props: EnforcementWorkflowProps & { caseId: string; source: FinancialObject },
) {
  const id = useId(),
    [kind, setKind] = useState<EnforcementEvent | "">(""),
    [reason, setReason] = useState(""),
    [notice, setNotice] = useState(""),
    [communication, setCommunication] = useState(""),
    [authorization, setAuthorization] = useState(""),
    [error, setError] = useState<string | null>(null);
  const assessment = financialObject(props.source.assessment);
  const eligible: Record<EnforcementEvent, boolean> = {
    TWENTY_DAY_WARNING: assessment.twenty_day_warning_eligible === true,
    THIRTY_DAY_SERIOUS_DEFAULT: assessment.thirty_day_default_eligible === true,
    CURE: assessment.cure_eligible === true,
    AUTHORIZED_FOLLOW_UP: true,
  };
  useEnforcementDraft(
    kind !== "" ||
      reason !== "" ||
      notice !== "" ||
      communication !== "" ||
      authorization !== "",
    props.onDirty,
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!kind || !eligible[kind] || !props.ready || props.busy) return;
    try {
      props.review(
        {
          operation: "rentNonpaymentEvent",
          target: { id: props.caseId },
          body: {
            event_kind: kind,
            reason,
            ...(kind === "TWENTY_DAY_WARNING"
              ? { notice_document_reference: notice }
              : {}),
            ...(communication ? { communication_record: communication } : {}),
            ...(kind === "AUTHORIZED_FOLLOW_UP"
              ? { authorization_reference: authorization }
              : {}),
          },
        },
        props.source,
        () => {
          setKind("");
          setReason("");
          setNotice("");
          setCommunication("");
          setAuthorization("");
        },
      );
    } catch (failure) {
      setError(financialUiError(failure));
    }
  }
  return (
    <form onSubmit={submit} aria-label="Record Rent nonpayment event">
      <h5>Record an explicit event</h5>
      <p>
        An authorized follow-up requires an authorization reference. It
        preserves the case history even when its Invoice has been voided.
      </p>
      <fieldset disabled={!props.ready || props.busy}>
        <label htmlFor={`${id}-kind`}>Nonpayment event</label>
        <select
          id={`${id}-kind`}
          value={kind}
          required
          onChange={(e) => {
            setKind(e.target.value as EnforcementEvent | "");
            setError(null);
          }}
        >
          <option value="">Select an eligible event</option>
          {Object.entries(ENFORCEMENT_EVENTS).map(([value, label]) => (
            <option
              key={value}
              value={value}
              disabled={!eligible[value as EnforcementEvent]}
            >
              {label}
              {eligible[value as EnforcementEvent]
                ? ""
                : " (currently ineligible)"}
            </option>
          ))}
        </select>
        {kind === "TWENTY_DAY_WARNING" && (
          <>
            <label htmlFor={`${id}-notice`}>
              Warning Notice document reference
            </label>
            <input
              id={`${id}-notice`}
              required
              maxLength={500}
              value={notice}
              onChange={(e) => {
                setNotice(e.target.value);
              }}
            />
          </>
        )}
        {kind === "AUTHORIZED_FOLLOW_UP" && (
          <>
            <label htmlFor={`${id}-authorization`}>
              Authorization reference
            </label>
            <input
              id={`${id}-authorization`}
              required
              maxLength={500}
              value={authorization}
              onChange={(e) => {
                setAuthorization(e.target.value);
              }}
            />
          </>
        )}
        <label htmlFor={`${id}-communication`}>
          Communication record (optional)
        </label>
        <textarea
          id={`${id}-communication`}
          maxLength={2000}
          value={communication}
          onChange={(e) => {
            setCommunication(e.target.value);
          }}
        />
        <label htmlFor={`${id}-reason`}>Reason for nonpayment event</label>
        <textarea
          id={`${id}-reason`}
          required
          maxLength={500}
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
        />
        <button type="submit" disabled={!kind || !eligible[kind]}>
          Review nonpayment event
        </button>
      </fieldset>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
