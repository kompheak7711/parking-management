// V1-058 R7a: Waiting for approval (DESIGN.md "Waiting for approval", mock-up round 8): four
// cards that filter the list, the drafts that wait (oldest first), the rule notice and what was
// decided today. Open shows the draft and what confirming does; the Owner or a Manager
// (financial.approve) confirms or rejects, and the person who prepared it may withdraw it
// before anyone decides (owner, 24/10/2026). The server checks every rule again.

import "../shell/screens.css";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type SettlementApi,
  SettlementRequestError,
} from "../settlementClient";
import { momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, CountCard, Dialog } from "../shell/ui";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import {
  type ApprovalsApi,
  ApprovalsNotAllowedError,
  type WaitingDraft,
  type WaitingPage,
} from "./approvalsClient";
import { apt, draftEffect, draftLabel } from "./text";

export const FINANCIAL_APPROVE = "financial.approve";

export type DraftDecisionApi = Pick<
  SettlementApi,
  "confirmDraft" | "rejectDraft" | "withdrawDraft"
>;

export interface ApprovalsPageProps {
  language: Language;
  propertyId: string;
  /** The page reads again each time it is opened. */
  active: boolean;
  approvalsApi: ApprovalsApi;
  decisionApi: DraftDecisionApi;
  capabilities: ReadonlySet<string> | null;
  /** The person signed in: the one who prepared a draft may withdraw it. */
  actorId: string | null;
}

type Filter = "all" | "wait" | "out" | "kept" | "done";
type Step = "open" | "reject" | "withdraw";

function sum(drafts: WaitingDraft[]): number {
  return drafts.reduce(
    (total, draft) => total + (draft.summary.amount_usd_cents ?? 0),
    0,
  );
}

function amountText(draft: WaitingDraft): string {
  const cents = draft.summary.amount_usd_cents;
  return cents === null ? "—" : usdFromCents(cents);
}

function StateChip({
  language,
  draft,
}: {
  language: Language;
  draft: WaitingDraft;
}) {
  if (draft.state === "PENDING")
    return (
      <Chip icon="clock" tone="warn">
        {apt(language, "ap_wait_chip")}
      </Chip>
    );
  if (draft.state === "CONFIRMED")
    return (
      <Chip icon="check" tone="ok">
        {apt(language, "ap_st_ok")}
      </Chip>
    );
  return (
    <Chip icon="x" tone="neutral">
      {apt(language, draft.state === "WITHDRAWN" ? "ap_st_wdr" : "ap_st_rej")}
    </Chip>
  );
}

function UnitLink({ draft }: { draft: WaitingDraft }) {
  const { unit_id, unit_number } = draft.summary;
  if (unit_id === null || unit_number === null) return null;
  return (
    <a className="ui-no ui-num" href={hashForPage("units", unit_id)}>
      {unit_number}
    </a>
  );
}

function DraftFacts({
  language,
  draft,
}: {
  language: Language;
  draft: WaitingDraft;
}) {
  const { summary } = draft;
  return (
    <dl className="ui-kv">
      <dt>{apt(language, "ap_col_for")}</dt>
      <dd>
        <UnitLink draft={draft} />
        {summary.unit_number !== null && summary.customer_name !== null && (
          <> · </>
        )}
        {summary.customer_name}
        {summary.unit_number === null && summary.customer_name === null && (
          <>—</>
        )}
      </dd>
      <dt>{apt(language, "ap_col_amt")}</dt>
      <dd className="ui-num">{amountText(draft)}</dd>
      <dt>{apt(language, "ap_prepared")}</dt>
      <dd>
        {summary.prepared_by_name ?? "—"} ·{" "}
        <span className="ui-num">{momentText(draft.prepared_at)}</span>
      </dd>
      <dt>{apt(language, "ap_reason")}</dt>
      <dd className="note">{draft.reason}</dd>
      {summary.reservation_id !== null && (
        <>
          <dt>{apt(language, "df_res")}</dt>
          <dd>
            <a href={hashForPage("reservations", summary.reservation_id)}>
              {apt(language, "ap_open")}
            </a>
          </dd>
        </>
      )}
      {summary.lease_id !== null && (
        <>
          <dt>{apt(language, "df_lease")}</dt>
          <dd>
            <a href={hashForPage("leases", summary.lease_id)}>
              {apt(language, "ap_open")}
            </a>
          </dd>
        </>
      )}
    </dl>
  );
}

function decidedLine(language: Language, draft: WaitingDraft): string {
  const decision = draft.decision;
  if (decision === null) return "";
  const line = apt(
    language,
    "ap_by_at",
    draft.summary.decided_by_name ?? "—",
    momentText(decision.decided_at),
  );
  return decision.reason ? `${line} · ${decision.reason}` : line;
}

function ReasonDialog({
  language,
  draft,
  step,
  busy,
  problem,
  onClose,
  onSend,
}: {
  language: Language;
  draft: WaitingDraft;
  step: "reject" | "withdraw";
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSend: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const reject = step === "reject";
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === "") {
      setMissing(true);
      return;
    }
    onSend(reason.trim());
  }
  const title = apt(language, reject ? "ap_rej_t" : "ap_wdr_t");
  return (
    <Dialog
      busy={busy}
      closeLabel={apt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={apt(language, reject ? "ap_reject" : "ap_withdraw")}
      title={
        draft.summary.unit_number === null
          ? title
          : `${title} · ${draft.summary.unit_number}`
      }
    >
      <dl className="ui-kv">
        <dt>{apt(language, "ap_col_draft")}</dt>
        <dd>{draftLabel(language, draft)}</dd>
        <dt>{apt(language, "ap_col_amt")}</dt>
        <dd className="ui-num">{amountText(draft)}</dd>
        <dt>{apt(language, "ap_col_by")}</dt>
        <dd>{draft.summary.prepared_by_name ?? "—"}</dd>
      </dl>
      <div className="ui-field">
        <label htmlFor="draft-reason">
          {apt(language, reject ? "ap_rej_why" : "ap_wdr_why")}
          <span className="req">{apt(language, "required")}</span>
        </label>
        <textarea
          aria-describedby={missing ? "draft-reason-error" : undefined}
          aria-invalid={missing}
          id="draft-reason"
          maxLength={2000}
          onChange={(event) => {
            setReason(event.currentTarget.value);
            setMissing(false);
          }}
          rows={3}
          value={reason}
        />
        {missing && (
          <p className="ui-error" id="draft-reason-error" role="alert">
            <Icon name="alert" small />
            <span>{apt(language, reject ? "ap_rej_e" : "ap_wdr_e")}</span>
          </p>
        )}
      </div>
      <p className="ui-small ui-muted">
        {apt(language, reject ? "ap_rej_note" : "ap_wdr_note")}
      </p>
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
    </Dialog>
  );
}

export function ApprovalsPage({
  language,
  propertyId,
  active,
  approvalsApi,
  decisionApi,
  capabilities,
  actorId,
}: ApprovalsPageProps) {
  const mayApprove =
    capabilities === null || capabilities.has(FINANCIAL_APPROVE);
  const [page, setPage] = useState<WaitingPage | null>(null);
  const [readAt, setReadAt] = useState("");
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [opened, setOpened] = useState<{ id: string; step: Step } | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const sequence = useRef(0);
  // One key per decision on a draft, kept until it succeeds, so sending again after an answer
  // that did not come back cannot decide twice.
  const keys = useRef(new Map<string, string>());

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailure(null);
    approvalsApi
      .waiting(propertyId)
      .then((loaded) => {
        if (operation !== sequence.current) return;
        setPage(loaded);
        setReadAt(new Date().toISOString());
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        // An old list could offer a draft that someone has decided since.
        setPage(null);
        setFailure(
          error instanceof ApprovalsNotAllowedError ? "not_allowed" : "failed",
        );
      });
  }, [approvalsApi, propertyId]);

  // Another Property never shows the drafts of the one before, and a decision still on its
  // way for the one before reports nothing here.
  const shownProperty = useRef(propertyId);
  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    keys.current.clear();
    setPage(null);
    setFailure(null);
    setFilter("all");
    setOpened(null);
    setProblem(null);
    setToast(null);
  }, [propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (propertyId === "") return null;

  const head = (
    <div className="ui-head">
      <p>
        {apt(language, "ap_sub")}
        {page !== null && readAt !== "" && (
          <span className="ui-num">
            {" "}
            · {apt(language, "as_of", momentText(readAt).slice(11))}
          </span>
        )}
      </p>
    </div>
  );

  if (failure !== null) {
    return (
      <>
        {head}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{apt(language, failure)}</p>
          {failure === "failed" && (
            <button className="ui-btn" onClick={load} type="button">
              {apt(language, "retry")}
            </button>
          )}
        </div>
      </>
    );
  }
  if (page === null) {
    return (
      <>
        {head}
        <p className="ui-muted" role="status">
          {apt(language, "loading")}
        </p>
      </>
    );
  }

  const waiting = page.waiting;
  const out = waiting.filter((draft) => draft.summary.direction === "OUT");
  // Some refunds are worked out only at confirm, so they add nothing to the sum yet.
  const unknownOut = out.filter(
    (draft) => draft.summary.amount_usd_cents === null,
  ).length;
  const kept = waiting.filter((draft) => draft.summary.direction === "KEPT");
  const done = page.decided_today;
  const shown =
    filter === "out"
      ? out
      : filter === "kept"
        ? kept
        : filter === "done"
          ? done
          : waiting;
  const toggle = (next: Filter) => {
    setFilter(filter === next ? "all" : next);
  };
  const draft =
    opened === null
      ? undefined
      : [...waiting, ...done].find((item) => item.draft_id === opened.id);

  const close = () => {
    if (busy) return;
    setOpened(null);
    setProblem(null);
  };

  function decide(
    target: WaitingDraft,
    step: "confirm" | "reject" | "withdraw",
    reason?: string,
  ) {
    // A new reason is a new request, so it gets its own key.
    const name = `${step}:${target.draft_id}:${reason ?? ""}`;
    const asked = propertyId;
    const key = keys.current.get(name) ?? crypto.randomUUID();
    keys.current.set(name, key);
    const label = draftLabel(language, target);
    setBusy(true);
    setProblem(null);
    const request =
      step === "confirm"
        ? decisionApi.confirmDraft(propertyId, target.draft_id, key)
        : step === "reject"
          ? decisionApi.rejectDraft(
              propertyId,
              target.draft_id,
              { reason: reason ?? "" },
              key,
            )
          : decisionApi.withdrawDraft(
              propertyId,
              target.draft_id,
              { reason: reason ?? "" },
              key,
            );
    request
      .then(() => {
        if (shownProperty.current !== asked) return;
        keys.current.delete(name);
        setOpened(null);
        setToast(
          apt(
            language,
            step === "confirm"
              ? "ap_ok_toast"
              : step === "reject"
                ? "ap_rej_toast"
                : "ap_wdr_toast",
            label,
          ),
        );
        load();
      })
      .catch((error: unknown) => {
        if (shownProperty.current !== asked) return;
        if (error instanceof SettlementRequestError) {
          // A named refusal: nothing changed, so the next try is a new request.
          keys.current.delete(name);
          setProblem(serverWords(language, error));
          // Someone else may have decided it meanwhile: the list is read again, and the
          // dialog then shows the draft as decided, with these words.
          if (error.status === 409) load();
        } else {
          setProblem(apt(language, "ap_unknown"));
        }
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const cards = (
    [
      ["wait", "check", "warn", waiting.length, String(waiting.length)],
      ["out", "payments", "info", out.length, usdFromCents(sum(out))],
      ["kept", "lock", "info", kept.length, usdFromCents(sum(kept))],
      ["done", "history", "brand", done.length, String(done.length)],
    ] as const
  ).map(([name, icon, tone, count, value]) => (
    <CountCard
      icon={icon}
      key={name}
      label={apt(language, `apc_${name}`)}
      note={
        name === "out" && unknownOut > 0
          ? apt(language, "apc_out_unknown", unknownOut)
          : apt(language, `apc_${name}_s`)
      }
      onPress={() => {
        toggle(name);
      }}
      pressed={filter === name}
      tone={tone}
      value={count}
      valueText={value}
    />
  ));

  return (
    <>
      {head}
      {toast !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{toast}</p>
        </div>
      )}
      <div className="ui-kpis">{cards}</div>
      <div className="ui-card pad0">
        {filter !== "all" && (
          <div className="ui-listbar">
            <span className="ui-showing">
              {apt(language, "ap_showing", apt(language, `apc_${filter}`))}{" "}
              <button
                className="ui-btn link"
                onClick={() => {
                  setFilter("all");
                }}
                type="button"
              >
                {apt(language, "pc_clear")}
              </button>
            </span>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">
            <Icon name="check" small />{" "}
            {apt(language, filter === "done" ? "ap_done_none" : "ap_none")}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{apt(language, "ap_col_draft")}</th>
                  <th scope="col">{apt(language, "ap_col_for")}</th>
                  <th scope="col">{apt(language, "ap_col_by")}</th>
                  <th className="r" scope="col">
                    {apt(language, "ap_col_amt")}
                  </th>
                  <th scope="col">{apt(language, "col_status")}</th>
                  <th scope="col">
                    <span className="ui-sr">{apt(language, "ap_open")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((item) => {
                  const label = draftLabel(language, item);
                  return (
                    <tr key={item.draft_id}>
                      <td>
                        <b>{label}</b>
                        <span className="ui-sub2 ui-clip" title={item.reason}>
                          {item.reason}
                        </span>
                      </td>
                      <td>
                        <UnitLink draft={item} />
                        {item.summary.customer_name !== null && (
                          <span className="ui-sub2">
                            {item.summary.customer_name}
                          </span>
                        )}
                      </td>
                      <td>
                        {item.summary.prepared_by_name ?? "—"}
                        <span className="ui-sub2 ui-num">
                          {momentText(item.prepared_at)}
                        </span>
                      </td>
                      <td className="r ui-num">{amountText(item)}</td>
                      <td>
                        <StateChip draft={item} language={language} />
                      </td>
                      <td className="r">
                        <button
                          aria-label={`${apt(language, "ap_open")}: ${label}`}
                          className="ui-btn"
                          onClick={() => {
                            setProblem(null);
                            setToast(null);
                            setOpened({ id: item.draft_id, step: "open" });
                          }}
                          type="button"
                        >
                          {apt(language, "ap_open")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {filter !== "done" && page.truncated === true && (
          <p className="ui-small ui-muted pad">{apt(language, "ap_more")}</p>
        )}
      </div>
      <div className="ui-notice info" role="note">
        <Icon name="info" />
        <p>{apt(language, "ap_rule")}</p>
      </div>
      <section aria-labelledby="approvals-done" className="ui-card">
        <h2 id="approvals-done">{apt(language, "ap_done_h")}</h2>
        {done.length === 0 ? (
          <p className="ui-muted">{apt(language, "ap_done_none")}</p>
        ) : (
          <ul className="ui-apps">
            {done.map((item) => (
              <li key={item.draft_id}>
                <span>
                  {[
                    draftLabel(language, item),
                    item.summary.unit_number,
                    item.summary.customer_name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  <small className="ui-num">
                    {decidedLine(language, item)}
                  </small>
                </span>
                <StateChip draft={item} language={language} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {opened !== null &&
        draft !== undefined &&
        (opened.step === "open" || draft.state !== "PENDING") && (
          <Dialog
            actions={
              draft.state === "PENDING" && (
                <>
                  {draft.prepared_by === actorId && (
                    <button
                      className="ui-btn"
                      disabled={busy}
                      onClick={() => {
                        setProblem(null);
                        setOpened({ id: draft.draft_id, step: "withdraw" });
                      }}
                      type="button"
                    >
                      <Icon name="back" />
                      {apt(language, "ap_withdraw")}
                    </button>
                  )}
                  {mayApprove && (
                    <>
                      <button
                        className="ui-btn danger"
                        disabled={busy}
                        onClick={() => {
                          setProblem(null);
                          setOpened({ id: draft.draft_id, step: "reject" });
                        }}
                        type="button"
                      >
                        <Icon name="x" />
                        {apt(language, "ap_reject")}
                      </button>
                      <button
                        className="ui-btn primary"
                        disabled={busy}
                        onClick={() => {
                          decide(draft, "confirm");
                        }}
                        type="button"
                      >
                        <Icon name="check" />
                        {apt(language, "ap_confirm")}
                      </button>
                    </>
                  )}
                </>
              )
            }
            busy={busy}
            closeLabel={apt(
              language,
              draft.state === "PENDING" ? "cancel" : "close",
            )}
            onClose={close}
            title={
              draft.summary.unit_number === null
                ? draftLabel(language, draft)
                : `${draftLabel(language, draft)} · ${draft.summary.unit_number}`
            }
          >
            <DraftFacts draft={draft} language={language} />
            {draft.state === "PENDING" ? (
              <>
                <div className="ui-notice info">
                  <Icon name="info" />
                  <p>
                    <b>{apt(language, "ap_moves")}</b>
                    <br />
                    {draftEffect(language, draft)}
                  </p>
                </div>
                <p className="ui-small ui-muted">
                  <Icon name="lock" small />{" "}
                  {apt(language, mayApprove ? "ap_lock" : "ap_lock_view")}
                </p>
              </>
            ) : (
              <div
                className={
                  draft.state === "CONFIRMED"
                    ? "ui-notice ok"
                    : "ui-notice info"
                }
              >
                <Icon name={draft.state === "CONFIRMED" ? "check" : "x"} />
                <p>
                  {apt(
                    language,
                    draft.state === "CONFIRMED"
                      ? "ap_st_ok"
                      : draft.state === "WITHDRAWN"
                        ? "ap_st_wdr"
                        : "ap_st_rej",
                  )}
                  : {decidedLine(language, draft)}
                </p>
              </div>
            )}
            {problem !== null && (
              <div className="ui-notice warn" role="alert">
                <Icon name="alert" />
                <p>{problem}</p>
              </div>
            )}
          </Dialog>
        )}
      {opened !== null &&
        draft !== undefined &&
        opened.step !== "open" &&
        draft.state === "PENDING" && (
          <ReasonDialog
            busy={busy}
            draft={draft}
            language={language}
            onClose={close}
            onSend={(reason) => {
              decide(
                draft,
                opened.step === "reject" ? "reject" : "withdraw",
                reason,
              );
            }}
            problem={problem}
            step={opened.step}
          />
        )}
    </>
  );
}
