// UI v81 (B4): one of a thing reads as one. TEST-FE-1910.
import { describe, expect, it } from "vitest";

import { singular } from "./plural";

describe("singular (UI v81)", () => {
  it("TEST-FE-1910 1 days reads 1 day; 21 days, $1 and 1.5 stay; Khmer is left alone", () => {
    expect(singular("1 days late")).toBe("1 day late");
    expect(singular("in 1 days")).toBe("in 1 day");
    expect(singular("1 nights · 1 people · 1 entries")).toBe(
      "1 night · 1 person · 1 entry",
    );
    expect(singular("21 days late")).toBe("21 days late");
    expect(singular("29 days")).toBe("29 days");
    expect(singular("1.1 days")).toBe("1.1 days");
    expect(singular("$1 days")).toBe("$1 days");
    expect(singular("យឺត 1 ថ្ងៃ")).toBe("យឺត 1 ថ្ងៃ");
  });
});
