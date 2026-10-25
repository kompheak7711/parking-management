// V1-058 R7a: the read of the Waiting for approval page (GET financial-drafts-waiting). The
// decisions (confirm, reject, withdraw) use the shared draft routes in settlementClient.ts.

import type { FinancialDraft } from "../settlementClient";

export type DraftDirection = "OUT" | "KEPT" | "INTERNAL";

/** One plain line per draft, worked out on the server from the draft's own payload. */
export interface DraftSummary {
  variant: string | null;
  amount_usd_cents: number | null;
  direction: DraftDirection;
  customer_id: string | null;
  customer_name: string | null;
  lease_id: string | null;
  reservation_id: string | null;
  /** SECURITY or PET when the draft names a Deposit. */
  deposit_type: string | null;
  unit_id: string | null;
  unit_number: string | null;
  prepared_by_name: string | null;
  decided_by_name: string | null;
}

export interface WaitingDraft extends FinancialDraft {
  summary: DraftSummary;
}

export interface WaitingPage {
  business_date: string;
  waiting: WaitingDraft[];
  decided_today: WaitingDraft[];
  /** More drafts wait than the 200 oldest shown. */
  truncated?: boolean;
}

export class ApprovalsNotAllowedError extends Error {
  constructor() {
    super("Your account cannot see the drafts.");
    this.name = "ApprovalsNotAllowedError";
  }
}

export class ApprovalsUnavailableError extends Error {
  constructor() {
    super("The drafts are not available right now.");
    this.name = "ApprovalsUnavailableError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isDraft(value: unknown): value is WaitingDraft {
  return (
    isObject(value) &&
    typeof value.draft_id === "string" &&
    typeof value.kind === "string" &&
    typeof value.prepared_at === "string" &&
    typeof value.state === "string" &&
    isObject(value.payload) &&
    isObject(value.summary) &&
    typeof value.summary.direction === "string"
  );
}

export interface ApprovalsApi {
  waiting: (propertyId: string) => Promise<WaitingPage>;
}

export const approvalsApi: ApprovalsApi = {
  waiting: async (propertyId) => {
    let response: Response;
    try {
      response = await fetch(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/financial-drafts-waiting`,
        { credentials: "include", headers: { Accept: "application/json" } },
      );
    } catch {
      throw new ApprovalsUnavailableError();
    }
    if ([401, 403, 404].includes(response.status)) {
      throw new ApprovalsNotAllowedError();
    }
    if (!response.ok) throw new ApprovalsUnavailableError();
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ApprovalsUnavailableError();
    }
    const data = isObject(body) ? body.data : null;
    if (
      !isObject(data) ||
      typeof data.business_date !== "string" ||
      !Array.isArray(data.waiting) ||
      !Array.isArray(data.decided_today) ||
      !data.waiting.every(isDraft) ||
      !data.decided_today.every(isDraft)
    ) {
      throw new ApprovalsUnavailableError();
    }
    return data as unknown as WaitingPage;
  },
};
