import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { financialUiError, type FinancialReadRequest } from "./financialUi";
import {
  captureFinancialScope,
  FinancialClientError,
  type FinancialScope,
  financialTransport,
  type FinancialTransport,
} from "./financialClient";
import {
  financialId,
  captureFinancialRequest,
  isFinancialCommand,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import type { FinancialActionContextInput } from "./financialActionContext";
import { FinancialActionContextSequence } from "./financialActionContextSequence";
import { PaymentReversalContextSequence } from "./paymentReversalContextSequence";
import type { ReversalContextView } from "./paymentReversalContext";
import {
  financialReferenceClient,
  FinancialReferenceError,
} from "./financialReferenceClient";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";

export const FINANCIAL_UI_CONTEXT_BYTES = 8_388_608;
export const FINANCIAL_UI_CONTEXT_PAGES = 1000;
type ReferenceClient = Pick<typeof financialReferenceClient, "read">;

export async function readFinancialRecord(
  scope: FinancialScope,
  request: FinancialReadRequest,
  transport: FinancialTransport = financialTransport,
) {
  const captured = captureFinancialRequest(request);
  if (isFinancialCommand(captured.operation)) return invalidFinancial();
  return await transport.send(scope, captured);
}

/** Publish only into the mounted actor, Property and record generation that started a read. */
export function useFinancialTask(scope: FinancialScope, revision = 0) {
  const { actorId, propertyId, signal } = scope;
  const mounted = useRef(false);
  const identity = useRef<(FinancialScope & { revision: number }) | null>(null);
  const generation = useRef(0);
  const active = useRef<{
    controller: AbortController;
    release: () => void;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = useCallback(() => {
    generation.current++;
    const task = active.current;
    active.current = null;
    task?.release();
    task?.controller.abort();
  }, []);
  useLayoutEffect(() => {
    mounted.current = true;
    identity.current = { actorId, propertyId, signal, revision };
    setBusy(false);
    setError(null);
    return () => {
      mounted.current = false;
      identity.current = null;
      stop();
    };
  }, [actorId, propertyId, signal, revision, stop]);
  const cancel = useCallback(() => {
    stop();
    if (mounted.current) {
      setBusy(false);
      setError(null);
    }
  }, [stop]);
  const run = useCallback(
    async <T>(
      work: (scope: FinancialScope) => Promise<T>,
      accept: (value: T) => void,
    ): Promise<void> => {
      const currentScope = identity.current;
      if (
        !mounted.current ||
        signal.aborted ||
        currentScope?.actorId !== actorId ||
        currentScope.propertyId !== propertyId ||
        currentScope.signal !== signal ||
        currentScope.revision !== revision
      )
        return;
      stop();
      const ticket = generation.current;
      const controller = new AbortController();
      const valid = () =>
        mounted.current &&
        generation.current === ticket &&
        !controller.signal.aborted &&
        !signal.aborted &&
        identity.current === currentScope;
      const onAbort = () => {
        if (generation.current !== ticket) return;
        stop();
        if (mounted.current) setBusy(false);
      };
      const release = () => {
        signal.removeEventListener("abort", onAbort);
      };
      active.current = { controller, release };
      signal.addEventListener("abort", onAbort, { once: true });
      setBusy(true);
      setError(null);
      try {
        const captured = captureFinancialScope({
          actorId,
          propertyId,
          signal: controller.signal,
        });
        const result = await work(captured);
        // Keep publication in this synchronous guard, not in a caller's later await continuation.
        if (valid()) accept(result);
      } catch (failure) {
        if (valid()) setError(financialUiError(failure));
      } finally {
        release();
        if (valid()) {
          active.current = null;
          setBusy(false);
        }
      }
    },
    [actorId, propertyId, signal, revision, stop],
  );
  return { run, cancel, busy, error };
}
/** Retain original read evidence while separately tracking whether its mutable projection is current. */
export function useFinancialSnapshot<T>(revision: number) {
  const [snapshot, setSnapshot] = useState<{
    value: T;
    revision: number;
  } | null>(null);
  const setValue = useCallback(
    (value: T | null) => {
      setSnapshot(value === null ? null : { value, revision });
    },
    [revision],
  );
  return [
    snapshot?.value ?? null,
    setValue,
    snapshot === null || snapshot.revision === revision,
  ] as const;
}

function current(scope: FinancialScope): void {
  if (scope.signal.aborted)
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
}
function tooLarge(): never {
  throw new FinancialReferenceError("RESPONSE_TOO_LARGE");
}

export async function loadFinancialActionContext(
  suppliedScope: FinancialScope,
  input: FinancialActionContextInput,
  client: ReferenceClient = financialReferenceClient,
): Promise<FinancialObject> {
  const scope = captureFinancialScope(suppliedScope);
  const sequence = new FinancialActionContextSequence(
    scope.actorId,
    scope.propertyId,
    input,
  );
  for (let page = 0; page < FINANCIAL_UI_CONTEXT_PAGES; page++) {
    current(scope);
    const cursor = sequence.nextCursor;
    const reply = await client.read(scope, {
      ...sequence.request,
      ...(cursor === null ? {} : { cursor }),
    });
    current(scope);
    sequence.append(reply);
    if (sequence.complete) return sequence.data ?? invalidFinancial();
  }
  return tooLarge();
}

/** Bound the accepted graph and detached display before either retains another page. */
export async function loadPaymentReversalContext(
  suppliedScope: FinancialScope,
  suppliedPaymentId: string,
  view: ReversalContextView,
  client: ReferenceClient = financialReferenceClient,
): Promise<FinancialObject> {
  const scope = captureFinancialScope(suppliedScope);
  const paymentId = financialId(suppliedPaymentId);
  const sequence = new PaymentReversalContextSequence(
    scope.actorId,
    scope.propertyId,
    paymentId,
    view,
  );
  let snapshot: string | null = null;
  let itemBytes = 0;
  const items: FinancialObject[] = [];
  try {
    for (let page = 0; page < FINANCIAL_UI_CONTEXT_PAGES; page++) {
      current(scope);
      const cursor = sequence.nextCursor;
      const reply = await client.read(scope, {
        operation: "paymentReversalContext",
        payment_id: paymentId,
        view,
        limit: 100,
        ...(cursor === null ? {} : { cursor }),
      });
      current(scope);
      const row = financialObject(
        parseFinancialJson(
          stringifyFinancialJson(reply.data, 1_048_576),
          1_048_576,
        ),
      );
      const { items: incoming, ...facts } = row;
      if (!Array.isArray(incoming)) return invalidFinancial();
      const header = stringifyFinancialJson(facts, 1_048_576);
      if (snapshot !== null && header !== snapshot) return invalidFinancial();
      const encoder = new TextEncoder();
      const headerBytes = encoder.encode(
        stringifyFinancialJson({ ...facts, items: [] }, 1_048_576),
      ).byteLength;
      const incomingBytes =
        encoder.encode(stringifyFinancialJson(incoming, 1_048_576)).byteLength -
        2;
      const nextBytes =
        itemBytes +
        incomingBytes +
        (items.length > 0 && incoming.length > 0 ? 1 : 0);
      if (headerBytes + nextBytes > FINANCIAL_UI_CONTEXT_BYTES)
        return tooLarge();
      sequence.append(reply);
      items.push(...incoming.map(financialObject));
      itemBytes = nextBytes;
      snapshot = header;
      if (sequence.complete) return { ...facts, items };
    }
    return tooLarge();
  } catch (error) {
    items.length = 0;
    snapshot = null;
    itemBytes = 0;
    throw error;
  }
}
