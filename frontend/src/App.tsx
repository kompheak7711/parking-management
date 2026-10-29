import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { todayInPhnomPenh } from "./shell/format";

import {
  type ApprovalsApi,
  approvalsApi as approvalsClient,
} from "./approvals/approvalsClient";
import {
  ApprovalsPage,
  type DraftDecisionApi,
} from "./approvals/ApprovalsPage";
import {
  AuthenticationApi,
  AuthenticationData,
  LocalSignIn,
  RecoveryCodeSetData,
  ReauthenticationRequest,
  RecoveryCodeSetSummary,
  SessionData,
  authenticationApi,
  signIn,
} from "./authClient";
import { SignInEntry, SignInScreens } from "./SignInScreens";
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
import { UnitApi, unitApi as defaultUnitApi } from "./unitClient";
import {
  CustomerManagement,
  CustomerReconciliationRequirement,
} from "./CustomerManagement";
import {
  CustomerApi,
  customerApi as defaultCustomerApi,
} from "./customerClient";
import { ConfigurationManagement } from "./ConfigurationManagement";
import {
  EffectiveConfigurationApi,
  effectiveConfigurationApi,
} from "./configurationClient";
import {
  ReservationApi,
  reservationApi as reservationClient,
} from "./reservationClient";
import { LeaseManagement } from "./LeaseManagement";
import { LeasesPage } from "./leases/LeasesPage";
import { LettersPage } from "./letters/LettersPage";
import {
  LettersApi,
  lettersApi as lettersClient,
} from "./letters/lettersClient";
import { ltr } from "./letters/text";
import { MoveoutPage } from "./moveout/MoveoutPage";
import {
  type MoveOutApi,
  moveOutApi as moveOutClient,
} from "./moveout/moveoutClient";
import { mt } from "./moveout/text";
import { lt } from "./leases/text";
import { LeaseApi, leaseApi as leaseClient } from "./leaseClient";
import { DepositManagement } from "./DepositManagement";
import { DepositApi, depositApi as depositClient } from "./depositClient";
import { UtilityManagement } from "./UtilityManagement";
import { UtilityLeaseWorkflows } from "./UtilityLeaseWorkflows";
import {
  type UtilityLeaseApi,
  utilityLeaseApi as utilityLeaseClient,
} from "./utilityLeaseClient";
import { UtilityApi, utilityApi as utilityClient } from "./utilityClient";
import { UtilitiesPage } from "./utilities/UtilitiesPage";
import { utt } from "./utilities/text";
import { InvoiceManagement } from "./InvoiceManagement";
import { InvoicesPage } from "./invoices/InvoicesPage";
import { PaymentsPage } from "./payments/PaymentsPage";
import { type HomeApi, HomeScreen } from "./home/HomeScreen";
import { reportsApi } from "./reportsClient";
import { type ReportApi, ReportsPage } from "./reports/ReportsPage";
import {
  type HistoryApi,
  historyApi as historyClient,
} from "./history/historyClient";
import { type HistoryExportApi, HistoryPage } from "./history/HistoryPage";
import { settlementApi, type SettlementApi } from "./settlementClient";
import {
  type HealthApi,
  healthApi as healthClient,
} from "./settings/healthClient";
import { SettingsPage } from "./settings/SettingsPage";
import {
  type PaymentsApi,
  paymentsApi as paymentsClient,
} from "./payments/paymentsClient";
import { pyt } from "./payments/text";
import { ivt } from "./invoices/text";
import {
  type DueDaysApi,
  dueDaysApi as dueDaysClient,
  InvoiceApi,
  invoiceApi as invoiceClient,
} from "./invoiceClient";
import { LeaseEnforcementManagement } from "./LeaseEnforcementManagement";
import type { EnforcementServices } from "./leaseEnforcementUi";
import { FinancialManagement } from "./FinancialManagement";
import type { FinancialUiServices } from "./financialUi";
import {
  CustomerAccountLedger,
  type LedgerSelection,
} from "./CustomerAccountLedger";
import {
  type CustomerLedgerApi,
  customerLedgerClient,
} from "./customerLedgerClient";
import { type Language, storeLanguage, storedLanguage } from "./signInText";
import { AppShell } from "./shell/AppShell";
import { NoAccess, PropertyNeeded } from "./shell/pages";
import { openPageInAddress, useHashPage } from "./shell/useHashPage";
import type { CustomerCommandGate } from "./customers/commands";
import { CustomersPage } from "./customers/CustomersPage";
import { ReservationsPage } from "./reservations/ReservationsPage";
import { ct } from "./customers/text";
import { UnitsPage } from "./units/UnitsPage";
import { type ActorAccessApi, actorAccessApi } from "./shell/accessClient";
import { pageAllowed, type PageId } from "./shell/navigation";

export interface AppProps {
  environment: string;
  buildId: string;
  authenticate?: LocalSignIn;
  api?: AuthenticationApi;
  administrationApi?: AccessAdministrationApi;
  propertyApi?: PropertyConfigurationApi;
  unitApi?: UnitApi;
  dueDaysApi?: DueDaysApi;
  customerApi?: CustomerApi;
  effectiveConfigApi?: EffectiveConfigurationApi;
  reservationApi?: ReservationApi;
  leaseApi?: LeaseApi;
  lettersApi?: LettersApi;
  moveOutApi?: MoveOutApi;
  utilityLeaseApi?: UtilityLeaseApi;
  /** The move-out cleaning charge (V1-058 R3 M4). */
  moveOutChargeApi?: Pick<
    SettlementApi,
    | "cleaningRate"
    | "chargeCleaning"
    | "settlements"
    | "startSettlement"
    | "settlementPreview"
    | "refundMethods"
    | "settlementDraft"
    | "extraCharge"
    | "forfeitureDraft"
  >;
  depositApi?: DepositApi;
  utilityApi?: UtilityApi;
  invoiceApi?: InvoiceApi;
  paymentsApi?: PaymentsApi;
  homeApi?: HomeApi;
  historyApi?: HistoryApi;
  historyExportApi?: HistoryExportApi;
  reportApi?: ReportApi;
  healthApi?: HealthApi;
  approvalsApi?: ApprovalsApi;
  draftDecisionApi?: DraftDecisionApi;
  financialServices?: FinancialUiServices;
  enforcementServices?: EnforcementServices;
  ledgerApi?: CustomerLedgerApi;
  accessApi?: ActorAccessApi;
  now?: () => number;
}

type SubmissionState = "idle" | "submitting" | "succeeded" | "failed";
// Login sub-slice L6: every step before the session lives in the sign-in layer.
type Screen = "sign_in" | "authenticated";

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unavailable" : parsed.toISOString();
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
  lettersApi = lettersClient,
  moveOutApi = moveOutClient,
  utilityLeaseApi = utilityLeaseClient,
  moveOutChargeApi = settlementApi,
  depositApi = depositClient,
  utilityApi = utilityClient,
  invoiceApi = invoiceClient,
  paymentsApi = paymentsClient,
  homeApi = reportsApi,
  historyApi = historyClient,
  historyExportApi = reportsApi,
  reportApi = reportsApi,
  healthApi = healthClient,
  dueDaysApi = dueDaysClient,
  approvalsApi = approvalsClient,
  draftDecisionApi = settlementApi,
  financialServices,
  enforcementServices,
  ledgerApi,
  accessApi = actorAccessApi,
  now = Date.now,
}: AppProps) {
  // V1-058 R7c: History names people from the user list when this account may read it.
  const historyPeople = useCallback(
    (id: string) =>
      administrationApi.load(id).then((snapshot) => snapshot.users),
    [administrationApi],
  );
  // V1-058 R7b-4: one object, so the Business tab does not read again on every render.
  const businessApi = useMemo(
    () => ({
      property: propertyApi,
      dueDays: dueDaysApi,
      units: unitApi ?? defaultUnitApi,
      rates: effectiveConfigApi,
    }),
    [propertyApi, dueDaysApi, unitApi, effectiveConfigApi],
  );
  const client = useMemo<AuthenticationApi>(
    () => api ?? { ...authenticationApi, signIn: authenticate },
    [api, authenticate],
  );
  // V1-058 R1: the page named by the address, and the screen language chosen on this device
  // (shared with the sign-in screens).
  const page = useHashPage();
  // V1-058 R1b: the person's capabilities, so the menu shows only what they may use; null while
  // unknown or unreadable (the server still checks every action).
  const [capabilities, setCapabilities] = useState<ReadonlySet<string> | null>(
    null,
  );
  const accessSequence = useRef(0);
  const [language, setLanguage] = useState<Language>(storedLanguage);
  function changeLanguage(next: Language) {
    setLanguage(next);
    storeLanguage(next);
  }
  const [screen, setScreen] = useState<Screen>("sign_in");
  const [session, setSession] = useState<SessionData | null>(null);
  const [submissionState, setSubmissionState] =
    useState<SubmissionState>("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const [signInEntry, setSignInEntry] = useState<SignInEntry>({
    kind: "sign_in",
  });
  // A new sign-in layer (cleared fields and steps) each time the app returns to it.
  const [signInSequence, setSignInSequence] = useState(0);
  const [recoveryCodes, setRecoveryCodes] =
    useState<RecoveryCodeSetData | null>(null);
  // Login sub-slice L6: the account's live recovery-code set without its codes; undefined until
  // the server answers (or when it could not).
  const [liveRecoverySet, setLiveRecoverySet] = useState<
    RecoveryCodeSetSummary | null | undefined
  >(undefined);
  const [liveRecoverySetFailed, setLiveRecoverySetFailed] = useState(false);
  const liveRecoverySetSequence = useRef(0);
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
  const [propertyId, setPropertyId] = useState("");
  const [configurationPropertyId, setConfigurationPropertyId] = useState("");
  const [propertyConfiguration, setPropertyConfiguration] =
    useState<PropertyBusinessConfiguration | null>(null);
  const [propertyConfigurationStatus, setPropertyConfigurationStatus] =
    useState<string | null>(null);
  const [propertyConfigurationAuthorized, setPropertyConfigurationAuthorized] =
    useState(false);
  const [customerDraftsDirty, setCustomerDraftsDirty] = useState(false);
  // V1-058 R2 step C2: the new Customer form page has its own unsaved values.
  const [customerPageDirty, setCustomerPageDirty] = useState(false);
  const [customerRecordsOpen, setCustomerRecordsOpen] = useState(false);
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

  const sessionActorId = session?.actor_id ?? null;
  useEffect(() => {
    if (sessionActorId === null) return;
    const ticket = ++accessSequence.current;
    const controller = new AbortController();
    void accessApi
      .read(controller.signal)
      .then((access) => {
        if (ticket !== accessSequence.current) return;
        if (access.actor_id !== sessionActorId) return;
        setCapabilities(
          new Set(access.capabilities.map((grant) => grant.capability)),
        );
        // V1 has one Property: fill the Property boxes once, so nobody types its identifier.
        const properties = new Set(
          access.capabilities.flatMap((grant) => grant.property_ids),
        );
        if (properties.size === 1) {
          const only = [...properties][0] ?? "";
          setConfigurationPropertyId((current) =>
            current === "" ? only : current,
          );
          setPropertyId((current) => (current === "" ? only : current));
        }
      })
      .catch(() => {
        // Unreadable access shows the whole menu; the server still refuses what is not allowed.
      });
    return () => {
      controller.abort();
    };
  }, [accessApi, sessionActorId]);

  function invalidatePropertyConfiguration() {
    propertyOperationSequence.current += 1;
    setPropertyConfiguration(null);
    setPropertyConfigurationAuthorized(false);
  }

  async function acceptAuthentication(
    result: AuthenticationData,
    welcome: string,
    operation = ++authenticationOperationSequence.current,
  ) {
    if (result.phase !== "authenticated" || result.session === null) return;
    const stored = await readStoredCustomerReconciliation(
      result.session.actor_id,
    );
    if (operation !== authenticationOperationSequence.current) return;
    const reconciliation = stored.requirement;
    invalidatePropertyConfiguration();
    setPropertyConfigurationStatus(null);
    setSession(result.session);
    // The sign-in screens may have changed the language on this device.
    setLanguage(storedLanguage());
    setCustomerCoordinationAvailable(
      stored.status !== "unavailable" && stored.status !== "invalid",
    );
    setCustomerReconciliationRequirement(reconciliation);
    setScreen("authenticated");
    setSubmissionState("succeeded");
    setNotice(
      stored.status === "unavailable" || stored.status === "invalid"
        ? "Customer command coordination is unavailable. Customer commands remain blocked without exposing another actor's reconciliation metadata."
        : reconciliation !== null
          ? "A Customer command outcome is unknown. Reload the applicable Customer list and verify the result before retrying."
          : welcome,
    );
  }

  function returnToSignIn(entry: SignInEntry) {
    // V1-058 R1: the next person starts on Home, not on the page the last person left open.
    openPageInAddress("home", true);
    accessSequence.current += 1;
    setCapabilities(null);
    setEnforcementDraftsDirty(false);
    setFinancialDraftsDirty(false);
    setCustomerDraftsDirty(false);
    setCustomerCommandBusy(false);
    setCustomerReconciliationRequirement(null);
    setLogoutPending(false);
    setLedgerSelection(null);
    setScreen("sign_in");
    setSession(null);
    setRecoveryCodes(null);
    setIssuedPassword(null);
    invalidatePropertyConfiguration();
    setPropertyConfigurationStatus(null);
    setSubmissionState("idle");
    setShowReauthentication(false);
    setNotice(null);
    setSignInEntry(entry);
    setSignInSequence((sequence) => sequence + 1);
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
    // Login sub-slice L6: the session's 24-hour limit comes first or the 30 minutes without use.
    const dayLimit =
      new Date(session.absolute_expires_at).getTime() <=
      new Date(session.idle_expires_at).getTime();
    let active = true;
    const ended = () => {
      returnToSignIn({
        kind: dayLimit ? "day" : "idle",
        note:
          customerCommandBusy || customerReconciliationRequirement !== null
            ? "Your session expired while a Customer command was pending. Its outcome is unknown; sign in, reload Customers, and reconcile before retrying."
            : null,
      });
    };
    const timer = window.setTimeout(() => {
      // L6 review round 1: every request moves the server's 30 minutes on, so the server is
      // asked first; a session it still holds for this person keeps the app open.
      const operation = authenticationOperationSequence.current;
      void client
        .inspectSession()
        .then((current) => {
          if (
            !active ||
            operation !== authenticationOperationSequence.current
          ) {
            return;
          }
          const currentEnd = Math.min(
            new Date(current.idle_expires_at).getTime(),
            new Date(current.absolute_expires_at).getTime(),
          );
          if (current.actor_id === session.actor_id && currentEnd > now()) {
            setSession(current);
          } else {
            ended();
          }
        })
        .catch(() => {
          if (active && operation === authenticationOperationSequence.current) {
            ended();
          }
        });
    }, delay);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [
    client,
    customerCommandBusy,
    customerReconciliationRequirement,
    now,
    screen,
    session,
  ]);

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

  /** V1-058 R7b-3: the Users tab asks for the password and code again itself. */
  async function reauthenticateForSettings(request: ReauthenticationRequest) {
    // The Property configuration is kept: clearing it could move the tab to no Property while
    // the action runs again.
    setSession(await client.reauthenticate(request));
  }

  function handleLogout() {
    if (
      (customerDraftsDirty ||
        customerPageDirty ||
        customerCommandBusy ||
        customerReconciliationRequirement !== null) &&
      !window.confirm(
        customerCommandBusy
          ? "A Customer command is still pending and its outcome will be unknown. Discard other unsaved Customer values and sign out?"
          : "Discard unsaved Customer form values and sign out?",
      )
    ) {
      setNotice(
        "Sign out was cancelled; unsaved Customer values were preserved.",
      );
      // V1-058 R1: show the page that holds the unsaved form.
      openPageInAddress("customers");
      return;
    }
    if (
      financialDraftsDirty &&
      !window.confirm("Discard unsaved financial form values and sign out?")
    ) {
      setNotice(
        "Sign out was cancelled; unsaved financial values were preserved.",
      );
      // V1-058 R1: show the page that holds the unsaved form.
      openPageInAddress("payments");
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
      // V1-058 R1: show the page that holds the unsaved form.
      openPageInAddress("letters");
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
        returnToSignIn({ kind: "sign_in", signedOut: true });
      })
      .catch(() => {
        // The server did not confirm the sign-out, so its session may still be alive: stay
        // signed in and say so, rather than show the sign-in screen to the next person (login
        // L8 review).
        setLogoutPending(false);
        setSubmissionState("idle");
        setNotice(
          "Sign out did not reach the office computer. Check the connection and sign out again.",
        );
      });
  }

  function loadLiveRecoverySet() {
    const sequence = ++liveRecoverySetSequence.current;
    setLiveRecoverySetFailed(false);
    void client
      .liveRecoveryCodeSet()
      .then((summary) => {
        if (sequence === liveRecoverySetSequence.current) {
          setLiveRecoverySet(summary);
        }
      })
      .catch(() => {
        // A refusal of this read does not mean signed out (plan binding of L3c-2c-1).
        if (sequence === liveRecoverySetSequence.current) {
          setLiveRecoverySet(undefined);
          setLiveRecoverySetFailed(true);
        }
      });
  }

  const sessionActor = session?.actor_id ?? null;
  useEffect(() => {
    liveRecoverySetSequence.current += 1;
    setLiveRecoverySet(undefined);
    setLiveRecoverySetFailed(false);
    if (screen !== "authenticated" || sessionActor === null) return;
    loadLiveRecoverySet();
  }, [client, screen, sessionActor]);

  function issueRecoveryCodes() {
    setSubmissionState("submitting");
    void client
      .issueRecoveryCodes()
      .then((result) => {
        setRecoveryCodes(result);
        loadLiveRecoverySet();
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
    // The set on screen, else the live set the server reports (for example the first Owner's
    // set from the server set-up, whose codes this screen never showed).
    const priorSetId = recoveryCodes?.set_id ?? liveRecoverySet?.set_id;
    if (priorSetId === undefined) return;
    setSubmissionState("submitting");
    void client
      .regenerateRecoveryCodes(priorSetId)
      .then((result) => {
        setRecoveryCodes(result);
        loadLiveRecoverySet();
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

  const buildInformation = (
    <footer aria-label="Build information" className="app-footer">
      {environment !== "production" && (
        <span className="environment">{environment}</span>
      )}
      <span>Build {buildId}</span>
    </footer>
  );

  if (screen !== "authenticated" || session === null) {
    return (
      <SignInScreens
        api={client}
        entry={signInEntry}
        footer={buildInformation}
        key={signInSequence}
        now={now}
        onAuthenticated={(result, welcome) => {
          void acceptAuthentication(result, welcome);
        }}
        onSignInStarted={() => {
          // L6 review round 1 (TEST-FE-110): a session restore still running must not open
          // the app for another person while this sign-in is on its way.
          authenticationOperationSequence.current += 1;
        }}
      />
    );
  }

  // V1-058 R1b: a page opens only when it is the address and the person may use it.
  // The one Customer command gate, shared by the earlier form and the V1-058 dialogs.
  const releaseCustomerGate = async (
    requirement: CustomerReconciliationRequirement,
  ): Promise<boolean> => {
    const clearance = await clearCustomerReconciliation(requirement);
    if (clearance.status === "cleared") {
      setCustomerCoordinationAvailable(true);
      setCustomerReconciliationRequirement((current) =>
        sameCustomerReconciliation(current, requirement) ? null : current,
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
  };
  const reserveCustomerGate = async (
    requirement: CustomerReconciliationRequirement,
  ): Promise<boolean> => {
    const reservation = await reserveCustomerReconciliation(requirement);
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
  };
  const customerGate: CustomerCommandGate = {
    actorId: session.actor_id,
    open:
      customerCoordinationAvailable &&
      customerReconciliationRequirement === null,
    reserve: reserveCustomerGate,
    release: releaseCustomerGate,
    setBusy: setCustomerCommandBusy,
  };
  const allowed = pageAllowed(page, capabilities);
  const shown = (candidate: PageId) => candidate === page && allowed;

  return (
    <AppShell
      buildId={buildId}
      capabilities={capabilities}
      displayName={session.display_name ?? null}
      environment={environment}
      language={language}
      notice={
        notice !== null && (
          <p className="global-status" role="status">
            {notice}
          </p>
        )
      }
      now={now}
      onLanguageChange={changeLanguage}
      onSignOut={handleLogout}
      page={page}
      signOutDisabled={isSubmitting}
    >
      {!allowed && <NoAccess language={language} />}
      <div className="shell-page" data-page="home" hidden={!shown("home")}>
        {propertyId === "" && propertyConfiguration === null && (
          <PropertyNeeded language={language} />
        )}
        <HomeScreen
          active={shown("home")}
          capabilities={capabilities}
          homeApi={homeApi}
          language={language}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
        />
      </div>
      <div
        className="shell-page"
        data-page="payments"
        hidden={!shown("payments")}
      >
        <PaymentsPage
          active={shown("payments")}
          capabilities={capabilities}
          customerApi={customerApi ?? defaultCustomerApi}
          invoiceApi={invoiceApi}
          language={language}
          leaseApi={leaseApi}
          paymentsApi={paymentsApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
        />
        {/* V1-058 R5c: the payment list, matching, Credit and refunds stay in the earlier English
            forms, folded, until the next steps move them into the Payments screens. */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{pyt(language, "records")}</span>
            <span className="ui-small ui-muted">
              {pyt(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            {!logoutPending && (
              <FinancialManagement
                key={session.actor_id}
                actorId={session.actor_id}
                services={financialServices}
                onDirtyStateChange={setFinancialDraftsDirty}
              />
            )}
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="invoices"
        hidden={!shown("invoices")}
      >
        <InvoicesPage
          active={shown("invoices")}
          capabilities={capabilities}
          customerApi={customerApi ?? defaultCustomerApi}
          invoiceApi={invoiceApi}
          language={language}
          lateApi={paymentsApi}
          leaseApi={leaseApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
        />
        {/* V1-058 R5: the billing runs and the Due Date settings stay in the earlier English
            forms, folded, until Settings and Home take them over. */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{ivt(language, "records")}</span>
            <span className="ui-small ui-muted">
              {ivt(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            {propertyConfiguration === null && (
              <PropertyNeeded language={language} />
            )}
            {!logoutPending && (
              <InvoiceManagement
                api={invoiceApi}
                actorId={session.actor_id}
                propertyId={
                  propertyId || (propertyConfiguration?.property_id ?? "")
                }
              />
            )}
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="utilities"
        hidden={!shown("utilities")}
      >
        <UtilitiesPage
          active={shown("utilities")}
          capabilities={capabilities}
          language={language}
          leaseApi={leaseApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          unitApi={unitApi ?? defaultUnitApi}
          utilityApi={utilityApi}
        />
        {/* V1-058 R4: meters, rates, corrections and move-in or move-out readings stay in the
            earlier English forms, folded, until the next steps move them into the design. */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{utt(language, "records")}</span>
            <span className="ui-small ui-muted">
              {utt(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            <UtilityManagement
              api={utilityApi}
              propertyId={
                propertyId || (propertyConfiguration?.property_id ?? "")
              }
            />
            <UtilityLeaseWorkflows
              propertyId={
                propertyId || (propertyConfiguration?.property_id ?? "")
              }
            />
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="approvals"
        hidden={!shown("approvals")}
      >
        <ApprovalsPage
          active={shown("approvals")}
          actorId={session.actor_id}
          approvalsApi={approvalsApi}
          capabilities={capabilities}
          decisionApi={draftDecisionApi}
          language={language}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
        />
      </div>
      <div className="shell-page" data-page="units" hidden={!shown("units")}>
        <UnitsPage
          active={shown("units")}
          capabilities={capabilities}
          language={language}
          leaseApi={leaseApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          reservationApi={reservationApi}
          unitApi={unitApi ?? defaultUnitApi}
          utilityApi={utilityApi}
        />
      </div>
      <div
        className="shell-page"
        data-page="customers"
        hidden={!shown("customers")}
      >
        {!logoutPending && (
          <CustomersPage
            active={shown("customers")}
            actorId={session.actor_id}
            capabilities={capabilities}
            customerApi={customerApi ?? defaultCustomerApi}
            gate={customerGate}
            onDirty={setCustomerPageDirty}
            language={language}
            leaseApi={leaseApi}
            ledgerApi={ledgerApi ?? customerLedgerClient}
            onOpenLedger={(customerId) => {
              const selected =
                propertyId || (propertyConfiguration?.property_id ?? "");
              if (selected === "") return;
              setLedgerSelection({
                customerId,
                propertyId: selected,
                actorId: session.actor_id,
                sequence: ++ledgerSequence.current,
              });
              setCustomerRecordsOpen(true);
              window.setTimeout(() => {
                document
                  .getElementById("customer-records")
                  ?.scrollIntoView({ block: "start" });
              }, 0);
            }}
            propertyId={
              propertyId || (propertyConfiguration?.property_id ?? "")
            }
            reservationApi={reservationApi}
          />
        )}
        {/* V1-058 R2 step C2: the earlier form stays folded away. It opens by itself while a
            Customer save waits to be checked, and for the full Account Ledger. */}
        <details
          className="ui-records"
          id="customer-records"
          onToggle={(event) => {
            // A waiting save opens it by itself; only the person's own click is remembered.
            if (customerReconciliationRequirement === null)
              setCustomerRecordsOpen(event.currentTarget.open);
          }}
          open={
            customerRecordsOpen || customerReconciliationRequirement !== null
          }
        >
          <summary lang={language}>
            <span className="ui-records-title">{ct(language, "records")}</span>
            <span className="ui-small ui-muted">
              {ct(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
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
                onReconciled={releaseCustomerGate}
                onReconciliationRequired={reserveCustomerGate}
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
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="reservations"
        hidden={!shown("reservations")}
      >
        {/* V1-060 B6: Make Reservation is in the design now; the earlier form is gone. */}
        <ReservationsPage
          active={shown("reservations")}
          api={reservationApi}
          capabilities={capabilities}
          customerApi={customerApi ?? defaultCustomerApi}
          customerGate={customerGate}
          language={language}
          paymentsApi={paymentsApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          unitApi={unitApi ?? defaultUnitApi}
        />
      </div>
      <div className="shell-page" data-page="leases" hidden={!shown("leases")}>
        <LeasesPage
          active={shown("leases")}
          api={leaseApi}
          capabilities={capabilities}
          depositApi={depositApi}
          language={language}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          customerApi={customerApi ?? defaultCustomerApi}
          customerCreateApi={customerApi ?? defaultCustomerApi}
          customerGate={customerGate}
          reservationApi={reservationApi}
          unitApi={unitApi ?? defaultUnitApi}
          lettersApi={lettersApi}
        />
        {/* V1-058 R3: the Lease actions stay in the earlier English forms, folded, until
            the next step moves them into the design. */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{lt(language, "records")}</span>
            <span className="ui-small ui-muted">
              {lt(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            <LeaseManagement api={leaseApi} />
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="letters"
        hidden={!shown("letters")}
      >
        <LettersPage
          active={shown("letters")}
          api={lettersApi}
          capabilities={capabilities}
          language={language}
          leaseApi={leaseApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
        />
        {/* V1-058 R3: the earlier English forms stay, folded, until the Terminate step and the
            later steps replace what is left in them (opening a case for another follow-up,
            Initial Rent alerts). */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{ltr(language, "records")}</span>
            <span className="ui-small ui-muted">
              {ltr(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            {!logoutPending && (
              <LeaseEnforcementManagement
                key={`lease-enforcement:${session.actor_id}`}
                actorId={session.actor_id}
                services={enforcementServices}
                onDirtyStateChange={setEnforcementDraftsDirty}
              />
            )}
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="moveout"
        hidden={!shown("moveout")}
      >
        <MoveoutPage
          active={shown("moveout")}
          capabilities={capabilities}
          depositApi={depositApi}
          language={language}
          leaseApi={leaseApi}
          moveOutApi={moveOutApi}
          invoiceApi={invoiceApi}
          utilityApi={utilityApi}
          utilityLeaseApi={utilityLeaseApi}
          settlementApi={moveOutChargeApi}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          today={todayInPhnomPenh()}
          unitApi={unitApi ?? defaultUnitApi}
        />
        {/* V1-058 R3 Move-out: the earlier English Deposit forms stay, folded, until the
            Final Settlement steps replace them. */}
        <details className="ui-records">
          <summary lang={language}>
            <span className="ui-records-title">{mt(language, "records")}</span>
            <span className="ui-small ui-muted">
              {mt(language, "records_note")}
            </span>
          </summary>
          <div lang="en">
            <DepositManagement api={depositApi} />
          </div>
        </details>
      </div>
      <div
        className="shell-page"
        data-page="reports"
        hidden={!shown("reports")}
      >
        {propertyId === "" && propertyConfiguration === null && (
          <PropertyNeeded language={language} />
        )}
        <ReportsPage
          active={shown("reports")}
          api={reportApi}
          capabilities={capabilities}
          language={language}
          now={now}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          today={todayInPhnomPenh()}
          units={unitApi ?? defaultUnitApi}
        />
      </div>
      <div
        className="shell-page"
        data-page="history"
        hidden={!shown("history")}
      >
        <HistoryPage
          active={shown("history")}
          api={historyApi}
          capabilities={capabilities}
          exporter={historyExportApi}
          language={language}
          me={{
            id: session.actor_id,
            name: session.display_name ?? session.actor_id.slice(0, 8),
          }}
          people={historyPeople}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          today={todayInPhnomPenh()}
          units={unitApi ?? defaultUnitApi}
        />
      </div>
      <div
        className="shell-page"
        data-page="account"
        hidden={!shown("account")}
        lang="en"
      >
        <section className="workspace-panel">
          <div className="workspace-heading">
            <h2 id="screen-heading">Account and access</h2>
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
              The application returns to sign-in after 30 minutes of inactivity
              or 24 hours total. Unsaved commands are never reported as
              successful. Session timestamps are shown in UTC.
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
              Recovery codes are single-use and are never displayed again after
              issuance. Authorized administrative recovery requires explicit
              consequence and audit confirmation.
            </p>
            <p className="panel-help">
              Staff are not granted recovery authority for Owner or Manager
              accounts. Role labels never replace server-side capability checks.
            </p>
            {liveRecoverySet !== undefined && recoveryCodes === null && (
              <p>
                {liveRecoverySet === null
                  ? "You have no recovery codes."
                  : `Your recovery codes: ${String(liveRecoverySet.usable_count)} still work. ${
                      liveRecoverySet.made_by === "issued"
                        ? "First made"
                        : liveRecoverySet.made_by === "regenerated"
                          ? "Replaced"
                          : "Made by the server set-up"
                    } ${formatDateTime(liveRecoverySet.created_at)}.`}
              </p>
            )}
            {session.reauthenticated_at === null ? (
              <p className="muted">
                Reauthenticate before generating or replacing recovery codes.
              </p>
            ) : recoveryCodes === null ? (
              liveRecoverySet === null ? (
                <button
                  disabled={isSubmitting}
                  onClick={issueRecoveryCodes}
                  type="button"
                >
                  Generate one-time recovery codes
                </button>
              ) : liveRecoverySet === undefined ? (
                // Nothing while the read runs (review round 2).
                liveRecoverySetFailed && (
                  <p className="muted">
                    Your recovery codes could not be checked. Reload the page to
                    try again.
                  </p>
                )
              ) : (
                <button
                  disabled={isSubmitting}
                  onClick={regenerateRecoveryCodes}
                  type="button"
                >
                  Replace my recovery codes
                </button>
              )
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
        </section>
      </div>
      <div
        className="shell-page"
        data-page="settings"
        hidden={!shown("settings")}
      >
        <SettingsPage
          active={shown("settings")}
          propertyId={propertyId || (propertyConfiguration?.property_id ?? "")}
          unitApi={unitApi ?? defaultUnitApi}
          capabilities={capabilities}
          earlier={{
            business: (
              <section className="workspace-panel">
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
                      current version for every change. The fixed timezone is
                      shown as an authoritative value, not an editable source
                      field.
                    </p>
                  ) : (
                    <p>
                      Enter the exact Property identifier. The server must
                      confirm
                      <code> settings.manage</code> or{" "}
                      <code>property.manage</code> for that Property before any
                      management screen or editing control is shown.
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
                        <h4 id="property-source-heading">
                          Property source data
                        </h4>
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
                          <button type="submit">
                            Save Property source data
                          </button>
                        </form>
                      </section>
                      <section aria-labelledby="payment-methods-heading">
                        <h4 id="payment-methods-heading">Payment Methods</h4>
                        {propertyConfiguration.payment_methods.length === 0 ? (
                          <p>No Payment Methods are configured.</p>
                        ) : (
                          <ul className="record-list">
                            {propertyConfiguration.payment_methods.map(
                              (method) => (
                                <li key={method.code}>
                                  <label>
                                    <input
                                      checked={method.accepted}
                                      onChange={(event) => {
                                        const accepted =
                                          event.currentTarget.checked;
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
                                    {method.display_name} ({method.code})
                                    accepted
                                  </label>
                                </li>
                              ),
                            )}
                          </ul>
                        )}
                        <form
                          className="form-stack"
                          onSubmit={addPaymentMethod}
                        >
                          <div className="form-field">
                            <label htmlFor="payment-method-code">
                              Method code
                            </label>
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
                          Retired methods remain visible and are never deleted
                          from configuration history.
                        </p>
                      </section>
                    </div>
                  )}
                </section>
              </section>
            ),
            rates: (
              <section className="workspace-panel">
                <ConfigurationManagement
                  api={effectiveConfigApi}
                  propertyId={propertyConfiguration?.property_id ?? ""}
                />
              </section>
            ),
            users: (
              <section className="workspace-panel">
                <section
                  aria-labelledby="administration-heading"
                  className="information-card"
                >
                  <h3 id="administration-heading">
                    Capability-checked administration
                  </h3>
                  <p>
                    Enter the exact property identifier. The server decides
                    whether this session has the required capability; role
                    labels are never treated as authority.
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
                        {formatDateTime(issuedPassword.expires_at)}, and the
                        person must choose a new password when they sign in. It
                        is shown only once.
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
                                    {user.username} · {user.lifecycle_state} ·
                                    MFA {user.mfa_policy_class}
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
                                        setPendingCommand({
                                          kind: "revoke",
                                          user,
                                        });
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
                          This current configuration is audit context, not proof
                          of authority. Historical authorization events remain
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
                            {administration.authorizationHistory.map(
                              (event) => (
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
                              ),
                            )}
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
                              <label htmlFor="new-display-name">
                                Display name
                              </label>
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
                            <button type="submit">
                              Create audited account
                            </button>
                          </form>
                          <form
                            className="form-stack nested-form"
                            onSubmit={createRoleBundle}
                          >
                            <h5>Create role bundle</h5>
                            <div className="form-field">
                              <label htmlFor="bundle-name">Bundle name</label>
                              <input
                                id="bundle-name"
                                name="bundle-name"
                                required
                              />
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
                                  <label htmlFor="assignment-user">
                                    Account
                                  </label>
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
                                    {administration.roleBundles.map(
                                      (bundle) => (
                                        <option
                                          key={bundle.role_bundle_id}
                                          value={bundle.role_bundle_id}
                                        >
                                          {bundle.name}
                                        </option>
                                      ),
                                    )}
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
                                The server permits only Owner recovery of
                                Manager or Staff. It rejects Staff recovery of
                                Owner or Manager and does not grant Manager
                                recovery of Staff.
                              </p>
                              <div className="form-field">
                                <label htmlFor="recovery-user">Account</label>
                                <select id="recovery-user" name="recovery-user">
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
                      <h4 id="confirmation-heading">
                        Confirm protected command
                      </h4>
                      <p>
                        {pendingCommand.kind === "disable"
                          ? "Disabling this account also revokes every applicable session."
                          : pendingCommand.kind === "recover"
                            ? "Recovery gives the selected account a one-time password, may reset MFA, and revokes every applicable session."
                            : "This revokes every applicable session for the selected account."}{" "}
                        The server records the acting account and request for
                        audit.
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
            ),
          }}
          healthApi={healthApi}
          language={language}
          myUserId={session.actor_id}
          reauthenticate={reauthenticateForSettings}
          usersApi={administrationApi}
          businessApi={businessApi}
          ratesApi={effectiveConfigApi}
        />
      </div>
    </AppShell>
  );
}
