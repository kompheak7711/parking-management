import { describe, expect, it } from "vitest";

import { serverWords } from "./serverText";

describe("Server words in the screen's language (V1-061 Fix 4)", () => {
  it("TEST-FE-1115 English shows the server's message; Khmer shows the code's Khmer words, and plain Khmer when the code is not known", () => {
    const refusal = {
      code: "DEPOSIT_SECURITY_ALREADY_EXISTS",
      message: "This Lease already has a Security Deposit.",
    };
    expect(serverWords("en", refusal)).toBe(
      "This Lease already has a Security Deposit.",
    );
    expect(serverWords("km", refusal)).toBe(
      "កិច្ចសន្យាជួលនេះ មានប្រាក់កក់សុវត្ថិភាពរួចហើយ។",
    );
    for (const code of ["SOMETHING_NEW", null])
      expect(
        serverWords("km", { code, message: "Some English words." }),
      ).toMatch(/^ម៉ាស៊ីនមេបានបដិសេធសំណើនេះ។/);
  });
});
