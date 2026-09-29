import {
  captureFinancialScope,
  FinancialClientError,
  type FinancialScope,
} from "./financialClient";
import { invalidFinancial, type FinancialObject } from "./financialContracts";
import type { FinancialDueSourcesInput } from "./financialDueSources";
import { FinancialDueSourcesSequence } from "./financialDueSourcesSequence";
import {
  financialReferenceClient,
  FinancialReferenceError,
} from "./financialReferenceClient";

function current(scope: FinancialScope): void {
  if (scope.signal.aborted)
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
}

/** Read complete dated facts within the current workspace, without posting. */
export async function loadFinancialDueSources(
  suppliedScope: FinancialScope,
  input: FinancialDueSourcesInput,
  client: Pick<
    typeof financialReferenceClient,
    "read"
  > = financialReferenceClient,
): Promise<FinancialObject> {
  const scope = captureFinancialScope(suppliedScope);
  const sequence = new FinancialDueSourcesSequence(
    scope.actorId,
    scope.propertyId,
    input,
  );
  for (let page = 0; page < 1000; page++) {
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
  throw new FinancialReferenceError("RESPONSE_TOO_LARGE");
}
