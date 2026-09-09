import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  customerLedgerClient,
  CustomerLedgerError,
  LEDGER_EVENTS,
  type CustomerLedgerApi,
  type LedgerCursor,
  type LedgerCustomerPage,
  type LedgerEventKind,
  type LedgerFilters,
  type LedgerHistory,
  type LedgerPage,
  type LedgerReply,
  type LedgerRequest,
} from "./customerLedgerClient";
import {
  LedgerComponentTable,
  LedgerCompositionTable,
  LedgerEventEvidence,
  LedgerHistoryTable,
  LedgerPositionSummary,
} from "./CustomerLedgerEvidence";

export interface LedgerSelection {
  customerId: string;
  propertyId: string;
}
export interface CustomerAccountLedgerProps {
  actorId: string;
  api?: CustomerLedgerApi;
  requested?: LedgerSelection & { sequence: number };
}
interface Context {
  actorId: string;
  api: CustomerLedgerApi;
  propertyId?: string;
}
function errorText(error: unknown): string {
  if (error instanceof CustomerLedgerError) {
    if (error.status === 409)
      return "Financial records changed. Refresh the whole account to continue with one current view.";
    if (error.status === 401)
      return "Sign in again to view this Customer ledger.";
    if (error.status === 403)
      return "You do not have permission to read this Customer ledger.";
    if (error.status === 404)
      return "This Customer ledger is not available in your Property.";
    if (
      error.code === "INVALID_RESPONSE" ||
      error.code === "RESPONSE_TOO_LARGE"
    )
      return "The ledger response could not be verified. No unverified financial information is displayed.";
  }
  return "The Customer ledger is temporarily unavailable. Try again.";
}
function Failure({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <div role="alert">
      <p>{errorText(error)}</p>
      {error instanceof CustomerLedgerError && error.requestId && (
        <p>Request reference: {error.requestId}</p>
      )}
      <button type="button" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
// Every request component owns its abort signal and an epoch guard. Its keyed
// parent removes obsolete payloads synchronously when any selection changes.
function Read({
  context,
  request,
  children,
  onConflict,
}: {
  context: Context;
  request: LedgerRequest;
  children: (reply: LedgerReply) => React.ReactNode;
  onConflict?: (error: unknown) => void;
}) {
  const [result, setResult] = useState<{
    key: object;
    api: CustomerLedgerApi;
    actorId: string;
    propertyId?: string;
    reply?: LedgerReply;
    error?: unknown;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void context.api
      .read(request, {
        actorId: context.actorId,
        propertyId: context.propertyId,
        signal: controller.signal,
      })
      .then((reply) => {
        if (active && !controller.signal.aborted)
          setResult({
            key: request,
            api: context.api,
            actorId: context.actorId,
            propertyId: context.propertyId,
            reply,
          });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        if (
          error instanceof CustomerLedgerError &&
          [401, 403, 404, 409].includes(error.status ?? 0) &&
          onConflict
        )
          onConflict(error);
        else
          setResult({
            key: request,
            api: context.api,
            actorId: context.actorId,
            propertyId: context.propertyId,
            error,
          });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [
    context.api,
    context.actorId,
    context.propertyId,
    request,
    attempt,
    onConflict,
  ]);
  if (
    !result ||
    result.key !== request ||
    result.api !== context.api ||
    result.actorId !== context.actorId ||
    result.propertyId !== context.propertyId
  )
    return <p role="status">Loading Customer ledger…</p>;
  if (result.reply) return children(result.reply);
  return (
    <Failure
      error={result.error}
      retry={() => {
        setResult(null);
        setAttempt((a) => a + 1);
      }}
    />
  );
}
function Pager({
  next,
  previous,
  page,
}: {
  next?: () => void;
  previous?: () => void;
  page: number;
}) {
  return (
    <nav aria-label="Ledger page controls">
      <button type="button" disabled={!previous} onClick={previous}>
        Previous page
      </button>
      <span> Page {page} </span>
      <button type="button" disabled={!next} onClick={next}>
        Next page
      </button>
    </nav>
  );
}
function Picker({
  context,
  choose,
}: {
  context: Context;
  choose: (selection: LedgerSelection) => void;
}) {
  const [paging, setPaging] = useState<{
    propertyId?: string;
    cursors: (LedgerCursor | undefined)[];
    index: number;
  }>({ cursors: [undefined], index: 0 });
  const [request, setRequest] = useState<LedgerRequest>({
    section: "customers",
  });
  const go = (
    index: number,
    reply: LedgerCustomerPage,
    cursor?: LedgerCursor,
  ) => {
    const cursors = cursor
      ? [...paging.cursors.slice(0, index), cursor]
      : paging.cursors;
    setPaging({ propertyId: reply.propertyId, cursors, index });
    setRequest({ section: "customers", cursor: cursors[index] });
  };
  return (
    <Read
      context={{ ...context, propertyId: paging.propertyId }}
      request={request}
    >
      {(reply) =>
        reply.section !== "customers" ? (
          <p role="alert">The Customer list could not be verified.</p>
        ) : (
          <>
            <p>
              Choose a Customer to read their account. This list uses your
              separate ledger permission.
            </p>
            {reply.items.length === 0 ? (
              <p>No Customers are available on this page.</p>
            ) : (
              <ul>
                {reply.items.map((customer) => (
                  <li key={customer.id}>
                    <button
                      type="button"
                      onClick={() => {
                        choose({
                          customerId: customer.id,
                          propertyId: reply.propertyId,
                        });
                      }}
                    >
                      {customer.legal_name || "Unnamed Customer"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <Pager
              page={paging.index + 1}
              previous={
                paging.index
                  ? () => {
                      go(paging.index - 1, reply);
                    }
                  : undefined
              }
              next={
                reply.nextCursor
                  ? () => {
                      go(
                        paging.index + 1,
                        reply,
                        reply.nextCursor ?? undefined,
                      );
                    }
                  : undefined
              }
            />
          </>
        )
      }
    </Read>
  );
}
function Pages({
  context,
  first,
  request: initialRequest,
  render,
  onConflict,
}: {
  context: Context;
  first?: LedgerPage;
  request: LedgerRequest;
  render: (reply: LedgerPage) => React.ReactNode;
  onConflict: (error: unknown) => void;
}) {
  const [paging, setPaging] = useState<{
    cursors: (LedgerCursor | undefined)[];
    index: number;
    request: LedgerRequest;
  }>({ cursors: [undefined], index: 0, request: initialRequest });
  const content = (reply: LedgerReply) => {
    if (
      reply.section === "customers" ||
      reply.section !== initialRequest.section
    )
      return <p role="alert">The ledger section could not be verified.</p>;
    const go = (index: number, cursor?: LedgerCursor) => {
      const cursors = cursor
        ? [...paging.cursors.slice(0, index), cursor]
        : paging.cursors;
      setPaging({
        cursors,
        index,
        request: { ...initialRequest, cursor: cursors[index] },
      });
    };
    return (
      <>
        {render(reply)}
        <Pager
          page={paging.index + 1}
          previous={
            paging.index
              ? () => {
                  go(paging.index - 1);
                }
              : undefined
          }
          next={
            reply.nextCursor
              ? () => {
                  go(paging.index + 1, reply.nextCursor ?? undefined);
                }
              : undefined
          }
        />
      </>
    );
  };
  return first && paging.index === 0 ? (
    content(first)
  ) : (
    <Read context={context} request={paging.request} onConflict={onConflict}>
      {content}
    </Read>
  );
}
function Source({
  row,
  account,
  context,
  onConflict,
  close,
}: {
  row: LedgerHistory;
  account: LedgerPage;
  context: Context;
  onConflict: (error: unknown) => void;
  close: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [request] = useState<LedgerRequest>({
    section: "components",
    customerId: account.customerId,
    snapshot: account.snapshot,
    eventKind: row.event_kind,
    eventId: row.event_id,
    source: row,
  });
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section
      id="account-ledger-source"
      aria-labelledby="account-ledger-source-heading"
    >
      <h5 id="account-ledger-source-heading" ref={heading} tabIndex={-1}>
        Source details: {LEDGER_EVENTS[row.event_kind][1]}
      </h5>
      <button type="button" onClick={close}>
        Close source details
      </button>
      <LedgerEventEvidence row={row} />
      <p>{row.component_count} source component(s) in this event.</p>
      <Pages
        context={context}
        request={request}
        onConflict={onConflict}
        render={(reply) =>
          reply.section === "components" ? (
            <LedgerComponentTable rows={reply.items} />
          ) : null
        }
      />
    </section>
  );
}
function AccountData({
  account,
  context,
  filters,
  onConflict,
}: {
  account: LedgerPage;
  context: Context;
  filters: LedgerFilters;
  onConflict: (error: unknown) => void;
}) {
  const [section, setSection] = useState<"history" | "composition">("history");
  const [source, setSource] = useState<LedgerHistory | null>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [historyRequest] = useState<LedgerRequest>({
    section: "history",
    customerId: account.customerId,
    snapshot: account.snapshot,
    filters,
  });
  const [compositionRequest] = useState<LedgerRequest>({
    section: "composition",
    customerId: account.customerId,
    snapshot: account.snapshot,
  });
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <>
      <h4 ref={heading} tabIndex={-1}>
        Account: {account.customerName || "Unnamed Customer"}
      </h4>
      <LedgerPositionSummary position={account.position} />
      <p>
        Credit, unallocated Payment and deposits remain separate. They reduce
        obligations only through a recorded application.
      </p>
      <div>
        <button
          type="button"
          aria-pressed={section === "history"}
          onClick={() => {
            setSection("history");
            setSource(null);
          }}
        >
          Financial history
        </button>
        <button
          type="button"
          aria-pressed={section === "composition"}
          onClick={() => {
            setSection("composition");
            setSource(null);
          }}
        >
          Balance composition
        </button>
      </div>
      {section === "history" ? (
        <>
          <p>
            {account.eventCount} event(s) in the complete account. Filters
            select displayed events; resulting balances include the full
            history. Events at the same instant share the position after all
            events at that instant.
          </p>
          <Pages
            key="history"
            context={context}
            first={account}
            request={historyRequest}
            onConflict={onConflict}
            render={(reply) =>
              reply.section === "history" ? (
                <>
                  {reply.items.length === 0 ? (
                    <p>
                      {account.eventCount === 0
                        ? "This Customer has no recorded financial events."
                        : "No financial events match these filters on this page."}
                    </p>
                  ) : (
                    <LedgerHistoryTable
                      rows={reply.items}
                      openSource={(row) => {
                        sourceTrigger.current =
                          document.activeElement as HTMLElement;
                        setSource(row);
                      }}
                    />
                  )}
                </>
              ) : null
            }
          />
        </>
      ) : (
        <>
          <p>
            Remaining amounts are grouped by authoritative source. A page may
            show only part of the composition; account totals above cover the
            whole account.
          </p>
          <Pages
            key="composition"
            context={context}
            request={compositionRequest}
            onConflict={onConflict}
            render={(reply) =>
              reply.section === "composition" ? (
                reply.items.length ? (
                  <LedgerCompositionTable rows={reply.items} />
                ) : (
                  <p>No remaining balances on this composition page.</p>
                )
              ) : null
            }
          />
        </>
      )}
      {source && (
        <Source
          key={`${source.event_kind}:${source.event_id}`}
          row={source}
          account={account}
          context={context}
          onConflict={onConflict}
          close={() => {
            setSource(null);
            sourceTrigger.current?.focus();
          }}
        />
      )}
    </>
  );
}
function Snapshot({
  context,
  selection,
  filters,
}: {
  context: Context;
  selection: LedgerSelection;
  filters: LedgerFilters;
}) {
  const [request] = useState<LedgerRequest>({
    section: "history",
    customerId: selection.customerId,
    filters,
  });
  const [conflict, setConflict] = useState<{ error: unknown } | null>(null);
  // Stable callback avoids restarting an in-flight read on presentation changes.
  const [onConflict] = useState(() => (error: unknown) => {
    setConflict({ error });
  });
  if (conflict) return <p role="alert">{errorText(conflict.error)}</p>;
  return (
    <Read context={context} request={request} onConflict={onConflict}>
      {(reply) =>
        reply.section === "history" ? (
          <AccountData
            account={reply}
            context={context}
            filters={filters}
            onConflict={onConflict}
          />
        ) : (
          <p role="alert">The account could not be verified.</p>
        )
      }
    </Read>
  );
}
function Account({
  context,
  selection,
}: {
  context: Context;
  selection: LedgerSelection;
}) {
  const [applied, setApplied] = useState<{
    filters: LedgerFilters;
    sequence: number;
  }>({ filters: {}, sequence: 0 });
  const [formError, setFormError] = useState<string | null>(null);
  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const fromValue = form.get("from"),
      throughValue = form.get("through"),
      kindValue = form.get("kind");
    const from = typeof fromValue === "string" ? fromValue : "",
      through = typeof throughValue === "string" ? throughValue : "",
      kind = typeof kindValue === "string" ? kindValue : "";
    if (from && through && from > through) {
      setFormError("The start date must be on or before the end date.");
      return;
    }
    setFormError(null);
    setApplied((current) => ({
      sequence: current.sequence + 1,
      filters: {
        ...(from ? { from: `${from}T00:00:00Z` } : {}),
        ...(through ? { through: `${through}T23:59:59.999999Z` } : {}),
        ...(kind ? { kind: kind as LedgerEventKind } : {}),
      },
    }));
  };
  return (
    <>
      <form onSubmit={apply} className="ledger-filters">
        <fieldset>
          <legend>Filter financial history by UTC event date</legend>
          <label>
            From date
            <input type="date" name="from" min="0001-01-01" max="9999-12-31" />
          </label>
          <label>
            Through date
            <input
              type="date"
              name="through"
              min="0001-01-01"
              max="9999-12-31"
            />
          </label>
          <label>
            Event kind
            <select name="kind">
              <option value="">All event kinds</option>
              {Object.entries(LEDGER_EVENTS).map(([kind, [, label]]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Apply history filters</button>
          <button
            type="reset"
            onClick={() => {
              setFormError(null);
              setApplied((current) => ({
                filters: {},
                sequence: current.sequence + 1,
              }));
            }}
          >
            Clear filters
          </button>
        </fieldset>
      </form>
      {formError && <p role="alert">{formError}</p>}
      <button
        type="button"
        onClick={() => {
          setApplied((current) => ({
            ...current,
            sequence: current.sequence + 1,
          }));
        }}
      >
        Refresh whole account
      </button>
      <Snapshot
        key={applied.sequence}
        context={{ ...context, propertyId: selection.propertyId }}
        selection={selection}
        filters={applied.filters}
      />
    </>
  );
}
function Entry({
  actorId,
  api,
  requested,
}: CustomerAccountLedgerProps & { api: CustomerLedgerApi }) {
  const [opened, setOpened] = useState(Boolean(requested));
  const [selection, setSelection] = useState<LedgerSelection | null>(
    requested ?? null,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  const context: Context = { actorId, api };
  useEffect(() => {
    if (opened) heading.current?.focus();
  }, [opened]);
  return (
    <section
      className="panel financial-management ledger-workspace"
      aria-labelledby="customer-account-ledger-heading"
    >
      <h3 id="customer-account-ledger-heading" tabIndex={-1} ref={heading}>
        Customer account ledger
      </h3>
      {!opened ? (
        <button
          type="button"
          onClick={() => {
            setOpened(true);
          }}
        >
          Open Customer account ledger
        </button>
      ) : (
        <>
          <p>Read-only financial history and current balances.</p>
          <button
            type="button"
            onClick={() => {
              setSelection(null);
              setOpened(false);
            }}
          >
            Close Customer ledger
          </button>
          {selection && (
            <button
              type="button"
              onClick={() => {
                setSelection(null);
              }}
            >
              Choose another Customer
            </button>
          )}
          {selection ? (
            <Account
              key={`${selection.propertyId}:${selection.customerId}`}
              context={context}
              selection={selection}
            />
          ) : (
            <Picker context={context} choose={setSelection} />
          )}
        </>
      )}
    </section>
  );
}
export function CustomerAccountLedger({
  actorId,
  api = customerLedgerClient,
  requested,
}: CustomerAccountLedgerProps) {
  return (
    <Entry
      key={`${actorId}:${requested?.propertyId ?? ""}:${requested?.customerId ?? ""}:${String(requested?.sequence ?? 0)}`}
      actorId={actorId}
      api={api}
      requested={requested}
    />
  );
}
