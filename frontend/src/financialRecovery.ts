import {
  MAX_SEALED_INTENT_BYTES,
  sealedIntentStore,
  type OpenIntent,
  type SealedIntentStore,
} from "./sealedIntentStore";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  captureFinancialRequest,
  captureWireRequest,
  exactKeys,
  financialId,
  financialObject,
  invalidFinancial,
  isFinancialCommand,
  type CapturedFinancialRequest,
  type FinancialCommandOperation,
  type FinancialRequest,
} from "./financialContracts";
import {
  captureFinancialScope,
  financialAborted,
  financialCsrf,
  financialTransport,
  FinancialClientError,
  type FinancialScope,
  type FinancialTransport,
} from "./financialClient";
import {
  validateFinancialReply,
  type FinancialReply,
} from "./financialResponse";

export interface PendingFinancialCommand {
  readonly namespace: "property-rental.financial-command";
  readonly version: 1;
  readonly actorId: string;
  readonly propertyId: string;
  readonly key: string;
  readonly operation: FinancialCommandOperation;
  readonly target: Readonly<Record<string, string>>;
  readonly wireBody: string;
}
export type FinancialRecoveryState =
  | { kind: "ready" }
  | { kind: "pending"; command: PendingFinancialCommand }
  | { kind: "other-property"; propertyId: string }
  | { kind: "foreign" }
  | { kind: "unavailable" }
  | { kind: "invalidated" };
export type FinancialExecutionResult =
  | { kind: "success"; reply: FinancialReply }
  | { kind: "rejected"; error: FinancialClientError }
  | {
      kind: "pending";
      command: PendingFinancialCommand;
      error: FinancialClientError | null;
    }
  | { kind: "blocked"; state: FinancialRecoveryState }
  | { kind: "invalidated" };
const namespace = "property-rental.financial-command";
function requestFor(
  command: PendingFinancialCommand,
): CapturedFinancialRequest {
  return captureWireRequest({
    operation: command.operation,
    target: { ...command.target },
    wireBody: command.wireBody,
  });
}
/** No financial transmission occurs here, including on malformed/foreign records. */
export function decodeFinancialIntent(
  opened: OpenIntent,
  actorId: string,
): PendingFinancialCommand | null {
  const row = financialObject(
    parseFinancialJson(opened.plaintext, MAX_SEALED_INTENT_BYTES),
  );
  if (row.namespace !== namespace) return null;
  exactKeys(row, [
    "namespace",
    "version",
    "actorId",
    "propertyId",
    "key",
    "operation",
    "target",
    "wireBody",
  ]);
  if (
    row.version !== 1 ||
    row.actorId !== financialId(actorId) ||
    row.key !== opened.requestKey ||
    row.key !== financialId(row.key) ||
    row.propertyId !== financialId(row.propertyId)
  )
    invalidFinancial();
  const request = captureWireRequest({
    operation: row.operation,
    target: row.target,
    wireBody: row.wireBody,
  });
  if (!isFinancialCommand(request.operation) || request.wireBody === null)
    return invalidFinancial();
  return Object.freeze({
    namespace,
    version: 1,
    actorId: row.actorId,
    propertyId: row.propertyId,
    key: row.key,
    operation: request.operation,
    target: request.target,
    wireBody: request.wireBody,
  });
}
export interface FinancialRecovery {
  load(scope: FinancialScope): Promise<FinancialRecoveryState>;
  submit(
    scope: FinancialScope,
    input: FinancialRequest,
  ): Promise<FinancialExecutionResult>;
  replay(
    scope: FinancialScope,
    expectedKey: string,
  ): Promise<FinancialExecutionResult>;
}
export function createFinancialRecovery(
  store: SealedIntentStore = sealedIntentStore,
  transport: FinancialTransport = financialTransport,
  csrf = financialCsrf,
): FinancialRecovery {
  async function load(scope: FinancialScope): Promise<FinancialRecoveryState> {
    try {
      const opened = await store.read(scope.actorId);
      if (financialAborted(scope.signal)) return { kind: "invalidated" };
      if (!opened) return { kind: "ready" };
      const command = decodeFinancialIntent(opened, scope.actorId);
      if (!command) return { kind: "foreign" };
      if (command.propertyId !== scope.propertyId)
        return { kind: "other-property", propertyId: command.propertyId };
      return { kind: "pending", command };
    } catch {
      return financialAborted(scope.signal)
        ? { kind: "invalidated" }
        : { kind: "unavailable" };
    }
  }
  async function execute(
    scope: FinancialScope,
    pending: PendingFinancialCommand,
    fresh: boolean,
  ): Promise<FinancialExecutionResult> {
    if (financialAborted(scope.signal)) return { kind: "invalidated" };
    let reply: FinancialReply;
    try {
      const request = requestFor(pending);
      reply = await transport.send(scope, request, pending.key);
      if (financialAborted(scope.signal)) return { kind: "invalidated" };
      if (reply.propertyId !== scope.propertyId) invalidFinancial();
      // Keep the retirement invariant even with an injected transport adapter.
      reply = validateFinancialReply(
        {
          data: reply.data,
          ...(reply.page ? { page: reply.page } : {}),
          meta: { property_id: reply.propertyId, request_id: reply.requestId },
        },
        request,
        scope.propertyId,
        financialId(reply.requestId),
      );
    } catch (error) {
      if (financialAborted(scope.signal)) return { kind: "invalidated" };
      const failure = error instanceof FinancialClientError ? error : null;
      if (
        fresh &&
        failure?.code === "HTTP_REJECTION" &&
        failure.definitiveRejection &&
        [400, 412, 422].includes(failure.status ?? 0)
      ) {
        try {
          await store.clear(scope.actorId, pending.key);
          if (financialAborted(scope.signal)) return { kind: "invalidated" };
          return { kind: "rejected", error: failure };
        } catch {
          return { kind: "blocked", state: await load(scope) };
        }
      }
      // A later rejection cannot disprove a previously committed but lost reply.
      return { kind: "pending", command: pending, error: failure };
    }
    try {
      await store.clear(scope.actorId, pending.key);
      if (financialAborted(scope.signal)) return { kind: "invalidated" };
      return { kind: "success", reply };
    } catch {
      return { kind: "blocked", state: await load(scope) };
    }
  }
  return {
    async load(supplied) {
      try {
        return await load(captureFinancialScope(supplied));
      } catch {
        return financialAborted(supplied.signal)
          ? { kind: "invalidated" }
          : { kind: "unavailable" };
      }
    },
    async submit(supplied, input) {
      // Capture the reviewed form, identity and original bytes before storage awaits.
      const scope = captureFinancialScope(supplied),
        request = captureFinancialRequest(input);
      if (!isFinancialCommand(request.operation) || request.wireBody === null)
        return invalidFinancial();
      csrf();
      const pending: PendingFinancialCommand = Object.freeze({
        namespace,
        version: 1,
        actorId: scope.actorId,
        propertyId: scope.propertyId,
        key: financialId(crypto.randomUUID()),
        operation: request.operation,
        target: request.target,
        wireBody: request.wireBody,
      });
      const plaintext = stringifyFinancialJson(
        pending,
        MAX_SEALED_INTENT_BYTES,
      );
      try {
        await store.begin(scope.actorId, {
          requestKey: pending.key,
          plaintext,
        });
      } catch {
        return { kind: "blocked", state: await load(scope) };
      }
      return execute(scope, pending, true);
    },
    async replay(supplied, expectedKey) {
      const scope = captureFinancialScope(supplied),
        key = financialId(expectedKey);
      const state = await load(scope);
      if (state.kind !== "pending" || state.command.key !== key)
        return { kind: "blocked", state };
      // Explicit caller action is required; load never invokes this operation.
      return execute(scope, state.command, false);
    },
  };
}
export const financialRecovery = createFinancialRecovery();
