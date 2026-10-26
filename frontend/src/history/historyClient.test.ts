import { afterEach, describe, expect, it, vi } from "vitest";

import {
  historyApi,
  HistoryNotAllowedError,
  HistoryUnavailableError,
} from "./historyClient";

afterEach(() => {
  vi.unstubAllGlobals();
});

const EVENT = {
  event_id: "e1",
  actor_id: "a1",
  property_id: "p/1",
  action: "invoice.created",
  resource_type: "invoice",
  resource_id: "r1",
  occurred_at: "2026-10-25T03:15:00Z",
  business_date: "2026-10-25",
  reason: "",
  previous_state: null,
  resulting_state: {},
  correlation_id: "c1",
  outcome: "succeeded",
  source: "api",
  linked_source_event_id: null,
};

describe("History client", () => {
  it("TEST-FE-961 reads a page of audit events with the filters as query values, and maps refusals", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: [EVENT],
            meta: { request_id: "r", next_cursor: "n2" },
          }),
        ),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 403 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: {}, meta: {} })),
      );
    vi.stubGlobal("fetch", fetcher);
    await expect(
      historyApi.search("p/1", {
        from: "2026-10-18",
        actorId: "a1",
        unitId: "u1",
        cursor: "c",
      }),
    ).resolves.toEqual({
      events: [
        {
          event_id: "e1",
          actor_id: "a1",
          action: "invoice.created",
          resource_type: "invoice",
          resource_id: "r1",
          occurred_at: "2026-10-25T03:15:00Z",
          business_date: "2026-10-25",
          reason: "",
          outcome: "succeeded",
          source: "api",
          linked_source_event_id: null,
        },
      ],
      nextCursor: "n2",
    });
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/p%2F1/audit-events?limit=50&from_date=2026-10-18&actor_id=a1&unit_id=u1&cursor=c",
    );
    await expect(historyApi.search("p/1", {})).rejects.toBeInstanceOf(
      HistoryNotAllowedError,
    );
    await expect(historyApi.search("p/1", {})).rejects.toBeInstanceOf(
      HistoryUnavailableError,
    );
  });
});
