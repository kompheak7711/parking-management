// V1-058 R2: New Unit, Update Unit and Change status (DESIGN.md "Units (round 2)"; owner
// 2026-10-24 19:24: the Unit number is fixed, the Unit Type comes from the Settings list).

import { FormEvent, useState } from "react";

import { HOME_FIELDS, ROOM_FEATURES, UNIT_INVENTORY } from "../leases/parking";
import type { Language } from "../signInText";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import {
  UnitApi,
  UnitConflictError,
  UnitDetails,
  UnitInUseError,
  UnitInvalidError,
  UnitResource,
  UnitSetupItem,
  UnitSetupLists,
  UnitStatus,
} from "../unitClient";
import { ForRentField, isForRent, isInUse } from "./ForRent";
import {
  RentTermsFields,
  type RentTermsServicesApi,
  rentCents,
  useServices,
} from "./RentTerms";
import { ut } from "./text";

function text(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function itemLabel(item: UnitSetupItem, language: Language): string {
  return language === "km" && item.name_km !== null
    ? item.name_km
    : item.name_en;
}

// The items a form may pick: those not removed, plus the one the Unit already uses.
function choices(items: UnitSetupItem[], current?: string | null) {
  return items.filter((item) => !item.removed || item.item_id === current);
}

// V1.1 (DL-115 (I)): Bedrooms, Bathrooms, Kitchen and the Room features are no longer asked;
// the Unit page's features list says them. An update leaves the old values as they were.
// Parking Step 5: a hidden field is left out of the request, not sent as empty, so the server
// keeps whatever the row already holds (it clears a field only when it receives one).
function detailsFrom(
  data: FormData,
): Partial<Pick<UnitDetails, "size_square_metres" | "view_item_id" | "notes">> {
  const details: Partial<Pick<UnitDetails, "size_square_metres" | "view_item_id" | "notes">> = {
    notes: text(data, "notes") || null,
  };
  if (HOME_FIELDS) {
    const size = text(data, "size");
    details.size_square_metres = size === "" ? null : Number(size).toFixed(2);
    details.view_item_id = text(data, "view") || null;
  }
  return details;
}

function failure(language: Language, error: unknown): string {
  if (error instanceof UnitInvalidError) return ut(language, "invalid");
  if (error instanceof UnitConflictError) return ut(language, "conflict");
  return ut(language, "not_saved");
}

function Problem({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{message}</span>
    </p>
  );
}

function FloorField({
  language,
  lists,
  current,
  missing,
}: {
  language: Language;
  lists: UnitSetupLists;
  current: string | null;
  missing: boolean;
}) {
  return (
    <div className="ui-field">
      <label htmlFor="unit-floor">
        {ut(language, "floor")}
        <span className="req">{ut(language, "required")}</span>
      </label>
      <select
        aria-invalid={missing}
        defaultValue={current ?? ""}
        id="unit-floor"
        name="floor"
      >
        <option value="">{ut(language, "pick_floor")}</option>
        {choices(lists.lists.FLOOR, current).map((item) => (
          <option key={item.item_id} value={item.item_id}>
            {itemLabel(item, language)}
          </option>
        ))}
      </select>
      {missing && <Problem message={ut(language, "floor_req")} />}
    </div>
  );
}

function DetailFields({
  language,
  lists,
  unit,
}: {
  language: Language;
  lists: UnitSetupLists;
  unit: UnitResource | null;
}) {
  const optionalSelect = (
    kind: "VIEW",
    name: "view",
    current: string | null,
  ) => (
    <div className="ui-field">
      <label htmlFor={`unit-${name}`}>{ut(language, name)}</label>
      <select defaultValue={current ?? ""} id={`unit-${name}`} name={name}>
        <option value="">{ut(language, "not_recorded")}</option>
        {choices(lists.lists[kind], current).map((item) => (
          <option key={item.item_id} value={item.item_id}>
            {itemLabel(item, language)}
          </option>
        ))}
      </select>
    </div>
  );
  const types = lists.lists.UNIT_TYPE.filter(
    (item) => !item.removed || item.code === unit?.unit_type,
  );
  return (
    <>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="unit-type">{ut(language, "type")}</label>
          <select
            defaultValue={unit?.unit_type ?? types[0]?.code}
            id="unit-type"
            name="type"
          >
            {types.map((item) => (
              <option key={item.item_id} value={item.code}>
                {itemLabel(item, language)}
              </option>
            ))}
          </select>
        </div>
        {HOME_FIELDS && (
          <div className="ui-field">
            <label htmlFor="unit-size">{ut(language, "size")} (m²)</label>
            <input
              defaultValue={unit?.size_square_metres ?? ""}
              id="unit-size"
              inputMode="decimal"
              max="10000"
              min="0.01"
              name="size"
              step="0.01"
              type="number"
            />
          </div>
        )}
      </div>
      {HOME_FIELDS && optionalSelect("VIEW", "view", unit?.view_item_id ?? null)}
      <div className="ui-field">
        <label htmlFor="unit-notes">{ut(language, "notes")}</label>
        <textarea
          defaultValue={unit?.notes ?? ""}
          id="unit-notes"
          maxLength={2000}
          name="notes"
          rows={3}
        />
      </div>
    </>
  );
}

/** New Unit: the number and floor are required; the Unit starts as Vacant. */
export function NewUnitDialog({
  api,
  servicesApi,
  language,
  lists,
  propertyId,
  onClose,
  onCreated,
}: {
  api: UnitApi;
  servicesApi: RentTermsServicesApi;
  language: Language;
  lists: UnitSetupLists;
  propertyId: string;
  onClose: () => void;
  onCreated: (unit: UnitResource) => void;
}) {
  // V1-061 (owner 29/10/2026): the default Rent and the required Services are set here too, saved
  // right after the Unit with the same Change command the Unit page uses.
  const read = useServices(servicesApi, propertyId);
  const services = read === null || read === "failed" ? read : read.services;
  const [rent, setRent] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [rentProblem, setRentProblem] = useState<string | null>(null);
  // V1.1 rework part 1 (owner 02/11/2026): For rent is chosen on New Unit too.
  const [forRent, setForRent] = useState(true);
  // The Unit is saved but its Rent and Services were not; the next press only closes.
  const [saved, setSaved] = useState<UnitResource | null>(null);
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState<{ no: boolean; floor: boolean }>({
    no: false,
    floor: false,
  });
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saved !== null) {
      onCreated(saved);
      return;
    }
    const form = event.currentTarget;
    const data = new FormData(form);
    // Unit numbers are kept in capitals, as in the mock-up (U107).
    const unitNumber = text(data, "number").toUpperCase();
    const floor = text(data, "floor");
    const blanks = { no: unitNumber === "", floor: floor === "" };
    setMissing(blanks);
    if (blanks.no || blanks.floor) {
      form
        .querySelector<HTMLElement>(blanks.no ? "#unit-number" : "#unit-floor")
        ?.focus();
      return;
    }
    const cents = rentCents(rent);
    setRentProblem(cents === "wrong" ? ut(language, "rt_err_rent") : null);
    if (cents === "wrong") {
      form.querySelector<HTMLElement>("#unit-rent-default")?.focus();
      return;
    }
    if (chosen.size > 20) {
      setProblem(ut(language, "rt_err_many"));
      return;
    }
    setBusy(true);
    setProblem(null);
    void api
      .create(propertyId, {
        unit_number: unitNumber,
        floor_item_id: floor,
        unit_type: text(data, "type"),
        status: "VACANT",
        ...detailsFrom(data),
      })
      .then(
        (created) => {
          // A Unit not for rent is set so right after it is saved, before its Rent terms.
          const marked = forRent
            ? Promise.resolve(created)
            : api.setForRent(created, false).catch(() => {
                setSaved(created);
                setProblem(
                  ut(language, "fr_new_not_saved", created.unit_number),
                );
                setBusy(false);
                return null;
              });
          void marked.then((unit) => {
            if (unit === null) return;
            if (cents === null && chosen.size === 0) {
              onCreated(unit);
              return;
            }
            api
              .setRentTerms(unit, {
                default_monthly_rent_usd_cents: cents,
                required_service_ids: [...chosen],
                // Parking Step 3: the first price needs no typed reason; History says it
                // came with the new Parking.
                reason: "Set with the new Parking",
              })
              .then(onCreated)
              .catch(() => {
                setSaved(unit);
                setProblem(ut(language, "rt_new_not_saved", unit.unit_number));
                setBusy(false);
              });
          });
        },
        (error: unknown) => {
          setProblem(failure(language, error));
          setBusy(false);
        },
      );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ut(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ut(language, saved === null ? "save" : "ok")}
      title={ut(language, "new_unit")}
    >
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="unit-number">
            {ut(language, "unit_no")}
            <span className="req">{ut(language, "required")}</span>
          </label>
          <input
            aria-invalid={missing.no}
            autoComplete="off"
            className="ui-num"
            id="unit-number"
            maxLength={100}
            name="number"
            placeholder="U107"
          />
          {missing.no && <Problem message={ut(language, "no_req")} />}
        </div>
        <FloorField
          current={null}
          language={language}
          lists={lists}
          missing={missing.floor}
        />
      </div>
      <DetailFields language={language} lists={lists} unit={null} />
      <ForRentField language={language} onChange={setForRent} value={forRent} />
      <RentTermsFields
        chosen={chosen}
        language={language}
        onChosen={setChosen}
        onRent={setRent}
        rent={rent}
        rentProblem={rentProblem}
        services={services}
      />
      <p className="ui-small ui-muted">
        {ut(language, UNIT_INVENTORY ? "new_note" : "new_note_parking")}
      </p>
      <Problem message={problem} />
    </Dialog>
  );
}

/** Update Unit: every detail except the Unit number, which cannot change. */
export function UpdateUnitDialog({
  api,
  language,
  lists,
  unit,
  onClose,
  onSaved,
  onConflict,
}: {
  api: UnitApi;
  language: Language;
  lists: UnitSetupLists;
  unit: UnitResource;
  onClose: () => void;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [missingFloor, setMissingFloor] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // V1.1 rework part 1 (owner 02/11/2026): For rent can be changed here too.
  const [forRent, setForRent] = useState(isForRent(unit));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const floor = text(data, "floor");
    setMissingFloor(floor === "");
    if (floor === "") {
      form.querySelector<HTMLElement>("#unit-floor")?.focus();
      return;
    }
    setBusy(true);
    setProblem(null);
    // For rent goes first: a Unit in use for renting refuses it and nothing is saved.
    const marked =
      forRent === isForRent(unit)
        ? Promise.resolve(unit)
        : api.setForRent(unit, forRent);
    void marked
      .then((current) =>
        api.update(current, {
          floor_item_id: floor,
          unit_type: text(data, "type"),
          ...detailsFrom(data),
        }),
      )
      .then(onSaved)
      .catch((error: unknown) => {
        setBusy(false);
        if (error instanceof UnitInUseError) {
          setProblem(ut(language, "fr_in_use"));
          return;
        }
        setProblem(failure(language, error));
        if (error instanceof UnitConflictError) onConflict();
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ut(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ut(language, "save")}
      title={`${ut(language, "update_unit")} · ${unit.unit_number}`}
    >
      <FloorField
        current={unit.floor_item_id}
        language={language}
        lists={lists}
        missing={missingFloor}
      />
      <DetailFields language={language} lists={lists} unit={unit} />
      <ForRentField
        language={language}
        locked={isInUse(unit)}
        onChange={setForRent}
        value={forRent}
      />
      <p className="ui-small ui-muted">{ut(language, "edit_note")}</p>
      <Problem message={problem} />
    </Dialog>
  );
}

const STATUS_CHOICES: UnitStatus[] = [
  "VACANT",
  "CLEANING",
  "UNDER_MAINTENANCE",
  "OUT_OF_SERVICE",
];

/**
 * Change status with a reason, which goes into the Unit's History. Occupied, Reserved and Short
 * stay are worked out from the Unit's records (C2, DL-241); staff set only its condition, and a
 * Unit with a signed Lease or an active Reservation cannot be changed here.
 */
export function ChangeStatusDialog({
  api,
  language,
  unit,
  blocked,
  onClose,
  onSaved,
  onConflict,
}: {
  api: UnitApi;
  language: Language;
  unit: UnitResource;
  blocked: "lease" | "reservation" | null;
  onClose: () => void;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [reasonMissing, setReasonMissing] = useState(false);
  const title = `${ut(language, "change_status")} · ${unit.unit_number}`;

  if (blocked !== null) {
    return (
      <Dialog closeLabel={ut(language, "ok")} onClose={onClose} title={title}>
        <div className="ui-notice">
          <Icon name="info" />
          <p>
            {ut(
              language,
              blocked === "lease" ? "blocked_lease" : "blocked_res",
            )}
          </p>
        </div>
      </Dialog>
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const status = text(data, "status") as UnitStatus;
    const reason = text(data, "reason");
    setReasonMissing(reason === "");
    if (
      status === (unit.condition ?? unit.status) ||
      !STATUS_CHOICES.includes(status)
    ) {
      setProblem(ut(language, "same_status"));
      return;
    }
    if (reason === "") {
      setProblem(null);
      form.querySelector<HTMLElement>("#status-reason")?.focus();
      return;
    }
    setBusy(true);
    setProblem(null);
    void api
      .update(unit, { status, reason })
      .then(onSaved)
      .catch((error: unknown) => {
        setProblem(failure(language, error));
        setBusy(false);
        if (error instanceof UnitConflictError) onConflict();
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ut(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ut(language, "save")}
      title={title}
    >
      <fieldset className="ui-radios">
        <legend>{ut(language, "new_status")}</legend>
        {STATUS_CHOICES.map((status) => (
          <label className="ui-chk" key={status}>
            <input
              defaultChecked={(unit.condition ?? unit.status) === status}
              name="status"
              type="radio"
              value={status}
            />
            <span>{ut(language, `s_${status}`)}</span>
          </label>
        ))}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="status-reason">
          {ut(language, "reason")}
          <span className="req">{ut(language, "required")}</span>
        </label>
        <input
          aria-invalid={reasonMissing}
          autoComplete="off"
          id="status-reason"
          maxLength={500}
          name="reason"
        />
        {reasonMissing && <Problem message={ut(language, "reason_req")} />}
      </div>
      <p className="ui-small ui-muted">{ut(language, "status_note")}</p>
      <Problem message={problem} />
    </Dialog>
  );
}
