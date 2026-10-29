import { afterEach, describe, expect, it, vi } from "vitest";

import {
  moveOutApi,
  MoveOutConflictError,
  MoveOutNotAllowedError,
  MoveOutRequestError,
  MoveOutUnavailableError,
  type InspectionSource,
  type MoveOutSource,
} from "./moveoutClient";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const RECORD = {
  event_id: "m1",
  lease_id: "l/1",
  termination_event_id: "t1",
  actual_move_out_date: "2026-10-25",
  unit_condition: "CLEANING",
  resulting_unit_status: "CLEANING",
  reason: "Parking handed back",
  evidence_reference: "Keys returned: all",
  supersedes_event_id: null,
  occurred_at: "2026-10-25T05:00:00Z",
  actor_id: "a1",
  occupancies: [],
};

const SOURCE: MoveOutSource = {
  event_id: "m1",
  termination_event_id: "t1",
  expected_lease_version: 4,
  expected_unit_version: 7,
  actual_move_out_date: "2026-10-25",
  unit_condition: "CLEANING",
  occupancies: [{ occupancy_id: "o1", expected_version: 2 }],
  reason: "Parking handed back",
  authorization_reference: "Recorded in the app",
  evidence_reference: "Keys returned: all",
  supersedes_event_id: null,
};

describe("Move-out client", () => {
  it("TEST-FE-965 reads a Lease's move-outs and open Occupancies, records one with the key and the CSRF token, and maps refusals", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              items: [RECORD],
              total: 1,
              open_occupancies: [
                {
                  occupancy_id: "o1",
                  customer_id: "c1",
                  move_in_date: "2025-10-25",
                  version: 2,
                },
              ],
            },
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: RECORD }), { status: 201 }),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 409 }))
      .mockResolvedValueOnce(new Response("{}", { status: 404 }))
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockRejectedValueOnce(new TypeError("offline"));
    vi.stubGlobal("fetch", fetcher);
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=token-1",
    );
    await expect(moveOutApi.read("p/1", "l/1")).resolves.toEqual({
      items: [RECORD],
      total: 1,
      open_occupancies: [
        {
          occupancy_id: "o1",
          customer_id: "c1",
          move_in_date: "2025-10-25",
          version: 2,
        },
      ],
    });
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/p%2F1/leases/l%2F1/move-outs?limit=20",
    );
    await expect(
      moveOutApi.record("p/1", "l/1", SOURCE, "key-1"),
    ).resolves.toEqual(RECORD);
    const [url, init] = fetcher.mock.calls[1] ?? [];
    expect(url).toBe("/api/v1/properties/p%2F1/leases/l%2F1/move-outs");
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("Idempotency-Key")).toBe("key-1");
    expect(headers.get("X-CSRF-Token")).toBe("token-1");
    expect(JSON.parse(init?.body as string)).toEqual(SOURCE);
    await expect(
      moveOutApi.record("p/1", "l/1", SOURCE, "key-1"),
    ).rejects.toBeInstanceOf(MoveOutConflictError);
    await expect(moveOutApi.read("p/1", "l/1")).rejects.toBeInstanceOf(
      MoveOutNotAllowedError,
    );
    await expect(moveOutApi.read("p/1", "l/1")).rejects.toBeInstanceOf(
      MoveOutUnavailableError,
    );
    await expect(moveOutApi.read("p/1", "l/1")).rejects.toBeInstanceOf(
      MoveOutUnavailableError,
    );
  });

  it("TEST-FE-983 reads a Lease's move-out inspections a page at a time and records one with the key and the CSRF token; an unreadable page is refused; a failed or unreadable save may be saved", async () => {
    const inspection = {
      id: "i1",
      lease_id: "l/1",
      inspection_date: "2026-10-13",
      result_text: "No damage found.",
      evidence_reference: "Recorded in the app",
      reason: "Move-out inspection",
      completed_at: "2026-10-13T04:00:00Z",
      supersedes_inspection_id: null,
      current_effect: "INSPECTION_ONLY",
      findings: [],
    };
    const source: InspectionSource = {
      inspection_id: "i1",
      expected_lease_version: 4,
      inspection_date: "2026-10-13",
      result_text: "No damage found.",
      authorization_reference: "Recorded in the app",
      evidence_reference: "Recorded in the app",
      reason: "Move-out inspection",
      findings: [],
      supersedes_inspection_id: null,
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ data: { items: [inspection], total: 21 } }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: inspection }), { status: 201 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { items: "none", total: 1 } })),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 409 }))
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { id: 1 } }), { status: 201 }),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=token-1",
    );
    await expect(moveOutApi.inspections("p/1", "l/1", 20)).resolves.toEqual({
      items: [inspection],
      total: 21,
    });
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/p%2F1/leases/l%2F1/move-out-inspections?limit=20&offset=20",
    );
    await expect(
      moveOutApi.inspect("p/1", "l/1", source, "key-2"),
    ).resolves.toEqual(inspection);
    const [url, init] = fetcher.mock.calls[1] ?? [];
    expect(url).toBe(
      "/api/v1/properties/p%2F1/leases/l%2F1/move-out-inspections",
    );
    const headers = new Headers(init?.headers);
    expect(headers.get("Idempotency-Key")).toBe("key-2");
    expect(headers.get("X-CSRF-Token")).toBe("token-1");
    expect(JSON.parse(init?.body as string)).toEqual(source);
    await expect(
      moveOutApi.inspections("p/1", "l/1", 0),
    ).rejects.toBeInstanceOf(MoveOutRequestError);
    await expect(
      moveOutApi.inspect("p/1", "l/1", source, "key-2"),
    ).rejects.toBeInstanceOf(MoveOutConflictError);
    await expect(
      moveOutApi.inspect("p/1", "l/1", source, "key-2"),
    ).rejects.toBeInstanceOf(MoveOutUnavailableError);
    await expect(
      moveOutApi.inspect("p/1", "l/1", source, "key-2"),
    ).rejects.toBeInstanceOf(MoveOutUnavailableError);
    await expect(
      moveOutApi.inspect("p/1", "l/1", source, "key-2"),
    ).rejects.toBeInstanceOf(MoveOutUnavailableError);
  });
});
