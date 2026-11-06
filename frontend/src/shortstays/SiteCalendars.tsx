// Daily and weekly rent, phase 6 step 5a: Tenants › Short stays › Booking sites. The Owner and the
// Manager (short_stays.approve) paste each room's calendar link from Booking.com, Agoda or Airbnb;
// the app reads it every 15 minutes and keeps those nights for that site only.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { SITES } from "./NewBooking";
import {
  type CalendarUnit,
  type ShortStaysApi,
  ShortStaysError,
  type SiteCalendar,
  type SiteCalendarSave,
} from "./shortStaysClient";
import { st, type StaysTextKey } from "./text";

const LINK = /^https:\/\/\S+$/;

function problemOf(error: unknown): StaysTextKey {
  if (!(error instanceof ShortStaysError)) return "f_failed";
  if (error.status === 403) return "f_step_right";
  if (error.status === 409) return "sc_taken";
  if (error.status === 412) return "f_stale";
  if (error.status === 422) return "sc_bad";
  return "f_failed";
}

function LinkCard({
  language,
  link,
  busy,
  onSave,
}: {
  language: Language;
  link: SiteCalendar;
  busy: boolean;
  onSave: (save: SiteCalendarSave) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(link.import_url ?? "");
  const save = (changes: Partial<SiteCalendarSave>) => {
    onSave({
      calendar_id: link.calendar_id,
      version: link.version,
      site_name: link.site_name,
      active: link.active,
      ...(link.import_url === null ? {} : { import_url: link.import_url }),
      ...changes,
    });
  };
  const wrong = url.trim() !== "" && !LINK.test(url.trim());
  return (
    <li className="ui-card">
      <div className="ui-hrow">
        <b className="ui-num">{link.unit_number}</b>
        <span>{link.site_name}</span>
        {!link.active ? (
          <Chip tone="neutral">{st(language, "sc_off")}</Chip>
        ) : link.last_read_ok === null ? (
          <Chip tone="neutral">{st(language, "sc_waiting")}</Chip>
        ) : link.last_read_ok ? (
          <Chip tone="ok">{st(language, "sc_ok")}</Chip>
        ) : (
          <Chip tone="warn">{st(language, "sc_failed")}</Chip>
        )}
      </div>
      {link.active && link.last_read_at !== null && (
        <p className="ui-small ui-muted">
          {st(language, "sc_read", momentText(link.last_read_at), link.holds)}
        </p>
      )}
      {link.last_error !== null && (
        <p className="ui-small ui-error">
          <Icon name="alert" small />
          <span>{link.last_error}</span>
        </p>
      )}
      {editing ? (
        <div className="ui-stack">
          <div className="ui-field">
            <label htmlFor={`sc-url-${link.calendar_id}`}>
              {st(language, "sc_url")}
            </label>
            <input
              aria-invalid={wrong}
              autoComplete="off"
              disabled={busy}
              id={`sc-url-${link.calendar_id}`}
              inputMode="url"
              maxLength={2000}
              onChange={(event) => {
                setUrl(event.currentTarget.value);
              }}
              value={url}
            />
            {wrong && (
              <p className="ui-error">
                <Icon name="alert" small />
                <span>{st(language, "e_link")}</span>
              </p>
            )}
          </div>
          <div className="ui-actions">
            <button
              className="ui-btn primary"
              disabled={busy || wrong}
              onClick={() => {
                const next = url.trim();
                save(
                  next === ""
                    ? { import_url: undefined }
                    : { import_url: next },
                );
                setEditing(false);
              }}
              type="button"
            >
              {st(language, "sc_save")}
            </button>
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setUrl(link.import_url ?? "");
              }}
              type="button"
            >
              {st(language, "sc_cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="ui-actions">
          <button
            className="ui-btn"
            disabled={busy}
            onClick={() => {
              setEditing(true);
            }}
            type="button"
          >
            {st(language, "sc_change")}
          </button>
          <button
            className="ui-btn"
            disabled={busy}
            onClick={() => {
              save({ active: !link.active });
            }}
            type="button"
          >
            {st(language, link.active ? "sc_turn_off" : "sc_turn_on")}
          </button>
        </div>
      )}
    </li>
  );
}

export function SiteCalendars({
  language,
  propertyId,
  api,
  today,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
  today: string;
}) {
  const [links, setLinks] = useState<SiteCalendar[] | null>(null);
  const [units, setUnits] = useState<CalendarUnit[]>([]);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<StaysTextKey | null>(null);
  const [unitId, setUnitId] = useState("");
  const [site, setSite] = useState("");
  const [url, setUrl] = useState("");
  const [checked, setChecked] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void Promise.all([
      api.siteCalendars(propertyId),
      api.calendar(propertyId, today, 1),
    ])
      .then(([found, calendar]) => {
        if (operation !== sequence.current) return;
        setLinks(found);
        setUnits(calendar.units.filter((unit) => unit.for_rent));
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, today]);

  useEffect(() => {
    load();
  }, [load]);

  const send = (save: SiteCalendarSave, done?: () => void) => {
    const operation = ++sequence.current;
    setBusy(true);
    setProblem(null);
    void api
      .saveSiteCalendar(propertyId, save)
      .then(() => {
        if (operation !== sequence.current) return;
        done?.();
        load();
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(problemOf(error));
        load();
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const wrongUnit = unitId === "";
  const wrongSite = site === "";
  const wrongUrl = !LINK.test(url.trim());
  const add = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrongUnit || wrongSite || wrongUrl) return;
    send(
      {
        unit_id: unitId,
        site_name: site,
        import_url: url.trim(),
        active: true,
      },
      () => {
        setChecked(false);
        setUnitId("");
        setSite("");
        setUrl("");
      },
    );
  };

  if (failed)
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{st(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {st(language, "retry")}
        </button>
      </div>
    );
  if (links === null)
    return (
      <p className="ui-muted" role="status">
        {st(language, "loading")}
      </p>
    );
  return (
    <>
      <p className="ui-small ui-muted">{st(language, "sc_s")}</p>
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{st(language, problem)}</p>
        </div>
      )}
      {links.length === 0 ? (
        <p className="ui-empty">{st(language, "sc_none")}</p>
      ) : (
        <ul
          aria-label={st(language, "tab_sites")}
          className="ui-plain ss-clean"
        >
          {links.map((link) => (
            <LinkCard
              busy={busy}
              key={`${link.calendar_id}:${String(link.version)}`}
              language={language}
              link={link}
              onSave={(save) => {
                send(save);
              }}
            />
          ))}
        </ul>
      )}
      <form className="ui-card ui-form ss-form" noValidate onSubmit={add}>
        <h2>{st(language, "sc_add")}</h2>
        <div className="ui-row2">
          <div className="ui-field">
            <label htmlFor="sc-unit">
              {st(language, "c_unit")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <select
              aria-invalid={checked && wrongUnit}
              className="ui-sel"
              disabled={busy}
              id="sc-unit"
              onChange={(event) => {
                setUnitId(event.currentTarget.value);
              }}
              value={unitId}
            >
              <option value="">{st(language, "pick")}</option>
              {units.map((unit) => (
                <option key={unit.unit_id} value={unit.unit_id}>
                  {unit.unit_number}
                </option>
              ))}
            </select>
          </div>
          <div className="ui-field">
            <label htmlFor="sc-site">
              {st(language, "f_site")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <select
              aria-invalid={checked && wrongSite}
              className="ui-sel"
              disabled={busy}
              id="sc-site"
              onChange={(event) => {
                setSite(event.currentTarget.value);
              }}
              value={site}
            >
              <option value="">{st(language, "pick")}</option>
              {SITES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="ui-field">
          <label htmlFor="sc-url">
            {st(language, "sc_url")}
            <span className="req">{st(language, "required")}</span>
          </label>
          <input
            aria-invalid={checked && wrongUrl}
            autoComplete="off"
            disabled={busy}
            id="sc-url"
            inputMode="url"
            maxLength={2000}
            onChange={(event) => {
              setUrl(event.currentTarget.value);
            }}
            placeholder="https://"
            value={url}
          />
          {checked && (wrongUnit || wrongSite || wrongUrl) && (
            <p className="ui-error">
              <Icon name="alert" small />
              <span>{st(language, "e_link_form")}</span>
            </p>
          )}
        </div>
        <div className="ui-actions">
          <button className="ui-btn primary" disabled={busy} type="submit">
            <Icon name="plus" small />
            {st(language, "sc_add_b")}
          </button>
        </div>
      </form>
    </>
  );
}
