import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationApi,
  AuthenticationData,
  LocalSignIn,
  MfaEnrollmentData,
  MfaMethod,
  PASSWORD_RULE_MESSAGE,
  PasswordRuleError,
  RecoveryCodeSetData,
  SessionData,
  authenticationApi,
  signIn,
} from "./authClient";
import {
  AccessAdministrationApi,
  AccessAdministrationSnapshot,
  AdministrationUnavailableError,
  UserAccount,
  accessAdministrationApi,
} from "./adminClient";
import {
  PropertyBusinessConfiguration,
  PropertyConfigurationApi,
  PropertyConfigurationUnavailableError,
  propertyConfigurationApi,
} from "./propertyClient";
import { UnitManagement } from "./UnitManagement";
import { UnitApi } from "./unitClient";
import {
  CustomerManagement,
  CustomerReconciliationRequirement,
} from "./CustomerManagement";
import { CustomerApi } from "./customerClient";
import { ConfigurationManagement } from "./ConfigurationManagement";
import {
  EffectiveConfigurationApi,
  effectiveConfigurationApi,
} from "./configurationClient";
import { ReservationManagement } from "./ReservationManagement";
import {
  ReservationApi,
  reservationApi as reservationClient,
} from "./reservationClient";
import { LeaseManagement } from "./LeaseManagement";
import { LeaseApi, leaseApi as leaseClient } from "./leaseClient";
import { DepositManagement } from "./DepositManagement";
import { DepositApi, depositApi as depositClient } from "./depositClient";
import { UtilityManagement } from "./UtilityManagement";
import { UtilityLeaseWorkflows } from "./UtilityLeaseWorkflows";
import { UtilityApi, utilityApi as utilityClient } from "./utilityClient";
import { InvoiceManagement } from "./InvoiceManagement";
import { InvoiceApi, invoiceApi as invoiceClient } from "./invoiceClient";
import { LeaseEnforcementManagement } from "./LeaseEnforcementManagement";
import type { EnforcementServices } from "./leaseEnforcementUi";
import { FinancialManagement } from "./FinancialManagement";
import type { FinancialUiServices } from "./financialUi";
import {
  CustomerAccountLedger,
  type LedgerSelection,
} from "./CustomerAccountLedger";
import type { CustomerLedgerApi } from "./customerLedgerClient";

export interface AppProps {
  environment: string;
  buildId: string;
  authenticate?: LocalSignIn;
  api?: AuthenticationApi;
  administrationApi?: AccessAdministrationApi;
  propertyApi?: PropertyConfigurationApi;
  unitApi?: UnitApi;
  customerApi?: CustomerApi;
  effectiveConfigApi?: EffectiveConfigurationApi;
  reservationApi?: ReservationApi;
  leaseApi?: LeaseApi;
  depositApi?: DepositApi;
  utilityApi?: UtilityApi;
  invoiceApi?: InvoiceApi;
  financialServices?: FinancialUiServices;
  enforcementServices?: EnforcementServices;
  ledgerApi?: CustomerLedgerApi;
  now?: () => number;
}

type SubmissionState = "idle" | "submitting" | "succeeded" | "failed";
type Screen =
  | "sign_in"
  | "mfa_required"
  | "mfa_enrollment_required"
  | "password_change_required"
  | "authenticated";

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unavailable" : parsed.toISOString();
}

const PASSWORD_CHANGE_NOT_FINISHED =
  "The password change did not finish. Sign in with your new password. If it is not accepted, sign in with your one-time password.";

function phaseScreen(result: AuthenticationData): Screen {
  return result.phase;
}

const CUSTOMER_RECONCILIATION_STORAGE_KEY =
  "property-rental.customer-reconciliation.v2";
const CUSTOMER_RECONCILIATION_DATABASE =
  "property-rental.customer-reconciliation.v1";
const CUSTOMER_RECONCILIATION_KEY_STORE = "non-extractable-keys";
const CUSTOMER_RECONCILIATION_KEY_ID = "customer-command-gate-v1";
const CUSTOMER_RECONCILIATION_SEALED_PREFIX = `${CUSTOMER_RECONCILIATION_STORAGE_KEY}.sealed.`;

interface SealedCustomerReconciliation {
  ciphertext: string;
  iv: string;
  version: 1;
}

let customerReconciliationDatabase: Promise<IDBDatabase> | null = null;

function openCustomerReconciliationDatabase(): Promise<IDBDatabase> {
  if (customerReconciliationDatabase !== null) {
    return customerReconciliationDatabase;
  }
  customerReconciliationDatabase = new Promise((resolve, reject) => {
    const request = window.indexedDB.open(CUSTOMER_RECONCILIATION_DATABASE, 1);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (
        !database.objectStoreNames.contains(CUSTOMER_RECONCILIATION_KEY_STORE)
      ) {
        database.createObjectStore(CUSTOMER_RECONCILIATION_KEY_STORE);
      }
    };
    request.onerror = () => {
      customerReconciliationDatabase = null;
      reject(
        request.error ??
          new Error("Customer coordination database unavailable"),
      );
    };
    request.onsuccess = () => {
      request.result.onversionchange = () => {
        request.result.close();
        customerReconciliationDatabase = null;
      };
      resolve(request.result);
    };
  });
  return customerReconciliationDatabase;
}

function databaseRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onerror = () => {
      reject(request.error ?? new Error("Browser storage failed"));
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
  });
}

function databaseTransactionCommitted(
  transaction: IDBTransaction,
): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.onabort = () => {
      reject(
        transaction.error ?? new Error("Browser storage transaction aborted"),
      );
    };
    transaction.onerror = () => {
      reject(
        transaction.error ?? new Error("Browser storage transaction failed"),
      );
    };
    transaction.oncomplete = () => {
      resolve();
    };
  });
}

async function customerReconciliationKey(): Promise<CryptoKey> {
  const database = await openCustomerReconciliationDatabase();
  const read = database.transaction(
    CUSTOMER_RECONCILIATION_KEY_STORE,
    "readonly",
  );
  const existing = await databaseRequest<unknown>(
    read
      .objectStore(CUSTOMER_RECONCILIATION_KEY_STORE)
      .get(CUSTOMER_RECONCILIATION_KEY_ID),
  );
  if (existing !== undefined) return existing as CryptoKey;
  const created = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  const write = database.transaction(
    CUSTOMER_RECONCILIATION_KEY_STORE,
    "readwrite",
  );
  const committed = databaseTransactionCommitted(write);
  await databaseRequest(
    write
      .objectStore(CUSTOMER_RECONCILIATION_KEY_STORE)
      .put(created, CUSTOMER_RECONCILIATION_KEY_ID),
  );
  await committed;
  return created;
}

function encodeBytes(value: ArrayBuffer | Uint8Array): string {
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return window.btoa(binary);
}

function decodeBytes(value: string): Uint8Array<ArrayBuffer> {
  const binary = window.atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function sealCustomerReconciliation(
  requirement: CustomerReconciliationRequirement,
): Promise<string> {
  const key = await customerReconciliationKey();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(JSON.stringify(requirement)),
  );
  return JSON.stringify({
    ciphertext: encodeBytes(ciphertext),
    iv: encodeBytes(iv),
    version: 1,
  } satisfies SealedCustomerReconciliation);
}

async function unsealCustomerReconciliation(value: string): Promise<unknown> {
  const sealed: unknown = JSON.parse(value);
  if (
    typeof sealed !== "object" ||
    sealed === null ||
    !("version" in sealed) ||
    sealed.version !== 1 ||
    !("iv" in sealed) ||
    typeof sealed.iv !== "string" ||
    !("ciphertext" in sealed) ||
    typeof sealed.ciphertext !== "string"
  ) {
    throw new Error("Invalid Customer coordination envelope");
  }
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: decodeBytes(sealed.iv) },
    await customerReconciliationKey(),
    decodeBytes(sealed.ciphertext),
  );
  return JSON.parse(new TextDecoder().decode(plaintext)) as unknown;
}

function isStoredCustomerSource(
  value: unknown,
  requireLegalName = true,
): boolean {
  if (typeof value !== "object" || value === null) return false;
  const source = value as Record<string, unknown>;
  if (
    (requireLegalName && typeof source.legal_name !== "string") ||
    (!requireLegalName &&
      "legal_name" in source &&
      typeof source.legal_name !== "string")
  )
    return false;
  for (const field of [
    "phone_number",
    "email_address",
    "contact_address",
    "memo",
  ]) {
    if (
      field in source &&
      source[field] !== null &&
      typeof source[field] !== "string"
    ) {
      return false;
    }
  }
  return (
    !("confirmed_distinct" in source) ||
    typeof source.confirmed_distinct === "boolean"
  );
}

type StoredCustomerReconciliation =
  | { status: "empty"; requirement: null }
  | { status: "valid"; requirement: CustomerReconciliationRequirement }
  | { status: "invalid" | "unavailable"; requirement: null };

async function readStoredCustomerReconciliation(
  actorId: string,
): Promise<StoredCustomerReconciliation> {
  let value: string | null;
  try {
    const opaqueHandle = window.localStorage.getItem(
      CUSTOMER_RECONCILIATION_STORAGE_KEY,
    );
    if (opaqueHandle === null) return { status: "empty", requirement: null };
    if (!/^[0-9a-f-]{36}$/i.test(opaqueHandle)) {
      return { status: "invalid", requirement: null };
    }
    value = window.localStorage.getItem(
      `${CUSTOMER_RECONCILIATION_SEALED_PREFIX}${opaqueHandle}`,
    );
  } catch {
    return { status: "unavailable", requirement: null };
  }
  if (value === null) return { status: "unavailable", requirement: null };
  try {
    const parsed = await unsealCustomerReconciliation(value);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("actorId" in parsed) ||
      !("commandNonce" in parsed) ||
      !("kind" in parsed) ||
      !("customerId" in parsed) ||
      !("propertyId" in parsed) ||
      !("resultFingerprint" in parsed) ||
      !("requestFingerprint" in parsed) ||
      !["create", "update", "deactivate"].includes(String(parsed.kind)) ||
      parsed.actorId !== actorId ||
      typeof parsed.commandNonce !== "string" ||
      parsed.commandNonce.length === 0 ||
      typeof parsed.customerId !== "string" ||
      parsed.customerId.length === 0 ||
      typeof parsed.propertyId !== "string" ||
      parsed.propertyId.length === 0 ||
      typeof parsed.requestFingerprint !== "string" ||
      !/^[0-9a-f]{64}$/.test(parsed.requestFingerprint) ||
      typeof parsed.resultFingerprint !== "string" ||
      !/^[0-9a-f]{64}$/.test(parsed.resultFingerprint) ||
      ("expectedVersion" in parsed &&
        (typeof parsed.expectedVersion !== "number" ||
          !Number.isInteger(parsed.expectedVersion) ||
          parsed.expectedVersion < 1)) ||
      ("createSource" in parsed &&
        !isStoredCustomerSource(parsed.createSource)) ||
      ("updateSource" in parsed &&
        !isStoredCustomerSource(parsed.updateSource, false)) ||
      ("deactivationReason" in parsed &&
        typeof parsed.deactivationReason !== "string")
    ) {
      return { status: "invalid", requirement: null };
    }
    return {
      status: "valid",
      requirement: parsed as CustomerReconciliationRequirement,
    };
  } catch {
    return { status: "invalid", requirement: null };
  }
}

async function persistCustomerReconciliation(
  requirement: CustomerReconciliationRequirement | null,
): Promise<boolean> {
  try {
    if (requirement === null) {
      const opaqueHandle = window.localStorage.getItem(
        CUSTOMER_RECONCILIATION_STORAGE_KEY,
      );
      window.localStorage.removeItem(CUSTOMER_RECONCILIATION_STORAGE_KEY);
      if (opaqueHandle !== null) {
        try {
          window.localStorage.removeItem(
            `${CUSTOMER_RECONCILIATION_SEALED_PREFIX}${opaqueHandle}`,
          );
        } catch {
          // The active gate is already cleared. An unreachable sealed orphan is
          // preferable to restoring a dangling handle that blocks all commands.
        }
      }
    } else {
      const sealed = await sealCustomerReconciliation(requirement);
      window.localStorage.setItem(
        `${CUSTOMER_RECONCILIATION_SEALED_PREFIX}${requirement.commandNonce}`,
        sealed,
      );
      window.localStorage.setItem(
        CUSTOMER_RECONCILIATION_STORAGE_KEY,
        requirement.commandNonce,
      );
    }
    return true;
  } catch {
    return false;
  }
}

interface CustomerReconciliationReservation {
  existing: CustomerReconciliationRequirement | null;
  reserved: boolean;
  storageAvailable: boolean;
}

function sameCustomerReconciliation(
  left: CustomerReconciliationRequirement | null,
  right: CustomerReconciliationRequirement | null,
): boolean {
  return (
    left !== null &&
    right !== null &&
    left.actorId === right.actorId &&
    left.commandNonce === right.commandNonce &&
    left.kind === right.kind &&
    left.customerId === right.customerId &&
    left.propertyId === right.propertyId &&
    left.resultFingerprint === right.resultFingerprint &&
    left.requestFingerprint === right.requestFingerprint &&
    left.expectedVersion === right.expectedVersion
  );
}

export async function reserveCustomerReconciliation(
  requirement: CustomerReconciliationRequirement,
): Promise<CustomerReconciliationReservation> {
  const lockManager = Reflect.get(navigator, "locks") as
    | LockManager
    | undefined;
  if (lockManager === undefined) {
    return { existing: null, reserved: false, storageAvailable: false };
  }
  try {
    return await lockManager.request(
      `${CUSTOMER_RECONCILIATION_STORAGE_KEY}.lock`,
      { mode: "exclusive" },
      async () => {
        const stored = await readStoredCustomerReconciliation(
          requirement.actorId,
        );
        if (stored.status === "unavailable" || stored.status === "invalid") {
          return {
            existing: null,
            reserved: false,
            storageAvailable: false,
          };
        }
        if (stored.requirement !== null) {
          if (sameCustomerReconciliation(stored.requirement, requirement)) {
            return {
              existing: null,
              reserved: true,
              storageAvailable: true,
            };
          }
          return {
            existing: stored.requirement,
            reserved: false,
            storageAvailable: true,
          };
        }
        const reserved = await persistCustomerReconciliation(requirement);
        return {
          existing: null,
          reserved,
          storageAvailable: reserved,
        };
      },
    );
  } catch {
    return { existing: null, reserved: false, storageAvailable: false };
  }
}

type CustomerReconciliationClearance =
  | { status: "cleared" }
  | {
      status: "superseded";
      requirement: CustomerReconciliationRequirement | null;
    }
  | { status: "unavailable" };

export async function clearCustomerReconciliation(
  requirement: CustomerReconciliationRequirement,
): Promise<CustomerReconciliationClearance> {
  const lockManager = Reflect.get(navigator, "locks") as
    | LockManager
    | undefined;
  if (lockManager === undefined) return { status: "unavailable" };
  try {
    return await lockManager.request(
      `${CUSTOMER_RECONCILIATION_STORAGE_KEY}.lock`,
      { mode: "exclusive" },
      async () => {
        const stored = await readStoredCustomerReconciliation(
          requirement.actorId,
        );
        if (stored.status === "unavailable" || stored.status === "invalid") {
          return { status: "unavailable" } as const;
        }
        if (!sameCustomerReconciliation(stored.requirement, requirement)) {
          return {
            status: "superseded",
            requirement: stored.requirement,
          } as const;
        }
        return (await persistCustomerReconciliation(null))
          ? ({ status: "cleared" } as const)
          : ({ status: "unavailable" } as const);
      },
    );
  } catch {
    return { status: "unavailable" };
  }
}

export function App({
  environment,
  buildId,
  authenticate = signIn,
  api,
  administrationApi = accessAdministrationApi,
  propertyApi = propertyConfigurationApi,
  unitApi,
  customerApi,
  effectiveConfigApi = effectiveConfigurationApi,
  reservationApi = reservationClient,
  leaseApi = leaseClient,
  depositApi = depositClient,
  utilityApi = utilityClient,
  invoiceApi = invoiceClient,
  financialServices,
  enforcementServices,
  ledgerApi,
  now = Date.now,
}: AppProps) {
  const client = useMemo<AuthenticationApi>(
    () => api ?? { ...authenticationApi, signIn: authenticate },
    [api, authenticate],
  );
  const [screen, setScreen] = useState<Screen>("sign_in");
  const [session, setSession] = useState<SessionData | null>(null);
  const [submissionState, setSubmissionState] =
    useState<SubmissionState>("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const [enrollment, setEnrollment] = useState<MfaEnrollmentData | null>(null);
  const [recoveryCodes, setRecoveryCodes] =
    useState<RecoveryCodeSetData | null>(null);
  const [mfaMethod, setMfaMethod] = useState<MfaMethod>("totp");
  const [showReauthentication, setShowReauthentication] = useState(false);
  const [administration, setAdministration] =
    useState<AccessAdministrationSnapshot | null>(null);
  const [administrationStatus, setAdministrationStatus] = useState<
    string | null
  >(null);
  // Login sub-slice L4: the one-time password the server made, shown once to the Owner.
  const [issuedPassword, setIssuedPassword] = useState<{
    username: string;
    value: string;
    expires_at: string;
  } | null>(null);
  const [passwordRuleRefused, setPasswordRuleRefused] = useState(false);
  const [propertyId, setPropertyId] = useState("");
  const [configurationPropertyId, setConfigurationPropertyId] = useState("");
  const [propertyConfiguration, setPropertyConfiguration] =
    useState<PropertyBusinessConfiguration | null>(null);
  const [propertyConfigurationStatus, setPropertyConfigurationStatus] =
    useState<string | null>(null);
  const [propertyConfigurationAuthorized, setPropertyConfigurationAuthorized] =
    useState(false);
  const [customerDraftsDirty, setCustomerDraftsDirty] = useState(false);
  const [financialDraftsDirty, setFinancialDraftsDirty] = useState(false);
  const [enforcementDraftsDirty, setEnforcementDraftsDirty] = useState(false);
  const [customerCommandBusy, setCustomerCommandBusy] = useState(false);
  const [customerCoordinationAvailable, setCustomerCoordinationAvailable] =
    useState(true);
  const [logoutPending, setLogoutPending] = useState(false);
  const [ledgerSelection, setLedgerSelection] = useState<
    (LedgerSelection & { actorId: string; sequence: number }) | null
  >(null);
  const ledgerSequence = useRef(0);
  const [
    customerReconciliationRequirement,
    setCustomerReconciliationRequirement,
  ] = useState<CustomerReconciliationRequirement | null>(null);
  const propertyOperationSequence = useRef(0);
  const authenticationOperationSequence = useRef(0);
  const customerStorageEventSequence = useRef(0);
  const [pendingCommand, setPendingCommand] = useState<{
    kind: "disable" | "revoke" | "recover";
    user: UserAccount;
    recovery?: { reset_mfa: boolean; reason: string };
  } | null>(null);

  useEffect(() => {
    if (session === null) return;
    const actorId = session.actor_id;
    function synchronizeCustomerGate(event: StorageEvent) {
      if (event.key !== CUSTOMER_RECONCILIATION_STORAGE_KEY) return;
      const eventSequence = ++customerStorageEventSequence.current;
      void readStoredCustomerReconciliation(actorId).then((stored) => {
        if (eventSequence !== customerStorageEventSequence.current) return;
        if (stored.status === "unavailable" || stored.status === "invalid") {
          setCustomerCoordinationAvailable(false);
          setNotice(
            "Customer command coordination is unavailable. Commands remain blocked until durable reconciliation storage is restored.",
          );
          return;
        }
        const reconciliation = stored.requirement;
        setCustomerCoordinationAvailable(true);
        setCustomerReconciliationRequirement(reconciliation);
        if (reconciliation !== null) {
          setNotice(
            "A Customer command outcome is unknown in another tab. Verify its exact result before retrying.",
          );
        } else {
          setNotice(
            "The Customer reconciliation gate was resolved in another tab.",
          );
        }
      });
    }
    window.addEventListener("storage", synchronizeCustomerGate);
    return () => {
      customerStorageEventSequence.current += 1;
      window.removeEventListener("storage", synchronizeCustomerGate);
    };
  }, [session]);

  function invalidatePropertyConfiguration() {
    propertyOperationSequence.current += 1;
    setPropertyConfiguration(null);
    setPropertyConfigurationAuthorized(false);
  }

  async function acceptAuthentication(
    result: AuthenticationData,
    operation = ++authenticationOperationSequence.current,
  ) {
    const stored =
      result.phase === "authenticated" && result.session !== null
        ? await readStoredCustomerReconciliation(result.session.actor_id)
        : ({ status: "empty", requirement: null } as const);
    if (operation !== authenticationOperationSequence.current) return;
    const reconciliation = stored.requirement;
    invalidatePropertyConfiguration();
    setPropertyConfigurationStatus(null);
    setSession(result.session);
    setCustomerCoordinationAvailable(
      stored.status !== "unavailable" && stored.status !== "invalid",
    );
    setCustomerReconciliationRequirement(reconciliation);
    setScreen(phaseScreen(result));
    setSubmissionState("succeeded");
    setNotice(
      result.phase !== "authenticated"
        ? null
        : stored.status === "unavailable" || stored.status === "invalid"
          ? "Customer command coordination is unavailable. Customer commands remain blocked without exposing another actor's reconciliation metadata."
          : reconciliation !== null
            ? "A Customer command outcome is unknown. Reload the applicable Customer list and verify the result before retrying."
            : "Your sign-in was accepted.",
    );
  }

  function returnToSignIn(message: string | null) {
    setEnforcementDraftsDirty(false);
    setFinancialDraftsDirty(false);
    setCustomerDraftsDirty(false);
    setCustomerCommandBusy(false);
    setCustomerReconciliationRequirement(null);
    setLogoutPending(false);
    setLedgerSelection(null);
    setScreen("sign_in");
    setSession(null);
    setEnrollment(null);
    setRecoveryCodes(null);
    setIssuedPassword(null);
    setPasswordRuleRefused(false);
    invalidatePropertyConfiguration();
    setPropertyConfigurationStatus(null);
    setSubmissionState("idle");
    setShowReauthentication(false);
    setNotice(message);
  }

  useEffect(() => {
    if (api !== undefined || authenticate !== signIn) return;
    let active = true;
    const operation = ++authenticationOperationSequence.current;
    void client
      .inspectSession()
      .then(async (restored) => {
        const stored = await readStoredCustomerReconciliation(
          restored.actor_id,
        );
        if (!active || operation !== authenticationOperationSequence.current) {
          return;
        }
        setSession(restored);
        setCustomerCoordinationAvailable(
          stored.status !== "unavailable" && stored.status !== "invalid",
        );
        setCustomerReconciliationRequirement(stored.requirement);
        setScreen("authenticated");
      })
      .catch(() => {
        // A missing or expired cookie is the normal anonymous state.
      });
    return () => {
      active = false;
    };
  }, [api, authenticate, client]);

  useEffect(() => {
    if (screen !== "authenticated" || session === null) {
      return;
    }
    const expiresAt = Math.min(
      new Date(session.idle_expires_at).getTime(),
      new Date(session.absolute_expires_at).getTime(),
    );
    const delay = Math.min(2_147_483_647, Math.max(0, expiresAt - now()));
    const timer = window.setTimeout(() => {
      returnToSignIn(
        customerCommandBusy || customerReconciliationRequirement !== null
          ? "Your session expired while a Customer command was pending. Its outcome is unknown; sign in, reload Customers, and reconcile before retrying."
          : "Your session expired. Any unsaved command was not submitted. Sign in again to continue.",
      );
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [
    customerCommandBusy,
    customerReconciliationRequirement,
    now,
    screen,
    session,
  ]);

  function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const username = formData.get("username");
    const password = formData.get("password");

    setNotice(null);
    setSubmissionState("submitting");
    const operation = ++authenticationOperationSequence.current;
    void client
      .signIn({
        username: typeof username === "string" ? username : "",
        password: typeof password === "string" ? password : "",
      })
      .then((result) => {
        if (result.phase === "authenticated") {
          form.reset();
        }
        void acceptAuthentication(result, operation);
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleMfaChallenge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const code = data.get("mfa-code");
    setSubmissionState("submitting");
    void client
      .completeMfa({
        method: mfaMethod,
        code: typeof code === "string" ? code : "",
      })
      .then((result) => acceptAuthentication(result))
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handlePasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const newPassword = data.get("new-password");
    const repeated = data.get("new-password-again");
    setPasswordRuleRefused(false);
    if (
      typeof newPassword !== "string" ||
      newPassword.length === 0 ||
      newPassword !== repeated
    ) {
      setSubmissionState("failed");
      return;
    }
    setSubmissionState("submitting");
    void client
      .changePassword(newPassword)
      .then((result) => acceptAuthentication(result))
      .catch((error: unknown) => {
        if (error instanceof PasswordRuleError) {
          setPasswordRuleRefused(true);
          setSubmissionState("idle");
        } else {
          // The change may have been saved before a later step failed (review round 1), so
          // the person is told to try the new password first.
          returnToSignIn(PASSWORD_CHANGE_NOT_FINISHED);
        }
      });
  }

  function beginEnrollment() {
    setSubmissionState("submitting");
    void client
      .beginMfaEnrollment()
      .then((result) => {
        setEnrollment(result);
        setSubmissionState("idle");
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function confirmEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const code = data.get("enrollment-code");
    setSubmissionState("submitting");
    void client
      .confirmMfaEnrollment(typeof code === "string" ? code : "")
      .then((result) => {
        setEnrollment(null);
        void acceptAuthentication(result);
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleReauthentication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = data.get("reauth-password");
    const code = data.get("reauth-code");
    setSubmissionState("submitting");
    void client
      .reauthenticate({
        password: typeof password === "string" ? password : "",
        ...(typeof code === "string" && code.length > 0
          ? { second_factor: { method: "totp" as const, code } }
          : {}),
      })
      .then((result) => {
        invalidatePropertyConfiguration();
        setPropertyConfigurationStatus(null);
        setSession(result);
        setShowReauthentication(false);
        setSubmissionState("succeeded");
        setNotice(
          "Recent authentication confirmed for protected administration.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleLogout() {
    if (
      customerDraftsDirty &&
      !window.confirm(
        customerCommandBusy
          ? "A Customer command is still pending and its outcome will be unknown. Discard other unsaved Customer values and sign out?"
          : "Discard unsaved Customer form values and sign out?",
      )
    ) {
      setNotice(
        "Sign out was cancelled; unsaved Customer values were preserved.",
      );
      return;
    }
    if (
      financialDraftsDirty &&
      !window.confirm("Discard unsaved financial form values and sign out?")
    ) {
      setNotice(
        "Sign out was cancelled; unsaved financial values were preserved.",
      );
      return;
    }
    if (
      enforcementDraftsDirty &&
      !window.confirm(
        "Discard unsaved Lease warning or nonpayment form values and sign out?",
      )
    ) {
      setNotice(
        "Sign out was cancelled; unsaved Lease enforcement values were preserved.",
      );
      return;
    }
    setEnforcementDraftsDirty(false);
    setFinancialDraftsDirty(false);
    setCustomerDraftsDirty(false);
    setLogoutPending(true);
    setLedgerSelection(null);
    setSubmissionState("submitting");
    void client
      .logout()
      .then(() => {
        returnToSignIn("You signed out.");
      })
      .catch(() => {
        returnToSignIn(
          "Your local session was cleared. Sign in again to continue.",
        );
      });
  }

  function issueRecoveryCodes() {
    setSubmissionState("submitting");
    void client
      .issueRecoveryCodes()
      .then((result) => {
        setRecoveryCodes(result);
        setSubmissionState("succeeded");
        setNotice(
          "Recovery codes were generated. Save them now; they will not be shown again.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
        setNotice("Recovery codes could not be generated.");
      });
  }

  function regenerateRecoveryCodes() {
    if (recoveryCodes === null) return;
    setSubmissionState("submitting");
    void client
      .regenerateRecoveryCodes(recoveryCodes.set_id)
      .then((result) => {
        setRecoveryCodes(result);
        setSubmissionState("succeeded");
        setNotice(
          "The prior recovery-code set was invalidated. Save this replacement set now.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
        setNotice("Recovery codes could not be replaced.");
      });
  }

  function loadPropertyConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const operationSequence = ++propertyOperationSequence.current;
    setPropertyConfigurationStatus(
      "Checking server-authorized business configuration access…",
    );
    void propertyApi
      .load(configurationPropertyId)
      .then((result) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        setPropertyConfiguration(result);
        setPropertyConfigurationAuthorized(true);
        setPropertyConfigurationStatus(
          "Business configuration loaded from the authoritative server state.",
        );
      })
      .catch((error: unknown) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        invalidatePropertyConfiguration();
        setPropertyConfigurationStatus(
          error instanceof PropertyConfigurationUnavailableError
            ? "Business configuration is not available for this session and property."
            : "Business configuration could not be loaded.",
        );
      });
  }

  function updatePropertySource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (propertyConfiguration === null) return;
    const operationSequence = ++propertyOperationSequence.current;
    const data = new FormData(event.currentTarget);
    const name = data.get("property-name");
    const address = data.get("property-address");
    setPropertyConfigurationStatus(
      "Submitting the version-checked Property update…",
    );
    void propertyApi
      .updateSource(propertyConfiguration, {
        name: typeof name === "string" ? name : "",
        address_text:
          typeof address === "string" && address.trim().length > 0
            ? address
            : null,
      })
      .then((result) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        setPropertyConfiguration(result);
        setPropertyConfigurationStatus("Property source data updated.");
      })
      .catch((error: unknown) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        if (error instanceof PropertyConfigurationUnavailableError) {
          invalidatePropertyConfiguration();
          setPropertyConfigurationStatus(
            "Business configuration is not available for this session and property.",
          );
          return;
        }
        setPropertyConfigurationStatus(
          "The Property update was not completed. Reload before retrying.",
        );
      });
  }

  function addPaymentMethod(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (propertyConfiguration === null) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const code = data.get("payment-method-code");
    const displayName = data.get("payment-method-name");
    if (typeof code !== "string" || typeof displayName !== "string") return;
    const normalizedCode = code.trim();
    if (
      normalizedCode.length === 0 ||
      displayName.trim().length === 0 ||
      propertyConfiguration.payment_methods.some(
        (method) => method.code === normalizedCode,
      )
    ) {
      setPropertyConfigurationStatus(
        "Payment Method code and name must be nonblank, and the code must be unique.",
      );
      return;
    }
    setPropertyConfiguration({
      ...propertyConfiguration,
      payment_methods: [
        ...propertyConfiguration.payment_methods,
        {
          code: normalizedCode,
          display_name: displayName.trim(),
          accepted: true,
        },
      ],
    });
    setPropertyConfigurationStatus(
      "Payment Method added locally. Save the configuration to make it authoritative.",
    );
    form.reset();
  }

  function savePaymentMethods() {
    if (propertyConfiguration === null) return;
    const operationSequence = ++propertyOperationSequence.current;
    setPropertyConfigurationStatus(
      "Submitting the version-checked Payment Method configuration…",
    );
    void propertyApi
      .updatePaymentMethods(
        propertyConfiguration,
        propertyConfiguration.payment_methods,
      )
      .then((result) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        setPropertyConfiguration(result);
        setPropertyConfigurationStatus("Payment Method configuration updated.");
      })
      .catch((error: unknown) => {
        if (operationSequence !== propertyOperationSequence.current) return;
        if (error instanceof PropertyConfigurationUnavailableError) {
          invalidatePropertyConfiguration();
          setPropertyConfigurationStatus(
            "Business configuration is not available for this session and property.",
          );
          return;
        }
        setPropertyConfigurationStatus(
          "The Payment Method update was not completed. Reload before retrying.",
        );
      });
  }

  function loadAdministration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // L4 review round 2: a one-time password never stays beside another property's users.
    setIssuedPassword(null);
    setAdministrationStatus(
      "Checking server-authorized administration access…",
    );
    void administrationApi
      .load(propertyId)
      .then((result) => {
        setAdministration(result);
        setAdministrationStatus(
          "Administration access confirmed by the server.",
        );
      })
      .catch((error: unknown) => {
        setAdministration(null);
        setAdministrationStatus(
          error instanceof AdministrationUnavailableError
            ? "Administration is not available for this session and property."
            : "Administration data could not be loaded.",
        );
      });
  }

  function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => {
      const field = data.get(name);
      return typeof field === "string" ? field : "";
    };
    setAdministrationStatus("Submitting the audited account command…");
    void administrationApi
      .createUser(propertyId, {
        username: value("new-username"),
        display_name: value("new-display-name"),
        audit_name: value("new-audit-name"),
        account_class:
          value("new-account-class") === "manager" ? "manager" : "staff",
      })
      .then((created) => {
        setAdministration((current) =>
          current === null
            ? current
            : { ...current, users: [...current.users, created.account] },
        );
        setIssuedPassword({
          username: created.account.username,
          ...created.one_time_password,
        });
        setAdministrationStatus("Account created and recorded for audit.");
        form.reset();
      })
      .catch(() => {
        setAdministrationStatus("The account command was not completed.");
      });
  }

  function confirmAdministrativeCommand() {
    if (pendingCommand === null) return;
    const command = pendingCommand;
    setAdministrationStatus("Submitting the confirmed protected command…");
    if (command.kind === "disable") {
      void administrationApi
        .disableUser(command.user)
        .then((updated) => {
          setAdministration((current) =>
            current === null
              ? current
              : {
                  ...current,
                  users: current.users.map((user) =>
                    user.user_id === updated.user_id ? updated : user,
                  ),
                },
          );
          setAdministrationStatus(
            "Account disabled and applicable sessions revoked by the server.",
          );
          setPendingCommand(null);
        })
        .catch(() => {
          setAdministrationStatus("The protected command was not completed.");
          setPendingCommand(null);
        });
      return;
    }
    if (command.kind === "recover" && command.recovery !== undefined) {
      void administrationApi
        .administrativelyRecoverUser(command.user.user_id, command.recovery)
        .then((result) => {
          setIssuedPassword({
            username: command.user.username,
            ...result.one_time_password,
          });
          setAdministrationStatus(
            `Recovery completed; ${String(result.sessions_revoked)} applicable session(s) revoked.`,
          );
          setPendingCommand(null);
        })
        .catch(() => {
          setAdministrationStatus("The protected recovery was not completed.");
          setPendingCommand(null);
        });
      return;
    }
    void administrationApi
      .revokeSessions(command.user.user_id)
      .then((count) => {
        setAdministrationStatus(
          `${String(count)} applicable session(s) revoked.`,
        );
        setPendingCommand(null);
      })
      .catch(() => {
        setAdministrationStatus("The protected command was not completed.");
        setPendingCommand(null);
      });
  }

  function prepareAdministrativeRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (administration === null) return;
    const data = new FormData(event.currentTarget);
    const userId = data.get("recovery-user");
    const selected = administration.users.find(
      (user) => user.user_id === userId,
    );
    const reason = data.get("recovery-reason");
    if (selected === undefined) return;
    setPendingCommand({
      kind: "recover",
      user: selected,
      recovery: {
        reset_mfa: data.get("recovery-reset-mfa") === "yes",
        reason: typeof reason === "string" ? reason : "",
      },
    });
  }

  function createRoleBundle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const name = data.get("bundle-name");
    const capabilityIds = data
      .getAll("bundle-capability")
      .filter((value): value is string => typeof value === "string");
    setAdministrationStatus("Submitting the audited role-bundle command…");
    void administrationApi
      .createRoleBundle(propertyId, {
        name: typeof name === "string" ? name : "",
        capability_ids: capabilityIds,
      })
      .then((bundle) => {
        setAdministration((current) =>
          current === null
            ? current
            : {
                ...current,
                roleBundles: [...current.roleBundles, bundle],
              },
        );
        setAdministrationStatus("Role bundle created and recorded for audit.");
        form.reset();
      })
      .catch(() => {
        setAdministrationStatus("The role-bundle command was not completed.");
      });
  }

  function assignRoleBundle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const userId = data.get("assignment-user");
    const bundleId = data.get("assignment-bundle");
    setAdministrationStatus("Submitting the audited role assignment…");
    void administrationApi
      .assignRoleBundle(
        typeof userId === "string" ? userId : "",
        typeof bundleId === "string" ? bundleId : "",
      )
      .then(() => {
        setAdministrationStatus("Role bundle assigned and recorded for audit.");
      })
      .catch(() => {
        setAdministrationStatus("The role assignment was not completed.");
      });
  }

  const isSubmitting = submissionState === "submitting";
  const hasError = submissionState === "failed";

  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="eyebrow">Staff application</p>
        <h1>Property Rental Management</h1>
      </header>

      <main aria-labelledby="screen-heading" className="app-content">
        {notice !== null && (
          <p className="global-status" role="status">
            {notice}
          </p>
        )}

        {screen === "sign_in" && (
          <section className="auth-panel">
            <div>
              <p className="eyebrow">Secure access</p>
              <h2 id="screen-heading">Sign in</h2>
              <p className="panel-introduction">
                Use your local staff username and password.
              </p>
            </div>
            <form
              aria-describedby={hasError ? "authentication-error" : undefined}
              className="form-stack"
              onSubmit={handleSignIn}
            >
              <div className="form-field">
                <label htmlFor="username">Username</label>
                <input
                  aria-describedby={
                    hasError ? "authentication-error" : undefined
                  }
                  aria-invalid={hasError}
                  autoComplete="username"
                  disabled={isSubmitting}
                  id="username"
                  name="username"
                  required
                  type="text"
                />
              </div>
              <div className="form-field">
                <label htmlFor="password">Password</label>
                <input
                  aria-describedby={
                    hasError ? "authentication-error" : undefined
                  }
                  aria-invalid={hasError}
                  autoComplete="current-password"
                  disabled={isSubmitting}
                  id="password"
                  name="password"
                  required
                  type="password"
                />
              </div>
              {hasError && (
                <p
                  className="authentication-error"
                  id="authentication-error"
                  role="alert"
                >
                  {AUTHENTICATION_ERROR_MESSAGE}
                </p>
              )}
              <button disabled={isSubmitting} type="submit">
                {isSubmitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="panel-help">
              Need help signing in? Contact your administrator.
            </p>
          </section>
        )}

        {screen === "password_change_required" && (
          <section className="auth-panel">
            <p className="eyebrow">One-time password</p>
            <h2 id="screen-heading">Choose your own password</h2>
            <p className="panel-introduction">
              You signed in with a one-time password. Choose a new password to
              continue.
            </p>
            <form className="form-stack" onSubmit={handlePasswordChange}>
              {/* 128 code points may be 256 UTF-16 units; the server checks the rule. */}
              <div className="form-field">
                <label htmlFor="new-password">New password</label>
                <input
                  aria-describedby="password-rule"
                  autoComplete="new-password"
                  disabled={isSubmitting}
                  id="new-password"
                  maxLength={256}
                  minLength={15}
                  name="new-password"
                  required
                  type="password"
                />
              </div>
              <div className="form-field">
                <label htmlFor="new-password-again">New password again</label>
                <input
                  autoComplete="new-password"
                  disabled={isSubmitting}
                  id="new-password-again"
                  maxLength={256}
                  minLength={15}
                  name="new-password-again"
                  required
                  type="password"
                />
              </div>
              <p className="panel-help" id="password-rule">
                {PASSWORD_RULE_MESSAGE}
              </p>
              {passwordRuleRefused && (
                <p className="authentication-error" role="alert">
                  This password was not accepted. {PASSWORD_RULE_MESSAGE}
                </p>
              )}
              {hasError && (
                <p className="authentication-error" role="alert">
                  The two passwords must match.
                </p>
              )}
              <button disabled={isSubmitting} type="submit">
                Save the new password
              </button>
            </form>
          </section>
        )}

        {screen === "mfa_required" && (
          <section className="auth-panel">
            <p className="eyebrow">Protected verification</p>
            <h2 id="screen-heading">Complete multi-factor authentication</h2>
            <p className="panel-introduction">
              Enter a current authenticator code or one unused recovery code.
            </p>
            <form className="form-stack" onSubmit={handleMfaChallenge}>
              <fieldset>
                <legend>Verification method</legend>
                <label>
                  <input
                    checked={mfaMethod === "totp"}
                    name="mfa-method"
                    onChange={() => {
                      setMfaMethod("totp");
                    }}
                    type="radio"
                  />
                  Authenticator code
                </label>
                <label>
                  <input
                    checked={mfaMethod === "recovery_code"}
                    name="mfa-method"
                    onChange={() => {
                      setMfaMethod("recovery_code");
                    }}
                    type="radio"
                  />
                  Recovery code
                </label>
              </fieldset>
              <div className="form-field">
                <label htmlFor="mfa-code">
                  {mfaMethod === "totp"
                    ? "Authenticator code"
                    : "Unused recovery code"}
                </label>
                <input
                  autoComplete="one-time-code"
                  id="mfa-code"
                  inputMode={mfaMethod === "totp" ? "numeric" : "text"}
                  name="mfa-code"
                  required
                />
              </div>
              {hasError && (
                <p className="authentication-error" role="alert">
                  Verification was not accepted. Try again or contact your
                  administrator.
                </p>
              )}
              <button disabled={isSubmitting} type="submit">
                Verify
              </button>
            </form>
            <p className="panel-help">
              A recovery code is single-use. Store remaining codes outside this
              application.
            </p>
          </section>
        )}

        {screen === "mfa_enrollment_required" && (
          <section className="auth-panel protected-material">
            <p className="eyebrow">Required enrollment</p>
            <h2 id="screen-heading">Enroll an authenticator</h2>
            {enrollment === null ? (
              <>
                <p className="panel-introduction">
                  Enrollment material is shown once. Continue only in a private
                  location.
                </p>
                <button
                  disabled={isSubmitting}
                  onClick={beginEnrollment}
                  type="button"
                >
                  Begin protected enrollment
                </button>
              </>
            ) : (
              <>
                <div
                  className="one-time-material"
                  role="region"
                  aria-label="One-time enrollment material"
                >
                  <p>
                    <strong>Show once:</strong> add this TOTP address to your
                    authenticator.
                  </p>
                  <code>{enrollment.provisioning_uri}</code>
                </div>
                <form className="form-stack" onSubmit={confirmEnrollment}>
                  <div className="form-field">
                    <label htmlFor="enrollment-code">Authenticator code</label>
                    <input
                      autoComplete="one-time-code"
                      id="enrollment-code"
                      inputMode="numeric"
                      name="enrollment-code"
                      pattern="[0-9]{6,8}"
                      required
                    />
                  </div>
                  <button disabled={isSubmitting} type="submit">
                    Confirm enrollment
                  </button>
                </form>
              </>
            )}
            {hasError && (
              <p className="authentication-error" role="alert">
                Enrollment could not be completed. Restart the protected flow.
              </p>
            )}
          </section>
        )}

        {screen === "authenticated" && session !== null && (
          <section className="workspace-panel">
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">Authenticated workspace</p>
                <h2 id="screen-heading">Account and access</h2>
              </div>
              <button
                disabled={isSubmitting}
                onClick={handleLogout}
                type="button"
              >
                Sign out
              </button>
            </div>
            <section
              aria-labelledby="session-heading"
              className="information-card"
            >
              <h3 id="session-heading">Current session</h3>
              <dl className="detail-list">
                <div>
                  <dt>Inactivity expiry</dt>
                  <dd>{formatDateTime(session.idle_expires_at)}</dd>
                </div>
                <div>
                  <dt>Absolute expiry</dt>
                  <dd>{formatDateTime(session.absolute_expires_at)}</dd>
                </div>
                <div>
                  <dt>MFA assurance</dt>
                  <dd>{session.mfa_assurance.replace("_", " ")}</dd>
                </div>
                <div>
                  <dt>Recent authentication</dt>
                  <dd>
                    {session.reauthenticated_at === null
                      ? "Not recorded"
                      : formatDateTime(session.reauthenticated_at)}
                  </dd>
                </div>
              </dl>
              <p className="panel-help">
                The application returns to sign-in after 30 minutes of
                inactivity or 24 hours total. Unsaved commands are never
                reported as successful. Session timestamps are shown in UTC.
              </p>
              <button
                onClick={() => {
                  setShowReauthentication((shown) => !shown);
                }}
                type="button"
              >
                {showReauthentication
                  ? "Cancel reauthentication"
                  : "Reauthenticate for protected administration"}
              </button>
              {showReauthentication && (
                <form
                  className="form-stack nested-form"
                  onSubmit={handleReauthentication}
                >
                  <div className="form-field">
                    <label htmlFor="reauth-password">Password</label>
                    <input
                      autoComplete="current-password"
                      id="reauth-password"
                      name="reauth-password"
                      required
                      type="password"
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor="reauth-code">
                      Authenticator code, when required
                    </label>
                    <input
                      autoComplete="one-time-code"
                      id="reauth-code"
                      inputMode="numeric"
                      name="reauth-code"
                    />
                  </div>
                  <button disabled={isSubmitting} type="submit">
                    Confirm recent authentication
                  </button>
                </form>
              )}
            </section>
            <section
              aria-labelledby="recovery-heading"
              className="information-card"
            >
              <h3 id="recovery-heading">Recovery safety</h3>
              <p>
                Recovery codes are single-use and are never displayed again
                after issuance. Authorized administrative recovery requires
                explicit consequence and audit confirmation.
              </p>
              <p className="panel-help">
                Staff are not granted recovery authority for Owner or Manager
                accounts. Role labels never replace server-side capability
                checks.
              </p>
              {session.reauthenticated_at === null ? (
                <p className="muted">
                  Reauthenticate before generating or replacing recovery codes.
                </p>
              ) : recoveryCodes === null ? (
                <button
                  disabled={isSubmitting}
                  onClick={issueRecoveryCodes}
                  type="button"
                >
                  Generate one-time recovery codes
                </button>
              ) : (
                <div
                  aria-label="One-time recovery codes"
                  className="one-time-material"
                  role="region"
                >
                  <p>
                    <strong>Shown once:</strong> save each code outside this
                    application. Each code can be used only once.
                  </p>
                  <ol>
                    {recoveryCodes.codes.map((code) => (
                      <li key={code}>
                        <code>{code}</code>
                      </li>
                    ))}
                  </ol>
                  <div className="button-row">
                    <button
                      disabled={isSubmitting}
                      onClick={regenerateRecoveryCodes}
                      type="button"
                    >
                      Invalidate and replace this set
                    </button>
                    <button
                      onClick={() => {
                        setRecoveryCodes(null);
                        setNotice(
                          "Recovery codes were cleared from this screen and cannot be displayed again.",
                        );
                      }}
                      type="button"
                    >
                      I saved these codes—clear them
                    </button>
                  </div>
                </div>
              )}
            </section>
            <section
              aria-labelledby="business-configuration-heading"
              className="information-card"
            >
              <h3 id="business-configuration-heading">
                {propertyConfigurationAuthorized
                  ? "Business configuration"
                  : "Business configuration access"}
              </h3>
              {propertyConfigurationAuthorized ? (
                <p>
                  The server authorized this Property. A change needs{" "}
                  <code>settings.manage</code>, and the server checks the
                  current version for every change. The fixed timezone is shown
                  as an authoritative value, not an editable source field.
                </p>
              ) : (
                <p>
                  Enter the exact Property identifier. The server must confirm
                  <code> settings.manage</code> or <code>property.manage</code>{" "}
                  for that Property before any management screen or editing
                  control is shown.
                </p>
              )}
              <form
                className="form-stack inline-form"
                onSubmit={loadPropertyConfiguration}
              >
                <div className="form-field">
                  <label htmlFor="configuration-property-id">
                    Configuration Property identifier
                  </label>
                  <input
                    id="configuration-property-id"
                    onChange={(event) => {
                      invalidatePropertyConfiguration();
                      setPropertyConfigurationStatus(null);
                      setConfigurationPropertyId(event.currentTarget.value);
                    }}
                    required
                    value={configurationPropertyId}
                  />
                </div>
                <button type="submit">Load business configuration</button>
              </form>
              {propertyConfigurationStatus !== null && (
                <p role="status">{propertyConfigurationStatus}</p>
              )}
              {propertyConfiguration !== null && (
                <div className="administration-grid">
                  <section aria-labelledby="property-source-heading">
                    <h4 id="property-source-heading">Property source data</h4>
                    <dl className="detail-list">
                      <div>
                        <dt>Timezone</dt>
                        <dd>{propertyConfiguration.timezone_name}</dd>
                      </div>
                      <div>
                        <dt>Version</dt>
                        <dd>{propertyConfiguration.version}</dd>
                      </div>
                    </dl>
                    <form
                      className="form-stack"
                      key={`property-source-${String(propertyConfiguration.version)}`}
                      onSubmit={updatePropertySource}
                    >
                      <div className="form-field">
                        <label htmlFor="property-name">Property name</label>
                        <input
                          defaultValue={propertyConfiguration.name}
                          id="property-name"
                          name="property-name"
                          required
                        />
                      </div>
                      <div className="form-field">
                        <label htmlFor="property-address">
                          Property address
                        </label>
                        <textarea
                          defaultValue={
                            propertyConfiguration.address_text ?? ""
                          }
                          id="property-address"
                          name="property-address"
                        />
                      </div>
                      <button type="submit">Save Property source data</button>
                    </form>
                  </section>
                  <section aria-labelledby="payment-methods-heading">
                    <h4 id="payment-methods-heading">Payment Methods</h4>
                    {propertyConfiguration.payment_methods.length === 0 ? (
                      <p>No Payment Methods are configured.</p>
                    ) : (
                      <ul className="record-list">
                        {propertyConfiguration.payment_methods.map((method) => (
                          <li key={method.code}>
                            <label>
                              <input
                                checked={method.accepted}
                                onChange={(event) => {
                                  const accepted = event.currentTarget.checked;
                                  setPropertyConfiguration({
                                    ...propertyConfiguration,
                                    payment_methods:
                                      propertyConfiguration.payment_methods.map(
                                        (candidate) =>
                                          candidate.code === method.code
                                            ? { ...candidate, accepted }
                                            : candidate,
                                      ),
                                  });
                                }}
                                type="checkbox"
                              />
                              {method.display_name} ({method.code}) accepted
                            </label>
                          </li>
                        ))}
                      </ul>
                    )}
                    <form className="form-stack" onSubmit={addPaymentMethod}>
                      <div className="form-field">
                        <label htmlFor="payment-method-code">Method code</label>
                        <input
                          id="payment-method-code"
                          name="payment-method-code"
                          required
                        />
                      </div>
                      <div className="form-field">
                        <label htmlFor="payment-method-name">
                          Method display name
                        </label>
                        <input
                          id="payment-method-name"
                          name="payment-method-name"
                          required
                        />
                      </div>
                      <button type="submit">Add Payment Method</button>
                    </form>
                    <button onClick={savePaymentMethods} type="button">
                      Save Payment Method configuration
                    </button>
                    <p className="panel-help">
                      Retired methods remain visible and are never deleted from
                      configuration history.
                    </p>
                  </section>
                </div>
              )}
            </section>
            <ConfigurationManagement
              api={effectiveConfigApi}
              propertyId={propertyConfiguration?.property_id ?? ""}
            />
            <UtilityManagement
              api={utilityApi}
              propertyId={propertyConfiguration?.property_id ?? ""}
            />
            <UtilityLeaseWorkflows
              propertyId={propertyConfiguration?.property_id ?? ""}
            />
            <UnitManagement api={unitApi} />
            {!logoutPending && (
              <InvoiceManagement
                api={invoiceApi}
                actorId={session.actor_id}
                propertyId={propertyConfiguration?.property_id ?? ""}
              />
            )}
            {!logoutPending && (
              <FinancialManagement
                key={session.actor_id}
                actorId={session.actor_id}
                services={financialServices}
                onDirtyStateChange={setFinancialDraftsDirty}
              />
            )}
            {!logoutPending && (
              <CustomerAccountLedger
                key={`customer-ledger:${session.actor_id}`}
                actorId={session.actor_id}
                api={ledgerApi}
                requested={
                  ledgerSelection?.actorId === session.actor_id
                    ? ledgerSelection
                    : undefined
                }
              />
            )}
            <ReservationManagement api={reservationApi} />
            <LeaseManagement api={leaseApi} />
            {!logoutPending && (
              <LeaseEnforcementManagement
                key={`lease-enforcement:${session.actor_id}`}
                actorId={session.actor_id}
                services={enforcementServices}
                onDirtyStateChange={setEnforcementDraftsDirty}
              />
            )}
            <DepositManagement api={depositApi} />
            {!logoutPending && (
              <CustomerManagement
                actorId={session.actor_id}
                api={customerApi}
                onOpenAccountLedger={(selection) => {
                  setLedgerSelection({
                    ...selection,
                    actorId: session.actor_id,
                    sequence: ++ledgerSequence.current,
                  });
                }}
                mutationCoordinationAvailable={customerCoordinationAvailable}
                onCommandBusyChange={setCustomerCommandBusy}
                onDirtyStateChange={setCustomerDraftsDirty}
                onReconciled={async (requirement) => {
                  const clearance =
                    await clearCustomerReconciliation(requirement);
                  if (clearance.status === "cleared") {
                    setCustomerCoordinationAvailable(true);
                    setCustomerReconciliationRequirement((current) =>
                      sameCustomerReconciliation(current, requirement)
                        ? null
                        : current,
                    );
                    return true;
                  } else if (clearance.status === "superseded") {
                    if (clearance.requirement === null) {
                      setCustomerCoordinationAvailable(true);
                      setCustomerReconciliationRequirement(null);
                      setNotice(
                        "The Customer reconciliation gate was already resolved in another tab.",
                      );
                      return true;
                    }
                    setCustomerReconciliationRequirement(clearance.requirement);
                    setNotice(
                      "A newer Customer command gate remains active. Reconcile that exact command before retrying.",
                    );
                    return false;
                  } else {
                    setNotice(
                      "The Customer result is known, but its durable command gate could not be cleared. Customer commands remain blocked.",
                    );
                    return false;
                  }
                }}
                onReconciliationRequired={async (requirement) => {
                  const reservation =
                    await reserveCustomerReconciliation(requirement);
                  if (reservation.existing !== null) {
                    setCustomerCoordinationAvailable(true);
                    setCustomerReconciliationRequirement(reservation.existing);
                    return false;
                  }
                  if (!reservation.reserved) {
                    setNotice(
                      reservation.storageAvailable
                        ? "Another tab already reserved the Customer command gate. Reconcile it before retrying."
                        : "Customer command coordination is unavailable. No command was sent; restore durable browser coordination before retrying.",
                    );
                    return false;
                  }
                  setCustomerCoordinationAvailable(true);
                  setCustomerReconciliationRequirement(requirement);
                  return true;
                }}
                reconciliationRequirement={customerReconciliationRequirement}
              />
            )}
            {!logoutPending && !customerCoordinationAvailable && (
              <section className="information-card">
                <h3>Customer command coordination unavailable</h3>
                <p>
                  Customer commands are blocked because the opaque
                  reconciliation handle cannot be matched to this authenticated
                  browser session. No confidential Customer or actor metadata
                  was read from local storage.
                </p>
              </section>
            )}
            <section
              aria-labelledby="administration-heading"
              className="information-card"
            >
              <h3 id="administration-heading">
                Capability-checked administration
              </h3>
              <p>
                Enter the exact property identifier. The server decides whether
                this session has the required capability; role labels are never
                treated as authority.
              </p>
              <form
                className="form-stack inline-form"
                onSubmit={loadAdministration}
              >
                <div className="form-field">
                  <label htmlFor="property-id">Property identifier</label>
                  <input
                    id="property-id"
                    name="property-id"
                    onChange={(event) => {
                      setPropertyId(event.currentTarget.value);
                    }}
                    required
                    value={propertyId}
                  />
                </div>
                <button type="submit">Check administration access</button>
              </form>
              {administrationStatus !== null && (
                <p role="status">{administrationStatus}</p>
              )}
              {issuedPassword !== null && (
                <section
                  aria-label="One-time password"
                  className="protected-material"
                >
                  <p>
                    One-time password for {issuedPassword.username}:{" "}
                    <code>{issuedPassword.value}</code>
                  </p>
                  <p className="panel-help">
                    Give it to the person directly. It works until{" "}
                    {formatDateTime(issuedPassword.expires_at)}, and the person
                    must choose a new password when they sign in. It is shown
                    only once.
                  </p>
                  <button
                    onClick={() => {
                      setIssuedPassword(null);
                    }}
                    type="button"
                  >
                    I gave it to the person—clear it
                  </button>
                </section>
              )}

              {administration !== null && (
                <div className="administration-grid">
                  <section aria-labelledby="users-heading">
                    <h4 id="users-heading">Accounts</h4>
                    {administration.users.length === 0 ? (
                      <p>No accounts were returned for this property.</p>
                    ) : (
                      <ul className="record-list">
                        {administration.users.map((user) => (
                          <li key={user.user_id}>
                            <div>
                              <strong>{user.display_name}</strong>
                              <span>
                                {user.username} · {user.lifecycle_state} · MFA{" "}
                                {user.mfa_policy_class}
                              </span>
                            </div>
                            {session.reauthenticated_at === null ? (
                              <span className="muted">
                                Reauthenticate before protected commands.
                              </span>
                            ) : (
                              <div className="button-row">
                                {user.lifecycle_state === "active" && (
                                  <button
                                    onClick={() => {
                                      setPendingCommand({
                                        kind: "disable",
                                        user,
                                      });
                                    }}
                                    type="button"
                                  >
                                    Disable account
                                  </button>
                                )}
                                <button
                                  onClick={() => {
                                    setPendingCommand({ kind: "revoke", user });
                                  }}
                                  type="button"
                                >
                                  Revoke sessions
                                </button>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section aria-labelledby="authorization-heading">
                    <h4 id="authorization-heading">
                      Authorization configuration
                    </h4>
                    <p className="panel-help">
                      This current configuration is audit context, not proof of
                      authority. Historical authorization events remain
                      immutable on the server. Event timestamps are shown in
                      UTC.
                    </p>
                    <ul className="record-list">
                      {administration.roleBundles.map((bundle) => (
                        <li key={bundle.role_bundle_id}>
                          <div>
                            <strong>{bundle.name}</strong>
                            <span>
                              {bundle.capability_ids.length} configured
                              capabilities
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                    <h5>Authorization history</h5>
                    {administration.authorizationHistory.length === 0 ? (
                      <p>No authorization events were returned.</p>
                    ) : (
                      <ol className="record-list">
                        {administration.authorizationHistory.map((event) => (
                          <li key={event.event_id}>
                            <div>
                              <strong>{event.action}</strong>
                              <span>
                                {formatDateTime(event.occurred_at)} ·{" "}
                                {event.outcome}
                                {" · actor "}
                                {event.actor_id}
                                {" · target "}
                                {event.target_id}
                              </span>
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                    <details>
                      <summary>Capability catalog</summary>
                      <ul>
                        {administration.capabilities.map((capability) => (
                          <li key={capability.capability_id}>
                            <strong>{capability.name}</strong> —{" "}
                            {capability.description}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </section>

                  {session.reauthenticated_at !== null && (
                    <section aria-labelledby="protected-admin-heading">
                      <h4 id="protected-admin-heading">
                        Protected account and capability commands
                      </h4>
                      <form className="form-stack" onSubmit={createUser}>
                        <h5>Create account</h5>
                        <div className="form-field">
                          <label htmlFor="new-username">Username</label>
                          <input
                            id="new-username"
                            name="new-username"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-display-name">Display name</label>
                          <input
                            id="new-display-name"
                            name="new-display-name"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-audit-name">Audit name</label>
                          <input
                            id="new-audit-name"
                            name="new-audit-name"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-account-class">
                            Account class
                          </label>
                          <select
                            id="new-account-class"
                            name="new-account-class"
                          >
                            <option value="staff">Staff</option>
                            <option value="manager">Manager</option>
                          </select>
                        </div>
                        <button type="submit">Create audited account</button>
                      </form>
                      <form
                        className="form-stack nested-form"
                        onSubmit={createRoleBundle}
                      >
                        <h5>Create role bundle</h5>
                        <div className="form-field">
                          <label htmlFor="bundle-name">Bundle name</label>
                          <input id="bundle-name" name="bundle-name" required />
                        </div>
                        <fieldset>
                          <legend>Explicit capabilities</legend>
                          {administration.capabilities.map((capability) => (
                            <label key={capability.capability_id}>
                              <input
                                name="bundle-capability"
                                type="checkbox"
                                value={capability.capability_id}
                              />
                              {capability.name}
                            </label>
                          ))}
                        </fieldset>
                        <button type="submit">
                          Create audited role bundle
                        </button>
                      </form>
                      {administration.users.length > 0 &&
                        administration.roleBundles.length > 0 && (
                          <form
                            className="form-stack nested-form"
                            onSubmit={assignRoleBundle}
                          >
                            <h5>Assign configured role bundle</h5>
                            <div className="form-field">
                              <label htmlFor="assignment-user">Account</label>
                              <select
                                id="assignment-user"
                                name="assignment-user"
                              >
                                {administration.users.map((user) => (
                                  <option
                                    key={user.user_id}
                                    value={user.user_id}
                                  >
                                    {user.display_name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="form-field">
                              <label htmlFor="assignment-bundle">
                                Role bundle
                              </label>
                              <select
                                id="assignment-bundle"
                                name="assignment-bundle"
                              >
                                {administration.roleBundles.map((bundle) => (
                                  <option
                                    key={bundle.role_bundle_id}
                                    value={bundle.role_bundle_id}
                                  >
                                    {bundle.name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <button type="submit">
                              Assign audited role bundle
                            </button>
                          </form>
                        )}
                      {administration.users.length > 0 && (
                        <form
                          className="form-stack nested-form"
                          onSubmit={prepareAdministrativeRecovery}
                        >
                          <h5>Owner-authorized account recovery</h5>
                          <p className="panel-help">
                            The server permits only Owner recovery of Manager or
                            Staff. It rejects Staff recovery of Owner or Manager
                            and does not grant Manager recovery of Staff.
                          </p>
                          <div className="form-field">
                            <label htmlFor="recovery-user">Account</label>
                            <select id="recovery-user" name="recovery-user">
                              {administration.users.map((user) => (
                                <option key={user.user_id} value={user.user_id}>
                                  {user.display_name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="form-field">
                            <label htmlFor="recovery-reason">
                              Audit reason
                            </label>
                            <input
                              id="recovery-reason"
                              maxLength={500}
                              name="recovery-reason"
                              required
                            />
                          </div>
                          <label>
                            <input
                              name="recovery-reset-mfa"
                              type="checkbox"
                              value="yes"
                            />
                            Reset current MFA enrollment
                          </label>
                          <button type="submit">
                            Review recovery consequences
                          </button>
                        </form>
                      )}
                    </section>
                  )}
                </div>
              )}

              {pendingCommand !== null && (
                <div
                  aria-labelledby="confirmation-heading"
                  aria-modal="true"
                  className="confirmation-panel"
                  role="alertdialog"
                >
                  <h4 id="confirmation-heading">Confirm protected command</h4>
                  <p>
                    {pendingCommand.kind === "disable"
                      ? "Disabling this account also revokes every applicable session."
                      : pendingCommand.kind === "recover"
                        ? "Recovery gives the selected account a one-time password, may reset MFA, and revokes every applicable session."
                        : "This revokes every applicable session for the selected account."}{" "}
                    The server records the acting account and request for audit.
                  </p>
                  <div className="button-row">
                    <button
                      onClick={confirmAdministrativeCommand}
                      type="button"
                    >
                      Confirm command
                    </button>
                    <button
                      onClick={() => {
                        setPendingCommand(null);
                      }}
                      type="button"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </section>
          </section>
        )}
      </main>

      <footer aria-label="Build information" className="app-footer">
        {environment !== "production" && (
          <span className="environment">{environment}</span>
        )}
        <span>Build {buildId}</span>
      </footer>
    </div>
  );
}
