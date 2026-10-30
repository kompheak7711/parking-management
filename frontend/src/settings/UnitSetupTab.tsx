// V1-058 R7b-2: Settings → Unit setup (mock-up round 9, DL-075 answer 10): Floors, Unit Types,
// Views, Kitchens and Room features, each with Add, Edit (not Floors) and Remove. The lists fill
// the choices of New Unit and Update Unit. The Unit counts come from the Units list; an item a Unit
// uses cannot be removed. R7b-6d: a Unit Type with no move-out cleaning rate shows a chip.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { CLEANING_CHARGE, HOME_FIELDS, ROOM_FEATURES } from "../leases/parking";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type UnitApi,
  UnitConflictError,
  UnitInvalidError,
  type UnitResource,
  type UnitSetupItem,
  type UnitSetupListKind,
  type UnitSetupLists,
  unitSetupListKinds,
} from "../unitClient";
import { allPages } from "../units/unitsData";
import {
  type CleaningSettingsApi,
  cleaningSettingsApi,
} from "./serviceSettingsClient";
import { type SettingsTextKey, sst } from "./text";

// Parking Step 5: no cleaning charge on Parking, so the Parking Type note says nothing about
// cleaning rates.
function noteFor(kind: UnitSetupListKind): SettingsTextKey | undefined {
  if (kind === "UNIT_TYPE" && !CLEANING_CHARGE) return "cf_type_note_parking";
  return NOTES[kind];
}

// Parking Step 5: Views and Kitchens go with the home-only fields, Room features with the
// Parking features. The list kinds stay in `unitSetupListKinds` (the parser checks them).
function shownOnParking(kind: UnitSetupListKind): boolean {
  if (kind === "VIEW" || kind === "KITCHEN") return HOME_FIELDS;
  if (kind === "ROOM_FEATURE") return ROOM_FEATURES;
  return true;
}

export type SetupApi = Pick<
  UnitApi,
  | "list"
  | "setupLists"
  | "createSetupItem"
  | "updateSetupItem"
  | "removeSetupItem"
>;

const NOTES: Partial<Record<UnitSetupListKind, SettingsTextKey>> = {
  UNIT_TYPE: "cf_type_note",
  ROOM_FEATURE: "cf_feat_note",
};

/** How many Units use the item; null when the Units could not be read. */
function unitCount(
  units: UnitResource[] | null,
  item: UnitSetupItem,
): number | null {
  if (units === null) return null;
  return units.filter((unit) => {
    switch (item.list_kind) {
      case "FLOOR":
        return unit.floor_item_id === item.item_id;
      case "UNIT_TYPE":
        return unit.unit_type === item.code;
      case "VIEW":
        return unit.view_item_id === item.item_id;
      case "KITCHEN":
        return unit.kitchen_item_id === item.item_id;
      case "ROOM_FEATURE":
        return unit.room_feature_ids.includes(item.item_id);
      default:
        return false;
    }
  }).length;
}

function itemName(language: Language, item: UnitSetupItem): string {
  return language === "km" && item.name_km ? item.name_km : item.name_en;
}

type Editing =
  | { kind: UnitSetupListKind; item: null }
  | { kind: UnitSetupListKind; item: UnitSetupItem };

function ItemDialog({
  language,
  editing,
  lists,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  editing: Editing;
  lists: UnitSetupLists;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (source: {
    name_en: string;
    name_km: string | null;
    sort_order?: number;
  }) => void;
}) {
  const { kind, item } = editing;
  const floor = kind === "FLOOR";
  const [english, setEnglish] = useState(item?.name_en ?? "");
  const [khmer, setKhmer] = useState(
    item?.name_km !== null && item?.name_km !== item?.name_en
      ? (item?.name_km ?? "")
      : "",
  );
  const [number, setNumber] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const taken = (...names: string[]) =>
      lists.lists[kind].some(
        (other) =>
          other.item_id !== item?.item_id &&
          names.some(
            (name) => other.name_en.toLowerCase() === name.toLowerCase(),
          ),
      );
    if (floor) {
      const value = Number(number);
      if (!/^\d{1,2}$/.test(number.trim()) || value > 99) {
        setError(sst(language, "cf_e_floor"));
        return;
      }
      const name = sst("en", "u_floor_n", value);
      // Floors moved over from the old Unit records are named by their number alone.
      if (taken(name, String(value))) {
        setError(sst(language, "cf_e_dup", sst(language, "u_floor_n", value)));
        return;
      }
      onSave({
        name_en: name,
        name_km: sst("km", "u_floor_n", value),
        // The moved-over Floors are ordered 10, 20, 30 …
        sort_order: value * 10,
      });
      return;
    }
    const name = english.trim();
    if (name === "") {
      setError(sst(language, "se_e_name"));
      return;
    }
    if (taken(name)) {
      setError(sst(language, "cf_e_dup", name));
      return;
    }
    onSave({ name_en: name, name_km: khmer.trim() || null });
  }

  const note = noteFor(kind);
  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={`${sst(language, item === null ? "cf_add" : "cf_edit")} · ${sst(
        language,
        `cf_one_${kind}`,
      )}`}
    >
      {floor ? (
        <div className="ui-field">
          <label htmlFor="setup-floor">{sst(language, "cf_floor_no")}</label>
          <input
            aria-describedby={error === null ? undefined : "setup-error"}
            aria-invalid={error !== null}
            autoComplete="off"
            id="setup-floor"
            inputMode="numeric"
            maxLength={2}
            onChange={(event) => {
              setNumber(event.currentTarget.value);
              setError(null);
            }}
            value={number}
          />
        </div>
      ) : (
        <div className="ui-row2">
          <div className="ui-field">
            <label htmlFor="setup-en">
              {sst(language, "cf_en")}
              <span className="req">{sst(language, "required")}</span>
            </label>
            <input
              aria-describedby={error === null ? undefined : "setup-error"}
              aria-invalid={error !== null}
              autoComplete="off"
              id="setup-en"
              maxLength={100}
              onChange={(event) => {
                setEnglish(event.currentTarget.value);
                setError(null);
              }}
              value={english}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="setup-km">{sst(language, "cf_kh")}</label>
            <input
              autoComplete="off"
              id="setup-km"
              lang="km"
              maxLength={100}
              onChange={(event) => {
                setKhmer(event.currentTarget.value);
              }}
              value={khmer}
            />
          </div>
        </div>
      )}
      {error !== null && (
        <p className="ui-error" id="setup-error" role="alert">
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
      {note !== undefined && (
        <p className="ui-small ui-muted">{sst(language, note)}</p>
      )}
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
    </Dialog>
  );
}

export function UnitSetupTab({
  language,
  propertyId,
  active,
  api,
  cleaning = cleaningSettingsApi,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: SetupApi;
  /** The move-out cleaning rates; the real server when not given. */
  cleaning?: CleaningSettingsApi;
}) {
  const [lists, setLists] = useState<UnitSetupLists | null>(null);
  // The Unit Types with no cleaning rate; null when the rates could not be read.
  const [noRate, setNoRate] = useState<Set<string> | null>(null);
  const [units, setUnits] = useState<UnitResource[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [removing, setRemoving] = useState<UnitSetupItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void Promise.all([
      api.setupLists(propertyId),
      allPages(async (cursor) =>
        api.list(propertyId, cursor === undefined ? {} : { cursor }),
      ).catch(() => null),
      // Parking Step 5: no cleaning charge on Parking, so no missing-rate chip.
      CLEANING_CHARGE
        ? cleaning
            .read(propertyId)
            .then(
              (found) =>
                new Set(
                  found.unit_types
                    .filter((type) => type.cleaning_rate_id === null)
                    .map((type) => type.code),
                ),
            )
            .catch(() => null)
        : Promise.resolve(null),
    ])
      .then(([loaded, read, missing]) => {
        if (operation !== sequence.current) return;
        setLists(loaded);
        setUnits(read);
        setNoRate(missing);
      })
      .catch(() => {
        if (operation !== sequence.current) return;
        setLists(null);
        setFailed(true);
      });
  }, [api, cleaning, propertyId]);

  // Another Property never shows the lists of the one before, and a change still on its way
  // for the one before reports nothing here.
  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    setFailed(false);
    setProblem(null);
    setLists(null);
    setUnits(null);
    setNoRate(null);
    setEditing(null);
    setRemoving(null);
    setToast(null);
  }, [propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  function run(work: () => Promise<unknown>, done: string) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    work()
      .then(() => {
        if (shownProperty.current !== asked) return;
        setEditing(null);
        setRemoving(null);
        setToast({ ok: true, text: done });
        load();
      })
      .catch((error: unknown) => {
        if (shownProperty.current !== asked) return;
        if (error instanceof UnitConflictError) {
          // The open form holds the old version, so it closes; the lists are read again.
          setEditing(null);
          setRemoving(null);
          setToast({ ok: false, text: sst(language, "changed") });
          load();
        } else if (error instanceof UnitInvalidError) {
          setProblem(sst(language, "refused"));
        } else {
          setProblem(sst(language, "unknown"));
          load();
        }
      })
      .finally(() => {
        setBusy(false);
      });
  }

  if (failed) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{sst(language, "units_failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {sst(language, "retry")}
        </button>
      </div>
    );
  }
  if (lists === null) {
    return (
      <p className="ui-muted" role="status">
        {sst(language, "units_loading")}
      </p>
    );
  }

  const manage = lists.can_manage;
  const card = (kind: UnitSetupListKind) => {
    const note = noteFor(kind);
    return (
      <section aria-labelledby={`setup-${kind}`} className="ui-card" key={kind}>
        <header className="ui-chead">
          <h2 id={`setup-${kind}`}>{sst(language, `cf_${kind}`)}</h2>
          {manage && (
            <button
              aria-label={`${sst(language, "cf_add")}: ${sst(language, `cf_one_${kind}`)}`}
              className="ui-btn"
              onClick={() => {
                setProblem(null);
                setToast(null);
                setEditing({ kind, item: null });
              }}
              type="button"
            >
              <Icon name="plus" small />
              {sst(language, "cf_add")}
            </button>
          )}
        </header>
        <ul className="ui-apps">
          {lists.lists[kind].map((item) => {
            const count = unitCount(units, item);
            const used = item.in_use || (count ?? 0) > 0;
            const name = itemName(language, item);
            return (
              <li key={item.item_id}>
                <span>
                  {name}
                  <small className="ui-num">
                    {count === null
                      ? used
                        ? sst(language, "in_use")
                        : sst(language, "set_none_units")
                      : count === 0
                        ? sst(language, "set_none_units")
                        : count === 1
                          ? sst(language, "set_n_unit1")
                          : sst(language, "set_n_units", count)}
                  </small>
                  {kind === "UNIT_TYPE" && noRate?.has(item.code) === true && (
                    <Chip icon="alert" tone="warn">
                      {sst(language, "cl_chip")}
                    </Chip>
                  )}
                </span>
                {manage && (
                  <span className="ui-actions">
                    {kind !== "FLOOR" && (
                      <button
                        aria-label={`${sst(language, "cf_edit")}: ${name}`}
                        className="ui-btn link"
                        onClick={() => {
                          setProblem(null);
                          setToast(null);
                          setEditing({ kind, item });
                        }}
                        type="button"
                      >
                        {sst(language, "cf_edit")}
                      </button>
                    )}
                    {!used && (
                      <button
                        aria-label={`${sst(language, "set_remove")}: ${name}`}
                        className="ui-btn link"
                        onClick={() => {
                          setProblem(null);
                          setToast(null);
                          setRemoving(item);
                        }}
                        type="button"
                      >
                        {sst(language, "set_remove")}
                      </button>
                    )}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
        {note !== undefined && (
          <p className="ui-small ui-muted">{sst(language, note)}</p>
        )}
      </section>
    );
  };

  return (
    <>
      {/* Mounted before it has words, so screen readers announce them. */}
      <div aria-live="polite" role="status">
        {toast !== null && (
          <div className={toast.ok ? "ui-notice ok" : "ui-notice warn"}>
            <Icon name={toast.ok ? "check" : "alert"} />
            <p>{toast.text}</p>
          </div>
        )}
      </div>
      <p className="ui-small ui-muted">{sst(language, "cf_note")}</p>
      {!manage && (
        <div className="ui-notice info" role="note">
          <Icon name="lock" />
          <p>{sst(language, "read_only")}</p>
        </div>
      )}
      <div className="ui-setup">
        {unitSetupListKinds.filter(shownOnParking).map(card)}
      </div>

      {editing !== null && (
        <ItemDialog
          busy={busy}
          editing={editing}
          language={language}
          lists={lists}
          onClose={() => {
            if (!busy) setEditing(null);
          }}
          onSave={(source) => {
            const { item } = editing;
            run(
              () =>
                item === null
                  ? api.createSetupItem(propertyId, {
                      list_kind: editing.kind,
                      ...source,
                    })
                  : api.updateSetupItem(item, {
                      name_en: source.name_en,
                      name_km: source.name_km,
                    }),
              sst(language, "cf_saved"),
            );
          }}
          problem={problem}
        />
      )}
      {removing !== null && (
        <Dialog
          actions={
            <button
              className="ui-btn danger"
              disabled={busy}
              onClick={() => {
                run(
                  () => api.removeSetupItem(removing),
                  sst(language, "set_removed", itemName(language, removing)),
                );
              }}
              type="button"
            >
              {sst(language, "set_remove")}
            </button>
          }
          busy={busy}
          closeLabel={sst(language, "cancel")}
          onClose={() => {
            if (!busy) setRemoving(null);
          }}
          title={`${sst(language, "set_remove")} · ${itemName(language, removing)}`}
        >
          <p>{sst(language, "set_remove_q", itemName(language, removing))}</p>
          {problem !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{problem}</p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
