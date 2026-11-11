// Telegram bots step 2c (DL-128, mock-up round 29): Office › Telegram with the tabs Linked
// tenants ("#/tglinks") and Telegram health ("#/tghealth"). Reading needs telegram.read;
// Remove link and Retry show only to a person with telegram.operate. Step 2d part 2 (DL-170):
// the tabs Contact office ("#/tgcontact", telegram.contact) and FAQ ("#/tgfaq", read with
// telegram.contact, changed with telegram.faq; only the Owner approves). Step 3a (DL-171):
// Bookings › Visit requests ("#/visitreqs", visit_requests.read), the requests the Customer bot
// saves. The server checks every right again. No bot key is ever shown.

import "../shell/screens.css";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { Chip, CountCard, Dialog, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type ContactMessage,
  type ContactPage,
  FAQ_BOTS,
  type FaqBots,
  type FaqPage,
  type FaqQuestion,
  type FaqWords,
  type HealthPage,
  type InvoicesPage,
  type TelegramInvoice,
  type LinkedTenant,
  type LinksPage,
  type TelegramApi,
  TelegramError,
  telegramApi as defaultTelegramApi,
  type VisitAction,
  type VisitHistoryStep,
  type VisitInquiry,
  type VisitMonth,
  type VisitRequest,
  type VisitRequestDetail,
  type VisitRequestsPage,
  type VisitStepBody,
} from "./telegramClient";
import { openPageInAddress } from "../shell/useHashPage";
import { hasText, type TelegramTextKey, tt } from "./text";

export interface TelegramPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: TelegramApi;
}

const OPERATE = "telegram.operate";
const CONTACT = "telegram.contact";
const FAQ = "telegram.faq";

function holds(
  capabilities: ReadonlySet<string> | null,
  capability: string,
): boolean {
  return capabilities === null || capabilities.has(capability);
}

function mayOperate(capabilities: ReadonlySet<string> | null): boolean {
  return capabilities === null || capabilities.has(OPERATE);
}

/** Reads one page each time it is opened; another Property never shows the one before. */
function usePage<T>(
  propertyId: string,
  active: boolean,
  read: (propertyId: string) => Promise<T>,
): {
  data: T | null;
  failed: boolean;
  load: () => void;
  set: (value: T) => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);
  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void read(propertyId)
      .then((found) => {
        if (operation === sequence.current) setData(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [propertyId, read]);
  useEffect(() => {
    sequence.current++;
    setData(null);
  }, [propertyId]);
  useEffect(() => {
    if (active) load();
  }, [active, load]);
  const set = useCallback((value: T) => {
    sequence.current++;
    setData(value);
  }, []);
  return { data, failed, load, set };
}

function Waiting({
  language,
  failed,
  onRetry,
}: {
  language: Language;
  failed: boolean;
  onRetry: () => void;
}) {
  if (!failed)
    return (
      <p className="ui-muted" role="status">
        {tt(language, "loading")}
      </p>
    );
  return (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{tt(language, "failed")}</p>
      <button className="ui-btn" onClick={onRetry} type="button">
        {tt(language, "retry_read")}
      </button>
    </div>
  );
}

function NoProperty({ language }: { language: Language }) {
  return (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{tt(language, "no_property")}</p>
    </div>
  );
}

function Done({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <div className="ui-notice ok" role="status">
      <Icon name="check" />
      <p>{text}</p>
    </div>
  );
}

function errorText(language: Language, code: string | null): string {
  if (code === null) return "";
  const key = `err_${code}`;
  return hasText(key) ? tt(language, key) : code;
}

function when(value: string | null, language: Language): string {
  return value === null ? tt(language, "never") : momentText(value);
}

function person(name: string | null, fallback: string): string {
  return name === null || name === "" ? fallback : name;
}

// ---------------------------------------------------------------- Linked tenants

export function LinkedTenantsPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultTelegramApi,
}: TelegramPageProps) {
  const page = usePage<LinksPage>(propertyId, active, api.links);
  const [removing, setRemoving] = useState<LinkedTenant | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const operate = mayOperate(capabilities);

  if (propertyId === "") return <NoProperty language={language} />;

  const head = (
    <div className="ui-head">
      <p>{tt(language, "links_sub")}</p>
    </div>
  );
  if (page.data === null)
    return (
      <>
        {head}
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      </>
    );
  const { linked, tries, ended, rules } = page.data;
  const block = tt(language, "hours", rules.block_hours);

  return (
    <>
      {head}
      <Done text={done} />
      {stale && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{tt(language, "e_rm_409")}</p>
        </div>
      )}
      {tries.length > 0 && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{tt(language, "tries_t", tries.length)}</p>
        </div>
      )}
      <section aria-labelledby="tg-linked" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-linked">{tt(language, "linked_now")}</h2>
        </div>
        {linked.length === 0 ? (
          <p className="ui-empty">{tt(language, "none_linked")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_acc")}</th>
                  <th scope="col">{tt(language, "c_cust")}</th>
                  <th scope="col">{tt(language, "c_unit")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_lease_end")}
                  </th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_on")}
                  </th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_how")}
                  </th>
                  {operate && (
                    <th scope="col">
                      <span className="ui-sr">{tt(language, "remove")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {linked.map((link) => (
                  <tr key={link.id}>
                    <td className="ui-num">
                      {link.phone ?? ""}
                      <span className="ui-sub2">
                        {String(link.telegram_user_id)}
                      </span>
                    </td>
                    <td>{person(link.name, "")}</td>
                    <td>{link.unit_number ?? ""}</td>
                    <td className="ui-wide ui-num">
                      {dayText(link.lease_end_date ?? link.stay_end_date)}
                      {link.booking_number !== null && (
                        <span className="ui-sub2">
                          {tt(language, "stay_n", link.booking_number)}
                        </span>
                      )}
                    </td>
                    <td className="ui-wide ui-num">
                      {momentText(link.linked_at)}
                    </td>
                    <td className="ui-wide">{tt(language, "how")}</td>
                    {operate && (
                      <td>
                        <button
                          className="ui-btn"
                          onClick={() => {
                            setDone(null);
                            setStale(false);
                            setRemoving(link);
                          }}
                          type="button"
                        >
                          {tt(language, "remove")}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot">{tt(language, "links_n")}</p>
      </section>
      <section aria-labelledby="tg-tries" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-tries">{tt(language, "tries_h")}</h2>
        </div>
        {tries.length === 0 ? (
          <p className="ui-empty">{tt(language, "none_tries")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_phone")}</th>
                  <th scope="col">{tt(language, "c_name")}</th>
                  <th scope="col">{tt(language, "c_unit_t")}</th>
                  <th scope="col">{tt(language, "c_tries")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_last")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {tries.map((row) => (
                  <tr key={row.telegram_user_id}>
                    <td className="ui-num">
                      {row.phone ?? ""}
                      <span className="ui-sub2">
                        {String(row.telegram_user_id)}
                      </span>
                    </td>
                    <td>{row.typed_name ?? ""}</td>
                    <td>{row.typed_unit ?? ""}</td>
                    <td>
                      <span className="ui-num">{row.tries}</span>{" "}
                      {row.blocked_until === null ? (
                        <Chip tone="warn">
                          {tt(language, "left", row.tries_left)}
                        </Chip>
                      ) : (
                        <Chip tone="err">
                          {tt(
                            language,
                            "blocked",
                            momentText(row.blocked_until),
                          )}
                        </Chip>
                      )}
                    </td>
                    <td className="ui-wide ui-num">
                      {momentText(row.last_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot">
          {tt(language, "tries_n", rules.tries, block)}
        </p>
      </section>
      <section aria-labelledby="tg-ended" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-ended">{tt(language, "ended")}</h2>
          <span className="ui-muted">
            {tt(language, "ended_sub", rules.keep_days)}
          </span>
        </div>
        {ended.length === 0 ? (
          <p className="ui-empty">{tt(language, "none_ended")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_cust")}</th>
                  <th scope="col">{tt(language, "c_unit")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_on")}
                  </th>
                  <th scope="col">{tt(language, "c_end")}</th>
                  <th scope="col">{tt(language, "c_why")}</th>
                </tr>
              </thead>
              <tbody>
                {ended.map((row) => {
                  const reason = `end_${row.reason}`;
                  return (
                    <tr key={`${row.id}:${row.ended_at}`}>
                      <td>
                        {person(row.name, "")}
                        <span className="ui-sub2 ui-num">
                          {String(row.telegram_user_id)}
                        </span>
                      </td>
                      <td>{row.unit_number ?? ""}</td>
                      <td className="ui-wide ui-num">
                        {momentText(row.linked_at)}
                      </td>
                      <td className="ui-num">{momentText(row.ended_at)}</td>
                      <td>
                        {hasText(reason) ? tt(language, reason) : row.reason}
                        {row.note !== null && (
                          <span className="ui-sub2">{row.note}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <InvoicesOnTelegram
        active={active}
        api={api}
        language={language}
        propertyId={propertyId}
      />
      {removing !== null && (
        <RemoveLinkDialog
          api={api}
          language={language}
          link={removing}
          onClose={() => {
            setRemoving(null);
          }}
          onDone={(next) => {
            page.set(next);
            setDone(
              tt(
                language,
                "rm_done",
                person(removing.name, removing.phone ?? ""),
              ),
            );
            setRemoving(null);
          }}
          onStale={() => {
            setRemoving(null);
            setStale(true);
            page.load();
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

// Invoices on Telegram (DL-211): who got each issued Invoice, and who needs a paper copy.

function invoiceReached(
  invoice: TelegramInvoice,
): "sent" | "waiting" | "failed" | "none" {
  if (invoice.sent.length === 0) return "none";
  if (invoice.sent.some((person) => person.state === "SENT")) return "sent";
  if (invoice.sent.every((person) => person.state === "GAVE_UP"))
    return "failed";
  return "waiting";
}

function InvoicesOnTelegram({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: TelegramApi;
}) {
  const page = usePage<InvoicesPage>(propertyId, active, api.invoices);
  const data = page.data;
  const paper =
    data === null
      ? 0
      : data.invoices.filter((invoice) => {
          const reached = invoiceReached(invoice);
          return reached === "none" || reached === "failed";
        }).length;
  return (
    <section aria-labelledby="tg-invoices" className="ui-card pad0">
      <div className="ui-listbar">
        <h2 id="tg-invoices">{tt(language, "inv_h")}</h2>
      </div>
      {data === null ? (
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      ) : (
        <>
          {paper > 0 && (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{tt(language, "inv_paper_t", paper)}</p>
            </div>
          )}
          {data.invoices.length === 0 ? (
            <p className="ui-empty">{tt(language, "inv_none")}</p>
          ) : (
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{tt(language, "c_invoice")}</th>
                    <th scope="col">{tt(language, "c_unit")}</th>
                    <th className="ui-wide" scope="col">
                      {tt(language, "c_cust")}
                    </th>
                    <th scope="col">{tt(language, "c_due")}</th>
                    <th className="ui-wide" scope="col">
                      {tt(language, "c_to_pay")}
                    </th>
                    <th scope="col">{tt(language, "c_telegram")}</th>
                    <th className="ui-wide" scope="col">
                      {tt(language, "c_reminder")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.invoices.map((invoice) => {
                    const reached = invoiceReached(invoice);
                    const sentCount = invoice.sent.filter(
                      (person) => person.state === "SENT",
                    ).length;
                    return (
                      <tr key={invoice.id}>
                        <td className="ui-num">{invoice.number}</td>
                        <td>{invoice.unit_number ?? ""}</td>
                        <td className="ui-wide">{invoice.customer}</td>
                        <td className="ui-num">{dayText(invoice.due_date)}</td>
                        <td className="ui-wide ui-num">
                          {usdFromCents(invoice.to_pay_usd_cents)}
                        </td>
                        <td>
                          {reached === "sent" && (
                            <Chip tone="ok">
                              {tt(language, "inv_sent", sentCount)}
                            </Chip>
                          )}
                          {reached === "waiting" && (
                            <Chip tone="warn">
                              {tt(language, "inv_waiting")}
                            </Chip>
                          )}
                          {reached === "failed" && (
                            <Chip tone="err">{tt(language, "inv_failed")}</Chip>
                          )}
                          {reached === "none" && (
                            <Chip tone="err">{tt(language, "inv_paper")}</Chip>
                          )}
                        </td>
                        <td className="ui-wide ui-num">
                          {invoice.reminded_at === null
                            ? tt(language, "inv_no_reminder")
                            : momentText(invoice.reminded_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="ui-tfoot">
            {tt(language, "inv_sub", data.rules.remind_days, data.rules.days)}
          </p>
        </>
      )}
    </section>
  );
}

function RemoveLinkDialog({
  language,
  propertyId,
  link,
  api,
  onClose,
  onDone,
  onStale,
}: {
  language: Language;
  propertyId: string;
  link: LinkedTenant;
  api: TelegramApi;
  onClose: () => void;
  onDone: (next: LinksPage) => void;
  onStale: () => void;
}) {
  const [reason, setReason] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const missing = reason.trim() === "";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setShown(true);
    if (missing || busy) return;
    setBusy(true);
    setFailure(null);
    api.removeLink(propertyId, link.id, reason.trim()).then(
      (next) => {
        setBusy(false);
        onDone(next);
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          onStale();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={tt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={tt(language, "remove")}
      title={tt(language, "rm_t")}
    >
      <p>
        {tt(
          language,
          "rm_q",
          person(link.name, ""),
          link.unit_number ?? "",
          link.phone ?? String(link.telegram_user_id),
        )}
      </p>
      <div className="ui-field">
        <label htmlFor="tg-rm-reason">
          {tt(language, "rm_reason")}
          <span className="req">{"*"}</span>
        </label>
        <textarea
          aria-describedby={shown && missing ? "tg-rm-reason-err" : undefined}
          aria-invalid={shown && missing}
          disabled={busy}
          id="tg-rm-reason"
          maxLength={300}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          placeholder={tt(language, "rm_ph")}
          rows={2}
          value={reason}
        />
        <p className="help">{tt(language, "rm_n")}</p>
        {shown && missing && (
          <p className="ui-error" id="tg-rm-reason-err">
            {tt(language, "e_reason")}
          </p>
        )}
      </div>
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- Telegram health

export function TelegramHealthPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultTelegramApi,
}: TelegramPageProps) {
  const page = usePage<HealthPage>(propertyId, active, api.health);
  const [done, setDone] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const operate = mayOperate(capabilities);

  if (propertyId === "") return <NoProperty language={language} />;

  const head = (
    <div className="ui-head">
      <p>{tt(language, "h_sub")}</p>
      <span className="ui-muted">
        <Icon name="lock" small /> {tt(language, "h_lock")}
      </span>
    </div>
  );
  if (page.data === null)
    return (
      <>
        {head}
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      </>
    );
  const health = page.data;
  const lastPull = health.pulls[0];

  const retry = (messageId: string, to: string) => {
    if (busy !== null) return;
    setBusy(messageId);
    setDone(null);
    setFailure(null);
    api.retry(propertyId, messageId).then(
      (next) => {
        setBusy(null);
        page.set(next);
        setDone(tt(language, "retry_done", to));
      },
      (error: unknown) => {
        setBusy(null);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          setFailure(tt(language, "e_retry_409"));
          page.load();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  const kpis: [string, string, string, boolean][] = [
    [
      tt(language, "k_pull"),
      health.last_pull_at === null
        ? tt(language, "k_pull_none")
        : momentText(health.last_pull_at),
      lastPull === undefined
        ? ""
        : tt(language, "k_pull_s", lastPull.items_saved),
      health.last_pull_outcome === "FAILED" || health.last_pull_at === null,
    ],
    [
      tt(language, "k_wait"),
      String(health.outbox_waiting),
      tt(language, "k_wait_s"),
      false,
    ],
    [
      tt(language, "k_bad"),
      String(health.outbox_failing_12h),
      tt(language, "k_bad_s"),
      health.outbox_failing_12h > 0,
    ],
    [
      tt(language, "k_old"),
      String(health.relay_dropped),
      tt(language, "k_old_s"),
      health.relay_dropped > 0,
    ],
  ];

  return (
    <>
      {head}
      <Done text={done} />
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
      <div className="ui-kpis" role="list">
        {kpis.map(([label, value, note, bad]) => (
          <div
            className={`ui-kpi ${bad ? "err" : "ok"}`}
            key={label}
            role="listitem"
          >
            <span className="ui-kpi-label">{label}</span>
            <span className="ui-kpi-value ui-num">{value}</span>
            <span className="ui-kpi-note">{note}</span>
          </div>
        ))}
      </div>
      {health.last_pull_outcome === "FAILED" &&
        health.last_pull_at !== null && (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {tt(
                language,
                "last_err",
                momentText(health.last_pull_at),
                errorText(language, health.last_pull_error),
              )}
            </p>
          </div>
        )}
      <section aria-labelledby="tg-bots" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-bots">{tt(language, "bots")}</h2>
        </div>
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{tt(language, "c_bot")}</th>
                <th scope="col">{tt(language, "c_state")}</th>
                <th scope="col">{tt(language, "c_in")}</th>
                <th scope="col">{tt(language, "c_out")}</th>
              </tr>
            </thead>
            <tbody>
              {health.bots.map((bot) => {
                const name = `bot_${bot.code}`;
                return (
                  <tr key={bot.code}>
                    <td>{hasText(name) ? tt(language, name) : bot.name}</td>
                    <td>
                      {bot.failing ? (
                        <Chip icon="alert" tone="err">
                          {tt(language, "problem")}
                        </Chip>
                      ) : (
                        <Chip tone="ok">{tt(language, "working")}</Chip>
                      )}
                    </td>
                    <td className="ui-num">{when(bot.last_in, language)}</td>
                    <td className="ui-num">{when(bot.last_out, language)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="ui-tfoot">{tt(language, "keys")}</p>
      </section>
      <section aria-labelledby="tg-outbox" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-outbox">{tt(language, "outbox")}</h2>
        </div>
        {health.outbox.length === 0 ? (
          <p className="ui-empty">{tt(language, "none_outbox")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_to")}</th>
                  <th scope="col">{tt(language, "c_since")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_tries")}
                  </th>
                  <th scope="col">{tt(language, "c_err")}</th>
                  <th scope="col">{tt(language, "c_state")}</th>
                </tr>
              </thead>
              <tbody>
                {health.outbox.map((message) => {
                  const bot = `bot_${message.bot}`;
                  const to =
                    message.to === null
                      ? tt(language, "to_chat")
                      : [message.to.name, message.to.unit_number]
                          .filter(Boolean)
                          .join(", ");
                  return (
                    <tr key={message.id}>
                      <td>
                        {to}
                        <span className="ui-sub2">
                          {hasText(bot) ? tt(language, bot) : message.bot}
                          {" · "}
                          {message.text_code}
                        </span>
                      </td>
                      <td className="ui-num">
                        {momentText(message.created_at)}
                      </td>
                      <td className="ui-wide ui-num">{message.tries}</td>
                      <td>
                        {errorText(language, message.last_error)}
                        {message.last_try_at !== null && (
                          <span className="ui-sub2 ui-num">
                            {momentText(message.last_try_at)}
                          </span>
                        )}
                      </td>
                      <td>
                        {message.retried ? (
                          <Chip tone="neutral">{tt(language, "retried")}</Chip>
                        ) : (
                          <Chip
                            tone={message.status === "GAVE_UP" ? "err" : "warn"}
                          >
                            {tt(language, `st_${message.status}`)}
                          </Chip>
                        )}
                        {operate &&
                          message.status === "GAVE_UP" &&
                          !message.retried && (
                            <>
                              {" "}
                              <button
                                className="ui-btn"
                                disabled={busy !== null}
                                onClick={() => {
                                  retry(message.id, to);
                                }}
                                type="button"
                              >
                                {tt(language, "retry")}
                              </button>
                            </>
                          )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot">{tt(language, "outbox_n")}</p>
      </section>
      <section aria-labelledby="tg-pulls" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="tg-pulls">{tt(language, "pulls")}</h2>
        </div>
        {health.pulls.length === 0 ? (
          <p className="ui-empty">{tt(language, "none_pulls")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_at")}</th>
                  <th scope="col">{tt(language, "c_items")}</th>
                  <th scope="col">{tt(language, "c_res")}</th>
                </tr>
              </thead>
              <tbody>
                {health.pulls.map((run) => {
                  const outcome = `pull_${run.outcome}`;
                  return (
                    <tr key={run.started_at}>
                      <td className="ui-num">{momentText(run.started_at)}</td>
                      <td className="ui-num">{run.items_saved}</td>
                      <td>
                        {run.outcome === "OK" ? (
                          <Chip tone="ok">{tt(language, "pull_OK")}</Chip>
                        ) : (
                          <Chip tone="err">
                            {hasText(outcome)
                              ? tt(language, outcome)
                              : run.outcome}
                          </Chip>
                        )}
                        {run.error_code !== null && (
                          <span className="ui-sub2">
                            {errorText(language, run.error_code)}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

// ---------------------------------------------------------------- Contact office

function botName(language: Language, bot: string): string {
  const key = `bot_${bot}`;
  return hasText(key) ? tt(language, key) : bot;
}

export function ContactOfficePage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultTelegramApi,
}: TelegramPageProps) {
  const page = usePage<ContactPage>(propertyId, active, api.contact);
  const [tab, setTab] = useState<"NEW" | "DONE">("NEW");
  const [answering, setAnswering] = useState<{
    message: ContactMessage;
    how: "TELEGRAM" | "PHONE";
  } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const answer = holds(capabilities, CONTACT);

  if (propertyId === "") return <NoProperty language={language} />;

  const head = (
    <div className="ui-head">
      <p>{tt(language, "contact_sub")}</p>
    </div>
  );
  if (page.data === null)
    return (
      <>
        {head}
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      </>
    );
  const { waiting, answered } = page.data;
  const shown = tab === "NEW" ? waiting : answered;

  return (
    <>
      {head}
      <Done text={done} />
      {stale && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{tt(language, "e_answered")}</p>
        </div>
      )}
      <section aria-labelledby="tg-contact" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 className="ui-sr" id="tg-contact">
            {pageTitle(language, "contact")}
          </h2>
          <div
            aria-label={pageTitle(language, "contact")}
            className="ui-seg"
            role="group"
          >
            {(["NEW", "DONE"] as const).map((value) => (
              <button
                aria-pressed={tab === value}
                key={value}
                onClick={() => {
                  setTab(value);
                }}
                type="button"
              >
                {tt(language, `ib_${value}`)}{" "}
                <span className="ui-num">
                  {value === "NEW" ? waiting.length : answered.length}
                </span>
              </button>
            ))}
          </div>
        </div>
        {shown.length === 0 ? (
          <p className="ui-empty">
            {tt(language, tab === "NEW" ? "none_waiting" : "none_answered")}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_from")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_phone")}
                  </th>
                  <th scope="col">{tt(language, "c_msg")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_at")}
                  </th>
                  {tab === "NEW" && answer && (
                    <th scope="col">
                      <span className="ui-sr">{tt(language, "reply")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {shown.map((message) => (
                  <tr key={message.id}>
                    <td>
                      {person(message.name, "")}
                      <span className="ui-sub2">
                        <Chip
                          tone={message.bot === "TENANT" ? "info" : "neutral"}
                        >
                          {botName(language, message.bot)}
                        </Chip>
                      </span>
                      {message.unit_number !== null && (
                        <span className="ui-sub2 ui-num">
                          {message.unit_number}
                        </span>
                      )}
                    </td>
                    <td className="ui-wide ui-num">{message.phone ?? ""}</td>
                    <td>
                      {message.message}
                      {message.answer !== null && (
                        <span className="ui-sub2">
                          {tt(
                            language,
                            `ans_${message.answer.how}`,
                            message.answer.by ?? "",
                            momentText(message.answer.at),
                          )}
                          {": "}
                          {message.answer.text}
                        </span>
                      )}
                    </td>
                    <td className="ui-wide ui-num">
                      {momentText(message.received_at)}
                    </td>
                    {tab === "NEW" && answer && (
                      <td>
                        <div className="ui-actions">
                          <button
                            className="ui-btn primary"
                            onClick={() => {
                              setDone(null);
                              setStale(false);
                              setAnswering({ message, how: "TELEGRAM" });
                            }}
                            type="button"
                          >
                            {tt(language, "reply")}
                          </button>
                          <button
                            className="ui-btn"
                            onClick={() => {
                              setDone(null);
                              setStale(false);
                              setAnswering({ message, how: "PHONE" });
                            }}
                            type="button"
                          >
                            {tt(language, "called")}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot">{tt(language, "contact_n")}</p>
      </section>
      {answering !== null && (
        <AnswerDialog
          api={api}
          how={answering.how}
          language={language}
          message={answering.message}
          onClose={() => {
            setAnswering(null);
          }}
          onDone={(next) => {
            page.set(next);
            const who = person(answering.message.name, "");
            setDone(
              tt(
                language,
                answering.how === "TELEGRAM" ? "rep_done" : "call_done",
                who,
              ),
            );
            setAnswering(null);
          }}
          onStale={() => {
            setAnswering(null);
            setStale(true);
            page.load();
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

function pageTitle(language: Language, which: "contact" | "faq"): string {
  return which === "contact"
    ? language === "km"
      ? "ទាក់ទងការិយាល័យ"
      : "Contact office"
    : language === "km"
      ? "សំណួរញឹកញាប់"
      : "FAQ";
}

function AnswerDialog({
  language,
  propertyId,
  message,
  how,
  api,
  onClose,
  onDone,
  onStale,
}: {
  language: Language;
  propertyId: string;
  message: ContactMessage;
  how: "TELEGRAM" | "PHONE";
  api: TelegramApi;
  onClose: () => void;
  onDone: (next: ContactPage) => void;
  onStale: () => void;
}) {
  const [words, setWords] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const missing = words.trim() === "";
  const reply = how === "TELEGRAM";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setShown(true);
    if (missing || busy) return;
    setBusy(true);
    setFailure(null);
    api.answer(propertyId, message.id, how, words.trim()).then(
      (next) => {
        setBusy(false);
        onDone(next);
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          onStale();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={tt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={tt(language, reply ? "send" : "save")}
      title={`${tt(language, reply ? "reply" : "called")} · ${person(message.name, "")}`}
    >
      <p className="ui-muted">{message.message}</p>
      <div className="ui-field">
        <label htmlFor="tg-answer">
          {tt(language, reply ? "rep_l" : "call_l")}
          <span className="req">{"*"}</span>
        </label>
        <textarea
          aria-describedby={shown && missing ? "tg-answer-err" : undefined}
          aria-invalid={shown && missing}
          disabled={busy}
          id="tg-answer"
          maxLength={600}
          onChange={(event) => {
            setWords(event.currentTarget.value);
          }}
          rows={3}
          value={words}
        />
        <p className="help">
          {reply
            ? tt(language, "rep_n", botName(language, message.bot))
            : tt(language, "call_n")}
        </p>
        {shown && missing && (
          <p className="ui-error" id="tg-answer-err">
            {tt(language, "e_text")}
          </p>
        )}
      </div>
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- FAQ

const NO_WORDS: FaqWords = {
  for_bots: "BOTH",
  question_en: "",
  answer_en: "",
  question_km: "",
  answer_km: "",
};

function wordsOf(question: FaqQuestion | null): FaqWords {
  const from = question?.pending ?? question?.current ?? null;
  if (from === null) return NO_WORDS;
  return {
    for_bots: from.for_bots,
    question_en: from.question_en,
    answer_en: from.answer_en,
    question_km: from.question_km,
    answer_km: from.answer_km,
  };
}

export function FaqPageView({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultTelegramApi,
}: TelegramPageProps) {
  const page = usePage<FaqPage>(propertyId, active, api.faq);
  const [editing, setEditing] = useState<FaqQuestion | "new" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (propertyId === "") return <NoProperty language={language} />;
  const edit = holds(capabilities, FAQ) && page.data?.can_edit === true;
  const head = (
    <div className="ui-head">
      <p>{tt(language, "faq_sub")}</p>
      {edit && (
        <button
          className="ui-btn primary"
          onClick={() => {
            setDone(null);
            setFailure(null);
            setEditing("new");
          }}
          type="button"
        >
          <Icon name="plus" small /> {tt(language, "faq_new")}
        </button>
      )}
    </div>
  );
  if (page.data === null)
    return (
      <>
        {head}
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      </>
    );
  const { questions, owner } = page.data;
  const km = language === "km";

  const approve = (question: FaqQuestion, versionId: string) => {
    if (busy) return;
    setBusy(true);
    setDone(null);
    setFailure(null);
    api.approveFaq(propertyId, versionId).then(
      (next) => {
        setBusy(false);
        page.set(next);
        setDone(tt(language, "faq_done_ok", question.number));
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          setFailure(tt(language, "e_faq_stale"));
          page.load();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  const loadStarter = () => {
    if (busy) return;
    setBusy(true);
    setDone(null);
    setFailure(null);
    api.loadFaqStarter(propertyId).then(
      (next) => {
        setBusy(false);
        page.set(next);
        setDone(tt(language, "faq_starter_done"));
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 409) {
          setFailure(tt(language, "e_faq_stale"));
          page.load();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  return (
    <>
      {head}
      <Done text={done} />
      {failure !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
      <section aria-labelledby="tg-faq" className="ui-card pad0">
        <h2 className="ui-sr" id="tg-faq">
          {pageTitle(language, "faq")}
        </h2>
        {questions.length === 0 ? (
          <div className="ui-empty">
            <p>{tt(language, "none_faq")}</p>
            {edit && (
              <>
                <p>{tt(language, "faq_starter_sub")}</p>
                <button
                  className="ui-btn"
                  disabled={busy}
                  onClick={loadStarter}
                  type="button"
                >
                  {tt(language, "faq_starter")}
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "c_no")}</th>
                  <th scope="col">{tt(language, "c_q")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_who")}
                  </th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "c_ver")}
                  </th>
                  <th scope="col">
                    <span className="ui-sr">{tt(language, "edit")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {questions.map((question) => {
                  const words = question.current ?? question.pending;
                  const pending = question.pending;
                  return (
                    <tr key={question.id}>
                      <td className="ui-num">{question.number}</td>
                      <td>
                        {words === null
                          ? ""
                          : km
                            ? words.question_km
                            : words.question_en}
                        {words !== null && (
                          <span className="ui-sub2">
                            {km ? words.question_en : words.question_km}
                          </span>
                        )}
                        {pending !== null && (
                          <span className="ui-sub2">
                            <Chip icon="clock" tone="warn">
                              {tt(
                                language,
                                "faq_pend",
                                pending.proposed_by ?? "",
                              )}
                            </Chip>
                          </span>
                        )}
                      </td>
                      <td className="ui-wide">
                        {words !== null && (
                          <Chip
                            tone={
                              words.for_bots === "HIDDEN"
                                ? "neutral"
                                : words.for_bots === "BOTH"
                                  ? "info"
                                  : "ok"
                            }
                          >
                            {tt(language, `who_${words.for_bots}`)}
                          </Chip>
                        )}
                      </td>
                      <td className="ui-wide">
                        {question.current === null ? (
                          tt(language, "not_yet")
                        ) : (
                          <>
                            <span className="ui-num">
                              {tt(
                                language,
                                "ver",
                                question.current.version_number,
                              )}
                            </span>
                            <span className="ui-sub2">
                              {tt(
                                language,
                                "ok_by",
                                question.current.approved_by ?? "",
                                momentText(question.current.approved_at),
                              )}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        <div className="ui-actions">
                          {pending !== null && owner && edit && (
                            <button
                              className="ui-btn primary"
                              disabled={busy}
                              onClick={() => {
                                approve(question, pending.version_id);
                              }}
                              type="button"
                            >
                              {tt(language, "faq_ok")}
                            </button>
                          )}
                          {edit && (
                            <button
                              className="ui-btn"
                              onClick={() => {
                                setDone(null);
                                setFailure(null);
                                setEditing(question);
                              }}
                              type="button"
                            >
                              {tt(
                                language,
                                pending !== null ? "faq_see" : "edit",
                              )}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot">
          <Icon name="lock" small /> {tt(language, "faq_n")}
          {!edit && <> {tt(language, "faq_read_only")}</>}
        </p>
      </section>
      {editing !== null && (
        <FaqDialog
          api={api}
          language={language}
          onClose={() => {
            setEditing(null);
          }}
          onDone={(saved) => {
            page.set(saved.page);
            setDone(
              tt(
                language,
                saved.approved ? "faq_done_ok" : "faq_done",
                saved.number,
              ),
            );
            setEditing(null);
          }}
          onStale={() => {
            setEditing(null);
            setFailure(tt(language, "e_faq_stale"));
            page.load();
          }}
          owner={owner}
          propertyId={propertyId}
          question={editing === "new" ? null : editing}
        />
      )}
    </>
  );
}

const FAQ_FIELDS = [
  ["question_en", "q_en", 160],
  ["answer_en", "a_en", 800],
  ["question_km", "q_km", 160],
  ["answer_km", "a_km", 800],
] as const;

function FaqDialog({
  language,
  propertyId,
  question,
  owner,
  api,
  onClose,
  onDone,
  onStale,
}: {
  language: Language;
  propertyId: string;
  question: FaqQuestion | null;
  owner: boolean;
  api: TelegramApi;
  onClose: () => void;
  onDone: (saved: Awaited<ReturnType<TelegramApi["saveFaq"]>>) => void;
  onStale: () => void;
}) {
  const [words, setWords] = useState<FaqWords>(() => wordsOf(question));
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const missing = FAQ_FIELDS.some(([field]) => words[field].trim() === "");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setShown(true);
    if (missing || busy) return;
    setBusy(true);
    setFailure(null);
    const trimmed: FaqWords = {
      for_bots: words.for_bots,
      question_en: words.question_en.trim(),
      answer_en: words.answer_en.trim(),
      question_km: words.question_km.trim(),
      answer_km: words.answer_km.trim(),
    };
    api.saveFaq(propertyId, question?.id ?? null, trimmed).then(
      (saved) => {
        setBusy(false);
        onDone(saved);
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          onStale();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={tt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={tt(language, owner ? "faq_save_ok" : "faq_save")}
      title={
        question === null
          ? tt(language, "faq_new")
          : tt(language, "faq_ed", question.number)
      }
      wide
    >
      <div className="ui-field">
        <label htmlFor="tg-faq-who">{tt(language, "c_who")}</label>
        <select
          className="ui-sel"
          disabled={busy}
          id="tg-faq-who"
          onChange={(event) => {
            const value = event.currentTarget.value;
            const found = FAQ_BOTS.find((code) => code === value);
            if (found !== undefined)
              setWords((before) => ({ ...before, for_bots: found }));
          }}
          value={words.for_bots}
        >
          {FAQ_BOTS.map((code: FaqBots) => (
            <option key={code} value={code}>
              {tt(language, `who_${code}`)}
            </option>
          ))}
        </select>
      </div>
      {FAQ_FIELDS.map(([field, label, most]) => {
        const empty = shown && words[field].trim() === "";
        const id = `tg-faq-${field}`;
        const change = (value: string) => {
          setWords((before) => ({ ...before, [field]: value }));
        };
        return (
          <div className="ui-field" key={field}>
            <label htmlFor={id}>
              {tt(language, label)}
              <span className="req">{"*"}</span>
            </label>
            {most === 160 ? (
              <input
                aria-describedby={empty ? `${id}-err` : undefined}
                aria-invalid={empty}
                autoComplete="off"
                disabled={busy}
                id={id}
                maxLength={most}
                onChange={(event) => {
                  change(event.currentTarget.value);
                }}
                value={words[field]}
              />
            ) : (
              <textarea
                aria-describedby={empty ? `${id}-err` : undefined}
                aria-invalid={empty}
                disabled={busy}
                id={id}
                maxLength={most}
                onChange={(event) => {
                  change(event.currentTarget.value);
                }}
                rows={3}
                value={words[field]}
              />
            )}
            {empty && (
              <p className="ui-error" id={`${id}-err`}>
                {tt(language, "e_text")}
              </p>
            )}
          </div>
        );
      })}
      <p className="help">{tt(language, owner ? "faq_own_n" : "faq_mgr_n")}</p>
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- Visit requests

function contactBy(language: Language, inquiry: VisitInquiry): string {
  const key = `ch_${inquiry.contact_by}`;
  return hasText(key) ? tt(language, key) : inquiry.contact_by;
}

function unitTypeName(language: Language, inquiry: VisitInquiry): string {
  const name = language === "km" ? inquiry.unit_type_km : inquiry.unit_type_en;
  return name ?? inquiry.unit_type;
}

function moveIn(language: Language, inquiry: VisitInquiry): string {
  if (inquiry.move_in_month === null) return tt(language, "vr_later");
  const [year = "", month = ""] = inquiry.move_in_month.split("-");
  return `${month}/${year}`;
}

function prefers(language: Language, inquiry: VisitInquiry): string {
  if (inquiry.visit_on === null) return tt(language, "vr_no_day");
  const key = `part_${inquiry.visit_part ?? ""}`;
  const part = hasText(key) ? tt(language, key) : "";
  return part === ""
    ? dayText(inquiry.visit_on)
    : `${dayText(inquiry.visit_on)}, ${part}`;
}

function statusName(language: Language, status: string): string {
  const key = `vst_${status}`;
  return hasText(key) ? tt(language, key) : status;
}

/** The status a person sees: Late, Cancelled (closed by the customer) or the status. */
function shownStatus(request: VisitRequest): string {
  if (request.late) return "LATE";
  if (request.status === "CLOSED" && request.reason === "CANCELLED")
    return "CANCELLED";
  return request.status;
}

function statusTone(status: string): Tone {
  if (status === "LATE") return "err";
  if (status === "NEW") return "info";
  if (status === "VISITED" || status === "RESERVED") return "ok";
  if (["CLOSED", "CANCELLED", "SPAM", "NO_SHOW"].includes(status))
    return "neutral";
  return "warn";
}

function textOf(language: Language, prefix: string, code: string): string {
  const key = `${prefix}${code}`;
  return hasText(key) ? tt(language, key) : code;
}

function waited(language: Language, request: VisitRequest): string {
  if (request.status !== "NEW") return tt(language, "vr_answered");
  const minutes = request.waiting_minutes;
  return tt(language, "vr_wait_hm", Math.floor(minutes / 60), minutes % 60);
}

/** "Saturday 07/11/2026" in the language given, from "YYYY-MM-DD". */
function visitDay(language: Language, day: string): string {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay();
  const name = textOf(language, "wd_", String(weekday === 0 ? 7 : weekday));
  return `${name} ${dayText(day)}`;
}

function visitText(language: Language, local: string): string {
  const [day = "", time = ""] = local.split("T");
  return `${visitDay(language, day)} ${time}`;
}

/** The words to send by hand, in the customer's language. */
function handWords(
  request: VisitRequest,
  what: string,
  address: string,
): string {
  const language: Language = request.language === "km" ? "km" : "en";
  const [day = "", time = ""] = (request.visit_local ?? "").split("T");
  return what === "REMINDER"
    ? tt(language, "msg_rem", visitDay(language, day), time)
    : tt(
        language,
        "msg_conf",
        visitDay(language, day),
        time,
        address,
        request.visit_staff ?? "",
      );
}

function InquiryCells({
  language,
  inquiry,
}: {
  language: Language;
  inquiry: VisitInquiry;
}) {
  return (
    <>
      <td>
        {inquiry.name}
        <span className="ui-sub2 ui-num">{inquiry.phone}</span>
      </td>
      <td className="ui-wide">
        {contactBy(language, inquiry)}
        {inquiry.email !== null && (
          <span className="ui-sub2">{inquiry.email}</span>
        )}
      </td>
      <td>
        {unitTypeName(language, inquiry)}
        <span className="ui-sub2">
          {tt(language, "vr_movein", moveIn(language, inquiry))}
        </span>
      </td>
      <td>{prefers(language, inquiry)}</td>
      <td className="ui-wide">
        <span className="ui-muted">{inquiry.note ?? ""}</span>
      </td>
    </>
  );
}

type VisitCard = "all" | "waiting" | "late" | "booked" | "mine";

const VISIT_CARDS: readonly [
  Exclude<VisitCard, "all">,
  ShellIcon,
  Tone,
  TelegramTextKey,
][] = [
  ["waiting", "clock", "info", "vr_c_waiting"],
  ["late", "alert", "err", "vr_c_late"],
  ["booked", "door", "warn", "vr_c_booked"],
  ["mine", "userplus", "ok", "vr_c_mine"],
];

function isOpen(request: VisitRequest): boolean {
  return !["CLOSED", "SPAM", "RESERVED"].includes(request.status);
}

const MONTH_STEPS = [
  "VISIT_BOOKED",
  "VISITED",
  "NO_SHOW",
  "RESERVED",
  "CLOSED",
  "SPAM",
] as const;

function CountTable({
  language,
  title,
  rows,
  prefix,
}: {
  language: Language;
  title: TelegramTextKey;
  rows: { code: string; count: number }[];
  prefix: string;
}) {
  return (
    <div>
      <h3>{tt(language, title)}</h3>
      {rows.length === 0 ? (
        <p className="ui-muted">{tt(language, "m_none")}</p>
      ) : (
        <table className="ui-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row.code}>
                <td>{textOf(language, prefix, row.code)}</td>
                <td className="r ui-num">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** This month, for Managers and the Owner (DL-173). */
function MonthSection({
  language,
  month,
}: {
  language: Language;
  month: VisitMonth;
}) {
  return (
    <section aria-labelledby="vr-month" className="ui-card">
      <h2 id="vr-month">
        {tt(language, "m_title")}{" "}
        <span className="ui-muted ui-num">
          {month.month.split("-").reverse().join("/")}
        </span>
      </h2>
      <dl className="ui-kv">
        <dt>{tt(language, "m_new")}</dt>
        <dd className="ui-num">{month.new}</dd>
        <dt>{tt(language, "m_joined")}</dt>
        <dd className="ui-num">{month.joined}</dd>
        {MONTH_STEPS.map((step) => [
          <dt key={`${step}-t`}>{tt(language, `m_${step}`)}</dt>,
          <dd className="ui-num" key={`${step}-d`}>
            {month.steps[step] ?? 0}
          </dd>,
        ])}
      </dl>
      <div className="ui-split">
        <CountTable
          language={language}
          prefix="reason_"
          rows={month.reasons}
          title="m_reasons"
        />
        <CountTable
          language={language}
          prefix="src_"
          rows={month.sources}
          title="m_sources"
        />
      </div>
    </section>
  );
}

function inVisitCard(request: VisitRequest, card: VisitCard): boolean {
  if (card === "waiting")
    return request.status === "NEW" && request.staff_id === null;
  if (card === "late") return request.late;
  if (card === "booked") return request.status === "VISIT_BOOKED";
  if (card === "mine") return request.mine && isOpen(request);
  return request.status !== "SPAM";
}

function SendByHand({
  language,
  page,
  busy,
  onSent,
}: {
  language: Language;
  page: VisitRequestsPage;
  busy: boolean;
  onSent: (request: VisitRequest, what: "CONFIRMATION" | "REMINDER") => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const items = page.requests.flatMap((request) =>
    request.to_send.map((what) => ({ request, what })),
  );
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="vr-hand" className="ui-card">
      <h2 id="vr-hand">{tt(language, "sbh_title")}</h2>
      <p className="ui-muted">{tt(language, "sbh_sub")}</p>
      <ul className="ui-timeline">
        {items.map(({ request, what }) => {
          const words = handWords(request, what, page.address);
          const id = `${request.id}-${what}`;
          const allowed = page.can_work && (request.mine || page.can_manage);
          return (
            <li key={id}>
              <div>
                <strong className="ui-num">{request.number}</strong>{" "}
                {request.name} · {contactBy(language, request)}{" "}
                <span className="ui-num">{request.email ?? request.phone}</span>
                <small>{textOf(language, "what_", what)}</small>
                <p className="ui-sub2" style={{ whiteSpace: "pre-line" }}>
                  {words}
                </p>
                <div className="ui-actions">
                  <button
                    className="ui-btn"
                    onClick={() => {
                      // A browser without a clipboard here fails quietly; the words stay on screen.
                      void Promise.resolve()
                        .then(() => navigator.clipboard.writeText(words))
                        .then(() => {
                          setCopied(id);
                        })
                        .catch(() => {
                          setCopied(null);
                        });
                    }}
                    type="button"
                  >
                    {tt(language, copied === id ? "sbh_copied" : "sbh_copy")}
                  </button>
                  {allowed && (
                    <button
                      className="ui-btn primary"
                      disabled={busy}
                      onClick={() => {
                        onSent(
                          request,
                          what === "REMINDER" ? "REMINDER" : "CONFIRMATION",
                        );
                      }}
                      type="button"
                    >
                      {tt(language, "sbh_sent")}
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function VisitRequestsPageView({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultTelegramApi,
}: TelegramPageProps) {
  const page = usePage<VisitRequestsPage>(
    propertyId,
    active,
    api.visitRequests,
  );
  const [card, setCard] = useState<VisitCard>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  if (propertyId === "") return <NoProperty language={language} />;
  const head = (
    <div className="ui-head">
      <p>{tt(language, "vr_sub")}</p>
    </div>
  );
  if (page.data === null)
    return (
      <>
        {head}
        <Waiting failed={page.failed} language={language} onRetry={page.load} />
      </>
    );
  const data = page.data;
  const requests = data.requests.filter((request) =>
    inVisitCard(request, card),
  );
  const markSent = (
    request: VisitRequest,
    what: "CONFIRMATION" | "REMINDER",
  ) => {
    setBusy(true);
    setFailure(null);
    api.visitStep(propertyId, request.id, "sent", { what }).then(
      (done) => {
        setBusy(false);
        page.set(done.page);
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        setFailure(
          tt(
            language,
            status === 403 ? "e_403" : status === 409 ? "e_vr_stale" : "e_save",
          ),
        );
        page.load();
      },
    );
  };
  const cardName = VISIT_CARDS.find(([value]) => value === card)?.[3];
  return (
    <>
      {head}
      <div className="ui-kpis">
        {VISIT_CARDS.map(([value, icon, tone, key]) => (
          <CountCard
            icon={icon}
            key={value}
            label={tt(language, key)}
            note={textOf(language, "", `${key}_s`)}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={
              data.requests.filter((request) => inVisitCard(request, value))
                .length
            }
          />
        ))}
      </div>
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
      <SendByHand
        busy={busy}
        language={language}
        onSent={markSent}
        page={data}
      />
      <section aria-labelledby="vr-list" className="ui-card pad0">
        <div className="ui-listbar">
          <h2 id="vr-list">
            {tt(language, "vr_title")}{" "}
            <span className="ui-muted ui-num">
              {tt(language, "vr_n", requests.length)}
            </span>
          </h2>
          {cardName !== undefined && (
            <>
              <span className="ui-muted">
                {tt(language, "vr_showing", tt(language, cardName))}
              </span>
              <button
                className="ui-btn link"
                onClick={() => {
                  setCard("all");
                }}
                type="button"
              >
                {tt(language, "vr_show_all")}
              </button>
            </>
          )}
        </div>
        {requests.length === 0 ? (
          <p className="ui-empty">{tt(language, "vr_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{tt(language, "vr_col_req")}</th>
                  <th scope="col">{tt(language, "vr_col_wait")}</th>
                  <th scope="col">{tt(language, "vr_col_who")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "vr_col_ch")}
                  </th>
                  <th scope="col">{tt(language, "vr_col_wants")}</th>
                  <th scope="col">{tt(language, "vr_col_pref")}</th>
                  <th className="ui-wide" scope="col">
                    {tt(language, "vr_col_note")}
                  </th>
                  <th scope="col">{tt(language, "vr_col_status")}</th>
                  <th scope="col">{tt(language, "vr_col_staff")}</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => [
                  <tr
                    className="ui-row"
                    key={request.id}
                    onClick={() => {
                      setOpenId(request.id);
                    }}
                  >
                    <td>
                      <button
                        aria-label={tt(language, "vr_open", request.number)}
                        className="ui-btn link ui-num"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenId(request.id);
                        }}
                        type="button"
                      >
                        {request.number}
                      </button>
                      <span className="ui-sub2 ui-num">
                        {momentText(request.received_at)}
                      </span>
                    </td>
                    <td className="ui-num">{waited(language, request)}</td>
                    <InquiryCells inquiry={request} language={language} />
                    <td>
                      <Chip tone={statusTone(shownStatus(request))}>
                        {statusName(language, shownStatus(request))}
                      </Chip>
                    </td>
                    <td>{request.staff ?? tt(language, "vr_nobody")}</td>
                  </tr>,
                  ...request.joined.map((kid) => (
                    <tr className="ui-joined" key={kid.id}>
                      <td>
                        <span className="ui-num">{kid.number}</span>
                        <span className="ui-sub2">
                          {tt(language, "vr_joins", request.number)}
                        </span>
                      </td>
                      <td />
                      <InquiryCells inquiry={kid} language={language} />
                      <td>
                        <Chip tone="neutral">{tt(language, "vst_JOINED")}</Chip>
                      </td>
                      <td />
                    </tr>
                  )),
                ])}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {data.month !== null && (
        <MonthSection language={language} month={data.month} />
      )}
      <p className="ui-muted">{tt(language, "vr_how")}</p>
      {openId !== null && (
        <VisitRequestDialog
          api={api}
          mayReserve={
            capabilities === null ||
            (capabilities.has("reservations.create") &&
              capabilities.has("payments.record"))
          }
          language={language}
          onClose={() => {
            setOpenId(null);
          }}
          onPage={page.set}
          page={data}
          propertyId={propertyId}
          requestId={openId}
        />
      )}
    </>
  );
}

const VISIT_TIMES = Array.from({ length: 21 }, (_, index) => {
  const minutes = 7 * 60 + index * 30;
  const hour = String(Math.floor(minutes / 60)).padStart(2, "0");
  return `${hour}:${minutes % 60 === 0 ? "00" : "30"}`;
});

const CLOSE_REASONS = [
  "PRICE",
  "TYPE_NOT_FREE",
  "LOCATION",
  "FOUND_OTHER",
  "MOVE_IN_FAR",
  "OTHER",
] as const;

function historyLine(language: Language, step: VisitHistoryStep): string {
  switch (step.kind) {
    case "TAKEN":
      return tt(language, "h_TAKEN", step.staff ?? "");
    case "GIVEN":
      return tt(language, "h_GIVEN", step.staff ?? "");
    case "CALL":
      return tt(language, step.answered === true ? "h_CALL_yes" : "h_CALL_no");
    case "VISIT_BOOKED":
      return tt(
        language,
        "h_VISIT_BOOKED",
        tt(
          language,
          "d_shown_by",
          step.visit_at === null ? "" : momentText(step.visit_at),
          step.staff ?? "",
        ),
      );
    case "CLOSED":
      return tt(
        language,
        "h_CLOSED",
        textOf(language, "reason_", step.reason ?? ""),
      );
    case "SENT_BY_HAND":
      return tt(
        language,
        "h_SENT_BY_HAND",
        textOf(language, "what_", step.what ?? ""),
      );
    default:
      return textOf(language, "h_", step.kind);
  }
}

function VisitRequestDialog({
  language,
  propertyId,
  requestId,
  page,
  api,
  mayReserve,
  onClose,
  onPage,
}: {
  language: Language;
  propertyId: string;
  requestId: string;
  page: VisitRequestsPage;
  api: TelegramApi;
  /** Make Reservation needs reservations.create and payments.record (null rights: shown). */
  mayReserve: boolean;
  onClose: () => void;
  onPage: (next: VisitRequestsPage) => void;
}) {
  const [detail, setDetail] = useState<VisitRequestDetail | null>(null);
  const [readFailed, setReadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [day, setDay] = useState("");
  const [time, setTime] = useState("10:00");
  const [shower, setShower] = useState(page.me);
  const [reason, setReason] = useState<string>("PRICE");
  const [closeNote, setCloseNote] = useState("");
  const [reopenNote, setReopenNote] = useState("");
  const [spamNote, setSpamNote] = useState("");
  const [blockNote, setBlockNote] = useState("");
  const [giveTo, setGiveTo] = useState(page.workers[0]?.id ?? "");
  const [shown, setShown] = useState<string | null>(null);

  const read = useCallback(() => {
    setReadFailed(false);
    api.visitRequest(propertyId, requestId).then(setDetail, () => {
      setReadFailed(true);
    });
  }, [api, propertyId, requestId]);
  useEffect(() => {
    read();
  }, [read]);

  const step = (action: VisitAction, body: VisitStepBody = {}) => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    setDone(null);
    api.visitStep(propertyId, requestId, action, body).then(
      (answer) => {
        setBusy(false);
        setDetail(answer.request);
        onPage(answer.page);
        setShown(null);
        setDone(tt(language, "vr_saved"));
      },
      (error: unknown) => {
        setBusy(false);
        const status = error instanceof TelegramError ? error.status : null;
        if (status === 404 || status === 409) {
          setFailure(tt(language, "e_vr_stale"));
          read();
          return;
        }
        setFailure(tt(language, status === 403 ? "e_403" : "e_save"));
      },
    );
  };

  const title = detail === null ? "" : `${detail.number} · ${detail.name}`;
  if (detail === null)
    return (
      <Dialog
        closeLabel={tt(language, "close_dlg")}
        onClose={onClose}
        title={title}
      >
        <Waiting failed={readFailed} language={language} onRetry={read} />
      </Dialog>
    );

  const open = isOpen(detail);
  const manager = page.can_manage;
  const mayWork = page.can_work && (detail.mine || manager);
  const status = shownStatus(detail);
  const visitDayNow =
    detail.visit_local !== null &&
    detail.visit_local.slice(0, 10) <= page.today;
  const sunday = day !== "" && new Date(`${day}T12:00:00Z`).getUTCDay() === 0;
  const badDay = day === "" || day < page.today || sunday;
  const bookable = ["CONTACTED", "VISIT_BOOKED", "NO_SHOW", "VISITED"].includes(
    detail.status,
  );
  const needs = (value: string) => value.trim() === "";

  return (
    <Dialog
      busy={busy}
      closeLabel={tt(language, "close_dlg")}
      onClose={onClose}
      title={title}
      wide
    >
      <p>
        <Chip tone={statusTone(status)}>{statusName(language, status)}</Chip>
      </p>
      {detail.removed && (
        <div className="ui-notice info" role="status">
          <Icon name="info" />
          <p>{tt(language, "d_removed")}</p>
        </div>
      )}
      {detail.blocked && (
        <div className="ui-notice warn" role="status">
          <Icon name="lock" />
          <p>{tt(language, "d_blocked")}</p>
        </div>
      )}
      {detail.reservation_id !== null && (
        <div className="ui-actions">
          <a
            className="ui-btn"
            href={`#/reservations/${encodeURIComponent(detail.reservation_id)}`}
          >
            {tt(language, "d_res_open")}
          </a>
        </div>
      )}
      <Done text={done} />
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
      <dl className="ui-kv">
        <dt>{tt(language, "d_phone")}</dt>
        <dd className="ui-num">{detail.phone}</dd>
        <dt>{tt(language, "vr_col_ch")}</dt>
        <dd>
          {contactBy(language, detail)}
          {detail.email !== null && ` (${detail.email})`}
        </dd>
        <dt>{tt(language, "vr_col_wants")}</dt>
        <dd>
          {unitTypeName(language, detail)} ·{" "}
          {tt(language, "vr_movein", moveIn(language, detail))}
        </dd>
        <dt>{tt(language, "vr_col_pref")}</dt>
        <dd>{prefers(language, detail)}</dd>
        {detail.note !== null && (
          <>
            <dt>{tt(language, "vr_col_note")}</dt>
            <dd>{detail.note}</dd>
          </>
        )}
        <dt>{tt(language, "d_arrived")}</dt>
        <dd className="ui-num">{momentText(detail.received_at)}</dd>
        <dt>{tt(language, "vr_col_staff")}</dt>
        <dd>{detail.staff ?? tt(language, "vr_nobody")}</dd>
        {detail.visit_local !== null && (
          <>
            <dt>{tt(language, "d_visit")}</dt>
            <dd>
              {tt(
                language,
                "d_shown_by",
                visitText(language, detail.visit_local),
                detail.visit_staff ?? "",
              )}
            </dd>
          </>
        )}
        <dt>{tt(language, "d_calls")}</dt>
        <dd className="ui-num">{detail.calls}</dd>
        {detail.reason !== null && (
          <>
            <dt>{tt(language, "d_reason")}</dt>
            <dd>
              {textOf(language, "reason_", detail.reason)}
              {detail.close_note !== null && ` · ${detail.close_note}`}
            </dd>
          </>
        )}
      </dl>

      {open && page.can_work && detail.staff_id === null && (
        <div className="ui-actions">
          <button
            className="ui-btn primary"
            disabled={busy}
            onClick={() => {
              step("take");
            }}
            type="button"
          >
            {tt(language, "d_take")}
          </button>
        </div>
      )}
      {open && detail.staff_id !== null && !mayWork && (
        <div className="ui-notice info" role="status">
          <Icon name="info" />
          <p>{tt(language, "d_has", detail.staff ?? "")}</p>
        </div>
      )}

      {open && detail.staff_id !== null && mayWork && (
        <>
          <fieldset className="ui-card">
            <legend>{tt(language, "d_call")}</legend>
            <div className="ui-actions">
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  step("call", { answered: true });
                }}
                type="button"
              >
                {tt(language, "d_answered")}
              </button>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  step("call", { answered: false });
                }}
                type="button"
              >
                {tt(language, "d_no_answer")}
              </button>
              <span className="ui-muted">
                {tt(language, "d_no_days", detail.no_answer_days)}
              </span>
              {detail.no_answer_days >= 3 && (
                <button
                  className="ui-btn danger"
                  disabled={busy}
                  onClick={() => {
                    step("close", { reason: "NO_REACH" });
                  }}
                  type="button"
                >
                  {tt(language, "d_no_reach")}
                </button>
              )}
            </div>
          </fieldset>

          {bookable && (
            <fieldset className="ui-card">
              <legend>
                {tt(
                  language,
                  detail.visit_local === null ? "d_book" : "d_move",
                )}
              </legend>
              <div className="ui-hrow">
                <div className="ui-field">
                  <label htmlFor="vr-day">{tt(language, "d_day")}</label>
                  <input
                    aria-invalid={shown === "book" && badDay}
                    disabled={busy}
                    id="vr-day"
                    min={page.today}
                    onChange={(event) => {
                      setDay(event.currentTarget.value);
                    }}
                    type="date"
                    value={day}
                  />
                </div>
                <div className="ui-field">
                  <label htmlFor="vr-time">{tt(language, "d_time")}</label>
                  <select
                    disabled={busy}
                    id="vr-time"
                    onChange={(event) => {
                      setTime(event.currentTarget.value);
                    }}
                    value={time}
                  >
                    {VISIT_TIMES.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="ui-field">
                  <label htmlFor="vr-shower">{tt(language, "d_shows")}</label>
                  <select
                    disabled={busy}
                    id="vr-shower"
                    onChange={(event) => {
                      setShower(event.currentTarget.value);
                    }}
                    value={shower}
                  >
                    {page.workers.map((worker) => (
                      <option key={worker.id} value={worker.id}>
                        {worker.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <p className="help">
                {tt(language, "d_book_help")}{" "}
                {tt(
                  language,
                  detail.contact_by === "TELEGRAM"
                    ? "d_bot_sends"
                    : "d_hand_sends",
                )}
              </p>
              {shown === "book" && badDay && (
                <p className="ui-error">{tt(language, "e_day")}</p>
              )}
              <button
                className="ui-btn primary"
                disabled={busy}
                onClick={() => {
                  setShown("book");
                  if (badDay) return;
                  step("book", {
                    visit_at: `${day}T${time}`,
                    staff_id: shower,
                  });
                }}
                type="button"
              >
                {tt(
                  language,
                  detail.visit_local === null ? "d_book_btn" : "d_move_btn",
                )}
              </button>
            </fieldset>
          )}

          {mayReserve &&
            ["CONTACTED", "VISIT_BOOKED", "VISITED", "NO_SHOW"].includes(
              detail.status,
            ) && (
              <div className="ui-actions">
                <button
                  className="ui-btn primary"
                  disabled={busy}
                  onClick={() => {
                    onClose();
                    openPageInAddress(
                      "reservations",
                      false,
                      `visit:${detail.id}`,
                    );
                  }}
                  type="button"
                >
                  {tt(language, "d_make_res")}
                </button>
              </div>
            )}
          {detail.status === "VISIT_BOOKED" && visitDayNow && (
            <div className="ui-actions">
              <button
                className="ui-btn primary"
                disabled={busy}
                onClick={() => {
                  step("visited");
                }}
                type="button"
              >
                {tt(language, "d_visited")}
              </button>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  step("no-show");
                }}
                type="button"
              >
                {tt(language, "d_no_show")}
              </button>
            </div>
          )}

          <fieldset className="ui-card">
            <legend>{tt(language, "d_close")}</legend>
            <div className="ui-hrow">
              <div className="ui-field">
                <label htmlFor="vr-reason">{tt(language, "d_reason_l")}</label>
                <select
                  disabled={busy}
                  id="vr-reason"
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                  }}
                  value={reason}
                >
                  {CLOSE_REASONS.map((value) => (
                    <option key={value} value={value}>
                      {textOf(language, "reason_", value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="ui-field">
                <label htmlFor="vr-close-note">
                  {tt(language, "d_note_l")}
                </label>
                <input
                  aria-invalid={shown === "close" && needs(closeNote)}
                  disabled={busy}
                  id="vr-close-note"
                  maxLength={300}
                  onChange={(event) => {
                    setCloseNote(event.currentTarget.value);
                  }}
                  value={closeNote}
                />
              </div>
            </div>
            {shown === "close" && reason === "OTHER" && needs(closeNote) && (
              <p className="ui-error">{tt(language, "e_note")}</p>
            )}
            <div className="ui-actions">
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  setShown("close");
                  if (reason === "OTHER" && needs(closeNote)) return;
                  step("close", {
                    reason,
                    ...(needs(closeNote) ? {} : { note: closeNote.trim() }),
                  });
                }}
                type="button"
              >
                {tt(language, "d_close_btn")}
              </button>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  step("close", { reason: "CANCELLED" });
                }}
                type="button"
              >
                {tt(language, "d_cancelled")}
              </button>
            </div>
          </fieldset>
        </>
      )}

      {open && manager && (
        <fieldset className="ui-card">
          <legend>{tt(language, "d_manager")}</legend>
          <div className="ui-hrow">
            <div className="ui-field">
              <label htmlFor="vr-give">{tt(language, "d_give")}</label>
              <select
                disabled={busy}
                id="vr-give"
                onChange={(event) => {
                  setGiveTo(event.currentTarget.value);
                }}
                value={giveTo}
              >
                {page.workers.map((worker) => (
                  <option key={worker.id} value={worker.id}>
                    {worker.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              className="ui-btn"
              disabled={busy || giveTo === ""}
              onClick={() => {
                step("give", { staff_id: giveTo });
              }}
              type="button"
            >
              {tt(language, "d_give")}
            </button>
          </div>
          {detail.status !== "VISIT_BOOKED" && (
            <div className="ui-hrow">
              <div className="ui-field">
                <label htmlFor="vr-spam">{tt(language, "d_spam_l")}</label>
                <input
                  aria-invalid={shown === "spam" && needs(spamNote)}
                  disabled={busy}
                  id="vr-spam"
                  maxLength={300}
                  onChange={(event) => {
                    setSpamNote(event.currentTarget.value);
                  }}
                  value={spamNote}
                />
              </div>
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  setShown("spam");
                  if (needs(spamNote)) return;
                  step("spam", { note: spamNote.trim() });
                }}
                type="button"
              >
                {tt(language, "d_spam")}
              </button>
            </div>
          )}
          {shown === "spam" && needs(spamNote) && (
            <p className="ui-error">{tt(language, "e_note")}</p>
          )}
        </fieldset>
      )}

      {!open &&
        page.can_work &&
        (manager || (detail.status === "CLOSED" && detail.mine)) && (
          <fieldset className="ui-card">
            <legend>{tt(language, "d_reopen")}</legend>
            <div className="ui-hrow">
              <div className="ui-field">
                <label htmlFor="vr-reopen">{tt(language, "d_reopen_l")}</label>
                <input
                  aria-invalid={shown === "reopen" && needs(reopenNote)}
                  disabled={busy}
                  id="vr-reopen"
                  maxLength={300}
                  onChange={(event) => {
                    setReopenNote(event.currentTarget.value);
                  }}
                  value={reopenNote}
                />
              </div>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  setShown("reopen");
                  if (needs(reopenNote)) return;
                  step("reopen", { note: reopenNote.trim() });
                }}
                type="button"
              >
                {tt(language, "d_reopen")}
              </button>
            </div>
            {shown === "reopen" && needs(reopenNote) && (
              <p className="ui-error">{tt(language, "e_note")}</p>
            )}
          </fieldset>
        )}

      {manager && !detail.removed && (
        <fieldset className="ui-card">
          <legend>
            {tt(language, detail.blocked ? "d_unblock" : "d_block")}
          </legend>
          {detail.blocked ? (
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                step("unblock");
              }}
              type="button"
            >
              {tt(language, "d_unblock")}
            </button>
          ) : (
            <div className="ui-hrow">
              <div className="ui-field">
                <label htmlFor="vr-block">{tt(language, "d_block_l")}</label>
                <input
                  aria-invalid={shown === "block" && needs(blockNote)}
                  disabled={busy}
                  id="vr-block"
                  maxLength={300}
                  onChange={(event) => {
                    setBlockNote(event.currentTarget.value);
                  }}
                  value={blockNote}
                />
              </div>
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  setShown("block");
                  if (needs(blockNote)) return;
                  step("block", { note: blockNote.trim() });
                }}
                type="button"
              >
                {tt(language, "d_block")}
              </button>
            </div>
          )}
          {shown === "block" && needs(blockNote) && (
            <p className="ui-error">{tt(language, "e_note")}</p>
          )}
        </fieldset>
      )}

      <h3>{tt(language, "d_hist")}</h3>
      <ul className="ui-timeline">
        {detail.history.map((item, index) => (
          <li key={`${item.at}-${String(index)}`}>
            <div>
              {historyLine(language, item)}
              {item.note !== null && ` · ${item.note}`}
              <small>
                {momentText(item.at)} · {tt(language, "h_by", item.by ?? "")}
                {item.sent_by_bot && ` · ${tt(language, "h_bot")}`}
              </small>
            </div>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
