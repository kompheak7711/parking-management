// DL-238 (owner 14 Nov 2026): the short-stay tab of Notices. The Tenant bot sends guests the
// check-out reminder, the late check-out notice and a note of a charge still unpaid by itself;
// the front desk gives house-rule warnings (1, then the final 2) and marks a notice told to a
// guest with no Telegram. Nothing here ends a stay or adds a charge.

import "./guestNotices.css";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import type {
  GuestNotice,
  GuestNotices,
  GuestNoticesApi,
  WarnableStay,
} from "../shortstays/shortStaysClient";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, CountCard, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { ltr } from "./text";

type Only = "all" | "tell" | "stays" | "warned";

export function GuestNoticesTab({
  language,
  propertyId,
  active,
  api,
  canGive,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: GuestNoticesApi;
  canGive: boolean;
}) {
  const [data, setData] = useState<GuestNotices | null>(null);
  const [failed, setFailed] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [giving, setGiving] = useState<string | null | undefined>(undefined);
  const [telling, setTelling] = useState<string | null>(null);
  // A count card shows only its notices; pressed again, all show.
  const [only, setOnly] = useState<Only>("all");
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    api
      .notices(propertyId)
      .then((found) => {
        if (operation === sequence.current) setData(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId]);

  useEffect(() => {
    sequence.current++;
    setData(null);
  }, [propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  function told(notice: GuestNotice) {
    if (telling !== null) return;
    setTelling(notice.notice_id);
    setToast(null);
    api
      .told(propertyId, notice.notice_id)
      .then((found) => {
        setData(found);
        setToast(
          ltr(
            language,
            "ss_told_toast",
            `${notice.unit_number} · ${notice.guest_name}`,
          ),
        );
      })
      .catch(() => {
        setToast(ltr(language, "ss_save_e"));
        load();
      })
      .finally(() => {
        setTelling(null);
      });
  }

  if (data === null) {
    return failed ? (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ltr(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {ltr(language, "retry")}
        </button>
      </div>
    ) : (
      <p className="ui-muted" role="status">
        {ltr(language, "loading")}
      </p>
    );
  }

  const toTell = data.notices.filter(
    (notice) =>
      (notice.telegram === "NO_TELEGRAM" ||
        notice.telegram === "NOT_DELIVERED") &&
      notice.told_at === null,
  );
  const warned = data.stays.filter((stay) => stay.warnings > 0).length;
  const inside = new Set(data.stays.map((stay) => stay.booking_id));
  const shown = data.notices.filter((notice) =>
    only === "tell"
      ? toTell.includes(notice)
      : only === "stays"
        ? inside.has(notice.booking_id)
        : only === "warned"
          ? notice.kind === "HOUSE_RULE_WARNING" &&
            inside.has(notice.booking_id)
          : true,
  );
  const press = (value: Only) => () => {
    setOnly((now) => (now === value ? "all" : value));
  };

  return (
    <>
      {toast !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{toast}</p>
        </div>
      )}
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>
          {ltr(
            language,
            "ss_rule",
            data.rules.reminder_at,
            data.rules.late_after_minutes,
            data.rules.unpaid_at,
          )}
        </p>
      </div>
      <div className="ui-kpis">
        <CountCard
          icon="phone"
          label={ltr(language, "ss_c_tell")}
          onPress={press("tell")}
          pressed={only === "tell"}
          tone={toTell.length > 0 ? "warn" : "none"}
          value={toTell.length}
        />
        <CountCard
          icon="customers"
          label={ltr(language, "ss_c_stays")}
          onPress={press("stays")}
          pressed={only === "stays"}
          tone="none"
          value={data.stays.length}
        />
        <CountCard
          icon="alert"
          label={ltr(language, "ss_c_warned")}
          onPress={press("warned")}
          pressed={only === "warned"}
          tone={warned > 0 ? "warn" : "none"}
          value={warned}
        />
      </div>
      <div className="ui-card pad0">
        <div className="ui-chead pad">
          <h2>{ltr(language, "tab_ss")}</h2>
          {canGive && (
            <button
              className="ui-btn primary"
              onClick={() => {
                setToast(null);
                setGiving(null);
              }}
              type="button"
            >
              <Icon name="plus" />
              {ltr(language, "ss_new")}
            </button>
          )}
        </div>
        {shown.length === 0 ? (
          <p className="ui-empty">
            {ltr(language, "ss_none", data.rules.days)}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table fit ui-pcards gn-list">
              <thead>
                <tr>
                  <th scope="col">{ltr(language, "ss_col_when")}</th>
                  <th scope="col">{ltr(language, "ss_col_guest")}</th>
                  <th scope="col">{ltr(language, "ss_col_notice")}</th>
                  <th scope="col">{ltr(language, "ss_col_sent")}</th>
                  {canGive && (
                    <th scope="col">
                      <span className="ui-sr">
                        {ltr(language, "ss_told_btn")}
                      </span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {shown.map((notice) => (
                  <tr key={notice.notice_id}>
                    <td className="ui-num pc-small">
                      {dayText(notice.notice_on)}
                    </td>
                    <td className="pc-full">
                      <a
                        className="ui-no ui-num"
                        href={hashForPage(
                          "shortstays",
                          `st:${notice.booking_id}`,
                        )}
                      >
                        {notice.unit_number}
                      </a>{" "}
                      · {notice.guest_name}
                      <span className="ui-sub2">{notice.booking_number}</span>
                    </td>
                    <td className="wrap pc-full">
                      <NoticeWhat language={language} notice={notice} />
                    </td>
                    <td>
                      <Reached language={language} notice={notice} />
                    </td>
                    {canGive && (
                      <td className="pc-end">
                        {(notice.telegram === "NO_TELEGRAM" ||
                          notice.telegram === "NOT_DELIVERED") &&
                          notice.told_at === null && (
                            <button
                              className="ui-btn"
                              disabled={telling !== null}
                              onClick={() => {
                                told(notice);
                              }}
                              type="button"
                            >
                              <Icon name="check" />
                              {ltr(language, "ss_told_btn")}
                            </button>
                          )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {giving !== undefined && (
        <GiveWarningDialog
          api={api}
          bookingId={giving}
          language={language}
          onClose={() => {
            setGiving(undefined);
          }}
          onSaved={(message) => {
            setGiving(undefined);
            setToast(message);
            load();
          }}
          propertyId={propertyId}
          stays={data.stays}
        />
      )}
    </>
  );
}

function NoticeWhat({
  language,
  notice,
}: {
  language: Language;
  notice: GuestNotice;
}) {
  let name: string;
  let detail: string | null = null;
  switch (notice.kind) {
    case "CHECK_OUT_REMINDER":
      name = ltr(language, "k_CHECK_OUT_REMINDER");
      detail = ltr(language, "ss_d_out", dayText(notice.check_out_on));
      break;
    case "LATE_CHECK_OUT":
      name = ltr(language, "k_LATE_CHECK_OUT");
      detail =
        notice.time === null ? null : ltr(language, "ss_d_late", notice.time);
      break;
    case "HOUSE_RULE_WARNING":
      name =
        notice.warning_number === 2
          ? ltr(language, "k_final")
          : ltr(language, "k_HOUSE_RULE_WARNING", notice.warning_number ?? 1);
      detail = notice.reason;
      break;
    case "UNPAID_CHARGE":
      name = ltr(language, "k_UNPAID_CHARGE");
      detail =
        notice.invoice_number === null
          ? null
          : ltr(
              language,
              "ss_d_unpaid",
              notice.invoice_number,
              notice.amount ?? "",
            );
      break;
  }
  const by = notice.automatic
    ? ltr(language, "ss_d_auto")
    : notice.given_by_name === null
      ? null
      : ltr(language, "ss_d_by", notice.given_by_name);
  return (
    <>
      <strong>{name}</strong>
      {detail !== null && <span className="ui-sub2">{detail}</span>}
      {by !== null && <span className="ui-sub2">{by}</span>}
    </>
  );
}

function Reached({
  language,
  notice,
}: {
  language: Language;
  notice: GuestNotice;
}) {
  if (notice.told_at !== null) {
    return (
      <Chip icon="check" tone="ok">
        {ltr(
          language,
          "ss_told",
          notice.told_by_name ?? "—",
          dayText(notice.told_at.slice(0, 10)),
        )}
      </Chip>
    );
  }
  switch (notice.telegram) {
    case "SENT":
      return (
        <Chip icon="check" tone="ok">
          {ltr(language, "t_SENT")}
        </Chip>
      );
    case "WAITING":
      return <Chip tone="info">{ltr(language, "t_WAITING")}</Chip>;
    case "NOT_DELIVERED":
      return (
        <Chip icon="alert" tone="err">
          {ltr(language, "t_NOT_DELIVERED")}
        </Chip>
      );
    case "NO_TELEGRAM":
      return (
        <Chip icon="alert" tone="warn">
          {ltr(language, "t_NO_TELEGRAM")}
        </Chip>
      );
  }
}

function GiveWarningDialog({
  language,
  api,
  propertyId,
  stays,
  bookingId,
  onClose,
  onSaved,
}: {
  language: Language;
  api: Pick<GuestNoticesApi, "warn">;
  propertyId: string;
  stays: WarnableStay[];
  bookingId: string | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const open = stays.filter((stay) => stay.warnings < 2);
  const [chosen, setChosen] = useState(
    open.find((stay) => stay.booking_id === bookingId)?.booking_id ??
      open[0]?.booking_id ??
      "",
  );
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stay = open.find((item) => item.booking_id === chosen);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || stay === undefined) return;
    const why = reason.trim();
    if (why === "") {
      setProblem(ltr(language, "ss_d_reason_e"));
      return;
    }
    setProblem(null);
    setBusy(true);
    api
      .warn(propertyId, stay.booking_id, why)
      .then((given) => {
        const who = `${stay.unit_number} · ${stay.guest_name}`;
        onSaved(
          given.telegram_messages > 0
            ? ltr(language, "ss_toast_tg", given.warning_number, who)
            : ltr(language, "ss_toast_person", given.warning_number, who),
        );
      })
      .catch(() => {
        setBusy(false);
        setProblem(ltr(language, "ss_save_e"));
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ltr(language, "close")}
      onClose={onClose}
      onSubmit={open.length === 0 ? undefined : submit}
      submitLabel={busy ? ltr(language, "saving") : ltr(language, "ss_new")}
      title={ltr(language, "ss_d_t")}
    >
      {open.length === 0 ? (
        <p>{ltr(language, "ss_d_no_stay")}</p>
      ) : (
        <>
          <div className="ui-field">
            <label htmlFor="guest-warning-stay">
              {ltr(language, "ss_d_guest")}
              <span className="req">{ltr(language, "required")}</span>
            </label>
            <select
              id="guest-warning-stay"
              onChange={(event) => {
                setChosen(event.currentTarget.value);
              }}
              value={chosen}
            >
              {stays.map((item) => (
                <option
                  disabled={item.warnings >= 2}
                  key={item.booking_id}
                  value={item.booking_id}
                >
                  {item.unit_number} · {item.guest_name}
                  {item.warnings >= 2 && ` (${ltr(language, "ss_d_full")})`}
                </option>
              ))}
            </select>
          </div>
          {stay !== undefined && (
            <div
              className={`ui-notice ${stay.warnings >= 1 ? "warn" : ""}`}
              role="note"
            >
              <Icon name={stay.warnings >= 1 ? "alert" : "info"} />
              <p>
                {ltr(
                  language,
                  stay.warnings >= 1 ? "ss_d_next2" : "ss_d_next1",
                )}
                {!stay.telegram && <> {ltr(language, "ss_d_no_tg")}</>}
              </p>
            </div>
          )}
          <div className="ui-field">
            <label htmlFor="guest-warning-reason">
              {ltr(language, "ss_d_reason")}
              <span className="req">{ltr(language, "required")}</span>
            </label>
            <textarea
              aria-invalid={problem !== null && reason.trim() === ""}
              id="guest-warning-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              rows={3}
              value={reason}
            />
          </div>
          {problem !== null && (
            <p className="ui-error" role="alert">
              <Icon name="alert" small />
              <span>{problem}</span>
            </p>
          )}
        </>
      )}
    </Dialog>
  );
}
