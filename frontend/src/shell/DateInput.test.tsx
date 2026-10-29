import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DateInput } from "./DateInput";

afterEach(cleanup);

describe("Date box (V1-061 owner test)", () => {
  it("TEST-FE-1120 says at once when a typed date is not a real day, and clears when it is fixed", () => {
    render(<DateInput id="day" />);
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "30/02/2026" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.blur(box);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This is not a real day.",
    );
    expect(box).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(box, { target: { value: "28/02/2026" } });
    fireEvent.blur(box);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(box).toHaveValue("28/02/2026");
  });
});
