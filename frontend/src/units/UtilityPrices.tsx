// V1-061 (owner 29/10/2026): the Utility prices show on the Units list and on the Unit page, with
// the Unit's own Meters. They only show what Settings › Rates and services and Utilities ›
// Meters hold; nothing here changes money. A Unit with no Meter of a kind is not billed for it
// (DL-098), so the page says so.

import { useCallback, useEffect, useState } from "react";

import { ratePerUnit } from "../settings/RatesTab";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip } from "../shell/ui";
import type { UnitResource } from "../unitClient";
import { AddMeterDialog } from "../utilities/MetersTab";
import type { Language } from "../signInText";
import type {
  UtilityApi,
  UtilityMeter,
  UtilityRate,
  UtilityType,
} from "../utilityClient";
import { ut } from "./text";

export type UtilityPricesApi = Pick<UtilityApi, "loadMeters" | "loadRates"> &
  Partial<Pick<UtilityApi, "installMeter">>;

const KINDS: readonly UtilityType[] = ["ELECTRICITY", "WATER"];
const KIND_TEXT = { ELECTRICITY: "u_el", WATER: "u_wa" } as const;
const ADD_TEXT = { ELECTRICITY: "u_add_el", WATER: "u_add_wa" } as const;
const KIND_UNIT = { ELECTRICITY: "kWh", WATER: "m³" } as const;
// A Property has few rates and meters; a few pages are plenty and stop a runaway loop.
const MAX_PAGES = 10;

async function all<T>(
  read: (cursor?: string) => Promise<{ items: T[]; nextCursor: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const found = await read(cursor);
    items.push(...found.items);
    if (found.nextCursor === null) break;
    cursor = found.nextCursor;
  }
  return items;
}

/** The rate in force today and the next one of each kind. */
export function ratesNow(
  rates: readonly UtilityRate[],
  today: string,
): Record<UtilityType, { now: UtilityRate | null; next: UtilityRate | null }> {
  const result = {
    ELECTRICITY: { now: null, next: null },
    WATER: { now: null, next: null },
  } as Record<
    UtilityType,
    { now: UtilityRate | null; next: UtilityRate | null }
  >;
  for (const kind of KINDS) {
    const own = rates
      .filter((rate) => rate.utility_type === kind)
      .sort((a, b) => a.effective_date.localeCompare(b.effective_date));
    for (const rate of own) {
      if (rate.effective_date <= today) result[kind].now = rate;
      else result[kind].next ??= rate;
    }
  }
  return result;
}

function price(language: Language, rate: UtilityRate): string {
  return ut(
    language,
    "u_price",
    ratePerUnit(rate.rate_usd_per_unit),
    KIND_UNIT[rate.utility_type],
  );
}

function RateText({
  language,
  kind,
  rates,
}: {
  language: Language;
  kind: UtilityType;
  rates: ReturnType<typeof ratesNow>;
}) {
  const { now, next } = rates[kind];
  return (
    <>
      {now === null ? (
        <span className="ui-muted">{ut(language, "u_no_rate")}</span>
      ) : (
        <span className="ui-num">
          <b>{price(language, now)}</b>{" "}
          <small className="ui-muted">
            {ut(language, "u_since", dayText(now.effective_date))}
          </small>
        </span>
      )}
      {next !== null && (
        <small className="ui-num ui-muted">
          {" · "}
          {ut(
            language,
            "u_next",
            dayText(next.effective_date),
            price(language, next),
          )}
        </small>
      )}
    </>
  );
}

type Loaded<T> = T | "failed" | null;

function useRates(
  api: UtilityPricesApi,
  propertyId: string,
  allowed: boolean,
): Loaded<UtilityRate[]> {
  const [rates, setRates] = useState<Loaded<UtilityRate[]>>(null);
  useEffect(() => {
    if (!allowed || propertyId === "") return;
    let live = true;
    setRates(null);
    all((cursor) => api.loadRates(propertyId, cursor))
      .then((found) => {
        if (live) setRates(found);
      })
      .catch(() => {
        if (live) setRates("failed");
      });
    return () => {
      live = false;
    };
  }, [allowed, api, propertyId]);
  return rates;
}

/** One line above the Units list: the electricity and water prices in force today. */
export function UtilityPricesStrip({
  language,
  propertyId,
  api,
  allowed,
  today,
}: {
  language: Language;
  propertyId: string;
  api: UtilityPricesApi;
  /** False when the person may not read Utilities: the line is not shown. */
  allowed: boolean;
  today: string;
}) {
  const rates = useRates(api, propertyId, allowed);
  if (!allowed || rates === null || rates === "failed") return null;
  const found = ratesNow(rates, today);
  return (
    <p className="ui-small" data-testid="utility-prices">
      <b>{ut(language, "prices_now")}:</b>{" "}
      {KINDS.map((kind, index) => (
        <span key={kind}>
          {index > 0 && " · "}
          {ut(language, KIND_TEXT[kind])}{" "}
          {found[kind].now === null
            ? ut(language, "u_no_rate")
            : price(language, found[kind].now)}
        </span>
      ))}
    </p>
  );
}

function currentMeter(
  meters: readonly UtilityMeter[],
  kind: UtilityType,
): UtilityMeter | null {
  return (
    meters.find(
      (meter) =>
        meter.utility_type === kind &&
        meter.current &&
        meter.deactivated_date === null,
    ) ?? null
  );
}

/** The Unit page card: each kind's Meter and its price. */
export function UnitUtilitiesCard({
  language,
  propertyId,
  unit,
  api,
  allowed,
  canAddMeter,
  today,
}: {
  language: Language;
  propertyId: string;
  unit: UnitResource;
  api: UtilityPricesApi;
  allowed: boolean;
  /** V1-061 (owner 29/10/2026): a new Unit's meters are added right here. */
  canAddMeter: boolean;
  today: string;
}) {
  const unitId = unit.unit_id;
  const rates = useRates(api, propertyId, allowed);
  const [meters, setMeters] = useState<Loaded<UtilityMeter[]>>(null);
  const [adding, setAdding] = useState<UtilityType | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reads, setReads] = useState(0);
  const reload = useCallback(() => {
    setReads((count) => count + 1);
  }, []);
  useEffect(() => {
    if (!allowed) return;
    let live = true;
    all((cursor) => api.loadMeters(unitId, cursor))
      .then((found) => {
        if (live) setMeters(found);
      })
      .catch(() => {
        if (live) setMeters("failed");
      });
    return () => {
      live = false;
    };
  }, [allowed, api, unitId, reads]);
  const install = api.installMeter;

  let body;
  if (!allowed) {
    body = <p className="ui-small ui-muted">{ut(language, "u_cannot")}</p>;
  } else if (rates === "failed" || meters === "failed") {
    body = <p className="ui-small ui-muted">{ut(language, "u_failed")}</p>;
  } else if (rates === null || meters === null) {
    body = (
      <p className="ui-small ui-muted" role="status">
        {ut(language, "loading")}
      </p>
    );
  } else {
    const found = ratesNow(rates, today);
    body = (
      <>
        <ul className="ui-apps">
          {KINDS.map((kind) => {
            const meter = currentMeter(meters, kind);
            return (
              <li data-kind={kind} key={kind}>
                <span>
                  <b>{ut(language, KIND_TEXT[kind])}</b>
                  <small>
                    {meter === null ? (
                      ut(language, "u_no_meter")
                    ) : (
                      <RateText kind={kind} language={language} rates={found} />
                    )}
                  </small>
                </span>
                {meter === null && canAddMeter && install !== undefined && (
                  <button
                    className="ui-btn"
                    onClick={() => {
                      setNotice(null);
                      setAdding(kind);
                    }}
                    type="button"
                  >
                    <Icon name="plus" />
                    {ut(language, ADD_TEXT[kind])}
                  </button>
                )}
                {meter !== null && (
                  <span>
                    <small className="ui-num">
                      {ut(language, "u_meter", meter.serial_number)}
                    </small>{" "}
                    {meter.failure_date === null ? (
                      <Chip icon="check" tone="ok">
                        {ut(language, "u_working")}
                      </Chip>
                    ) : (
                      <Chip tone="warn">
                        {ut(language, "u_broken", dayText(meter.failure_date))}
                      </Chip>
                    )}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
        <p className="ui-small ui-muted">{ut(language, "u_settings")}</p>
      </>
    );
  }
  return (
    <section aria-labelledby="unit-utilities" className="ui-card">
      <h2 id="unit-utilities">{ut(language, "utilities")}</h2>
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {body}
      {adding !== null && install !== undefined && Array.isArray(meters) && (
        <AddMeterDialog
          api={{ installMeter: install }}
          data={{ units: [unit], meters }}
          language={language}
          onClose={(unsure) => {
            setAdding(null);
            // After a lost answer the meter may have been added: read the list again.
            if (unsure) reload();
          }}
          onConflict={() => {
            setAdding(null);
            reload();
          }}
          onSaved={(text) => {
            setAdding(null);
            setNotice(text);
            reload();
          }}
          preset={{ type: adding, unitId }}
          today={today}
        />
      )}
    </section>
  );
}
