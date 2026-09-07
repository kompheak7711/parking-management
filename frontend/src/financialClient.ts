import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  FINANCIAL_OPERATIONS,
  FINANCIAL_ENVELOPE_BYTES,
  captureFinancialRequest,
  captureWireRequest,
  financialId,
  financialObject,
  financialPath,
  isFinancialCommand,
  type CapturedFinancialRequest,
  type FinancialRequest,
} from "./financialContracts";
import {
  validateFinancialReply,
  type FinancialReply,
} from "./financialResponse";

// A defensive availability limit, not a guarantee about every historical text field.
// Covers the existing 1 MiB inner history/audit ceilings plus envelopes and headroom.
export const FINANCIAL_REPLY_BYTES = 4_194_304;
export const FINANCIAL_DEADLINE_MS = 20_000;
export interface FinancialScope {
  actorId: string;
  propertyId: string;
  signal: AbortSignal;
}
export type FinancialFailure =
  | "INVALID_REQUEST"
  | "WORKSPACE_INVALIDATED"
  | "CSRF_UNAVAILABLE"
  | "UNAVAILABLE"
  | "INVALID_RESPONSE"
  | "RESPONSE_TOO_LARGE"
  | "HTTP_REJECTION";
export class FinancialClientError extends Error {
  constructor(
    readonly code: FinancialFailure,
    readonly dispatched: boolean,
    readonly status: number | null = null,
    readonly requestId: string | null = null,
    readonly definitiveRejection = false,
  ) {
    super(
      code === "WORKSPACE_INVALIDATED"
        ? "This financial workspace is no longer current."
        : code === "RESPONSE_TOO_LARGE"
          ? "This financial evidence exceeds the display limit and is unavailable."
          : "The financial request could not be completed. Check its outcome before continuing.",
    );
    this.name = "FinancialClientError";
  }
}
export function financialCsrf(): string {
  const values = document.cookie
    .split(";")
    .map((value) => value.trim())
    .filter((value) => value.startsWith("__Host-prm_csrf="));
  try {
    if (values.length !== 1) throw new Error();
    const value = decodeURIComponent(
      (values[0] ?? "").slice("__Host-prm_csrf=".length),
    );
    if (!value || value.length > 4096 || /[^\x21-\x7e]/.test(value))
      throw new Error();
    return value;
  } catch {
    throw new FinancialClientError("CSRF_UNAVAILABLE", false);
  }
}
export function captureFinancialScope(scope: FinancialScope): FinancialScope {
  const actorId = financialId(scope.actorId),
    propertyId = financialId(scope.propertyId),
    signal = scope.signal;
  if (!(signal instanceof AbortSignal) || signal.aborted)
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
  return Object.freeze({ actorId, propertyId, signal });
}
export function financialAborted(signal: AbortSignal): boolean {
  return signal.aborted;
}
export interface FinancialTransport {
  send: (
    scope: FinancialScope,
    request: CapturedFinancialRequest,
    requestKey?: string,
  ) => Promise<FinancialReply>;
}
export function createFinancialTransport(
  fetcher: typeof fetch = (...args) => fetch(...args),
  csrf = financialCsrf,
): FinancialTransport {
  return {
    async send(suppliedScope, suppliedRequest, suppliedKey) {
      let dispatched = false;
      let requestId: string | null = null;
      let observedStatus: number | null = null;
      const controller = new AbortController();
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      const responseBody: { current: ReadableStream<Uint8Array> | null } = {
        current: null,
      };
      let timer: ReturnType<typeof setTimeout> | undefined;
      let release = () => {
        /* Replaced when the abort listener is registered. */
      };
      try {
        const scope = captureFinancialScope(suppliedScope);
        // Recapture supplied data before the first await, including restored commands.
        const captured = financialObject(
          parseFinancialJson(
            stringifyFinancialJson(suppliedRequest, FINANCIAL_ENVELOPE_BYTES),
            FINANCIAL_ENVELOPE_BYTES,
          ),
        );
        const request = captureWireRequest({
          operation: captured.operation,
          target: captured.target,
          ...(captured.wireBody === null
            ? { query: captured.query }
            : { wireBody: captured.wireBody }),
        });
        const command = isFinancialCommand(request.operation),
          key = command ? financialId(suppliedKey) : undefined;
        if (!command && suppliedKey !== undefined)
          throw new FinancialClientError("INVALID_REQUEST", false);
        requestId = financialId(crypto.randomUUID());
        const headers = new Headers({
          Accept: "application/json",
          "X-Financial-Property-ID": scope.propertyId,
          "X-Request-ID": requestId,
          "X-Billing-Actor-ID": scope.actorId,
        });
        if (command) {
          headers.set("Content-Type", "application/json");
          headers.set("Idempotency-Key", key ?? "");
          headers.set("X-CSRF-Token", csrf());
        }
        const interrupted = new Promise<never>((_resolve, reject) => {
          const stop = () => {
            controller.abort();
            reject(
              new FinancialClientError(
                financialAborted(scope.signal)
                  ? "WORKSPACE_INVALIDATED"
                  : "UNAVAILABLE",
                dispatched,
                null,
                requestId,
              ),
            );
          };
          scope.signal.addEventListener("abort", stop, { once: true });
          release = () => {
            scope.signal.removeEventListener("abort", stop);
          };
          timer = setTimeout(stop, FINANCIAL_DEADLINE_MS);
        });
        const guard = <T>(promise: Promise<T>) =>
          Promise.race([promise, interrupted]);
        if (financialAborted(scope.signal))
          throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
        if (financialAborted(scope.signal))
          throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
        dispatched = true;
        const response = await guard(
          fetcher(financialPath(request, scope.propertyId), {
            method: FINANCIAL_OPERATIONS[request.operation][0],
            headers,
            credentials: "include",
            cache: "no-store",
            redirect: "error",
            signal: controller.signal,
            ...(command ? { body: request.wireBody ?? "" } : {}),
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
        observedStatus = response.status;
        const invalid = () =>
          new FinancialClientError(
            "INVALID_RESPONSE",
            dispatched,
            response.status,
            requestId,
          );
        if (
          response.redirected ||
          response.headers.get("X-Request-ID") !== requestId ||
          !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(
            response.headers.get("Content-Type") ?? "",
          )
        )
          throw invalid();
        const declared = response.headers.get("Content-Length");
        if (
          declared !== null &&
          (!/^(?:0|[1-9][0-9]*)$/.test(declared) ||
            BigInt(declared) > BigInt(FINANCIAL_REPLY_BYTES))
        )
          throw new FinancialClientError(
            "RESPONSE_TOO_LARGE",
            dispatched,
            response.status,
            requestId,
          );
        if (!response.body) throw invalid();
        reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8", { fatal: true });
        let raw = "",
          bytes = 0;
        for (;;) {
          const part = await guard(reader.read());
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > FINANCIAL_REPLY_BYTES)
            throw new FinancialClientError(
              "RESPONSE_TOO_LARGE",
              dispatched,
              response.status,
              requestId,
            );
          raw += decoder.decode(part.value, { stream: true });
        }
        raw += decoder.decode();
        if (
          financialAborted(scope.signal) ||
          financialAborted(controller.signal)
        )
          throw new FinancialClientError(
            "WORKSPACE_INVALIDATED",
            dispatched,
            response.status,
            requestId,
          );
        const envelope = financialObject(
          parseFinancialJson(raw, FINANCIAL_REPLY_BYTES),
        );
        if (response.status !== FINANCIAL_OPERATIONS[request.operation][2]) {
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
          const error = financialObject(envelope.error),
            meta = financialObject(envelope.meta);
          if (
            !Object.hasOwn(codes, response.status) ||
            error.code !== codes[response.status] ||
            meta.request_id !== requestId ||
            Object.hasOwn(envelope, "data") ||
            Object.hasOwn(meta, "property_id")
          )
            throw invalid();
          throw new FinancialClientError(
            "HTTP_REJECTION",
            dispatched,
            response.status,
            requestId,
            [400, 412, 422].includes(response.status),
          );
        }
        return validateFinancialReply(
          envelope,
          request,
          scope.propertyId,
          requestId,
        );
      } catch (error) {
        if (error instanceof FinancialClientError) throw error;
        throw new FinancialClientError(
          dispatched ? "INVALID_RESPONSE" : "INVALID_REQUEST",
          dispatched,
          observedStatus,
          requestId,
        );
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        release();
        controller.abort();
        if (reader)
          void reader.cancel().catch(() => {
            /* Cancellation is best effort after the bounded result settles. */
          });
        else
          void responseBody.current?.cancel().catch(() => {
            /* Header/length rejection can precede reader acquisition. */
          });
      }
    },
  };
}
export const financialTransport = createFinancialTransport();
export async function readFinancial(
  scope: FinancialScope,
  input: FinancialRequest,
  transport = financialTransport,
): Promise<FinancialReply> {
  const request = captureFinancialRequest(input);
  if (isFinancialCommand(request.operation))
    throw new FinancialClientError("INVALID_REQUEST", false);
  return transport.send(scope, request);
}
