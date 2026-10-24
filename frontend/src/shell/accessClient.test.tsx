import { describe, expect, it, vi } from "vitest";

import {
  ActorAccessUnavailableError,
  createActorAccessApi,
  parseActorAccess,
} from "./accessClient";

describe("V1-058 R1b access read", () => {
  it("TEST-FE-813 reads the person's own access once and refuses any other shape", async () => {
    const body = {
      data: {
        actor_id: "actor-1",
        capabilities: [{ capability: "units.read", property_ids: ["p-1"] }],
      },
      meta: { request_id: "r" },
    };
    const fetchDouble = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(body)));
    const access = await createActorAccessApi(fetchDouble).read(
      new AbortController().signal,
    );
    expect(access).toEqual(body.data);
    expect(fetchDouble.mock.calls[0]?.[0]).toBe("/api/v1/identity/me/access");
    expect(fetchDouble.mock.calls[0]?.[1]).toMatchObject({
      credentials: "include",
    });

    for (const bad of [
      null,
      { data: null },
      { data: { actor_id: 1, capabilities: [] } },
      { data: { actor_id: "a", capabilities: [{ capability: "x" }] } },
      {
        data: {
          actor_id: "a",
          capabilities: [{ capability: "x", property_ids: [1] }],
        },
      },
    ]) {
      expect(() => parseActorAccess(bad)).toThrow(ActorAccessUnavailableError);
    }
    await expect(
      createActorAccessApi(
        vi
          .fn<typeof fetch>()
          .mockResolvedValue(new Response("", { status: 403 })),
      ).read(new AbortController().signal),
    ).rejects.toThrow(ActorAccessUnavailableError);
    await expect(
      createActorAccessApi(
        vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline")),
      ).read(new AbortController().signal),
    ).rejects.toThrow(ActorAccessUnavailableError);
  });
});
