import { describe, expect, it } from "vitest";

import type { RentAlert, RentAssessment } from "./lettersClient";
import {
  type RentRow,
  botNotice,
  nextLetter,
  noticesGiven,
  stepDay,
  waitingStep,
} from "./lettersData";

function row(
  flags: Partial<RentAssessment>,
  due = "2026-11-05",
  days: RentAssessment["step_days"] = {
    TEN_DAY_NOTICE: "2026-11-10",
    TWENTY_DAY_WARNING: "2026-11-20",
    TWENTY_FIVE_DAY_NOTICE: "2026-11-25",
    THIRTY_DAY_SERIOUS_DEFAULT: "2026-11-30",
  },
): RentRow {
  const alert: RentAlert = {
    rent_invoice_line_id: "line-1",
    invoice_id: "invoice-1",
    invoice_number: "INV1",
    lease_id: "lease-1",
    customer_id: "customer-1",
    due_date: due,
    case_id: null,
    assessment: {
      business_date: "2026-11-26",
      remaining_rent: { currency: "USD", minor_units: 50000 },
      ten_day_notice_eligible: false,
      twenty_day_warning_eligible: false,
      twenty_five_day_notice_eligible: false,
      thirty_day_default_eligible: false,
      ten_day_notice_recorded: false,
      warning_recorded: false,
      twenty_five_day_notice_recorded: false,
      serious_default_recorded: false,
      telegram_linked: false,
      step_days: days,
      ...flags,
    },
  };
  return {
    alert,
    lease: undefined,
    monthStart: `${due.slice(0, 8)}01`,
    letters: { 10: null, 20: null, 25: null, 30: null },
  };
}

describe("Rent notice days (DL-237)", () => {
  it("TEST-FE-2250 each step shows the day the server counted, and without it day N from the 1st but never before the Due Date has passed", () => {
    const counted = row({});
    expect(stepDay(counted, 10)).toBe("2026-11-10");
    expect(stepDay(counted, 30)).toBe("2026-11-30");
    // A Due Date on the 15th: the day-10 notice waits for the 16th.
    const late = row({}, "2026-11-15", null);
    expect(stepDay(late, 10)).toBe("2026-11-16");
    expect(stepDay(late, 20)).toBe("2026-11-20");
    expect(stepDay(late, 25)).toBe("2026-11-25");
    // Day 30 of February is 2 March.
    expect(stepDay(row({}, "2027-02-05", null), 30)).toBe("2027-03-02");
  });

  it("TEST-FE-2251 a person gives the notices of a tenant without Telegram, the Tenant bot those of a linked tenant, and the termination letter always waits for a person", () => {
    const due = {
      ten_day_notice_eligible: true,
      twenty_day_warning_eligible: true,
    };
    // No Telegram link: the oldest notice not given comes first.
    expect(nextLetter(row(due))).toBe(10);
    expect(nextLetter(row({ ...due, ten_day_notice_recorded: true }))).toBe(20);
    expect(botNotice(row(due))).toBeNull();
    // Linked: the notices go by themselves, so nobody is asked to record one.
    const linked = row({ ...due, telegram_linked: true });
    expect(nextLetter(linked)).toBeNull();
    expect(botNotice(linked)).toBe(10);
    // Day 30 with the three notices given: the termination letter, linked or not.
    const given = {
      ten_day_notice_recorded: true,
      warning_recorded: true,
      twenty_five_day_notice_recorded: true,
    };
    expect(noticesGiven(row(given).alert.assessment)).toBe(true);
    expect(noticesGiven(row(due).alert.assessment)).toBe(false);
    for (const telegram_linked of [true, false]) {
      const ready = row({
        ...given,
        telegram_linked,
        thirty_day_default_eligible: true,
      });
      expect(nextLetter(ready)).toBe(30);
      expect(botNotice(ready)).toBeNull();
    }
    // Nothing due today: the next step that is not given yet is the one to wait for.
    expect(waitingStep(row({ ten_day_notice_recorded: true }))).toBe(20);
    expect(waitingStep(row(given))).toBe(30);
    expect(
      waitingStep(row({ ...given, serious_default_recorded: true })),
    ).toBeNull();
  });
});
