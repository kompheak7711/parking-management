import { FormEvent, useEffect, useRef, useState } from "react";

import {
  CustomerApi,
  CustomerConflictError,
  CustomerIdNumberInUseError,
  CustomerDetail,
  CustomerFinancialSummary,
  CustomerListItem,
  CustomerRequestError,
  CustomerSource,
  CustomerUnavailableError,
  customerApi,
} from "./customerClient";

export interface CustomerManagementProps {
  actorId?: string;
  api?: CustomerApi;
  mutationCoordinationAvailable?: boolean;
  onCommandBusyChange?: (busy: boolean) => void;
  onOpenAccountLedger?: (selection: {
    customerId: string;
    propertyId: string;
  }) => void;
  onDirtyStateChange?: (dirty: boolean) => void;
  onReconciled?: (
    requirement: CustomerReconciliationRequirement,
  ) => boolean | undefined | Promise<boolean | undefined>;
  onReconciliationRequired?: (
    requirement: CustomerReconciliationRequirement,
  ) => boolean | undefined | Promise<boolean | undefined>;
  reconciliationRequirement?: CustomerReconciliationRequirement | null;
}

export interface CustomerReconciliationRequirement {
  actorId: string;
  commandNonce: string;
  kind: "create" | "update" | "deactivate";
  customerId: string;
  propertyId: string;
  resultFingerprint: string;
  requestFingerprint: string;
  expectedVersion?: number;
  createSource?: CustomerSource;
  updateSource?: Partial<CustomerSource>;
  deactivationReason?: string;
}

const CUSTOMER_PHONE_PATTERN = String.raw`(?=.*[0-9])[0-9+\(\). \-]*`;

interface CustomerReconciliationProof {
  outcome: "exists" | "absent";
  requirement: CustomerReconciliationRequirement;
}

type CustomerActiveFilter = "all" | "active" | "deactivated";
type CustomerDraftKind = "create" | "update" | "deactivate";
type CustomerSourceField =
  | "legal_name"
  | "phone_number"
  | "email_address"
  | "contact_address"
  | "memo"
  | "id_document_number";

interface PendingUpdateReview {
  customerId: string;
  legalName: string;
  draft: CustomerSource;
}

function message(error: unknown): string {
  if (error instanceof CustomerUnavailableError) {
    return "Customer access is unavailable for this session.";
  }
  if (error instanceof CustomerConflictError) return error.message;
  if (error instanceof CustomerRequestError) {
    const fields =
      error.fields.length === 0
        ? ""
        : ` Invalid field(s): ${error.fields.join(", ")}.`;
    const request =
      error.requestId === null ? "" : ` Correlation ID: ${error.requestId}.`;
    return `${error.message}${fields}${request}`;
  }
  return "The Customer request was not completed. Retry when the service is available.";
}

function isPythonStripCodePoint(codePoint: number): boolean {
  return (
    (codePoint >= 0x0009 && codePoint <= 0x000d) ||
    (codePoint >= 0x001c && codePoint <= 0x0020) ||
    codePoint === 0x0085 ||
    codePoint === 0x00a0 ||
    codePoint === 0x1680 ||
    (codePoint >= 0x2000 && codePoint <= 0x200a) ||
    codePoint === 0x2028 ||
    codePoint === 0x2029 ||
    codePoint === 0x202f ||
    codePoint === 0x205f ||
    codePoint === 0x3000
  );
}

export function normalizeCustomerText(value: string): string {
  let start = 0;
  let end = value.length;
  while (start < end && isPythonStripCodePoint(value.charCodeAt(start))) {
    start += 1;
  }
  while (end > start && isPythonStripCodePoint(value.charCodeAt(end - 1))) {
    end -= 1;
  }
  return value.slice(start, end);
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? normalizeCustomerText(value) : "";
}

function optionalFormString(data: FormData, name: string): string | null {
  const value = formString(data, name);
  return value === "" ? null : value;
}

function usd(cents: number): string {
  if (!Number.isSafeInteger(cents)) return "Unsupported amount";
  const negative = cents < 0;
  const minor = BigInt(Math.abs(cents));
  const whole = (minor / 100n).toLocaleString("en-US");
  const fraction = (minor % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}$${whole}.${fraction}`;
}

const UPDATE_FORM_FIELDS: readonly (readonly [CustomerSourceField, string])[] =
  [
    ["legal_name", "edit-customer-legal-name"],
    ["phone_number", "edit-customer-phone"],
    ["email_address", "edit-customer-email"],
    ["contact_address", "edit-customer-address"],
    ["memo", "edit-customer-memo"],
    ["id_document_number", "edit-customer-id-number"],
  ];

function differingUpdateFields(
  current: CustomerDetail,
  draft: CustomerSource | null,
): ReadonlySet<CustomerSourceField> {
  if (draft === null) return new Set();
  return new Set(
    UPDATE_FORM_FIELDS.filter(([field]) =>
      field === "legal_name"
        ? draft[field] !== current[field]
        : (draft[field] ?? null) !== current[field],
    ).map(([field]) => field),
  );
}

function updateSource(
  data: FormData,
  current: CustomerDetail,
  edited: ReadonlySet<CustomerSourceField>,
): CustomerSource {
  return {
    legal_name: edited.has("legal_name")
      ? formString(data, "edit-customer-legal-name")
      : current.legal_name,
    phone_number: edited.has("phone_number")
      ? optionalFormString(data, "edit-customer-phone")
      : current.phone_number,
    email_address: edited.has("email_address")
      ? optionalFormString(data, "edit-customer-email")
      : current.email_address,
    contact_address: edited.has("contact_address")
      ? optionalFormString(data, "edit-customer-address")
      : current.contact_address,
    memo: edited.has("memo")
      ? optionalFormString(data, "edit-customer-memo")
      : current.memo,
    id_document_number: edited.has("id_document_number")
      ? optionalFormString(data, "edit-customer-id-number")
      : current.id_document_number,
    confirmed_distinct: data.get("edit-customer-confirmed-distinct") === "on",
  };
}

function createSource(data: FormData): CustomerSource {
  return {
    legal_name: formString(data, "customer-legal-name"),
    phone_number: optionalFormString(data, "customer-phone"),
    email_address: optionalFormString(data, "customer-email"),
    contact_address: optionalFormString(data, "customer-address"),
    memo: optionalFormString(data, "customer-memo"),
    id_document_number: formString(data, "customer-id-number"),
    confirmed_distinct: data.get("customer-confirmed-distinct") === "on",
  };
}

function changedCustomerSource(
  current: CustomerDetail,
  draft: CustomerSource,
  edited: ReadonlySet<CustomerSourceField>,
): Partial<CustomerSource> {
  const changed: Partial<CustomerSource> = {};
  if (edited.has("legal_name") && draft.legal_name !== current.legal_name)
    changed.legal_name = draft.legal_name;
  if (edited.has("phone_number") && draft.phone_number !== current.phone_number)
    changed.phone_number = draft.phone_number;
  if (
    edited.has("email_address") &&
    draft.email_address !== current.email_address
  )
    changed.email_address = draft.email_address;
  if (
    edited.has("contact_address") &&
    draft.contact_address !== current.contact_address
  )
    changed.contact_address = draft.contact_address;
  if (edited.has("memo") && draft.memo !== current.memo)
    changed.memo = draft.memo;
  if (
    edited.has("id_document_number") &&
    draft.id_document_number !== current.id_document_number
  )
    changed.id_document_number = draft.id_document_number;
  if (draft.confirmed_distinct) changed.confirmed_distinct = true;
  return changed;
}

function supportsStrictPhoneInput(value: string | null): boolean {
  return (
    value === null || (/[0-9]/.test(value) && /^[0-9+(). -]*$/.test(value))
  );
}

function supportsStrictEmailInput(value: string | null): boolean {
  if (value === null) return true;
  if (
    value !== normalizeCustomerText(value) ||
    !/^[\x21-\x7e]+$/.test(value) ||
    value.split("@").length !== 2
  ) {
    return false;
  }
  const [local, domain] = value.split("@") as [string, string];
  if (
    local.length === 0 ||
    local.length > 64 ||
    local.startsWith(".") ||
    local.endsWith(".") ||
    local.includes("..") ||
    !/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local) ||
    domain.length === 0 ||
    domain.length > 255 ||
    domain.startsWith(".") ||
    domain.endsWith(".") ||
    domain.includes("..")
  ) {
    return false;
  }
  return domain
    .split(".")
    .every(
      (label) =>
        label.length > 0 &&
        label.length <= 63 &&
        /^[A-Za-z0-9-]+$/.test(label) &&
        !label.startsWith("-") &&
        !label.endsWith("-"),
    );
}

function hasChangedCustomerSource(source: Partial<CustomerSource>): boolean {
  return (
    "legal_name" in source ||
    "phone_number" in source ||
    "email_address" in source ||
    "contact_address" in source ||
    "memo" in source ||
    "id_document_number" in source
  );
}

function mergeMutationHistory(
  previous: CustomerDetail,
  result: CustomerDetail,
): CustomerDetail {
  if (previous.customer_id !== result.customer_id) {
    return result;
  }
  if (
    previous.can_view_audit &&
    previous.audit_history_available &&
    result.can_view_audit &&
    !result.audit_history_available
  ) {
    return {
      ...result,
      audit_history: previous.audit_history,
      audit_history_next_cursor: null,
      audit_history_available: false,
    };
  }
  if (
    !previous.can_view_audit ||
    !previous.audit_history_available ||
    !result.can_view_audit ||
    !result.audit_history_available
  ) {
    return result;
  }
  const eventIds = new Set(result.audit_history.map((event) => event.event_id));
  return {
    ...result,
    audit_history: [
      ...result.audit_history,
      ...previous.audit_history.filter(
        (event) => !eventIds.has(event.event_id),
      ),
    ],
    audit_history_next_cursor:
      result.audit_history_next_cursor ?? previous.audit_history_next_cursor,
  };
}

function absentReconciliationCopy(
  kind: CustomerReconciliationRequirement["kind"],
): { button: string; status: string } {
  if (kind === "create") {
    return {
      button: "I verified the Customer was not created",
      status:
        "The prior creation was not committed. A retry will reuse the same exact command identity.",
    };
  }
  if (kind === "update") {
    return {
      button: "I verified the Customer update was not committed",
      status:
        "The prior Customer update was not committed. A retry will reuse the same exact command identity.",
    };
  }
  return {
    button: "I verified the Customer deactivation was not committed",
    status:
      "The prior Customer deactivation was not committed. A retry will reuse the same exact command identity.",
  };
}

function relationshipCount(
  detail: CustomerDetail,
  name: keyof CustomerDetail["relationships"],
) {
  return detail.relationships[name].length;
}

function auditValue(value: unknown): string {
  if (value === null || value === undefined) return "None";
  return JSON.stringify(value, null, 2);
}

function sameReconciliationRequirement(
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

function fingerprintPayload(
  kind: "update" | "deactivate",
  customer: Pick<
    CustomerDetail,
    | "customer_id"
    | "legal_name"
    | "phone_number"
    | "email_address"
    | "contact_address"
    | "memo"
    | "id_document_number"
    | "version"
    | "active"
    | "deactivation_reason"
  >,
): string {
  return JSON.stringify(
    kind === "update"
      ? [
          kind,
          customer.customer_id,
          customer.version,
          customer.active,
          customer.legal_name,
          customer.phone_number,
          normalizedEmailSourceValue(customer.email_address),
          customer.contact_address,
          customer.memo,
          customer.id_document_number,
        ]
      : [
          kind,
          customer.customer_id,
          customer.version,
          customer.active,
          customer.deactivation_reason,
        ],
  );
}

export async function customerReconciliationResultFingerprint(
  kind: "update" | "deactivate",
  customer: Parameters<typeof fingerprintPayload>[1],
): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(fingerprintPayload(kind, customer)),
    );
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    return null;
  }
}

export async function customerCreateRequestFingerprint(
  source: CustomerSource,
): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(
        JSON.stringify([
          "create",
          normalizeCustomerText(source.legal_name),
          normalizedOptionalSourceValue(source.phone_number),
          normalizedEmailSourceValue(source.email_address),
          normalizedOptionalSourceValue(source.contact_address),
          normalizedOptionalSourceValue(source.memo),
          normalizedOptionalSourceValue(source.id_document_number),
          source.confirmed_distinct === true,
        ]),
      ),
    );
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    return null;
  }
}

function normalizedOptionalSourceValue(value: string | null | undefined) {
  const normalized =
    value === undefined ? undefined : normalizeCustomerText(value ?? "");
  return normalized === undefined || normalized === "" ? null : normalized;
}

function normalizedEmailSourceValue(value: string | null | undefined) {
  const normalized = normalizedOptionalSourceValue(value);
  if (normalized === null) return normalized;
  const separator = normalized.lastIndexOf("@");
  if (separator <= 0 || separator !== normalized.indexOf("@")) {
    return normalized;
  }
  return `${normalized.slice(0, separator)}@${normalized
    .slice(separator + 1)
    .toLowerCase()}`;
}

export async function customerCreateResultFingerprint(
  customerId: string,
  source: CustomerSource,
): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(
        JSON.stringify([
          "create-result",
          customerId,
          1,
          true,
          normalizeCustomerText(source.legal_name),
          normalizedOptionalSourceValue(source.phone_number),
          normalizedEmailSourceValue(source.email_address),
          normalizedOptionalSourceValue(source.contact_address),
          normalizedOptionalSourceValue(source.memo),
          normalizedOptionalSourceValue(source.id_document_number),
        ]),
      ),
    );
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    return null;
  }
}

export async function customerUpdateRequestFingerprint(
  current: CustomerDetail,
  changed: Partial<CustomerSource>,
): Promise<string | null> {
  try {
    const fields = (
      [
        "legal_name",
        "phone_number",
        "email_address",
        "contact_address",
        "memo",
        "id_document_number",
      ] as const
    )
      .filter((field) => Object.hasOwn(changed, field))
      .map((field) => [
        field,
        field === "legal_name"
          ? normalizeCustomerText(changed.legal_name ?? "")
          : field === "email_address"
            ? normalizedEmailSourceValue(changed.email_address)
            : normalizedOptionalSourceValue(changed[field]),
      ]);
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(
        JSON.stringify([
          "update-request",
          current.customer_id,
          current.version,
          changed.confirmed_distinct === true,
          fields,
        ]),
      ),
    );
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    return null;
  }
}

export function CustomerManagement({
  actorId = "test-actor",
  api = customerApi,
  mutationCoordinationAvailable = true,
  onCommandBusyChange,
  onOpenAccountLedger,
  onDirtyStateChange,
  onReconciled,
  onReconciliationRequired,
  reconciliationRequirement = null,
}: CustomerManagementProps) {
  const [propertyId, setPropertyId] = useState("");
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<CustomerActiveFilter>("all");
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [reuseCandidates, setReuseCandidates] = useState<CustomerListItem[]>(
    [],
  );
  const [canManage, setCanManage] = useState(false);
  const [selected, setSelected] = useState<CustomerDetail | null>(null);
  const [financial, setFinancial] = useState<CustomerFinancialSummary | null>(
    null,
  );
  const [financialUnavailable, setFinancialUnavailable] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editDraft, setEditDraft] = useState<CustomerSource | null>(null);
  const [editedFields, setEditedFields] = useState<
    ReadonlySet<CustomerSourceField>
  >(new Set());
  const [pendingUpdateReview, setPendingUpdateReview] =
    useState<PendingUpdateReview | null>(null);
  const [deactivationDraft, setDeactivationDraft] = useState("");
  const [createFormRevision, setCreateFormRevision] = useState(0);
  const [createDraft, setCreateDraft] = useState<CustomerSource | null>(null);
  const [reconciliationProof, setReconciliationProof] =
    useState<CustomerReconciliationProof | null>(null);
  const [reconciledCreateCustomerId, setReconciledCreateCustomerId] = useState<
    string | null
  >(null);
  const [reconciledRetryRequirement, setReconciledRetryRequirement] =
    useState<CustomerReconciliationRequirement | null>(null);
  const sequence = useRef(0);
  const reconciliationSequence = useRef(0);
  const reconciliationRequirementRef =
    useRef<CustomerReconciliationRequirement | null>(reconciliationRequirement);
  const autoRestoredCreateNonce = useRef<string | null>(null);
  const mounted = useRef(false);
  const dirtyDrafts = useRef<Record<CustomerDraftKind, boolean>>({
    create: false,
    update: false,
    deactivate: false,
  });

  function hasDirtyDrafts(): boolean {
    return Object.values(dirtyDrafts.current).some(Boolean);
  }

  function clearDirtyDrafts() {
    dirtyDrafts.current = { create: false, update: false, deactivate: false };
    setEditedFields(new Set());
    onDirtyStateChange?.(false);
  }

  function setDraftDirty(kind: CustomerDraftKind, dirty: boolean) {
    dirtyDrafts.current[kind] = dirty;
    onDirtyStateChange?.(hasDirtyDrafts());
  }

  async function reserveReconciliation(
    requirement: CustomerReconciliationRequirement,
  ): Promise<boolean> {
    try {
      return (await onReconciliationRequired?.(requirement)) !== false;
    } catch {
      return false;
    }
  }

  function buildCommandRequirement(
    kind: CustomerReconciliationRequirement["kind"],
    customerId: string,
    exactPropertyId: string,
    resultFingerprint: string,
    requestFingerprint: string,
    commandCreateSource?: CustomerSource,
    expectedVersion?: number,
    commandUpdateSource?: Partial<CustomerSource>,
    commandDeactivationReason?: string,
  ): CustomerReconciliationRequirement {
    if (
      reconciledRetryRequirement !== null &&
      reconciledRetryRequirement.actorId === actorId &&
      reconciledRetryRequirement.kind === kind &&
      reconciledRetryRequirement.customerId === customerId &&
      reconciledRetryRequirement.propertyId === exactPropertyId &&
      reconciledRetryRequirement.resultFingerprint === resultFingerprint &&
      reconciledRetryRequirement.requestFingerprint === requestFingerprint &&
      reconciledRetryRequirement.expectedVersion === expectedVersion
    ) {
      return reconciledRetryRequirement;
    }
    return {
      actorId,
      commandNonce: crypto.randomUUID(),
      kind,
      customerId,
      propertyId: exactPropertyId,
      resultFingerprint,
      requestFingerprint,
      ...(expectedVersion === undefined ? {} : { expectedVersion }),
      ...(commandCreateSource === undefined
        ? {}
        : { createSource: commandCreateSource }),
      ...(commandUpdateSource === undefined
        ? {}
        : { updateSource: commandUpdateSource }),
      ...(commandDeactivationReason === undefined
        ? {}
        : { deactivationReason: commandDeactivationReason }),
    };
  }

  function preparationWasCancelled(preparationSequence: number): boolean {
    return !mounted.current || preparationSequence !== sequence.current;
  }

  function commandGateAllows(
    kind: CustomerReconciliationRequirement["kind"],
    customerId?: string,
  ): boolean {
    return (
      mutationCoordinationAvailable &&
      (reconciliationRequirement === null ||
        (reconciledRetryRequirement?.kind === kind &&
          (customerId === undefined ||
            reconciledRetryRequirement.customerId === customerId) &&
          sameReconciliationRequirement(
            reconciledRetryRequirement,
            reconciliationRequirement,
          )))
    );
  }

  function hasDraftForDifferentCustomer(customerId: string): boolean {
    return (
      selected !== null &&
      selected.customer_id !== customerId &&
      (dirtyDrafts.current.update || dirtyDrafts.current.deactivate)
    );
  }

  function updateDraftMatchesRequirement(
    requirement: CustomerReconciliationRequirement,
  ): boolean {
    if (
      requirement.kind !== "update" ||
      requirement.updateSource === undefined ||
      editDraft === null ||
      selected?.customer_id !== requirement.customerId
    ) {
      return false;
    }
    const requiredFields = UPDATE_FORM_FIELDS.map(([field]) => field).filter(
      (field) => Object.hasOwn(requirement.updateSource ?? {}, field),
    );
    if (
      requiredFields.length !== editedFields.size ||
      requiredFields.some((field) => !editedFields.has(field))
    ) {
      return false;
    }
    return (
      requiredFields.every(
        (field) =>
          (editDraft[field] ?? null) ===
          (requirement.updateSource?.[field] ?? null),
      ) &&
      (editDraft.confirmed_distinct === true) ===
        (requirement.updateSource.confirmed_distinct === true)
    );
  }

  function deactivationDraftMatchesRequirement(
    requirement: CustomerReconciliationRequirement,
  ): boolean {
    return (
      requirement.kind === "deactivate" &&
      requirement.deactivationReason !== undefined &&
      selected?.customer_id === requirement.customerId &&
      deactivationDraft === requirement.deactivationReason
    );
  }

  function hasUnrelatedSameCustomerDraft(
    requirement: CustomerReconciliationRequirement,
  ): boolean {
    if (selected?.customer_id !== requirement.customerId) return false;
    if (requirement.kind === "update") {
      return (
        dirtyDrafts.current.update &&
        !updateDraftMatchesRequirement(requirement)
      );
    }
    if (requirement.kind === "deactivate") {
      return (
        dirtyDrafts.current.deactivate &&
        !deactivationDraftMatchesRequirement(requirement)
      );
    }
    return false;
  }

  useEffect(() => {
    reconciliationRequirementRef.current = reconciliationRequirement;
    reconciliationSequence.current += 1;
    setReconciliationProof(null);
    const replacedAutoRestoredDraft =
      autoRestoredCreateNonce.current !== null &&
      (reconciliationRequirement === null ||
        reconciliationRequirement.kind !== "create" ||
        reconciliationRequirement.commandNonce !==
          autoRestoredCreateNonce.current);
    if (replacedAutoRestoredDraft) {
      autoRestoredCreateNonce.current = null;
      setCreateDraft(null);
      setCreateFormRevision((current) => current + 1);
      setDraftDirty("create", false);
    }
    if (reconciliationRequirement !== null) {
      setReconciledRetryRequirement((current) =>
        current === null ||
        sameReconciliationRequirement(current, reconciliationRequirement)
          ? current
          : null,
      );
      if (
        reconciliationRequirement.kind === "create" &&
        reconciliationRequirement.createSource !== undefined &&
        (!dirtyDrafts.current.create || replacedAutoRestoredDraft)
      ) {
        setCreateDraft(reconciliationRequirement.createSource);
        autoRestoredCreateNonce.current =
          reconciliationRequirement.commandNonce;
        setCreateFormRevision((current) => current + 1);
        setDraftDirty("create", true);
      }
    }
  }, [
    reconciliationRequirement?.actorId,
    reconciliationRequirement?.commandNonce,
    reconciliationRequirement?.customerId,
    reconciliationRequirement?.kind,
    reconciliationRequirement?.propertyId,
    reconciliationRequirement?.requestFingerprint,
    reconciliationRequirement?.resultFingerprint,
    reconciliationRequirement?.expectedVersion,
    reconciliationRequirement?.createSource,
  ]);

  useEffect(() => {
    if (
      reconciledRetryRequirement === null ||
      (reconciliationRequirement !== null &&
        sameReconciliationRequirement(
          reconciledRetryRequirement,
          reconciliationRequirement,
        ))
    ) {
      return;
    }
    setReconciledRetryRequirement(null);
    setReconciledCreateCustomerId(null);
  }, [reconciledRetryRequirement, reconciliationRequirement]);

  useEffect(() => {
    mounted.current = true;
    function warnBeforeUnload(event: BeforeUnloadEvent) {
      if (!hasDirtyDrafts()) return;
      event.preventDefault();
    }
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => {
      mounted.current = false;
      sequence.current += 1;
      onCommandBusyChange?.(false);
      window.removeEventListener("beforeunload", warnBeforeUnload);
    };
  }, [onCommandBusyChange]);

  function invalidate() {
    sequence.current += 1;
    setLoading(false);
    setCustomers([]);
    setNextCursor(null);
    setReuseCandidates([]);
    setCanManage(false);
    setSelected(null);
    setFinancial(null);
    setFinancialUnavailable(false);
    setEditDraft(null);
    setEditedFields(new Set());
    setPendingUpdateReview(null);
    setDeactivationDraft("");
    setCreateFormRevision((current) => current + 1);
    setCreateDraft(null);
    autoRestoredCreateNonce.current = null;
    clearDirtyDrafts();
  }

  function confirmDraftDiscard(preserveReconciledCreate = false): boolean {
    if (!hasDirtyDrafts()) return true;
    if (
      preserveReconciledCreate &&
      (reconciledRetryRequirement?.kind === "create" ||
        reconciliationRequirement?.kind === "create") &&
      dirtyDrafts.current.create &&
      !dirtyDrafts.current.update &&
      !dirtyDrafts.current.deactivate
    ) {
      return true;
    }
    if (
      !window.confirm(
        "Discard the unsaved Customer form values and change the current view?",
      )
    ) {
      setStatus(
        "The view was not changed; unsaved Customer values were preserved.",
      );
      return false;
    }
    clearDirtyDrafts();
    setCreateFormRevision((current) => current + 1);
    setCreateDraft(null);
    autoRestoredCreateNonce.current = null;
    setEditDraft(null);
    setEditedFields(new Set());
    setPendingUpdateReview(null);
    setDeactivationDraft("");
    return true;
  }

  function invalidateCustomerList() {
    setCustomers([]);
    setNextCursor(null);
  }

  function applyManagementDowngrade() {
    setCanManage(false);
    setReuseCandidates([]);
    setCreateDraft(null);
    autoRestoredCreateNonce.current = null;
    setCreateFormRevision((current) => current + 1);
    setEditDraft(null);
    setEditedFields(new Set());
    setPendingUpdateReview(null);
    setDeactivationDraft("");
    clearDirtyDrafts();
  }

  function retainManagementCapability(current: CustomerDetail): boolean {
    if (current.can_manage) return true;
    applyManagementDowngrade();
    return false;
  }

  function loadCustomers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmDraftDiscard(true)) return;
    const operation = ++sequence.current;
    setLoading(true);
    setSelected(null);
    setFinancial(null);
    setFinancialUnavailable(false);
    setStatus("Loading the minimized Customer list…");
    setReconciliationProof(null);
    void api
      .list(propertyId, {
        ...(query.trim() === "" ? {} : { query: query.trim() }),
        ...(activeFilter === "all"
          ? {}
          : { active: activeFilter === "active" }),
      })
      .then((page) => {
        if (operation !== sequence.current) return;
        setCustomers(page.items);
        setNextCursor(page.next_cursor);
        setCanManage(page.can_manage);
        if (!page.can_manage) applyManagementDowngrade();
        setStatus(
          reconciliationRequirement !== null
            ? "The minimized Customer list was loaded, but it cannot prove the prior command outcome. Check the exact command identity before retrying."
            : page.items.length === 0
              ? "No Customers were found for this Property."
              : `${String(page.items.length)} minimized Customer record(s) loaded.`,
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        invalidate();
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function loadMoreCustomers() {
    if (nextCursor === null) return;
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Loading the next bounded Customer page…");
    void api
      .list(propertyId, {
        ...(query.trim() === "" ? {} : { query: query.trim() }),
        ...(activeFilter === "all"
          ? {}
          : { active: activeFilter === "active" }),
        cursor: nextCursor,
      })
      .then((page) => {
        if (operation !== sequence.current) return;
        setCustomers((current) => [...current, ...page.items]);
        setNextCursor(page.next_cursor);
        setCanManage(page.can_manage);
        if (!page.can_manage) {
          setSelected((current) =>
            current === null
              ? null
              : { ...current, can_manage: false, can_deactivate: false },
          );
          applyManagementDowngrade();
          setStatus(
            "The next Customer page was loaded. Management access changed, so stale Customer actions and drafts were removed.",
          );
          return;
        }
        setStatus("The next Customer page was loaded.");
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof CustomerUnavailableError) invalidate();
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function openCustomer(
    customerId: string,
    restoredDraft: CustomerSource | null = null,
    preservePendingReview = false,
  ) {
    if (preservePendingReview) {
      const preservingCurrentPendingUpdate =
        pendingUpdateReview !== null &&
        selected?.customer_id === pendingUpdateReview.customerId;
      const hasUnrelatedDraft =
        dirtyDrafts.current.deactivate ||
        (dirtyDrafts.current.update && !preservingCurrentPendingUpdate);
      if (
        hasUnrelatedDraft &&
        !window.confirm(
          "Discard unrelated unsaved Customer values and continue the pending reuse review?",
        )
      ) {
        setStatus(
          "Reuse navigation was cancelled; unrelated Customer values were preserved.",
        );
        return;
      }
      if (hasUnrelatedDraft) {
        dirtyDrafts.current = {
          create: dirtyDrafts.current.create,
          update: pendingUpdateReview !== null,
          deactivate: false,
        };
        onDirtyStateChange?.(
          dirtyDrafts.current.create || pendingUpdateReview !== null,
        );
      }
    } else if (!confirmDraftDiscard()) {
      return;
    }
    const operation = ++sequence.current;
    setLoading(true);
    setReuseCandidates([]);
    setEditDraft(null);
    setEditedFields(new Set());
    setDraftDirty("deactivate", false);
    if (!preservePendingReview) setPendingUpdateReview(null);
    setDeactivationDraft("");
    setSelected(null);
    setFinancial(null);
    setFinancialUnavailable(false);
    setStatus("Loading Customer detail and financial summary…");
    void Promise.allSettled([
      api.get(customerId),
      api.financialSummary(customerId),
    ])
      .then(([detailResult, summaryResult]) => {
        if (operation !== sequence.current) return;
        if (detailResult.status === "rejected") {
          if (detailResult.reason instanceof CustomerUnavailableError) {
            invalidate();
          }
          setStatus(message(detailResult.reason));
          return;
        }
        const canRetainDrafts = retainManagementCapability(detailResult.value);
        setSelected(detailResult.value);
        setEditDraft(canRetainDrafts ? restoredDraft : null);
        setEditedFields(
          canRetainDrafts
            ? differingUpdateFields(detailResult.value, restoredDraft)
            : new Set(),
        );
        setDraftDirty(
          "update",
          canRetainDrafts &&
            (restoredDraft !== null ||
              (preservePendingReview && pendingUpdateReview !== null)),
        );
        if (summaryResult.status === "fulfilled") {
          setFinancial(summaryResult.value);
          setStatus("Customer detail loaded through explicit navigation.");
          return;
        }
        if (summaryResult.reason instanceof CustomerUnavailableError) {
          invalidate();
          setStatus(message(summaryResult.reason));
          return;
        }
        setFinancial(null);
        setFinancialUnavailable(true);
        setStatus(
          "Customer detail loaded. The independent financial summary is temporarily unavailable.",
        );
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function loadOlderHistory() {
    const current = selected;
    if (current === null) return;
    const historyCursor = current.audit_history_next_cursor;
    if (historyCursor === null) return;
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Loading the next bounded Customer audit-history page…");
    void api
      .get(current.customer_id, historyCursor)
      .then(async (older) => {
        if (operation !== sequence.current) return;
        if (
          older.can_view_audit &&
          older.audit_history_available &&
          older.version !== current.version
        ) {
          invalidateCustomerList();
          setStatus(
            "Customer changed while history was loading; restarting from the newest audit page…",
          );
          const fresh = await api.get(current.customer_id);
          if (operation !== sequence.current) return;
          retainManagementCapability(fresh);
          setSelected(fresh);
          setStatus(
            "Customer changed while history was loading. The newest audit page was reloaded.",
          );
          return;
        }
        if (older.version !== current.version) invalidateCustomerList();
        retainManagementCapability(older);
        setSelected({
          ...older,
          audit_history:
            older.can_view_audit && older.audit_history_available
              ? [...current.audit_history, ...older.audit_history]
              : [],
          audit_history_next_cursor:
            older.can_view_audit && older.audit_history_available
              ? older.audit_history_next_cursor
              : null,
        });
        setStatus("The next Customer audit-history page was loaded.");
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof CustomerUnavailableError) invalidate();
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function checkReconciliationCommand() {
    if (
      reconciliationRequirement === null ||
      reconciliationRequirement.actorId !== actorId
    ) {
      return;
    }
    const checkedRequirement = { ...reconciliationRequirement };
    const operation = ++sequence.current;
    const reconciliationOperation = ++reconciliationSequence.current;
    setLoading(true);
    setStatus("Checking the exact Customer command identity…");
    const reconciliation = api.commandStatus(
      reconciliationRequirement.propertyId,
      reconciliationRequirement.customerId,
      reconciliationRequirement.kind,
      reconciliationRequirement.commandNonce,
    );
    void reconciliation
      .then(async (proof) => {
        if (
          operation !== sequence.current ||
          reconciliationOperation !== reconciliationSequence.current ||
          !sameReconciliationRequirement(
            checkedRequirement,
            reconciliationRequirementRef.current,
          )
        ) {
          return;
        }
        if (!proof.recorded && proof.expired) {
          setReconciliationProof(null);
          setStatus(
            "The server retention window for this exact Customer command has expired, so its outcome is unknown. The command gate remains active; do not retry or clear it.",
          );
          return;
        }
        if (!proof.recorded || proof.customer === null) {
          setPropertyId(checkedRequirement.propertyId);
          setReconciliationProof({
            outcome: "absent",
            requirement: checkedRequirement,
          });
          setStatus(
            "The exact Customer command was not committed. Confirm this authoritative result before retrying; the retry will reuse the same command identity.",
          );
          return;
        }
        const proofFingerprint =
          checkedRequirement.kind === "create"
            ? await customerCreateResultFingerprint(
                checkedRequirement.customerId,
                proof.customer,
              )
            : await customerReconciliationResultFingerprint(
                checkedRequirement.kind,
                proof.customer,
              );
        if (proofFingerprint !== checkedRequirement.resultFingerprint) {
          setReconciliationProof(null);
          setStatus(
            "The recorded Customer result does not match the exact pending command. The command gate remains active; do not retry.",
          );
          return;
        }
        const current = await api.get(checkedRequirement.customerId);
        if (
          operation !== sequence.current ||
          reconciliationOperation !== reconciliationSequence.current ||
          !sameReconciliationRequirement(
            checkedRequirement,
            reconciliationRequirementRef.current,
          )
        ) {
          return;
        }
        const preservingOtherCustomerDraft = hasDraftForDifferentCustomer(
          checkedRequirement.customerId,
        );
        const canRetainDrafts = retainManagementCapability(current);
        if (!preservingOtherCustomerDraft) {
          setPropertyId(checkedRequirement.propertyId);
          setSelected(current);
          setFinancial(null);
          setFinancialUnavailable(false);
        }
        setReconciliationProof({
          outcome: "exists",
          requirement: checkedRequirement,
        });
        setStatus(
          !canRetainDrafts
            ? "The exact Customer command identity now exists and its original result was verified, but Customer management access changed. Privileged drafts were removed; the command gate remains active until reconciliation is explicitly confirmed."
            : preservingOtherCustomerDraft
              ? "The exact Customer command identity now exists. Its original result was verified; the other Customer's unsaved values remain selected and were not reassigned. Explicitly confirm reconciliation."
              : "The exact Customer command identity now exists. Its original result was verified and current Customer detail was reloaded; explicitly confirm reconciliation.",
        );
      })
      .catch((error: unknown) => {
        if (
          operation !== sequence.current ||
          reconciliationOperation !== reconciliationSequence.current ||
          !sameReconciliationRequirement(
            checkedRequirement,
            reconciliationRequirementRef.current,
          )
        ) {
          return;
        }
        setReconciliationProof(null);
        if (error instanceof CustomerUnavailableError) invalidate();
        setStatus(
          error instanceof CustomerUnavailableError
            ? "The exact Customer command identity is not currently available. The command gate remains active; do not retry."
            : message(error),
        );
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  async function confirmReconciliationProof() {
    const proof = reconciliationProof;
    const requirement = reconciliationRequirement;
    if (
      proof === null ||
      requirement === null ||
      !sameReconciliationRequirement(proof.requirement, requirement)
    ) {
      return;
    }
    if (proof.outcome === "exists") {
      const preservedUnrelatedDraft =
        hasUnrelatedSameCustomerDraft(requirement);
      if (requirement.kind === "create" && createDraft !== null) {
        const draftFingerprint =
          await customerCreateRequestFingerprint(createDraft);
        if (draftFingerprint === requirement.requestFingerprint) {
          setCreateDraft(null);
          autoRestoredCreateNonce.current = null;
          setReconciledCreateCustomerId(null);
          setCreateFormRevision((current) => current + 1);
          setDraftDirty("create", false);
        }
      }
      if (
        requirement.kind === "update" &&
        updateDraftMatchesRequirement(requirement)
      ) {
        setEditDraft(null);
        setEditedFields(new Set());
        const preservesOtherPendingUpdate =
          pendingUpdateReview !== null &&
          pendingUpdateReview.customerId !== requirement.customerId;
        setPendingUpdateReview((current) =>
          current?.customerId === requirement.customerId ? null : current,
        );
        setDraftDirty("update", preservesOtherPendingUpdate);
      }
      if (
        requirement.kind === "deactivate" &&
        deactivationDraftMatchesRequirement(requirement)
      ) {
        setDeactivationDraft("");
        setDraftDirty("deactivate", false);
      }
      setReconciledRetryRequirement(null);
      void onReconciled?.(requirement);
      setReconciliationProof(null);
      setStatus(
        preservedUnrelatedDraft
          ? "The prior Customer command outcome was explicitly reconciled. This tab's different unsaved Customer values were preserved."
          : "The prior Customer command outcome was explicitly reconciled.",
      );
      return;
    }
    if (requirement.kind === "create") {
      if (requirement.createSource === undefined) {
        setStatus(
          "The prior creation was absent, but its sealed original values are unavailable. The command gate remains active and the command cannot be retried.",
        );
        return;
      }
      const currentFingerprint =
        createDraft === null
          ? null
          : await customerCreateRequestFingerprint(createDraft);
      if (currentFingerprint !== requirement.requestFingerprint) {
        setStatus(
          "The prior creation was absent. Your unrelated create draft was preserved; explicitly restore the sealed original values before preparing the exact retry.",
        );
        return;
      }
      setReconciledCreateCustomerId(requirement.customerId);
      setReconciledRetryRequirement(requirement);
      setReconciliationProof(null);
      setStatus(absentReconciliationCopy(requirement.kind).status);
      return;
    }
    if (hasDraftForDifferentCustomer(requirement.customerId)) {
      setStatus(
        "The prior Customer command was absent, but another Customer has unsaved values. Preserve or discard that draft before preparing this exact retry.",
      );
      return;
    }
    if (hasUnrelatedSameCustomerDraft(requirement)) {
      setStatus(
        "The prior Customer command was not committed, but this tab has different unsaved values for the same Customer. Those values were preserved; resolve them before preparing the exact retry.",
      );
      return;
    }
    if (requirement.expectedVersion === undefined) {
      setReconciledRetryRequirement(requirement);
      setReconciliationProof(null);
      setStatus(absentReconciliationCopy(requirement.kind).status);
      return;
    }

    const operation = ++sequence.current;
    setLoading(true);
    setStatus(
      "Reloading the current Customer version before allowing a retry…",
    );
    try {
      const current = await api.get(requirement.customerId);
      if (
        operation !== sequence.current ||
        !sameReconciliationRequirement(
          requirement,
          reconciliationRequirementRef.current,
        )
      ) {
        return;
      }
      setPropertyId(requirement.propertyId);
      setSelected(current);
      setFinancial(null);
      setFinancialUnavailable(false);
      if (!retainManagementCapability(current)) {
        setReconciledRetryRequirement(null);
        setReconciliationProof(null);
        setStatus(
          "Customer management access changed while the prior command was being reconciled. Privileged drafts were removed and the command gate remains active.",
        );
        return;
      }
      if (current.version !== requirement.expectedVersion || !current.active) {
        setReconciledRetryRequirement(null);
        const cleared = (await onReconciled?.(requirement)) !== false;
        setStatus(
          cleared
            ? "The prior Customer command was not committed, but its original version is now stale. The command gate was cleared and current detail was loaded for a fresh decision."
            : "The prior Customer command was not committed and its original version is now stale, but the durable command gate could not be cleared. Current detail was loaded; Customer commands remain blocked until the active gate is reconciled.",
        );
      } else {
        setReconciledRetryRequirement(requirement);
        if (
          requirement.kind === "update" &&
          requirement.updateSource !== undefined
        ) {
          const restoredDraft: CustomerSource = {
            legal_name: current.legal_name,
            phone_number: current.phone_number,
            email_address: current.email_address,
            contact_address: current.contact_address,
            memo: current.memo,
            id_document_number: current.id_document_number,
            ...requirement.updateSource,
          };
          setEditDraft(restoredDraft);
          setEditedFields(differingUpdateFields(current, restoredDraft));
          setDraftDirty("update", true);
        }
        if (
          requirement.kind === "deactivate" &&
          requirement.deactivationReason !== undefined
        ) {
          setDeactivationDraft(requirement.deactivationReason);
          setDraftDirty("deactivate", true);
        }
        setStatus(absentReconciliationCopy(requirement.kind).status);
      }
      setReconciliationProof(null);
    } catch (error: unknown) {
      if (operation !== sequence.current) return;
      if (error instanceof CustomerUnavailableError) invalidate();
      setStatus(
        error instanceof CustomerUnavailableError
          ? "The prior command was absent, but the current Customer version could not be verified. The command gate remains active."
          : message(error),
      );
    } finally {
      if (operation === sequence.current) setLoading(false);
    }
  }

  async function createCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      (dirtyDrafts.current.update ||
        dirtyDrafts.current.deactivate ||
        pendingUpdateReview !== null) &&
      !window.confirm(
        "Discard the other unsaved Customer values if this new Customer is created?",
      )
    ) {
      setStatus(
        "Customer creation was cancelled; the other unsaved Customer values were preserved.",
      );
      return;
    }
    const form = event.currentTarget;
    const data = new FormData(form);
    const source = createSource(data);
    if (source.legal_name === "") {
      setStatus(
        "Legal name must contain a non-whitespace character; no Customer command was sent.",
      );
      return;
    }
    const preparationSequence = sequence.current;
    setLoading(true);
    onCommandBusyChange?.(true);
    const requestFingerprint = await customerCreateRequestFingerprint(source);
    if (preparationWasCancelled(preparationSequence)) return;
    if (requestFingerprint === null) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Customer command coordination is unavailable. No creation was sent; restore secure request verification before retrying.",
      );
      return;
    }
    if (
      reconciledRetryRequirement?.kind === "create" &&
      reconciledRetryRequirement.requestFingerprint !== requestFingerprint
    ) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "The authoritatively absent creation can only be retried with its original Customer values. Restore those values before reusing its command identity.",
      );
      return;
    }
    const customerId = reconciledCreateCustomerId ?? crypto.randomUUID();
    const resultFingerprint = await customerCreateResultFingerprint(
      customerId,
      source,
    );
    if (preparationWasCancelled(preparationSequence)) return;
    if (resultFingerprint === null) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Customer command coordination is unavailable. No creation was sent; restore secure result verification before retrying.",
      );
      return;
    }
    const commandRequirement = buildCommandRequirement(
      "create",
      customerId,
      propertyId.trim(),
      resultFingerprint,
      requestFingerprint,
      source,
    );
    const reserved = await reserveReconciliation(commandRequirement);
    if (preparationWasCancelled(preparationSequence)) {
      if (reserved) await onReconciled?.(commandRequirement);
      return;
    }
    if (!reserved) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Another tab already has an unresolved Customer command. Reconcile that exact command before submitting another one.",
      );
      return;
    }
    const operation = ++sequence.current;
    setCreateDraft(source);
    setStatus("Creating a stable Customer identity…");
    void api
      .create(propertyId, customerId, source, commandRequirement.commandNonce)
      .then(async (created) => {
        if (operation !== sequence.current) return;
        void onReconciled?.(commandRequirement);
        setCustomers([]);
        setNextCursor(null);
        setSelected(created);
        setFinancial(null);
        setFinancialUnavailable(false);
        setReuseCandidates([]);
        setEditDraft(null);
        setPendingUpdateReview(null);
        setDeactivationDraft("");
        setCreateDraft(null);
        autoRestoredCreateNonce.current = null;
        setReconciledCreateCustomerId(null);
        setReconciledRetryRequirement(null);
        clearDirtyDrafts();
        form.reset();
        try {
          const summary = await api.financialSummary(created.customer_id);
          if (operation !== sequence.current) return;
          setFinancial(summary);
          setStatus("Customer created without assigning a permanent type.");
        } catch (error: unknown) {
          if (operation !== sequence.current) return;
          if (error instanceof CustomerUnavailableError) {
            invalidate();
            setStatus(message(error));
            return;
          }
          setFinancialUnavailable(true);
          setStatus(
            "Customer created without assigning a permanent type. The independent financial summary is temporarily unavailable.",
          );
        }
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof CustomerUnavailableError) invalidate();
        if (error instanceof CustomerConflictError) {
          setReuseCandidates(error.candidates);
        }
        if (error instanceof CustomerRequestError && error.outcomeUnknown) {
          setStatus(
            "The Customer creation outcome is unknown. Reload this Property's Customer list and reconcile before retrying.",
          );
        } else {
          void onReconciled?.(commandRequirement);
          setReconciledRetryRequirement(null);
          setStatus(message(error));
        }
      })
      .finally(() => {
        if (!mounted.current) return;
        onCommandBusyChange?.(false);
        if (operation === sequence.current) setLoading(false);
      });
  }

  async function updateCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const submittedFields = new Set(editedFields);
    const source = updateSource(data, selected, submittedFields);
    if (
      submittedFields.has("legal_name") &&
      normalizeCustomerText(source.legal_name) === ""
    ) {
      setStatus(
        "Legal name must contain a non-whitespace character; no Customer command was sent.",
      );
      return;
    }
    const changedSource = changedCustomerSource(
      selected,
      source,
      submittedFields,
    );
    if (!hasChangedCustomerSource(changedSource)) {
      setStatus(
        "No approved Customer source field changed; no command was sent.",
      );
      return;
    }
    const preparationSequence = sequence.current;
    setLoading(true);
    onCommandBusyChange?.(true);
    const [resultFingerprint, requestFingerprint] = await Promise.all([
      customerReconciliationResultFingerprint("update", {
        ...selected,
        ...source,
        version: selected.version + 1,
      }),
      customerUpdateRequestFingerprint(selected, changedSource),
    ]);
    if (preparationWasCancelled(preparationSequence)) return;
    if (resultFingerprint === null || requestFingerprint === null) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Customer command coordination is unavailable. No update was sent; restore secure result verification before retrying.",
      );
      return;
    }
    if (
      reconciledRetryRequirement?.kind === "update" &&
      reconciledRetryRequirement.requestFingerprint !== requestFingerprint
    ) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "The authoritatively absent update can only be retried with its original Customer values and reuse decision.",
      );
      return;
    }
    const commandRequirement = buildCommandRequirement(
      "update",
      selected.customer_id,
      propertyId.trim(),
      resultFingerprint,
      requestFingerprint,
      undefined,
      selected.version,
      changedSource,
    );
    const reserved = await reserveReconciliation(commandRequirement);
    if (preparationWasCancelled(preparationSequence)) {
      if (reserved) await onReconciled?.(commandRequirement);
      return;
    }
    if (!reserved) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Another tab already has an unresolved Customer command. Reconcile that exact command before submitting another one.",
      );
      return;
    }
    const operation = ++sequence.current;
    setEditDraft(source);
    setEditedFields(submittedFields);
    setDraftDirty("update", true);
    setStatus("Submitting the version-checked Customer update…");
    void api
      .update(selected, changedSource, commandRequirement.commandNonce)
      .then((updated) => {
        if (operation !== sequence.current) return;
        void onReconciled?.(commandRequirement);
        setReconciledRetryRequirement(null);
        setSelected(mergeMutationHistory(selected, updated));
        setEditDraft(null);
        setEditedFields(new Set());
        const preservesOtherPendingUpdate =
          pendingUpdateReview !== null &&
          pendingUpdateReview.customerId !== selected.customer_id;
        setPendingUpdateReview((current) =>
          current?.customerId === selected.customer_id ? null : current,
        );
        setCustomers([]);
        setNextCursor(null);
        setDraftDirty("update", preservesOtherPendingUpdate);
        setStatus(
          "Customer source fields updated. Reload Customer detail to refresh its current audit history.",
        );
      })
      .catch(async (error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof CustomerUnavailableError) invalidate();
        if (error instanceof CustomerRequestError && error.outcomeUnknown) {
          setStatus(
            "The Customer update outcome is unknown. Reload this exact Customer and verify its detail before retrying.",
          );
          return;
        }
        void onReconciled?.(commandRequirement);
        setReconciledRetryRequirement(null);
        if (error instanceof CustomerIdNumberInUseError) {
          setReuseCandidates(error.candidates);
          setEditDraft(source);
          setStatus(error.message);
          return;
        }
        if (
          error instanceof CustomerConflictError &&
          error.candidates.length > 0
        ) {
          setReuseCandidates(error.candidates);
          setPendingUpdateReview({
            customerId: selected.customer_id,
            legalName: selected.legal_name,
            draft: source,
          });
        }
        if (
          error instanceof CustomerConflictError &&
          error.candidates.length === 0
        ) {
          try {
            const current = await api.get(selected.customer_id);
            if (operation !== sequence.current) return;
            invalidateCustomerList();
            setSelected(current);
            if (!retainManagementCapability(current)) {
              setStatus(
                "Customer management access changed while current data was reloading. Privileged drafts and actions were removed.",
              );
              return;
            }
            setEditDraft(source);
            setEditedFields(differingUpdateFields(current, source));
            setStatus(
              current.active
                ? "The Customer changed. Current server data was reloaded; your entered values are preserved for a fresh decision."
                : "The Customer became deactivated. Your entered update values are preserved below for review, but the update cannot be retried.",
            );
          } catch (reloadError: unknown) {
            if (operation !== sequence.current) return;
            if (reloadError instanceof CustomerUnavailableError) invalidate();
            setStatus(message(reloadError));
          }
          return;
        }
        setStatus(message(error));
      })
      .finally(() => {
        if (!mounted.current) return;
        onCommandBusyChange?.(false);
        if (operation === sequence.current) setLoading(false);
      });
  }

  async function deactivateCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const reason = formString(data, "customer-deactivation-reason");
    if (reason === "") {
      setStatus(
        "Deactivation reason must contain a non-whitespace character; no Customer command was sent.",
      );
      return;
    }
    const preparationSequence = sequence.current;
    setLoading(true);
    onCommandBusyChange?.(true);
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "deactivate",
      {
        ...selected,
        version: selected.version + 1,
        active: false,
        deactivation_reason: reason,
      },
    );
    if (preparationWasCancelled(preparationSequence)) return;
    if (resultFingerprint === null) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Customer command coordination is unavailable. No deactivation was sent; restore secure result verification before retrying.",
      );
      return;
    }
    if (
      reconciledRetryRequirement?.kind === "deactivate" &&
      reconciledRetryRequirement.requestFingerprint !== resultFingerprint
    ) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "The authoritatively absent deactivation can only be retried with its original reason.",
      );
      return;
    }
    const commandRequirement = buildCommandRequirement(
      "deactivate",
      selected.customer_id,
      propertyId.trim(),
      resultFingerprint,
      resultFingerprint,
      undefined,
      selected.version,
      undefined,
      reason,
    );
    const reserved = await reserveReconciliation(commandRequirement);
    if (preparationWasCancelled(preparationSequence)) {
      if (reserved) await onReconciled?.(commandRequirement);
      return;
    }
    if (!reserved) {
      setLoading(false);
      onCommandBusyChange?.(false);
      setStatus(
        "Another tab already has an unresolved Customer command. Reconcile that exact command before submitting another one.",
      );
      return;
    }
    const operation = ++sequence.current;
    setDeactivationDraft(reason);
    setDraftDirty("deactivate", true);
    setStatus(
      "Deactivating this Customer without deleting identity or history…",
    );
    void api
      .deactivate(selected, reason, commandRequirement.commandNonce)
      .then((updated) => {
        if (operation !== sequence.current) return;
        void onReconciled?.(commandRequirement);
        setReconciledRetryRequirement(null);
        setSelected(mergeMutationHistory(selected, updated));
        setDeactivationDraft("");
        setDraftDirty("deactivate", false);
        setCustomers((current) =>
          activeFilter === "active"
            ? current.filter(
                (customer) => customer.customer_id !== updated.customer_id,
              )
            : current.map((customer) =>
                customer.customer_id === updated.customer_id
                  ? { ...customer, active: false }
                  : customer,
              ),
        );
        setStatus(
          "Customer deactivated without deleting identity or audit history. Reload Customer detail to refresh the current history view.",
        );
      })
      .catch(async (error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof CustomerUnavailableError) invalidate();
        if (error instanceof CustomerRequestError && error.outcomeUnknown) {
          setStatus(
            "The Customer deactivation outcome is unknown. Reload this exact Customer and verify its state before retrying.",
          );
          return;
        }
        void onReconciled?.(commandRequirement);
        setReconciledRetryRequirement(null);
        if (error instanceof CustomerConflictError) {
          try {
            const current = await api.get(selected.customer_id);
            if (operation !== sequence.current) return;
            invalidateCustomerList();
            setSelected(current);
            if (!retainManagementCapability(current)) {
              setStatus(
                "Customer management access changed while current data was reloading. Privileged drafts and actions were removed.",
              );
              return;
            }
            setDeactivationDraft(reason);
            setStatus(
              current.active
                ? "The Customer changed. Current server data was reloaded; the deactivation reason is preserved for a fresh decision."
                : "The Customer was already deactivated. Your deactivation reason is preserved below for review and was not submitted again.",
            );
          } catch (reloadError: unknown) {
            if (operation !== sequence.current) return;
            if (reloadError instanceof CustomerUnavailableError) invalidate();
            setStatus(message(reloadError));
          }
          return;
        }
        setStatus(message(error));
      })
      .finally(() => {
        if (!mounted.current) return;
        onCommandBusyChange?.(false);
        if (operation === sequence.current) setLoading(false);
      });
  }

  function loadMoreDepositLiabilities() {
    const cursor = financial?.deposit_liabilities_page.next_cursor;
    if (selected === null || cursor === null || cursor === undefined) return;
    const operation = sequence.current;
    const customerId = selected.customer_id;
    setLoading(true);
    setStatus("Loading the next bounded Deposit liability page…");
    void api
      .financialSummary(customerId, cursor)
      .then((next) => {
        if (
          operation !== sequence.current ||
          selected.customer_id !== customerId
        )
          return;
        setFinancial((current) =>
          current === null
            ? next
            : {
                ...next,
                deposit_liabilities: [
                  ...current.deposit_liabilities,
                  ...next.deposit_liabilities,
                ],
              },
        );
        setStatus("The next Deposit liability page was loaded.");
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  return (
    <section
      aria-labelledby="customer-management-heading"
      className="information-card"
    >
      <h3 id="customer-management-heading">Customer management</h3>
      <p>
        Search the minimized Customer list, then explicitly open a record to
        view contact, relationship, financial-summary, and audit details.
      </p>
      {reconciliationRequirement !== null && (
        <div role="alert">
          <p>
            A prior Customer command may have completed after the session ended.
            Verify its exact result before retrying any command.
          </p>
          <button
            disabled={loading}
            onClick={checkReconciliationCommand}
            type="button"
          >
            Check the prior Customer command status
          </button>
          {reconciliationProof !== null &&
            sameReconciliationRequirement(
              reconciliationProof.requirement,
              reconciliationRequirement,
            ) && (
              <button
                disabled={loading}
                onClick={() => {
                  void confirmReconciliationProof();
                }}
                type="button"
              >
                {reconciliationProof.outcome === "absent"
                  ? absentReconciliationCopy(reconciliationRequirement.kind)
                      .button
                  : "I verified the prior Customer command result"}
              </button>
            )}
          {reconciliationProof?.outcome === "absent" &&
            reconciliationRequirement.kind === "create" &&
            reconciliationRequirement.createSource !== undefined && (
              <button
                disabled={loading}
                onClick={() => {
                  autoRestoredCreateNonce.current = null;
                  setCreateDraft(
                    reconciliationRequirement.createSource ?? null,
                  );
                  setCreateFormRevision((current) => current + 1);
                  setDraftDirty("create", true);
                  setStatus(
                    "The sealed original Customer creation values were restored for exact retry preparation.",
                  );
                }}
                type="button"
              >
                Restore the exact Customer creation values
              </button>
            )}
        </div>
      )}
      <form className="form-stack inline-form" onSubmit={loadCustomers}>
        <div className="form-field">
          <label htmlFor="customer-property-id">
            Customer Property identifier
          </label>
          <input
            disabled={loading}
            id="customer-property-id"
            onChange={(event) => {
              if (!confirmDraftDiscard()) return;
              invalidate();
              setPropertyId(event.currentTarget.value);
              setStatus(null);
            }}
            required
            value={propertyId}
          />
        </div>
        <div className="form-field">
          <label htmlFor="customer-search">Search Customers</label>
          <input
            disabled={loading}
            id="customer-search"
            onChange={(event) => {
              if (!confirmDraftDiscard()) return;
              invalidate();
              setQuery(event.currentTarget.value);
            }}
            value={query}
          />
        </div>
        <div className="form-field">
          <label htmlFor="customer-active-filter">Customer state</label>
          <select
            disabled={loading}
            id="customer-active-filter"
            onChange={(event) => {
              if (!confirmDraftDiscard()) return;
              invalidate();
              setActiveFilter(
                event.currentTarget.value as CustomerActiveFilter,
              );
            }}
            value={activeFilter}
          >
            <option value="all">All Customers</option>
            <option value="active">Active Customers</option>
            <option value="deactivated">Deactivated Customers</option>
          </select>
        </div>
        <button disabled={loading} type="submit">
          Load Customers
        </button>
      </form>
      {status !== null && <p role="status">{status}</p>}

      {customers.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>
              Minimized Customer identity and relationship indicators
            </caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">State</th>
                <th scope="col">Relationships</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => (
                <tr key={customer.customer_id}>
                  <th scope="row">{customer.legal_name}</th>
                  <td>{customer.active ? "Active" : "Deactivated"}</td>
                  <td>
                    {customer.relationship_indicators.join(", ") ||
                      "None recorded"}
                  </td>
                  <td>
                    <button
                      disabled={loading}
                      onClick={() => {
                        openCustomer(customer.customer_id);
                      }}
                      type="button"
                    >
                      Open {customer.legal_name}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {nextCursor !== null && (
        <button disabled={loading} onClick={loadMoreCustomers} type="button">
          Load more Customers
        </button>
      )}

      {reuseCandidates.length > 0 && (
        <section aria-labelledby="customer-reuse-heading">
          <h4 id="customer-reuse-heading">Possible existing Customers</h4>
          <p>
            Open and review a possible match before confirming a distinct
            identity.
          </p>
          <ul>
            {reuseCandidates.map((candidate) => (
              <li key={candidate.customer_id}>
                <button
                  disabled={loading}
                  onClick={() => {
                    openCustomer(candidate.customer_id, null, true);
                  }}
                  type="button"
                >
                  Review existing {candidate.legal_name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {pendingUpdateReview !== null &&
        selected?.customer_id !== pendingUpdateReview.customerId && (
          <button
            disabled={loading}
            onClick={() => {
              openCustomer(
                pendingUpdateReview.customerId,
                pendingUpdateReview.draft,
                true,
              );
            }}
            type="button"
          >
            Return to pending update for {pendingUpdateReview.legalName}
          </button>
        )}

      {canManage && commandGateAllows("create") && (
        <form
          className="form-stack"
          key={`create-${String(createFormRevision)}`}
          onChange={(event) => {
            autoRestoredCreateNonce.current = null;
            setDraftDirty("create", true);
            setCreateDraft(createSource(new FormData(event.currentTarget)));
          }}
          onSubmit={(event) => {
            void createCustomer(event);
          }}
        >
          <h4>Create Customer</h4>
          <div className="form-field">
            <label htmlFor="customer-legal-name">Legal name</label>
            <input
              disabled={loading}
              id="customer-legal-name"
              maxLength={255}
              name="customer-legal-name"
              required
              defaultValue={createDraft?.legal_name ?? ""}
            />
          </div>
          <div className="form-field">
            <label htmlFor="customer-id-number">
              ID number / Passport number
            </label>
            <input
              disabled={loading}
              id="customer-id-number"
              maxLength={64}
              name="customer-id-number"
              required
              defaultValue={createDraft?.id_document_number ?? ""}
            />
          </div>
          <div className="form-field">
            <label htmlFor="customer-phone">Phone (optional)</label>
            <input
              disabled={loading}
              id="customer-phone"
              inputMode="tel"
              maxLength={100}
              name="customer-phone"
              pattern={CUSTOMER_PHONE_PATTERN}
              defaultValue={createDraft?.phone_number ?? ""}
            />
          </div>
          <div className="form-field">
            <label htmlFor="customer-email">Email (optional)</label>
            <input
              disabled={loading}
              id="customer-email"
              maxLength={320}
              name="customer-email"
              type="email"
              defaultValue={createDraft?.email_address ?? ""}
            />
          </div>
          <div className="form-field">
            <label htmlFor="customer-address">Contact address (optional)</label>
            <textarea
              disabled={loading}
              id="customer-address"
              maxLength={1000}
              name="customer-address"
              defaultValue={createDraft?.contact_address ?? ""}
            />
          </div>
          <div className="form-field">
            <label htmlFor="customer-memo">Memo (optional)</label>
            <textarea
              disabled={loading}
              id="customer-memo"
              maxLength={5000}
              name="customer-memo"
              defaultValue={createDraft?.memo ?? ""}
            />
          </div>
          <label>
            <input
              disabled={loading}
              name="customer-confirmed-distinct"
              type="checkbox"
              defaultChecked={createDraft?.confirmed_distinct ?? false}
            />{" "}
            Confirm a distinct person after reviewing a possible match
          </label>
          <button disabled={loading} type="submit">
            Create Customer
          </button>
        </form>
      )}

      {selected !== null && (
        <section aria-labelledby="customer-detail-heading">
          <h4 id="customer-detail-heading">
            Customer detail: {selected.legal_name}
          </h4>
          <dl className="detail-list">
            <div>
              <dt>Stable identity</dt>
              <dd>{selected.customer_id}</dd>
            </div>
            <div>
              <dt>State</dt>
              <dd>{selected.active ? "Active" : "Deactivated"}</dd>
            </div>
            <div>
              <dt>ID number / Passport number</dt>
              <dd>
                {selected.id_document_number ??
                  "Not recorded yet. Add it with Update Customer."}
              </dd>
            </div>
            <div>
              <dt>Phone</dt>
              <dd>{selected.phone_number ?? "Not supplied"}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{selected.email_address ?? "Not supplied"}</dd>
            </div>
            <div>
              <dt>Contact address</dt>
              <dd>{selected.contact_address ?? "Not supplied"}</dd>
            </div>
            <div>
              <dt>Memo</dt>
              <dd>{selected.memo ?? "Not supplied"}</dd>
            </div>
            <div>
              <dt>Deactivated at</dt>
              <dd>{selected.deactivated_at ?? "Not deactivated"}</dd>
            </div>
            <div>
              <dt>Deactivation reason</dt>
              <dd>{selected.deactivation_reason ?? "Not deactivated"}</dd>
            </div>
            <div>
              <dt>Reservations</dt>
              <dd>{relationshipCount(selected, "reservations")}</dd>
            </div>
            <div>
              <dt>Primary tenant leases</dt>
              <dd>{relationshipCount(selected, "primary_tenant_leases")}</dd>
            </div>
            <div>
              <dt>Signer leases</dt>
              <dd>{relationshipCount(selected, "signer_leases")}</dd>
            </div>
            <div>
              <dt>Occupancies</dt>
              <dd>{relationshipCount(selected, "occupancies")}</dd>
            </div>
            <div>
              <dt>Invoices</dt>
              <dd>{relationshipCount(selected, "invoices")}</dd>
            </div>
            <div>
              <dt>Payments and allocations</dt>
              <dd>{relationshipCount(selected, "payments")}</dd>
            </div>
            <div>
              <dt>Customer credit</dt>
              <dd>{relationshipCount(selected, "customer_credit")}</dd>
            </div>
            <div>
              <dt>Refunds</dt>
              <dd>{relationshipCount(selected, "refunds")}</dd>
            </div>
          </dl>

          {onOpenAccountLedger && (
            <button
              type="button"
              onClick={() => {
                onOpenAccountLedger({
                  customerId: selected.customer_id,
                  propertyId: propertyId.trim().toLowerCase(),
                });
              }}
            >
              Open account ledger
            </button>
          )}
          <h5>Financial summary</h5>
          {financialUnavailable ? (
            <p>
              Financial summary is temporarily unavailable. Customer detail and
              authorized management actions remain available.
            </p>
          ) : financial === null ? (
            <p>Financial summary has not been loaded.</p>
          ) : financial.source_availability.deposits !== "AVAILABLE" ? (
            <p>
              Deposit liabilities are not available yet; no zero balance is
              implied. Other financial sources are also unavailable.
            </p>
          ) : (
            <>
              <p>
                Deposit aggregate: {financial.deposit_aggregate.count}{" "}
                record(s), required{" "}
                {usd(financial.deposit_aggregate.required_usd_cents)}, received{" "}
                {usd(financial.deposit_aggregate.received_usd_cents)}, held{" "}
                {usd(financial.deposit_aggregate.held_refundable_usd_cents)},
                outstanding{" "}
                {usd(
                  financial.deposit_aggregate.outstanding_required_usd_cents,
                )}
                .
              </p>
              <h6>Separate Deposit liabilities</h6>
              {financial.deposit_liabilities.length === 0 ? (
                <p>No Deposit liabilities are recorded for this Customer.</p>
              ) : (
                <ul>
                  {financial.deposit_liabilities.map((deposit) => (
                    <li key={deposit.deposit_id}>
                      {deposit.deposit_type} Deposit {deposit.deposit_id}:
                      required {usd(deposit.required_usd_cents)}, received{" "}
                      {usd(deposit.received_usd_cents)}, held{" "}
                      {usd(deposit.held_refundable_usd_cents)}, outstanding{" "}
                      {usd(deposit.outstanding_required_usd_cents)}; source{" "}
                      {deposit.reservation_id !== null
                        ? `Reservation ${deposit.reservation_id}`
                        : deposit.lease_id !== null
                          ? `Lease ${deposit.lease_id}`
                          : "unavailable"}
                    </li>
                  ))}
                </ul>
              )}
              {financial.deposit_liabilities_page.next_cursor !== null && (
                <button
                  disabled={loading}
                  onClick={loadMoreDepositLiabilities}
                  type="button"
                >
                  Load more Deposit liabilities
                </button>
              )}
              <p>
                Invoice, late-charge, unallocated-Payment, and Customer Credit
                summaries are not available yet; no zero balances are implied.
              </p>
            </>
          )}
          <p>Customer credit and deposit liability remain separate balances.</p>

          <h5>Audit history</h5>
          {!selected.can_view_audit ? (
            <p>Audit history requires separate audit-view access.</p>
          ) : !selected.audit_history_available ? (
            <p>
              Audit history is temporarily unavailable; the Customer command
              outcome shown above is unchanged.
            </p>
          ) : selected.audit_history.length === 0 ? (
            <p>No audit events recorded.</p>
          ) : (
            <ul>
              {selected.audit_history.map((event) => (
                <li key={event.event_id}>
                  <strong>
                    {event.occurred_at}: {event.action} — {event.outcome}
                  </strong>
                  <div>Actor: {event.actor_id}</div>
                  <div>Reason: {event.reason}</div>
                  <div>Correlation ID: {event.correlation_id}</div>
                  <div>Previous state</div>
                  <pre>{auditValue(event.previous_state)}</pre>
                  <div>Resulting state</div>
                  <pre>{auditValue(event.resulting_state)}</pre>
                </li>
              ))}
            </ul>
          )}
          {selected.can_view_audit &&
            selected.audit_history_available &&
            selected.audit_history_next_cursor !== null && (
              <button
                disabled={loading}
                onClick={loadOlderHistory}
                type="button"
              >
                Load older Customer audit history
              </button>
            )}

          {selected.can_manage &&
            selected.active &&
            commandGateAllows("update", selected.customer_id) && (
              <form
                className="form-stack"
                key={`customer-${selected.customer_id}-${String(selected.version)}`}
                onChange={(event) => {
                  const data = new FormData(event.currentTarget);
                  const changedFields = new Set(editedFields);
                  const changedName = (event.target as HTMLInputElement).name;
                  const changedField = UPDATE_FORM_FIELDS.find(
                    ([, formName]) => formName === changedName,
                  )?.[0];
                  if (changedField !== undefined)
                    changedFields.add(changedField);
                  const draft = updateSource(data, selected, changedFields);
                  setEditedFields(changedFields);
                  setDraftDirty("update", true);
                  setEditDraft(draft);
                  setPendingUpdateReview((current) =>
                    current?.customerId === selected.customer_id
                      ? { ...current, draft }
                      : current,
                  );
                }}
                onSubmit={(event) => {
                  void updateCustomer(event);
                }}
              >
                <h5>Update approved Customer source data</h5>
                <div className="form-field">
                  <label htmlFor="edit-customer-legal-name">Legal name</label>
                  <input
                    defaultValue={editDraft?.legal_name ?? selected.legal_name}
                    disabled={loading}
                    id="edit-customer-legal-name"
                    maxLength={255}
                    name="edit-customer-legal-name"
                    required
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-customer-phone">Phone</label>
                  <input
                    defaultValue={
                      editDraft === null
                        ? (selected.phone_number ?? "")
                        : (editDraft.phone_number ?? "")
                    }
                    disabled={loading}
                    id="edit-customer-phone"
                    inputMode="tel"
                    maxLength={100}
                    name="edit-customer-phone"
                    pattern={
                      editedFields.has("phone_number") ||
                      supportsStrictPhoneInput(selected.phone_number)
                        ? CUSTOMER_PHONE_PATTERN
                        : undefined
                    }
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-customer-email">Email</label>
                  <input
                    defaultValue={
                      editDraft === null
                        ? (selected.email_address ?? "")
                        : (editDraft.email_address ?? "")
                    }
                    disabled={loading}
                    id="edit-customer-email"
                    maxLength={320}
                    name="edit-customer-email"
                    type={
                      editedFields.has("email_address") ||
                      supportsStrictEmailInput(selected.email_address)
                        ? "email"
                        : "text"
                    }
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-customer-address">Contact address</label>
                  <textarea
                    defaultValue={
                      editDraft === null
                        ? (selected.contact_address ?? "")
                        : (editDraft.contact_address ?? "")
                    }
                    disabled={loading}
                    id="edit-customer-address"
                    maxLength={1000}
                    name="edit-customer-address"
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-customer-id-number">
                    ID number / Passport number
                  </label>
                  <input
                    defaultValue={
                      editDraft === null
                        ? (selected.id_document_number ?? "")
                        : (editDraft.id_document_number ?? "")
                    }
                    disabled={loading}
                    id="edit-customer-id-number"
                    maxLength={64}
                    name="edit-customer-id-number"
                    required={selected.id_document_number !== null}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-customer-memo">Memo</label>
                  <textarea
                    defaultValue={
                      editDraft === null
                        ? (selected.memo ?? "")
                        : (editDraft.memo ?? "")
                    }
                    disabled={loading}
                    id="edit-customer-memo"
                    maxLength={5000}
                    name="edit-customer-memo"
                  />
                </div>
                <label>
                  <input
                    defaultChecked={editDraft?.confirmed_distinct ?? false}
                    disabled={loading}
                    name="edit-customer-confirmed-distinct"
                    type="checkbox"
                  />{" "}
                  Confirm distinct after reviewing a possible match
                </label>
                <button disabled={loading} type="submit">
                  Update Customer
                </button>
              </form>
            )}

          {selected.can_deactivate &&
            selected.active &&
            commandGateAllows("deactivate", selected.customer_id) && (
              <form
                className="form-stack"
                key={`deactivate-${selected.customer_id}-${String(selected.version)}`}
                onSubmit={(event) => {
                  void deactivateCustomer(event);
                }}
              >
                <h5>Deactivate without deleting history</h5>
                <div className="form-field">
                  <label htmlFor="customer-deactivation-reason">Reason</label>
                  <input
                    disabled={loading}
                    id="customer-deactivation-reason"
                    maxLength={1000}
                    name="customer-deactivation-reason"
                    onChange={(event) => {
                      setDraftDirty("deactivate", true);
                      setDeactivationDraft(event.currentTarget.value);
                    }}
                    required
                    value={deactivationDraft}
                  />
                </div>
                <button disabled={loading} type="submit">
                  Deactivate Customer
                </button>
              </form>
            )}

          {!selected.active &&
            (editDraft !== null || deactivationDraft !== "") && (
              <section aria-labelledby="preserved-customer-draft-heading">
                <h5 id="preserved-customer-draft-heading">
                  Preserved unsent Customer command
                </h5>
                {editDraft !== null && (
                  <dl className="detail-list">
                    <div>
                      <dt>Draft legal name</dt>
                      <dd>{editDraft.legal_name}</dd>
                    </div>
                    <div>
                      <dt>Draft phone</dt>
                      <dd>{editDraft.phone_number ?? "Not supplied"}</dd>
                    </div>
                    <div>
                      <dt>Draft email</dt>
                      <dd>{editDraft.email_address ?? "Not supplied"}</dd>
                    </div>
                    <div>
                      <dt>Draft contact address</dt>
                      <dd>{editDraft.contact_address ?? "Not supplied"}</dd>
                    </div>
                    <div>
                      <dt>Draft memo</dt>
                      <dd>{editDraft.memo ?? "Not supplied"}</dd>
                    </div>
                    <div>
                      <dt>Draft ID number / Passport number</dt>
                      <dd>{editDraft.id_document_number ?? "Not recorded"}</dd>
                    </div>
                  </dl>
                )}
                {deactivationDraft !== "" && (
                  <p>Draft deactivation reason: {deactivationDraft}</p>
                )}
              </section>
            )}
        </section>
      )}
    </section>
  );
}
