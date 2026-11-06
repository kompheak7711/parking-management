// Telegram bots step 2c (DL-128, API-TG-001): Office › Telegram, the tabs Linked tenants and
// Telegram health; step 2d part 2 (DL-170): the tabs Contact office and FAQ. The server checks
// every right again; this client only reads and sends. No bot key is ever read or shown.

export class TelegramError extends Error {
  /** The HTTP status, or null when the server could not be reached or answered badly:
   * 403 no right, 404 not found, 409 already done, 422 refused. */
  constructor(readonly status: number | null = null) {
    super("The Telegram page could not be read or saved.");
    this.name = "TelegramError";
  }
}

export interface LinkedTenant {
  id: string;
  telegram_user_id: number;
  phone: string | null;
  name: string | null;
  unit_number: string | null;
  lease_end_date: string | null;
  linked_at: string;
}

export interface LinkTry {
  telegram_user_id: number;
  phone: string | null;
  typed_name: string | null;
  typed_unit: string | null;
  tries: number;
  tries_left: number;
  blocked_until: string | null;
  last_at: string;
}

export interface EndedLink {
  id: string;
  telegram_user_id: number;
  name: string | null;
  unit_number: string | null;
  linked_at: string;
  ended_at: string;
  /** LEASE_ENDED, REMOVED or another code from the server. */
  reason: string;
  note: string | null;
}

export interface LinksPage {
  linked: LinkedTenant[];
  tries: LinkTry[];
  ended: EndedLink[];
  rules: { tries: number; block_hours: number; keep_days: number };
}

export interface BotHealth {
  code: string;
  name: string;
  last_in: string | null;
  last_out: string | null;
  failing: boolean;
}

export interface WaitingMessage {
  id: string;
  bot: string;
  text_code: string;
  created_at: string;
  tries: number;
  last_error: string | null;
  last_try_at: string | null;
  status: "WAITING" | "GAVE_UP";
  retried: boolean;
  /** The tenant and Unit of a Tenant bot chat; null for anyone else. */
  to: { name: string | null; unit_number: string | null } | null;
}

export interface PullRun {
  started_at: string;
  outcome: string;
  error_code: string | null;
  items_saved: number;
}

export interface HealthPage {
  last_pull_at: string | null;
  last_pull_outcome: string | null;
  last_pull_error: string | null;
  outbox_waiting: number;
  outbox_failing_12h: number;
  relay_dropped: number;
  bots: BotHealth[];
  outbox: WaitingMessage[];
  pulls: PullRun[];
}

export interface ContactAnswer {
  how: "TELEGRAM" | "PHONE";
  text: string;
  at: string;
  by: string | null;
}

export interface ContactMessage {
  id: string;
  /** TENANT or CUSTOMER. */
  bot: string;
  /** The linked tenant's name, else the person's Telegram name. */
  name: string | null;
  unit_number: string | null;
  phone: string | null;
  message: string;
  received_at: string;
  answer: ContactAnswer | null;
}

export interface ContactPage {
  waiting: ContactMessage[];
  answered: ContactMessage[];
}

export type FaqBots = "BOTH" | "CUSTOMER" | "TENANT" | "HIDDEN";
export const FAQ_BOTS: readonly FaqBots[] = [
  "BOTH",
  "TENANT",
  "CUSTOMER",
  "HIDDEN",
];

export interface FaqWords {
  for_bots: FaqBots;
  question_en: string;
  answer_en: string;
  question_km: string;
  answer_km: string;
}

export interface FaqApproved extends FaqWords {
  version_id: string;
  version_number: number;
  approved_by: string | null;
  approved_at: string;
}

export interface FaqWaiting extends FaqWords {
  version_id: string;
  proposed_by: string | null;
  proposed_at: string;
}

export interface FaqQuestion {
  id: string;
  number: number;
  current: FaqApproved | null;
  pending: FaqWaiting | null;
}

export interface FaqPage {
  questions: FaqQuestion[];
  /** The person is the Owner: a save is used at once and Approve shows. */
  owner: boolean;
  can_edit: boolean;
}

export interface FaqSaved {
  number: number;
  approved: boolean;
  page: FaqPage;
}

/** One inquiry from the Customer bot (step 3a, DL-171). */
export interface VisitInquiry {
  id: string;
  number: string;
  received_at: string;
  name: string;
  phone: string;
  /** TELEGRAM, EMAIL, PHONE or WHATSAPP. */
  contact_by: string;
  email: string | null;
  language: string;
  unit_type: string;
  unit_type_en: string | null;
  unit_type_km: string | null;
  visit_on: string | null;
  /** MORNING or AFTERNOON. */
  visit_part: string | null;
  /** "YYYY-MM", or null for Later. */
  move_in_month: string | null;
  note: string | null;
}

export interface VisitRequest extends VisitInquiry {
  /** NEW, CONTACTED, VISIT_BOOKED, VISITED, NO_SHOW, CLOSED or SPAM (step 3b, DL-172). */
  status: string;
  /** Who has the request (Take or Give to), or null. */
  staff_id: string | null;
  staff: string | null;
  mine: boolean;
  /** Working minutes since it arrived (Monday to Saturday, 07:00 to 17:00). */
  waiting_minutes: number;
  /** New, nobody took it, more than 2 working hours. */
  late: boolean;
  no_answer_days: number;
  calls: number;
  /** The visit booked, local time "YYYY-MM-DDTHH:MM", or null. */
  visit_local: string | null;
  visit_staff: string | null;
  /** Why it closed (PRICE ... CANCELLED), or null. */
  reason: string | null;
  close_note: string | null;
  /** CONFIRMATION and REMINDER still to send by hand (not a Telegram customer). */
  to_send: string[];
  /** The Reservation the request became (step 3c, DL-173), or null. */
  reservation_id: string | null;
  /** A Manager blocked this Telegram account. */
  blocked: boolean;
  /** The name, phone and email were removed after 12 months with no activity. */
  removed: boolean;
  /** Later inquiries of the same person or phone, which keep this request's place. */
  joined: VisitInquiry[];
}

export interface VisitWorker {
  id: string;
  name: string;
}

export interface VisitRequestsPage {
  requests: VisitRequest[];
  today: string;
  /** The Property's address, for the words sent by hand. */
  address: string;
  /** The people who work Visit requests (Give to, Book a visit). */
  workers: VisitWorker[];
  me: string;
  can_work: boolean;
  can_manage: boolean;
  /** This month, for Managers and the Owner only (null for Staff). */
  month: VisitMonth | null;
}

export interface VisitCount {
  code: string;
  count: number;
}

export interface VisitMonth {
  /** "YYYY-MM". */
  month: string;
  new: number;
  joined: number;
  /** Requests with each step this month: VISIT_BOOKED, VISITED, NO_SHOW, RESERVED, CLOSED, SPAM. */
  steps: Record<string, number>;
  reasons: VisitCount[];
  sources: VisitCount[];
}

export interface VisitHistoryStep {
  at: string;
  kind: string;
  by: string | null;
  staff: string | null;
  answered: boolean | null;
  visit_at: string | null;
  reason: string | null;
  what: string | null;
  note: string | null;
  sent_by_bot: boolean;
}

export interface VisitRequestDetail extends VisitRequest {
  history: VisitHistoryStep[];
}

export type VisitAction =
  | "take"
  | "give"
  | "call"
  | "book"
  | "visited"
  | "no-show"
  | "close"
  | "reopen"
  | "spam"
  | "sent"
  | "reserve"
  | "block"
  | "unblock";

export interface VisitStepBody {
  staff_id?: string;
  answered?: boolean;
  /** Local time "YYYY-MM-DDTHH:MM". */
  visit_at?: string;
  reason?: string;
  what?: "CONFIRMATION" | "REMINDER";
  note?: string;
  reservation_id?: string;
}

export interface VisitStepDone {
  request: VisitRequestDetail;
  page: VisitRequestsPage;
}

export interface TelegramApi {
  links: (propertyId: string) => Promise<LinksPage>;
  /** Removes a link with a reason and answers the page again. */
  removeLink: (
    propertyId: string,
    linkId: string,
    reason: string,
  ) => Promise<LinksPage>;
  health: (propertyId: string) => Promise<HealthPage>;
  /** Sends a message the app gave up on once more and answers the page again. */
  retry: (propertyId: string, messageId: string) => Promise<HealthPage>;
  contact: (propertyId: string) => Promise<ContactPage>;
  /** Answers one message, once, and answers the page again. */
  answer: (
    propertyId: string,
    messageId: string,
    how: "TELEGRAM" | "PHONE",
    text: string,
  ) => Promise<ContactPage>;
  faq: (propertyId: string) => Promise<FaqPage>;
  /** Saves a new version of a question (a new question when questionId is null). */
  saveFaq: (
    propertyId: string,
    questionId: string | null,
    words: FaqWords,
  ) => Promise<FaqSaved>;
  /** The Owner approves the version waiting and answers the page again. */
  approveFaq: (propertyId: string, versionId: string) => Promise<FaqPage>;
  /** DL-179: loads the 15 starter questions into an empty FAQ, each waiting for the Owner. */
  loadFaqStarter: (propertyId: string) => Promise<FaqPage>;
  visitRequests: (propertyId: string) => Promise<VisitRequestsPage>;
  visitRequest: (
    propertyId: string,
    requestId: string,
  ) => Promise<VisitRequestDetail>;
  /** One step on a request; answers the request and the list again. */
  visitStep: (
    propertyId: string,
    requestId: string,
    action: VisitAction,
    body: VisitStepBody,
  ) => Promise<VisitStepDone>;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new TelegramError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new TelegramError();
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new TelegramError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new TelegramError();
  return value;
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new TelegramError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new TelegramError();
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
    throw new TelegramError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new TelegramError(response.status);
  if (!isObject(payload) || !("data" in payload)) throw new TelegramError();
  return payload.data;
}

function post(body?: unknown): RequestInit {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/telegram`;
}

export function linksPageOf(value: unknown): LinksPage {
  const page = record(value);
  const rules = record(page.rules);
  return {
    linked: list(page.linked).map((item) => {
      const row = record(item);
      return {
        id: text(row.id),
        telegram_user_id: whole(row.telegram_user_id),
        phone: maybeText(row.phone),
        name: maybeText(row.name),
        unit_number: maybeText(row.unit_number),
        lease_end_date: maybeText(row.lease_end_date),
        linked_at: text(row.linked_at),
      };
    }),
    tries: list(page.tries).map((item) => {
      const row = record(item);
      return {
        telegram_user_id: whole(row.telegram_user_id),
        phone: maybeText(row.phone),
        typed_name: maybeText(row.typed_name),
        typed_unit: maybeText(row.typed_unit),
        tries: whole(row.tries),
        tries_left: whole(row.tries_left),
        blocked_until: maybeText(row.blocked_until),
        last_at: text(row.last_at),
      };
    }),
    ended: list(page.ended).map((item) => {
      const row = record(item);
      return {
        id: text(row.id),
        telegram_user_id: whole(row.telegram_user_id),
        name: maybeText(row.name),
        unit_number: maybeText(row.unit_number),
        linked_at: text(row.linked_at),
        ended_at: text(row.ended_at),
        reason: text(row.reason),
        note: maybeText(row.note),
      };
    }),
    rules: {
      tries: whole(rules.tries),
      block_hours: whole(rules.block_hours),
      keep_days: whole(rules.keep_days),
    },
  };
}

export function healthPageOf(value: unknown): HealthPage {
  const page = record(value);
  return {
    last_pull_at: maybeText(page.last_pull_at),
    last_pull_outcome: maybeText(page.last_pull_outcome),
    last_pull_error: maybeText(page.last_pull_error),
    outbox_waiting: whole(page.outbox_waiting),
    outbox_failing_12h: whole(page.outbox_failing_12h ?? 0),
    relay_dropped: whole(page.relay_dropped ?? 0),
    bots: list(page.bots).map((item) => {
      const row = record(item);
      return {
        code: text(row.code),
        name: text(row.name),
        last_in: maybeText(row.last_in),
        last_out: maybeText(row.last_out),
        failing: row.failing === true,
      };
    }),
    outbox: list(page.outbox).map((item) => {
      const row = record(item);
      const to =
        row.to === null || row.to === undefined ? null : record(row.to);
      return {
        id: text(row.id),
        bot: text(row.bot),
        text_code: text(row.text_code),
        created_at: text(row.created_at),
        tries: whole(row.tries ?? 0),
        last_error: maybeText(row.last_error),
        last_try_at: maybeText(row.last_try_at),
        status: row.status === "GAVE_UP" ? "GAVE_UP" : "WAITING",
        retried: row.retried === true,
        to:
          to === null
            ? null
            : {
                name: maybeText(to.name),
                unit_number: maybeText(to.unit_number),
              },
      };
    }),
    pulls: list(page.pulls).map((item) => {
      const row = record(item);
      return {
        started_at: text(row.started_at),
        outcome: text(row.outcome),
        error_code: maybeText(row.error_code),
        items_saved: whole(row.items_saved ?? 0),
      };
    }),
  };
}

function contactMessageOf(value: unknown): ContactMessage {
  const row = record(value);
  const answer =
    row.answer === null || row.answer === undefined ? null : record(row.answer);
  return {
    id: text(row.id),
    bot: text(row.bot),
    name: maybeText(row.name),
    unit_number: maybeText(row.unit_number),
    phone: maybeText(row.phone),
    message: text(row.message),
    received_at: text(row.received_at),
    answer:
      answer === null
        ? null
        : {
            how: answer.how === "PHONE" ? "PHONE" : "TELEGRAM",
            text: text(answer.text),
            at: text(answer.at),
            by: maybeText(answer.by),
          },
  };
}

export function contactPageOf(value: unknown): ContactPage {
  const page = record(value);
  return {
    waiting: list(page.waiting).map(contactMessageOf),
    answered: list(page.answered).map(contactMessageOf),
  };
}

function bots(value: unknown): FaqBots {
  const found = FAQ_BOTS.find((code) => code === value);
  if (found === undefined) throw new TelegramError();
  return found;
}

function wordsOf(row: Record<string, unknown>): FaqWords {
  return {
    for_bots: bots(row.for_bots),
    question_en: text(row.question_en),
    answer_en: text(row.answer_en),
    question_km: text(row.question_km),
    answer_km: text(row.answer_km),
  };
}

export function faqPageOf(value: unknown): FaqPage {
  const page = record(value);
  return {
    owner: page.owner === true,
    can_edit: page.can_edit === true,
    questions: list(page.questions).map((item) => {
      const row = record(item);
      const current =
        row.current === null || row.current === undefined
          ? null
          : record(row.current);
      const pending =
        row.pending === null || row.pending === undefined
          ? null
          : record(row.pending);
      return {
        id: text(row.id),
        number: whole(row.number),
        current:
          current === null
            ? null
            : {
                ...wordsOf(current),
                version_id: text(current.version_id),
                version_number: whole(current.version_number),
                approved_by: maybeText(current.approved_by),
                approved_at: text(current.approved_at),
              },
        pending:
          pending === null
            ? null
            : {
                ...wordsOf(pending),
                version_id: text(pending.version_id),
                proposed_by: maybeText(pending.proposed_by),
                proposed_at: text(pending.proposed_at),
              },
      };
    }),
  };
}

function inquiryOf(value: unknown): VisitInquiry {
  const row = record(value);
  return {
    id: text(row.id),
    number: text(row.number),
    received_at: text(row.received_at),
    name: text(row.name),
    phone: text(row.phone),
    contact_by: text(row.contact_by),
    email: maybeText(row.email),
    language: text(row.language),
    unit_type: text(row.unit_type),
    unit_type_en: maybeText(row.unit_type_en),
    unit_type_km: maybeText(row.unit_type_km),
    visit_on: maybeText(row.visit_on),
    visit_part: maybeText(row.visit_part),
    move_in_month: maybeText(row.move_in_month),
    note: maybeText(row.note),
  };
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new TelegramError();
  return value;
}

function visitRequestOf(value: unknown): VisitRequest {
  const row = record(value);
  return {
    ...inquiryOf(row),
    status: text(row.status),
    staff_id: maybeText(row.staff_id),
    staff: maybeText(row.staff),
    mine: row.mine === true,
    waiting_minutes: whole(row.waiting_minutes),
    late: flag(row.late),
    no_answer_days: whole(row.no_answer_days),
    calls: whole(row.calls),
    visit_local: maybeText(row.visit_local),
    visit_staff: maybeText(row.visit_staff),
    reason: maybeText(row.reason),
    close_note: maybeText(row.close_note),
    to_send: list(row.to_send).map(text),
    reservation_id: maybeText(row.reservation_id),
    blocked: row.blocked === true,
    removed: row.removed === true,
    joined: list(row.joined).map(inquiryOf),
  };
}

function countsOf(value: unknown, key: string): VisitCount[] {
  return list(value).map((item) => {
    const row = record(item);
    return { code: text(row[key]), count: whole(row.count) };
  });
}

function monthOf(value: unknown): VisitMonth | null {
  if (value === null || value === undefined) return null;
  const month = record(value);
  const steps: Record<string, number> = {};
  for (const [kind, count] of Object.entries(record(month.steps)))
    steps[kind] = whole(count);
  return {
    month: text(month.month),
    new: whole(month.new),
    joined: whole(month.joined),
    steps,
    reasons: countsOf(month.reasons, "reason"),
    sources: countsOf(month.sources, "source"),
  };
}

export function visitRequestsPageOf(value: unknown): VisitRequestsPage {
  const page = record(value);
  return {
    today: text(page.today),
    address: text(page.address),
    me: text(page.me),
    can_work: flag(page.can_work),
    can_manage: flag(page.can_manage),
    month: monthOf(page.month),
    workers: list(page.workers).map((item) => {
      const worker = record(item);
      return { id: text(worker.id), name: text(worker.name) };
    }),
    requests: list(page.requests).map(visitRequestOf),
  };
}

export function visitRequestDetailOf(value: unknown): VisitRequestDetail {
  const row = record(value);
  return {
    ...visitRequestOf(row),
    history: list(row.history).map((item) => {
      const step = record(item);
      return {
        at: text(step.at),
        kind: text(step.kind),
        by: maybeText(step.by),
        staff: maybeText(step.staff),
        answered:
          step.answered === null || step.answered === undefined
            ? null
            : flag(step.answered),
        visit_at: maybeText(step.visit_at),
        reason: maybeText(step.reason),
        what: maybeText(step.what),
        note: maybeText(step.note),
        sent_by_bot: step.sent_by_bot === true,
      };
    }),
  };
}

function visitRoot(propertyId: string, requestId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/visit-requests/${encodeURIComponent(requestId)}`;
}

export const telegramApi: TelegramApi = {
  async links(propertyId) {
    return linksPageOf(await request(`${root(propertyId)}/links`));
  },
  async removeLink(propertyId, linkId, reason) {
    return linksPageOf(
      await request(
        `${root(propertyId)}/links/${encodeURIComponent(linkId)}/remove`,
        post({ reason }),
      ),
    );
  },
  async health(propertyId) {
    return healthPageOf(await request(`${root(propertyId)}/health`));
  },
  async retry(propertyId, messageId) {
    const answer = record(
      await request(
        `${root(propertyId)}/outbox/${encodeURIComponent(messageId)}/retry`,
        post(),
      ),
    );
    return healthPageOf(answer.health);
  },
  async contact(propertyId) {
    return contactPageOf(await request(`${root(propertyId)}/contact`));
  },
  async answer(propertyId, messageId, how, words) {
    return contactPageOf(
      await request(
        `${root(propertyId)}/contact/${encodeURIComponent(messageId)}/answer`,
        post({ how, answer: words }),
      ),
    );
  },
  async faq(propertyId) {
    return faqPageOf(await request(`${root(propertyId)}/faq`));
  },
  async saveFaq(propertyId, questionId, words) {
    const answer = record(
      await request(
        `${root(propertyId)}/faq`,
        post({ question_id: questionId, ...words }),
      ),
    );
    const saved = record(answer.saved);
    return {
      number: whole(saved.number),
      approved: saved.approved === true,
      page: faqPageOf(answer.faq),
    };
  },
  async approveFaq(propertyId, versionId) {
    const answer = record(
      await request(
        `${root(propertyId)}/faq/versions/${encodeURIComponent(versionId)}/approve`,
        post(),
      ),
    );
    return faqPageOf(answer.faq);
  },
  async loadFaqStarter(propertyId) {
    const answer = record(
      await request(`${root(propertyId)}/faq/starter`, post()),
    );
    return faqPageOf(answer.faq);
  },
  async visitRequests(propertyId) {
    return visitRequestsPageOf(
      await request(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/visit-requests`,
      ),
    );
  },
  async visitRequest(propertyId, requestId) {
    return visitRequestDetailOf(
      await request(visitRoot(propertyId, requestId)),
    );
  },
  async visitStep(propertyId, requestId, action, body) {
    const answer = record(
      await request(
        `${visitRoot(propertyId, requestId)}/${action}`,
        post(body),
      ),
    );
    return {
      request: visitRequestDetailOf(answer.request),
      page: visitRequestsPageOf(answer.page),
    };
  },
};
