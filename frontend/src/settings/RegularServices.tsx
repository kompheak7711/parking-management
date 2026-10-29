// V1.1 (DL-115 (I); mock-up round 13): the Regular services of Settings → Rates and services.
// Each has an English and a Khmer name and a set price. Staff never type a price on a Services
// Invoice: it always comes from here, and a new price is used for new Invoices only. A service
// on an Invoice this year can be removed only next year (the server refuses it too).

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { centsOf } from "../invoices/invoicesData";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { Problem } from "./BusinessTab";
import {
  failureText,
  Field,
  focusFirst,
  NameFields,
  nameErrors,
  nameOf,
} from "./ServiceDialogs";
import {
  type RegularService,
  type RegularServiceForm,
  type RegularServices,
  type RegularServicesApi,
  ServiceSettingsError,
} from "./serviceSettingsClient";
import { sst } from "./text";

type Open =
  | { kind: "edit"; service: RegularService | null }
  | { kind: "remove"; service: RegularService };

function RegularServiceDialog({
  language,
  service,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  /** null: a new service. */
  service: RegularService | null;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (form: RegularServiceForm) => void;
}) {
  const [nameEn, setNameEn] = useState(service?.name_en ?? "");
  const [nameKm, setNameKm] = useState(service?.name_km ?? "");
  const [amount, setAmount] = useState(
    service === null ? "" : (service.price_usd_cents / 100).toFixed(2),
  );
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = nameErrors(language, "rs", nameEn, nameKm);
    const cents = centsOf(amount);
    if (cents === null) found["rs-price"] = sst(language, "err_amount");
    setErrors(found);
    if (focusFirst(found, ["rs-en", "rs-km", "rs-price"])) return;
    if (cents === null) return;
    onSave({
      name_en: nameEn.trim(),
      name_km: nameKm.trim() || null,
      price_usd_cents: cents,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={
        service === null
          ? sst(language, "rs_add")
          : `${sst(language, "rs_edit_t")} · ${nameOf(language, service)}`
      }
    >
      <NameFields
        errors={errors}
        language={language}
        nameEn={nameEn}
        nameKm={nameKm}
        onEn={setNameEn}
        onKm={setNameKm}
        prefix="rs"
      />
      <Field
        error={errors["rs-price"]}
        id="rs-price"
        label={sst(language, "rs_price")}
        required={sst(language, "required")}
      >
        {(describedBy) => (
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              aria-describedby={describedBy}
              aria-invalid={errors["rs-price"] !== undefined}
              autoComplete="off"
              id="rs-price"
              inputMode="decimal"
              onChange={(event) => {
                setAmount(event.currentTarget.value);
              }}
              value={amount}
            />
          </div>
        )}
      </Field>
      <p className="ui-small ui-muted">{sst(language, "rs_note")}</p>
      <Problem text={problem} />
    </Dialog>
  );
}

export function RegularServicesCard({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: RegularServicesApi;
}) {
  // "failed": nothing to show or change until a read works.
  const [settings, setSettings] = useState<RegularServices | "failed" | null>(
    null,
  );
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);
  // The id of a new service stays until the server confirms it, so a resend after a lost
  // answer never adds a second service.
  const pending = useRef<string | null>(null);

  const load = useCallback((): Promise<void> => {
    if (propertyId === "") return Promise.resolve();
    const operation = ++sequence.current;
    return api.read(propertyId).then(
      (found) => {
        if (operation === sequence.current) setSettings(found);
      },
      () => {
        if (operation !== sequence.current) return;
        setSettings((before) =>
          before !== null && before !== "failed" ? before : "failed",
        );
      },
    );
  }, [api, propertyId]);

  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    pending.current = null;
    setSettings(null);
    setOpen(null);
    setProblem(null);
    setToast(null);
    setBusy(false);
  }, [propertyId]);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  function run(work: () => Promise<unknown>, done: string, adding: boolean) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    work()
      .then(
        () => {
          if (shownProperty.current !== asked) return undefined;
          if (adding) pending.current = null;
          setOpen(null);
          setToast({ ok: true, text: done });
          return load();
        },
        (error: unknown) => {
          if (shownProperty.current !== asked) return undefined;
          const found =
            error instanceof ServiceSettingsError ? error.failure : "unknown";
          if (found === "id_reused" && adding) pending.current = null;
          if (found === "id_reused" || found === "not_found") {
            setOpen(null);
            setToast({ ok: false, text: failureText(language, found) });
            return load();
          }
          setProblem(failureText(language, found));
          if (
            found === "out_of_date" ||
            found === "used_this_year" ||
            found === "unknown"
          ) {
            return load();
          }
          return undefined;
        },
      )
      .finally(() => {
        if (shownProperty.current === asked) setBusy(false);
      });
  }

  if (settings === null) return null;
  if (settings === "failed") {
    return (
      <section aria-labelledby="rates-regular" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="rates-regular">{sst(language, "rs_title")}</h2>
        </header>
        <div className="ui-notice warn pad" role="status">
          <Icon name="alert" />
          <p>{sst(language, "rs_read_failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              void load();
            }}
            type="button"
          >
            {sst(language, "retry")}
          </button>
        </div>
      </section>
    );
  }

  const manage = settings.can_manage;
  const latest = (service: RegularService) =>
    settings.regular_services.find(
      (item) => item.regular_service_id === service.regular_service_id,
    ) ?? service;
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };
  const removing = open?.kind === "remove" ? latest(open.service) : null;

  return (
    <>
      <div aria-live="polite" role="status">
        {toast !== null && (
          <div className={toast.ok ? "ui-notice ok" : "ui-notice warn"}>
            <Icon name={toast.ok ? "check" : "alert"} />
            <p>{toast.text}</p>
          </div>
        )}
      </div>
      <section aria-labelledby="rates-regular" className="ui-card pad0">
        <header className="ui-chead pad">
          <div>
            <h2 id="rates-regular">{sst(language, "rs_title")}</h2>
            <p className="ui-small ui-muted">{sst(language, "rs_sub")}</p>
          </div>
          {manage && (
            <button
              className="ui-btn"
              onClick={() => {
                setProblem(null);
                setToast(null);
                setOpen({ kind: "edit", service: null });
              }}
              type="button"
            >
              <Icon name="plus" small />
              {sst(language, "rs_add")}
            </button>
          )}
        </header>
        {settings.regular_services.length === 0 ? (
          <p className="pad ui-muted">{sst(language, "rs_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{sst(language, "cl_name")}</th>
                  <th className="r" scope="col">
                    {sst(language, "rs_price")}
                  </th>
                  <th className="r" scope="col">
                    {sst(language, "rs_used")}
                  </th>
                  {manage && (
                    <th scope="col">
                      <span className="ui-sr">{sst(language, "actions")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {settings.regular_services.map((service) => {
                  const name = nameOf(language, service);
                  return (
                    <tr key={service.regular_service_id}>
                      <td>
                        <b>{name}</b>
                      </td>
                      <td className="r ui-num">
                        {usdFromCents(service.price_usd_cents)}
                      </td>
                      <td className="r ui-num">{service.used_this_year}</td>
                      {manage && (
                        <td>
                          <span className="ui-actions">
                            <button
                              aria-label={`${sst(language, "cf_edit")}: ${name}`}
                              className="ui-btn link"
                              onClick={() => {
                                setProblem(null);
                                setToast(null);
                                setOpen({ kind: "edit", service });
                              }}
                              type="button"
                            >
                              {sst(language, "cf_edit")}
                            </button>
                            <button
                              aria-label={`${sst(language, "set_remove")}: ${name}`}
                              className="ui-btn link"
                              onClick={() => {
                                setProblem(null);
                                setToast(null);
                                setOpen({ kind: "remove", service });
                              }}
                              type="button"
                            >
                              {sst(language, "set_remove")}
                            </button>
                          </span>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="ui-tfoot">
          <span>{sst(language, "rs_note")}</span>
        </div>
      </section>

      {open?.kind === "edit" && (
        <RegularServiceDialog
          key={
            open.service === null
              ? "new"
              : `${open.service.regular_service_id}-${String(latest(open.service).version)}`
          }
          busy={busy}
          language={language}
          onClose={closeOpen}
          onSave={(form) => {
            if (open.service !== null) {
              const service = latest(open.service);
              run(
                () =>
                  api.change(propertyId, service.regular_service_id, {
                    ...form,
                    version: service.version,
                  }),
                sst(language, "sv_changed", nameOf(language, form)),
                false,
              );
              return;
            }
            const serviceId = pending.current ?? crypto.randomUUID();
            pending.current = serviceId;
            run(
              () =>
                api.add(propertyId, { regular_service_id: serviceId, ...form }),
              sst(language, "sv_added", nameOf(language, form)),
              true,
            );
          }}
          problem={problem}
          service={open.service === null ? null : latest(open.service)}
        />
      )}
      {removing !== null && (
        <Dialog
          actions={
            removing.used_this_year === 0 ? (
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  run(
                    () =>
                      api.remove(
                        propertyId,
                        removing.regular_service_id,
                        removing.version,
                      ),
                    sst(language, "set_removed", nameOf(language, removing)),
                    false,
                  );
                }}
                type="button"
              >
                {sst(language, "set_remove")}
              </button>
            ) : undefined
          }
          busy={busy}
          closeLabel={sst(language, "cancel")}
          onClose={closeOpen}
          title={`${sst(language, "set_remove")} · ${nameOf(language, removing)}`}
        >
          {removing.used_this_year === 0 ? (
            <p>{sst(language, "set_remove_q", nameOf(language, removing))}</p>
          ) : (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{sst(language, "rs_block", removing.used_this_year)}</p>
            </div>
          )}
          <Problem text={problem} />
        </Dialog>
      )}
    </>
  );
}
