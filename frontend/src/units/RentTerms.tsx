// V1-061 (owner 29/10/2026, DL-110): the Unit's default Rent and the Services every new Lease of
// the Unit must have. A new Reservation or Lease starts at the default Rent; staff may agree more,
// and less needs a Manager or the Owner ("Lower Rent needs a Manager"). The required Services are
// ticked on New Lease and cannot be unticked ("Ticked and locked"). A Manager or the Owner changes
// both here; each change is kept in the Unit's History.

import { FormEvent, useEffect, useState } from "react";

import type {
  ServiceSetting,
  ServiceSettingsApi,
} from "../settings/serviceSettingsClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type UnitApi,
  UnitConflictError,
  UnitInvalidError,
  type UnitResource,
} from "../unitClient";
import { ut } from "./text";

export type RentTermsServicesApi = Pick<ServiceSettingsApi, "read">;

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
function centsOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [dollars = "0", part = ""] = value.split(".");
  const cents = Number(dollars) * 100 + Number(part.padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

function serviceName(service: ServiceSetting, language: Language): string {
  return language === "km" && service.name_km !== null
    ? service.name_km
    : service.name_en;
}

/** The Property's Services, read once; null while reading, "failed" when they cannot be read. */
function useServices(
  api: RentTermsServicesApi,
  propertyId: string,
): ServiceSetting[] | "failed" | null {
  const [services, setServices] = useState<ServiceSetting[] | "failed" | null>(
    null,
  );
  useEffect(() => {
    const run = { live: true };
    setServices(null);
    api
      .read(propertyId)
      .then((found) => {
        if (run.live) setServices(found.services);
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
  const services = useServices(servicesApi, propertyId);
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
                      : serviceName(service, language),
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
    const cents = rent.trim() === "" ? null : centsOf(rent);
    if (rent.trim() !== "" && cents === null) {
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
      <div className="ui-field">
        <label htmlFor="unit-rent-default">{ut(language, "rt_rent")}</label>
        <input
          aria-invalid={rentProblem !== null}
          id="unit-rent-default"
          inputMode="decimal"
          onChange={(event) => {
            setRent(event.currentTarget.value);
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
                  setChosen(next);
                }}
                type="checkbox"
              />
              <span>{serviceName(service, language)}</span>
            </label>
          ))}
      </fieldset>
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
