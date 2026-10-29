import { describe, expect, it } from "vitest";

import { acceptanceReason } from "./MakeReservationDialog";

describe("Make Reservation saved reason (V1-061 review)", () => {
  it("TEST-FE-1119 keeps the person's words, adds the Rent-below reason, and is cut by whole characters with no space at the end", () => {
    expect(acceptanceReason("Agreed with the Owner.", null)).toBe(
      "Agreed with the Owner.",
    );
    expect(acceptanceReason("Agreed with the Owner.", "Long stay")).toBe(
      "Agreed with the Owner. Rent below the Unit default: Long stay",
    );
    const long = acceptanceReason(`${"a".repeat(499)} 😀`, null);
    expect(long).toBe("a".repeat(499));
    const cut = acceptanceReason(`${"b".repeat(499)}😀😀`, null);
    expect(Array.from(cut)).toHaveLength(500);
    expect(cut.endsWith("😀")).toBe(true);
  });
});
