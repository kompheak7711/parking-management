// Daily and weekly rent, phase 6 step 5c: Tenants › Short stays › Weekly report (migration
// 20270608_318, mock-up round 28 "ss33rep"). The PRD's measures of the test, week by week: paid
// unit-nights, income per Unit after cleaning, laundry and booking-site costs, guests who signed a
// Lease, damage and complaints from monthly tenants. Owner and Manager only; the desk records a
// complaint here too.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import {
  addDays,
  type CalendarUnit,
  type ShortStaysApi,
  type WeekReport as Report,
} from "./shortStaysClient";
import { st } from "./text";

/** The Monday of the week of an ISO day. */
export function mondayOf(day: string): string {
  const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
  return addDays(day, -((weekday + 6) % 7));
}

/** Basis points as "42.5%". */
function percent(points: number): string {
  return `${(points / 100).toFixed(1)}%`;
}

export function WeekReport({
  language,
  propertyId,
  api,
  may,
  today,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
  today: string;
}) {
  const [from, setFrom] = useState(mondayOf(today));
  const [report, setReport] = useState<Report | null>(null);
  const [units, setUnits] = useState<CalendarUnit[]>([]);
  const [failed, setFailed] = useState(false);
  const [what, setWhat] = useState("");
  const [unitId, setUnitId] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    setReport(null);
    void Promise.all([
      api.weekReport(propertyId, from),
      api.calendar(propertyId, today, 1),
    ])
      .then(([found, calendar]) => {
        if (operation !== sequence.current) return;
        setReport(found);
        setUnits(calendar.units);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, from, today]);

  useEffect(() => {
    load();
  }, [load]);

  const record = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (what.trim() === "" || busy) return;
    setBusy(true);
    setSaveFailed(false);
    void api
      .complaint(propertyId, {
        what: what.trim(),
        ...(unitId === "" ? {} : { unit_id: unitId }),
      })
      .then(() => {
        setWhat("");
        setUnitId("");
        setChecked(false);
        load();
      })
      .catch(() => {
        setSaveFailed(true);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const nextFrom = addDays(from, 7);
  const tools = (
    <div className="ui-filters">
      <h2 className="ui-num" data-record-title="">
        {st(language, "rp_week", dayText(from), dayText(addDays(from, 6)))}
        {report?.so_far === true && (
          <span className="ui-small ui-muted">
            {" "}
            {st(language, "rp_so_far")}
          </span>
        )}
      </h2>
      <div className="ui-actions">
        <button
          className="ui-btn"
          onClick={() => {
            setFrom(addDays(from, -7));
          }}
          type="button"
        >
          <Icon name="back" small />
          {st(language, "rp_prev")}
        </button>
        <button
          className="ui-btn"
          disabled={nextFrom > today}
          onClick={() => {
            setFrom(nextFrom);
          }}
          type="button"
        >
          {st(language, "rp_next")}
        </button>
        <button
          className="ui-btn"
          onClick={() => {
            window.print();
          }}
          type="button"
        >
          {st(language, "rp_print")}
        </button>
      </div>
    </div>
  );

  if (failed)
    return (
      <>
        {tools}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{st(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {st(language, "retry")}
          </button>
        </div>
      </>
    );
  if (report === null)
    return (
      <>
        {tools}
        <p className="ui-muted" role="status">
          {st(language, "loading")}
        </p>
      </>
    );
  const totals = report.totals;
  const above = totals.occupancy_points >= report.base_occupancy_points;
  return (
    <>
      <p className="ui-small ui-muted">{st(language, "rp_sub")}</p>
      {tools}
      <div className="ui-kpis">
        <div className={`ui-kpi ss-static ${above ? "ok" : "warn"}`}>
          <span className="ui-kpi-label">{st(language, "rp_occ")}</span>
          <b className="ui-kpi-value ui-num">
            {percent(totals.occupancy_points)}
          </b>
          <small className="ui-kpi-note">
            {st(
              language,
              "rp_occ_s",
              totals.nights,
              totals.unit_nights,
              percent(report.base_occupancy_points),
            )}
          </small>
        </div>
        <div className="ui-kpi ss-static">
          <span className="ui-kpi-label">{st(language, "rp_net")}</span>
          <b className="ui-kpi-value ui-num">
            {usdFromCents(totals.net_usd_cents)}
          </b>
          <small className="ui-kpi-note">
            {st(language, "rp_net_s", usdFromCents(totals.income_usd_cents))}
          </small>
        </div>
        <div className="ui-kpi ss-static">
          <span className="ui-kpi-label">{st(language, "rp_lease")}</span>
          <b className="ui-kpi-value ui-num">{report.leases.length}</b>
          <small className="ui-kpi-note">{st(language, "rp_lease_s")}</small>
        </div>
        <div className="ui-kpi ss-static">
          <span className="ui-kpi-label">{st(language, "rp_dmg")}</span>
          <b className="ui-kpi-value ui-num">
            {report.damages.length + report.complaints.length}
          </b>
          <small className="ui-kpi-note">
            {st(
              language,
              "rp_dmg_s",
              report.damages.length,
              report.complaints.length,
            )}
          </small>
        </div>
      </div>
      <div className="ui-card pad0 ui-tablewrap">
        <table className="ui-table">
          <caption className="ui-sr">{st(language, "tab_report")}</caption>
          <thead>
            <tr>
              <th scope="col">{st(language, "c_unit")}</th>
              <th className="r" scope="col">
                {st(language, "rp_nights")}
              </th>
              <th className="r" scope="col">
                {st(language, "rp_occ")}
              </th>
              <th className="r" scope="col">
                {st(language, "rp_income")}
              </th>
              <th className="r" scope="col">
                {st(language, "rp_site")}
              </th>
              <th className="r" scope="col">
                {st(language, "rp_clean")}
              </th>
              <th className="r" scope="col">
                {st(language, "rp_after")}
              </th>
            </tr>
          </thead>
          <tbody>
            {report.units.map((unit) => (
              <tr key={unit.unit_id}>
                <th className="ui-num" scope="row">
                  {unit.unit_number}
                </th>
                <td className="r ui-num">{unit.nights}</td>
                <td className="r ui-num">
                  {percent(Math.floor((unit.nights * 10000) / 7))}
                </td>
                <td className="r ui-num">
                  {usdFromCents(unit.income_usd_cents)}
                </td>
                <td className="r ui-num">
                  {usdFromCents(unit.site_fees_usd_cents)}
                </td>
                <td className="r ui-num">
                  {usdFromCents(unit.cleaning_usd_cents)}
                </td>
                <td className="r ui-num">
                  <b>{usdFromCents(unit.net_usd_cents)}</b>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{st(language, "rp_all")}</th>
              <td className="r ui-num">{totals.nights}</td>
              <td className="r ui-num">{percent(totals.occupancy_points)}</td>
              <td className="r ui-num">
                {usdFromCents(totals.income_usd_cents)}
              </td>
              <td className="r ui-num">
                {usdFromCents(totals.site_fees_usd_cents)}
              </td>
              <td className="r ui-num">
                {usdFromCents(totals.cleaning_usd_cents)}
              </td>
              <td className="r ui-num">
                <b>{usdFromCents(totals.net_usd_cents)}</b>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="ui-small ui-muted">
        {st(
          language,
          "rp_note",
          usdFromCents(report.change_over_usd_cents),
          usdFromCents(report.linen_usd_cents),
        )}
      </p>
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="rp-leases" className="ui-card">
            <h2 id="rp-leases">{st(language, "rp_leases_t")}</h2>
            {report.leases.length === 0 ? (
              <p className="ui-small ui-muted">{st(language, "rp_none")}</p>
            ) : (
              <ul className="ui-plain ss-ready">
                {report.leases.map((lease) => (
                  <li key={lease.booking_id}>
                    <a
                      href={hashForPage("shortstays", `st:${lease.booking_id}`)}
                    >
                      {lease.guest_name}
                    </a>
                    <span className="ui-num">
                      {st(
                        language,
                        "rp_lease_row",
                        lease.booking_number,
                        lease.lease_unit_number,
                        usdFromCents(lease.off_usd_cents),
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="rp-damage" className="ui-card">
            <h2 id="rp-damage">{st(language, "rp_damage_t")}</h2>
            {report.damages.length === 0 ? (
              <p className="ui-small ui-muted">{st(language, "rp_none")}</p>
            ) : (
              <ul className="ui-plain ss-ready">
                {report.damages.map((damage) => (
                  <li key={damage.damage_id}>
                    <a
                      className="ui-num"
                      href={hashForPage(
                        "shortstays",
                        `st:${damage.booking_id}`,
                      )}
                    >
                      {damage.booking_number}
                    </a>
                    <span>
                      {damage.unit_number} · {damage.description}
                    </span>
                    <span className="ui-num">
                      {usdFromCents(damage.amount_usd_cents)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="rp-compl" className="ui-card">
            <h2 id="rp-compl">{st(language, "rp_compl_t")}</h2>
            {report.complaints.length === 0 ? (
              <p className="ui-small ui-muted">{st(language, "rp_none")}</p>
            ) : (
              <ul className="ui-plain ss-notes">
                {report.complaints.map((complaint) => (
                  <li key={complaint.complaint_id}>
                    <small className="ui-num ui-muted">
                      {dayText(complaint.noted_on)}
                      {complaint.unit_number !== null &&
                        ` · ${complaint.unit_number}`}
                    </small>
                    <span className="note">{complaint.what}</span>
                  </li>
                ))}
              </ul>
            )}
            {may("short_stays.desk") && (
              <form className="ui-form ss-form" noValidate onSubmit={record}>
                <h3>{st(language, "cp_add")}</h3>
                <div className="ui-field">
                  <label htmlFor="cp-what">{st(language, "cp_what")}</label>
                  <input
                    aria-invalid={checked && what.trim() === ""}
                    autoComplete="off"
                    disabled={busy}
                    id="cp-what"
                    maxLength={500}
                    onChange={(event) => {
                      setWhat(event.currentTarget.value);
                    }}
                    value={what}
                  />
                  {checked && what.trim() === "" && (
                    <p className="ui-error">
                      <Icon name="alert" small />
                      <span>{st(language, "cp_empty")}</span>
                    </p>
                  )}
                </div>
                <div className="ui-field">
                  <label htmlFor="cp-unit">{st(language, "cp_unit")}</label>
                  <select
                    className="ui-sel"
                    disabled={busy}
                    id="cp-unit"
                    onChange={(event) => {
                      setUnitId(event.currentTarget.value);
                    }}
                    value={unitId}
                  >
                    <option value="">{st(language, "cp_none_unit")}</option>
                    {units.map((unit) => (
                      <option key={unit.unit_id} value={unit.unit_id}>
                        {unit.unit_number}
                      </option>
                    ))}
                  </select>
                </div>
                {saveFailed && (
                  <p className="ui-error" role="alert">
                    <Icon name="alert" small />
                    <span>{st(language, "f_failed")}</span>
                  </p>
                )}
                <div className="ui-actions">
                  <button className="ui-btn" disabled={busy} type="submit">
                    {st(language, "cp_save")}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
        <div className="ui-stack">
          <section aria-labelledby="rp-src" className="ui-card">
            <h2 id="rp-src">{st(language, "rp_src_t")}</h2>
            {report.sources.length === 0 ? (
              <p className="ui-small ui-muted">{st(language, "rp_none")}</p>
            ) : (
              <ul className="ui-plain ss-lines">
                {report.sources.map((source) => (
                  <li key={`${source.source}:${source.site_name ?? ""}`}>
                    <span>
                      {source.source === "BOOKING_SITE" &&
                      source.site_name !== null
                        ? source.site_name
                        : st(language, `src_${source.source}`)}
                    </span>
                    <span className="ui-num">{source.stays}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="ui-small ui-muted">
              {st(
                language,
                "rp_cancel",
                report.cancellations.count,
                usdFromCents(report.cancellations.kept_usd_cents),
              )}
            </p>
          </section>
          <section aria-labelledby="rp-judge" className="ui-card">
            <h2 id="rp-judge">{st(language, "rp_judge_t")}</h2>
            <p className="ui-small">
              {st(language, "rp_judge", percent(report.base_occupancy_points))}
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
