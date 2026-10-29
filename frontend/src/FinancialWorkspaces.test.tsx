import { readFileSync } from "node:fs";
const financialStyles = readFileSync("src/styles.css", "utf8");
import {
  act,
  cleanup,
  waitFor,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ActionContextEvidence,
  TargetEvidence,
  FinancialProposalEvidence,
  PaymentEvidence,
  CreditEvidence,
  RefundEvidence,
  CreditApplicationRecordEvidence,
  FinancialOutcomeEvidence,
} from "./FinancialEvidence";
import {
  financialObject,
  financialInteger,
  type FinancialObject,
} from "./financialContracts";
import { financialMoney } from "./financialUi";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import { createFinancialReferenceClient } from "./financialReferenceClient";
import { loadFinancialActionContext } from "./financialUiContext";
import {
  actionContextFixtures,
  type FinancialActionFixture,
} from "./test/financialActionContextFixtures";
import {
  FinancialCurrentAfterConfirmation,
  FinancialManagement,
  type ConfirmedFinancialAction,
} from "./FinancialManagement";
import { FinancialAllocationReceiptWorkspace } from "./FinancialAllocationReceiptWorkspace";
import { FinancialPaymentWorkspace } from "./FinancialPaymentWorkspace";
import { FinancialCreditWorkspace } from "./FinancialCreditWorkspace";
import { FinancialRefundWorkspace } from "./FinancialRefundWorkspace";
import { createFinancialTransport } from "./financialClient";
import {
  FINANCIAL_CAPABILITIES,
  type FinancialCapabilities,
} from "./financialReferenceClient";
import { captureFinancialRequest, financialId } from "./financialContracts";
import type { FinancialWorkspaceProps } from "./financialUi";
import { fixture, ids } from "./test/financialFixtures";

afterEach(cleanup);
async function loadSample(
  sample: FinancialActionFixture,
  actorId = sample.actorId,
) {
  let calls = 0,
    offset = 0;
  let expectedCursor: string | null = null;
  const items = sample.data.items;
  if (!Array.isArray(items))
    throw new Error("Expected synthetic context items");
  const limit = sample.request.limit ?? 50;
  const client = createFinancialReferenceClient((url, init) => {
    calls++;
    if (typeof url !== "string") throw new Error("Expected finite context URL");
    expect(
      new URL(url, "https://synthetic.invalid").searchParams.get("cursor"),
    ).toBe(expectedCursor);
    const requestId = new Headers(init?.headers).get("X-Request-ID");
    expect(init?.method).toBe("GET");
    const pageItems = items.slice(offset, offset + limit);
    offset += limit;
    if (offset < items.length) {
      const last = financialObject(pageItems[pageItems.length - 1]);
      if (
        typeof sample.data.revision !== "string" ||
        typeof last.id !== "string" ||
        typeof last.sequence !== "number"
      )
        throw new Error("Expected synthetic continuation facts");
      expectedCursor = `${sample.data.revision}:${last.sequence.toString()}:${last.id}`;
    } else expectedCursor = null;
    return Promise.resolve(
      new Response(
        stringifyFinancialJson(
          {
            data: { ...sample.data, items: pageItems },
            page: { limit, next_cursor: expectedCursor },
            meta: {
              request_id: requestId,
              actor_id: actorId,
              property_id: sample.propertyId,
            },
          },
          1_048_576,
        ),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId ?? "",
          },
        },
      ),
    );
  });
  const data = await loadFinancialActionContext(
    {
      actorId,
      propertyId: sample.propertyId,
      signal: new AbortController().signal,
    },
    sample.request,
    client,
  );
  expect(calls).toBe(Math.max(1, Math.ceil(items.length / limit)));
  return data;
}
function selected(
  predicate: (sample: FinancialActionFixture) => boolean,
): FinancialActionFixture {
  const sample = [...actionContextFixtures].reverse().find(predicate);
  if (!sample) throw new Error("Required synthetic history is missing");
  return sample;
}
function value(region: HTMLElement, label: string): string | null {
  return (
    within(region).getByText(label, { selector: "dt" }).nextElementSibling
      ?.textContent ?? null
  );
}

describe("finite original and current financial evidence", () => {
  it.each(actionContextFixtures.map((sample, index) => ({ sample, index })))(
    "TEST-FE-428 renders actual complete history $index with finite source facts and no invented missing values",
    async ({ sample }) => {
      const data = await loadSample(sample);
      render(<ActionContextEvidence value={data} />);
      expect(
        screen.queryAllByText("Unavailable", { exact: true }),
      ).toHaveLength(0);
      expect(document.body).not.toHaveTextContent("[object Object]");
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getAllByRole("heading").length).toBeGreaterThan(0);
    },
  );

  it("TEST-FE-429 keeps original Receipt name and issuer distinct from the viewing actor", async () => {
    const sample = selected((s) => s.request.purpose === "receipt_reprint");
    const data = await loadSample(sample, ids.other);
    const receipt = financialObject(financialObject(data.context).receipt);
    render(
      <>
        <p>Viewing actor: {ids.other}</p>
        <ActionContextEvidence value={data} />
      </>,
    );
    const region = screen.getByRole("region", {
      name: "Original Receipt identity",
    });
    expect(value(region, "Original payer name")).toBe(
      financialObject(receipt.identity_snapshot).payer_legal_name,
    );
    expect(value(region, "Original issuer")).toBe(receipt.issued_by);
    expect(value(region, "Original issuer")).not.toBe(ids.other);
    expect(value(region, "Original Receipt number")).toBe(
      receipt.receipt_number,
    );
    expect(
      screen.getByRole("region", { name: "Current payment position" }),
    ).toBeVisible();
  });

  it("TEST-FE-430 retains Reservation correction history without inventing return evidence or a Payment source", async () => {
    const sample = selected((s) => {
      const context = financialObject(s.data.context);
      if (!context.refund) return false;
      return (
        typeof financialObject(financialObject(context.refund).refund)
          .source_lifecycle_event_id === "string"
      );
    });
    render(<ActionContextEvidence value={await loadSample(sample)} />);
    const correction = screen.getByRole("region", {
      name: "Original Refund correction",
    });
    expect(value(correction, "Verified returned USD")).toBe("Not recorded");
    expect(value(correction, "Verified return time")).toBe("Not recorded");
    expect(value(correction, "Return method reference")).toBe("Not recorded");
    expect(
      screen.getByText(/coordinated Reservation outcome workflow/),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Original payment facts" }),
    ).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(
      value(
        screen.getByRole("region", { name: "Original Deposit source" }),
        "Deposit type",
      ),
    ).toBe("SECURITY");
  });

  it("TEST-FE-431 shows a selected original application separately from multiple-contributor Credit totals", async () => {
    const sample = selected((s) => {
      const context = financialObject(s.data.context);
      if (!context.application || !context.credit) return false;
      const original = financialObject(context.application).amount_usd_cents;
      const applied = financialObject(
        financialObject(context.credit).position,
      ).applied_usd_cents;
      return (
        (typeof original === "number" || typeof original === "bigint") &&
        (typeof applied === "number" || typeof applied === "bigint") &&
        BigInt(original) < BigInt(applied)
      );
    });
    const data = await loadSample(sample),
      context = financialObject(data.context);
    render(<ActionContextEvidence value={data} />);
    expect(
      value(
        screen.getByRole("region", { name: "Original Credit application" }),
        "Original selected amount",
      ),
    ).toBe(
      financialMoney(financialObject(context.application).amount_usd_cents),
    );
    expect(
      value(
        screen.getByRole("region", { name: "Current Credit position" }),
        "Applied USD",
      ),
    ).toBe(
      financialMoney(
        financialObject(financialObject(context.credit).position)
          .applied_usd_cents,
      ),
    );
    expect(
      screen.getByText(
        /selected original is distinct from current aggregate balances/,
      ),
    ).toBeVisible();
  });

  it("TEST-FE-432 pages every loaded Invoice line without dropping totals or retaining an old target page", async () => {
    const sample = selected(
      (s) =>
        s.request.purpose === "allocation" &&
        s.request.target_kind === "INVOICE",
    );
    const data = await loadSample(sample),
      target = structuredClone(financialObject(data.target));
    if (!Array.isArray(data.items) || !data.items[0])
      throw new Error("Expected original Invoice line");
    const original = financialObject(data.items[0]);
    const items: FinancialObject[] = Array.from(
      { length: 102 },
      (_, index) => ({
        ...structuredClone(original),
        id: `00000000-0000-4000-8000-${(index + 1).toString().padStart(12, "0")}`,
        sequence: index + 1,
        data: {
          ...structuredClone(financialObject(original.data)),
          description: `Evidence line ${(index + 1).toString().padStart(3, "0")}`,
        },
      }),
    );
    target.line_count = 102;
    for (const [field, lineField] of [
      ["original_total_usd_cents", "original_amount_usd_cents"],
      ["adjusted_total_usd_cents", "adjusted_amount_usd_cents"],
      ["outstanding_usd_cents", "outstanding_usd_cents"],
    ] as const) {
      const amount = financialObject(original.data)[lineField];
      if (typeof amount !== "number" && typeof amount !== "bigint")
        throw new Error("Expected exact target amount");
      target[field] = BigInt(amount) * 102n;
    }
    const complete = await loadSample({
      ...sample,
      data: { ...data, target, items, item_count: 102 },
    });
    const { rerender } = render(
      <TargetEvidence target={complete.target} items={complete.items} />,
    );
    expect(screen.getByRole("table")).toHaveAccessibleName(
      /102 lines loaded; showing 1–50/,
    );
    expect(screen.getAllByRole("row")).toHaveLength(51);
    expect(
      screen.queryByRole("cell", { name: /Evidence line 051/ }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Next evidence lines" }),
    );
    expect(screen.getByRole("table")).toHaveAccessibleName(
      /102 lines loaded; showing 51–100/,
    );
    expect(
      screen.getByRole("cell", { name: /Evidence line 051/ }),
    ).toBeVisible();
    expect(
      screen.queryByRole("cell", { name: /Evidence line 001/ }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Next evidence lines" }),
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(
      screen.getByRole("cell", { name: /Evidence line 102/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Next evidence lines" }),
    ).toBeDisabled();
    expect(
      value(
        screen.getByRole("region", { name: "Selected Invoice facts" }),
        "Original Invoice total",
      ),
    ).toBe(financialMoney(target.original_total_usd_cents));
    rerender(
      <TargetEvidence
        target={{ ...target, id: ids.other }}
        items={items.map((item) => ({
          ...item,
          data: { ...financialObject(item.data), invoice_id: ids.other },
        }))}
      />,
    );
    expect(
      screen.getByRole("cell", { name: /Evidence line 001/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Previous evidence lines" }),
    ).toBeDisabled();
  });
});

function currentRefund(
  purpose: "refund_return" | "refund_correction_reversal",
) {
  return selected((sample) => {
    if (sample.request.purpose !== purpose) return false;
    const c = financialObject(sample.data.context);
    const refund = financialObject(financialObject(c.refund).refund);
    return (
      refund.source_lifecycle_event_id === null &&
      (purpose === "refund_return"
        ? BigInt(
            financialObject(c.refund).net_refund_usd_cents as number | bigint,
          ) > 0n
        : c.reversal === null)
    );
  });
}
function refundProps(
  sample: FinancialActionFixture,
  grant: keyof FinancialCapabilities,
  sourceData?: FinancialObject,
) {
  const calls: {
    url: string;
    method: string;
    signal: AbortSignal | null | undefined;
  }[] = [];
  let wait: Promise<void> | null = null;
  const fetcher: typeof fetch = async (url, init) => {
    if (typeof url !== "string")
      throw new Error("Expected exact synthetic URL");
    calls.push({ url, method: init?.method ?? "", signal: init?.signal });
    if (wait) await wait;
    const requestId = new Headers(init?.headers).get("X-Request-ID");
    const context = url.includes("-context"),
      source = url.includes("/refund-sources/");
    const resource = financialObject(
      financialObject(sample.data.context).refund,
    );
    const data = context
      ? sample.data
      : source
        ? sourceData
        : {
            ...resource,
            corrections: { items: [], page: { limit: 50, next_cursor: null } },
          };
    if (!data) throw new Error("Missing synthetic source");
    return new Response(
      stringifyFinancialJson({
        data,
        ...(context ? { page: { limit: 50, next_cursor: null } } : {}),
        meta: {
          property_id: sample.propertyId,
          actor_id: sample.actorId,
          request_id: requestId,
        },
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId ?? "",
        },
      },
    );
  };
  const review =
    vi.fn<
      ReturnType<FinancialWorkspaceProps["commands"]["beginReview"]>["review"]
    >();
  const recovery = {
    load: vi.fn(() => Promise.resolve({ kind: "unavailable" } as const)),
    submit: vi.fn(() => Promise.resolve({ kind: "invalidated" } as const)),
    replay: vi.fn(() => Promise.resolve({ kind: "invalidated" } as const)),
  };
  const props: FinancialWorkspaceProps = {
    scope: {
      actorId: sample.actorId,
      propertyId: sample.propertyId,
      signal: new AbortController().signal,
    },
    capabilities: Object.fromEntries(
      FINANCIAL_CAPABILITIES.map((c) => [c, c === grant]),
    ) as FinancialCapabilities,
    services: {
      references: createFinancialReferenceClient(fetcher),
      transport: createFinancialTransport(fetcher),
      recovery,
    },
    commands: {
      ready: true,
      busy: false,
      revision: 0,
      beginReview: () => ({ isCurrent: () => true, review }),
      invalidate: vi.fn(),
    },
  };
  return {
    props,
    recovery,
    calls,
    review,
    pause: (promise: Promise<void>) => {
      wait = promise;
    },
  };
}
function fill(label: string | RegExp, text: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value: text } });
}
function returnFields(sample: FinancialActionFixture) {
  fill(
    "Refund reference",
    financialId(
      financialObject(
        financialObject(financialObject(sample.data.context).refund).refund,
      ).id,
    ),
  );
  fill("Demonstrated returned amount (USD)", "0.01");
  fill(/Verified return time/, "2026-09-08T11:00:00.123");
  fill("Actual return method reference", "Synthetic bank return");
  fill("Evidence reference", "Synthetic verified evidence");
  fill("Reason", "Demonstrated return only");
}
function reviewRefund() {
  fireEvent.click(screen.getByRole("button", { name: "Review Refund action" }));
}

describe("Refund forms through accepted read clients", () => {
  it("TEST-FE-439 performs no automatic financial read or send and uses only the exact action-granted context", async () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.correct");
    render(<FinancialRefundWorkspace {...h.props} />);
    expect(h.calls).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "View Refunds" })).toBeNull();
    fill("Refund reference", sample.request.source_id);
    fireEvent.click(
      screen.getByRole("button", { name: "Load current source facts" }),
    );
    await screen.findByRole("region", { name: "Original completed Refund" });
    expect(h.calls).toHaveLength(1);
    expect(h.calls[0]?.method).toBe("GET");
    expect(h.calls[0]?.url).toContain(
      `/properties/${sample.propertyId}/refunds/${sample.request.source_id}/verified-return-context`,
    );
    expect(h.review).not.toHaveBeenCalled();
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });

  it("TEST-FE-440 reloads the exact source and prepares explicit USD return evidence without sending", async () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.correct");
    render(<FinancialRefundWorkspace {...h.props} />);
    returnFields(sample);
    reviewRefund();
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledTimes(1);
    });
    const call = h.review.mock.calls[0];
    if (!call) throw new Error("Expected review");
    const captured = captureFinancialRequest(call[0]);
    expect(captured.operation).toBe("refundReturn");
    expect(captured.target).toEqual({ id: sample.request.source_id });
    expect(captured.wireBody).toContain('"returned_amount_minor":1');
    expect(captured.wireBody).toContain(
      '"returned_at":"2026-09-08T11:00:00.123+07:00"',
    );
    expect(call[1].consequence).toMatch(
      /does not establish a collection right/,
    );
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });

  it("TEST-FE-441 addresses the exact original Refund and correction pair", async () => {
    const sample = currentRefund("refund_correction_reversal"),
      h = refundProps(sample, "refunds.corrections.reverse");
    render(<FinancialRefundWorkspace {...h.props} />);
    fill("Refund reference", sample.request.refund_id ?? "");
    fill("Original return correction reference", sample.request.source_id);
    fill("Evidence reference", "Synthetic correction evidence");
    fill("Reason", "Correct erroneous return evidence");
    reviewRefund();
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledTimes(1);
    });
    const request = h.review.mock.calls[0]?.[0];
    expect(request?.operation).toBe("refundReturnReverse");
    expect(request?.target).toEqual({
      id: sample.request.refund_id,
      correctionId: sample.request.source_id,
    });
    expect(h.calls[0]?.url).toContain(
      `/refunds/${sample.request.refund_id ?? ""}/corrections/${sample.request.source_id}/reversal-context`,
    );
  });

  it.each(["refunds.correct", "refunds.corrections.reverse"] as const)(
    "TEST-FE-442 keeps legacy Reservation history readable with %s but excludes general corrections",
    async (grant) => {
      const original = selected(
        (s) =>
          s.request.purpose === "refund_correction_reversal" &&
          financialObject(
            financialObject(financialObject(s.data.context).refund).refund,
          ).source_lifecycle_event_id !== null,
      );
      // Both contexts retain the same authoritative Refund; return mode has no selected correction fields.
      const sample =
        grant === "refunds.corrections.reverse"
          ? original
          : (() => {
              const data = structuredClone(original.data),
                c = financialObject(data.context);
              const context = { ...c };
              delete context.correction;
              delete context.reversal;
              const refundId = financialId(
                financialObject(financialObject(c.refund).refund).id,
              );
              return {
                ...original,
                request: {
                  operation: "financialActionContext" as const,
                  purpose: "refund_return" as const,
                  source_id: refundId,
                },
                data: {
                  ...data,
                  purpose: "refund_return",
                  refund_id: null,
                  source_id: refundId,
                  context,
                },
              };
            })();
      const h = refundProps(sample, grant);
      render(<FinancialRefundWorkspace {...h.props} />);
      fill("Refund reference", original.request.refund_id ?? "");
      if (grant === "refunds.corrections.reverse")
        fill(
          "Original return correction reference",
          original.request.source_id,
        );
      fireEvent.click(
        screen.getByRole("button", { name: "Load current source facts" }),
      );
      await screen.findByRole("link", {
        name: "coordinated Reservation outcome workflow",
      });
      expect(
        screen.getByRole("button", { name: "Review Refund action" }),
      ).toBeDisabled();
      expect(h.review).not.toHaveBeenCalled();
    },
  );

  it.each(["PAYMENT", "CREDIT", "PET_DEPOSIT"] as const)(
    "TEST-FE-443 loads only supported %s source and records the confirmed USD amount",
    async (type) => {
      const sample = currentRefund("refund_return"),
        p = financialObject(sample.data.payment_resource);
      const sourceData: FinancialObject = {
        source_type: type,
        source_id: ids.payment,
        property_id: sample.propertyId,
        recipient_customer_id: ids.customer,
        refund_currency: "USD",
        available_usd_cents: 100,
        eligible: true,
        ...(type === "PET_DEPOSIT"
          ? {
              pet_refund_review_id: ids.event,
              pet_departure_id: ids.other,
              pet_approval_id: ids.application,
              lease_id: ids.invoice,
              qualified_at: "2026-09-01T12:00:00+07:00",
            }
          : {
              source_payment: p.payment ?? null,
              source_exchange_rate: p.exchange_rate ?? null,
              receipt_evidence: { received_at: null, evidence_reference: null },
            }),
      };
      const h = refundProps(sample, "refunds.create", sourceData);
      render(<FinancialRefundWorkspace {...h.props} />);
      fill("Refund source", type);
      fill("Source reference", ids.payment);
      if (type === "PET_DEPOSIT")
        fill("Qualifying Pet review reference", ids.event);
      fill("Refund amount (USD)", "0.99");
      fill("Reason", "Synthetic completed USD payout");
      reviewRefund();
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledTimes(1);
      });
      const request = h.review.mock.calls[0]?.[0];
      expect(request?.body).toEqual({
        currency: "USD",
        source_type: type,
        source_id: ids.payment,
        amount_usd_cents: 99n,
        reason: "Synthetic completed USD payout",
        ...(type === "PET_DEPOSIT" ? { pet_refund_review_id: ids.event } : {}),
      });
      expect(h.calls[0]?.url).toContain(
        `/refund-sources/${type}/${ids.payment}`,
      );
      if (type === "PET_DEPOSIT")
        expect(h.calls[0]?.url).toContain(`pet_refund_review_id=${ids.event}`);
      expect(
        screen.queryByRole("option", {
          name: /Reservation|Security|Settlement/i,
        }),
      ).toBeNull();
      expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    },
  );

  it("TEST-FE-444 refuses a return larger than the exact current net payout", async () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.correct");
    render(<FinancialRefundWorkspace {...h.props} />);
    returnFields(sample);
    fill("Demonstrated returned amount (USD)", "90000000000000");
    reviewRefund();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /exceeds the current net USD payout/,
    );
    expect(h.review).not.toHaveBeenCalled();
  });

  it("TEST-FE-445 aborts an old source response on field edits and does not restore its review", async () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.correct");
    let release!: () => void;
    h.pause(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    render(<FinancialRefundWorkspace {...h.props} />);
    returnFields(sample);
    reviewRefund();
    await waitFor(() => {
      expect(h.calls).toHaveLength(1);
    });
    fill("Refund reference", ids.other);
    expect(h.calls[0]?.signal?.aborted).toBe(true);
    await act(async () => {
      release();
      await Promise.resolve();
    });
    expect(h.review).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("region", { name: "Original completed Refund" }),
    ).toBeNull();
    expect(screen.getByLabelText("Refund reference")).toHaveValue(ids.other);
  });

  it("TEST-FE-446 reads an authorized original Refund while command recovery is unavailable", async () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.read");
    h.props.commands.ready = false;
    render(<FinancialRefundWorkspace {...h.props} />);
    fill("Refund reference", sample.request.source_id);
    fireEvent.click(
      screen.getByRole("button", { name: "Load original Refund" }),
    );
    await screen.findByRole("region", { name: "Original completed Refund" });
    expect(h.calls[0]?.url).toContain(`/refunds/${sample.request.source_id}`);
    expect(h.recovery.load).not.toHaveBeenCalled();
    expect(h.review).not.toHaveBeenCalled();
  });
});

describe("native return time entry", () => {
  it("TEST-FE-447 prevents review when a native date-time value is invalid instead of inventing a return time", () => {
    const sample = currentRefund("refund_return"),
      h = refundProps(sample, "refunds.correct");
    render(<FinancialRefundWorkspace {...h.props} />);
    returnFields(sample);
    const input =
      screen.getByLabelText<HTMLInputElement>(/Verified return time/);
    expect(input).toHaveValue("2026-09-08T11:00:00.123");
    fill(/Verified return time/, "2026-09-08T11:00:00.123456");
    expect(input).toHaveValue("");
    expect(input.checkValidity()).toBe(false);
    reviewRefund();
    expect(h.calls).toHaveLength(0);
    expect(h.review).not.toHaveBeenCalled();
  });
});

function creditFixtureText(value: unknown): string {
  if (typeof value !== "string")
    throw new Error("Expected exact synthetic text");
  return value;
}
function reviewedCredit(h: ReturnType<typeof creditHarness>) {
  const request = h.review.mock.calls[0]?.[0];
  if (!request) throw new Error("Expected explicit Credit review");
  return request;
}
function creditSample(
  purpose: FinancialActionFixture["request"]["purpose"],
  target?: "INVOICE" | "LATE_PAYMENT_CHARGE",
  reversed = false,
) {
  return selected(
    (sample) =>
      sample.request.purpose === purpose &&
      (target === undefined ||
        sample.request.target_kind === target ||
        (sample.data.target !== null &&
          financialObject(sample.data.target).kind === target)) &&
      (purpose.endsWith("reversal")
        ? (financialObject(sample.data.context).reversal !== null) === reversed
        : true),
  );
}
function creditHarness(
  sample: FinancialActionFixture,
  grant: keyof FinancialCapabilities,
) {
  const base = refundProps(sample, grant);
  const calls: {
    url: string;
    method: string;
    signal: AbortSignal | null | undefined;
  }[] = [];
  let pause: Promise<void> | null = null;
  let override: ((url: string) => FinancialObject | FinancialObject[]) | null =
    null;
  const fetcher: typeof fetch = async (url, init) => {
    if (typeof url !== "string")
      throw new Error("Expected synthetic Credit URL");
    calls.push({ url, method: init?.method ?? "", signal: init?.signal });
    if (pause) await pause;
    const requestId = new Headers(init?.headers).get("X-Request-ID");
    const context = url.includes("-context");
    let data = context
      ? sample.data
      : override
        ? override(url)
        : financialObject(financialObject(sample.data.context).credit);
    let page;
    if (context) {
      const u = new URL(url, "https://synthetic.invalid"),
        cursor = u.searchParams.get("cursor");
      const rows = Array.isArray(sample.data.items)
        ? sample.data.items.map(financialObject)
        : [];
      const offset = cursor ? Number(cursor.split(":")[1]) : 0,
        items = rows.slice(offset, offset + 50),
        last = items.at(-1);
      const next =
        offset + items.length < rows.length && last
          ? `${creditFixtureText(sample.data.revision)}:${financialInteger(last.sequence).toString()}:${creditFixtureText(last.id)}`
          : null;
      data = { ...sample.data, items };
      page = { limit: 50, next_cursor: next };
    } else if (Array.isArray(data)) page = { limit: 50, next_cursor: null };
    return new Response(
      stringifyFinancialJson({
        data,
        ...(page ? { page } : {}),
        meta: {
          actor_id: sample.actorId,
          property_id: sample.propertyId,
          request_id: requestId,
        },
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId ?? "",
        },
      },
    );
  };
  base.props.services.references = createFinancialReferenceClient(fetcher);
  base.props.services.transport = createFinancialTransport(fetcher);
  return {
    ...base,
    calls,
    pause: (value: Promise<void>) => {
      pause = value;
    },
    reply: (value: typeof override) => {
      override = value;
    },
  };
}
function creditProposal(
  sample: FinancialActionFixture,
  requested = 101n,
  amount = requested,
) {
  const target = financialObject(sample.data.target),
    context = financialObject(sample.data.context),
    source = financialObject(context.credit),
    credit = financialObject(source.credit);
  if (!Array.isArray(sample.data.items) || !sample.data.items.length)
    throw new Error("Missing synthetic Invoice line");
  const first = financialObject(sample.data.items[0]);
  return {
    property_id: sample.propertyId,
    credit_id: financialId(credit.id),
    invoice_id: financialId(target.id),
    customer_id: financialId(credit.customer_id),
    invoice_version: 1,
    requested_amount_usd_cents: requested,
    amount_usd_cents: amount,
    remaining_requested_usd_cents: requested - amount,
    available_usd_cents: financialInteger(
      financialObject(source.position).available_usd_cents,
    ),
    generated_at: "2026-09-08T10:00:00+07:00",
    policy: "RENT_SERVICE_SOURCE_ORDER",
    continuation: "CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL",
    continuation_status: requested === amount ? "COMPLETE" : "MORE_ELIGIBLE",
    details: [
      {
        invoice_line_id: financialId(first.id),
        category: "RENT",
        attribution_basis: "RENT_FIRST_PROPOSAL",
        amount_usd_cents: amount,
        outstanding_usd_cents: financialInteger(
          financialObject(first.data).outstanding_usd_cents,
        ),
      },
    ],
  } satisfies FinancialObject;
}
function creditInput(
  sample: FinancialActionFixture,
  mode: "recognize" | "apply" | "reverse" | "applicationReverse",
) {
  fill(
    mode === "recognize"
      ? "Source Payment reference"
      : mode === "applicationReverse"
        ? "Original Credit application reference"
        : "Credit reference",
    sample.request.source_id,
  );
  if (mode === "recognize" || mode === "apply")
    fill("Credit amount (USD)", "1.01");
  if (mode === "recognize")
    fill("Payer authorization reference", "Synthetic explicit payer consent");
  if (mode === "apply")
    fill(
      "Target reference",
      creditFixtureText(financialObject(sample.data.target).id),
    );
  else fill("Credit reason", "Correct the selected original only");
}

describe("Credit staff forms using actual scoped clients", () => {
  it.each([
    {
      purpose: "credit_recognition",
      grant: "credits.recognize",
      mode: "recognize",
      operation: "creditRecognize",
    },
    {
      purpose: "credit_reversal",
      grant: "credits.reverse",
      mode: "reverse",
      operation: "creditReverse",
    },
    {
      purpose: "credit_application_reversal",
      grant: "credits.applications.reverse",
      mode: "applicationReverse",
      operation: "creditApplicationReverse",
    },
  ] as const)(
    "TEST-FE-462 prepares $operation from fresh original facts under its action-only grant without posting",
    async ({ purpose, grant, mode, operation }) => {
      const sample = creditSample(purpose),
        h = creditHarness(sample, grant);
      render(<FinancialCreditWorkspace {...h.props} />);
      creditInput(sample, mode);
      expect(h.calls).toHaveLength(0);
      expect(
        screen.queryByRole("button", { name: "View Customer Credit" }),
      ).toBeNull();
      fireEvent.click(
        screen.getByRole("button", { name: "Review Credit action" }),
      );
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledOnce();
      });
      const request = reviewedCredit(h),
        captured = captureFinancialRequest(request);
      expect(request.operation).toBe(operation);
      expect(financialObject(request.target).id).toBe(sample.request.source_id);
      expect(captured.wireBody).toContain("Correct the selected original only");
      if (mode === "recognize")
        expect(captured.wireBody).toContain('"amount_usd_cents":101');
      expect(
        h.calls.every((c) => c.method === "GET" && c.url.includes("-context")),
      ).toBe(true);
      expect(h.recovery.submit).not.toHaveBeenCalled();
      expect(h.recovery.replay).not.toHaveBeenCalled();
    },
  );

  it.each(["credit_reversal", "credit_application_reversal"] as const)(
    "TEST-FE-463 shows already reversed $0 history while refusing a new reversal",
    async (purpose) => {
      const sample = creditSample(purpose, undefined, true),
        mode = purpose === "credit_reversal" ? "reverse" : "applicationReverse",
        h = creditHarness(
          sample,
          mode === "reverse"
            ? "credits.reverse"
            : "credits.applications.reverse",
        );
      render(<FinancialCreditWorkspace {...h.props} />);
      creditInput(sample, mode);
      fireEvent.click(
        screen.getByRole("button", { name: "Load current Credit context" }),
      );
      expect(
        await screen.findByRole("region", { name: "Linked reversal" }),
      ).toBeVisible();
      fireEvent.click(
        screen.getByRole("button", { name: "Review Credit action" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        /Resolve active|already has a linked reversal/,
      );
      expect(h.review).not.toHaveBeenCalled();
    },
  );

  it("TEST-FE-464 preserves a fresh exact within-Invoice proposal and never automatically sends or continues it", async () => {
    const sample = creditSample("credit_application", "INVOICE"),
      h = creditHarness(sample, "credits.apply"),
      proposal = creditProposal(sample);
    h.reply(() => proposal);
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fireEvent.click(
      screen.getByRole("button", { name: "Load Credit proposal" }),
    );
    expect(
      await screen.findByRole("region", {
        name: "Credit application proposal",
      }),
    ).toBeVisible();
    expect(h.review).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    expect(
      h.calls.filter((c) => c.url.includes("application-proposal")),
    ).toHaveLength(2);
    const request = reviewedCredit(h),
      body = financialObject(request.body);
    expect(request.operation).toBe("creditApply");
    expect(
      stringifyFinancialJson(
        financialObject(financialObject(body.intent).proposal),
      ),
    ).toBe(stringifyFinancialJson(proposal));
    expect(captureFinancialRequest(request).wireBody).toContain(
      '"mode":"PROPOSAL"',
    );
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });

  it.each(["DIRECT_CHARGE", "DESIGNATED"] as const)(
    "TEST-FE-465 prepares an exact separate Charge application with $0 attribution",
    async (basis) => {
      const sample = creditSample("credit_application", "LATE_PAYMENT_CHARGE"),
        h = creditHarness(sample, "credits.apply");
      render(<FinancialCreditWorkspace {...h.props} />);
      fill("Credit target", "LATE_PAYMENT_CHARGE");
      creditInput(sample, "apply");
      fill("Credit attribution", basis);
      if (basis === "DESIGNATED")
        fill("Customer designation reference", "Synthetic Charge designation");
      fireEvent.click(
        screen.getByRole("button", { name: "Review Credit action" }),
      );
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledOnce();
      });
      const request = reviewedCredit(h),
        intent = financialObject(financialObject(request.body).intent);
      expect(intent).toEqual({
        mode: basis,
        late_payment_charge_id: sample.request.target_id,
        amount_usd_cents: 101n,
        ...(basis === "DESIGNATED"
          ? { designation_reference: "Synthetic Charge designation" }
          : {}),
      });
      expect(captureFinancialRequest(request).wireBody).not.toContain(
        "invoice_id",
      );
      expect(h.calls.every((c) => c.url.includes("-context"))).toBe(true);
    },
  );

  it("TEST-FE-466 confirms explicit designated line amounts only after reloading the complete target", async () => {
    const sample = creditSample("credit_application", "INVOICE"),
      h = creditHarness(sample, "credits.apply");
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fill("Credit attribution", "DESIGNATED");
    fill("Customer designation reference", "Synthetic line designation");
    fireEvent.click(
      screen.getByRole("button", { name: "Load current Credit context" }),
    );
    const line = await screen.findByLabelText(/Designated USD for line/);
    fireEvent.change(line, { target: { value: "1.23" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    expect(h.calls).toHaveLength(2);
    const request = reviewedCredit(h);
    expect(financialObject(financialObject(request.body).intent)).toMatchObject(
      {
        mode: "DESIGNATED",
        amount_usd_cents: 123n,
        details: [
          {
            invoice_line_id: financialObject(
              (sample.data.items as FinancialObject[])[0],
            ).id,
            amount_usd_cents: 123n,
          },
        ],
      },
    );
    expect(captureFinancialRequest(request).wireBody).toContain(
      '"designation_reference":"Synthetic line designation"',
    );
  });

  it("TEST-FE-467 rejects designation beyond fresh line balance and makes no proposal or command request", async () => {
    const sample = creditSample("credit_application", "INVOICE"),
      h = creditHarness(sample, "credits.apply");
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fill("Credit attribution", "DESIGNATED");
    fill("Customer designation reference", "Synthetic designation");
    fireEvent.click(
      screen.getByRole("button", { name: "Load current Credit context" }),
    );
    fireEvent.change(await screen.findByLabelText(/Designated USD for line/), {
      target: { value: "90000000000000" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /selected line changed|exceeds its current/,
    );
    expect(h.review).not.toHaveBeenCalled();
    expect(h.calls.every((c) => c.url.includes("-context"))).toBe(true);
  });

  it("TEST-FE-468 aborts a superseded proposal and refuses late context and confirmation", async () => {
    const sample = creditSample("credit_application", "INVOICE"),
      h = creditHarness(sample, "credits.apply");
    let release!: () => void;
    h.pause(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    await waitFor(() => {
      expect(h.calls).toHaveLength(1);
    });
    fill("Target reference", ids.other);
    expect(h.calls[0]?.signal?.aborted).toBe(true);
    await act(async () => {
      release();
      await Promise.resolve();
    });
    expect(h.review).not.toHaveBeenCalled();
    expect(h.calls).toHaveLength(1);
    expect(
      screen.queryByRole("region", { name: "Selected Invoice facts" }),
    ).toBeNull();
  });

  it("TEST-FE-469 reads Credit list, selected original and flattened ledger events without requiring command recovery", async () => {
    const sample = creditSample("credit_reversal"),
      h = creditHarness(sample, "credits.read"),
      resource = financialObject(financialObject(sample.data.context).credit),
      credit = financialObject(resource.credit);
    h.props.commands.ready = false;
    h.reply((url) =>
      url.includes("/customers/")
        ? [resource]
        : url.includes("/ledger")
          ? {
              ...resource,
              history: {
                items: [
                  {
                    event_kind: "RECOGNITION",
                    event_id: financialId(credit.id),
                    occurred_at: creditFixtureText(credit.recognized_at),
                    balance_effect_usd_cents: financialInteger(
                      credit.recognized_usd_cents,
                    ),
                    available_after_usd_cents: financialInteger(
                      credit.recognized_usd_cents,
                    ),
                    source_kind: "CREDIT",
                    source_id: financialId(credit.id),
                    actor_id: financialId(credit.recognized_by),
                    reason: creditFixtureText(credit.reason),
                    reason_in_source: false,
                  },
                ],
                page: { limit: 50, next_cursor: null },
              },
            }
          : resource,
    );
    render(<FinancialCreditWorkspace {...h.props} />);
    fill(
      "Customer reference for Credit list",
      creditFixtureText(credit.customer_id),
    );
    // Selecting a Credit from a list must override an earlier application-read mode.
    fill("Credit record type", "application");
    fill(
      "Customer reference for Credit list",
      creditFixtureText(credit.customer_id),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load Customer Credit list" }),
    );
    const list = await screen.findByRole("region", {
      name: "Customer Credit list page",
    });
    fireEvent.click(within(list).getByRole("button", { name: /originally/ }));
    expect(
      await screen.findByRole("region", {
        name: "Original Credit recognition",
      }),
    ).toBeVisible();
    expect(h.calls[1]?.url).toContain(
      `/customer-credits/${creditFixtureText(credit.id)}`,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load Credit event history" }),
    );
    const table = await screen.findByRole("table", {
      name: "Credit event history page",
    });
    expect(table).toHaveTextContent(creditFixtureText(credit.recognized_by));
    expect(table).toHaveTextContent(creditFixtureText(credit.reason));
    expect(table).not.toHaveTextContent("Unavailable");
    expect(h.review).not.toHaveBeenCalled();
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
});

function multiLineCreditSample(count: number): FinancialActionFixture {
  const source = structuredClone(creditSample("credit_application", "INVOICE"));
  if (!Array.isArray(source.data.items) || !source.data.items[0])
    throw new Error("Missing synthetic target line");
  const line = financialObject(source.data.items[0]);
  source.data.items = Array.from({ length: count }, (_, i) => ({
    ...line,
    id: `00000000-0000-4000-8000-${(i + 1).toString().padStart(12, "0")}`,
    sequence: i + 1,
    data: {
      ...financialObject(line.data),
      description: `Synthetic Credit line ${(i + 1).toString()}`,
      original_amount_usd_cents: 1,
      adjusted_amount_usd_cents: 1,
      outstanding_usd_cents: 1,
    },
  }));
  source.data.target = {
    ...financialObject(source.data.target),
    line_count: count,
    original_total_usd_cents: count,
    adjusted_total_usd_cents: count,
    outstanding_usd_cents: count,
  };
  source.data.item_count = count;
  return source;
}
describe("complete Credit batches and original application reads", () => {
  it("TEST-FE-470 reviews only the returned 500-line batch from a 501-cent request after all 11 context pages", async () => {
    const sample = multiLineCreditSample(501),
      h = creditHarness(sample, "credits.apply"),
      proposal = creditProposal(sample, 501n, 500n);
    if (!Array.isArray(sample.data.items))
      throw new Error("Missing synthetic lines");
    proposal.details = sample.data.items.slice(0, 500).map((value) => ({
      invoice_line_id: financialId(financialObject(value).id),
      category: "RENT",
      attribution_basis: "RENT_FIRST_PROPOSAL",
      amount_usd_cents: 1n,
      outstanding_usd_cents: 1,
    }));
    h.reply(() => proposal);
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fill("Credit amount (USD)", "5.01");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    expect(h.calls).toHaveLength(12);
    expect(
      h.calls.slice(0, 11).every((c) => c.url.includes("application-context")),
    ).toBe(true);
    expect(h.calls[11]?.url).toContain("amount_usd_cents=501");
    const request = reviewedCredit(h),
      returned = financialObject(financialObject(request.body).intent).proposal;
    expect(stringifyFinancialJson(financialObject(returned))).toBe(
      stringifyFinancialJson(proposal),
    );
    expect(captureFinancialRequest(request).wireBody).toContain(
      '"remaining_requested_usd_cents":1',
    );
    expect(h.recovery.submit).not.toHaveBeenCalled();
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    const region = screen.getByRole("region", {
      name: "Credit application proposal",
    });
    expect(value(region, "Requested USD")).toBe("USD 5.01");
    expect(value(region, "This batch USD")).toBe("USD 5.00");
    expect(value(region, "Remaining requested USD")).toBe("USD 0.01");
  });
  it("TEST-FE-471 preserves designated amounts across line pages and submits their exact combined total", async () => {
    const sample = multiLineCreditSample(102),
      h = creditHarness(sample, "credits.apply");
    render(<FinancialCreditWorkspace {...h.props} />);
    creditInput(sample, "apply");
    fill("Credit attribution", "DESIGNATED");
    fill("Customer designation reference", "Synthetic two-page designation");
    fireEvent.click(
      screen.getByRole("button", { name: "Load current Credit context" }),
    );
    const firstId = "00000000-0000-4000-8000-000000000001",
      nextId = "00000000-0000-4000-8000-000000000051";
    fireEvent.change(
      await screen.findByLabelText(`Designated USD for line ${firstId}`),
      { target: { value: "0.01" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Next designation lines" }),
    );
    fill(`Designated USD for line ${nextId}`, "0.01");
    fireEvent.click(
      screen.getByRole("button", { name: "Previous designation lines" }),
    );
    expect(
      screen.getByLabelText(`Designated USD for line ${firstId}`),
    ).toHaveValue("0.01");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Credit action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    expect(h.calls).toHaveLength(6);
    expect(
      financialObject(financialObject(reviewedCredit(h).body).intent),
    ).toMatchObject({
      amount_usd_cents: 2n,
      details: [
        { invoice_line_id: firstId, amount_usd_cents: 1n },
        { invoice_line_id: nextId, amount_usd_cents: 1n },
      ],
    });
  });
  it("TEST-FE-472 renders a read-only selected application separately from the larger current aggregate position", async () => {
    const sample = selected(
        (s) =>
          s.request.purpose === "credit_application_reversal" &&
          financialObject(s.data.context).reversal === null &&
          financialObject(
            financialObject(financialObject(s.data.context).credit).position,
          ).applied_usd_cents !==
            financialObject(financialObject(s.data.context).application)
              .amount_usd_cents,
      ),
      h = creditHarness(sample, "credits.read"),
      c = financialObject(sample.data.context),
      application = financialObject(c.application),
      target = financialObject(sample.data.target);
    if (!Array.isArray(sample.data.items))
      throw new Error("Missing synthetic selected details");
    const details = sample.data.items.map((v) => {
      const line = financialObject(v),
        d = financialObject(line.data);
      return {
        id: financialId(line.id),
        detail_sequence: financialInteger(line.sequence),
        invoice_line_id: financialId(d.target_id),
        late_payment_charge_id: null,
        applied_amount_usd_cents: financialInteger(d.applied_amount_usd_cents),
        proposed_amount_usd_cents: d.proposed_amount_usd_cents ?? null,
        attribution_basis: creditFixtureText(d.attribution_basis),
      };
    });
    h.reply(() => ({
      application: {
        ...application,
        invoice_id: financialId(application.target_id),
        late_payment_charge_id: null,
      },
      details,
      credit_position: financialObject(c.credit),
      target_balance_usd_cents: financialInteger(target.outstanding_usd_cents),
      target_invoice_status: creditFixtureText(target.status),
      reversal: null,
    }));
    h.props.commands.ready = false;
    render(<FinancialCreditWorkspace {...h.props} />);
    fill("Credit record type", "application");
    fill("Original Credit application reference", sample.request.source_id);
    fireEvent.click(screen.getByRole("button", { name: "Load Credit record" }));
    const region = await screen.findByRole("region", {
      name: "Selected Credit record",
    });
    expect(
      value(
        within(region).getByRole("region", {
          name: "Original Credit application",
        }),
        "Original selected amount",
      ),
    ).toBe(financialMoney(application.amount_usd_cents));
    expect(
      value(
        within(region).getByRole("region", { name: "Current Credit position" }),
        "Applied USD",
      ),
    ).toBe(
      financialMoney(
        financialObject(financialObject(c.credit).position).applied_usd_cents,
      ),
    );
    const table = within(region).getByRole("table", {
      name: "Original Credit application details",
    });
    expect(table).toHaveTextContent("Not recorded");
    expect(region).not.toHaveTextContent("Unavailable");
    expect(h.review).not.toHaveBeenCalled();
  });
});

function paymentHarness(grant: "payments.read" | "payments.record") {
  const sample = creditSample("credit_recognition"),
    base = refundProps(sample, grant);
  const calls: {
    url: string;
    method: string;
    body: string | null;
    signal: AbortSignal | null | undefined;
  }[] = [];
  let outage = false,
    fallback = true,
    accepted = true,
    wait: Promise<void> | null = null;
  const resource = financialObject(sample.data.payment_resource);
  const method = {
    id: ids.method,
    property_id: sample.propertyId,
    code: "CASH",
    display_name: "Synthetic accepted cash",
  };
  const fetcher: typeof fetch = async (url, init) => {
    if (
      typeof url !== "string" ||
      (init?.body != null && typeof init.body !== "string")
    )
      throw new Error("Expected finite Payment request");
    calls.push({
      url,
      method: init?.method ?? "",
      body: init?.body ?? null,
      signal: init?.signal,
    });
    if (wait) await wait;
    const requestId = new Headers(init?.headers).get("X-Request-ID"),
      u = new URL(url, "https://synthetic.invalid");
    let data: FinancialObject | FinancialObject[], page;
    if (u.pathname.endsWith("/payment-methods")) {
      data = accepted ? [method] : [];
      page = { limit: 100, next_cursor: null };
    } else if (u.pathname.endsWith("/khr-preview")) {
      const request = financialObject(
          parseFinancialJson(creditFixtureText(init?.body)),
        ),
        usd = BigInt(financialInteger(request.usd_amount_cents)),
        manual = request.manual_reference;
      if (outage && !manual)
        data = {
          property_id: sample.propertyId,
          provisional: true,
          status: "source_unavailable",
          usd_amount_cents: usd,
          manual_fallback_allowed: fallback,
        };
      else {
        const reference = manual
          ? financialObject(manual)
          : {
              reference_rate_khr_per_usd: "4000.000000",
              source_reference: "Synthetic automatic quote",
              applicable_at: "2026-09-08T10:00:00+07:00",
              fallback_reason: null,
            };
        const unrounded = usd * 4020n;
        data = {
          ...reference,
          property_id: sample.propertyId,
          provisional: true,
          status: "available",
          usd_amount_cents: usd,
          rate_source: manual ? "ABA_EQUIVALENT_MANUAL" : "ABA_AUTOMATIC",
          automatic_source_unavailable: Boolean(manual),
          markup_basis_points: 50,
          system_rate_khr_per_usd: 4020,
          unrounded_khr_amount: `${(unrounded / 100n).toString()}.${(unrounded % 100n).toString().padStart(2, "0")}`,
          payable_khr_amount: (unrounded + 99n) / 100n,
        };
      }
    } else if (u.pathname.endsWith("/payments")) {
      data = [resource];
      page = { limit: 50, next_cursor: null };
    } else data = resource;
    return new Response(
      stringifyFinancialJson({
        data,
        ...(page ? { page } : {}),
        meta: {
          property_id: sample.propertyId,
          actor_id: sample.actorId,
          request_id: requestId,
        },
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId ?? "",
        },
      },
    );
  };
  base.props.services.references = createFinancialReferenceClient(
    fetcher,
    () => "synthetic-csrf",
  );
  base.props.services.transport = createFinancialTransport(fetcher);
  return {
    ...base,
    sample,
    method,
    calls,
    outage: (value = true) => {
      outage = value;
    },
    fallback: (value: boolean) => {
      fallback = value;
    },
    accepted: (value: boolean) => {
      accepted = value;
    },
    pause: (value: Promise<void>) => {
      wait = value;
    },
  };
}
async function paymentInput(
  h: ReturnType<typeof paymentHarness>,
  currency: "USD" | "KHR" = "USD",
) {
  fireEvent.click(
    screen.getByRole("button", { name: "Load accepted Payment methods" }),
  );
  await screen.findByRole("option", { name: "Synthetic accepted cash · CASH" });
  fill(
    "Payer Customer reference",
    financialId(
      financialObject(financialObject(h.sample.data.payment_resource).payment)
        .payer_customer_id,
    ),
  );
  fill("Accepted Payment method", h.method.id);
  fill(/Payment received at/, "2026-09-08T11:00:00.123");
  fill("Payment evidence reference", "Synthetic original receipt evidence");
  fill("Incoming currency", currency);
  fill(
    `Original received amount (${currency})`,
    currency === "USD" ? "1.01" : "4061",
  );
  if (currency === "KHR") fill("Explicit USD accounting amount", "1.01");
}
function reviewedPayment(h: ReturnType<typeof paymentHarness>) {
  const request = h.review.mock.calls[0]?.[0];
  if (!request) throw new Error("Missing explicit Payment review");
  return request;
}
describe("Payment entry and original KHR evidence", () => {
  it("TEST-FE-473 refreshes accepted methods and captures original USD Payment scope, references and local time without submitting", async () => {
    const h = paymentHarness("payments.record");
    render(<FinancialPaymentWorkspace {...h.props} />);
    expect(h.calls).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "View Payments" })).toBeNull();
    await paymentInput(h);
    fill("Payment payer scope", "THIRD_PARTY_IDENTIFIED");
    fill("Identified Invoice reference", ids.invoice);
    fill("Payer intent memo", "Synthetic identified third-party rent");
    fireEvent.click(
      screen.getByRole("button", { name: "Review incoming Payment" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const request = reviewedPayment(h),
      captured = captureFinancialRequest(request);
    expect(request.operation).toBe("paymentRecord");
    expect(captured.wireBody).toContain('"minor_units":101');
    expect(captured.wireBody).toContain(
      '"received_at":"2026-09-08T11:00:00.123+07:00"',
    );
    expect(captured.wireBody).toContain(
      '"payment_scope_kind":"THIRD_PARTY_IDENTIFIED"',
    );
    expect(h.calls).toHaveLength(2);
    expect(
      h.calls.every(
        (c) => c.method === "GET" && c.url.includes("payment-methods"),
      ),
    ).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it("TEST-FE-474 keeps valid actual channel evidence distinct from the provisional payable KHR", async () => {
    const h = paymentHarness("payments.record");
    render(<FinancialPaymentWorkspace {...h.props} />);
    await paymentInput(h, "KHR");
    fill("Original received amount (KHR)", "900");
    fireEvent.click(
      screen.getByLabelText("Include actual channel confirmation evidence"),
    );
    fill(/Channel confirmed at/, "2026-09-08T11:00:00.124");
    fill("Actual channel KHR amount", "900");
    fill("Actual channel USD value", "1.01");
    fill("Channel transaction reference", "Synthetic-channel-001");
    fireEvent.click(
      screen.getByRole("button", { name: "Review incoming Payment" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const body = financialObject(reviewedPayment(h).body);
    expect(body.amount).toEqual({ currency: "KHR", minor_units: 900n });
    expect(body.usd_accounting_amount).toEqual({
      currency: "USD",
      minor_units: 101n,
    });
    expect(financialObject(body.channel_evidence)).toMatchObject({
      actual_amount_minor: 900n,
      actual_usd_value_cents: 101n,
      transaction_reference: "Synthetic-channel-001",
    });
    const region = screen.getByRole("region", {
      name: "Provisional KHR preview",
    });
    expect(value(region, "Provisional payable KHR")).toBe("KHR 4,061");
    expect(
      h.calls
        .filter((c) => c.method === "POST")
        .every((c) => c.url.endsWith("/khr-preview")),
    ).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it.each([
    { outage: false, fallback: true, grant: true },
    { outage: true, fallback: true, grant: false },
    { outage: true, fallback: false, grant: true },
  ])(
    "TEST-FE-475 exposes no manual inputs without both approved outage and permission $outage/$fallback/$grant",
    async ({ outage, fallback, grant }) => {
      const h = paymentHarness("payments.record");
      h.outage(outage);
      h.fallback(fallback);
      h.props.capabilities["exchange_rates.manage"] = grant;
      render(<FinancialPaymentWorkspace {...h.props} />);
      await paymentInput(h, "KHR");
      fireEvent.click(
        screen.getByRole("button", { name: "Load provisional KHR preview" }),
      );
      expect(
        await screen.findByRole("region", { name: "Provisional KHR preview" }),
      ).toBeVisible();
      expect(
        screen.queryByLabelText("Use authorized manual fallback"),
      ).toBeNull();
      expect(
        screen.queryByLabelText("Manual reference KHR per USD"),
      ).toBeNull();
      expect(h.review).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-476 rechecks the approved-source outage and preserves explicit manual evidence at confirmation", async () => {
    const h = paymentHarness("payments.record");
    h.outage();
    h.props.capabilities["exchange_rates.manage"] = true;
    render(<FinancialPaymentWorkspace {...h.props} />);
    await paymentInput(h, "KHR");
    fireEvent.click(
      screen.getByRole("button", { name: "Load provisional KHR preview" }),
    );
    fireEvent.click(
      await screen.findByLabelText("Use authorized manual fallback"),
    );
    fill("Manual reference KHR per USD", "4000.000000");
    fill("Manual source reference", "Synthetic approved equivalent source");
    fill(/Manual reference applicable at/, "2026-09-08T10:00:00.123");
    fill("Manual fallback reason", "Synthetic automatic-source outage");
    fireEvent.click(
      screen.getByRole("button", { name: "Review incoming Payment" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    expect(h.calls.filter((c) => c.url.endsWith("/khr-preview"))).toHaveLength(
      3,
    );
    const captured = captureFinancialRequest(reviewedPayment(h));
    expect(captured.wireBody).toContain(
      '"manual_reference":{"reference_rate_khr_per_usd":"4000.000000"',
    );
    expect(captured.wireBody).toContain(
      '"applicable_at":"2026-09-08T10:00:00.123+07:00"',
    );
    expect(
      screen.getByRole("region", { name: "Provisional KHR preview" }),
    ).toHaveTextContent("ABA_EQUIVALENT_MANUAL");
  });
  it("TEST-FE-477 blocks a Payment when its selected method is no longer accepted on fresh review", async () => {
    const h = paymentHarness("payments.record");
    render(<FinancialPaymentWorkspace {...h.props} />);
    await paymentInput(h);
    h.accepted(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Review incoming Payment" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "no longer accepted",
    );
    expect(h.review).not.toHaveBeenCalled();
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
  });
  it("TEST-FE-478 discards a delayed preview after the USD accounting amount changes", async () => {
    const h = paymentHarness("payments.record");
    render(<FinancialPaymentWorkspace {...h.props} />);
    await paymentInput(h, "KHR");
    let release!: () => void;
    h.pause(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load provisional KHR preview" }),
    );
    await waitFor(() => {
      expect(h.calls).toHaveLength(2);
    });
    fill("Explicit USD accounting amount", "2.01");
    expect(h.calls[1]?.signal?.aborted).toBe(true);
    await act(async () => {
      release();
      await Promise.resolve();
    });
    expect(
      screen.queryByRole("region", { name: "Provisional KHR preview" }),
    ).toBeNull();
    expect(h.review).not.toHaveBeenCalled();
  });
  it("TEST-FE-479 reads original Payment facts without method-discovery, Customer permission or command recovery", async () => {
    const h = paymentHarness("payments.read");
    h.props.commands.ready = false;
    render(<FinancialPaymentWorkspace {...h.props} />);
    fireEvent.click(screen.getByRole("button", { name: "Load Payment list" }));
    const table = await screen.findByRole("table", {
      name: "Original Payment list page",
    });
    fireEvent.click(within(table).getByRole("button"));
    const region = await screen.findByRole("region", {
      name: "Selected Payment record",
    });
    expect(region).not.toHaveTextContent("Unavailable");
    expect(
      h.calls.every(
        (c) =>
          c.method === "GET" &&
          c.url.includes("/payments") &&
          !c.url.includes("/payment-methods"),
      ),
    ).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
    expect(h.review).not.toHaveBeenCalled();
  });
});

function allocationSample(kind?: "INVOICE" | "LATE_PAYMENT_CHARGE") {
  return selected(
    (s) =>
      s.request.purpose === "allocation" &&
      (kind ? s.request.target_kind === kind : !s.request.target_kind),
  );
}
function allocationInput(sample: FinancialActionFixture) {
  fill("Source Payment reference", sample.request.source_id);
}
function allocationProposal(sample: FinancialActionFixture): FinancialObject {
  const payment = financialObject(
      financialObject(sample.data.payment_resource).payment,
    ),
    target = financialObject(sample.data.target);
  if (!Array.isArray(sample.data.items) || !sample.data.items[0])
    throw new Error("Missing synthetic proposal line");
  const line = financialObject(sample.data.items[0]);
  return {
    payment_id: sample.request.source_id,
    property_id: sample.propertyId,
    proposal_batch_id: ids.key,
    generated_at: "2026-09-08T11:00:00+07:00",
    available_usd_cents: financialInteger(
      financialObject(financialObject(sample.data.payment_resource).position)
        .available_usd_cents,
    ),
    policy: "DUE_ISSUED_NUMBER_ID/RENT_SERVICE_SOURCE_ORDER",
    continuation_status: "COMPLETE",
    continuation: "CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL",
    designation_reference: null,
    payment_scope: creditFixtureText(payment.payment_scope_kind),
    unallocated_after_usd_cents:
      BigInt(
        financialInteger(
          financialObject(
            financialObject(sample.data.payment_resource).position,
          ).available_usd_cents,
        ),
      ) - 101n,
    targets: [
      {
        invoice_id: financialId(target.id),
        invoice_number: creditFixtureText(target.invoice_number),
        version: 1,
        target_customer_id: financialId(target.customer_id),
        due_date: creditFixtureText(target.due_date),
        issued_at: creditFixtureText(target.issued_at),
        sequence: 1,
        amount_usd_cents: 101,
        details: [
          {
            invoice_line_id: financialId(line.id),
            category: creditFixtureText(financialObject(line.data).category),
            amount_usd_cents: 101,
            outstanding_usd_cents: financialInteger(
              financialObject(line.data).outstanding_usd_cents,
            ),
            attribution_basis: "RENT_FIRST_PROPOSAL",
          },
        ],
      },
    ],
  };
}
describe("Allocation and original Receipt staff forms", () => {
  it("TEST-FE-480 prepares only the refreshed server FIFO proposal under the Allocation grant", async () => {
    const invoiceSample = allocationSample("INVOICE"),
      proposal = allocationProposal(invoiceSample),
      sample: FinancialActionFixture = {
        ...invoiceSample,
        request: {
          operation: "financialActionContext",
          purpose: "allocation",
          source_id: invoiceSample.request.source_id,
        },
        data: {
          ...invoiceSample.data,
          requested_target_kind: null,
          requested_target_id: null,
          target: null,
          items: [],
          item_count: 0,
        },
      },
      h = creditHarness(sample, "payments.allocate");
    h.reply(() => proposal);
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    allocationInput(sample);
    fireEvent.click(
      screen.getByRole("button", { name: "Load Payment Allocation proposal" }),
    );
    expect(
      await screen.findByRole("region", {
        name: "Payment Allocation proposal",
      }),
    ).toBeVisible();
    expect(h.review).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected financial action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const request = reviewedCredit(h);
    expect(request.operation).toBe("allocationPost");
    expect(
      stringifyFinancialJson(
        financialObject(financialObject(request.body).intent),
      ),
    ).toBe(stringifyFinancialJson({ mode: "PROPOSAL", proposal }));
    expect(h.calls).toHaveLength(4);
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it("TEST-FE-481 reloads designated Invoice lines and captures their exact Payment Allocation attribution", async () => {
    const sample = allocationSample("INVOICE"),
      h = creditHarness(sample, "payments.allocate");
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    allocationInput(sample);
    fill("Allocation attribution", "DESIGNATED");
    fill("Allocation target reference", financialId(sample.request.target_id));
    fill(
      "Allocation designation reference",
      "Synthetic explicit Invoice instruction",
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load complete original and current context",
      }),
    );
    fireEvent.change(await screen.findByLabelText(/Allocation USD for line/), {
      target: { value: "1.23" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected financial action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const request = reviewedCredit(h);
    expect(request.operation).toBe("allocationPost");
    expect(financialObject(financialObject(request.body).intent)).toMatchObject(
      {
        mode: "DESIGNATED",
        designation_reference: "Synthetic explicit Invoice instruction",
        targets: [
          { invoice_id: sample.request.target_id, amount_usd_cents: 123n },
        ],
      },
    );
    expect(h.calls).toHaveLength(2);
    expect(captureFinancialRequest(request).wireBody).toContain(
      '"amount_usd_cents":123',
    );
  });
  it.each(["DIRECT_CHARGE", "DESIGNATED"] as const)(
    "TEST-FE-482 preserves the separate Charge target with $0 Allocation intent",
    async (basis) => {
      const sample = allocationSample("LATE_PAYMENT_CHARGE"),
        h = creditHarness(sample, "payments.allocate");
      render(<FinancialAllocationReceiptWorkspace {...h.props} />);
      allocationInput(sample);
      fill("Allocation attribution", basis);
      if (basis === "DESIGNATED") {
        fill("Designated Allocation target", "LATE_PAYMENT_CHARGE");
        fill(
          "Allocation designation reference",
          "Synthetic Charge instruction",
        );
      }
      fill(
        "Allocation target reference",
        financialId(sample.request.target_id),
      );
      fill("Separate Charge Allocation amount (USD)", "1.01");
      fireEvent.click(
        screen.getByRole("button", {
          name: "Review selected financial action",
        }),
      );
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledOnce();
      });
      const request = reviewedCredit(h),
        body = captureFinancialRequest(request).wireBody;
      expect(body).toContain('"amount_usd_cents":101');
      expect(body).toContain(
        `"late_payment_charge_id":"${financialId(sample.request.target_id)}"`,
      );
      expect(body).not.toContain("invoice_id");
      expect(financialObject(financialObject(request.body).intent).mode).toBe(
        basis,
      );
    },
  );
  it.each([false, true])(
    "TEST-FE-483 loads the exact original Allocation and respects an existing linked reversal %s",
    async (reversed) => {
      const sample = selected(
          (s) =>
            s.request.purpose === "allocation_reversal" &&
            (financialObject(s.data.context).reversal !== null) === reversed,
        ),
        h = creditHarness(sample, "payments.allocations.reverse");
      render(<FinancialAllocationReceiptWorkspace {...h.props} />);
      fill("Original Allocation reference", sample.request.source_id);
      fill(
        "Allocation, reversal or reprint reason",
        "Correct this selected original Allocation",
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Load complete original and current context",
        }),
      );
      expect(
        await screen.findByRole("region", { name: "Original Allocation" }),
      ).toBeVisible();
      fireEvent.click(
        screen.getByRole("button", {
          name: "Review selected financial action",
        }),
      );
      if (reversed) {
        expect(await screen.findByRole("alert")).toHaveTextContent(
          "already has a linked reversal",
        );
        expect(h.review).not.toHaveBeenCalled();
      } else {
        await waitFor(() => {
          expect(h.review).toHaveBeenCalledOnce();
        });
        expect(reviewedCredit(h).operation).toBe("allocationReverse");
        expect(captureFinancialRequest(reviewedCredit(h)).target.id).toBe(
          sample.request.source_id,
        );
      }
      expect(screen.queryByLabelText("Allocation target reference")).toBeNull();
      expect(h.calls.every((c) => c.method === "GET")).toBe(true);
    },
  );
  it.each(["RECEIVED", "REVERSED"] as const)(
    "TEST-FE-484 prepares a reasoned reprint of the same original Receipt when its Payment is %s",
    async (status) => {
      const sample = selected(
          (s) =>
            s.request.purpose === "receipt_reprint" &&
            financialObject(financialObject(s.data.payment_resource).payment)
              .status === status,
        ),
        h = creditHarness(sample, "receipts.reprint"),
        receipt = financialObject(financialObject(sample.data.context).receipt);
      render(<FinancialAllocationReceiptWorkspace {...h.props} />);
      fill("Original Receipt reference", sample.request.source_id);
      fill(
        "Allocation, reversal or reprint reason",
        "Synthetic original Receipt copy",
      );
      fill("Optional Receipt delivery reference", "Synthetic desk collection");
      fireEvent.click(
        screen.getByRole("button", {
          name: "Review selected financial action",
        }),
      );
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledOnce();
      });
      const request = reviewedCredit(h);
      expect(request.operation).toBe("receiptReprint");
      expect(captureFinancialRequest(request).target.id).toBe(receipt.id);
      expect(captureFinancialRequest(request).wireBody).toContain(
        '"delivery_reference":"Synthetic desk collection"',
      );
      expect(
        screen.queryByRole("button", { name: /Print original Receipt/ }),
      ).toBeNull();
      const region = screen.getByRole("region", {
        name: "Original Receipt identity",
      });
      expect(value(region, "Original payer name")).toBe(
        financialObject(receipt.identity_snapshot).payer_legal_name,
      );
      expect(h.recovery.submit).not.toHaveBeenCalled();
    },
  );
});

function rawAllocation(sample: FinancialActionFixture): FinancialObject {
  const context = financialObject(sample.data.context),
    original = financialObject(context.allocation);
  if (!Array.isArray(sample.data.items))
    throw new Error("Missing synthetic Allocation details");
  return {
    allocation: {
      ...original,
      invoice_id:
        original.target_kind === "INVOICE"
          ? financialId(original.target_id)
          : null,
      late_payment_charge_id:
        original.target_kind === "LATE_PAYMENT_CHARGE"
          ? financialId(original.target_id)
          : null,
      reversal: context.reversal ?? null,
      proposal_trace: null,
    },
    details: sample.data.items.map((value) => {
      const line = financialObject(value),
        d = financialObject(line.data);
      return {
        id: financialId(line.id),
        detail_sequence: financialInteger(line.sequence),
        invoice_line_id:
          d.target_kind === "INVOICE_LINE" ? financialId(d.target_id) : null,
        late_payment_charge_id:
          d.target_kind === "LATE_PAYMENT_CHARGE"
            ? financialId(d.target_id)
            : null,
        invoice_line_category_snapshot: d.category ?? null,
        proposed_amount_usd_cents: d.proposed_amount_usd_cents ?? null,
        posted_amount_usd_cents: financialInteger(d.posted_amount_usd_cents),
        attribution_basis: creditFixtureText(d.attribution_basis),
      };
    }),
  };
}
function receiptReadResource(sample: FinancialActionFixture): FinancialObject {
  const paymentResource = financialObject(sample.data.payment_resource),
    payment = financialObject(paymentResource.payment),
    position = financialObject(paymentResource.position),
    dispositions = financialObject(position.dispositions),
    receipt = financialObject(financialObject(sample.data.context).receipt);
  return {
    ...paymentResource,
    receipt,
    financial_position: {
      status: creditFixtureText(payment.status),
      allocated_usd_cents: financialInteger(dispositions.allocation_usd_cents),
      deposit_directed_usd_cents: financialInteger(
        dispositions.deposit_usd_cents,
      ),
      available_usd_cents: financialInteger(position.available_usd_cents),
    },
    reprints: {
      items: [
        {
          id: ids.event,
          receipt_id: financialId(receipt.id),
          reprinted_at: "2026-09-08T12:00:00+07:00",
          reprinted_by: sample.actorId,
          reason: "Synthetic original copy history",
          delivery_reference: "Synthetic desk",
        },
      ],
      page: { limit: 50, next_cursor: null },
    },
  };
}
function scopedReadFetcher(
  sample: FinancialActionFixture,
  data: FinancialObject,
  paged = false,
): typeof fetch {
  return (_url, init) => {
    const requestId = new Headers(init?.headers).get("X-Request-ID");
    return Promise.resolve(
      new Response(
        stringifyFinancialJson({
          data,
          ...(paged ? { page: { limit: 50, next_cursor: null } } : {}),
          meta: {
            actor_id: sample.actorId,
            property_id: sample.propertyId,
            request_id: requestId,
          },
        }),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId ?? "",
          },
        },
      ),
    );
  };
}
describe("finite original Allocation and Receipt reads", () => {
  it("TEST-FE-485 displays original selected Allocation detail without inventing Charge category or proposal amounts", async () => {
    const sample = selected(
        (s) =>
          s.request.purpose === "allocation_reversal" &&
          financialObject(s.data.target).kind === "LATE_PAYMENT_CHARGE",
      ),
      h = creditHarness(sample, "payments.read"),
      raw = rawAllocation(sample),
      original = financialObject(raw.allocation);
    h.props.services.transport = createFinancialTransport(
      scopedReadFetcher(sample, raw, true),
    );
    h.props.commands.ready = false;
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    fill("Source Payment reference", financialId(original.payment_id));
    fill("Optional selected Allocation reference", sample.request.source_id);
    fireEvent.click(
      screen.getByRole("button", { name: "Load original history page" }),
    );
    const region = await screen.findByRole("region", {
      name: "Original Allocation history page",
    });
    expect(region).not.toHaveTextContent("Unavailable");
    const table = within(region).getByRole("table", {
      name: "Original Allocation detail page",
    });
    expect(table).toHaveTextContent("Separate Charge");
    expect(table).toHaveTextContent("Not recorded");
    expect(h.review).not.toHaveBeenCalled();
  });
  it.each([false, true])(
    "TEST-FE-486 reads the original Receipt with immutable identity and paged reprint evidence, Payment lookup %s",
    async (byPayment) => {
      const sample = selected((s) => s.request.purpose === "receipt_reprint"),
        h = creditHarness(sample, "receipts.read"),
        data = receiptReadResource(sample);
      h.props.services.transport = createFinancialTransport(
        scopedReadFetcher(sample, data),
      );
      h.props.commands.ready = false;
      render(<FinancialAllocationReceiptWorkspace {...h.props} />);
      fill("Receipt lookup basis", byPayment ? "payment" : "receipt");
      fill(
        byPayment ? "Source Payment reference" : "Original Receipt reference",
        byPayment
          ? financialId(financialObject(data.payment).id)
          : sample.request.source_id,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Load original history page" }),
      );
      const region = await screen.findByRole("region", {
        name: "Original Receipt record",
      });
      expect(region).not.toHaveTextContent("Unavailable");
      expect(
        within(region).getByRole("table", {
          name: "Original Receipt reprint history page",
        }),
      ).toHaveTextContent("Synthetic original copy history");
      expect(
        screen.queryByRole("button", { name: "Record Receipt reprint" }),
      ).toBeNull();
      expect(h.review).not.toHaveBeenCalled();
    },
  );
});
function reversalHarness(dependencies = 0) {
  const sample = creditSample("credit_recognition"),
    h = creditHarness(sample, "payments.reverse"),
    resource = structuredClone(financialObject(sample.data.payment_resource)),
    payment = financialObject(resource.payment),
    paymentId = financialId(payment.id);
  const calls: {
    url: string;
    method: string;
    signal: AbortSignal | null | undefined;
  }[] = [];
  const items: FinancialObject[] = Array.from(
    { length: dependencies },
    (_, i) => {
      const id = `60000000-0000-4000-8000-${(i + 1).toString().padStart(12, "0")}`;
      return {
        ordinal: 3,
        kind: "CREDIT",
        id,
        data: {
          source_kind: "PAYMENT",
          source_id: paymentId,
          target_kind: "CREDIT",
          target_id: id,
          amount_usd_cents: 1,
          occurred_at: "2026-09-08T11:00:00+07:00",
        },
      };
    },
  );
  const revision = "a".repeat(64),
    position = financialObject(resource.position);
  financialObject(position.dispositions).credit_usd_cents = dependencies;
  position.available_usd_cents =
    BigInt(financialInteger(position.original_usd_cents)) -
    BigInt(dependencies);
  const results: FinancialObject[] = [
    {
      ordinal: 1,
      kind: "INVOICE",
      id: ids.invoice,
      data: {
        invoice_number: "Synthetic Invoice",
        status: "UNPAID",
        outstanding_usd_cents: 101,
      },
    },
    {
      ordinal: 2,
      kind: "LATE_PAYMENT_CHARGE",
      id: ids.other,
      data: {
        source_invoice_id: ids.invoice,
        original_usd_cents: 101,
        reversed: false,
        adjusted_obligation_usd_cents: 100,
        remaining_balance_usd_cents: 100,
      },
    },
    {
      ordinal: 3,
      kind: "CREDIT",
      id: ids.credit,
      data: {
        recognized_usd_cents: 101,
        applied_usd_cents: 0,
        refunded_usd_cents: 0,
        reversed_usd_cents: 101,
        available_usd_cents: 0,
      },
    },
    {
      ordinal: 4,
      kind: "DEPOSIT",
      id: ids.receipt,
      data: {
        deposit_type: "SECURITY",
        held_usd_cents: 0,
        received_usd_cents: 101,
        disposed_usd_cents: 101,
        refunded_usd_cents: 0,
      },
    },
  ];
  const fetcher: typeof fetch = (url, init) => {
    if (typeof url !== "string")
      throw new Error("Missing synthetic reversal URL");
    calls.push({ url, method: init?.method ?? "", signal: init?.signal });
    const u = new URL(url, "https://synthetic.invalid"),
      result = u.searchParams.get("view") === "result",
      rows = result ? results : items,
      after = u.searchParams.get("cursor"),
      offset = after
        ? rows.findIndex((r) => r.id === after.split(":")[2]) + 1
        : 0,
      batch = rows.slice(offset, offset + 100),
      last = batch.at(-1);
    const selected = structuredClone(resource);
    if (result) {
      financialObject(selected.payment).status = "REVERSED";
      financialObject(selected.position).available_usd_cents = 0;
    }
    const next =
        offset + batch.length < rows.length && last
          ? `${revision}:${financialInteger(last.ordinal).toString()}:${financialId(last.id)}`
          : null,
      requestId = new Headers(init?.headers).get("X-Request-ID");
    return Promise.resolve(
      new Response(
        stringifyFinancialJson({
          data: {
            payment_resource: selected,
            view: result ? "result" : "impact",
            revision,
            items: batch,
          },
          page: { limit: 100, next_cursor: next },
          meta: {
            actor_id: sample.actorId,
            property_id: sample.propertyId,
            request_id: requestId,
          },
        }),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId ?? "",
          },
        },
      ),
    );
  };
  h.props.services.references = createFinancialReferenceClient(fetcher);
  return { ...h, calls, paymentId };
}
describe("explicit Payment reversal with complete related evidence", () => {
  it("TEST-FE-487 reviews the original Payment only after a complete empty impact and sends no reversal", async () => {
    const h = reversalHarness();
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    fill("Source Payment reference", h.paymentId);
    fill(
      "Allocation, reversal or reprint reason",
      "Synthetic original Payment correction",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected financial action" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const request = reviewedCredit(h);
    expect(request.operation).toBe("paymentReverse");
    expect(captureFinancialRequest(request).wireBody).toContain(
      '"expected_status":"RECEIVED"',
    );
    expect(
      screen.getByRole("region", { name: "Complete Payment reversal impact" }),
    ).toHaveTextContent("No active downstream dependencies");
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it("TEST-FE-488 loads all 101 dependency records before display and blocks reversal until they are explicitly resolved", async () => {
    const h = reversalHarness(101);
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    fill("Source Payment reference", h.paymentId);
    fill(
      "Allocation, reversal or reprint reason",
      "Synthetic original correction",
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load complete original and current context",
      }),
    );
    // 101 records render slowly on a busy machine: this test waits longer than the usual 15
    // seconds, still well inside the 60-second test limit (V1-061 Fix 5).
    const slow = { timeout: 45_000 };
    const region = await screen.findByRole(
      "region",
      { name: "Complete Payment reversal impact" },
      slow,
    );
    expect(region).toHaveTextContent("101 related dependency records loaded");
    expect(h.calls).toHaveLength(2);
    expect(within(region).getAllByRole("row")).toHaveLength(51);
    fireEvent.click(
      screen.getByRole("button", { name: "Next reversal records" }),
    );
    // Wait for the second page to commit before paging again: under load the next click can
    // otherwise reach the button before React has finished the first page change.
    await waitFor(() => {
      expect(region).toHaveTextContent("60000000-0000-4000-8000-000000000051");
    }, slow);
    fireEvent.click(
      screen.getByRole("button", { name: "Next reversal records" }),
    );
    await waitFor(() => {
      expect(within(region).getAllByRole("row")).toHaveLength(2);
    }, slow);
    expect(region).toHaveTextContent("60000000-0000-4000-8000-000000000101");
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected financial action" }),
    );
    expect(await screen.findByRole("alert", {}, slow)).toHaveTextContent(
      "Resolve the active linked",
    );
    expect(h.calls).toHaveLength(4);
    expect(h.review).not.toHaveBeenCalled();
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it("TEST-FE-489 displays recomputed Invoice, Charge, Credit and Deposit result categories separately", async () => {
    const h = reversalHarness();
    render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    fill("Source Payment reference", h.paymentId);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load complete original and current context",
      }),
    );
    await screen.findByRole("region", {
      name: "Complete Payment reversal impact",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Load complete reversal result" }),
    );
    const region = await screen.findByRole("region", {
      name: "Complete Payment reversal result",
    });
    expect(region).toHaveTextContent("4 related balance records loaded");
    expect(region).toHaveTextContent("Adjusted Charge USD");
    expect(region).toHaveTextContent("Reversed Credit USD");
    expect(region).toHaveTextContent("Disposed Deposit USD");
    expect(region).not.toHaveTextContent("Unavailable");
    expect(h.review).not.toHaveBeenCalled();
  });
});

function confirmedReprint(
  sample: FinancialActionFixture,
): ConfirmedFinancialAction {
  const receipt = financialObject(financialObject(sample.data.context).receipt);
  return {
    operation: "receiptReprint",
    target: { id: sample.request.source_id },
    wireBody: stringifyFinancialJson({ reason: "Synthetic confirmed copy" }),
    reply: {
      propertyId: sample.propertyId,
      requestId: "synthetic-confirmed-reprint",
      data: {
        receipt_id: financialId(receipt.id),
        receipt_number: creditFixtureText(receipt.receipt_number),
        reprint: {
          id: ids.event,
          receipt_id: financialId(receipt.id),
          reprinted_at: "2026-09-08T12:00:00+07:00",
          reprinted_by: sample.actorId,
          reason: "Synthetic confirmed copy",
          delivery_reference: null,
        },
      },
    },
  };
}
describe("printing only a confirmed original Receipt copy", () => {
  it.each(["RECEIVED", "REVERSED"] as const)(
    "TEST-FE-492 fetches original identity after confirmed reprint and requires an explicit print click for %s Payment",
    async (status) => {
      const sample = selected(
          (s) =>
            s.request.purpose === "receipt_reprint" &&
            financialObject(financialObject(s.data.payment_resource).payment)
              .status === status,
        ),
        h = creditHarness(sample, "receipts.reprint"),
        confirmed = confirmedReprint(sample),
        print = vi.spyOn(window, "print").mockImplementation(() => undefined);
      try {
        render(
          <FinancialCurrentAfterConfirmation
            {...h.props}
            confirmed={confirmed}
          />,
        );
        const copy = await screen.findByLabelText(
          "Confirmed original Receipt copy",
        );
        expect(copy).toHaveTextContent(
          creditFixtureText(
            financialObject(
              financialObject(financialObject(sample.data.context).receipt)
                .identity_snapshot,
            ).payer_legal_name,
          ),
        );
        expect(copy).toHaveTextContent(ids.event);
        expect(print).not.toHaveBeenCalled();
        expect(h.calls).toHaveLength(1);
        expect(h.calls[0]?.url).toContain(
          `/receipts/${sample.request.source_id}/reprint-context`,
        );
        expect(h.calls[0]?.method).toBe("GET");
        fireEvent.click(
          screen.getByRole("button", { name: "Print original Receipt copy" }),
        );
        expect(print).toHaveBeenCalledOnce();
        expect(h.recovery.submit).not.toHaveBeenCalled();
      } finally {
        print.mockRestore();
      }
    },
  );
  it("TEST-FE-493 does not fetch or expose printing after reprint permission is revoked", async () => {
    const sample = selected((s) => s.request.purpose === "receipt_reprint"),
      h = creditHarness(sample, "receipts.read");
    render(
      <FinancialCurrentAfterConfirmation
        {...h.props}
        confirmed={confirmedReprint(sample)}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.calls).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Print original Receipt copy" }),
    ).toBeNull();
  });
  it("TEST-FE-494 aborts a late confirmed-Receipt identity read on unmount and exposes no old print action", async () => {
    const sample = selected((s) => s.request.purpose === "receipt_reprint"),
      h = creditHarness(sample, "receipts.reprint");
    let release!: () => void;
    h.pause(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    const view = render(
      <FinancialCurrentAfterConfirmation
        {...h.props}
        confirmed={confirmedReprint(sample)}
      />,
    );
    await waitFor(() => {
      expect(h.calls).toHaveLength(1);
    });
    view.unmount();
    expect(h.calls[0]?.signal?.aborted).toBe(true);
    await act(async () => {
      release();
      await Promise.resolve();
    });
    expect(
      screen.queryByRole("button", { name: "Print original Receipt copy" }),
    ).toBeNull();
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
});

describe("authorized current facts after confirmed financial actions", () => {
  it("TEST-FE-495 automatically loads the complete reversal result after confirmation without another command", async () => {
    const h = reversalHarness();
    const confirmed: ConfirmedFinancialAction = {
      operation: "paymentReverse",
      target: { id: h.paymentId },
      wireBody: stringifyFinancialJson({
        reason: "Synthetic confirmed reversal",
        expected_status: "RECEIVED",
      }),
      reply: {
        propertyId: h.props.scope.propertyId,
        requestId: "synthetic-confirmed-reversal",
        data: {},
      },
    };
    render(
      <FinancialCurrentAfterConfirmation {...h.props} confirmed={confirmed} />,
    );
    const result = await screen.findByRole("region", {
      name: "Complete Payment reversal result",
    });
    expect(result).toHaveTextContent("4 related balance records loaded");
    expect(result).toHaveTextContent("Adjusted Charge USD");
    expect(result).toHaveTextContent("Reversed Credit USD");
    expect(result).toHaveTextContent("Disposed Deposit USD");
    expect(h.calls).toHaveLength(1);
    expect(h.calls[0]?.url).toContain("view=result");
    expect(h.calls[0]?.method).toBe("GET");
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
  it.each([
    ["allocationPost", "allocation", "payments.allocate"],
    [
      "allocationReverse",
      "allocation_reversal",
      "payments.allocations.reverse",
    ],
    ["creditRecognize", "credit_recognition", "credits.recognize"],
    ["creditReverse", "credit_reversal", "credits.reverse"],
    ["creditApply", "credit_application", "credits.apply"],
    [
      "creditApplicationReverse",
      "credit_application_reversal",
      "credits.applications.reverse",
    ],
    ["refundReturn", "refund_return", "refunds.correct"],
    [
      "refundReturnReverse",
      "refund_correction_reversal",
      "refunds.corrections.reverse",
    ],
  ] as const)(
    "TEST-FE-496 refreshes the original %s source under its own action grant only",
    async (operation, purpose, grant) => {
      const sample = selected(
          (s) => s.request.purpose === purpose && !s.request.target_kind,
        ),
        h = creditHarness(sample, grant),
        target: Readonly<Record<string, string>> =
          operation === "refundReturnReverse"
            ? {
                id: financialId(sample.request.refund_id),
                correctionId: sample.request.source_id,
              }
            : { id: sample.request.source_id },
        confirmed: ConfirmedFinancialAction = {
          operation,
          target,
          wireBody: "{}",
          reply: {
            propertyId: sample.propertyId,
            requestId: "synthetic-current-source",
            data: {},
          },
        };
      render(
        <FinancialCurrentAfterConfirmation
          {...h.props}
          confirmed={confirmed}
        />,
      );
      await waitFor(() => {
        expect(
          screen.queryByText("Refreshing authorized related facts…"),
        ).toBeNull();
        expect(screen.queryByRole("alert")).toBeNull();
        expect(
          screen.getByRole("region", {
            name: "Related facts refreshed after confirmation",
          }),
        ).toHaveTextContent("separately fetched facts");
      });
      expect(h.calls.length).toBeGreaterThan(0);
      expect(
        h.calls.every(
          (c) => c.method === "GET" && c.url.includes(sample.request.source_id),
        ),
      ).toBe(true);
      if (operation === "refundReturnReverse")
        expect(h.calls[0]?.url).toContain(
          financialId(sample.request.refund_id),
        );
      expect(h.recovery.submit).not.toHaveBeenCalled();
      expect(h.review).not.toHaveBeenCalled();
    },
  );
  it.each(["missing-read", "wrong-property"] as const)(
    "TEST-FE-497 refuses a post-Payment read with %s",
    async (reason) => {
      const h = paymentHarness(
          reason === "missing-read" ? "payments.record" : "payments.read",
        ),
        confirmed: ConfirmedFinancialAction = {
          operation: "paymentRecord",
          target: {},
          wireBody: "{}",
          reply: {
            propertyId:
              reason === "wrong-property"
                ? ids.other
                : h.props.scope.propertyId,
            requestId: "synthetic-confirmed-payment",
            data: { payment: { id: ids.payment } },
          },
        };
      render(
        <FinancialCurrentAfterConfirmation
          {...h.props}
          confirmed={confirmed}
        />,
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(h.calls).toHaveLength(0);
      expect(
        screen.queryByRole("region", {
          name: "Related facts refreshed after confirmation",
        }),
      ).toBeNull();
    },
  );
});

describe("financial reads after another confirmed action", () => {
  it.each(["Payment", "Credit", "Refund", "Receipt"] as const)(
    "TEST-FE-506 preserves original %s facts but withdraws current positions until a fresh authorized read",
    async (kind) => {
      const sample =
        kind === "Receipt"
          ? selected((s) => s.request.purpose === "receipt_reprint")
          : kind === "Refund"
            ? currentRefund("refund_return")
            : kind === "Credit"
              ? creditSample("credit_reversal")
              : creditSample("credit_recognition");
      const data =
        kind === "Receipt"
          ? receiptReadResource(sample)
          : kind === "Refund"
            ? financialObject(financialObject(sample.data.context).refund)
            : kind === "Credit"
              ? financialObject(financialObject(sample.data.context).credit)
              : financialObject(sample.data.payment_resource);
      const grant =
        kind === "Receipt"
          ? "receipts.read"
          : kind === "Refund"
            ? "refunds.read"
            : kind === "Credit"
              ? "credits.read"
              : "payments.read";
      const h = creditHarness(sample, grant);
      if (kind === "Refund")
        data.corrections = {
          items: [],
          page: { limit: 50, next_cursor: null },
        };
      h.reply(() => data);
      const Component =
        kind === "Receipt"
          ? FinancialAllocationReceiptWorkspace
          : kind === "Refund"
            ? FinancialRefundWorkspace
            : kind === "Credit"
              ? FinancialCreditWorkspace
              : FinancialPaymentWorkspace;
      const view = render(<Component {...h.props} />);
      const input =
        kind === "Receipt" ? "Original Receipt reference" : `${kind} reference`;
      const entity = financialObject(data[kind.toLowerCase()]);
      fill(input, financialId(entity.id));
      const submitRead = () => {
        const form = screen.getByLabelText(input).closest("form");
        if (!form) throw new Error("Synthetic read form missing");
        fireEvent.submit(form);
      };
      submitRead();
      const original =
        kind === "Receipt"
          ? "Original Receipt identity"
          : kind === "Refund"
            ? "Original completed Refund"
            : kind === "Credit"
              ? "Original Credit recognition"
              : "Original payment facts";
      const current =
        kind === "Receipt"
          ? "Current Receipt-linked Payment context"
          : kind === "Refund"
            ? "Current Refund value"
            : kind === "Credit"
              ? "Current Credit position"
              : "Current payment position";
      const region = await screen.findByRole("region", { name: original });
      const facts = region.textContent;
      expect(screen.getByRole("region", { name: current })).toBeVisible();
      const before = h.calls.length;
      view.rerender(
        <Component
          {...h.props}
          commands={{ ...h.props.commands, revision: 1 }}
        />,
      );
      expect(screen.queryByRole("region", { name: current })).toBeNull();
      expect(screen.getByRole("region", { name: original }).textContent).toBe(
        facts,
      );
      expect(
        screen.getByText(/Loaded financial facts are out of date/),
      ).toBeVisible();
      expect(h.calls).toHaveLength(before);
      h.reply(() => {
        throw new Error("Synthetic fresh read unavailable");
      });
      submitRead();
      await screen.findByRole("alert");
      expect(screen.queryByRole("region", { name: current })).toBeNull();
      h.reply(() => data);
      submitRead();
      expect(
        await screen.findByRole("region", { name: current }),
      ).toBeVisible();
      expect(
        screen.queryByText(/Loaded financial facts are out of date/),
      ).toBeNull();
      expect(h.calls.every((c) => c.method === "GET")).toBe(true);
      expect(h.recovery.submit).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-507 shows each proposed Invoice Customer once without duplicate React keys", () => {
    const sample = allocationSample("INVOICE"),
      proposal = allocationProposal(sample);
    const errors = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    try {
      render(<FinancialProposalEvidence value={proposal} />);
      const targets = screen.getAllByRole("region", {
        name: /^Proposed Invoice/,
      });
      for (const target of targets)
        expect(
          within(target).getAllByText("Target Customer reference", {
            selector: "dt",
          }),
        ).toHaveLength(1);
      expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
    } finally {
      errors.mockRestore();
    }
  });
  it("TEST-FE-S11G-003 shows a proposed late-payment charge after its Invoice as a charge", () => {
    const sample = allocationSample("INVOICE"),
      proposal = allocationProposal(sample);
    const invoice = financialObject((proposal.targets as FinancialObject[])[0]);
    const charges = ["a", "b"].map((letter, index) => ({
      late_payment_charge_id: `${letter.repeat(8)}-${letter.repeat(4)}-4${letter.repeat(3)}-8${letter.repeat(3)}-${letter.repeat(12)}`,
      target_customer_id: invoice.target_customer_id,
      source_invoice_id: invoice.invoice_id,
      due_date: invoice.due_date,
      issued_at: invoice.issued_at,
      invoice_number: invoice.invoice_number,
      sequence: index + 2,
      outstanding_usd_cents: 8000,
      amount_usd_cents: 8000,
    }));
    const errors = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    try {
      render(
        <FinancialProposalEvidence
          value={{
            ...proposal,
            policy:
              "DUE_ISSUED_NUMBER_ID_CHARGE_AFTER_INVOICE/RENT_SERVICE_SOURCE_ORDER",
            targets: [invoice, ...charges],
          }}
        />,
      );
      expect(
        screen.getAllByRole("region", { name: /^Proposed Invoice/ }),
      ).toHaveLength(1);
      const shown = screen.getAllByRole("region", {
        name: /^Proposed late-payment charge of Invoice/,
      });
      expect(shown).toHaveLength(2);
      const [first] = shown;
      const [firstCharge] = charges;
      if (!first || !firstCharge) throw new Error("Expected two proposals");
      expect(
        within(first).getByText(firstCharge.late_payment_charge_id),
      ).toBeVisible();
      expect(
        within(first).getByText(invoice.invoice_id as string),
      ).toBeVisible();
      expect(
        within(first).queryByText("Invoice version at proposal"),
      ).toBeNull();
      expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
    } finally {
      errors.mockRestore();
    }
  });
});

describe("original Payment receipt evidence and authorized handoff", () => {
  it.each([false, true])(
    "TEST-FE-509 preserves exact original received and Receipt facts with explicit legacy-null evidence %s",
    (legacy) => {
      const resource = financialObject(
        creditSample("credit_recognition").data.payment_resource,
      );
      render(
        <PaymentEvidence
          resource={{
            ...resource,
            confirmation_evidence: {
              received_at: legacy ? null : "2026-09-01T11:59:00.123456+07:00",
              evidence_reference: legacy
                ? null
                : "Synthetic immutable receipt evidence",
            },
            receipt: {
              id: ids.receipt,
              receipt_number: "RECEIPT-ORIGINAL-SYNTHETIC",
            },
          }}
          showPosition={false}
        />,
      );
      const original = screen.getByRole("region", {
        name: "Original payment facts",
      });
      expect(value(original, "Original received time")).toBe(
        legacy ? "Not recorded" : "2026-09-01 11:59:00.123456+07:00",
      );
      expect(value(original, "Original receipt evidence reference")).toBe(
        legacy ? "Not recorded" : "Synthetic immutable receipt evidence",
      );
      expect(value(original, "Original Receipt number")).toBe(
        "RECEIPT-ORIGINAL-SYNTHETIC",
      );
      expect(value(original, "Original Receipt reference")).toBe(ids.receipt);
      expect(
        screen.queryByRole("region", { name: "Current payment position" }),
      ).toBeNull();
    },
  );
  it.each(["receipts.read", "receipts.reprint", null] as const)(
    "TEST-FE-510 hands off the exact original Receipt under its separate %s grant without posting",
    async (grant) => {
      const sample = selected((s) => s.request.purpose === "receipt_reprint");
      const h = creditHarness(sample, "payments.read");
      const receiptResource = receiptReadResource(sample),
        receipt = financialObject(receiptResource.receipt);
      const paymentResource: FinancialObject = {
        ...financialObject(sample.data.payment_resource),
        receipt: {
          id: financialId(receipt.id),
          receipt_number: creditFixtureText(receipt.receipt_number),
        },
      };
      const grants = Object.fromEntries(
        FINANCIAL_CAPABILITIES.map((c) => [
          c,
          c === "payments.read" || c === grant,
        ]),
      );
      const calls: {
        url: string;
        method: string;
        actor: string | null;
        property: string | null;
      }[] = [];
      const fetcher: typeof fetch = (url, init) => {
        if (typeof url !== "string")
          throw new Error("Expected synthetic Receipt URL");
        const headers = new Headers(init?.headers),
          requestId = headers.get("X-Request-ID");
        calls.push({
          url,
          method: init?.method ?? "",
          actor: headers.get("X-Billing-Actor-ID"),
          property: headers.get("X-Financial-Property-ID"),
        });
        const discovery = url.includes("financial-workspaces"),
          context = url.includes("reprint-context");
        const data = discovery
          ? [
              {
                property_id: sample.propertyId,
                name: "Synthetic Receipt Property",
                timezone: "Asia/Phnom_Penh",
                capabilities: grants,
              },
            ]
          : url.includes("financial-capabilities")
            ? { property_id: sample.propertyId, capabilities: grants }
            : context
              ? sample.data
              : url.includes("/receipts/")
                ? receiptResource
                : paymentResource;
        return Promise.resolve(
          new Response(
            stringifyFinancialJson({
              data,
              ...(discovery || context
                ? { page: { limit: discovery ? 100 : 50, next_cursor: null } }
                : {}),
              meta: {
                request_id: requestId,
                actor_id: sample.actorId,
                ...(discovery ? {} : { property_id: sample.propertyId }),
              },
            }),
            {
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": requestId ?? "",
              },
            },
          ),
        );
      };
      h.props.services.references = createFinancialReferenceClient(fetcher);
      h.props.services.transport = createFinancialTransport(fetcher);
      render(
        <FinancialManagement
          actorId={sample.actorId}
          services={h.props.services}
        />,
      );
      await screen.findByRole("option", { name: "Synthetic Receipt Property" });
      fill("Financial Property", sample.propertyId);
      await screen.findByLabelText("Payment reference");
      fill(
        "Payment reference",
        financialId(financialObject(paymentResource.payment).id),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Load Payment record" }),
      );
      await screen.findByRole("region", { name: "Selected Payment record" });
      const handoff = screen.queryByRole("button", {
        name: "Open original Receipt",
      });
      if (grant === null) {
        expect(handoff).toBeNull();
        expect(calls.some((c) => c.url.includes("/receipts/"))).toBe(false);
      } else {
        if (!handoff) throw new Error("Original Receipt handoff missing");
        expect(handoff).toBeEnabled();
        fireEvent.click(handoff);
        expect(
          await screen.findByLabelText("Original Receipt reference"),
        ).toHaveValue(financialId(receipt.id));
        expect(
          await screen.findByRole("region", {
            name: "Original Receipt identity",
          }),
        ).toBeVisible();
        const receiptCalls = calls.filter((c) => c.url.includes("/receipts/"));
        expect(receiptCalls).toHaveLength(1);
        const receiptCall = receiptCalls[0];
        if (!receiptCall)
          throw new Error("Expected exact original Receipt GET");
        expect(receiptCall.url).toContain(
          `/receipts/${financialId(receipt.id)}${grant === "receipts.reprint" ? "/reprint-context" : ""}`,
        );
        expect(receiptCall.method).toBe("GET");
        expect(receiptCall.actor).toBe(sample.actorId);
        expect(receiptCall.property).toBe(sample.propertyId);
        expect(screen.queryByRole("dialog")).toBeNull();
      }
      expect(calls.every((c) => c.method === "GET")).toBe(true);
      expect(h.recovery.submit).not.toHaveBeenCalled();
      expect(h.recovery.replay).not.toHaveBeenCalled();
    },
  );
});

it.each(["actor", "property", "signal", "aborted", "no-grant"] as const)(
  "TEST-FE-511 refuses a Receipt handoff with %s mismatch before any read or command",
  async (mismatch) => {
    const sample = selected((s) => s.request.purpose === "receipt_reprint"),
      h = creditHarness(sample, "receipts.read");
    const origin = { ...h.props.scope };
    if (mismatch === "actor") origin.actorId = ids.other;
    if (mismatch === "property") origin.propertyId = ids.other;
    if (mismatch === "signal") origin.signal = new AbortController().signal;
    if (mismatch === "aborted") {
      const controller = new AbortController();
      controller.abort();
      origin.signal = controller.signal;
      h.props.scope = origin;
    }
    if (mismatch === "no-grant") h.props.capabilities["receipts.read"] = false;
    render(
      <FinancialAllocationReceiptWorkspace
        {...h.props}
        receiptHandoff={{ scope: origin, receiptId: sample.request.source_id }}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.calls).toHaveLength(0);
    expect(h.review).not.toHaveBeenCalled();
    expect(h.recovery.submit).not.toHaveBeenCalled();
  },
);

describe("retained proposal history and complete amount alignment", () => {
  it("TEST-FE-516 keeps non-null posted proposal balances historical across revision and failed reload", async () => {
    const sample = creditSample("allocation_reversal", "INVOICE"),
      h = creditHarness(sample, "payments.read"),
      raw = rawAllocation(sample),
      allocation = financialObject(raw.allocation),
      proposal = allocationProposal(allocationSample("INVOICE"));
    // Reconstruct a finite original trace from the captured original Allocation facts.
    const target = financialObject(sample.data.target),
      line = financialObject(
        financialObject((sample.data.items as FinancialObject[])[0]).data,
      ),
      posted = BigInt(financialInteger(line.posted_amount_usd_cents)),
      before =
        posted + BigInt(financialInteger(line.current_outstanding_usd_cents));
    proposal.payment_id = financialId(allocation.payment_id);
    proposal.property_id = sample.propertyId;
    proposal.proposal_batch_id = financialId(allocation.proposal_batch_id);
    proposal.generated_at = creditFixtureText(allocation.proposal_generated_at);
    proposal.available_usd_cents = posted;
    proposal.unallocated_after_usd_cents = 0;
    proposal.targets = [
      {
        invoice_id: financialId(target.id),
        invoice_number: creditFixtureText(target.invoice_number),
        version: 1,
        target_customer_id: financialId(target.customer_id),
        due_date: creditFixtureText(target.due_date),
        issued_at: creditFixtureText(target.issued_at),
        sequence: financialInteger(allocation.between_invoice_sequence),
        amount_usd_cents: posted,
        details: [
          {
            invoice_line_id: financialId(line.target_id),
            category: creditFixtureText(line.category),
            amount_usd_cents: posted,
            outstanding_usd_cents: before,
            attribution_basis: creditFixtureText(line.attribution_basis),
          },
        ],
      },
    ];
    allocation.proposal_trace = proposal;
    let unavailable = false;
    const calls: string[] = [];
    const reader = scopedReadFetcher(sample, raw, true);
    h.props.services.transport = createFinancialTransport((url, init) => {
      calls.push(init?.method ?? "");
      if (unavailable)
        return Promise.reject(new Error("Synthetic unavailable refresh"));
      return reader(url, init);
    });
    const view = render(<FinancialAllocationReceiptWorkspace {...h.props} />);
    fill("Source Payment reference", financialId(allocation.payment_id));
    fill("Optional selected Allocation reference", financialId(allocation.id));
    const load = () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Load original history page" }),
      );
    load();
    const region = await screen.findByRole("region", {
      name: "Original Allocation history page",
    });
    const assertHistorical = () => {
      expect(within(region).queryByText("Current outstanding")).toBeNull();
      const header = within(region).getByRole("columnheader", {
        name: "Outstanding at proposal",
      });
      expect(header.closest("table")).toHaveTextContent(financialMoney(before));
      expect(region).toHaveTextContent(financialMoney(posted));
      expect(region).not.toHaveTextContent(
        "Confirmation posts only the displayed batch",
      );
      expect(region).toHaveTextContent("Original recorded proposal");
    };
    assertHistorical();
    const originalProposal = within(region).getByRole("region", {
      name: "Original recorded proposal",
    });
    const originalLines = within(region).getByRole("table", {
      name: "Original Allocation detail page",
    });
    const facts = originalProposal.textContent,
      lines = originalLines.textContent;
    view.rerender(
      <FinancialAllocationReceiptWorkspace
        {...h.props}
        commands={{ ...h.props.commands, revision: 1 }}
      />,
    );
    assertHistorical();
    expect(originalProposal.textContent).toBe(facts);
    expect(originalLines.textContent).toBe(lines);
    expect(
      screen.getByText(/Loaded financial facts are out of date/),
    ).toBeVisible();
    unavailable = true;
    load();
    await screen.findByRole("alert");
    const retained = screen.queryByRole("region", {
      name: "Original Allocation history page",
    });
    // Failed refresh may withdraw the record, but must never revive current labels.
    if (retained) expect(retained).not.toHaveTextContent("Current outstanding");
    expect(screen.queryByText("Current outstanding")).toBeNull();
    unavailable = false;
    load();
    const reloaded = await screen.findByRole("region", {
      name: "Original Allocation history page",
    });
    expect(reloaded).toHaveTextContent("Outstanding at proposal");
    expect(reloaded).not.toHaveTextContent("Current outstanding");
    expect(calls).toEqual(["GET", "GET", "GET"]);
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });

  it.each(["Payment", "Credit", "Refund", "Allocation"] as const)(
    "TEST-FE-517 right-aligns standalone %s amount entry without changing its exact value",
    async (kind) => {
      const sample = allocationSample("INVOICE"),
        grant =
          kind === "Payment"
            ? "payments.record"
            : kind === "Credit"
              ? "credits.recognize"
              : kind === "Refund"
                ? "refunds.create"
                : "payments.allocate",
        h = creditHarness(sample, grant),
        Component =
          kind === "Payment"
            ? FinancialPaymentWorkspace
            : kind === "Credit"
              ? FinancialCreditWorkspace
              : kind === "Refund"
                ? FinancialRefundWorkspace
                : FinancialAllocationReceiptWorkspace;
      const style = document.createElement("style");
      style.textContent = financialStyles;
      document.head.append(style);
      try {
        render(
          <section className="financial-management">
            <Component {...h.props} />
          </section>,
        );
        if (kind === "Allocation")
          fill("Allocation attribution", "DIRECT_CHARGE");
        const label =
          kind === "Payment"
            ? "Original received amount (USD)"
            : kind === "Credit"
              ? "Credit amount (USD)"
              : kind === "Refund"
                ? "Refund amount (USD)"
                : "Separate Charge Allocation amount (USD)";
        const input = await screen.findByLabelText<HTMLInputElement>(label);
        fireEvent.change(input, { target: { value: "123456789012345.67" } });
        expect(input).toHaveValue("123456789012345.67");
        expect(getComputedStyle(input).textAlign).toBe("right");
        expect(h.recovery.submit).not.toHaveBeenCalled();
      } finally {
        style.remove();
      }
    },
  );

  it("TEST-FE-518 right-aligns the proposed-money header alongside its exact cells", () => {
    const sample = creditSample("allocation_reversal", "INVOICE");
    const style = document.createElement("style");
    style.textContent = financialStyles;
    document.head.append(style);
    try {
      render(
        <section className="financial-management">
          <TargetEvidence
            target={sample.data.target}
            items={sample.data.items}
          />
        </section>,
      );
      const header = screen.getByRole("columnheader", {
        name: "Original attribution / proposal",
      });
      expect(getComputedStyle(header).textAlign).toBe("right");
      expect(header.closest("table")).toHaveTextContent("Proposed:");
    } finally {
      style.remove();
    }
  });
});

describe("operation-owned unsent financial drafts", () => {
  it("TEST-FE-529 retains an unsent payout after another Refund operation is acknowledged", async () => {
    const sample = currentRefund("refund_correction_reversal"),
      h = refundProps(sample, "refunds.create"),
      changed = vi.fn();
    h.props.capabilities["refunds.corrections.reverse"] = true;
    render(
      <FinancialRefundWorkspace {...h.props} onDirtyStateChange={changed} />,
    );
    fill("Refund source", "PET_DEPOSIT");
    fill("Source reference", ids.payment);
    fill("Qualifying Pet review reference", ids.event);
    fill("Refund amount (USD)", "123.45");
    fill("Reason", "Synthetic unsent payout");
    fireEvent.click(
      screen.getByRole("button", { name: "Reverse return correction" }),
    );
    fill("Refund reference", sample.request.refund_id ?? "");
    fill("Original return correction reference", sample.request.source_id);
    fill("Evidence reference", "Synthetic correction evidence");
    fill("Reason", "Correct erroneous return evidence");
    reviewRefund();
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const review = h.review.mock.calls[0];
    expect(review?.[0].operation).toBe("refundReturnReverse");
    if (!review?.[1].onRecorded)
      throw new Error("Expected exact acknowledgement");
    act(review[1].onRecorded);
    expect(changed).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Record USD Refund" }));
    expect(screen.getByLabelText("Source reference")).toHaveValue(ids.payment);
    expect(
      screen.getByLabelText("Qualifying Pet review reference"),
    ).toHaveValue(ids.event);
    expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue("123.45");
    expect(h.calls.every((c) => c.method === "GET")).toBe(true);
  });
  it("TEST-FE-530 cancels Refund source loss before resetting references or invalidating", () => {
    const h = refundProps(currentRefund("refund_return"), "refunds.create"),
      discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      render(<FinancialRefundWorkspace {...h.props} />);
      fill("Refund source", "PET_DEPOSIT");
      fill("Source reference", ids.payment);
      fill("Qualifying Pet review reference", ids.event);
      fill("Refund amount (USD)", "123.45");
      fill("Reason", "Synthetic unsent payout");
      const invalidations = vi.mocked(h.props.commands.invalidate).mock.calls
        .length;
      fill("Refund source", "PAYMENT");
      expect(discard).toHaveBeenCalledOnce();
      expect(screen.getByLabelText("Refund source")).toHaveValue("PET_DEPOSIT");
      expect(screen.getByLabelText("Source reference")).toHaveValue(
        ids.payment,
      );
      expect(
        screen.getByLabelText("Qualifying Pet review reference"),
      ).toHaveValue(ids.event);
      expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue(
        "123.45",
      );
      expect(h.props.commands.invalidate).toHaveBeenCalledTimes(invalidations);
      expect(h.calls).toHaveLength(0);
      discard.mockReturnValue(true);
      fill("Refund source", "PAYMENT");
      expect(screen.getByLabelText("Source reference")).toHaveValue("");
      expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue(
        "123.45",
      );
      fill("Refund source", "PET_DEPOSIT");
      expect(
        screen.getByLabelText("Qualifying Pet review reference"),
      ).toHaveValue("");
    } finally {
      discard.mockRestore();
    }
  });
  it("TEST-FE-531 marks a selection-only Payment draft dirty", () => {
    const h = paymentHarness("payments.record"),
      changed = vi.fn();
    render(
      <FinancialPaymentWorkspace {...h.props} onDirtyStateChange={changed} />,
    );
    expect(changed).toHaveBeenLastCalledWith(false);
    fill("Payment payer scope", "THIRD_PARTY_IDENTIFIED");
    expect(screen.getByLabelText("Payment payer scope")).toHaveValue(
      "THIRD_PARTY_IDENTIFIED",
    );
    expect(changed).toHaveBeenLastCalledWith(true);
    expect(h.calls).toHaveLength(0);
  });
  it("TEST-FE-532 retains a later Payment selection after the original review is acknowledged", async () => {
    const h = paymentHarness("payments.record"),
      changed = vi.fn();
    render(
      <FinancialPaymentWorkspace {...h.props} onDirtyStateChange={changed} />,
    );
    await paymentInput(h);
    fireEvent.click(
      screen.getByRole("button", { name: "Review incoming Payment" }),
    );
    await waitFor(() => {
      expect(h.review).toHaveBeenCalledOnce();
    });
    const review = h.review.mock.calls[0];
    expect(review?.[0].body.payment_scope_kind).toBe("NORMAL_CUSTOMER");
    if (!review?.[1].onRecorded)
      throw new Error("Expected exact acknowledgement");
    fill("Payment payer scope", "THIRD_PARTY_IDENTIFIED");
    act(review[1].onRecorded);
    expect(changed).toHaveBeenLastCalledWith(true);
    expect(screen.getByLabelText("Payment payer scope")).toHaveValue(
      "THIRD_PARTY_IDENTIFIED",
    );
    expect(review[0].body.payment_scope_kind).toBe("NORMAL_CUSTOMER");
    expect(h.recovery.submit).not.toHaveBeenCalled();
  });
});

describe("command selections and conditional Payment draft ownership", () => {
  it.each(["channel", "manual"] as const)(
    "TEST-FE-535 retains a later %s choice after acknowledgement of the original Payment",
    async (choice) => {
      const h = paymentHarness("payments.record"),
        changed = vi.fn();
      if (choice === "manual") {
        h.outage();
        h.props.capabilities["exchange_rates.manage"] = true;
      }
      const view = render(
        <FinancialPaymentWorkspace {...h.props} onDirtyStateChange={changed} />,
      );
      await paymentInput(h, "KHR");
      if (choice === "manual") {
        fireEvent.click(
          screen.getByRole("button", { name: "Load provisional KHR preview" }),
        );
        fireEvent.click(
          await screen.findByLabelText("Use authorized manual fallback"),
        );
        fill("Manual reference KHR per USD", "4000.000000");
        fill("Manual source reference", "Synthetic approved equivalent source");
        fill(/Manual reference applicable at/, "2026-09-08T10:00:00.123");
        fill("Manual fallback reason", "Synthetic automatic-source outage");
      }
      fireEvent.click(
        screen.getByRole("button", { name: "Review incoming Payment" }),
      );
      await waitFor(() => {
        expect(h.review).toHaveBeenCalledOnce();
      });
      const review = h.review.mock.calls[0];
      if (!review?.[1].onRecorded)
        throw new Error("Expected original acknowledgement");
      const bytes = captureFinancialRequest(review[0]).wireBody;
      const label =
        choice === "manual"
          ? "Use authorized manual fallback"
          : "Include actual channel confirmation evidence";
      fireEvent.click(screen.getByLabelText(label));
      act(review[1].onRecorded);
      expect(changed).toHaveBeenLastCalledWith(true);
      expect(screen.getByLabelText(label)).toHaveProperty(
        "checked",
        choice === "channel",
      );
      expect(captureFinancialRequest(review[0]).wireBody).toBe(bytes);
      view.rerender(
        <FinancialPaymentWorkspace
          {...h.props}
          commands={{ ...h.props.commands, revision: 1 }}
          onDirtyStateChange={changed}
        />,
      );
      if (choice === "channel")
        expect(screen.getByLabelText(label)).toBeChecked();
      expect(changed).toHaveBeenLastCalledWith(true);
      expect(h.recovery.submit).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-536 retains unsent manual evidence and choices across voluntary mode/currency changes and revisions", async () => {
    const h = paymentHarness("payments.record"),
      changed = vi.fn(),
      discard = vi.spyOn(window, "confirm").mockReturnValue(true);
    h.props.capabilities["payments.read"] = true;
    h.props.capabilities["exchange_rates.manage"] = true;
    h.outage();
    try {
      const view = render(
        <FinancialPaymentWorkspace {...h.props} onDirtyStateChange={changed} />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Record Payment" }));
      await paymentInput(h, "KHR");
      fireEvent.click(
        screen.getByRole("button", { name: "Load provisional KHR preview" }),
      );
      fireEvent.click(
        await screen.findByLabelText("Use authorized manual fallback"),
      );
      fill("Manual source reference", "Synthetic unsent manual evidence");
      fireEvent.click(
        screen.getByLabelText("Include actual channel confirmation evidence"),
      );
      fill("Actual channel USD value", "12.34");
      fireEvent.click(screen.getByRole("button", { name: "View Payments" }));
      fireEvent.click(screen.getByRole("button", { name: "Record Payment" }));
      expect(
        screen.getByLabelText("Use authorized manual fallback"),
      ).toBeChecked();
      expect(
        screen.getByLabelText("Include actual channel confirmation evidence"),
      ).toBeChecked();
      fill("Incoming currency", "USD");
      fill("Incoming currency", "KHR");
      expect(
        screen.getByLabelText("Include actual channel confirmation evidence"),
      ).toBeChecked();
      expect(screen.getByLabelText("Actual channel USD value")).toHaveValue(
        "12.34",
      );
      view.rerender(
        <FinancialPaymentWorkspace
          {...h.props}
          commands={{ ...h.props.commands, revision: 1 }}
          onDirtyStateChange={changed}
        />,
      );
      expect(
        screen.getByLabelText("Use authorized manual fallback"),
      ).toBeChecked();
      expect(changed).toHaveBeenLastCalledWith(true);
      expect(h.review).not.toHaveBeenCalled();
    } finally {
      discard.mockRestore();
    }
  });
  it.each(["Credit", "Allocation"] as const)(
    "TEST-FE-537 tracks selection-only %s attribution",
    (kind) => {
      const sample =
          kind === "Credit"
            ? creditSample("credit_application", "INVOICE")
            : allocationSample("INVOICE"),
        h = creditHarness(
          sample,
          kind === "Credit" ? "credits.apply" : "payments.allocate",
        ),
        changed = vi.fn();
      render(
        kind === "Credit" ? (
          <FinancialCreditWorkspace {...h.props} onDirtyStateChange={changed} />
        ) : (
          <FinancialAllocationReceiptWorkspace
            {...h.props}
            onDirtyStateChange={changed}
          />
        ),
      );
      expect(changed).toHaveBeenLastCalledWith(false);
      fill(kind + " attribution", "DESIGNATED");
      expect(changed).toHaveBeenLastCalledWith(true);
      expect(h.calls).toHaveLength(0);
    },
  );
});

it.each(["Credit", "Allocation"] as const)(
  "TEST-FE-539 cancels %s target changes before clearing a pending target reference",
  (kind) => {
    const sample =
        kind === "Credit"
          ? creditSample("credit_application", "INVOICE")
          : allocationSample("INVOICE"),
      h = creditHarness(
        sample,
        kind === "Credit" ? "credits.apply" : "payments.allocate",
      ),
      discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      render(
        kind === "Credit" ? (
          <FinancialCreditWorkspace {...h.props} />
        ) : (
          <FinancialAllocationReceiptWorkspace {...h.props} />
        ),
      );
      if (kind === "Allocation") fill("Allocation attribution", "DESIGNATED");
      const reference =
          kind === "Credit"
            ? "Target reference"
            : "Allocation target reference",
        selection =
          kind === "Credit" ? "Credit target" : "Designated Allocation target";
      fill(reference, ids.invoice);
      const before = vi.mocked(h.props.commands.invalidate).mock.calls.length;
      fill(selection, "LATE_PAYMENT_CHARGE");
      expect(discard).toHaveBeenCalledOnce();
      expect(screen.getByLabelText(reference)).toHaveValue(ids.invoice);
      expect(screen.getByLabelText(selection)).toHaveValue("INVOICE");
      expect(h.props.commands.invalidate).toHaveBeenCalledTimes(before);
      expect(h.calls).toHaveLength(0);
      discard.mockReturnValue(true);
      fill(selection, "LATE_PAYMENT_CHARGE");
      expect(screen.getByLabelText(reference)).toHaveValue("");
    } finally {
      discard.mockRestore();
    }
  },
);

describe("immutable command results and separately current positions", () => {
  it.each([
    "creditRecognize",
    "creditReverse",
    "creditApply",
    "creditApplicationReverse",
    "refundCreate",
    "refundReturn",
    "refundReturnReverse",
  ] as const)(
    "TEST-FE-543 identifies %s balances as the original confirmation without changing saved values",
    (operation) => {
      const data = fixture(operation).data;
      const before = stringifyFinancialJson(data);
      render(
        <FinancialOutcomeEvidence
          operation={operation}
          reply={{ data, requestId: ids.key, propertyId: ids.property }}
        />,
      );
      const result = screen.getByRole("region", {
        name: "Confirmed financial result",
      });
      const refund = operation.startsWith("refund");
      const position = within(result).getByRole("region", {
        name: refund
          ? "Refund value at original confirmation"
          : "Credit position at original confirmation",
      });
      expect(position).toHaveTextContent(
        operation === "refundReturn" ? "USD 0.00" : "USD 1.00",
      );
      if (refund)
        expect(position).toHaveTextContent(
          "Net Refund USD at original confirmation",
        );
      expect(within(result).queryByText(/^Current /)).toBeNull();
      expect(
        within(result).queryByRole("region", { name: /^Current / }),
      ).toBeNull();
      expect(stringifyFinancialJson(data)).toBe(before);
      if (
        operation === "creditApply" ||
        operation === "creditApplicationReverse"
      )
        expect(result).toHaveTextContent(
          "Selected target balance at confirmation",
        );
    },
  );

  it.each(["creditGet", "creditApplication", "refundGet"] as const)(
    "TEST-FE-544 retains Current labels for a separately loaded %s and hides invalidated positions",
    (operation) => {
      const data = fixture(operation).data;
      const Component =
        operation === "creditGet"
          ? CreditEvidence
          : operation === "creditApplication"
            ? CreditApplicationRecordEvidence
            : RefundEvidence;
      const title =
        operation === "refundGet"
          ? "Current Refund value"
          : "Current Credit position";
      const before = stringifyFinancialJson(data);
      const view = render(<Component resource={data} />);
      expect(screen.getByRole("region", { name: title })).toHaveTextContent(
        "USD 1.00",
      );
      expect(screen.queryByText(/at original confirmation/)).toBeNull();
      view.rerender(<Component resource={data} showPosition={false} />);
      expect(screen.queryByRole("region", { name: title })).toBeNull();
      expect(stringifyFinancialJson(data)).toBe(before);
    },
  );
});
