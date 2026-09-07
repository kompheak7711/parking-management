import {
  financialAborted,
  financialCsrf,
  FINANCIAL_DEADLINE_MS,
} from "./financialClient";
import {
  exactKeys,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import {
  parseFinancialJson,
  stringifyFinancialJson,
  type FinancialJson,
} from "./financialJson";

import {
  captureReversalContext,
  validateReversalContext,
  type ReversalContextView,
} from "./paymentReversalContext";

export const FINANCIAL_REFERENCE_REPLY_BYTES = 1_048_576;
export const FINANCIAL_CAPABILITIES = [
  "payments.read",
  "payments.record",
  "payments.allocate",
  "payments.allocations.reverse",
  "payments.reverse",
  "receipts.read",
  "receipts.reprint",
  "credits.read",
  "credits.recognize",
  "credits.reverse",
  "credits.apply",
  "credits.applications.reverse",
  "refunds.read",
  "refunds.create",
  "refunds.correct",
  "refunds.corrections.reverse",
  "exchange_rates.manage",
] as const;
export type FinancialCapabilities = Record<
  (typeof FINANCIAL_CAPABILITIES)[number],
  boolean
>;
export interface FinancialReferenceScope {
  actorId: string;
  propertyId?: string;
  signal: AbortSignal;
}
export type FinancialReferenceRequest =
  | { operation: "workspaces" | "methods"; limit?: number; cursor?: string }
  | { operation: "capabilities" }
  | {
      operation: "paymentReversalContext";
      payment_id: string;
      view?: ReversalContextView;
      limit?: number;
      cursor?: string;
    }
  | {
      operation: "khrPreview";
      usd_amount_cents: number | bigint;
      manual_reference?: FinancialObject;
    };
export interface FinancialReferenceReply {
  operation: FinancialReferenceRequest["operation"];
  actorId: string;
  propertyId: string | null;
  requestId: string;
  data: FinancialJson;
  page: { limit: number; nextCursor: string | null } | null;
}
export class FinancialReferenceError extends Error {
  constructor(
    readonly code:
      | "INVALID_REQUEST"
      | "INVALID_RESPONSE"
      | "UNAVAILABLE"
      | "WORKSPACE_INVALIDATED"
      | "HTTP_REJECTION"
      | "RESPONSE_TOO_LARGE",
    readonly status: number | null = null,
    readonly requestId: string | null = null,
  ) {
    super(
      code === "WORKSPACE_INVALIDATED"
        ? "This financial workspace is no longer current."
        : "Financial references are unavailable. Refresh them before continuing.",
    );
    this.name = "FinancialReferenceError";
  }
}
// Existing PostgreSQL labels use btrim's ASCII-space nonblank check. They have
// no character ceiling; the bounded UTF-8 response budget still applies.
function label(value: unknown): string {
  if (typeof value !== "string" || !/[^ ]/.test(value) || value.includes("\0"))
    invalidFinancial();
  return value;
}
// Match Python str.strip and len for the existing bounded FX evidence contract.
// FEFF is not Python boundary whitespace; internal whitespace remains valid.
const evidenceBoundarySpace = new Set([
  9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, 8192, 8193, 8194, 8195,
  8196, 8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288,
]);
function evidenceText(value: unknown): string {
  const checked = label(value),
    characters = Array.from(checked);
  if (
    characters.length > 500 ||
    evidenceBoundarySpace.has(checked.charCodeAt(0)) ||
    evidenceBoundarySpace.has(checked.charCodeAt(checked.length - 1)) ||
    characters.some((character) => {
      const point = character.codePointAt(0) ?? 0;
      return point >= 0xd800 && point <= 0xdfff;
    })
  )
    invalidFinancial();
  return checked;
}
function rate(value: unknown): bigint {
  if (
    typeof value !== "string" ||
    !/^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$/.test(value)
  )
    invalidFinancial();
  const [whole, fraction = ""] = value.split(".");
  const result =
    BigInt(whole ?? "") * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  if (result <= 0n) invalidFinancial();
  return result;
}
function manual(value: unknown): FinancialObject {
  const row = financialObject(value);
  exactKeys(row, [
    "reference_rate_khr_per_usd",
    "source_reference",
    "applicable_at",
    "fallback_reason",
  ]);
  rate(row.reference_rate_khr_per_usd);
  evidenceText(row.source_reference);
  evidenceText(row.fallback_reason);
  financialInstant(row.applicable_at);
  return row;
}
function grants(value: unknown): FinancialCapabilities {
  const row = financialObject(value);
  exactKeys(row, [...FINANCIAL_CAPABILITIES]);
  for (const capability of FINANCIAL_CAPABILITIES)
    if (typeof row[capability] !== "boolean") invalidFinancial();
  return row as FinancialCapabilities;
}
function capture(input: FinancialReferenceRequest): FinancialObject {
  const row = financialObject(
    parseFinancialJson(stringifyFinancialJson(input, 32_768), 32_768),
  );
  if (row.operation === "workspaces" || row.operation === "methods") {
    exactKeys(row, ["operation"], ["limit", "cursor"]);
    if (row.limit !== undefined) financialInteger(row.limit, 1n, 100n);
    if (row.cursor !== undefined) row.cursor = financialId(row.cursor);
  } else if (row.operation === "paymentReversalContext")
    captureReversalContext(row);
  else if (row.operation === "capabilities") exactKeys(row, ["operation"]);
  else if (row.operation === "khrPreview") {
    exactKeys(row, ["operation", "usd_amount_cents"], ["manual_reference"]);
    financialInteger(row.usd_amount_cents, 1n, 9_000_000_000_000_000n);
    if (row.manual_reference !== undefined) manual(row.manual_reference);
  } else invalidFinancial();
  return row;
}
function validate(
  envelope: FinancialObject,
  input: FinancialObject,
  actorId: string,
  propertyId: string | null,
  requestId: string,
): FinancialReferenceReply {
  const context = input.operation === "paymentReversalContext";
  const paged =
    context ||
    input.operation === "workspaces" ||
    input.operation === "methods";
  exactKeys(envelope, ["data", "meta", ...(paged ? ["page"] : [])]);
  const meta = financialObject(envelope.meta);
  exactKeys(meta, [
    "request_id",
    "actor_id",
    ...(propertyId ? ["property_id"] : []),
  ]);
  if (
    meta.request_id !== requestId ||
    meta.actor_id !== actorId ||
    (propertyId && meta.property_id !== propertyId)
  )
    invalidFinancial();
  let page: FinancialReferenceReply["page"] = null;
  if (context) {
    page = validateReversalContext(
      envelope,
      input,
      financialId(propertyId),
      requestId,
    );
  } else if (paged) {
    const pagination = financialObject(envelope.page);
    exactKeys(pagination, ["limit", "next_cursor"]);
    const limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
    if (
      pagination.limit !== limit ||
      !Array.isArray(envelope.data) ||
      envelope.data.length > limit
    )
      invalidFinancial();
    let last = typeof input.cursor === "string" ? input.cursor : null;
    for (const value of envelope.data) {
      const row = financialObject(value);
      const identity = financialId(
        input.operation === "workspaces" ? row.property_id : row.id,
      );
      if (last !== null && identity <= last) invalidFinancial();
      last = identity;
      if (input.operation === "workspaces") {
        exactKeys(row, ["property_id", "name", "timezone", "capabilities"]);
        label(row.name);
        if (row.timezone !== "Asia/Phnom_Penh") invalidFinancial();
        const permissions = grants(row.capabilities);
        if (
          !FINANCIAL_CAPABILITIES.slice(0, 16).some((cap) => permissions[cap])
        )
          invalidFinancial();
      } else {
        exactKeys(row, ["id", "property_id", "code", "display_name"]);
        if (row.property_id !== propertyId) invalidFinancial();
        label(row.code);
        label(row.display_name);
      }
    }
    const cursor =
      pagination.next_cursor === null
        ? null
        : financialId(pagination.next_cursor);
    if (cursor !== null && (envelope.data.length !== limit || cursor !== last))
      invalidFinancial();
    page = { limit, nextCursor: cursor };
  } else if (input.operation === "capabilities") {
    const row = financialObject(envelope.data);
    exactKeys(row, ["property_id", "capabilities"]);
    if (row.property_id !== propertyId) invalidFinancial();
    grants(row.capabilities);
  } else {
    const row = financialObject(envelope.data);
    if (
      row.property_id !== propertyId ||
      row.provisional !== true ||
      BigInt(
        financialInteger(row.usd_amount_cents, 1n, 9_000_000_000_000_000n),
      ) !== BigInt(financialInteger(input.usd_amount_cents))
    )
      invalidFinancial();
    const common = ["property_id", "usd_amount_cents", "provisional", "status"];
    if (row.status === "source_unavailable") {
      exactKeys(row, [...common, "manual_fallback_allowed"]);
      if (
        typeof row.manual_fallback_allowed !== "boolean" ||
        input.manual_reference !== undefined
      )
        invalidFinancial();
    } else {
      exactKeys(row, [
        ...common,
        "reference_rate_khr_per_usd",
        "source_reference",
        "applicable_at",
        "fallback_reason",
        "rate_source",
        "automatic_source_unavailable",
        "markup_basis_points",
        "system_rate_khr_per_usd",
        "unrounded_khr_amount",
        "payable_khr_amount",
      ]);
      if (row.status !== "available" || row.markup_basis_points !== 50)
        invalidFinancial();
      const reference = rate(row.reference_rate_khr_per_usd);
      evidenceText(row.source_reference);
      financialInstant(row.applicable_at);
      if (input.manual_reference === undefined) {
        if (
          row.rate_source !== "ABA_AUTOMATIC" ||
          row.automatic_source_unavailable !== false ||
          row.fallback_reason !== null
        )
          invalidFinancial();
      } else {
        const selected = manual(input.manual_reference);
        if (
          row.rate_source !== "ABA_EQUIVALENT_MANUAL" ||
          row.automatic_source_unavailable !== true ||
          row.fallback_reason !== selected.fallback_reason ||
          row.source_reference !== selected.source_reference ||
          financialInstant(row.applicable_at) !==
            financialInstant(selected.applicable_at) ||
          reference !== rate(selected.reference_rate_khr_per_usd)
        )
          invalidFinancial();
      }
      // Verify server consequences; display only the returned provisional values.
      const system = BigInt(
        financialInteger(row.system_rate_khr_per_usd, 1n, 100_500_000_000_000n),
      );
      const unrounded = BigInt(financialInteger(row.usd_amount_cents)) * system;
      if (
        system !== (reference * 1005n + 999_999_999n) / 1_000_000_000n ||
        row.unrounded_khr_amount !==
          `${(unrounded / 100n).toString()}.${(unrounded % 100n).toString().padStart(2, "0")}` ||
        BigInt(
          financialInteger(row.payable_khr_amount, 1n, 9_000_000_000_000_000n),
        ) !==
          (unrounded + 99n) / 100n
      )
        invalidFinancial();
    }
  }
  return {
    operation: input.operation as FinancialReferenceRequest["operation"],
    actorId,
    propertyId,
    requestId,
    data: envelope.data ?? null,
    page,
  };
}
export function createFinancialReferenceClient(
  fetcher: typeof fetch = (...args) => fetch(...args),
  csrf = financialCsrf,
) {
  return {
    async read(
      supplied: FinancialReferenceScope,
      original: FinancialReferenceRequest,
    ): Promise<FinancialReferenceReply> {
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout> | undefined;
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      const responseBody: { current: ReadableStream<Uint8Array> | null } = {
        current: null,
      };
      let release = () => {
        /* Set after listener registration. */
      };
      let requestId: string | null = null;
      let status: number | null = null;
      let sent = false;
      try {
        const input = capture(original),
          actorId = financialId(supplied.actorId),
          signal = supplied.signal;
        const propertyId =
          input.operation === "workspaces"
            ? null
            : financialId(supplied.propertyId);
        if (
          (input.operation === "workspaces" &&
            supplied.propertyId !== undefined) ||
          !(signal instanceof AbortSignal)
        )
          invalidFinancial();
        if (financialAborted(signal))
          throw new FinancialReferenceError("WORKSPACE_INVALIDATED");
        requestId = financialId(crypto.randomUUID());
        const preview = input.operation === "khrPreview";
        const path =
          input.operation === "workspaces"
            ? "/api/v1/financial-workspaces"
            : input.operation === "paymentReversalContext"
              ? `/api/v1/properties/${financialId(propertyId)}/payments/${financialId(input.payment_id)}/reversal-context`
              : `/api/v1/properties/${financialId(propertyId)}/${input.operation === "capabilities" ? "financial-capabilities" : input.operation === "methods" ? "payment-methods" : "payments/khr-preview"}`;
        const query = new URLSearchParams();
        if (
          ["workspaces", "methods", "paymentReversalContext"].includes(
            typeof input.operation === "string"
              ? input.operation
              : invalidFinancial(),
          )
        ) {
          if (input.limit !== undefined)
            query.set(
              "limit",
              financialInteger(input.limit, 1n, 100n).toString(),
            );
          if (input.cursor !== undefined)
            query.set(
              "cursor",
              input.operation === "paymentReversalContext"
                ? typeof input.cursor === "string"
                  ? input.cursor
                  : invalidFinancial()
                : financialId(input.cursor),
            );
          if (
            input.operation === "paymentReversalContext" &&
            input.view !== undefined
          )
            query.set(
              "view",
              typeof input.view === "string" ? input.view : invalidFinancial(),
            );
        }
        const headers = new Headers({
          Accept: "application/json",
          "X-Request-ID": requestId,
          "X-Billing-Actor-ID": actorId,
        });
        if (propertyId) headers.set("X-Financial-Property-ID", propertyId);
        let body: string | undefined;
        if (preview) {
          headers.set("Content-Type", "application/json");
          headers.set("X-CSRF-Token", csrf());
          const { operation: _operation, ...fields } = input;
          void _operation;
          body = stringifyFinancialJson(fields, 32_768);
        }
        const interrupted = new Promise<never>((_resolve, reject) => {
          const stop = () => {
            controller.abort();
            reject(
              new FinancialReferenceError(
                financialAborted(signal)
                  ? "WORKSPACE_INVALIDATED"
                  : "UNAVAILABLE",
                status,
                requestId,
              ),
            );
          };
          signal.addEventListener("abort", stop, { once: true });
          release = () => {
            signal.removeEventListener("abort", stop);
          };
          timer = setTimeout(stop, FINANCIAL_DEADLINE_MS);
        });
        const guard = <T>(promise: Promise<T>) =>
          Promise.race([promise, interrupted]);
        if (financialAborted(signal))
          throw new FinancialReferenceError("WORKSPACE_INVALIDATED");
        sent = true;
        const response = await guard(
          fetcher(path + (query.size ? `?${query}` : ""), {
            method: preview ? "POST" : "GET",
            headers,
            credentials: "include",
            cache: "no-store",
            redirect: "error",
            signal: controller.signal,
            ...(body === undefined ? {} : { body }),
          }).then((received) => {
            responseBody.current = received.body;
            // A noncooperating fetch may resolve after the raced request has
            // already settled. Its body must still have an explicit owner.
            if (financialAborted(controller.signal))
              void responseBody.current?.cancel().catch(() => {
                /* Best-effort late-body cancellation must not delay settlement. */
              });
            return received;
          }),
        );
        status = response.status;
        const invalid = () =>
          new FinancialReferenceError("INVALID_RESPONSE", status, requestId);
        if (
          response.redirected ||
          response.headers.get("X-Request-ID") !== requestId ||
          !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(
            response.headers.get("Content-Type") ?? "",
          ) ||
          !response.body
        )
          throw invalid();
        const declared = response.headers.get("Content-Length");
        if (
          declared !== null &&
          (!/^(?:0|[1-9][0-9]*)$/.test(declared) ||
            BigInt(declared) > BigInt(FINANCIAL_REFERENCE_REPLY_BYTES))
        )
          throw new FinancialReferenceError(
            "RESPONSE_TOO_LARGE",
            status,
            requestId,
          );
        reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8", { fatal: true });
        let raw = "",
          bytes = 0;
        for (;;) {
          const part = await guard(reader.read());
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > FINANCIAL_REFERENCE_REPLY_BYTES)
            throw new FinancialReferenceError(
              "RESPONSE_TOO_LARGE",
              status,
              requestId,
            );
          raw += decoder.decode(part.value, { stream: true });
        }
        raw += decoder.decode();
        if (financialAborted(signal) || financialAborted(controller.signal))
          throw new FinancialReferenceError(
            "WORKSPACE_INVALIDATED",
            status,
            requestId,
          );
        const envelope = financialObject(
          parseFinancialJson(raw, FINANCIAL_REFERENCE_REPLY_BYTES),
        );
        if (status !== 200) {
          const codes: Record<number, string> = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            412: "PRECONDITION_FAILED",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
          };
          const meta = financialObject(envelope.meta),
            error = financialObject(envelope.error);
          if (
            !Object.hasOwn(codes, status) ||
            error.code !== codes[status] ||
            meta.request_id !== requestId ||
            Object.hasOwn(envelope, "data") ||
            Object.hasOwn(meta, "property_id")
          )
            throw invalid();
          throw new FinancialReferenceError(
            "HTTP_REJECTION",
            status,
            requestId,
          );
        }
        return validate(envelope, input, actorId, propertyId, requestId);
      } catch (error) {
        if (error instanceof FinancialReferenceError) throw error;
        throw new FinancialReferenceError(
          sent ? "INVALID_RESPONSE" : "INVALID_REQUEST",
          status,
          requestId,
        );
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        release();
        controller.abort();
        if (reader)
          void reader.cancel().catch(() => {
            /* Best-effort stream cancellation after settlement. */
          });
        else
          void responseBody.current?.cancel().catch(() => {
            /* Header/length rejection can precede reader acquisition. */
          });
      }
    },
  };
}
export const financialReferenceClient = createFinancialReferenceClient();
