// V1-061 (owner 29/10/2026, DL-110): the Unit's default Rent and the Services every new Lease of
// the Unit must have. A new Reservation or Lease starts at the default Rent; staff may agree more,
// and less needs a Manager or the Owner ("Lower Rent needs a Manager"). The required Services are
// ticked on New Lease and cannot be unticked ("Ticked and locked"). A Manager or the Owner changes
// both here; each change is kept in the Unit's History.

import { FormEvent, useEffect, useState } from "react";

import type {
  ServiceSetting,
  ServiceSettingsApi,
  ServiceType,
} from "../settings/serviceSettingsClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type UnitApi,
  UnitConflictError,
  UnitInvalidError,
  type UnitResource,
} from "../unitClient";
import { centsOf } from "../payments/depositMoney";
import { ut } from "./text";

export type RentTermsServicesApi = Pick<ServiceSettingsApi, "read">;

function serviceName(service: ServiceSetting, language: Language): string {
  return language === "km" && service.name_km !== null
    ? service.name_km
    : service.name_en;
}

/** The required Service on the card: its type and monthly rate, as "Trash $8.00 per month"
 * (owner 29/10/2026); the Service's own name when it has no type. A rate that starts later
 * says from when, and a Service with no rate says so. */
function serviceLine(
  service: ServiceSetting,
  types: readonly ServiceType[],
  language: Language,
): string {
  const type = types.find(
    (item) => item.service_type_id === service.service_type_id,
  );
  const name =
    type === undefined
      ? serviceName(service, language)
      : language === "km" && type.name_km !== null
        ? type.name_km
        : type.name_en;
  if (service.rate_today_usd_cents !== null)
    return ut(
      language,
      "rt_service_rate",
      name,
      usdFromCents(service.rate_today_usd_cents),
    );
  if (service.next_rate !== null)
    return ut(
      language,
      "rt_service_from",
      name,
      usdFromCents(service.next_rate.monthly_rate_usd_cents),
      dayText(service.next_rate.effective_date),
    );
  return ut(language, "rt_service_no_rate", name);
}

export interface ServicesRead {
  services: ServiceSetting[];
  types: ServiceType[];
}

/** The Property's Services, read once; null while reading, "failed" when they cannot be read. */
export function useServices(
  api: RentTermsServicesApi,
  propertyId: string,
): ServicesRead | "failed" | null {
  const [services, setServices] = useState<ServicesRead | "failed" | null>(
    null,
  );
  useEffect(() => {
    const run = { live: true };
    setServices(null);
    api
      .read(propertyId)
      .then((found) => {
        if (run.live)
          setServices({
            services: found.services,
            types: found.service_types,
          });
      })
      .catch(() => {
        if (run.live) setServices("failed");
      });
    return () => {
      run.live = false;
    };
  }, [api, propertyId]);
  return services;
}

export function RentTermsCard({
  language,
  unit,
  propertyId,
  servicesApi,
  unitApi,
  canManage,
  onSaved,
  onConflict,
}: {
  language: Language;
  unit: UnitResource;
  propertyId: string;
  servicesApi: RentTermsServicesApi;
  unitApi: Pick<UnitApi, "setRentTerms">;
  canManage: boolean;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const read = useServices(servicesApi, propertyId);
  const services = read === null || read === "failed" ? read : read.services;
  const types = read === null || read === "failed" ? [] : read.types;
  const [open, setOpen] = useState(false);
  const rent = unit.default_monthly_rent_usd_cents ?? null;
  const required = unit.required_service_ids ?? [];
  const names =
    services === null || services === "failed"
      ? null
      : required.map(
          (id) => services.find((service) => service.service_id === id) ?? null,
        );

  return (
    <section aria-labelledby="unit-rent-terms" className="ui-card">
      <div className="ui-chead">
        <h2 id="unit-rent-terms">{ut(language, "rt_title")}</h2>
        {canManage && (
          <button
            className="ui-btn"
            onClick={() => {
              setOpen(true);
            }}
            type="button"
          >
            <Icon name="swap" />
            {ut(language, "rt_change")}
          </button>
        )}
      </div>
      <dl className="ui-kv">
        <dt>{ut(language, "rt_rent")}</dt>
        <dd className="ui-num" data-testid="unit-default-rent">
          {rent === null ? ut(language, "rt_none") : usdFromCents(rent)}
        </dd>
        <dt>{ut(language, "rt_services")}</dt>
        <dd data-testid="unit-required-services">
          {required.length === 0
            ? ut(language, "rt_no_services")
            : names === null
              ? services === "failed"
                ? ut(language, "rt_services_count", required.length)
                : ut(language, "rt_loading")
              : names
                  .map((service) =>
                    service === null
                      ? ut(language, "rt_unknown_service")
                      : serviceLine(service, types, language),
                  )
                  .join(", ")}
        </dd>
      </dl>
      <p className="ui-small ui-muted">{ut(language, "rt_note")}</p>
      {open && (
        <RentTermsDialog
          api={unitApi}
          language={language}
          onClose={() => {
            setOpen(false);
          }}
          onConflict={() => {
            setOpen(false);
            onConflict();
          }}
          onSaved={(saved) => {
            setOpen(false);
            onSaved(saved);
          }}
          services={services}
          unit={unit}
        />
      )}
    </section>
  );
}

function RentTermsDialog({
  api,
  language,
  unit,
  services,
  onClose,
  onSaved,
  onConflict,
}: {
  api: Pick<UnitApi, "setRentTerms">;
  language: Language;
  unit: UnitResource;
  services: ServiceSetting[] | "failed" | null;
  onClose: () => void;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const first = unit.default_monthly_rent_usd_cents ?? null;
  const [rent, setRent] = useState(
    first === null ? "" : (first / 100).toFixed(2),
  );
  const [chosen, setChosen] = useState<Set<string>>(
    new Set(unit.required_service_ids ?? []),
  );
  const [rentProblem, setRentProblem] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = services !== null && services !== "failed";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    const cents = rentCents(rent);
    if (cents === "wrong") {
      setRentProblem(ut(language, "rt_err_rent"));
      return;
    }
    setRentProblem(null);
    if (chosen.size > 20) {
      setProblem(ut(language, "rt_err_many"));
      return;
    }
    setBusy(true);
    setProblem(null);
    void api
      .setRentTerms(unit, {
        default_monthly_rent_usd_cents: cents,
        required_service_ids: [...chosen],
      })
      .then(onSaved)
      .catch((error: unknown) => {
        setBusy(false);
        if (error instanceof UnitConflictError) {
          onConflict();
          return;
        }
        setProblem(
          ut(
            language,
            error instanceof UnitInvalidError ? "invalid" : "not_saved",
          ),
        );
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ut(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ut(language, "save")}
      title={`${ut(language, "rt_title")} · ${unit.unit_number}`}
    >
      <RentTermsFields
        chosen={chosen}
        language={language}
        onChosen={setChosen}
        onRent={setRent}
        rent={rent}
        rentProblem={rentProblem}
        services={services}
      />
      <p className="ui-small ui-muted">{ut(language, "rt_dialog_note")}</p>
      {problem !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </Dialog>
  );
}

/** The default Rent box and the required Services ticks, shared by New Unit and Change. */
export function RentTermsFields({
  language,
  rent,
  onRent,
  chosen,
  onChosen,
  services,
  rentProblem,
}: {
  language: Language;
  rent: string;
  onRent: (rent: string) => void;
  chosen: ReadonlySet<string>;
  onChosen: (chosen: Set<string>) => void;
  services: ServiceSetting[] | "failed" | null;
  rentProblem: string | null;
}) {
  const ready = services !== null && services !== "failed";
  return (
    <>
      <div className="ui-field">
        <label htmlFor="unit-rent-default">{ut(language, "rt_rent")}</label>
        <input
          aria-invalid={rentProblem !== null}
          id="unit-rent-default"
          inputMode="decimal"
          onChange={(event) => {
            onRent(event.currentTarget.value);
          }}
          value={rent}
        />
        <p className="help">{ut(language, "rt_rent_help")}</p>
        {rentProblem !== null && (
          <p className="ui-error" role="alert">
            <Icon name="alert" small />
            <span>{rentProblem}</span>
          </p>
        )}
      </div>
      <fieldset className="ui-radios">
        <legend>{ut(language, "rt_services")}</legend>
        {services === null && (
          <p className="ui-small ui-muted" role="status">
            {ut(language, "rt_loading")}
          </p>
        )}
        {services === "failed" && (
          <p className="ui-small" role="status">
            {ut(language, "rt_services_failed")}
          </p>
        )}
        {ready && services.length === 0 && (
          <p className="ui-small ui-muted">
            {ut(language, "rt_no_property_services")}
          </p>
        )}
        {ready &&
          services.map((service) => (
            <label className="ui-chk" key={service.service_id}>
              <input
                checked={chosen.has(service.service_id)}
                onChange={(event) => {
                  const next = new Set(chosen);
                  if (event.currentTarget.checked) next.add(service.service_id);
                  else next.delete(service.service_id);
                  onChosen(next);
                }}
                type="checkbox"
              />
              <span>{serviceName(service, language)}</span>
            </label>
          ))}
      </fieldset>
    </>
  );
}

/** The Rent box's cents, or "wrong" when it is not an amount; a blank box is no default. */
export function rentCents(rent: string): number | null | "wrong" {
  if (rent.trim() === "") return null;
  return centsOf(rent) ?? "wrong";
}
