import { FormEvent, useRef, useState } from "react";

import {
  MEASUREMENT_UNIT_CODES,
  measurementUnitLabel,
} from "./measurementUnits";

import {
  EffectiveConfigurationApi,
  EffectiveConfigurationConflictError,
  EffectiveConfigurationError,
  EffectiveConfigurationSnapshot,
  EffectiveConfigurationUnavailableError,
} from "./configurationClient";

export interface ConfigurationManagementProps {
  api: EffectiveConfigurationApi;
  propertyId?: string;
}

export function ConfigurationManagement({
  api,
  propertyId = "",
}: ConfigurationManagementProps) {
  const [targetPropertyId, setTargetPropertyId] = useState(propertyId);
  const [snapshot, setSnapshot] =
    useState<EffectiveConfigurationSnapshot | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exchangeSource, setExchangeSource] = useState<
    "ABA_AUTOMATIC" | "ABA_EQUIVALENT_MANUAL"
  >("ABA_AUTOMATIC");
  const pendingKeys = useRef<
    Record<string, { payload: string; key: string } | undefined>
  >({});

  function text(data: FormData, name: string): string {
    const value = data.get(name);
    return typeof value === "string" ? value : "";
  }

  function cambodiaTimestamp(value: string): string {
    return value.length === 16 ? `${value}:00+07:00` : `${value}+07:00`;
  }

  function commandKey(kind: string, payload: object): string {
    const serialized = JSON.stringify(payload);
    const existing = pendingKeys.current[kind];
    if (existing?.payload === serialized) return existing.key;
    const key = crypto.randomUUID();
    pendingKeys.current[kind] = { payload: serialized, key };
    return key;
  }

  function diagnostics(error: unknown): string {
    if (!(error instanceof EffectiveConfigurationError)) return "";
    const parts: string[] = [];
    if (error.requestId !== null) parts.push(`Reference: ${error.requestId}.`);
    if (error.fields.length > 0) {
      parts.push(`Check fields: ${error.fields.join(", ")}.`);
    }
    return parts.length === 0 ? "" : ` ${parts.join(" ")}`;
  }

  function prepend<Record extends { id: string }>(
    item: Record,
    history: Record[],
  ): Record[] {
    return [item, ...history.filter((candidate) => candidate.id !== item.id)];
  }

  function load() {
    setBusy(true);
    setFailed(false);
    setStatus("Loading authorized effective-dated configuration history…");
    void api
      .load(targetPropertyId)
      .then((value) => {
        setSnapshot(value);
        setStatus("Effective-dated configuration history loaded.");
      })
      .catch((error: unknown) => {
        setSnapshot(null);
        setFailed(true);
        setStatus(
          error instanceof EffectiveConfigurationUnavailableError
            ? `Effective-dated configuration is not available for this session and Property.${diagnostics(error)}`
            : `Effective-dated configuration could not be loaded.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function complete<Result>(
    kind: string,
    payload: object,
    command: (idempotencyKey: string) => Promise<Result>,
    applyResult: (
      current: EffectiveConfigurationSnapshot,
      result: Result,
    ) => EffectiveConfigurationSnapshot,
    message: string,
    form: HTMLFormElement,
  ) {
    setBusy(true);
    setFailed(false);
    setStatus("Submitting the authorized effective-dated configuration…");
    void command(commandKey(kind, payload))
      .then((result) => {
        pendingKeys.current[kind] = undefined;
        form.reset();
        setSnapshot((current) =>
          current === null ? current : applyResult(current, result),
        );
        setStatus(`${message} Refreshing protected history…`);
        return api
          .load(targetPropertyId)
          .then((value) => {
            setSnapshot(value);
            setStatus(message);
          })
          .catch((error: unknown) => {
            setFailed(true);
            setStatus(
              `${message} The saved result is retained, but current history could not be refreshed.${diagnostics(error)}`,
            );
          });
      })
      .catch((error: unknown) => {
        setFailed(true);
        setStatus(
          error instanceof EffectiveConfigurationConflictError
            ? `Configuration history changed or this command was already used. Reload before retrying.${diagnostics(error)}`
            : error instanceof EffectiveConfigurationUnavailableError
              ? `This configuration change is not authorized for the current session.${diagnostics(error)}`
              : `The configuration change was not completed.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function createService(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload = {
      property_service_id: text(data, "service-id"),
      monthly_rate_usd_cents: Number(data.get("service-rate-cents")),
      effective_date: text(data, "service-effective-date"),
      source_memo: text(data, "service-memo").trim() || null,
    };
    complete(
      "service",
      payload,
      (key) => api.createServiceRate(targetPropertyId, payload, key),
      (current, result) => ({
        ...current,
        serviceRates: prepend(result, current.serviceRates),
      }),
      "Service rate appended to protected history.",
      form,
    );
  }

  function createUtility(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload = {
      utility_type:
        data.get("utility-type") === "WATER"
          ? ("WATER" as const)
          : ("ELECTRICITY" as const),
      measurement_unit_code:
        MEASUREMENT_UNIT_CODES[
          data.get("utility-type") === "WATER" ? "WATER" : "ELECTRICITY"
        ],
      rate_usd_per_unit: text(data, "utility-rate"),
      effective_date: text(data, "utility-effective-date"),
      notice_at: cambodiaTimestamp(text(data, "utility-notice-at")),
      notice_evidence: text(data, "utility-notice-evidence"),
      source_memo: text(data, "utility-memo").trim() || null,
    };
    complete(
      "utility",
      payload,
      (key) => api.createUtilityRate(targetPropertyId, payload, key),
      (current, result) => ({
        ...current,
        utilityRates: prepend(result, current.utilityRates),
      }),
      "Utility rate appended to protected history.",
      form,
    );
  }

  function confirmExchange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload =
      exchangeSource === "ABA_AUTOMATIC"
        ? {
            rate_source: "ABA_AUTOMATIC" as const,
            usd_amount_cents: Number(data.get("exchange-usd-cents")),
          }
        : {
            rate_source: "ABA_EQUIVALENT_MANUAL" as const,
            reference_rate_khr_per_usd: text(data, "exchange-reference-rate"),
            source_reference: text(data, "exchange-reference").trim(),
            applicable_at: cambodiaTimestamp(
              text(data, "exchange-applicable-at"),
            ),
            automatic_source_unavailable: true as const,
            fallback_reason: text(data, "exchange-fallback-reason").trim(),
            usd_amount_cents: Number(data.get("exchange-usd-cents")),
          };
    complete(
      "exchange",
      payload,
      (key) => api.confirmExchangeRate(targetPropertyId, payload, key),
      (current, result) => ({
        ...current,
        exchangeRates: prepend(result, current.exchangeRates),
      }),
      "Exchange-rate evidence confirmed and calculated by the server.",
      form,
    );
  }

  function loadOlder(kind: "service" | "utility" | "exchange") {
    if (snapshot === null) return;
    const cursor =
      kind === "service"
        ? snapshot.serviceNextCursor
        : kind === "utility"
          ? snapshot.utilityNextCursor
          : snapshot.exchangeNextCursor;
    if (cursor === null) return;
    setBusy(true);
    setFailed(false);
    let command: Promise<void>;
    if (kind === "service") {
      command = api.loadServiceRates(targetPropertyId, cursor).then((page) => {
        setSnapshot((current) => {
          if (current === null) return current;
          return {
            ...current,
            serviceRates: [...current.serviceRates, ...page.items],
            serviceNextCursor: page.nextCursor,
          };
        });
      });
    } else if (kind === "utility") {
      command = api.loadUtilityRates(targetPropertyId, cursor).then((page) => {
        setSnapshot((current) =>
          current === null
            ? current
            : {
                ...current,
                utilityRates: [...current.utilityRates, ...page.items],
                utilityNextCursor: page.nextCursor,
              },
        );
      });
    } else {
      command = api.loadExchangeRates(targetPropertyId, cursor).then((page) => {
        setSnapshot((current) =>
          current === null
            ? current
            : {
                ...current,
                exchangeRates: [...current.exchangeRates, ...page.items],
                exchangeNextCursor: page.nextCursor,
              },
        );
      });
    }
    void command
      .then(() => {
        setStatus("Older protected configuration history loaded.");
      })
      .catch((error: unknown) => {
        setFailed(true);
        setStatus(
          `Older configuration history could not be loaded.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function loadMoreConfiguredServices() {
    if (snapshot?.configuredServiceNextCursor === null || snapshot === null)
      return;
    setBusy(true);
    setFailed(false);
    void api
      .loadConfiguredServices(
        targetPropertyId,
        snapshot.configuredServiceNextCursor,
      )
      .then((page) => {
        setSnapshot((current) => {
          if (current === null) return current;
          const known = new Set(
            current.configuredServices.map((item) => item.id),
          );
          return {
            ...current,
            configuredServices: [
              ...current.configuredServices,
              ...page.items.filter((item) => !known.has(item.id)),
            ],
            configuredServiceNextCursor: page.nextCursor,
          };
        });
        setStatus("More configured Services loaded.");
      })
      .catch((error: unknown) => {
        setFailed(true);
        setStatus(
          `Configured Services could not be loaded.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <section
      aria-labelledby="effective-configuration-heading"
      className="information-card"
    >
      <h4 id="effective-configuration-heading">
        Effective-dated configuration
      </h4>
      <p>
        Historical versions are read-only. New authorized values are appended
        with their effective date and evidence.
      </p>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          load();
        }}
      >
        <label>
          Effective configuration Property identifier
          <input
            onChange={(event) => {
              setTargetPropertyId(event.target.value.trim());
            }}
            required
            value={targetPropertyId}
          />
        </label>
        <button disabled={busy || targetPropertyId.length === 0} type="submit">
          Load effective-dated configuration
        </button>
      </form>
      {status !== null && <p role={failed ? "alert" : "status"}>{status}</p>}
      {snapshot !== null && (
        <div className="administration-grid">
          <section aria-labelledby="service-rate-heading">
            <h5 id="service-rate-heading">Service rate history</h5>
            {snapshot.serviceRates.length === 0 ? (
              <p>No Service rates are configured.</p>
            ) : (
              <table>
                <caption>Service rate history, newest first</caption>
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Effective</th>
                    <th>Monthly USD</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.serviceRates.map((rate) => (
                    <tr key={rate.id}>
                      <td>
                        {rate.display_name} ({rate.service_code})
                      </td>
                      <td>{rate.effective_date}</td>
                      <td>{(rate.monthly_rate_usd_cents / 100).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {snapshot.serviceNextCursor !== null && (
              <button
                disabled={busy}
                onClick={() => {
                  loadOlder("service");
                }}
                type="button"
              >
                Load older Service rates
              </button>
            )}
            {snapshot.capabilities.manage_service_rates && (
              <form className="form-stack" onSubmit={createService}>
                <label>
                  Configured Service
                  <select
                    disabled={snapshot.configuredServices.length === 0}
                    name="service-id"
                    required
                  >
                    <option value="">Select a configured Service</option>
                    {snapshot.configuredServices.map((service) => (
                      <option key={service.id} value={service.id}>
                        {service.display_name} ({service.service_code})
                      </option>
                    ))}
                  </select>
                </label>
                {snapshot.configuredServices.length === 0 && (
                  <p role="status">
                    No configured Services are available. Configure the Service
                    identity through the authorized upstream workflow first.
                  </p>
                )}
                {snapshot.configuredServiceNextCursor !== null && (
                  <button
                    disabled={busy}
                    onClick={loadMoreConfiguredServices}
                    type="button"
                  >
                    Load more configured Services
                  </button>
                )}
                <label>
                  Monthly rate in USD cents
                  <input
                    min="1"
                    name="service-rate-cents"
                    required
                    type="number"
                  />
                </label>
                <label>
                  Effective date
                  <input name="service-effective-date" required type="date" />
                </label>
                <label>
                  Approval memo
                  <textarea maxLength={500} name="service-memo" />
                </label>
                <button
                  disabled={busy || snapshot.configuredServices.length === 0}
                  type="submit"
                >
                  Append Service rate
                </button>
              </form>
            )}
          </section>
          <section aria-labelledby="utility-rate-heading">
            <h5 id="utility-rate-heading">Utility rate history</h5>
            {snapshot.utilityRates.length === 0 ? (
              <p>No Utility rates are configured.</p>
            ) : (
              <table>
                <caption>Utility rate history, newest first</caption>
                <thead>
                  <tr>
                    <th>Utility</th>
                    <th>Effective</th>
                    <th>Rate and unit</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.utilityRates.map((rate) => (
                    <tr key={rate.id}>
                      <td>{rate.utility_type}</td>
                      <td>{rate.effective_date}</td>
                      <td>
                        {rate.rate_usd_per_unit} /{" "}
                        {measurementUnitLabel(rate.measurement_unit_code)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {snapshot.utilityNextCursor !== null && (
              <button
                disabled={busy}
                onClick={() => {
                  loadOlder("utility");
                }}
                type="button"
              >
                Load older Utility rates
              </button>
            )}
            {snapshot.capabilities.manage_utility_rates && (
              <form className="form-stack" onSubmit={createUtility}>
                <label>
                  Utility type
                  <select name="utility-type">
                    <option value="ELECTRICITY">Electricity</option>
                    <option value="WATER">Water</option>
                  </select>
                </label>
                <p className="panel-help">
                  Electricity is measured in kWh and water in m³.
                </p>
                <label>
                  USD rate per unit
                  <input
                    min="0.00000001"
                    name="utility-rate"
                    required
                    step="0.00000001"
                    type="number"
                  />
                </label>
                <label>
                  Effective date
                  <input name="utility-effective-date" required type="date" />
                </label>
                <label>
                  Notice timestamp
                  <input
                    name="utility-notice-at"
                    required
                    type="datetime-local"
                  />
                </label>
                <label>
                  Advance-notice evidence
                  <textarea
                    maxLength={500}
                    name="utility-notice-evidence"
                    required
                  />
                </label>
                <label>
                  Source memo
                  <textarea maxLength={500} name="utility-memo" />
                </label>
                <button disabled={busy} type="submit">
                  Append Utility rate
                </button>
              </form>
            )}
          </section>
          <section aria-labelledby="exchange-rate-heading">
            <h5 id="exchange-rate-heading">Payment exchange-rate evidence</h5>
            {snapshot.exchangeRates.length === 0 ? (
              <p>No exchange-rate evidence is recorded.</p>
            ) : (
              <table>
                <caption>Exchange-rate evidence, newest first</caption>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>System rate</th>
                    <th>Payable KHR</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.exchangeRates.map((rate) => (
                    <tr key={rate.id}>
                      <td>{rate.rate_source}</td>
                      <td>{rate.system_rate_khr_per_usd}</td>
                      <td>{rate.payable_khr}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {snapshot.exchangeNextCursor !== null && (
              <button
                disabled={busy}
                onClick={() => {
                  loadOlder("exchange");
                }}
                type="button"
              >
                Load older exchange rates
              </button>
            )}
            {snapshot.capabilities.manage_exchange_rates && (
              <form className="form-stack" onSubmit={confirmExchange}>
                <label>
                  Rate source
                  <select
                    name="exchange-source"
                    onChange={(event) => {
                      setExchangeSource(
                        event.target.value === "ABA_EQUIVALENT_MANUAL"
                          ? "ABA_EQUIVALENT_MANUAL"
                          : "ABA_AUTOMATIC",
                      );
                    }}
                    value={exchangeSource}
                  >
                    <option value="ABA_AUTOMATIC">ABA automatic</option>
                    <option value="ABA_EQUIVALENT_MANUAL">
                      Authorized manual fallback
                    </option>
                  </select>
                </label>
                {exchangeSource === "ABA_EQUIVALENT_MANUAL" && (
                  <>
                    <label>
                      ABA-equivalent reference sell rate
                      <input
                        min="0.000001"
                        name="exchange-reference-rate"
                        required
                        step="0.000001"
                        type="number"
                      />
                    </label>
                    <label>
                      Source evidence reference
                      <input
                        maxLength={500}
                        name="exchange-reference"
                        required
                      />
                    </label>
                    <label>
                      Automatic-source failure reason
                      <textarea
                        maxLength={500}
                        name="exchange-fallback-reason"
                        required
                      />
                    </label>
                    <label>
                      Applicable timestamp
                      <input
                        name="exchange-applicable-at"
                        required
                        type="datetime-local"
                      />
                    </label>
                  </>
                )}
                <label>
                  Payment amount in USD cents
                  <input
                    min="1"
                    name="exchange-usd-cents"
                    required
                    type="number"
                  />
                </label>
                <button disabled={busy} type="submit">
                  Confirm and calculate exchange rate
                </button>
                <p className="panel-help">
                  The server applies 0.5%, rounds the system rate up to whole
                  KHR, then rounds final KHR payable up. Calculated values are
                  read-only.
                </p>
              </form>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
