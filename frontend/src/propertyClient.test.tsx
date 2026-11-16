import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PropertyConfigurationError,
  PropertyConfigurationUnavailableError,
  PropertySavedReadFailedError,
  propertyConfigurationApi,
} from "./propertyClient";

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});

function response(data: Record<string, unknown>, status = 200): Response {
  return new Response(
    JSON.stringify({ data, meta: { request_id: "request-1" } }),
    {
      status,
      headers: { "Content-Type": "application/json" },
    },
  );
}

describe("Property business configuration client", () => {
  it("TEST-FE-017 loads Property source fields and configured Payment Methods", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        response({
          property_id: "property-1",
          name: "Riverside",
          address_text: "Phnom Penh",
          timezone_name: "Asia/Phnom_Penh",
          version: 3,
        }),
      )
      .mockResolvedValueOnce(
        response({
          property_id: "property-1",
          timezone_name: "Asia/Phnom_Penh",
          version: 3,
          payment_methods: [
            { code: "BANK", display_name: "Bank transfer", accepted: true },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      propertyConfigurationApi.load("property-1"),
    ).resolves.toMatchObject({
      name: "Riverside",
      version: 3,
      payment_methods: [{ code: "BANK", accepted: true }],
    });
  });

  it("TEST-FE-018 uses CSRF and the exact version precondition for source updates", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValueOnce(response({}));
    fetchMock.mockResolvedValueOnce(
      response({
        property_id: "property-1",
        name: "Updated",
        address_text: null,
        timezone_name: "Asia/Phnom_Penh",
        version: 4,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      response({
        property_id: "property-1",
        timezone_name: "Asia/Phnom_Penh",
        version: 4,
        payment_methods: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await propertyConfigurationApi.updateSource(
      {
        property_id: "property-1",
        name: "Riverside",
        address_text: "Phnom Penh",
        description: null,
        business_name: null,
        timezone_name: "Asia/Phnom_Penh",
        payment_methods: [],
        version: 3,
      },
      { name: "Updated", address_text: null },
    );

    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("If-Match")).toBe('"3"');
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("TEST-FE-953 a saved change whose read-back fails says it was saved, not that it failed", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({}))
      .mockRejectedValueOnce(new Error("network down"))
      .mockRejectedValueOnce(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      propertyConfigurationApi.updatePaymentMethods(
        {
          property_id: "property-1",
          name: "Riverside",
          address_text: null,
          description: null,
          business_name: null,
          timezone_name: "Asia/Phnom_Penh",
          payment_methods: [],
          version: 3,
        },
        [
          {
            code: "CASH",
            display_name: "Cash",
            accepted: true,
            aba_qr: false,
          },
        ],
      ),
    ).rejects.toBeInstanceOf(PropertySavedReadFailedError);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("PATCH");
  });

  it("TEST-FE-019 does not expose configuration after a server capability denial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(response({}, 403)),
    );

    await expect(
      propertyConfigurationApi.load("property-1"),
    ).rejects.toBeInstanceOf(PropertyConfigurationUnavailableError);
  });

  it("TEST-FE-2142 the ABA QR mark of a Payment Method is read as true or false (no mark = false), a mark that is not true or false is refused, and a save sends the mark (DL-227)", async () => {
    const read = (methods: unknown[]) =>
      response({
        property_id: "property-1",
        timezone_name: "Asia/Phnom_Penh",
        version: 5,
        payment_methods: methods,
      });
    const source = response({
      property_id: "property-1",
      name: "Riverside",
      address_text: null,
      timezone_name: "Asia/Phnom_Penh",
      version: 5,
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(source.clone())
        .mockResolvedValueOnce(
          read([
            { code: "CASH", display_name: "Cash", accepted: true },
            {
              code: "ABA",
              display_name: "ABA QR code",
              accepted: true,
              aba_qr: true,
            },
          ]),
        ),
    );
    const loaded = await propertyConfigurationApi.load("property-1");
    expect(loaded.payment_methods.map((method) => method.aba_qr)).toEqual([
      false,
      true,
    ]);

    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(source.clone())
        .mockResolvedValueOnce(
          read([
            {
              code: "CASH",
              display_name: "Cash",
              accepted: true,
              aba_qr: "yes",
            },
          ]),
        ),
    );
    await expect(
      propertyConfigurationApi.load("property-1"),
    ).rejects.toBeInstanceOf(PropertyConfigurationError);

    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    const save = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({}))
      .mockResolvedValueOnce(source.clone())
      .mockResolvedValueOnce(read([]));
    vi.stubGlobal("fetch", save);
    await propertyConfigurationApi.updatePaymentMethods(loaded, [
      { code: "CASH", display_name: "Cash", accepted: true, aba_qr: true },
      {
        code: "ABA",
        display_name: "ABA QR code",
        accepted: true,
        aba_qr: false,
      },
    ]);
    const body = JSON.parse(save.mock.calls[0]?.[1]?.body as string) as {
      payment_methods: { aba_qr: boolean }[];
    };
    expect(body.payment_methods.map((method) => method.aba_qr)).toEqual([
      true,
      false,
    ]);
  });
});
