// V1.1 part 3 (DL-120): a small permissions list and the three first roles, for the tests.

import { vi } from "vitest";

import type {
  Permission,
  Role,
  RoleAssignment,
  RolesAndPermissions,
} from "../access/rolesClient";

export const PERMISSIONS: Permission[] = [
  {
    permission_code: "BASIC",
    group_code: null,
    group_name_en: null,
    group_name_kh: null,
    name_en: "Sign in and see the Property, its Units and its setup",
    name_kh: "ចូលប្រើ និងមើលអចលនទ្រព្យ បន្ទប់ និងការកំណត់",
    capability_ids: ["property.read", "units.read"],
  },
  {
    permission_code: "PAY_RECV",
    group_code: "OPERATIONS",
    group_name_en: "Operations",
    group_name_kh: "ប្រតិបត្តិការ",
    name_en: "Receive payment",
    name_kh: "ទទួលប្រាក់",
    capability_ids: ["payments.allocate", "payments.record"],
  },
  {
    permission_code: "INV_OPEN",
    group_code: "OPERATIONS",
    group_name_en: "Operations",
    group_name_kh: "ប្រតិបត្តិការ",
    name_en: "Open Invoices",
    name_kh: "បើកវិក្កយបត្រ",
    capability_ids: ["invoices.read"],
  },
  {
    permission_code: "APPROVE",
    group_code: "MONEY",
    group_name_en: "Money approval",
    group_name_kh: "ការអនុម័តប្រាក់",
    name_en: "Approve money changes",
    name_kh: "អនុម័តការប្តូរប្រាក់",
    capability_ids: ["financial.approve", "invoices.void"],
  },
  {
    permission_code: "RULES",
    group_code: "ADMIN",
    group_name_en: "Administration",
    group_name_kh: "រដ្ឋបាល",
    name_en: "Change business rules",
    name_kh: "ប្ដូរច្បាប់អាជីវកម្ម",
    capability_ids: ["settings.manage"],
  },
  {
    permission_code: "USERS",
    group_code: "ADMIN",
    group_name_en: "Administration",
    group_name_kh: "រដ្ឋបាល",
    name_en: "Users and roles",
    name_kh: "អ្នកប្រើ និងតួនាទី",
    capability_ids: ["identity.manage_access"],
  },
];

const BASIC = ["property.read", "units.read"];

export const OWNER_ROLE: Role = {
  role_bundle_id: "role-owner",
  name: "Owner",
  name_kh: "ម្ចាស់",
  version: 2,
  turned_off: false,
  owner_role: true,
  capability_ids: [
    ...BASIC,
    "financial.approve",
    "invoices.read",
    "invoices.void",
    "payments.allocate",
    "payments.record",
    "settings.manage",
  ],
  holders: 1,
};

export const MANAGER_ROLE: Role = {
  role_bundle_id: "role-manager",
  name: "Manager",
  name_kh: "អ្នកគ្រប់គ្រង",
  version: 2,
  turned_off: false,
  owner_role: false,
  // Part of Approve money changes only.
  capability_ids: [
    ...BASIC,
    "financial.approve",
    "invoices.read",
    "payments.allocate",
    "payments.record",
  ],
  holders: 1,
};

export const STAFF_ROLE: Role = {
  role_bundle_id: "role-staff",
  name: "Staff",
  name_kh: "បុគ្គលិក",
  version: 2,
  turned_off: false,
  owner_role: false,
  capability_ids: [...BASIC, "payments.allocate", "payments.record"],
  holders: 1,
};

export const OLD_ROLE: Role = {
  role_bundle_id: "role-old",
  name: "Night desk",
  name_kh: null,
  version: 1,
  turned_off: true,
  owner_role: false,
  capability_ids: [...BASIC],
  holders: 0,
};

export const ASSIGNMENTS: RoleAssignment[] = [
  { user_id: "owner-1", role_bundle_id: "role-owner" },
  { user_id: "user-Dara", role_bundle_id: "role-manager" },
  { user_id: "user-Vanna", role_bundle_id: "role-staff" },
];

export function rolesData(
  extra: Partial<RolesAndPermissions> = {},
): RolesAndPermissions {
  return {
    permissions: PERMISSIONS,
    roles: [OWNER_ROLE, MANAGER_ROLE, STAFF_ROLE, OLD_ROLE],
    assignments: ASSIGNMENTS,
    ...extra,
  };
}

export function rolesApiOf(
  data: () => Promise<RolesAndPermissions> = () => Promise.resolve(rolesData()),
) {
  return {
    load: vi.fn(data),
    createRole: vi.fn((_propertyId: string, change: { name: string }) =>
      Promise.resolve({
        ...STAFF_ROLE,
        role_bundle_id: "role-new",
        name: change.name,
        name_kh: null,
        version: 1,
        holders: 0,
      }),
    ),
    saveRole: vi.fn((role: Role, change: { name: string }) =>
      Promise.resolve({
        ...role,
        name: change.name,
        version: role.version + 1,
      }),
    ),
    giveRole: vi.fn(() => Promise.resolve()),
    takeRole: vi.fn(() => Promise.resolve()),
  };
}
