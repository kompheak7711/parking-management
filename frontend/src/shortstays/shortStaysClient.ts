// Daily and weekly rent, phase 6 step 2: Tenants › Short stays. The calendar, the price box and
// bookings. The server prices every stay from the owner's rules and checks every right; this
// client only reads and sends.

import { choicesOf, type ProblemType } from "../problems/problemsClient";

export type BookingStatus =
  | "BOOKED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED"
  | "NO_SHOW";
export type BookingSource =
  | "WALK_IN"
  | "PHONE"
  | "TELEGRAM"
  | "WEBSITE"
  | "BOOKING_SITE";
export type PriceKind =
  | "NIGHTS"
  | "WEEKS"
  | "EARLY_CHECK_IN"
  | "LATE_CHECK_OUT"
  | "RETURNING_GUEST"
  | "EXTRA_DISCOUNT";

export const SOURCES: readonly BookingSource[] = [
  "WALK_IN",
  "PHONE",
  "TELEGRAM",
  "WEBSITE",
  "BOOKING_SITE",
];
const STATUSES: readonly BookingStatus[] = [
  "BOOKED",
  "CHECKED_IN",
  "CHECKED_OUT",
  "CANCELLED",
  "NO_SHOW",
];
const KINDS: readonly PriceKind[] = [
  "NIGHTS",
  "WEEKS",
  "EARLY_CHECK_IN",
  "LATE_CHECK_OUT",
  "RETURNING_GUEST",
  "EXTRA_DISCOUNT",
];

export interface PriceLine {
  position: number;
  kind: PriceKind;
  quantity: number;
  unit_price_usd_cents: number;
  discount_basis_points: number;
  amount_usd_cents: number;
}

export interface StayPrice {
  unit_id: string;
  unit_number: string;
  unit_type: string;
  check_in_on: string;
  check_out_on: string;
  nights: number;
  night_usd_cents: number;
  week_usd_cents: number;
  total_usd_cents: number;
  charged_as_whole_weeks: boolean;
  lines: PriceLine[];
  month_only_usd_cents: number | null;
  suggest_month: boolean;
  /** Why the Unit cannot be booked for these nights: PAST, BOOKED, LEASE, RESERVED … */
  blockers: string[];
  /** Step 5a: nights a booking site holds; only a booking from that site may take them. */
  site_holds: SiteHold[];
}

/** Step 5a: a booked range read from a booking site's calendar. */
export interface SiteHold {
  hold_id: string;
  site_name: string;
  start_on: string;
  end_on: string;
  /** The calendar only: a booking from somewhere else has the same nights. */
  clash: boolean;
}

/** Step 5a: a booking site's calendar link for one Unit. */
export interface SiteCalendar {
  calendar_id: string;
  unit_id: string;
  unit_number: string;
  site_name: string;
  import_url: string | null;
  active: boolean;
  last_read_at: string | null;
  last_read_ok: boolean | null;
  last_error: string | null;
  version: number;
  holds: number;
}

export interface SiteCalendarSave {
  unit_id?: string;
  calendar_id?: string;
  version?: number;
  site_name: string;
  import_url?: string;
  active: boolean;
}

export interface CalendarBooking {
  booking_id: string;
  booking_number: string;
  guest_name: string;
  status: BookingStatus;
  source: BookingSource;
  check_in_on: string;
  check_out_on: string;
  /** Paid in full (or on the booking site); an unpaid booking shows a dashed square. */
  paid: boolean;
}

export interface CalendarUnit {
  unit_id: string;
  unit_number: string;
  unit_type: string;
  status: string;
  for_rent: boolean;
  monthly_rent_usd_cents: number | null;
  bookings: CalendarBooking[];
  leases: { lease_id: string; start_date: string; end_date: string }[];
  reserved: boolean;
  site_holds: SiteHold[];
}

export interface StayCalendar {
  from: string;
  days: number;
  today: string;
  units: CalendarUnit[];
}

export interface BookingHistoryEntry {
  kind: string;
  occurred_at: string;
  note: string | null;
  /** What the step kept beside its note: the two Units of a move, the amount of a discount. */
  details?: Record<string, unknown> | null;
}

/** Step 3: how the stay is paid. */
export type PaymentState =
  | "NOT_BILLED"
  | "UNPAID"
  | "PARTIALLY_PAID"
  | "PAID"
  | "PAID_ON_SITE";
const PAYMENTS: readonly PaymentState[] = [
  "NOT_BILLED",
  "UNPAID",
  "PARTIALLY_PAID",
  "PAID",
  "PAID_ON_SITE",
];

export interface StayDeposit {
  deposit_id: string;
  kind: "CASH" | "CARD_HOLD";
  amount_usd_cents: number;
  hold_reference: string | null;
  card_last4: string | null;
  status: "HELD" | "RETURNED" | "KEPT";
  kept_usd_cents: number;
  taken_at: string;
  ended_at: string | null;
}

export interface RoomCheck {
  task_id: string;
  task_on: string;
  status: "TO_DO" | "DONE" | "SKIPPED";
  note: string | null;
  done_at: string | null;
}

export interface StayDamage {
  damage_id: string;
  description: string;
  amount_usd_cents: number;
  status: "WAITING" | "APPROVED" | "REFUSED";
  decided_at: string | null;
  decision_note: string | null;
  from_deposit_usd_cents: number;
  invoice_id: string | null;
  invoice_number: string | null;
}

/** DL-222: a problem the room check reported, kept as a Unit Problem report. */
export interface StayProblem {
  report_id: string;
  report_number: string;
  description: string;
  type_name_en: string;
  type_name_kh: string | null;
  urgent: boolean;
  status: string;
}

/** DL-222: the one decision on a stay's damage, made by the person who bills damage. */
export interface DamageDecision {
  outcome: "CHARGE" | "NO_CHARGE";
  damage_id: string | null;
  note: string | null;
  decided_at: string;
}

/** DL-222: Charge the guest (what for and how much) or No charge. */
export type DamageChoice =
  | { charge: true; description: string; amount_usd_cents: number }
  | { charge: false; note?: string };

/** Owner test 06/11/2026: a free cancel's money, given back with the Refund button. */
export interface StayRefund {
  credits: { credit_id: string; left_usd_cents: number }[];
  left_usd_cents: number;
  waiting_usd_cents: number;
  refunded_usd_cents: number;
}

/** A Refund method (Cash, Bank transfer) from Settings. */
export interface RefundMethod {
  id: string;
  name: string;
}

export interface NewRefund {
  credit_id: string;
  amount_usd_cents: number;
  reason: string;
  refund_method_id: string;
  reference_note: string;
}

export interface Booking {
  booking_id: string;
  booking_number: string;
  unit_id: string;
  unit_number: string;
  unit_type: string;
  customer_id: string;
  guest_name: string;
  guest_phone: string | null;
  guest_count: number;
  check_in_on: string;
  check_out_on: string;
  nights: number;
  source: BookingSource;
  site_name: string | null;
  site_reference: string | null;
  note: string | null;
  status: BookingStatus;
  total_usd_cents: number;
  version: number;
  created_at: string;
  lines: PriceLine[];
  history: BookingHistoryEntry[];
  unit_status: string;
  guest_has_id: boolean;
  payment: PaymentState;
  invoice: {
    invoice_id: string;
    invoice_number: string;
    status: string;
    total_usd_cents: number;
    /** Step 5b: what the guest owes after the thank-you or discount credit. */
    due_usd_cents: number;
  } | null;
  deposit: StayDeposit | null;
  room_check: RoomCheck | null;
  damages: StayDamage[];
  /** DL-222: the problems the room check reported. */
  problems: StayProblem[];
  damage_decision: DamageDecision | null;
  /** Problems were reported and nobody has charged the guest or chosen No charge yet. */
  damage_due: boolean;
  extra_invoices: ExtraInvoice[];
  early_check_in: boolean;
  late_check_out: boolean;
  /** What an early check-in or a late check-out costs this stay; 0 from 7 nights. */
  fee_usd_cents: number;
  /** Minutes after midnight. */
  check_in_time: number;
  check_out_time: number;
  late_check_out_until: number;
  cleans: DailyClean[];
  /** The last day of free cancel (until 23:59). */
  free_cancel_until: string;
  cancel_reason: string | null;
  paid_usd_cents: number;
  cancellation: StayCancellation | null;
  credit: StayCredit | null;
  /** After a free cancel: the guest's Credit it made, and what the Refund button gives back. */
  refund?: StayRefund | null;
  /** Step 4c: what comes off the first month when the guest changes to a Lease (today's rule). */
  lease_off_usd_cents: number;
  lease_offer: StayLeaseOffer | null;
  /** The guest's Lease drafts in this building, not linked yet. */
  lease_drafts: StayLeaseDraft[];
  /** Step 5b: the guest stayed and checked out before this stay. */
  returning_guest: boolean;
  /** A note marks the guest as a problem guest. */
  problem_guest: boolean;
  review_asked_at: string | null;
}

/** Step 5b: one stay in a guest's history. */
export interface GuestStay {
  booking_id: string;
  booking_number: string;
  unit_number: string;
  check_in_on: string;
  check_out_on: string;
  status: BookingStatus;
  source: BookingSource;
  site_name: string | null;
  total_usd_cents: number;
}

export interface GuestNote {
  note: string;
  problem_guest: boolean;
  created_at: string;
  booking_number: string | null;
}

/** Step 5b: a guest's stays in this building, the notes and the problem-guest mark. */
export interface GuestHistory {
  customer_id: string;
  legal_name: string;
  phone_number: string | null;
  stays: GuestStay[];
  stays_done: number;
  nights_done: number;
  spent_usd_cents: number;
  returning: boolean;
  problem_guest: boolean;
  notes: GuestNote[];
  /** Today's thank-you for a returning direct guest (0 when only a note was added). */
  thank_you_usd_cents: number;
}

/** Step 5b: today's price for a Unit and nights, to send to the guest. Not a promise. */
export interface StayQuote {
  quote_id: string;
  quote_number: string;
  unit_id: string | null;
  unit_number: string | null;
  unit_type: string;
  guest_name: string | null;
  guest_contact: string | null;
  guest_count: number;
  check_in_on: string;
  check_out_on: string;
  nights: number;
  total_usd_cents: number;
  lines: PriceLine[];
  made_on: string;
  /** Minutes after midnight. */
  check_in_time: number;
  check_out_time: number;
  deposit_usd_cents: number;
  /** Step 5c: the month prices next to the stay. */
  month_only_usd_cents: number | null;
  monthly_rent_usd_cents: number | null;
}

/** Step 5c: one Unit's week in the report; money in cents. */
export interface ReportUnit {
  unit_id: string;
  unit_number: string;
  nights: number;
  income_usd_cents: number;
  site_fees_usd_cents: number;
  cleaning_usd_cents: number;
  net_usd_cents: number;
}

/** Step 5c: the weekly short-stay report (Owner and Manager). */
export interface WeekReport {
  from: string;
  to: string;
  so_far: boolean;
  /** Basis points: 4000 = 40%. */
  base_occupancy_points: number;
  change_over_usd_cents: number;
  linen_usd_cents: number;
  units: ReportUnit[];
  totals: {
    units: number;
    unit_nights: number;
    nights: number;
    income_usd_cents: number;
    site_fees_usd_cents: number;
    cleaning_usd_cents: number;
    net_usd_cents: number;
    occupancy_points: number;
  };
  leases: {
    booking_id: string;
    booking_number: string;
    guest_name: string;
    lease_id: string;
    lease_unit_number: string;
    off_usd_cents: number;
  }[];
  damages: {
    damage_id: string;
    booking_id: string;
    booking_number: string;
    unit_number: string;
    description: string;
    amount_usd_cents: number;
    status: string;
  }[];
  complaints: {
    complaint_id: string;
    noted_on: string;
    unit_number: string | null;
    what: string;
  }[];
  sources: { source: BookingSource; site_name: string | null; stays: number }[];
  cancellations: { count: number; kept_usd_cents: number };
}

export interface NewComplaint {
  what: string;
  unit_id?: string;
  noted_on?: string;
}

export interface NewQuote {
  unit_id: string;
  guest_name: string;
  guest_contact?: string;
  guest_count: number;
  check_in_on: string;
  check_out_on: string;
}

/** Step 3: the actions on one booking; each answers with the booking as it is now. */
export type StayStep =
  | "bill"
  | "paid-on-site"
  | "deposit"
  | "deposit/end"
  | "check-in"
  | "check-out"
  | "room-check"
  | "damage"
  | "fee"
  | "extend"
  | "cancel"
  | "credit"
  | "credit/end"
  | "lease"
  | "discount"
  | "unit"
  | "move-discount"
  | "review";

/** Step 4c: the guest's Lease, with the money off its first month kept from the link. */
export interface StayLeaseOffer {
  lease_id: string;
  off_usd_cents: number;
  lease_status: string;
  start_date: string | null;
  unit_number: string;
}

export interface StayLeaseDraft {
  lease_id: string;
  unit_number: string;
  start_date: string | null;
  monthly_rent_usd_cents: number;
}

/** Step 4b: how a cancelled booking ended. */
/** DL-224: a Unit a booked stay can move to: free on every night of the stay. */
export interface MoveUnit {
  unit_id: string;
  unit_number: string;
  floor: string;
  unit_type: string;
  /** The same type as the Unit the guest booked; these are offered first. */
  same_type: boolean;
  monthly_rent_usd_cents: number | null;
}

export interface StayCancellation {
  kind: "CANCELLED" | "NO_SHOW";
  free: boolean;
  paid_usd_cents: number;
  /** Made Customer Credit, to pay back on Refund of Credit (free cancel). */
  back_usd_cents: number;
  /** Kept as income (late cancel or no-show). */
  kept_usd_cents: number;
}

export interface StayCredit {
  amount_usd_cents: number;
  use_by: string;
  note: string;
  /** Step 5d: what the guest can still use (0 once the credit ended). */
  left_usd_cents: number;
  /** Step 5d: the credit ended after its use-by day; what was left paid this Invoice. */
  ended: {
    left_usd_cents: number;
    invoice_id: string | null;
    invoice_number: string | null;
    at: string;
  } | null;
}

/** Step 5d: a late-cancel credit past its use-by day, with money left. */
export interface CreditDue {
  booking_id: string;
  booking_number: string;
  guest_name: string;
  use_by: string;
  left_usd_cents: number;
}

/** DL-222: a stay whose room check reported problems and whose damage is not decided yet. */
export interface DamageDue {
  booking_id: string;
  booking_number: string;
  guest_name: string;
  unit_number: string;
  problem_count: number;
}

/** Step 4a: an Invoice for a fee or an extension, made after the stay was billed. */
export interface ExtraInvoice {
  invoice_id: string;
  invoice_number: string;
  status: string;
  kind: "EXTEND" | "EARLY_CHECK_IN" | "LATE_CHECK_OUT";
  total_usd_cents: number;
}

export interface DailyClean {
  task_id: string;
  task_on: string;
  status: "TO_DO" | "DONE" | "SKIPPED";
  note: string | null;
}

/** Step 4a: one task on the cleaning list of a day. */
export interface CleaningTask {
  task_id: string;
  kind: "DAILY_CLEAN" | "CHANGE_OVER" | "ROOM_CHECK";
  task_on: string;
  status: "TO_DO" | "DONE" | "SKIPPED";
  note: string | null;
  done_at: string | null;
  unit_id: string;
  unit_number: string;
  booking_id: string | null;
  booking_number: string | null;
  guest_name: string | null;
  /** Due on an earlier day and not done yet (shown today). */
  late: boolean;
}

export interface CleaningDay {
  day: string;
  today: string;
  tasks: CleaningTask[];
}

export interface NewBooking {
  unit_id: string;
  customer_id: string;
  guest_count: number;
  check_in_on: string;
  check_out_on: string;
  source: BookingSource;
  site_name?: string;
  site_reference?: string;
  note?: string;
}

export interface ShortStaysApi {
  calendar: (
    propertyId: string,
    from: string,
    days: number,
  ) => Promise<StayCalendar>;
  price: (
    propertyId: string,
    unitId: string,
    checkIn: string,
    checkOut: string,
  ) => Promise<StayPrice>;
  list: (propertyId: string) => Promise<Booking[]>;
  get: (propertyId: string, bookingId: string) => Promise<Booking>;
  book: (propertyId: string, booking: NewBooking) => Promise<Booking>;
  step: (
    propertyId: string,
    bookingId: string,
    step: StayStep,
    body: Record<string, unknown> | null,
  ) => Promise<Booking>;
  /** DL-224: the Units a booked stay can move to, the same type first. */
  moveUnits: (propertyId: string, bookingId: string) => Promise<MoveUnit[]>;
  decide: (
    propertyId: string,
    damageId: string,
    decision: { approve: boolean; note?: string },
  ) => Promise<Booking>;
  cleaning: (propertyId: string, day: string) => Promise<CleaningDay>;
  finishTask: (
    propertyId: string,
    taskId: string,
    finish: { skip: boolean; note?: string },
  ) => Promise<CleaningDay>;
  siteCalendars: (propertyId: string) => Promise<SiteCalendar[]>;
  saveSiteCalendar: (
    propertyId: string,
    link: SiteCalendarSave,
  ) => Promise<SiteCalendar>;
  guest: (propertyId: string, customerId: string) => Promise<GuestHistory>;
  addGuestNote: (
    propertyId: string,
    customerId: string,
    note: { note: string; problem_guest: boolean; booking_id?: string },
  ) => Promise<GuestHistory>;
  quotes: (propertyId: string) => Promise<StayQuote[]>;
  quote: (propertyId: string, quote: NewQuote) => Promise<StayQuote>;
  weekReport: (propertyId: string, from: string) => Promise<WeekReport>;
  complaint: (propertyId: string, complaint: NewComplaint) => Promise<void>;
  creditsDue: (propertyId: string) => Promise<CreditDue[]>;
  /** DL-222: the stays waiting for Charge the guest or No charge (damage_charges.bill). */
  damageDue: (propertyId: string) => Promise<DamageDue[]>;
  /** DL-222: the problem types the room check offers (problem_reports.read). */
  problemTypes: (propertyId: string) => Promise<ProblemType[]>;
  refundMethods: (propertyId: string) => Promise<RefundMethod[]>;
  /** Records a Refund draft of one Credit; a financial.approve holder confirms it. */
  refund: (propertyId: string, refund: NewRefund, key: string) => Promise<void>;
}

export class ShortStaysError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404, 409 taken or not bookable,
   * 422 refused. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super("The short-stay command was not completed.");
    this.name = "ShortStaysError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new ShortStaysError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new ShortStaysError();
  return token;
}

async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new ShortStaysError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      isObject(payload) && typeof payload.detail === "string"
        ? payload.detail
        : null;
    throw new ShortStaysError(response.status, detail);
  }
  if (!isObject(payload) || !("data" in payload)) throw new ShortStaysError();
  return payload.data;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new ShortStaysError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new ShortStaysError();
  return value;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new ShortStaysError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new ShortStaysError();
  return value;
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T {
  const found = values.find((entry) => entry === value);
  if (found === undefined) throw new ShortStaysError();
  return found;
}

function lineOf(value: unknown): PriceLine {
  const row = record(value);
  return {
    position: whole(row.position),
    kind: oneOf(KINDS, row.kind),
    quantity: whole(row.quantity),
    unit_price_usd_cents: whole(row.unit_price_usd_cents),
    discount_basis_points: whole(row.discount_basis_points),
    amount_usd_cents: whole(row.amount_usd_cents),
  };
}

export function priceOf(value: unknown): StayPrice {
  const row = record(value);
  return {
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    unit_type: text(row.unit_type),
    check_in_on: text(row.check_in_on),
    check_out_on: text(row.check_out_on),
    nights: whole(row.nights),
    night_usd_cents: whole(row.night_usd_cents),
    week_usd_cents: whole(row.week_usd_cents),
    total_usd_cents: whole(row.total_usd_cents),
    charged_as_whole_weeks: row.charged_as_whole_weeks === true,
    lines: list(row.lines).map(lineOf),
    month_only_usd_cents: maybeWhole(row.month_only_usd_cents),
    suggest_month: row.suggest_month === true,
    blockers: list(row.blockers).map(text),
    site_holds: list(row.site_holds ?? []).map(holdOf),
  };
}

function holdOf(value: unknown): SiteHold {
  const row = record(value);
  return {
    hold_id: text(row.hold_id),
    site_name: text(row.site_name),
    start_on: text(row.start_on),
    end_on: text(row.end_on),
    clash: row.clash === true,
  };
}

export function siteCalendarOf(value: unknown): SiteCalendar {
  const row = record(value);
  return {
    calendar_id: text(row.calendar_id),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    site_name: text(row.site_name),
    import_url: maybeText(row.import_url),
    active: row.active === true,
    last_read_at: maybeText(row.last_read_at),
    last_read_ok:
      row.last_read_ok === null || row.last_read_ok === undefined
        ? null
        : row.last_read_ok === true,
    last_error: maybeText(row.last_error),
    version: whole(row.version),
    holds: whole(row.holds),
  };
}

export function calendarOf(value: unknown): StayCalendar {
  const row = record(value);
  return {
    from: text(row.from),
    days: whole(row.days),
    today: text(row.today),
    units: list(row.units).map((entry) => {
      const unit = record(entry);
      return {
        unit_id: text(unit.unit_id),
        unit_number: text(unit.unit_number),
        unit_type: text(unit.unit_type),
        status: text(unit.status),
        for_rent: unit.for_rent !== false,
        monthly_rent_usd_cents: maybeWhole(unit.monthly_rent_usd_cents),
        bookings: list(unit.bookings).map((item) => {
          const booking = record(item);
          return {
            booking_id: text(booking.booking_id),
            booking_number: text(booking.booking_number),
            guest_name: text(booking.guest_name),
            status: oneOf(STATUSES, booking.status),
            source: oneOf(SOURCES, booking.source),
            check_in_on: text(booking.check_in_on),
            check_out_on: text(booking.check_out_on),
            paid: booking.paid === true,
          };
        }),
        leases: list(unit.leases).map((item) => {
          const lease = record(item);
          return {
            lease_id: text(lease.lease_id),
            start_date: text(lease.start_date),
            end_date: text(lease.end_date),
          };
        }),
        reserved: unit.reserved === true,
        site_holds: list(unit.site_holds ?? []).map(holdOf),
      };
    }),
  };
}

function depositOf(value: unknown): StayDeposit | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return {
    deposit_id: text(row.deposit_id),
    kind: oneOf(["CASH", "CARD_HOLD"] as const, row.kind),
    amount_usd_cents: whole(row.amount_usd_cents),
    hold_reference: maybeText(row.hold_reference),
    card_last4: maybeText(row.card_last4),
    status: oneOf(["HELD", "RETURNED", "KEPT"] as const, row.status),
    kept_usd_cents: whole(row.kept_usd_cents),
    taken_at: text(row.taken_at),
    ended_at: maybeText(row.ended_at),
  };
}

function roomCheckOf(value: unknown): RoomCheck | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return {
    task_id: text(row.task_id),
    task_on: text(row.task_on),
    status: oneOf(["TO_DO", "DONE", "SKIPPED"] as const, row.status),
    note: maybeText(row.note),
    done_at: maybeText(row.done_at),
  };
}

function problemOf(value: unknown): StayProblem {
  const row = record(value);
  return {
    report_id: text(row.report_id),
    report_number: text(row.report_number),
    description: text(row.description),
    type_name_en: text(row.type_name_en),
    type_name_kh: maybeText(row.type_name_kh),
    urgent: row.urgent === true,
    status: text(row.status),
  };
}

function decisionOf(value: unknown): DamageDecision | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return {
    outcome: oneOf(["CHARGE", "NO_CHARGE"] as const, row.outcome),
    damage_id: maybeText(row.damage_id),
    note: maybeText(row.note),
    decided_at: text(row.decided_at),
  };
}

function damageOf(value: unknown): StayDamage {
  const row = record(value);
  return {
    damage_id: text(row.damage_id),
    description: text(row.description),
    amount_usd_cents: whole(row.amount_usd_cents),
    status: oneOf(["WAITING", "APPROVED", "REFUSED"] as const, row.status),
    decided_at: maybeText(row.decided_at),
    decision_note: maybeText(row.decision_note),
    from_deposit_usd_cents: whole(row.from_deposit_usd_cents),
    invoice_id: maybeText(row.invoice_id),
    invoice_number: maybeText(row.invoice_number),
  };
}

function refundOf(row: Record<string, unknown>): StayRefund {
  return {
    credits: list(row.credits).map((entry) => {
      const credit = record(entry);
      return {
        credit_id: text(credit.credit_id),
        left_usd_cents: whole(credit.left_usd_cents),
      };
    }),
    left_usd_cents: whole(row.left_usd_cents),
    waiting_usd_cents: whole(row.waiting_usd_cents),
    refunded_usd_cents: whole(row.refunded_usd_cents),
  };
}

export function bookingOf(value: unknown): Booking {
  const row = record(value);
  const invoice =
    row.invoice === null || row.invoice === undefined
      ? null
      : record(row.invoice);
  return {
    booking_id: text(row.booking_id),
    booking_number: text(row.booking_number),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    unit_type: text(row.unit_type),
    customer_id: text(row.customer_id),
    guest_name: text(row.guest_name),
    guest_phone: maybeText(row.guest_phone),
    guest_count: whole(row.guest_count),
    check_in_on: text(row.check_in_on),
    check_out_on: text(row.check_out_on),
    nights: whole(row.nights),
    source: oneOf(SOURCES, row.source),
    site_name: maybeText(row.site_name),
    site_reference: maybeText(row.site_reference),
    note: maybeText(row.note),
    status: oneOf(STATUSES, row.status),
    total_usd_cents: whole(row.total_usd_cents),
    version: whole(row.version),
    created_at: text(row.created_at),
    lines: list(row.lines).map(lineOf),
    history: list(row.history).map((entry) => {
      const event = record(entry);
      return {
        kind: text(event.kind),
        occurred_at: text(event.occurred_at),
        note: maybeText(event.note),
        ...(isObject(event.details) ? { details: event.details } : {}),
      };
    }),
    unit_status: text(row.unit_status),
    guest_has_id: row.guest_has_id === true,
    payment: oneOf(PAYMENTS, row.payment),
    invoice:
      invoice === null
        ? null
        : {
            invoice_id: text(invoice.invoice_id),
            invoice_number: text(invoice.invoice_number),
            status: text(invoice.status),
            total_usd_cents: whole(invoice.total_usd_cents),
            due_usd_cents: whole(
              invoice.due_usd_cents ?? invoice.total_usd_cents,
            ),
          },
    deposit: depositOf(row.deposit),
    room_check: roomCheckOf(row.room_check),
    damages: list(row.damages).map(damageOf),
    problems: list(row.problems ?? []).map(problemOf),
    damage_decision: decisionOf(row.damage_decision),
    damage_due: row.damage_due === true,
    extra_invoices: list(row.extra_invoices).map((entry) => {
      const extra = record(entry);
      return {
        invoice_id: text(extra.invoice_id),
        invoice_number: text(extra.invoice_number),
        status: text(extra.status),
        kind: oneOf(EXTRA_KINDS, extra.kind),
        total_usd_cents: whole(extra.total_usd_cents),
      };
    }),
    early_check_in: row.early_check_in === true,
    late_check_out: row.late_check_out === true,
    fee_usd_cents: whole(row.fee_usd_cents),
    check_in_time: whole(row.check_in_time),
    check_out_time: whole(row.check_out_time),
    late_check_out_until: whole(row.late_check_out_until),
    cleans: list(row.cleans).map((entry) => {
      const clean = record(entry);
      return {
        task_id: text(clean.task_id),
        task_on: text(clean.task_on),
        status: oneOf(TASK_STATUSES, clean.status),
        note: maybeText(clean.note),
      };
    }),
    free_cancel_until: text(row.free_cancel_until),
    cancel_reason: maybeText(row.cancel_reason),
    paid_usd_cents: whole(row.paid_usd_cents),
    cancellation:
      row.cancellation === null || row.cancellation === undefined
        ? null
        : cancellationOf(record(row.cancellation)),
    credit:
      row.credit === null || row.credit === undefined
        ? null
        : creditOf(record(row.credit)),
    refund:
      row.refund === null || row.refund === undefined
        ? null
        : refundOf(record(row.refund)),
    lease_off_usd_cents: whole(row.lease_off_usd_cents ?? 0),
    lease_offer:
      row.lease_offer === null || row.lease_offer === undefined
        ? null
        : leaseOfferOf(record(row.lease_offer)),
    lease_drafts: list(row.lease_drafts ?? []).map((entry) => {
      const draft = record(entry);
      return {
        lease_id: text(draft.lease_id),
        unit_number: text(draft.unit_number),
        start_date: maybeText(draft.start_date),
        monthly_rent_usd_cents: whole(draft.monthly_rent_usd_cents),
      };
    }),
    returning_guest: row.returning_guest === true,
    problem_guest: row.problem_guest === true,
    review_asked_at: maybeText(row.review_asked_at),
  };
}

function guestOf(value: unknown): GuestHistory {
  const row = record(value);
  return {
    customer_id: text(row.customer_id),
    legal_name: text(row.legal_name),
    phone_number: maybeText(row.phone_number),
    stays: list(row.stays).map((entry) => {
      const stay = record(entry);
      return {
        booking_id: text(stay.booking_id),
        booking_number: text(stay.booking_number),
        unit_number: text(stay.unit_number),
        check_in_on: text(stay.check_in_on),
        check_out_on: text(stay.check_out_on),
        status: oneOf(STATUSES, stay.status),
        source: oneOf(SOURCES, stay.source),
        site_name: maybeText(stay.site_name),
        total_usd_cents: whole(stay.total_usd_cents),
      };
    }),
    stays_done: whole(row.stays_done),
    nights_done: whole(row.nights_done),
    spent_usd_cents: whole(row.spent_usd_cents),
    returning: row.returning === true,
    problem_guest: row.problem_guest === true,
    notes: list(row.notes).map((entry) => {
      const note = record(entry);
      return {
        note: text(note.note),
        problem_guest: note.problem_guest === true,
        created_at: text(note.created_at),
        booking_number: maybeText(note.booking_number),
      };
    }),
    thank_you_usd_cents: whole(row.thank_you_usd_cents ?? 0),
  };
}

function quoteOf(value: unknown): StayQuote {
  const row = record(value);
  return {
    quote_id: text(row.quote_id),
    quote_number: text(row.quote_number),
    unit_id: maybeText(row.unit_id),
    unit_number: maybeText(row.unit_number),
    unit_type: text(row.unit_type),
    guest_name: maybeText(row.guest_name),
    guest_contact: maybeText(row.guest_contact),
    guest_count: whole(row.guest_count),
    check_in_on: text(row.check_in_on),
    check_out_on: text(row.check_out_on),
    nights: whole(row.nights),
    total_usd_cents: whole(row.total_usd_cents),
    lines: list(row.lines).map(lineOf),
    made_on: text(row.made_on),
    check_in_time: whole(row.check_in_time),
    check_out_time: whole(row.check_out_time),
    deposit_usd_cents: whole(row.deposit_usd_cents),
    month_only_usd_cents: maybeWhole(row.month_only_usd_cents),
    monthly_rent_usd_cents: maybeWhole(row.monthly_rent_usd_cents),
  };
}

function reportOf(value: unknown): WeekReport {
  const row = record(value);
  const totals = record(row.totals);
  const cancels = record(row.cancellations);
  return {
    from: text(row.from),
    to: text(row.to),
    so_far: row.so_far === true,
    base_occupancy_points: whole(row.base_occupancy_points),
    change_over_usd_cents: whole(row.change_over_usd_cents),
    linen_usd_cents: whole(row.linen_usd_cents),
    units: list(row.units).map((entry) => {
      const unit = record(entry);
      return {
        unit_id: text(unit.unit_id),
        unit_number: text(unit.unit_number),
        nights: whole(unit.nights),
        income_usd_cents: whole(unit.income_usd_cents),
        site_fees_usd_cents: whole(unit.site_fees_usd_cents),
        cleaning_usd_cents: whole(unit.cleaning_usd_cents),
        net_usd_cents: whole(unit.net_usd_cents),
      };
    }),
    totals: {
      units: whole(totals.units),
      unit_nights: whole(totals.unit_nights),
      nights: whole(totals.nights),
      income_usd_cents: whole(totals.income_usd_cents),
      site_fees_usd_cents: whole(totals.site_fees_usd_cents),
      cleaning_usd_cents: whole(totals.cleaning_usd_cents),
      net_usd_cents: whole(totals.net_usd_cents),
      occupancy_points: whole(totals.occupancy_points),
    },
    leases: list(row.leases).map((entry) => {
      const lease = record(entry);
      return {
        booking_id: text(lease.booking_id),
        booking_number: text(lease.booking_number),
        guest_name: text(lease.guest_name),
        lease_id: text(lease.lease_id),
        lease_unit_number: text(lease.lease_unit_number),
        off_usd_cents: whole(lease.off_usd_cents),
      };
    }),
    damages: list(row.damages).map((entry) => {
      const damage = record(entry);
      return {
        damage_id: text(damage.damage_id),
        booking_id: text(damage.booking_id),
        booking_number: text(damage.booking_number),
        unit_number: text(damage.unit_number),
        description: text(damage.description),
        amount_usd_cents: whole(damage.amount_usd_cents),
        status: text(damage.status),
      };
    }),
    complaints: list(row.complaints).map((entry) => {
      const complaint = record(entry);
      return {
        complaint_id: text(complaint.complaint_id),
        noted_on: text(complaint.noted_on),
        unit_number: maybeText(complaint.unit_number),
        what: text(complaint.what),
      };
    }),
    sources: list(row.sources).map((entry) => {
      const source = record(entry);
      return {
        source: oneOf(SOURCES, source.source),
        site_name: maybeText(source.site_name),
        stays: whole(source.stays),
      };
    }),
    cancellations: {
      count: whole(cancels.count),
      kept_usd_cents: whole(cancels.kept_usd_cents),
    },
  };
}

function moveUnitOf(value: unknown): MoveUnit {
  const row = record(value);
  return {
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    floor: text(row.floor),
    unit_type: text(row.unit_type),
    same_type: row.same_type === true,
    monthly_rent_usd_cents: maybeWhole(row.monthly_rent_usd_cents),
  };
}

function leaseOfferOf(row: Record<string, unknown>): StayLeaseOffer {
  return {
    lease_id: text(row.lease_id),
    off_usd_cents: whole(row.off_usd_cents),
    lease_status: text(row.lease_status),
    start_date: maybeText(row.start_date),
    unit_number: text(row.unit_number),
  };
}

function cancellationOf(row: Record<string, unknown>): StayCancellation {
  return {
    kind: oneOf(["CANCELLED", "NO_SHOW"] as const, row.kind),
    free: row.free === true,
    paid_usd_cents: whole(row.paid_usd_cents),
    back_usd_cents: whole(row.back_usd_cents),
    kept_usd_cents: whole(row.kept_usd_cents),
  };
}

function creditOf(row: Record<string, unknown>): StayCredit {
  const ended =
    row.ended === null || row.ended === undefined ? null : record(row.ended);
  return {
    amount_usd_cents: whole(row.amount_usd_cents),
    use_by: text(row.use_by),
    note: text(row.note),
    left_usd_cents:
      row.left_usd_cents === undefined
        ? whole(row.amount_usd_cents)
        : whole(row.left_usd_cents),
    ended:
      ended === null
        ? null
        : {
            left_usd_cents: whole(ended.left_usd_cents),
            invoice_id: maybeText(ended.invoice_id),
            invoice_number: maybeText(ended.invoice_number),
            at: text(ended.at),
          },
  };
}

function creditDueOf(row: Record<string, unknown>): CreditDue {
  return {
    booking_id: text(row.booking_id),
    booking_number: text(row.booking_number),
    guest_name: text(row.guest_name),
    use_by: text(row.use_by),
    left_usd_cents: whole(row.left_usd_cents),
  };
}

function damageDueOf(row: Record<string, unknown>): DamageDue {
  return {
    booking_id: text(row.booking_id),
    booking_number: text(row.booking_number),
    guest_name: text(row.guest_name),
    unit_number: text(row.unit_number),
    problem_count: whole(row.problem_count),
  };
}

const EXTRA_KINDS = ["EXTEND", "EARLY_CHECK_IN", "LATE_CHECK_OUT"] as const;
const TASK_STATUSES = ["TO_DO", "DONE", "SKIPPED"] as const;
const TASK_KINDS = ["DAILY_CLEAN", "CHANGE_OVER", "ROOM_CHECK"] as const;

export function cleaningOf(value: unknown): CleaningDay {
  const row = record(value);
  return {
    day: text(row.day),
    today: text(row.today),
    tasks: list(row.tasks).map((entry) => {
      const task = record(entry);
      return {
        task_id: text(task.task_id),
        kind: oneOf(TASK_KINDS, task.kind),
        task_on: text(task.task_on),
        status: oneOf(TASK_STATUSES, task.status),
        note: maybeText(task.note),
        done_at: maybeText(task.done_at),
        unit_id: text(task.unit_id),
        unit_number: text(task.unit_number),
        booking_id: maybeText(task.booking_id),
        booking_number: maybeText(task.booking_number),
        guest_name: maybeText(task.guest_name),
        late: task.late === true,
      };
    }),
  };
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/short-stays`;
}

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    ...(body === null ? {} : { body: JSON.stringify(body) }),
  };
}

export const shortStaysApi: ShortStaysApi = {
  calendar: async (propertyId, from, days) =>
    calendarOf(
      await request(
        `${base(propertyId)}/calendar?from=${encodeURIComponent(from)}&days=${String(days)}`,
      ),
    ),
  price: async (propertyId, unitId, checkIn, checkOut) =>
    priceOf(
      await request(
        `${base(propertyId)}/price?unit_id=${encodeURIComponent(unitId)}` +
          `&check_in_on=${encodeURIComponent(checkIn)}` +
          `&check_out_on=${encodeURIComponent(checkOut)}`,
      ),
    ),
  list: async (propertyId) =>
    list(await request(`${base(propertyId)}/bookings`)).map(bookingOf),
  get: async (propertyId, bookingId) =>
    bookingOf(
      await request(
        `${base(propertyId)}/bookings/${encodeURIComponent(bookingId)}`,
      ),
    ),
  book: async (propertyId, booking) =>
    bookingOf(await request(`${base(propertyId)}/bookings`, post(booking))),
  step: async (propertyId, bookingId, step, body) =>
    bookingOf(
      await request(
        `${base(propertyId)}/bookings/${encodeURIComponent(bookingId)}/${step}`,
        post(body),
      ),
    ),
  moveUnits: async (propertyId, bookingId) =>
    list(
      record(
        await request(
          `${base(propertyId)}/bookings/${encodeURIComponent(bookingId)}/units`,
        ),
      ).units,
    ).map(moveUnitOf),
  decide: async (propertyId, damageId, decision) =>
    bookingOf(
      await request(
        `${base(propertyId)}/damages/${encodeURIComponent(damageId)}/decision`,
        post(decision),
      ),
    ),
  cleaning: async (propertyId, day) =>
    cleaningOf(
      await request(
        `${base(propertyId)}/housekeeping?day=${encodeURIComponent(day)}`,
      ),
    ),
  finishTask: async (propertyId, taskId, finish) =>
    cleaningOf(
      await request(
        `${base(propertyId)}/housekeeping/${encodeURIComponent(taskId)}`,
        post(finish),
      ),
    ),
  siteCalendars: async (propertyId) =>
    list(await request(`${base(propertyId)}/site-calendars`)).map(
      siteCalendarOf,
    ),
  saveSiteCalendar: async (propertyId, link) =>
    siteCalendarOf(
      await request(`${base(propertyId)}/site-calendars`, post(link)),
    ),
  guest: async (propertyId, customerId) =>
    guestOf(
      await request(
        `${base(propertyId)}/guests/${encodeURIComponent(customerId)}`,
      ),
    ),
  addGuestNote: async (propertyId, customerId, note) =>
    guestOf(
      await request(
        `${base(propertyId)}/guests/${encodeURIComponent(customerId)}/notes`,
        post(note),
      ),
    ),
  quotes: async (propertyId) =>
    list(await request(`${base(propertyId)}/quotes`)).map(quoteOf),
  quote: async (propertyId, quote) =>
    quoteOf(await request(`${base(propertyId)}/quotes`, post(quote))),
  weekReport: async (propertyId, from) =>
    reportOf(
      await request(
        `${base(propertyId)}/report?from=${encodeURIComponent(from)}`,
      ),
    ),
  complaint: async (propertyId, complaint) => {
    await request(`${base(propertyId)}/complaints`, post(complaint));
  },
  creditsDue: async (propertyId) =>
    list(await request(`${base(propertyId)}/credits-due`)).map((row) =>
      creditDueOf(record(row)),
    ),
  damageDue: async (propertyId) =>
    list(await request(`${base(propertyId)}/damage-due`)).map((row) =>
      damageDueOf(record(row)),
    ),
  problemTypes: async (propertyId) =>
    choicesOf(
      await request(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/problem-report-choices`,
      ),
    ).types,
  refundMethods: async (propertyId) =>
    list(
      await request(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/refund-methods`,
        { method: "GET", headers: { "X-Financial-Property-ID": propertyId } },
      ),
    ).flatMap((row) => {
      const method = record(row);
      return method.active === true &&
        typeof method.id === "string" &&
        typeof method.display_name === "string"
        ? [{ id: method.id, name: method.display_name }]
        : [];
    }),
  refund: async (propertyId, refund, key) => {
    const init = post({
      currency: "USD",
      source_type: "CREDIT",
      source_id: refund.credit_id,
      amount_usd_cents: refund.amount_usd_cents,
      reason: refund.reason,
      refund_method_id: refund.refund_method_id,
      reference_note: refund.reference_note,
    });
    await request("/api/v1/refund-drafts", {
      ...init,
      headers: {
        ...(init.headers as Record<string, string>),
        "Idempotency-Key": key,
        "X-Financial-Property-ID": propertyId,
      },
    });
  },
};

/** Adds days to an ISO day ("2026-11-04" + 3 → "2026-11-07"), in UTC so no clock shifts it. */
export function addDays(day: string, days: number): string {
  const moment = new Date(`${day}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

/** Whole days from one ISO day to another. */
export function daysBetween(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) /
      86400000,
  );
}
