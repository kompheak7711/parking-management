import { defaultEnforcementServices } from "./leaseEnforcementUi";
import type { EnforcementClient } from "./leaseEnforcementClient";
import {
  ids as enforcementIds,
  readData as enforcementReadData,
} from "./test/leaseEnforcementFixtures";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  App,
  clearCustomerReconciliation,
  reserveCustomerReconciliation,
} from "./App";
import type { CustomerReconciliationRequirement } from "./CustomerManagement";
import { defaultFinancialUiServices } from "./FinancialManagement";
import {
  FINANCIAL_CAPABILITIES,
  createFinancialReferenceClient,
} from "./financialReferenceClient";
import { AccessAdministrationApi, UserAccount } from "./adminClient";
import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationApi,
  PASSWORD_RULE_MESSAGE,
  PasswordRuleError,
  SessionData,
  SessionExpiredError,
} from "./authClient";
import {
  PropertyBusinessConfiguration,
  PropertyConfigurationApi,
  PropertyConfigurationUnavailableError,
} from "./propertyClient";
import {
  CustomerApi,
  CustomerDetail,
  CustomerRequestError,
} from "./customerClient";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    clear: () => {
      values.clear();
    },
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

let indexedDatabaseReadGate: Promise<void> | null = null;
let indexedDatabaseWriteAborts = false;
let indexedDatabaseOpenCount = 0;
let indexedDatabaseVersionChange: (() => void) | null = null;

function memoryIndexedDatabase(): IDBFactory {
  const values = new Map<IDBValidKey, unknown>();
  let initialized = false;
  function request<T>(
    result: T,
    gate: Promise<void> | null = null,
  ): IDBRequest<T> {
    const pending = { result, error: null } as unknown as IDBRequest<T>;
    void (gate ?? Promise.resolve()).then(() => {
      queueMicrotask(() => {
        pending.onsuccess?.(new Event("success"));
      });
    });
    return pending;
  }
  function databaseConnection(): IDBDatabase {
    const database = {
      close: () => undefined,
      createObjectStore: () => {
        initialized = true;
        return {};
      },
      objectStoreNames: { contains: () => initialized },
      onversionchange: null,
      transaction: (_store: string, mode?: IDBTransactionMode) => {
        const transaction = {
          error: null,
          onabort: null,
          oncomplete: null,
          onerror: null,
          objectStore: () => ({
            get: (key: IDBValidKey) => {
              const gate = indexedDatabaseReadGate;
              indexedDatabaseReadGate = null;
              return request(values.get(key), gate);
            },
            put: (value: unknown, key: IDBValidKey) => {
              const pending = request(key);
              void Promise.resolve().then(() => {
                queueMicrotask(() => {
                  queueMicrotask(() => {
                    if (indexedDatabaseWriteAborts) {
                      transaction.onabort?.(new Event("abort"));
                    } else {
                      values.set(key, value);
                      transaction.oncomplete?.(new Event("complete"));
                    }
                  });
                });
              });
              return pending;
            },
          }),
        } as unknown as IDBTransaction;
        if (mode !== "readwrite") {
          queueMicrotask(() => {
            transaction.oncomplete?.(new Event("complete"));
          });
        }
        return transaction;
      },
    } as unknown as IDBDatabase;
    return database;
  }
  return {
    open: () => {
      indexedDatabaseOpenCount += 1;
      const database = databaseConnection();
      const pending = {
        error: null,
        result: database,
      } as unknown as IDBOpenDBRequest;
      queueMicrotask(() => {
        if (!initialized) {
          pending.onupgradeneeded?.(
            Object.assign(new Event("upgradeneeded"), {
              newVersion: 1,
              oldVersion: 0,
            }),
          );
        }
        pending.onsuccess?.(new Event("success"));
        indexedDatabaseVersionChange = () => {
          database.onversionchange?.(
            Object.assign(new Event("versionchange"), {
              newVersion: 2,
              oldVersion: 1,
            }),
          );
        };
      });
      return pending;
    },
  } as unknown as IDBFactory;
}

beforeEach(() => {
  indexedDatabaseVersionChange?.();
  indexedDatabaseReadGate = null;
  indexedDatabaseWriteAborts = false;
  indexedDatabaseOpenCount = 0;
  indexedDatabaseVersionChange = null;
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: memoryStorage(),
  });
  Object.defineProperty(window, "indexedDB", {
    configurable: true,
    value: memoryIndexedDatabase(),
  });
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (
        _name: string,
        _options: LockOptions,
        callback: (lock: unknown) => unknown,
      ) => Promise.resolve(callback(null)),
    },
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

const session: SessionData = {
  actor_id: "actor-1",
  authenticated_at: "2026-08-22T10:00:00Z",
  last_activity_at: "2026-08-22T10:00:00Z",
  idle_expires_at: "2026-08-22T10:30:00Z",
  absolute_expires_at: "2026-08-23T10:00:00Z",
  mfa_assurance: "totp",
  reauthenticated_at: "2026-08-22T10:05:00Z",
};

const customerReconciliationKey = "property-rental.customer-reconciliation.v2";

async function storeCustomerReconciliation(
  requirement: CustomerReconciliationRequirement,
) {
  expect(await reserveCustomerReconciliation(requirement)).toMatchObject({
    reserved: true,
  });
}

function mockAuthenticationApi(
  overrides: Partial<AuthenticationApi> = {},
): AuthenticationApi {
  return {
    signIn: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    changePassword: vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session }),
    completeMfa: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    beginMfaEnrollment: vi.fn().mockResolvedValue({
      method: "totp",
      provisioning_uri: "otpauth://totp/PropertyRental:test?secret=protected",
    }),
    confirmMfaEnrollment: vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session }),
    inspectSession: vi.fn().mockResolvedValue(session),
    reauthenticate: vi.fn().mockResolvedValue(session),
    issueRecoveryCodes: vi.fn().mockResolvedValue({
      set_id: "set-1",
      codes: ["code-one", "code-two"],
    }),
    regenerateRecoveryCodes: vi.fn().mockResolvedValue({
      set_id: "set-2",
      codes: ["replacement-one", "replacement-two"],
    }),
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const configuredProperty: PropertyBusinessConfiguration = {
  property_id: "property-1",
  name: "Riverside",
  address_text: "Phnom Penh",
  timezone_name: "Asia/Phnom_Penh",
  payment_methods: [],
  version: 3,
};

function propertyApiDouble(
  overrides: Partial<PropertyConfigurationApi> = {},
): PropertyConfigurationApi {
  return {
    load: vi.fn().mockResolvedValue(configuredProperty),
    updateSource: vi.fn(),
    updatePaymentMethods: vi.fn(),
    ...overrides,
  };
}

function customerApiDouble(overrides: Partial<CustomerApi> = {}): CustomerApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
      can_manage: true,
    }),
    get: vi.fn().mockRejectedValue(new Error("not used")),
    commandStatus: vi.fn().mockRejectedValue(new Error("not used")),
    create: vi.fn().mockRejectedValue(new Error("not used")),
    update: vi.fn().mockRejectedValue(new Error("not used")),
    deactivate: vi.fn().mockRejectedValue(new Error("not used")),
    financialSummary: vi.fn().mockRejectedValue(new Error("not used")),
    ...overrides,
  };
}

function reconciledCustomer(
  customerId: string,
  legalName = "Reconciled Customer",
): CustomerDetail {
  return {
    customer_id: customerId,
    legal_name: legalName,
    phone_number: null,
    email_address: null,
    contact_address: null,
    memo: null,
    version: 1,
    active: true,
    deactivated_at: null,
    deactivation_reason: null,
    relationships: {
      reservations: [],
      primary_tenant_leases: [],
      signer_leases: [],
      occupancies: [],
      invoices: [],
      payments: [],
      customer_credit: [],
      refunds: [],
    },
    audit_history: [],
    audit_history_next_cursor: null,
    can_manage: true,
    can_deactivate: true,
    can_view_audit: false,
    audit_history_available: false,
  };
}

function renderPropertyConfigurationApp(propertyApi: PropertyConfigurationApi) {
  render(
    <App
      api={mockAuthenticationApi()}
      buildId="test-build"
      environment="development"
      now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      propertyApi={propertyApi}
    />,
  );
}

async function signInAndLoadProperty(propertyId = "property-1") {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "manager" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  const input = await screen.findByLabelText(
    "Configuration Property identifier",
  );
  fireEvent.change(input, { target: { value: propertyId } });
  fireEvent.click(
    screen.getByRole("button", { name: "Load business configuration" }),
  );
  return input;
}

function expectPropertyManagementHidden() {
  expect(
    screen.getByRole("heading", { name: "Business configuration access" }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Property name")).not.toBeInTheDocument();
}

describe("local sign-in", () => {
  it("TEST-FE-111 sends no Customer command when the encryption-key transaction aborts", async () => {
    indexedDatabaseWriteAborts = true;
    const requirement = {
      actorId: "actor-1",
      commandNonce: "12121212-1212-4212-8212-121212121212",
      kind: "create" as const,
      customerId: "customer-aborted-key",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
      createSource: { legal_name: "Already created elsewhere" },
    };

    expect(await reserveCustomerReconciliation(requirement)).toEqual({
      existing: null,
      reserved: false,
      storageAvailable: false,
    });
    expect(window.localStorage.length).toBe(0);
  });

  it("TEST-FE-141 reopens Customer coordination storage after an IndexedDB version change", async () => {
    const first = {
      actorId: "actor-version-1",
      commandNonce: "14114114-1141-4141-8141-141141141141",
      kind: "create" as const,
      customerId: "customer-version-1",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
      createSource: { legal_name: "First version" },
    };
    expect(await reserveCustomerReconciliation(first)).toMatchObject({
      reserved: true,
      storageAvailable: true,
    });
    expect(indexedDatabaseOpenCount).toBe(1);

    indexedDatabaseVersionChange?.();
    expect(await clearCustomerReconciliation(first)).toEqual({
      status: "cleared",
    });
    expect(indexedDatabaseOpenCount).toBe(2);
    const second = {
      ...first,
      actorId: "actor-version-2",
      commandNonce: "14114114-1141-4141-8141-141141141142",
      customerId: "customer-version-2",
      createSource: { legal_name: "Second version" },
    };
    expect(await reserveCustomerReconciliation(second)).toMatchObject({
      reserved: true,
      storageAvailable: true,
    });
    expect(indexedDatabaseOpenCount).toBe(2);
  });

  it("TEST-FE-001 renders an accessible local username and password form", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(
      screen.getByRole("heading", { name: "Property Rental Management" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute(
      "type",
      "submit",
    );
  });

  it("TEST-FE-002 shows safe support metadata outside production", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(screen.getByText("development")).toBeInTheDocument();
    expect(screen.getByText("Build test-build")).toBeInTheDocument();
  });

  it("TEST-FE-003 does not show the environment indicator in production", () => {
    render(<App environment="production" buildId="release-1" />);

    expect(screen.queryByText("production")).not.toBeInTheDocument();
    expect(screen.getByText("Build release-1")).toBeInTheDocument();
  });

  it("TEST-FE-004 submits the labeled controls through the semantic form", async () => {
    const authenticate = vi.fn().mockResolvedValue({
      phase: "authenticated",
      session,
    });
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    const form = screen
      .getByRole("button", { name: "Sign in" })
      .closest("form");
    expect(form).not.toBeNull();
    if (form === null) {
      throw new Error("sign-in form is missing");
    }
    fireEvent.submit(form);

    await waitFor(() => {
      expect(authenticate).toHaveBeenCalledWith({
        username: "local-user",
        password: "local-password",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your sign-in was accepted.",
    );
  });

  it("TEST-FE-221 mounts the Utilities workflow only in the authenticated workspace", async () => {
    const authenticate = vi.fn().mockResolvedValue({
      phase: "authenticated",
      session,
    });
    render(
      <App
        environment="development"
        buildId="utility-integration"
        authenticate={authenticate}
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    expect(
      screen.queryByRole("heading", { name: "Utilities" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "utility-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "protected-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "Utilities" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-005 announces one generic, associated authentication failure", async () => {
    const authenticate = vi
      .fn()
      .mockRejectedValue(new Error("account disabled"));
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "possible-owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(AUTHENTICATION_ERROR_MESSAGE);
    expect(alert).not.toHaveTextContent("disabled");
    expect(screen.getByLabelText("Username")).toHaveAccessibleDescription(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("TEST-FE-006 exposes no first-Owner, external-provider, SMS, or security-question flow", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(screen.queryByText(/create first owner/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/google|microsoft|auth0/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/sms|security question/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Need help signing in? Contact your administrator."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-007 keeps native controls focusable in a logical keyboard order", () => {
    render(<App environment="development" buildId="test-build" />);

    const username = screen.getByLabelText("Username");
    const password = screen.getByLabelText("Password");
    const submit = screen.getByRole("button", { name: "Sign in" });
    const form = submit.closest("form");

    expect(form).not.toBeNull();
    expect(form?.querySelectorAll("input, button")).toEqual(
      expect.objectContaining({
        0: username,
        1: password,
        2: submit,
        length: 3,
      }),
    );

    for (const control of [username, password, submit]) {
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("TEST-FE-008 allows retry after a generic failure without clearing credentials", async () => {
    const authenticate = vi
      .fn()
      .mockRejectedValueOnce(new Error("unknown account"))
      .mockResolvedValueOnce({ phase: "authenticated", session });
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Username")).toHaveValue("local-user");
    expect(screen.getByLabelText("Password")).toHaveValue("local-password");

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your sign-in was accepted.",
    );
    expect(authenticate).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-009 completes TOTP or single-use recovery-code challenge without revealing account state", async () => {
    const completeMfa = vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session });
    const api = mockAuthenticationApi({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_required", session: null }),
      completeMfa,
    });
    render(<App api={api} environment="development" buildId="test-build" />);

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", {
        name: "Complete multi-factor authentication",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Recovery code"));
    fireEvent.change(screen.getByLabelText("Unused recovery code"), {
      target: { value: "one-time-code" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => {
      expect(completeMfa).toHaveBeenCalledWith({
        method: "recovery_code",
        code: "one-time-code",
      });
    });
    expect(screen.queryByText(/account disabled/i)).not.toBeInTheDocument();
  });

  it("TEST-FE-010 presents enrollment material once and confirms protected TOTP enrollment", async () => {
    const api = mockAuthenticationApi({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_enrollment_required", session: null }),
    });
    render(<App api={api} environment="development" buildId="test-build" />);
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Begin protected enrollment" }),
    );
    expect(
      await screen.findByRole("region", {
        name: "One-time enrollment material",
      }),
    ).toHaveTextContent("otpauth://totp/");
    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm enrollment" }));
    await waitFor(() => {
      expect(api.confirmMfaEnrollment).toHaveBeenCalledWith("123456");
    });
  });

  it("TEST-FE-011 returns expired sessions to sign-in without claiming unsaved commands succeeded", async () => {
    vi.useFakeTimers();
    const api = mockAuthenticationApi();
    render(
      <App
        api={api}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:29:59Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Account and access");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByRole("status")).toHaveTextContent(
      "unsaved command was not submitted",
    );
    vi.useRealTimers();
  });

  it("TEST-FE-012 exposes account commands only after server capability and recent-auth checks with explicit consequence confirmation", async () => {
    const user: UserAccount = {
      user_id: "user-1",
      property_id: "property-1",
      username: "staff-one",
      display_name: "Staff One",
      audit_name: "Staff One",
      lifecycle_state: "active",
      mfa_policy_class: "optional",
      version: 1,
      account_class: "staff",
      settings_access: false,
    };
    const disableUser = vi.fn().mockResolvedValue({
      ...user,
      lifecycle_state: "disabled",
      version: 2,
    });
    const administrationApi: AccessAdministrationApi = {
      load: vi.fn().mockResolvedValue({
        users: [user],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      }),
      createUser: vi.fn(),
      disableUser,
      revokeSessions: vi.fn(),
      createRoleBundle: vi.fn(),
      assignRoleBundle: vi.fn(),
      administrativelyRecoverUser: vi.fn(),
    };
    render(
      <App
        administrationApi={administrationApi}
        api={mockAuthenticationApi()}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    expect((await screen.findAllByText("Staff One")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Disable account" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "revokes every applicable session",
    );
    expect(disableUser).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    await waitFor(() => {
      expect(disableUser).toHaveBeenCalledWith(user);
    });
  });

  it("TEST-FE-013 presents recovery codes once and clears accessible material on acknowledgement", async () => {
    const api = mockAuthenticationApi();
    render(
      <App
        api={api}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Generate one-time recovery codes",
      }),
    );

    expect(
      await screen.findByRole("region", { name: "One-time recovery codes" }),
    ).toHaveTextContent("code-one");
    fireEvent.click(
      screen.getByRole("button", {
        name: "I saved these codes—clear them",
      }),
    );
    expect(
      screen.queryByRole("region", { name: "One-time recovery codes" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("code-one")).not.toBeInTheDocument();
  });

  it("TEST-FE-014 requires consequence confirmation before administrative recovery", async () => {
    const user: UserAccount = {
      user_id: "user-1",
      property_id: "property-1",
      username: "staff-one",
      display_name: "Staff One",
      audit_name: "Staff One",
      lifecycle_state: "active",
      mfa_policy_class: "optional",
      version: 1,
      account_class: "staff",
      settings_access: false,
    };
    const administrativelyRecoverUser = vi.fn().mockResolvedValue({
      user_id: "user-1",
      password_changed: true,
      mfa_reset: true,
      sessions_revoked: 2,
      one_time_password: {
        value: "k7m2-x9qp-4hrt-w3nd",
        expires_at: "2026-08-23T10:10:00Z",
      },
    });
    const administrationApi: AccessAdministrationApi = {
      load: vi.fn().mockResolvedValue({
        users: [user],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      }),
      createUser: vi.fn(),
      disableUser: vi.fn(),
      revokeSessions: vi.fn(),
      createRoleBundle: vi.fn(),
      assignRoleBundle: vi.fn(),
      administrativelyRecoverUser,
    };
    render(
      <App
        administrationApi={administrationApi}
        api={mockAuthenticationApi()}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    await screen.findByRole("heading", {
      name: "Owner-authorized account recovery",
    });
    // Login sub-slice L4: the Owner types no password; the server makes a one-time password.
    expect(
      screen.queryByLabelText("New password (15–128 characters)"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Audit reason"), {
      target: { value: "approved recovery" },
    });
    fireEvent.click(screen.getByLabelText("Reset current MFA enrollment"));
    fireEvent.click(
      screen.getByRole("button", { name: "Review recovery consequences" }),
    );
    expect(administrativelyRecoverUser).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "revokes every applicable session",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    await waitFor(() => {
      expect(administrativelyRecoverUser).toHaveBeenCalledWith("user-1", {
        reset_mfa: true,
        reason: "approved recovery",
      });
    });
    const shown = await screen.findByRole("region", {
      name: "One-time password",
    });
    expect(shown).toHaveTextContent("staff-one");
    expect(shown).toHaveTextContent("k7m2-x9qp-4hrt-w3nd");
    expect(shown).toHaveTextContent("2026-08-23T10:10:00.000Z");
    fireEvent.click(
      screen.getByRole("button", { name: "I gave it to the person—clear it" }),
    );
    expect(screen.queryByText("k7m2-x9qp-4hrt-w3nd")).not.toBeInTheDocument();
  });

  it("TEST-FE-684 shows a new account's first one-time password once and clears it", async () => {
    const created: UserAccount = {
      user_id: "user-2",
      property_id: "property-1",
      username: "staff-two",
      display_name: "Staff Two",
      audit_name: "Staff Two",
      lifecycle_state: "active",
      mfa_policy_class: "optional",
      version: 1,
      account_class: "staff",
      settings_access: false,
    };
    const createUser = vi.fn().mockResolvedValue({
      account: created,
      one_time_password: {
        value: "p4qr-7mxt-k2nw-9hds",
        expires_at: "2026-08-23T10:10:00Z",
      },
    });
    const load = vi.fn().mockResolvedValue({
      users: [],
      capabilities: [],
      roleBundles: [],
      authorizationHistory: [],
    });
    const administrationApi: AccessAdministrationApi = {
      load,
      createUser,
      disableUser: vi.fn(),
      revokeSessions: vi.fn(),
      createRoleBundle: vi.fn(),
      assignRoleBundle: vi.fn(),
      administrativelyRecoverUser: vi.fn(),
    };
    render(
      <App
        administrationApi={administrationApi}
        api={mockAuthenticationApi()}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    await screen.findByRole("heading", { name: "Create account" });
    const createAccount = () => {
      fireEvent.change(screen.getByLabelText("Username"), {
        target: { value: "staff-two" },
      });
      fireEvent.change(screen.getByLabelText("Display name"), {
        target: { value: "Staff Two" },
      });
      fireEvent.change(screen.getByLabelText("Audit name"), {
        target: { value: "Staff Two" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Create audited account" }),
      );
    };
    createAccount();
    const shown = await screen.findByRole("region", {
      name: "One-time password",
    });
    expect(createUser).toHaveBeenCalledTimes(1);
    expect(shown).toHaveTextContent("staff-two");
    expect(shown).toHaveTextContent("p4qr-7mxt-k2nw-9hds");
    fireEvent.click(
      screen.getByRole("button", { name: "I gave it to the person—clear it" }),
    );
    expect(screen.queryByText("p4qr-7mxt-k2nw-9hds")).not.toBeInTheDocument();

    // Review round 2: loading the administration again clears a password not cleared by hand.
    createAccount();
    await screen.findByRole("region", { name: "One-time password" });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    await waitFor(() => {
      expect(load).toHaveBeenCalledTimes(2);
    });
    expect(
      screen.queryByRole("region", { name: "One-time password" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-682 asks for a new password after a one-time password and shows the rule", async () => {
    const changePassword = vi
      .fn()
      .mockRejectedValueOnce(new PasswordRuleError())
      .mockResolvedValueOnce({
        phase: "mfa_enrollment_required",
        session: null,
      });
    const api = mockAuthenticationApi({
      signIn: vi.fn().mockResolvedValue({
        phase: "password_change_required",
        session: null,
      }),
      changePassword,
    });
    render(<App api={api} environment="development" buildId="test-build" />);
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "staff-one" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "k7m2-x9qp-4hrt-w3nd" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "Choose your own password" }),
    ).toBeInTheDocument();
    expect(screen.getByText(PASSWORD_RULE_MESSAGE)).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Save the new password" });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "a long new password of mine" },
    });
    fireEvent.change(screen.getByLabelText("New password again"), {
      target: { value: "a different long password" },
    });
    fireEvent.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords must match",
    );
    expect(changePassword).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("New password again"), {
      target: { value: "a long new password of mine" },
    });
    fireEvent.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This password was not accepted.",
    );
    fireEvent.click(save);
    expect(
      await screen.findByRole("button", { name: "Begin protected enrollment" }),
    ).toBeInTheDocument();
    expect(changePassword).toHaveBeenCalledTimes(2);
    expect(changePassword).toHaveBeenLastCalledWith(
      "a long new password of mine",
    );
  });

  it.each([new SessionExpiredError(), new Error("network")])(
    "TEST-FE-683 returns to sign-in when the password change did not finish",
    async (failure) => {
      const api = mockAuthenticationApi({
        signIn: vi.fn().mockResolvedValue({
          phase: "password_change_required",
          session: null,
        }),
        changePassword: vi.fn().mockRejectedValue(failure),
      });
      render(<App api={api} environment="development" buildId="test-build" />);
      fireEvent.change(screen.getByLabelText("Username"), {
        target: { value: "staff-one" },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "k7m2-x9qp-4hrt-w3nd" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      fireEvent.change(await screen.findByLabelText("New password"), {
        target: { value: "a long new password of mine" },
      });
      fireEvent.change(screen.getByLabelText("New password again"), {
        target: { value: "a long new password of mine" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Save the new password" }),
      );
      expect(
        await screen.findByText(
          "The password change did not finish. Sign in with your new password. If it is not accepted, sign in with your one-time password.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Sign in" }),
      ).toBeInTheDocument();
    },
  );

  it("TEST-FE-015 restores a valid server session after a browser refresh", async () => {
    const restoredSession = {
      ...session,
      idle_expires_at: "2099-08-22T10:30:00Z",
      absolute_expires_at: "2099-08-23T10:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: restoredSession,
            meta: { request_id: "restore-session" },
          }),
        ),
      ),
    );

    render(<App environment="development" buildId="test-build" />);

    expect(
      await screen.findByRole("heading", { name: "Account and access" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-016 shows and updates capability-checked Property business configuration", async () => {
    const configured: PropertyBusinessConfiguration = {
      property_id: "property-1",
      name: "Riverside",
      address_text: "Phnom Penh",
      timezone_name: "Asia/Phnom_Penh",
      payment_methods: [
        { code: "BANK", display_name: "Bank transfer", accepted: true },
      ],
      version: 3,
    };
    const updateSource = vi.fn().mockResolvedValue({
      ...configured,
      name: "Riverside Apartments",
      version: 4,
    });
    const propertyApi: PropertyConfigurationApi = {
      load: vi.fn().mockResolvedValue(configured),
      updateSource,
      updatePaymentMethods: vi.fn(),
    };
    renderPropertyConfigurationApp(propertyApi);
    await signInAndLoadProperty();

    expect(await screen.findByDisplayValue("Riverside")).toBeInTheDocument();
    expect(screen.getByText("Asia/Phnom_Penh")).toBeInTheDocument();
    expect(screen.getByLabelText(/Bank transfer.*accepted/)).toBeChecked();
    fireEvent.change(screen.getByLabelText("Property name"), {
      target: { value: "Riverside Apartments" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Property source data" }),
    );
    await waitFor(() => {
      expect(updateSource).toHaveBeenCalledWith(configured, {
        name: "Riverside Apartments",
        address_text: "Phnom Penh",
      });
    });
  });

  it("TEST-FE-020 keeps the management screen hidden when server capability authorization is denied", async () => {
    const propertyApi = propertyApiDouble({
      load: vi
        .fn()
        .mockRejectedValue(new PropertyConfigurationUnavailableError()),
    });
    renderPropertyConfigurationApp(propertyApi);
    await signInAndLoadProperty();

    expect(
      await screen.findByText(
        "Business configuration is not available for this session and property.",
      ),
    ).toBeInTheDocument();
    expectPropertyManagementHidden();
  });

  it("TEST-FE-021 hides loaded management controls when source-update authorization is revoked", async () => {
    const propertyApi = propertyApiDouble({
      updateSource: vi
        .fn()
        .mockRejectedValue(new PropertyConfigurationUnavailableError()),
    });
    renderPropertyConfigurationApp(propertyApi);
    await signInAndLoadProperty();
    fireEvent.click(
      await screen.findByRole("button", { name: "Save Property source data" }),
    );

    await screen.findByRole("heading", {
      name: "Business configuration access",
    });
    expectPropertyManagementHidden();
  });

  it("TEST-FE-022 hides loaded management controls when configuration-update authorization is revoked", async () => {
    const propertyApi = propertyApiDouble({
      updatePaymentMethods: vi
        .fn()
        .mockRejectedValue(new PropertyConfigurationUnavailableError()),
    });
    renderPropertyConfigurationApp(propertyApi);
    await signInAndLoadProperty();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Save Payment Method configuration",
      }),
    );

    await screen.findByRole("heading", {
      name: "Business configuration access",
    });
    expectPropertyManagementHidden();
  });

  it("TEST-FE-023 ignores a stale Property load that resolves after sign-out", async () => {
    let resolveLoad!: (value: PropertyBusinessConfiguration) => void;
    const propertyApi = propertyApiDouble({
      load: vi.fn().mockReturnValue(
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          resolveLoad = resolve;
        }),
      ),
    });
    renderPropertyConfigurationApp(propertyApi);
    await signInAndLoadProperty();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();

    await act(async () => {
      resolveLoad(configuredProperty);
      await Promise.resolve();
    });

    expect(
      screen.queryByRole("heading", { name: "Business configuration" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Property name")).not.toBeInTheDocument();
  });

  it("TEST-FE-071 protects dirty Customer forms from in-app sign-out", async () => {
    const authentication = mockAuthenticationApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Unsent Customer" } },
    );

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(confirm).toHaveBeenCalledOnce();
    expect(authentication.logout).not.toHaveBeenCalled();
    expect(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
    ).toHaveValue("Unsent Customer");
    expect(
      screen.getByText(
        "Sign out was cancelled; unsaved Customer values were preserved.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-072 hides a pending command and requires reconciliation after sign-out", async () => {
    let finishCreate!: (value: Parameters<CustomerApi["update"]>[0]) => void;
    const pendingCreate = new Promise<Parameters<CustomerApi["update"]>[0]>(
      (resolve) => {
        finishCreate = resolve;
      },
    );
    const authentication = mockAuthenticationApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const customers = customerApiDouble({
      get: vi
        .fn()
        .mockImplementation((customerId: string) =>
          Promise.resolve(reconciledCustomer(customerId, "Pending Customer")),
        ),
      commandStatus: vi
        .fn()
        .mockImplementation((_: string, customerId: string) =>
          Promise.resolve({
            recorded: true,
            customer: reconciledCustomer(customerId, "Pending Customer"),
          }),
        ),
      create: vi.fn().mockReturnValue(pendingCreate),
      financialSummary: vi.fn().mockResolvedValue({
        source_status: "UNAVAILABLE_UNTIL_FINANCIAL_SOURCES_ARE_IMPLEMENTED",
        source_availability: {
          deposits: "UNAVAILABLE_NOT_IMPLEMENTED",
          invoices: "UNAVAILABLE_NOT_IMPLEMENTED",
          late_charges: "UNAVAILABLE_NOT_IMPLEMENTED",
          payments: "UNAVAILABLE_NOT_IMPLEMENTED",
          customer_credit: "UNAVAILABLE_NOT_IMPLEMENTED",
        },
        currency_summaries: [],
        deposit_liabilities: [],
        deposit_liabilities_page: { next_cursor: null, limit: 50 },
        deposit_aggregate: {
          count: 0,
          required_usd_cents: 0,
          received_usd_cents: 0,
          held_refundable_usd_cents: 0,
          outstanding_required_usd_cents: 0,
        },
        customer_credit_is_separate_from_deposit: true,
      }),
    });
    render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Pending Customer" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await waitFor(() => {
      expect(customers.create).toHaveBeenCalledOnce();
    });

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(confirm).toHaveBeenCalledOnce();
    expect(authentication.logout).toHaveBeenCalledOnce();
    expect(
      screen.queryByLabelText("Customer Property identifier"),
    ).not.toBeInTheDocument();
    await screen.findByLabelText("Username");

    await act(async () => {
      finishCreate({
        customer_id: "customer-created",
        legal_name: "Pending Customer",
        phone_number: null,
        email_address: null,
        contact_address: null,
        memo: null,
        version: 1,
        active: true,
        deactivated_at: null,
        deactivation_reason: null,
        relationships: {
          reservations: [],
          primary_tenant_leases: [],
          signer_leases: [],
          occupancies: [],
          invoices: [],
          payments: [],
          customer_credit: [],
          refunds: [],
        },
        audit_history: [],
        audit_history_next_cursor: null,
        can_manage: true,
        can_deactivate: true,
        can_view_audit: false,
        audit_history_available: false,
      });
      await Promise.resolve();
    });

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByText(/A Customer command outcome is unknown/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    await waitFor(() => {
      expect(
        screen.queryByText(/A prior Customer command may have completed/),
      ).not.toBeInTheDocument();
    });
  });

  it("TEST-FE-076 marks an in-flight Customer outcome unknown on session expiry", async () => {
    vi.useFakeTimers();
    let finishCreate!: (value: Parameters<CustomerApi["update"]>[0]) => void;
    const pendingCreate = new Promise<Parameters<CustomerApi["update"]>[0]>(
      (resolve) => {
        finishCreate = resolve;
      },
    );
    const expiringSession = {
      ...session,
      idle_expires_at: "2026-08-22T10:10:01Z",
    };
    const authentication = mockAuthenticationApi({
      signIn: vi.fn().mockResolvedValue({
        phase: "authenticated",
        session: expiringSession,
      }),
    });
    const customers = customerApiDouble({
      create: vi.fn().mockReturnValue(pendingCreate),
    });
    render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load Customers",
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Pending Customer" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await vi.waitFor(() => {
      expect(customers.create).toHaveBeenCalledOnce();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(
      screen.getByText(/session expired while a Customer command was pending/),
    ).toBeInTheDocument();
    await act(async () => {
      finishCreate({
        customer_id: "customer-created",
        legal_name: "Pending Customer",
        phone_number: null,
        email_address: null,
        contact_address: null,
        memo: null,
        version: 1,
        active: true,
        deactivated_at: null,
        deactivation_reason: null,
        relationships: {
          reservations: [],
          primary_tenant_leases: [],
          signer_leases: [],
          occupancies: [],
          invoices: [],
          payments: [],
          customer_credit: [],
          refunds: [],
        },
        audit_history: [],
        audit_history_next_cursor: null,
        can_manage: true,
        can_deactivate: true,
        can_view_audit: false,
        audit_history_available: false,
      });
      await Promise.resolve();
    });
    vi.useRealTimers();
  });

  it("TEST-FE-101 keeps an unresolved Customer command pending at later session expiry", async () => {
    vi.useFakeTimers();
    const expiringSession = {
      ...session,
      idle_expires_at: "2026-08-22T10:10:01Z",
    };
    const authentication = mockAuthenticationApi({
      signIn: vi.fn().mockResolvedValue({
        phase: "authenticated",
        session: expiringSession,
      }),
    });
    const customers = customerApiDouble({
      create: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError("Outcome unknown", [], null, true),
        ),
    });
    render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Possibly Created" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await vi.waitFor(() => {
      expect(customers.create).toHaveBeenCalledOnce();
    });
    expect(
      screen.getByText(/Customer creation outcome is unknown/),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(
      screen.getByText(/session expired while a Customer command was pending/),
    ).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("TEST-FE-079 requires list reconciliation after an ambiguous Customer create", async () => {
    const customers = customerApiDouble({
      get: vi
        .fn()
        .mockImplementation((customerId: string) =>
          Promise.resolve(reconciledCustomer(customerId, "Possibly Created")),
        ),
      commandStatus: vi
        .fn()
        .mockImplementation((_: string, customerId: string) =>
          Promise.resolve({
            recorded: true,
            customer: reconciledCustomer(customerId, "Possibly Created"),
          }),
        ),
      create: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError(
            "The Customer creation outcome is unknown.",
            [],
            null,
            true,
          ),
        ),
    });
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Possibly Created" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    expect(
      await screen.findByText(/Customer creation outcome is unknown/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    expect(
      await screen.findByRole(
        "button",
        { name: "I verified the prior Customer command result" },
        { timeout: 5000 },
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(
      await screen.findByRole("button", { name: "Create Customer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("");
  });

  it("TEST-FE-087 safely retries an authoritatively absent creation with the same identity", async () => {
    const commandId = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(crypto, "randomUUID").mockReturnValue(commandId);
    const customers = customerApiDouble({
      commandStatus: vi
        .fn()
        .mockResolvedValue({ recorded: false, customer: null }),
      create: vi
        .fn()
        .mockRejectedValueOnce(
          new CustomerRequestError(
            "The Customer creation outcome is unknown.",
            [],
            null,
            true,
          ),
        )
        .mockResolvedValueOnce(reconciledCustomer(commandId)),
    });
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Possibly Created" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await screen.findByText(/Customer creation outcome is unknown/);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    expect(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Possibly Created");
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await waitFor(() => {
      expect(customers.create).toHaveBeenCalledTimes(2);
    });
    expect(customers.create).toHaveBeenNthCalledWith(
      1,
      "property-1",
      commandId,
      expect.objectContaining({ legal_name: "Possibly Created" }),
      commandId,
    );
    expect(customers.create).toHaveBeenNthCalledWith(
      2,
      "property-1",
      commandId,
      expect.objectContaining({ legal_name: "Possibly Created" }),
      commandId,
    );
  });

  it("TEST-FE-080 restores an unresolved Customer command gate after reload", async () => {
    const customers = customerApiDouble({
      create: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError(
            "The Customer creation outcome is unknown.",
            [],
            null,
            true,
          ),
        ),
    });
    const authentication = mockAuthenticationApi();
    const first = render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Possibly Created" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await screen.findByText(/Customer creation outcome is unknown/);
    expect(window.localStorage.length).toBe(2);
    const opaqueHandle = window.localStorage.getItem(customerReconciliationKey);
    expect(opaqueHandle).toMatch(/^[0-9a-f-]{36}$/i);
    expect(opaqueHandle).not.toContain("actor-1");
    expect(opaqueHandle).not.toContain("property-1");
    expect(opaqueHandle).not.toContain("Possibly Created");
    expect(window.sessionStorage.length).toBe(0);
    const sealed = window.localStorage.getItem(
      `${customerReconciliationKey}.sealed.${opaqueHandle ?? ""}`,
    );
    expect(sealed).not.toContain("actor-1");
    expect(sealed).not.toContain("property-1");
    expect(sealed).not.toContain("Possibly Created");
    first.unmount();

    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByText(/A prior Customer command may have completed/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-085 does not expose one actor's unresolved command to another actor", async () => {
    await storeCustomerReconciliation({
      actorId: "actor-1",
      commandNonce: "66666666-6666-4666-8666-666666666666",
      kind: "create",
      customerId: "customer-command-1",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    });
    const otherActor = { ...session, actor_id: "actor-2" };
    render(
      <App
        api={mockAuthenticationApi({
          signIn: vi.fn().mockResolvedValue({
            phase: "authenticated",
            session: otherActor,
          }),
        })}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "other-manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "coordination is unavailable",
    );
    expect(
      screen.queryByText(/A prior Customer command may have completed/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-088 synchronizes an actor's unresolved command gate across tabs", async () => {
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByLabelText("Customer Property identifier");
    const key = customerReconciliationKey;
    const requirement: CustomerReconciliationRequirement = {
      actorId: "actor-1",
      commandNonce: "77777777-7777-4777-8777-777777777777",
      kind: "create",
      customerId: "customer-command-cross-tab",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    await storeCustomerReconciliation(requirement);
    window.dispatchEvent(
      new StorageEvent("storage", {
        key,
        newValue: requirement.commandNonce,
      }),
    );
    expect(
      await screen.findByText(/A prior Customer command may have completed/),
    ).toBeInTheDocument();

    window.localStorage.removeItem(key);
    window.dispatchEvent(new StorageEvent("storage", { key, newValue: null }));
    await waitFor(() => {
      expect(
        screen.queryByText(/A prior Customer command may have completed/),
      ).not.toBeInTheDocument();
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "resolved in another tab",
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    expect(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("");
  });

  it("TEST-FE-103 ignores a stale encrypted gate read after a newer clear event", async () => {
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByLabelText("Customer Property identifier");
    const requirement: CustomerReconciliationRequirement = {
      actorId: "actor-1",
      commandNonce: "99999999-9999-4999-8999-999999999999",
      kind: "create",
      customerId: "customer-command-stale-read",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    await storeCustomerReconciliation(requirement);
    let releaseRead!: () => void;
    indexedDatabaseReadGate = new Promise((resolve) => {
      releaseRead = resolve;
    });
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: customerReconciliationKey,
        newValue: requirement.commandNonce,
      }),
    );
    await waitFor(() => {
      expect(indexedDatabaseReadGate).toBeNull();
    });

    window.localStorage.removeItem(customerReconciliationKey);
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: customerReconciliationKey,
        newValue: null,
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "resolved in another tab",
    );
    releaseRead();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      "resolved in another tab",
    );
    expect(
      screen.queryByText(/A prior Customer command may have completed/),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-092 serializes simultaneous Customer reservations before either command is sent", async () => {
    let lockQueue = Promise.resolve<unknown>(undefined);
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: {
        request: vi.fn(
          (
            _name: string,
            _options: LockOptions,
            callback: (lock: unknown) => unknown,
          ) => {
            const result = lockQueue.then(() => callback(null));
            lockQueue = result.then(
              () => undefined,
              () => undefined,
            );
            return result;
          },
        ),
      },
    });
    const firstRequirement = {
      actorId: "actor-1",
      commandNonce: "22222222-2222-4222-8222-222222222222",
      kind: "create" as const,
      customerId: "customer-command-first",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    const secondRequirement = {
      ...firstRequirement,
      commandNonce: "33333333-3333-4333-8333-333333333333",
      customerId: "customer-command-second",
    };

    const [first, second] = await Promise.all([
      reserveCustomerReconciliation(firstRequirement),
      reserveCustomerReconciliation(secondRequirement),
    ]);

    expect(first).toEqual({
      existing: null,
      reserved: true,
      storageAvailable: true,
    });
    expect(second).toEqual({
      existing: firstRequirement,
      reserved: false,
      storageAvailable: true,
    });
    expect(window.localStorage.length).toBe(2);
  });

  it("TEST-FE-094 never lets a late command completion clear a newer durable gate", async () => {
    const firstRequirement = {
      actorId: "actor-1",
      commandNonce: "44444444-4444-4444-8444-444444444444",
      kind: "update" as const,
      customerId: "customer-same",
      propertyId: "property-1",
      resultFingerprint: "a".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    const newerRequirement = {
      ...firstRequirement,
      commandNonce: "55555555-5555-4555-8555-555555555555",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "b".repeat(64),
    };

    expect(await reserveCustomerReconciliation(firstRequirement)).toMatchObject(
      {
        reserved: true,
      },
    );
    expect(await clearCustomerReconciliation(firstRequirement)).toEqual({
      status: "cleared",
    });
    expect(await reserveCustomerReconciliation(newerRequirement)).toMatchObject(
      {
        reserved: true,
      },
    );

    expect(await clearCustomerReconciliation(firstRequirement)).toEqual({
      status: "superseded",
      requirement: newerRequirement,
    });
    expect(window.localStorage.getItem(customerReconciliationKey)).toBe(
      newerRequirement.commandNonce,
    );
  });

  it("TEST-FE-115 clears the active gate before best-effort sealed cleanup", async () => {
    const requirement = {
      actorId: "actor-1",
      commandNonce: "66666666-6666-4666-8666-666666666666",
      kind: "update" as const,
      customerId: "customer-clear-order",
      propertyId: "property-1",
      resultFingerprint: "c".repeat(64),
      requestFingerprint: "d".repeat(64),
    };
    expect(await reserveCustomerReconciliation(requirement)).toMatchObject({
      reserved: true,
    });
    const sealedKey = `${customerReconciliationKey}.sealed.${requirement.commandNonce}`;
    const removeItem = window.localStorage.removeItem.bind(window.localStorage);
    vi.spyOn(window.localStorage, "removeItem").mockImplementation((key) => {
      if (key === sealedKey) throw new Error("browser closed during cleanup");
      removeItem(key);
    });

    expect(await clearCustomerReconciliation(requirement)).toEqual({
      status: "cleared",
    });
    expect(window.localStorage.getItem(customerReconciliationKey)).toBeNull();
    expect(window.localStorage.getItem(sealedKey)).not.toBeNull();
  });

  it("TEST-FE-135 treats a matching gate cleared by another tab as reconciled", async () => {
    const commandId = "77777777-7777-4777-8777-777777777777";
    vi.spyOn(crypto, "randomUUID").mockReturnValue(commandId);
    const customers = customerApiDouble({
      get: vi
        .fn()
        .mockImplementation((customerId: string) =>
          Promise.resolve(reconciledCustomer(customerId, "Cross-tab Customer")),
        ),
      commandStatus: vi
        .fn()
        .mockImplementation((_: string, customerId: string) =>
          Promise.resolve({
            recorded: true,
            customer: reconciledCustomer(customerId, "Cross-tab Customer"),
          }),
        ),
      create: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError(
            "The Customer creation outcome is unknown.",
            [],
            null,
            true,
          ),
        ),
    });
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Cross-tab Customer" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await screen.findByText(/Customer creation outcome is unknown/);
    const checkStatus = screen.getByRole("button", {
      name: "Check the prior Customer command status",
    });
    await waitFor(() => {
      expect(checkStatus).toBeEnabled();
    });
    fireEvent.click(checkStatus);
    const reconcile = await screen.findByRole(
      "button",
      { name: "I verified the prior Customer command result" },
      { timeout: 5000 },
    );
    await waitFor(() => {
      expect(reconcile).toBeEnabled();
    });
    window.localStorage.removeItem(customerReconciliationKey);
    fireEvent.click(reconcile);

    expect(
      await screen.findByRole("button", { name: "Create Customer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The Customer reconciliation gate was already resolved in another tab.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/A newer Customer command gate remains active/),
    ).not.toBeInTheDocument();
  }, 15000);

  it("TEST-FE-093 sends no Customer command when durable coordination is unavailable", async () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const customers = customerApiDouble();
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.change(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Blocked command" } },
    );

    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    expect(
      await screen.findByText(
        "Customer command coordination is unavailable. No command was sent; restore durable browser coordination before retrying.",
      ),
    ).toBeInTheDocument();
    expect(customers.create).not.toHaveBeenCalled();
  });

  it("TEST-FE-109 keeps Customer reads available when durable mutation coordination is unavailable", async () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const detail = reconciledCustomer("customer-readable", "Readable Customer");
    const customers = customerApiDouble({
      list: vi.fn().mockResolvedValue({
        items: [
          {
            customer_id: detail.customer_id,
            legal_name: detail.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: null,
        can_manage: true,
      }),
      get: vi.fn().mockResolvedValue(detail),
      financialSummary: vi.fn().mockResolvedValue({
        source_status: "UNAVAILABLE_UNTIL_FINANCIAL_SOURCES_ARE_IMPLEMENTED",
        source_availability: {
          deposits: "UNAVAILABLE_NOT_IMPLEMENTED",
          invoices: "UNAVAILABLE_NOT_IMPLEMENTED",
          late_charges: "UNAVAILABLE_NOT_IMPLEMENTED",
          payments: "UNAVAILABLE_NOT_IMPLEMENTED",
          customer_credit: "UNAVAILABLE_NOT_IMPLEMENTED",
        },
        currency_summaries: [],
        deposit_liabilities: [],
        deposit_liabilities_page: { next_cursor: null, limit: 50 },
        deposit_aggregate: {
          count: 0,
          required_usd_cents: 0,
          received_usd_cents: 0,
          held_refundable_usd_cents: 0,
          outstanding_required_usd_cents: 0,
        },
        customer_credit_is_separate_from_deposit: true,
      }),
    });
    render(
      <App
        api={mockAuthenticationApi()}
        buildId="test-build"
        customerApi={customers}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    fireEvent.change(
      await screen.findByLabelText("Customer Property identifier"),
      { target: { value: "property-1" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Readable Customer" }),
    );

    expect(await screen.findByText("Readable Customer")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Customer command coordination unavailable",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Update Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-110 prevents delayed session restoration from replacing a newer sign-in", async () => {
    const oldRequirement: CustomerReconciliationRequirement = {
      actorId: "actor-1",
      commandNonce: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      kind: "create",
      customerId: "customer-old-session",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    await storeCustomerReconciliation(oldRequirement);
    let releaseStoredGate!: () => void;
    indexedDatabaseReadGate = new Promise<void>((resolve) => {
      releaseStoredGate = resolve;
    });
    const newerSession: SessionData = {
      ...session,
      actor_id: "actor-2",
      idle_expires_at: "2026-08-22T11:30:00Z",
      absolute_expires_at: "2026-08-24T10:00:00Z",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const data = path.endsWith("/auth/session")
        ? session
        : { phase: "authenticated", session: newerSession };
      return Promise.resolve(
        new Response(
          JSON.stringify({ data, meta: { request_id: "request-1" } }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <App
        buildId="test-build"
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/auth/session",
        expect.objectContaining({ method: "GET" }),
      );
    });
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByText("2026-08-24T10:00:00.000Z"),
    ).toBeInTheDocument();

    releaseStoredGate();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("2026-08-24T10:00:00.000Z")).toBeInTheDocument();
    expect(
      screen.queryByText("2026-08-23T10:00:00.000Z"),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-073 removes Customer commands while logout is pending", async () => {
    let finishLogout!: () => void;
    const pendingLogout = new Promise<void>((resolve) => {
      finishLogout = resolve;
    });
    const authentication = mockAuthenticationApi({
      logout: vi.fn().mockReturnValue(pendingLogout),
    });
    render(
      <App
        api={authentication}
        buildId="test-build"
        customerApi={customerApiDouble()}
        environment="development"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByLabelText("Customer Property identifier");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(authentication.logout).toHaveBeenCalledOnce();
    expect(
      screen.queryByLabelText("Customer Property identifier"),
    ).not.toBeInTheDocument();
    finishLogout();
    await screen.findByLabelText("Username");
  });

  it("TEST-FE-024 ignores an older successful Property load after a newer authorization denial", async () => {
    let resolveFirstLoad!: (value: PropertyBusinessConfiguration) => void;
    const propertyApi = propertyApiDouble({
      load: vi
        .fn()
        .mockReturnValueOnce(
          new Promise<PropertyBusinessConfiguration>((resolve) => {
            resolveFirstLoad = resolve;
          }),
        )
        .mockRejectedValueOnce(new PropertyConfigurationUnavailableError()),
    });
    renderPropertyConfigurationApp(propertyApi);
    const propertyId = await signInAndLoadProperty();
    fireEvent.change(propertyId, { target: { value: "property-2" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Load business configuration" }),
    );
    expect(
      await screen.findByText(
        "Business configuration is not available for this session and property.",
      ),
    ).toBeInTheDocument();

    await act(async () => {
      resolveFirstLoad(configuredProperty);
      await Promise.resolve();
    });

    expect(
      screen.queryByRole("heading", { name: "Business configuration" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Property name")).not.toBeInTheDocument();
  });

  it("TEST-FE-025 clears loaded management controls when the Property identifier changes", async () => {
    const propertyApi = propertyApiDouble();
    renderPropertyConfigurationApp(propertyApi);
    const propertyId = await signInAndLoadProperty();
    expect(await screen.findByLabelText("Property name")).toBeInTheDocument();

    fireEvent.change(propertyId, { target: { value: "property-2" } });

    expectPropertyManagementHidden();
  });

  it("TEST-FE-026 ignores an in-flight Property load when the identifier changes", async () => {
    let resolveLoad!: (value: PropertyBusinessConfiguration) => void;
    const propertyApi = propertyApiDouble({
      load: vi.fn().mockReturnValue(
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          resolveLoad = resolve;
        }),
      ),
    });
    renderPropertyConfigurationApp(propertyApi);
    const propertyId = await signInAndLoadProperty();

    fireEvent.change(propertyId, { target: { value: "property-2" } });
    await act(async () => {
      resolveLoad(configuredProperty);
      await Promise.resolve();
    });

    expectPropertyManagementHidden();
  });
});

describe("financial panel session integration", () => {
  it.each([false, true])(
    "TEST-FE-498 removes financial access and aborts discovery during logout, delayed=%s",
    async (delayed) => {
      const actorId = "70000000-0000-4000-8000-000000000001",
        signedIn = { ...session, actor_id: actorId };
      let releaseDiscovery!: () => void, releaseLogout!: () => void;
      const discoveryGate = new Promise<void>((resolve) => {
          releaseDiscovery = resolve;
        }),
        logoutGate = new Promise<void>((resolve) => {
          releaseLogout = resolve;
        }),
        calls: {
          method: string | undefined;
          headers: Headers;
          signal: AbortSignal | null | undefined;
        }[] = [];
      const references = createFinancialReferenceClient(async (_url, init) => {
        const headers = new Headers(init?.headers);
        calls.push({ method: init?.method, headers, signal: init?.signal });
        if (delayed) await discoveryGate;
        const requestId = headers.get("X-Request-ID");
        return new Response(
          JSON.stringify({
            data: [],
            page: { limit: 100, next_cursor: null },
            meta: { actor_id: actorId, request_id: requestId },
          }),
          {
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId ?? "",
            },
          },
        );
      });
      const authentication = mockAuthenticationApi({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "authenticated", session: signedIn }),
        inspectSession: vi.fn().mockResolvedValue(signedIn),
        logout: vi.fn().mockReturnValue(logoutGate),
      });
      render(
        <App
          api={authentication}
          buildId="synthetic-financial-integration"
          environment="development"
          customerApi={customerApiDouble()}
          financialServices={{ ...defaultFinancialUiServices, references }}
          now={() => new Date("2026-08-22T10:10:00Z").getTime()}
        />,
      );
      expect(
        screen.queryByRole("heading", { name: "Financial records" }),
      ).toBeNull();
      fireEvent.change(screen.getByLabelText("Username"), {
        target: { value: "synthetic-manager" },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "synthetic-password" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await screen.findByRole("heading", { name: "Financial records" });
      await waitFor(() => {
        expect(calls).toHaveLength(1);
      });
      expect(calls[0]?.headers.get("X-Billing-Actor-ID")).toBe(actorId);
      expect(calls[0]?.method).toBe("GET");
      if (!delayed)
        await screen.findByText(
          "No financial Property access is available for this account.",
        );
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      expect(authentication.logout).toHaveBeenCalledOnce();
      expect(
        screen.queryByRole("heading", { name: "Financial records" }),
      ).toBeNull();
      expect(calls[0]?.signal?.aborted).toBe(true);
      await act(async () => {
        releaseDiscovery();
        await Promise.resolve();
      });
      expect(screen.queryByLabelText("Financial Property")).toBeNull();
      releaseLogout();
      await screen.findByLabelText("Username");
      expect(calls).toHaveLength(1);
    },
  );
});

describe("financial drafts during App logout and expiry", () => {
  it.each([false, true])(
    "TEST-FE-525 protects voluntary sign-out drafts and immediately clears forced expiry, forced=%s",
    async (forced) => {
      const actorId = "70000000-0000-4000-8000-000000000001",
        propertyId = "70000000-0000-4000-8000-000000000002",
        sourceId = "70000000-0000-4000-8000-000000000003",
        signedIn = { ...session, actor_id: actorId },
        grants = Object.fromEntries(
          FINANCIAL_CAPABILITIES.map((name) => [
            name,
            name === "refunds.create",
          ]),
        ),
        discard = vi.spyOn(window, "confirm").mockReturnValue(false);
      const calls: {
        method: string | undefined;
        signal: AbortSignal | null | undefined;
      }[] = [];
      const references = createFinancialReferenceClient((url, init) => {
        if (typeof url !== "string")
          throw new Error("Expected finite synthetic financial read");
        calls.push({ method: init?.method, signal: init?.signal });
        const headers = new Headers(init?.headers),
          requestId = headers.get("X-Request-ID"),
          workspace = url.includes("financial-workspaces");
        if (!workspace && !url.includes("financial-capabilities"))
          throw new Error("Unexpected financial request");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              data: workspace
                ? [
                    {
                      property_id: propertyId,
                      name: "Synthetic draft Property",
                      timezone: "Asia/Phnom_Penh",
                      capabilities: grants,
                    },
                  ]
                : { property_id: propertyId, capabilities: grants },
              ...(workspace ? { page: { limit: 100, next_cursor: null } } : {}),
              meta: {
                actor_id: actorId,
                request_id: requestId,
                ...(workspace ? {} : { property_id: propertyId }),
              },
            }),
            {
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": requestId ?? "",
              },
            },
          ),
        );
      });
      const recovery = {
        ...defaultFinancialUiServices.recovery,
        load: vi.fn(() => Promise.resolve({ kind: "ready" as const })),
        submit: vi.fn(() =>
          Promise.reject(new Error("Unexpected financial submission")),
        ),
      };
      let releaseLogout!: () => void;
      const logout = new Promise<void>((resolve) => {
        releaseLogout = resolve;
      });
      const authentication = mockAuthenticationApi({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "authenticated", session: signedIn }),
        inspectSession: vi.fn().mockResolvedValue(signedIn),
        logout: vi.fn().mockReturnValue(logout),
      });
      const props = {
        api: authentication,
        buildId: "synthetic-financial-drafts",
        environment: "development",
        customerApi: customerApiDouble(),
        financialServices: {
          ...defaultFinancialUiServices,
          references,
          recovery,
        },
      };
      try {
        const view = render(
          <App
            {...props}
            now={() => new Date("2026-08-22T10:10:00Z").getTime()}
          />,
        );
        fireEvent.change(screen.getByLabelText("Username"), {
          target: { value: "synthetic-manager" },
        });
        fireEvent.change(screen.getByLabelText("Password"), {
          target: { value: "synthetic-password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
        await screen.findByRole("heading", { name: "Financial records" });
        await screen.findByRole("option", { name: "Synthetic draft Property" });
        fireEvent.change(screen.getByLabelText("Financial Property"), {
          target: { value: propertyId },
        });
        const region = await screen.findByRole("region", {
          name: "Refund workspace",
        });
        fireEvent.change(within(region).getByLabelText("Source reference"), {
          target: { value: sourceId },
        });
        fireEvent.change(within(region).getByLabelText("Refund amount (USD)"), {
          target: { value: "123.45" },
        });
        fireEvent.change(within(region).getByLabelText("Reason"), {
          target: { value: "Synthetic unsent financial evidence" },
        });
        const signals = calls.map((call) => call.signal?.aborted);
        if (forced) {
          view.rerender(
            <App
              {...props}
              now={() => new Date("2026-08-24T10:10:00Z").getTime()}
            />,
          );
          await screen.findByLabelText("Username");
          expect(discard).not.toHaveBeenCalled();
          expect(authentication.logout).not.toHaveBeenCalled();
        } else {
          fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
          expect(discard).toHaveBeenCalledWith(
            "Discard unsaved financial form values and sign out?",
          );
          expect(authentication.logout).not.toHaveBeenCalled();
          expect(
            within(region).getByLabelText("Refund amount (USD)"),
          ).toHaveValue("123.45");
          expect(within(region).getByLabelText("Reason")).toHaveValue(
            "Synthetic unsent financial evidence",
          );
          expect(calls.map((call) => call.signal?.aborted)).toEqual(signals);
          discard.mockReturnValue(true);
          fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
          expect(authentication.logout).toHaveBeenCalledOnce();
          expect(
            screen.queryByRole("heading", { name: "Financial records" }),
          ).toBeNull();
          releaseLogout();
          await screen.findByLabelText("Username");
        }
        expect(
          screen.queryByDisplayValue("Synthetic unsent financial evidence"),
        ).toBeNull();
        expect(calls[0]?.signal?.aborted).toBe(true);
        expect(calls.every((call) => call.method === "GET")).toBe(true);
        expect(recovery.submit).not.toHaveBeenCalled();
        const unloaded = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(unloaded);
        expect(unloaded.defaultPrevented).toBe(false);
      } finally {
        discard.mockRestore();
        releaseLogout();
      }
    },
  );
});

describe("Customer ledger App integration", () => {
  it("TEST-FE-578 opens ledger from the Customer detail and aborts its read when logout begins, without replay after sign-in", async () => {
    const actorId = "00000000-0000-4000-8000-000000000001",
      customerId = "00000000-0000-4000-8000-000000000003",
      propertyId = "00000000-0000-4000-8000-000000000002";
    const signedIn = { ...session, actor_id: actorId };
    let releaseLogout!: () => void;
    const logout = new Promise<void>((resolve) => {
      releaseLogout = resolve;
    });
    const authentication = mockAuthenticationApi({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "authenticated", session: signedIn }),
      inspectSession: vi.fn().mockResolvedValue(signedIn),
      logout: vi.fn().mockReturnValue(logout),
    });
    const customerApi = customerApiDouble({
      list: vi.fn().mockResolvedValue({
        items: [
          {
            customer_id: customerId,
            legal_name: "Synthetic ledger Customer",
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: null,
        can_manage: false,
      }),
      get: vi.fn().mockResolvedValue({
        ...reconciledCustomer(customerId, "Synthetic ledger Customer"),
        can_manage: false,
        can_deactivate: false,
      }),
    });
    const read = vi.fn<
      import("./customerLedgerClient").CustomerLedgerApi["read"]
    >(
      () =>
        new Promise(() => {
          /* Synthetic noncooperating ledger read. */
        }),
    );
    render(
      <App
        api={authentication}
        buildId="synthetic-ledger-integration"
        environment="development"
        customerApi={customerApi}
        ledgerApi={{ read }}
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    const signIn = async () => {
      fireEvent.change(screen.getByLabelText("Username"), {
        target: { value: "synthetic-manager" },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "synthetic-password" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await screen.findByLabelText("Customer Property identifier");
    };
    await signIn();
    expect(read).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: propertyId },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Synthetic ledger Customer",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open account ledger" }),
    );
    await waitFor(() => {
      expect(read).toHaveBeenCalledTimes(1);
    });
    expect(read.mock.calls[0]?.[0]).toMatchObject({
      section: "history",
      customerId,
    });
    expect(read.mock.calls[0]?.[1]).toMatchObject({ actorId, propertyId });
    expect(customerApi.create).not.toHaveBeenCalled();
    expect(customerApi.update).not.toHaveBeenCalled();
    expect(customerApi.deactivate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(read.mock.calls[0]?.[1].signal.aborted).toBe(true);
    expect(
      screen.queryByRole("heading", { name: "Customer account ledger" }),
    ).not.toBeInTheDocument();
    releaseLogout();
    await screen.findByLabelText("Username");
    await signIn();
    expect(read).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Open Customer account ledger" }),
    ).toBeInTheDocument();
  });
});

describe("Lease enforcement drafts during App logout and expiry", () => {
  it.each([false, true])(
    "TEST-FE-614 protects unsaved enforcement values and invalidates forced expiry, forced=%s",
    async (forced) => {
      const signedIn = { ...session, actor_id: enforcementIds.actor };
      const discard = vi.spyOn(window, "confirm").mockReturnValue(false);
      const read = vi.fn<EnforcementClient["read"]>(async (scope, input) =>
        Promise.resolve({
          data: enforcementReadData(input, false, ["leases.warn"]),
          actorId: scope.actorId,
          propertyId: scope.propertyId,
          requestId: crypto.randomUUID(),
        }),
      );
      const reads: EnforcementClient = { read };
      const recovery = {
        ...defaultEnforcementServices.recovery,
        load: vi.fn(() => Promise.resolve({ kind: "ready" as const })),
        submit: vi.fn(() =>
          Promise.reject(new Error("Unexpected enforcement submission")),
        ),
      };
      let releaseLogout!: () => void;
      const logout = new Promise<void>((resolve) => {
        releaseLogout = resolve;
      });
      const authentication = mockAuthenticationApi({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "authenticated", session: signedIn }),
        inspectSession: vi.fn().mockResolvedValue(signedIn),
        logout: vi.fn().mockReturnValue(logout),
      });
      const props = {
        api: authentication,
        buildId: "synthetic-enforcement-drafts",
        environment: "development",
        customerApi: customerApiDouble(),
        enforcementServices: { reads, recovery },
      };
      try {
        const view = render(
          <App
            {...props}
            now={() => new Date("2026-08-22T10:10:00Z").getTime()}
          />,
        );
        fireEvent.change(screen.getByLabelText("Username"), {
          target: { value: "synthetic-manager" },
        });
        fireEvent.change(screen.getByLabelText("Password"), {
          target: { value: "synthetic-password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
        await screen.findByRole("option", { name: "Synthetic River Property" });
        fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
          target: { value: enforcementIds.property },
        });
        await screen.findByRole("option", { name: /SYNTHETIC-A1/ });
        fireEvent.change(screen.getByLabelText("Lease for general warnings"), {
          target: { value: enforcementIds.lease },
        });
        const form = await screen.findByRole("form", {
          name: "Record Lease warning",
        });
        fireEvent.change(within(form).getByLabelText("Violation description"), {
          target: { value: "Synthetic unsent Lease evidence" },
        });
        const calls = read.mock.calls;
        if (forced) {
          view.rerender(
            <App
              {...props}
              now={() => new Date("2026-08-24T10:10:00Z").getTime()}
            />,
          );
          await screen.findByLabelText("Username");
          expect(discard).not.toHaveBeenCalled();
          expect(authentication.logout).not.toHaveBeenCalled();
        } else {
          fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
          expect(discard).toHaveBeenCalledWith(
            "Discard unsaved Lease warning or nonpayment form values and sign out?",
          );
          expect(authentication.logout).not.toHaveBeenCalled();
          expect(
            within(form).getByLabelText("Violation description"),
          ).toHaveValue("Synthetic unsent Lease evidence");
          discard.mockReturnValue(true);
          fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
          expect(authentication.logout).toHaveBeenCalledOnce();
          expect(
            screen.queryByLabelText("Lease enforcement Property"),
          ).not.toBeInTheDocument();
          releaseLogout();
          await screen.findByLabelText("Username");
        }
        expect(
          screen.queryByDisplayValue("Synthetic unsent Lease evidence"),
        ).not.toBeInTheDocument();
        expect(calls[0]?.[0].signal.aborted).toBe(true);
        expect(recovery.submit).not.toHaveBeenCalled();
      } finally {
        releaseLogout();
        discard.mockRestore();
      }
    },
  );
});
