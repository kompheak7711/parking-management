// V1.1 part 3 (DL-120): Settings › Users and sign-in › Roles. The roles with their users, their
// permissions and whether two-step sign-in is needed; Add role and Edit (English and Khmer name,
// the permissions by group, Turn off); and the tick boxes that give a person their roles. The
// Owner role keeps its name and is never turned off, "Users and roles" stays the Owner's own, and
// a role with users cannot be turned off. Saving runs through the Users tab, which asks for the
// password and code again when the server says so.

import { type FormEvent, type ReactNode, useState } from "react";

import type { UserAccount } from "../adminClient";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  heldState,
  type Permission,
  permissionGroups,
  needsTwoStep,
  type Role,
  type RoleChange,
  RULES_CAPABILITY,
  type RolesAndPermissions,
  roleName,
  USERS_CAPABILITY,
} from "./rolesClient";
import { sst } from "../settings/text";
import { at } from "./text";

/** The permissions shown on the screen (all but the one every role has). */
function shown(permissions: readonly Permission[]): Permission[] {
  return permissions.filter((item) => item.group_code !== null);
}

/** How many shown permissions the role has whole. */
function wholeCount(role: Role, permissions: readonly Permission[]): number {
  const held = new Set(role.capability_ids);
  if (role.owner_role) held.add(USERS_CAPABILITY);
  return shown(permissions).filter((item) => heldState(item, held) === "all")
    .length;
}

export function RolesSection({
  language,
  data,
  onAdd,
  onEdit,
}: {
  language: Language;
  data: RolesAndPermissions;
  onAdd: () => void;
  onEdit: (role: Role) => void;
}) {
  const total = shown(data.permissions).length;
  return (
    <section aria-labelledby="settings-roles" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="settings-roles">{at(language, "ro_title")}</h2>
        <span className="ui-actions">
          <button className="ui-btn primary" onClick={onAdd} type="button">
            <Icon name="plus" small />
            {at(language, "ro_add")}
          </button>
        </span>
      </header>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{at(language, "ro_role")}</th>
              <th scope="col">{at(language, "ro_users")}</th>
              <th scope="col">{at(language, "ro_perms")}</th>
              <th scope="col">{at(language, "ro_two_step")}</th>
              <th scope="col">
                <span className="ui-sr">{at(language, "ro_edit")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.roles.map((role) => (
              <tr key={role.role_bundle_id}>
                <td>
                  <b>{roleName(role, language)}</b>
                  {role.turned_off && (
                    <>
                      {" "}
                      <Chip tone="neutral">{at(language, "ro_off")}</Chip>
                    </>
                  )}
                </td>
                <td className="ui-num">{role.holders}</td>
                <td>
                  {at(
                    language,
                    "ro_of",
                    wholeCount(role, data.permissions),
                    total,
                  )}
                </td>
                <td>
                  {needsTwoStep(role) ? (
                    <Chip icon="lock" tone="info">
                      {at(language, "ro_required")}
                    </Chip>
                  ) : (
                    <span className="ui-muted">
                      {at(language, "ro_optional")}
                    </span>
                  )}
                </td>
                <td>
                  <button
                    aria-label={`${at(language, "ro_edit")}: ${roleName(role, language)}`}
                    className="ui-btn"
                    onClick={() => {
                      onEdit(role);
                    }}
                    type="button"
                  >
                    {at(language, "ro_edit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="ui-tfoot">
        <span>{at(language, "ro_note")}</span>
      </div>
    </section>
  );
}

function PermissionBox({
  language,
  item,
  held,
  locked,
  onChange,
}: {
  language: Language;
  item: Permission;
  held: ReadonlySet<string>;
  locked: boolean;
  onChange: (on: boolean) => void;
}) {
  const state = heldState(item, held);
  const label = language === "km" ? item.name_kh : item.name_en;
  return (
    <label className={locked ? "ui-chk off" : "ui-chk"}>
      <input
        aria-checked={state === "some" ? "mixed" : state === "all"}
        checked={state === "all"}
        disabled={locked}
        onChange={(event) => {
          onChange(event.currentTarget.checked);
        }}
        ref={(box) => {
          if (box !== null) box.indeterminate = state === "some";
        }}
        type="checkbox"
      />
      <span>
        {label}
        {state === "some" && (
          <small className="ui-muted"> · {at(language, "ro_some")}</small>
        )}
        {item.capability_ids.includes(RULES_CAPABILITY) && (
          <small className="ui-muted ui-sub2">
            {at(language, "ro_rules_h")}
          </small>
        )}
        {item.capability_ids.includes(USERS_CAPABILITY) && (
          <small className="ui-muted ui-sub2">
            {at(language, "ro_users_lock")}
          </small>
        )}
      </span>
    </label>
  );
}

export function RoleEditorDialog({
  language,
  data,
  role,
  busy,
  notice,
  onClose,
  onSave,
}: {
  language: Language;
  data: RolesAndPermissions;
  /** null for a new role. */
  role: Role | null;
  busy: boolean;
  notice: ReactNode;
  onClose: () => void;
  onSave: (change: RoleChange) => void;
}) {
  const owner = role?.owner_role ?? false;
  const [name, setName] = useState(role?.name ?? "");
  const [nameKh, setNameKh] = useState(role?.name_kh ?? "");
  const [held, setHeld] = useState(
    () => new Set(role === null ? [] : role.capability_ids),
  );
  const [turnedOff, setTurnedOff] = useState(role?.turned_off ?? false);
  const [error, setError] = useState<string | null>(null);
  const hasUsers = (role?.holders ?? 0) > 0;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const english = name.trim();
    if (english === "") {
      setError(at(language, "ro_e_name"));
      document.getElementById("ro-name")?.focus();
      return;
    }
    const taken = data.roles.some(
      (other) =>
        other.role_bundle_id !== role?.role_bundle_id &&
        other.name.trim().toLowerCase() === english.toLowerCase(),
    );
    if (taken) {
      setError(at(language, "ro_e_taken"));
      document.getElementById("ro-name")?.focus();
      return;
    }
    const basic = new Set(
      data.permissions
        .filter((item) => item.group_code === null)
        .flatMap((item) => item.capability_ids),
    );
    onSave({
      name: english,
      name_kh: nameKh.trim() === "" ? null : nameKh.trim(),
      // Every role has the basic rights and the server adds them; Users and roles is the
      // Owner's own and never part of a role.
      capability_ids: [...held]
        .filter((id) => id !== USERS_CAPABILITY && !basic.has(id))
        .sort(),
      turned_off: turnedOff,
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
        role === null
          ? at(language, "ro_new_t")
          : at(language, "ro_edit_t", roleName(role, language))
      }
      wide
    >
      <div className="ui-field">
        <label htmlFor="ro-name">
          {at(language, "ro_name")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={owner ? "ro-owner-h" : undefined}
          aria-invalid={error !== null}
          autoComplete="off"
          disabled={owner}
          id="ro-name"
          maxLength={80}
          onChange={(event) => {
            setName(event.currentTarget.value);
            setError(null);
          }}
          value={name}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="ro-name-kh">{at(language, "ro_name_kh")}</label>
        <input
          autoComplete="off"
          disabled={owner}
          id="ro-name-kh"
          lang="km"
          maxLength={80}
          onChange={(event) => {
            setNameKh(event.currentTarget.value);
          }}
          value={nameKh}
        />
        {owner && (
          <p className="help" id="ro-owner-h">
            {at(language, "ro_owner_name")}
          </p>
        )}
      </div>
      {error !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
      {permissionGroups(data.permissions).map((group) => (
        <fieldset className="ui-radios" key={group.code}>
          <legend>{language === "km" ? group.kh : group.en}</legend>
          {group.items.map((item) => {
            const users = item.capability_ids.includes(USERS_CAPABILITY);
            // Users and roles: ticked and locked for the Owner role, locked off for the others.
            const view =
              users && owner
                ? new Set([...held, ...item.capability_ids])
                : users
                  ? new Set<string>()
                  : held;
            return (
              <PermissionBox
                held={view}
                item={item}
                key={item.permission_code}
                language={language}
                locked={users}
                onChange={(on) => {
                  setHeld((before) => {
                    const next = new Set(before);
                    for (const id of item.capability_ids) {
                      if (on) next.add(id);
                      else next.delete(id);
                    }
                    return next;
                  });
                }}
              />
            );
          })}
        </fieldset>
      ))}
      {role !== null && !owner && (
        <div className="ui-field">
          <label className={hasUsers && !turnedOff ? "ui-chk off" : "ui-chk"}>
            <input
              aria-describedby="ro-off-h"
              checked={turnedOff}
              disabled={hasUsers && !turnedOff}
              onChange={(event) => {
                setTurnedOff(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            <span>{at(language, "ro_turn_off")}</span>
          </label>
          <p className="help" id="ro-off-h">
            {at(
              language,
              hasUsers && !turnedOff ? "ro_turn_off_users" : "ro_turn_off_h",
            )}
          </p>
        </div>
      )}
      {notice}
    </Dialog>
  );
}

export interface RolesChange {
  give: string[];
  take: string[];
  reason: string;
}

export function UserRolesDialog({
  language,
  user,
  data,
  busy,
  notice,
  onClose,
  onSave,
}: {
  language: Language;
  user: UserAccount;
  data: RolesAndPermissions;
  busy: boolean;
  notice: ReactNode;
  onClose: () => void;
  onSave: (change: RolesChange) => void;
}) {
  const isOwner = user.account_class === "owner";
  const had = new Set(
    data.assignments
      .filter((item) => item.user_id === user.user_id)
      .map((item) => item.role_bundle_id),
  );
  const [ticked, setTicked] = useState(() => new Set(had));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The Owner role is only for the Owner; a turned-off role is listed only to take it away.
  const listed = data.roles.filter(
    (role) =>
      (role.owner_role ? isOwner : true) &&
      (!role.turned_off || had.has(role.role_bundle_id)),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const give = listed
      .map((role) => role.role_bundle_id)
      .filter((id) => ticked.has(id) && !had.has(id));
    const take = listed
      .map((role) => role.role_bundle_id)
      .filter((id) => !ticked.has(id) && had.has(id));
    if (give.length === 0 && take.length === 0) {
      setError(sst(language, "ua_e_none"));
      return;
    }
    if (take.length > 0 && reason.trim() === "") {
      setError(sst(language, "ua_e_reason"));
      document.getElementById("urr-reason")?.focus();
      return;
    }
    onSave({ give, take, reason: reason.trim() });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={at(language, "ur_roles_t", user.display_name)}
    >
      <fieldset className="ui-radios">
        <legend>{at(language, "ur_roles_legend")}</legend>
        {listed.map((role) => {
          const locked = role.owner_role && isOwner;
          const off = role.turned_off && !ticked.has(role.role_bundle_id);
          return (
            <label
              className={locked || off ? "ui-chk off" : "ui-chk"}
              key={role.role_bundle_id}
            >
              <input
                checked={locked || ticked.has(role.role_bundle_id)}
                disabled={locked || off}
                onChange={(event) => {
                  const on = event.currentTarget.checked;
                  setError(null);
                  setTicked((before) => {
                    const next = new Set(before);
                    if (on) next.add(role.role_bundle_id);
                    else next.delete(role.role_bundle_id);
                    return next;
                  });
                }}
                type="checkbox"
              />
              <span>
                {roleName(role, language)}
                {role.turned_off && (
                  <small className="ui-muted">
                    {" "}
                    · {at(language, "ro_off")}
                  </small>
                )}
                {needsTwoStep(role) && (
                  <small className="ui-muted">
                    {" "}
                    · {at(language, "ro_two_step")}
                  </small>
                )}
              </span>
            </label>
          );
        })}
      </fieldset>
      {isOwner && (
        <p className="ui-small ui-muted">{at(language, "ur_owner_keeps")}</p>
      )}
      <div className="ui-field">
        <label htmlFor="urr-reason">{sst(language, "ur_reason")}</label>
        <input
          aria-describedby="urr-reason-h"
          autoComplete="off"
          id="urr-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
            setError(null);
          }}
          value={reason}
        />
        <p className="help" id="urr-reason-h">
          {at(language, "ur_roles_reason_h")}
        </p>
      </div>
      {error !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
      {notice}
    </Dialog>
  );
}

/** The roles a person has, by name, for the Users table. */
export function userRoleNames(
  language: Language,
  user: UserAccount,
  data: RolesAndPermissions,
): string {
  const names = data.assignments
    .filter((item) => item.user_id === user.user_id)
    .map((item) =>
      data.roles.find((role) => role.role_bundle_id === item.role_bundle_id),
    )
    .filter((role): role is Role => role !== undefined)
    .map((role) => roleName(role, language));
  return names.length === 0 ? at(language, "ur_roles_none") : names.join(", ");
}
