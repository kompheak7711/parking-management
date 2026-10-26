// V1-058 R4: the Unit box of both Utilities tabs, and how a Unit's Customer is named.

import { useState } from "react";

import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import type { UnitResource } from "../unitClient";
import { utt, type UtilitiesTextKey } from "./text";
import { findUnit, type UtilitiesData } from "./utilitiesData";

/** The Unit box: type "U302", "u302" or "302", or pick from the list; empty is All Units. */
export function UnitBox({
  language,
  units,
  customers,
  unit,
  onUnit,
}: {
  language: Language;
  units: readonly UnitResource[];
  customers: ReadonlyMap<string, string>;
  unit: UnitResource | null;
  onUnit: (unit: UnitResource | null) => void;
}) {
  const [typed, setTyped] = useState(unit?.unit_number ?? "");
  const [bad, setBad] = useState<string | null>(null);
  const commit = (value: string) => {
    const found = findUnit(units, value);
    if (found === undefined) {
      setBad(value.trim());
      return;
    }
    setBad(null);
    setTyped(found?.unit_number ?? "");
    onUnit(found);
  };
  return (
    <form
      className="ui-combo"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        commit(typed);
      }}
    >
      <label htmlFor="ut-unit">{utt(language, "unit")}</label>
      <input
        aria-describedby={bad === null ? undefined : "ut-unit-err"}
        aria-invalid={bad === null ? undefined : true}
        autoComplete="off"
        className="ui-search"
        id="ut-unit"
        list="ut-units"
        onBlur={() => {
          commit(typed);
        }}
        onChange={(event) => {
          const value = event.currentTarget.value;
          setTyped(value);
          // Picking from the list fills the whole number: use it at once. A number that is
          // still the start of another one ("U10" of "U101") waits for Enter or leaving the box.
          const found = findUnit(units, value);
          const longer =
            found !== undefined &&
            found !== null &&
            units.some(
              (item) =>
                item !== found &&
                item.unit_number.startsWith(found.unit_number),
            );
          if (found !== undefined && found !== null && !longer) {
            setBad(null);
            onUnit(found);
          }
        }}
        placeholder={utt(language, "all_units")}
        spellCheck={false}
        value={typed}
      />
      <datalist id="ut-units">
        {units.map((item) => (
          <option key={item.unit_id} value={item.unit_number}>
            {customers.get(item.unit_id) ?? ""}
          </option>
        ))}
      </datalist>
      {(unit !== null || bad !== null) && (
        <button
          aria-label={utt(language, "all_units")}
          className="ui-btn"
          onClick={() => {
            setTyped("");
            setBad(null);
            onUnit(null);
          }}
          title={utt(language, "all_units")}
          type="button"
        >
          <Icon name="x" />
        </button>
      )}
      {bad !== null && (
        <p className="ui-error" id="ut-unit-err" role="alert">
          <Icon name="alert" small />
          {utt(language, "unit_bad", bad, units[0]?.unit_number ?? "U101")}
        </p>
      )}
    </form>
  );
}

export function whoText(
  language: Language,
  data: UtilitiesData,
  unit: UnitResource,
): { text: string; muted: boolean } {
  const name = data.customers.get(unit.unit_id);
  if (name !== undefined) return { text: name, muted: false };
  const key: UtilitiesTextKey =
    unit.status === "VACANT"
      ? "vacant_note"
      : unit.status === "RESERVED"
        ? "reserved_note"
        : "other_note";
  return { text: utt(language, key), muted: true };
}
