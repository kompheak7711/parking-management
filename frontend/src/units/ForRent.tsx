// V1.1 rework part 1 (owner 2026-11-02, mock-up v53): For rent Yes or No. A Unit that is not for
// rent (for example the warehouse W01) is left out of every renting screen. A Manager or the
// Owner changes it on the Unit page; a Unit with a Reservation or a Lease stays for rent.

import { FormEvent, useState } from "react";

import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type UnitApi,
  UnitConflictError,
  UnitInUseError,
  type UnitResource,
} from "../unitClient";
import { ut } from "./text";

/** A Unit is for rent unless the server says No. */
export function isForRent(unit: Pick<UnitResource, "for_rent">): boolean {
  return unit.for_rent !== false;
}

/**
 * Owner 02/11/2026: a Reserved or Occupied Unit is in use, so For rent cannot be changed. The
 * server also refuses it for an active Reservation or a draft or signed Lease.
 */
export function isInUse(unit: Pick<UnitResource, "status">): boolean {
  return unit.status === "RESERVED" || unit.status === "OCCUPIED";
}

/** For rent Yes or Not for rent, shared by New Unit, Update Unit and Change. */
export function ForRentField({
  language,
  value,
  onChange,
  name = "unit-for-rent",
  locked = false,
}: {
  language: Language;
  value: boolean;
  onChange: (value: boolean) => void;
  name?: string;
  /** True for a Unit in use: the choice is shown but cannot be changed. */
  locked?: boolean;
}) {
  return (
    <>
      <fieldset className="ui-radios" disabled={locked}>
        <legend>{ut(language, "fr_col")}</legend>
        {([true, false] as const).map((choice) => (
          <label className="ui-chk" key={String(choice)}>
            <input
              checked={value === choice}
              name={name}
              onChange={() => {
                onChange(choice);
              }}
              type="radio"
            />
            {ut(language, choice ? "fr_yes" : "fr_no")}
          </label>
        ))}
      </fieldset>
      <p className="ui-small ui-muted">
        {ut(language, locked ? "fr_locked" : "fr_help")}
      </p>
    </>
  );
}

export function ForRentDialog({
  api,
  language,
  unit,
  onClose,
  onSaved,
  onConflict,
}: {
  api: Pick<UnitApi, "setForRent">;
  language: Language;
  unit: UnitResource;
  onClose: () => void;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const [forRent, setForRent] = useState(isForRent(unit));
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (forRent === isForRent(unit)) {
      onClose();
      return;
    }
    setBusy(true);
    setProblem(null);
    void api
      .setForRent(unit, forRent)
      .then(onSaved)
      .catch((error: unknown) => {
        setBusy(false);
        if (error instanceof UnitInUseError) {
          setProblem(ut(language, "fr_in_use"));
          return;
        }
        if (error instanceof UnitConflictError) {
          onConflict();
          return;
        }
        setProblem(ut(language, "not_saved"));
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ut(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ut(language, "save")}
      title={`${ut(language, "fr_title")} · ${unit.unit_number}`}
    >
      <ForRentField
        language={language}
        locked={isInUse(unit)}
        onChange={setForRent}
        value={forRent}
      />
      {problem !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </Dialog>
  );
}
