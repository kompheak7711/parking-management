import {
  financialAborted,
  FinancialClientError,
  FINANCIAL_DEADLINE_MS,
  FINANCIAL_REPLY_BYTES,
} from "./financialClient";
import {
  exactKeys,
  financialId,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  captureEnforcementRead,
  enforcementPath,
  validateEnforcementRead,
  type EnforcementRead,
} from "./leaseEnforcementContract";

export interface EnforcementReadScope {
  actorId: string;
  propertyId: string | null;
  signal: AbortSignal;
}
export interface EnforcementReply {
  data: FinancialObject;
  actorId: string;
  propertyId: string | null;
  requestId: string;
}
export interface EnforcementClient {
  read(
    scope: EnforcementReadScope,
    input: EnforcementRead,
  ): Promise<EnforcementReply>;
}
function capture(scope: EnforcementReadScope, input: EnforcementRead) {
  const actorId = financialId(scope.actorId),
    propertyId =
      scope.propertyId === null ? null : financialId(scope.propertyId),
    signal = scope.signal;
  const request = captureEnforcementRead(input);
  if ((request.kind === "workspaces") !== (propertyId === null))
    invalidFinancial();
  if (!(signal instanceof AbortSignal) || signal.aborted)
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
  return { actorId, propertyId, signal, request };
}
export function createEnforcementClient(
  fetcher: typeof fetch = (...args) => fetch(...args),
): EnforcementClient {
  return {
    async read(scope, input) {
      let dispatched = false,
        requestId: string | null = null,
        status: number | null = null;
      const controller = new AbortController();
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      const body: { current: ReadableStream<Uint8Array> | null } = {
        current: null,
      };
      let timer: ReturnType<typeof setTimeout> | undefined;
      let release = () => {
        /* Installed after capture. */
      };
      try {
        const saved = capture(scope, input);
        requestId = financialId(crypto.randomUUID());
        const headers = new Headers({
          Accept: "application/json",
          "X-Request-ID": requestId,
          "X-Billing-Actor-ID": saved.actorId,
        });
        if (saved.propertyId !== null)
          headers.set("X-Financial-Property-ID", saved.propertyId);
        const interrupted = new Promise<never>((_resolve, reject) => {
          const stop = () => {
            controller.abort();
            reject(
              new FinancialClientError(
                financialAborted(saved.signal)
                  ? "WORKSPACE_INVALIDATED"
                  : "UNAVAILABLE",
                dispatched,
                status,
                requestId,
              ),
            );
          };
          saved.signal.addEventListener("abort", stop, { once: true });
          release = () => {
            saved.signal.removeEventListener("abort", stop);
          };
          timer = setTimeout(stop, FINANCIAL_DEADLINE_MS);
        });
        const guard = <T>(promise: Promise<T>) =>
          Promise.race([promise, interrupted]);
        if (financialAborted(saved.signal))
          throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
        dispatched = true;
        const response = await guard(
          fetcher(enforcementPath(saved.request, saved.propertyId), {
            method: "GET",
            headers,
            credentials: "include",
            cache: "no-store",
            redirect: "error",
            signal: controller.signal,
          }).then((received) => {
            body.current = received.body;
            if (financialAborted(controller.signal))
              void received.body?.cancel().catch(() => {
                /* Own late bodies without delaying settlement. */
              });
            return received;
          }),
        );
        status = response.status;
        const invalid = () =>
          new FinancialClientError("INVALID_RESPONSE", true, status, requestId);
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
            true,
            status,
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
              true,
              status,
              requestId,
            );
          raw += decoder.decode(part.value, { stream: true });
        }
        raw += decoder.decode();
        if (
          financialAborted(saved.signal) ||
          financialAborted(controller.signal)
        )
          throw new FinancialClientError(
            "WORKSPACE_INVALIDATED",
            true,
            status,
            requestId,
          );
        const envelope = financialObject(
          parseFinancialJson(raw, FINANCIAL_REPLY_BYTES),
        );
        if (status !== 200) {
          const codes: Record<number, string> = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
          };
          const error = financialObject(envelope.error),
            meta = financialObject(envelope.meta);
          if (
            !Object.hasOwn(codes, status) ||
            error.code !== codes[status] ||
            meta.request_id !== requestId ||
            Object.hasOwn(envelope, "data") ||
            Object.hasOwn(meta, "property_id")
          )
            throw invalid();
          throw new FinancialClientError(
            "HTTP_REJECTION",
            true,
            status,
            requestId,
          );
        }
        const data = validateEnforcementRead(
          envelope,
          saved.request,
          saved.actorId,
          saved.propertyId,
          requestId,
        );
        return {
          data,
          actorId: saved.actorId,
          propertyId: saved.propertyId,
          requestId,
        };
      } catch (error) {
        if (error instanceof FinancialClientError) throw error;
        throw new FinancialClientError(
          dispatched ? "INVALID_RESPONSE" : "INVALID_REQUEST",
          dispatched,
          status,
          requestId,
        );
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        release();
        controller.abort();
        if (reader)
          void reader.cancel().catch(() => {
            /* Best effort after settlement. */
          });
        else
          void body.current?.cancel().catch(() => {
            /* Includes header/size failures. */
          });
      }
    },
  };
}
export const enforcementClient = createEnforcementClient();

/** Also detach and validate injected clients before a workspace accepts their evidence. */
export async function readEnforcement(
  scope: EnforcementReadScope,
  input: EnforcementRead,
  client: EnforcementClient = enforcementClient,
): Promise<FinancialObject> {
  const saved = capture(scope, input);
  const reply = await client.read(
    {
      actorId: saved.actorId,
      propertyId: saved.propertyId,
      signal: saved.signal,
    },
    saved.request as unknown as EnforcementRead,
  );
  if (financialAborted(saved.signal))
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
  const row = financialObject(
    parseFinancialJson(
      stringifyFinancialJson(reply, FINANCIAL_REPLY_BYTES),
      FINANCIAL_REPLY_BYTES,
    ),
  );
  exactKeys(row, ["data", "actorId", "propertyId", "requestId"]);
  if (row.actorId !== saved.actorId || row.propertyId !== saved.propertyId)
    invalidFinancial();
  return validateEnforcementRead(
    {
      data: row.data ?? null,
      meta: {
        request_id: financialId(row.requestId),
        ...(saved.propertyId === null
          ? { actor_id: saved.actorId }
          : { property_id: saved.propertyId }),
      },
    },
    saved.request,
    saved.actorId,
    saved.propertyId,
    financialId(row.requestId),
  );
}
