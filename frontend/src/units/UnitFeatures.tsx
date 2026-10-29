// V1.1 part 1 (owner 2026-10-29, DL-115 (I); mock-up round 13): the Unit page lists the Unit's
// features with how many of each ("Bedroom ×2"). Edit features changes the counts (1 to 9),
// removes a feature with × and adds one from the Unit features list in Settings → Unit setup.

import { type FormEvent, useState } from "react";

import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type UnitApi,
  UnitConflictError,
  type UnitFeatureCount,
  UnitInvalidError,
  type UnitResource,
  type UnitSetupItem,
  type UnitSetupLists,
} from "../unitClient";
import { ut } from "./text";

const MAX_COUNT = 9;
const MAX_FEATURES = 50;

function label(item: UnitSetupItem | undefined, language: Language): string {
  if (item === undefined) return "";
  return language === "km" && item.name_km !== null
    ? item.name_km
    : item.name_en;
}

/** The Unit's features in the order of the Settings list. */
function ordered(
  features: UnitFeatureCount[],
  lists: UnitSetupLists,
): UnitFeatureCount[] {
  const place = new Map(
    lists.lists.UNIT_FEATURE.map((item, index) => [item.item_id, index]),
  );
  return [...features].sort(
    (left, right) =>
      (place.get(left.item_id) ?? Number.MAX_SAFE_INTEGER) -
      (place.get(right.item_id) ?? Number.MAX_SAFE_INTEGER),
  );
}

export function UnitFeaturesPanel({
  api,
  language,
  unit,
  lists,
  canManage,
  onSaved,
  onConflict,
}: {
  api: Pick<UnitApi, "setFeatures">;
  language: Language;
  unit: UnitResource;
  lists: UnitSetupLists | null;
  canManage: boolean;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const features = unit.features ?? [];
  const byId = new Map(
    (lists?.lists.UNIT_FEATURE ?? []).map((item) => [item.item_id, item]),
  );
  return (
    <div className="ui-features">
      <h3 id="unit-features">{ut(language, "uf_title")}</h3>
      {features.length === 0 ? (
        <p className="ui-small ui-muted">{ut(language, "uf_none")}</p>
      ) : (
        <ul aria-labelledby="unit-features" className="ui-feature-chips">
          {(lists === null ? features : ordered(features, lists)).map(
            (feature) => (
              <li key={feature.item_id}>
                {label(byId.get(feature.item_id), language) ||
                  ut(language, "uf_unknown")}{" "}
                <b className="ui-num">×{feature.count}</b>
              </li>
            ),
          )}
        </ul>
      )}
      {canManage && lists !== null && (
        <button
          className="ui-btn"
          onClick={() => {
            setEditing(true);
          }}
          type="button"
        >
          <Icon name="list" small />
          {ut(language, "uf_edit")}
        </button>
      )}
      {editing && lists !== null && (
        <EditFeaturesDialog
          api={api}
          language={language}
          lists={lists}
          onClose={() => {
            setEditing(false);
          }}
          onConflict={() => {
            setEditing(false);
            onConflict();
          }}
          onSaved={(saved) => {
            setEditing(false);
            onSaved(saved);
          }}
          unit={unit}
        />
      )}
    </div>
  );
}

function EditFeaturesDialog({
  api,
  language,
  lists,
  unit,
  onClose,
  onSaved,
  onConflict,
}: {
  api: Pick<UnitApi, "setFeatures">;
  language: Language;
  lists: UnitSetupLists;
  unit: UnitResource;
  onClose: () => void;
  onSaved: (unit: UnitResource) => void;
  onConflict: () => void;
}) {
  const [rows, setRows] = useState<UnitFeatureCount[]>(
    ordered(unit.features ?? [], lists),
  );
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const items = new Map(
    lists.lists.UNIT_FEATURE.map((item) => [item.item_id, item]),
  );
  const types = new Map(
    lists.lists.FEATURE_TYPE.map((item) => [item.item_id, item]),
  );
  const offered = lists.lists.UNIT_FEATURE.filter(
    (item) =>
      !item.removed && !rows.some((row) => row.item_id === item.item_id),
  );

  function change(itemId: string, count: number) {
    setRows((current) =>
      current.map((row) => (row.item_id === itemId ? { ...row, count } : row)),
    );
  }

  function add() {
    if (adding === "" || rows.length >= MAX_FEATURES) return;
    setRows((current) => [...current, { item_id: adding, count: 1 }]);
    setAdding("");
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setProblem(null);
    void api
      .setFeatures(unit, rows)
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
      submitLabel={ut(language, "uf_save")}
      title={`${ut(language, "uf_title")} · ${unit.unit_number}`}
    >
      {rows.length === 0 ? (
        <p className="ui-small ui-muted">{ut(language, "uf_none")}</p>
      ) : (
        <ul className="ui-feature-edit">
          {rows.map((row) => {
            const item = items.get(row.item_id);
            const name = label(item, language) || ut(language, "uf_unknown");
            const type = types.get(item?.feature_type_item_id ?? "");
            return (
              <li key={row.item_id}>
                <span className="ui-feature-name">
                  {name}
                  {type !== undefined && (
                    <Chip tone="neutral">{label(type, language)}</Chip>
                  )}
                </span>
                <span className="ui-stepper">
                  <button
                    aria-label={ut(language, "uf_less", name)}
                    className="ui-btn"
                    disabled={busy || row.count <= 1}
                    onClick={() => {
                      change(row.item_id, row.count - 1);
                    }}
                    type="button"
                  >
                    −
                  </button>
                  <output
                    aria-label={ut(language, "uf_count", name)}
                    className="ui-num"
                  >
                    {row.count}
                  </output>
                  <button
                    aria-label={ut(language, "uf_more", name)}
                    className="ui-btn"
                    disabled={busy || row.count >= MAX_COUNT}
                    onClick={() => {
                      change(row.item_id, row.count + 1);
                    }}
                    type="button"
                  >
                    +
                  </button>
                </span>
                <button
                  aria-label={ut(language, "uf_remove", name)}
                  className="ui-btn link"
                  disabled={busy}
                  onClick={() => {
                    setRows((current) =>
                      current.filter((other) => other.item_id !== row.item_id),
                    );
                  }}
                  type="button"
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="ui-feature-add">
        <label className="ui-sr" htmlFor="unit-feature-add">
          {ut(language, "uf_add_label")}
        </label>
        <select
          disabled={busy || offered.length === 0}
          id="unit-feature-add"
          onChange={(event) => {
            setAdding(event.currentTarget.value);
          }}
          value={adding}
        >
          <option value="">
            {ut(language, offered.length === 0 ? "uf_add_none" : "uf_add_pick")}
          </option>
          {offered.map((item) => (
            <option key={item.item_id} value={item.item_id}>
              {label(item, language)}
            </option>
          ))}
        </select>
        <button
          className="ui-btn"
          disabled={busy || adding === ""}
          onClick={add}
          type="button"
        >
          {ut(language, "uf_add")}
        </button>
      </div>
      <p className="ui-small ui-muted">{ut(language, "uf_note")}</p>
      {problem !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </Dialog>
  );
}
