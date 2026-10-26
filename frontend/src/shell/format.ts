// V1-058 R2: how the rebuilt screens show money, dates and times (approved 2026-10-12):
// US dollars from whole cents, dd/mm/yyyy, 24-hour times in Phnom Penh.

const dollars = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 45000 cents → "$450.00". */
export function usdFromCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${dollars.format(Math.abs(cents) / 100)}`;
}

/** "2026-10-24" → "24/10/2026"; any other text is shown as it is. */
export function dayText(value: string | null): string {
  if (value === null) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (match === null) return value;
  const [, year = "", month = "", day = ""] = match;
  return `${day}/${month}/${year}`;
}

/** A moment as "24/10/2026 12:30" in Phnom Penh. */
export function momentText(value: string | null): string {
  if (value === null) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: string) =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("day")}/${part("month")}/${part("year")} ${part("hour")}:${part("minute")}`;
}

/** Today in Phnom Penh as "2026-10-24", for comparing with Lease and Reservation dates. */
export function todayInPhnomPenh(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).formatToParts(now);
  const part = (type: string) =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}
