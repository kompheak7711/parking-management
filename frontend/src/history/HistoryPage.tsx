// V1-058 R7c: History (mock-up round 9, app4.js vHistory; DL-072 answer 14). Who did what and
// when across the Property, newest first, filtered by period, person and Unit; Show more reads the
// next page. The server keeps the events and their action codes; the screen names the kind of
// record and links Units, Leases, Customers, Reservations and Invoices to their pages. Export
// audit makes a spreadsheet or PDF with the same filters (audit.export).

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  AuditExportRequest,
  DownloadedFile,
  ExportAnswer,
  ExportFileType,
} from "../reportsClient";
import { ExportRefusedError, ReportsNotAllowedError } from "../reportsClient";
import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import { allPages } from "../units/unitsData";
import {
  type HistoryApi,
  type HistoryEvent,
  type HistoryFilter,
  HistoryNotAllowedError,
} from "./historyClient";
import { actionText, hit, kindOf, kindText } from "./text";

export interface HistoryExportApi {
  exportAudit: (
    propertyId: string,
    request: AuditExportRequest,
  ) => Promise<ExportAnswer>;
  download: (propertyId: string, exportId: string) => Promise<DownloadedFile>;
}

export interface HistoryPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api: HistoryApi;
  /** Names for the Who list; only an account that manages users can read them all. */
  people: (
    propertyId: string,
  ) => Promise<{ user_id: string; display_name: string }[]>;
  me: { id: string; name: string };
  units: Pick<UnitApi, "list">;
  exporter: HistoryExportApi;
  /** For tests; otherwise today in Phnom Penh. */
  today: string;
}

type Period = "0" | "7" | "30" | "all";

interface Search {
  period: Period;
  actorId: string;
  unitId: string;
}

const START: Search = { period: "7", actorId: "", unitId: "" };

function daysBefore(today: string, days: number): string {
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

function filterOf(search: Search, today: string): HistoryFilter {
  const filter: HistoryFilter = {};
  // "7 days" is today and the 6 days before it (the server keeps business_date >= from).
  if (search.period !== "all") {
    filter.from = daysBefore(today, Math.max(0, Number(search.period) - 1));
  }
  if (search.actorId !== "") filter.actorId = search.actorId;
  if (search.unitId !== "") filter.unitId = search.unitId;
  return filter;
}

// The pages a record opens on, by the server's entity type.
const RECORD_PAGES: Readonly<Record<string, (id: string) => string>> = {
  unit: (id) => hashForPage("units", id),
  lease: (id) => hashForPage("leases", id),
  customer: (id) => hashForPage("customers", id),
  reservation: (id) => hashForPage("reservations", id),
  invoice: (id) => hashForPage("invoices", `inv:${id}`),
};

function save(file: DownloadedFile | { fileName: string; file: Blob }) {
  const url = URL.createObjectURL(file.file);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function HistoryPage({
  language,
  propertyId,
  active,
  capabilities,
  api,
  people,
  me,
  units,
  exporter,
  today,
}: HistoryPageProps) {
  const mayExport = capabilities === null || capabilities.has("audit.export");
  const [form, setForm] = useState<Search>(START);
  // The filter of the list on screen, so Show more and Export use the same days after midnight.
  const [shown, setShown] = useState<HistoryFilter>({});
  const [events, setEvents] = useState<HistoryEvent[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [unitList, setUnitList] = useState<{ id: string; number: string }[]>(
    [],
  );
  const [exporting, setExporting] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const sequence = useRef(0);
  const shownProperty = useRef(propertyId);

  const searchWith = useCallback(
    (filter: HistoryFilter) => {
      if (propertyId === "") return;
      const operation = ++sequence.current;
      setFailure(null);
      setEvents(null);
      setNext(null);
      setLoadingMore(false);
      setShown(filter);
      api
        .search(propertyId, filter)
        .then((page) => {
          if (operation !== sequence.current) return;
          setEvents(page.events);
          setNext(page.nextCursor);
        })
        .catch((error: unknown) => {
          if (operation !== sequence.current) return;
          setFailure(
            error instanceof HistoryNotAllowedError ? "not_allowed" : "failed",
          );
        });
    },
    [api, propertyId],
  );
  const search = useCallback(
    (wanted: Search) => {
      searchWith(filterOf(wanted, today));
    },
    [searchWith, today],
  );

  // Each opening of the page is one search (the first page of a search is written to History),
  // so it is not repeated on every render, nor when React runs the effect twice.
  const searched = useRef<string | null>(null);
  useEffect(() => {
    if (shownProperty.current !== propertyId) {
      shownProperty.current = propertyId;
      searched.current = null;
      sequence.current++;
      setForm(START);
      setShown({});
      setEvents(null);
      setNext(null);
      setFailure(null);
      setNames(new Map());
      setUnitList([]);
      setNote(null);
      setLoadingMore(false);
      setExporting(false);
    }
    if (!active || propertyId === "" || searched.current === propertyId) return;
    searched.current = propertyId;
    search(START);
    const asked = propertyId;
    people(propertyId)
      .then((list) => {
        if (shownProperty.current !== asked) return;
        setNames(
          new Map(list.map((person) => [person.user_id, person.display_name])),
        );
      })
      .catch(() => undefined);
    allPages(async (cursor) =>
      units.list(propertyId, cursor === undefined ? {} : { cursor }),
    )
      .then((list) => {
        if (shownProperty.current !== asked) return;
        setUnitList(
          list
            .map((unit) => ({ id: unit.unit_id, number: unit.unit_number }))
            .sort((a, b) => a.number.localeCompare(b.number)),
        );
      })
      .catch(() => undefined);
  }, [active, propertyId, search, people, units]);

  function more() {
    if (next === null || events === null) return;
    const operation = sequence.current;
    setLoadingMore(true);
    api
      .search(propertyId, { ...shown, cursor: next })
      .then((page) => {
        if (operation !== sequence.current) return;
        setEvents([...events, ...page.events]);
        setNext(page.nextCursor);
      })
      .catch(() => {
        if (operation !== sequence.current) return;
        setNote({ ok: false, text: hit(language, "failed") });
      })
      .finally(() => {
        if (operation === sequence.current) setLoadingMore(false);
      });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNote(null);
    search(form);
  }

  function exportFile(fileType: ExportFileType) {
    // A new search does not drop a file the server is already making; a Property change does.
    const asked = propertyId;
    const filter = shown;
    setExporting(true);
    setNote(null);
    exporter
      .exportAudit(propertyId, {
        fileType,
        from: filter.from,
        to: filter.from === undefined ? undefined : today,
        actorId: filter.actorId,
        unitId: filter.unitId,
      })
      .then(async (answer) => {
        const file =
          answer.kind === "file"
            ? answer
            : await exporter.download(propertyId, answer.exportId);
        if (shownProperty.current !== asked) return;
        save(file);
        setNote({ ok: true, text: hit(language, "ex_saved", answer.fileName) });
      })
      .catch((error: unknown) => {
        if (shownProperty.current !== asked) return;
        setNote({
          ok: false,
          text: hit(
            language,
            error instanceof ExportRefusedError
              ? "ex_refused"
              : error instanceof ReportsNotAllowedError
                ? "not_allowed"
                : "ex_failed",
          ),
        });
      })
      .finally(() => {
        if (shownProperty.current === asked) setExporting(false);
      });
  }

  if (propertyId === "") return null;

  const who = (actorId: string) => {
    const name = names.get(actorId);
    if (actorId === me.id) return hit(language, "me", name ?? me.name);
    return name ?? hit(language, "someone", actorId.slice(0, 8));
  };
  const whoList = [...names.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  if (!names.has(me.id)) whoList.unshift([me.id, me.name]);

  const head = (
    <div className="ui-head">
      <p>{hit(language, "hi_sub")}</p>
      {mayExport && (
        <div className="ui-actions">
          {(["xlsx", "pdf"] as const).map((type) => (
            <button
              className="ui-btn"
              disabled={exporting || failure !== null}
              key={type}
              onClick={() => {
                exportFile(type);
              }}
              type="button"
            >
              <Icon name="upload" small />
              {hit(language, "hi_export")} ·{" "}
              {hit(language, type === "xlsx" ? "ex_xlsx" : "ex_pdf")}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const filters = (
    <form className="ui-filters" noValidate onSubmit={submit}>
      <div
        aria-label={hit(language, "hi_when")}
        className="ui-seg"
        role="group"
      >
        {(
          [
            ["0", "hi_today"],
            ["7", "hi_7"],
            ["30", "hi_30"],
            ["all", "hi_all"],
          ] as const
        ).map(([value, key]) => (
          <button
            aria-pressed={form.period === value}
            key={value}
            onClick={() => {
              setForm({ ...form, period: value });
            }}
            type="button"
          >
            {hit(language, key)}
          </button>
        ))}
      </div>
      <label className="ui-sr" htmlFor="hi-who">
        {hit(language, "hi_who")}
      </label>
      <select
        className="ui-sel"
        id="hi-who"
        onChange={(event) => {
          setForm({ ...form, actorId: event.currentTarget.value });
        }}
        value={form.actorId}
      >
        <option value="">{hit(language, "hi_anyone")}</option>
        {whoList.map(([id]) => (
          <option key={id} value={id}>
            {who(id)}
          </option>
        ))}
      </select>
      <label className="ui-sr" htmlFor="hi-unit">
        {hit(language, "hi_unit")}
      </label>
      <select
        className="ui-sel"
        id="hi-unit"
        onChange={(event) => {
          setForm({ ...form, unitId: event.currentTarget.value });
        }}
        value={form.unitId}
      >
        <option value="">{hit(language, "hi_any_unit")}</option>
        {unitList.map((unit) => (
          <option key={unit.id} value={unit.id}>
            {unit.number}
          </option>
        ))}
      </select>
      <button className="ui-btn primary" type="submit">
        <Icon name="search" small />
        {hit(language, "hi_search")}
      </button>
    </form>
  );

  if (failure !== null) {
    return (
      <>
        {head}
        {filters}
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{hit(language, failure)}</p>
          {failure === "failed" && (
            <button
              className="ui-btn"
              onClick={() => {
                searchWith(shown);
              }}
              type="button"
            >
              {hit(language, "retry")}
            </button>
          )}
        </div>
      </>
    );
  }

  const unitNumber = (id: string) =>
    unitList.find((unit) => unit.id === id)?.number;

  return (
    <>
      {head}
      {filters}
      <div aria-live="polite" role="status">
        {note !== null && (
          <div className={note.ok ? "ui-notice ok" : "ui-notice warn"}>
            <Icon name={note.ok ? "check" : "alert"} />
            <p>{note.text}</p>
          </div>
        )}
      </div>
      <section aria-label={hit(language, "hi_title")} className="ui-card pad0">
        {events === null ? (
          <p className="ui-empty" role="status">
            {hit(language, "loading")}
          </p>
        ) : events.length === 0 ? (
          <p className="ui-empty">{hit(language, "hi_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{hit(language, "hi_when")}</th>
                  <th scope="col">{hit(language, "hi_who")}</th>
                  <th scope="col">{hit(language, "hi_kind")}</th>
                  <th scope="col">{hit(language, "hi_col_what")}</th>
                  <th scope="col">{hit(language, "hi_col_rec")}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => {
                  const when = momentText(event.occurred_at);
                  const page = RECORD_PAGES[event.resource_type];
                  const kind = kindText(language, kindOf(event.resource_type));
                  // The kind is in its own column; the record shows the Unit number or a
                  // short id, and its full name is read out.
                  const record =
                    (event.resource_type === "unit"
                      ? unitNumber(event.resource_id)
                      : undefined) ?? event.resource_id.slice(0, 8);
                  return (
                    <tr key={event.event_id}>
                      <td className="ui-num">
                        {when.slice(0, 10)}{" "}
                        <span className="ui-sub2">{when.slice(11)}</span>
                      </td>
                      <td>{who(event.actor_id)}</td>
                      <td>
                        <Chip tone="neutral">{kind}</Chip>
                      </td>
                      <td>
                        <span lang="en">{actionText(event.action)}</span>
                        {event.outcome.toLowerCase() === "refused" && (
                          <>
                            {" "}
                            <Chip tone="warn">{hit(language, "refused")}</Chip>
                          </>
                        )}
                        {event.reason.trim() !== "" && (
                          <span className="ui-sub2">
                            {hit(language, "reason", event.reason)}
                          </span>
                        )}
                      </td>
                      <td>
                        {page === undefined ? (
                          <span
                            aria-label={`${kind} ${record}`}
                            className="ui-num"
                          >
                            {record}
                          </span>
                        ) : (
                          <a
                            aria-label={`${kind} ${record}`}
                            className="ui-num"
                            href={page(event.resource_id)}
                          >
                            {record}
                          </a>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {events !== null && (
          <div className="ui-tfoot ui-tfoot-row">
            <span>
              {events.length === 1
                ? hit(language, "hi_n1")
                : hit(language, "hi_n", events.length)}{" "}
              · {hit(language, "hi_note")}
            </span>
            {next !== null && (
              <button
                className="ui-btn"
                disabled={loadingMore}
                onClick={more}
                type="button"
              >
                {hit(language, "more")}
              </button>
            )}
          </div>
        )}
      </section>
    </>
  );
}
