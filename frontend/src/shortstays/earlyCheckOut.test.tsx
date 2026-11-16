// UI v81 (owner 07/11/2026): Check out before the booked day warns first. TEST-FE-1904.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Booking } from "./shortStaysClient";
import { CheckOutCard } from "./StaySteps";

afterEach(() => {
  cleanup();
});

function show(today: string) {
  const onStep = vi.fn();
  const booking = {
    status: "CHECKED_IN",
    version: 4,
    unit_number: "U305",
    check_out_on: "2026-11-12",
    nights: 7,
  } as unknown as Booking;
  render(
    <CheckOutCard
      booking={booking}
      busy={false}
      language="en"
      may={() => true}
      onDecide={vi.fn()}
      onPrice={vi.fn()}
      onStep={onStep}
      problemTypes={[]}
      today={today}
    />,
  );
  return onStep;
}

describe("Early check-out warning", () => {
  it("TEST-FE-1904 warns before the check-out day; Keep the stay does nothing; Check out early checks out; on the day no warning", () => {
    const onStep = show("2026-11-07");
    fireEvent.click(screen.getByRole("button", { name: "Check out" }));
    const dialog = screen.getByRole("dialog", {
      name: "Not the check-out date",
    });
    expect(dialog).toHaveTextContent(
      "U305 is booked until 12/11/2026 (7 nights). Today is 07/11/2026.",
    );
    expect(dialog).toHaveTextContent(
      "The unused nights stay paid. There is no money back by itself.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep the stay" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onStep).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Check out" }));
    fireEvent.click(screen.getByRole("button", { name: "Check out early" }));
    expect(onStep).toHaveBeenCalledWith("check-out", { version: 4 });
    cleanup();

    const onDay = show("2026-11-12");
    fireEvent.click(screen.getByRole("button", { name: "Check out" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onDay).toHaveBeenCalledWith("check-out", { version: 4 });
  });
});
