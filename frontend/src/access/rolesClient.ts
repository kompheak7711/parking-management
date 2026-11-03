// V1.1 part 3 (DL-120): Users and access > Roles. The permissions list, the roles and who has
// which role come in one read; a role is saved whole (English and Khmer name, rights, turned
// off) at its version. A person's roles change one at a time (give and take away).

import {
  AdministrationError,
  isObject,
  mutationHeaders,
  oneData,
  request,
} from "../adminClient";

export interface Permission {
  permission_code: string;
  /** null only for BASIC, which every role has and the screen does not show. */
  group_code: string | null;
  group_name_en: string | null;
  group_name_kh: string | null;
  name_en: string;
  name_kh: string;
  capability_ids: string[];
}

export interface Role {
  role_bundle_id: string;
  name: string;
  name_kh: string | null;
  version: number;
  turned_off: boolean;
  owner_role: boolean;
  capability_ids: string[];
  holders: number;
}

export interface RoleAssignment {
  user_id: string;
  role_bundle_id: string;
}

export interface RolesAndPermissions {
  permissions: Permission[];
  roles: Role[];
  assignments: RoleAssignment[];
}

export interface RoleChange {
  name: string;
  name_kh: string | null;
  capability_ids: string[];
  turned_off: boolean;
}

export interface RolesApi {
  load: (propertyId: string) => Promise<RolesAndPermissions>;
  createRole: (propertyId: string, role: RoleChange) => Promise<Role>;
  saveRole: (role: Role, change: RoleChange) => Promise<Role>;
  giveRole: (userId: string, roleBundleId: string) => Promise<void>;
  takeRole: (
    userId: string,
    roleBundleId: string,
    reason: string,
  ) => Promise<void>;
}

/** The right that the role flag "Change business rules" gives. */
export const RULES_CAPABILITY = "settings.manage";
/** Users and roles: the Owner's own, shown locked. */
export const USERS_CAPABILITY = "identity.manage_access";

function strings(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string"))
    throw new AdministrationError();
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new AdministrationError();
  return value;
}

function textOrNull(value: unknown): string | null {
  return value === null ? null : text(value);
}

function permission(value: unknown): Permission {
  if (!isObject(value)) throw new AdministrationError();
  return {
    permission_code: text(value.permission_code),
    group_code: textOrNull(value.group_code),
    group_name_en: textOrNull(value.group_name_en),
    group_name_kh: textOrNull(value.group_name_kh),
    name_en: text(value.name_en),
    name_kh: text(value.name_kh),
    capability_ids: strings(value.capability_ids),
  };
}

function role(value: unknown): Role {
  if (
    !isObject(value) ||
    typeof value.version !== "number" ||
    typeof value.turned_off !== "boolean" ||
    typeof value.owner_role !== "boolean" ||
    typeof value.holders !== "number"
  ) {
    throw new AdministrationError();
  }
  return {
    role_bundle_id: text(value.role_bundle_id),
    name: text(value.name),
    name_kh: textOrNull(value.name_kh),
    version: value.version,
    turned_off: value.turned_off,
    owner_role: value.owner_role,
    capability_ids: strings(value.capability_ids),
    holders: value.holders,
  };
}

function assignment(value: unknown): RoleAssignment {
  if (!isObject(value)) throw new AdministrationError();
  return {
    user_id: text(value.user_id),
    role_bundle_id: text(value.role_bundle_id),
  };
}

function list<T>(value: unknown, item: (one: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new AdministrationError();
  return value.map(item);
}

export const rolesApi: RolesApi = {
  async load(propertyId) {
    const data = oneData(
      await request(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/roles`,
        { method: "GET" },
      ),
    );
    return {
      permissions: list(data.permissions, permission),
      roles: list(data.roles, role),
      assignments: list(data.assignments, assignment),
    };
  },

  async createRole(propertyId, change) {
    const payload = await request(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/roles`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({
          name: change.name,
          name_kh: change.name_kh,
          capability_ids: change.capability_ids,
        }),
      },
    );
    return role(oneData(payload));
  },

  async saveRole(current, change) {
    const payload = await request(
      `/api/v1/roles/${encodeURIComponent(current.role_bundle_id)}`,
      {
        method: "PUT",
        headers: mutationHeaders({
          "If-Match": `"${String(current.version)}"`,
        }),
        body: JSON.stringify(change),
      },
    );
    return role(oneData(payload));
  },

  async giveRole(userId, roleBundleId) {
    await request(
      `/api/v1/users/${encodeURIComponent(userId)}/role-assignments`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({ role_bundle_id: roleBundleId }),
      },
    );
  },

  async takeRole(userId, roleBundleId, reason) {
    await request(
      `/api/v1/users/${encodeURIComponent(userId)}/role-assignments/remove`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({ role_bundle_id: roleBundleId, reason }),
      },
    );
  },
};

/** The permissions shown in the Roles editor, by group in their order. */
export function permissionGroups(
  permissions: readonly Permission[],
): { code: string; en: string; kh: string; items: Permission[] }[] {
  const groups: {
    code: string;
    en: string;
    kh: string;
    items: Permission[];
  }[] = [];
  for (const item of permissions) {
    if (item.group_code === null) continue;
    let group = groups.find((one) => one.code === item.group_code);
    if (group === undefined) {
      group = {
        code: item.group_code,
        en: item.group_name_en ?? item.group_code,
        kh: item.group_name_kh ?? item.group_code,
        items: [],
      };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

/** "all", "some" or "none" of a permission's rights in a set of rights. */
export function heldState(
  item: Permission,
  held: ReadonlySet<string>,
): "all" | "some" | "none" {
  const count = item.capability_ids.filter((id) => held.has(id)).length;
  if (count === 0) return "none";
  return count === item.capability_ids.length ? "all" : "some";
}

/** A role that can change business rules or users must use two-step sign-in. */
export function needsTwoStep(item: Role): boolean {
  return item.owner_role || item.capability_ids.includes(RULES_CAPABILITY);
}

/** The role's name in the chosen language (the English one when there is no Khmer). */
export function roleName(item: Role, language: "en" | "km"): string {
  return language === "km" && item.name_kh !== null ? item.name_kh : item.name;
}
