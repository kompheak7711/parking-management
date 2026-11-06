# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 1 (owner 2026-11-04 "yes you merge it now", go for coding).

The short-stay design the owner approved on 03/11/2026 and 04/11/2026 (PRD JT5u9buNHVSLmyaLfefN86,
tech and DB plan CdRyrTaRnCpbZMEYSP4MbZ, mock-up v73 and round 35). Step 1 is the database only:

1. Nine new tables. ``short_stay_quotes`` (SQyy000n), ``short_stay_bookings`` (STyy000n) with
   their ``short_stay_price_lines`` (one set per price version: an extension prices the whole
   stay again) and ``short_stay_booking_events`` (the history, append-only),
   ``short_stay_deposits`` ($50 cash, or a $50 card hold kept as a reference only: a card number
   is never saved), ``housekeeping_tasks`` (daily cleaning for daily and weekly guests, the
   change-over and the room check), ``short_stay_damages`` (a Manager approves a charge),
   ``booking_site_calendars`` (free iCal links) and ``guest_notes``. Guests are Customers.
2. One Unit never has two bookings, or a booking and a signed Lease, on the same night. A
   booking holds the nights from the check-in day up to, not including, the check-out day; a
   Lease holds every day from its Start Date to its End Date (or its termination day). A new
   Lease over a booked night is refused: the booking wins (owner rule C, 03/11/2026).
3. The Unit status "Short stay" (SHORT_STAY), counted as occupied. Only a guest's check-in gives
   it and only the check-out takes it away.
4. The short-stay business rules in the new Settings area "Daily and weekly rent", with the
   owner's values. They show "Not used yet" until the next steps use them.
5. Rights in the new group "Daily and weekly rent": see, front desk, housekeeping, approve
   (damage charges and extra discounts, booking-site calendars) and give Credit after a late
   cancel. The Owner and the Manager have all five; Staff see, work the front desk and do
   housekeeping (the Owner can change this in Roles).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; every money value is the
owner's. Forward-only.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270531_310"
down_revision: str | None = "20270609_320"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "short-stays"
GROUP = ("SHORT_STAYS", "Daily and weekly rent", "ការជួលប្រចាំថ្ងៃ និងប្រចាំសប្ដាហ៍")
CAPABILITIES = (
    ("short_stays.read", "See short-stay bookings, the calendar and housekeeping"),
    (
        "short_stays.desk",
        "Make, change and cancel short-stay bookings, take payment and check guests in and out",
    ),
    ("short_stays.housekeeping", "Do and tick housekeeping tasks"),
    (
        "short_stays.approve",
        "Approve short-stay damage charges and extra discounts and set up booking-site calendars",
    ),
    ("short_stays.credit", "Turn money kept after a late cancel into Customer Credit"),
)
PERMISSIONS = (
    (
        "SHORT_STAYS_SEE",
        "See daily and weekly bookings",
        "មើលការកក់ប្រចាំថ្ងៃ និងប្រចាំសប្ដាហ៍",
        ("short_stays.read",),
    ),
    (
        "SHORT_STAYS_DESK",
        "Front desk: book, take payment, check in and out",
        "កន្លែងទទួលភ្ញៀវ៖ កក់ ទទួលប្រាក់ ចូល និងចេញ",
        ("short_stays.desk",),
    ),
    (
        "SHORT_STAYS_HOUSEKEEPING",
        "Housekeeping tasks",
        "ការងារសម្អាតបន្ទប់",
        ("short_stays.housekeeping",),
    ),
    (
        "SHORT_STAYS_APPROVE",
        "Approve damage charges and extra discounts",
        "អនុម័តថ្លៃខូចខាត និងការបញ្ចុះតម្លៃបន្ថែម",
        ("short_stays.approve",),
    ),
    (
        "SHORT_STAYS_CREDIT",
        "Give Credit after a late cancel",
        "ផ្ដល់ឥណទានក្រោយការលុបចោលយឺត",
        ("short_stays.credit",),
    ),
)
OWNER = (
    "short_stays.read",
    "short_stays.desk",
    "short_stays.housekeeping",
    "short_stays.approve",
    "short_stays.credit",
)
STAFF = ("short_stays.read", "short_stays.desk", "short_stays.housekeeping")
REASON = "Owner 2026-11-04 short stays phase 6: Daily and weekly rent rights"
SEED_REASON = "First value: the owner's daily and weekly rent rules (03/11 and 04/11/2026)"

SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'problem_reports.read', 'problem_reports.add']::text[]"
RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'TR_AUTO_CLOSE_DAYS' AND NEW.value NOT BETWEEN 1 AND 30)"

# code, unit, value, lowest, highest, English, Khmer
RULES = (
    (
        "SS_NIGHT_PERCENT",
        "PERCENT",
        30000,
        1,
        100000,
        "Night price: % of the monthly rent, then shared by the days below",
        "តម្លៃមួយយប់៖ % នៃថ្លៃជួលប្រចាំខែ រួចចែកនឹងចំនួនថ្ងៃខាងក្រោម",
    ),
    (
        "SS_NIGHT_DAYS",
        "COUNT",
        30,
        1,
        31,
        "Night price: days in a month",
        "តម្លៃមួយយប់៖ ចំនួនថ្ងៃក្នុងមួយខែ",
    ),
    (
        "SS_WEEK_PERCENT",
        "PERCENT",
        20000,
        1,
        100000,
        "Week price: % of the monthly rent, then shared by the weeks below",
        "តម្លៃមួយសប្ដាហ៍៖ % នៃថ្លៃជួលប្រចាំខែ រួចចែកនឹងចំនួនសប្ដាហ៍ខាងក្រោម",
    ),
    (
        "SS_WEEKS_IN_MONTH_TENTHS",
        "COUNT",
        43,
        10,
        50,
        "Week price: weeks in a month, in tenths (43 = 4.3)",
        "តម្លៃមួយសប្ដាហ៍៖ ចំនួនសប្ដាហ៍ក្នុងមួយខែ គិតជាភាគដប់ (43 = 4.3)",
    ),
    ("SS_TWO_NIGHTS_OFF", "PERCENT", 2000, 0, 10000, "2 nights: discount", "2 យប់៖ បញ្ចុះតម្លៃ"),
    (
        "SS_THREE_NIGHTS_OFF",
        "PERCENT",
        3000,
        0,
        10000,
        "3 to 6 nights: discount",
        "3 ដល់ 6 យប់៖ បញ្ចុះតម្លៃ",
    ),
    ("SS_TWO_WEEKS_OFF", "PERCENT", 1000, 0, 10000, "2 weeks: discount", "2 សប្ដាហ៍៖ បញ្ចុះតម្លៃ"),
    ("SS_THREE_WEEKS_OFF", "PERCENT", 1500, 0, 10000, "3 weeks: discount", "3 សប្ដាហ៍៖ បញ្ចុះតម្លៃ"),
    ("SS_MAX_NIGHTS", "DAYS", 29, 1, 60, "Longest short stay (nights)", "ការស្នាក់នៅខ្លីវែងបំផុត (យប់)"),
    (
        "SS_MONTH_ONLY_STUDIO",
        "USD_CENTS",
        44900,
        1,
        100000000,
        "1-month-only rent: Studio",
        "ថ្លៃជួលតែ 1 ខែ៖ បន្ទប់ស្ទូឌីយ៉ូ",
    ),
    (
        "SS_MONTH_ONLY_ONE_BEDROOM",
        "USD_CENTS",
        40500,
        1,
        100000000,
        "1-month-only rent: One bedroom",
        "ថ្លៃជួលតែ 1 ខែ៖ បន្ទប់គេង 1",
    ),
    (
        "SS_MONTH_ONLY_TWO_BEDROOM",
        "USD_CENTS",
        74900,
        1,
        100000000,
        "1-month-only rent: Two bedroom",
        "ថ្លៃជួលតែ 1 ខែ៖ បន្ទប់គេង 2",
    ),
    (
        "SS_CASH_DEPOSIT",
        "USD_CENTS",
        5000,
        0,
        100000000,
        "Deposit for guests who pay cash",
        "ប្រាក់កក់សម្រាប់ភ្ញៀវបង់សាច់ប្រាក់",
    ),
    (
        "SS_CARD_HOLD",
        "USD_CENTS",
        5000,
        0,
        100000000,
        "Card hold for guests who pay by card",
        "ការរក្សាទុកលើកាតសម្រាប់ភ្ញៀវបង់ដោយកាត",
    ),
    (
        "SS_FREE_CANCEL_DAYS",
        "DAYS",
        2,
        0,
        30,
        "Free cancel until 23:59 this many days before check-in",
        "លុបចោលដោយឥតគិតថ្លៃរហូតដល់ម៉ោង 23:59 មុនថ្ងៃចូលប៉ុន្មានថ្ងៃនេះ",
    ),
    (
        "SS_CREDIT_MONTHS",
        "COUNT",
        12,
        1,
        24,
        "Credit after a late cancel lasts (months)",
        "ឥណទានក្រោយការលុបចោលយឺតមានសុពលភាព (ខែ)",
    ),
    ("SS_CHECK_IN_TIME", "TIME_OF_DAY", 840, 0, 1439, "Check-in time", "ម៉ោងចូល"),
    ("SS_CHECK_OUT_TIME", "TIME_OF_DAY", 720, 0, 1439, "Check-out time", "ម៉ោងចេញ"),
    (
        "SS_LATE_CHECK_OUT_UNTIL",
        "TIME_OF_DAY",
        1080,
        0,
        1439,
        "Late check-out: at the latest",
        "ចេញយឺត៖ យឺតបំផុត",
    ),
    (
        "SS_EARLY_LATE_FEE",
        "USD_CENTS",
        500,
        0,
        100000000,
        "Early check-in or late check-out fee",
        "ថ្លៃចូលមុនម៉ោង ឬចេញយឺត",
    ),
    (
        "SS_EARLY_LATE_FREE_NIGHTS",
        "DAYS",
        7,
        1,
        60,
        "No early or late fee from this many nights",
        "គ្មានថ្លៃចូលមុន ឬចេញយឺត ចាប់ពីចំនួនយប់នេះ",
    ),
    (
        "SS_LEASE_FIRST_MONTH_OFF",
        "USD_CENTS",
        5000,
        0,
        100000000,
        "Change to a Lease: off the first month",
        "ប្ដូរទៅកិច្ចសន្យា៖ បញ្ចុះលើខែដំបូង",
    ),
    (
        "SS_RETURNING_GUEST_OFF",
        "USD_CENTS",
        300,
        0,
        100000000,
        "Returning guest thank-you (direct bookings)",
        "អរគុណភ្ញៀវមកម្ដងទៀត (ការកក់ផ្ទាល់)",
    ),
    (
        "SS_CHANGE_OVER_COST",
        "USD_CENTS",
        500,
        0,
        100000000,
        "Report only: cleaning cost per change-over",
        "សម្រាប់របាយការណ៍៖ ថ្លៃសម្អាតពេលប្ដូរភ្ញៀវ",
    ),
    (
        "SS_LINEN_COST",
        "USD_CENTS",
        200,
        0,
        100000000,
        "Report only: linen cost per change-over",
        "សម្រាប់របាយការណ៍៖ ថ្លៃកម្រាលពេលប្ដូរភ្ញៀវ",
    ),
    (
        "SS_CALENDAR_SYNC_MINUTES",
        "MINUTES",
        15,
        5,
        1440,
        "Read booking-site calendars every",
        "អានប្រតិទិនគេហទំព័រកក់រៀងរាល់",
    ),
)

TABLES = (
    "short_stay_quotes",
    "short_stay_bookings",
    "short_stay_price_lines",
    "short_stay_booking_events",
    "short_stay_deposits",
    "housekeeping_tasks",
    "short_stay_damages",
    "booking_site_calendars",
    "guest_notes",
)

SCHEMA = r"""
-- Price quotes (SQ): what the guest is told before paying. A quote never changes.
CREATE TABLE app.short_stay_quotes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    quote_number text NOT NULL UNIQUE CHECK (quote_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
    unit_id uuid REFERENCES app.units (id) ON DELETE RESTRICT,
    unit_type text NOT NULL CHECK (unit_type ~ '^[A-Z][A-Z0-9_]{0,39}$'),
    customer_id uuid REFERENCES app.customers (id) ON DELETE RESTRICT,
    guest_name text CHECK (guest_name = btrim(guest_name) AND length(guest_name) BETWEEN 1 AND 120),
    guest_contact text CHECK (guest_contact = btrim(guest_contact)
        AND length(guest_contact) BETWEEN 1 AND 120),
    guest_count smallint NOT NULL CHECK (guest_count BETWEEN 1 AND 10),
    check_in_on date NOT NULL,
    check_out_on date NOT NULL,
    total_usd_cents bigint NOT NULL CHECK (total_usd_cents >= 0),
    price_lines jsonb NOT NULL CHECK (jsonb_typeof(price_lines) = 'array'),
    made_on date NOT NULL,
    valid_until date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_quotes_nights CHECK (check_out_on - check_in_on BETWEEN 1 AND 60),
    CONSTRAINT short_stay_quotes_valid CHECK (valid_until >= made_on),
    CONSTRAINT short_stay_quotes_for_someone CHECK (customer_id IS NOT NULL OR guest_name IS NOT NULL)
);
CREATE INDEX short_stay_quotes_property_idx ON app.short_stay_quotes (property_id, created_at DESC);

-- Bookings (ST). A booking holds the nights [check-in day, check-out day).
CREATE TABLE app.short_stay_bookings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
    booking_number text NOT NULL UNIQUE CHECK (booking_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
    customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
    guest_count smallint NOT NULL CHECK (guest_count BETWEEN 1 AND 10),
    check_in_on date NOT NULL,
    check_out_on date NOT NULL,
    nights integer GENERATED ALWAYS AS (check_out_on - check_in_on) STORED,
    source text NOT NULL CHECK (source IN ('WALK_IN', 'PHONE', 'TELEGRAM', 'WEBSITE', 'BOOKING_SITE')),
    site_name text CHECK (site_name = btrim(site_name) AND length(site_name) BETWEEN 1 AND 80),
    site_reference text CHECK (site_reference = btrim(site_reference)
        AND length(site_reference) BETWEEN 1 AND 80),
    quote_id uuid UNIQUE REFERENCES app.short_stay_quotes (id) ON DELETE RESTRICT,
    note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    price_version integer NOT NULL DEFAULT 1 CHECK (price_version > 0),
    total_usd_cents bigint NOT NULL CHECK (total_usd_cents >= 0),
    status text NOT NULL DEFAULT 'BOOKED'
        CHECK (status IN ('BOOKED', 'CHECKED_IN', 'CHECKED_OUT', 'CANCELLED', 'NO_SHOW')),
    checked_in_at timestamptz,
    checked_in_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    checked_out_at timestamptz,
    checked_out_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    cancelled_at timestamptz,
    cancelled_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    cancel_reason text CHECK (cancel_reason = btrim(cancel_reason)
        AND length(cancel_reason) BETWEEN 1 AND 500),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_bookings_nights CHECK (check_out_on - check_in_on BETWEEN 1 AND 60),
    CONSTRAINT short_stay_bookings_site_shape CHECK (
        (source = 'BOOKING_SITE') = (site_name IS NOT NULL)
        AND (site_reference IS NULL OR source = 'BOOKING_SITE')),
    CONSTRAINT short_stay_bookings_checked_in_shape CHECK (
        (status IN ('CHECKED_IN', 'CHECKED_OUT'))
            = (checked_in_at IS NOT NULL AND checked_in_by IS NOT NULL)),
    CONSTRAINT short_stay_bookings_checked_out_shape CHECK (
        (status = 'CHECKED_OUT') = (checked_out_at IS NOT NULL AND checked_out_by IS NOT NULL)),
    CONSTRAINT short_stay_bookings_cancelled_shape CHECK (
        (status IN ('CANCELLED', 'NO_SHOW'))
            = (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancel_reason IS NOT NULL)),
    -- One Unit never has two bookings on the same night.
    CONSTRAINT short_stay_bookings_one_per_night EXCLUDE USING gist (
        unit_id WITH =,
        daterange(check_in_on, check_out_on, '[)') WITH &&
    ) WHERE (status IN ('BOOKED', 'CHECKED_IN'))
);
CREATE INDEX short_stay_bookings_property_idx
    ON app.short_stay_bookings (property_id, check_in_on DESC);
CREATE INDEX short_stay_bookings_customer_idx ON app.short_stay_bookings (customer_id);
CREATE INDEX short_stay_bookings_unit_idx ON app.short_stay_bookings (unit_id, check_in_on);
COMMENT ON TABLE app.short_stay_bookings IS
    'Daily and weekly rent: one guest stay in one Unit, nights [check_in_on, check_out_on).';

-- The price of each version of a booking; an extension prices the whole stay again.
CREATE TABLE app.short_stay_price_lines (
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    price_version integer NOT NULL CHECK (price_version > 0),
    line_position smallint NOT NULL CHECK (line_position BETWEEN 1 AND 30),
    kind text NOT NULL CHECK (kind IN ('NIGHTS', 'WEEKS', 'EARLY_CHECK_IN', 'LATE_CHECK_OUT',
        'RETURNING_GUEST', 'EXTRA_DISCOUNT')),
    quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 60),
    unit_price_usd_cents bigint NOT NULL CHECK (unit_price_usd_cents >= 0),
    discount_basis_points integer NOT NULL DEFAULT 0 CHECK (discount_basis_points BETWEEN 0 AND 10000),
    amount_usd_cents bigint NOT NULL,
    reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
    approved_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (booking_id, price_version, line_position),
    CONSTRAINT short_stay_price_lines_sign CHECK (
        CASE WHEN kind IN ('RETURNING_GUEST', 'EXTRA_DISCOUNT') THEN amount_usd_cents < 0
             ELSE amount_usd_cents >= 0 END),
    -- A Manager approves an extra discount, with a reason.
    CONSTRAINT short_stay_price_lines_extra_discount_approved CHECK (
        (kind = 'EXTRA_DISCOUNT') = (reason IS NOT NULL AND approved_by IS NOT NULL))
);

-- What happened to a booking, in order (append-only).
CREATE TABLE app.short_stay_booking_events (
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    event_number integer NOT NULL CHECK (event_number > 0),
    kind text NOT NULL CHECK (kind ~ '^[A-Z][A-Z_]{1,39}$'),
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    actor_id uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    PRIMARY KEY (booking_id, event_number)
);

-- The $50 cash deposit, or the $50 card hold. A card number is never saved: only the hold's
-- reference from the card machine and, if wanted, the card's last 4 digits.
CREATE TABLE app.short_stay_deposits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id uuid NOT NULL UNIQUE REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('CASH', 'CARD_HOLD')),
    amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
    hold_reference text CHECK (hold_reference = btrim(hold_reference)
        AND length(hold_reference) BETWEEN 1 AND 60
        AND regexp_replace(hold_reference, '[^0-9]', '', 'g') !~ '[0-9]{12,}'),
    card_last4 text CHECK (card_last4 ~ '^[0-9]{4}$'),
    status text NOT NULL DEFAULT 'HELD' CHECK (status IN ('HELD', 'RETURNED', 'KEPT')),
    kept_usd_cents bigint NOT NULL DEFAULT 0 CHECK (kept_usd_cents BETWEEN 0 AND amount_usd_cents),
    taken_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    taken_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    ended_at timestamptz,
    ended_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    end_note text CHECK (end_note = btrim(end_note) AND length(end_note) BETWEEN 1 AND 500),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT short_stay_deposits_card_shape CHECK (
        (kind = 'CARD_HOLD') = (hold_reference IS NOT NULL)
        AND (card_last4 IS NULL OR kind = 'CARD_HOLD')),
    CONSTRAINT short_stay_deposits_end_shape CHECK (
        (status = 'HELD') = (ended_at IS NULL AND ended_by IS NULL)),
    CONSTRAINT short_stay_deposits_kept_shape CHECK (
        (status = 'KEPT') = (kept_usd_cents > 0)
        AND (status <> 'KEPT' OR end_note IS NOT NULL))
);

-- Housekeeping: daily cleaning (daily and weekly guests), the change-over and the room check.
CREATE TABLE app.housekeeping_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
    booking_id uuid REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    task_on date NOT NULL,
    kind text NOT NULL CHECK (kind IN ('DAILY_CLEAN', 'CHANGE_OVER', 'ROOM_CHECK')),
    status text NOT NULL DEFAULT 'TO_DO' CHECK (status IN ('TO_DO', 'DONE', 'SKIPPED')),
    note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    done_at timestamptz,
    done_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT housekeeping_tasks_once UNIQUE (booking_id, task_on, kind),
    CONSTRAINT housekeeping_tasks_done_shape CHECK (
        (status = 'TO_DO') = (done_at IS NULL AND done_by IS NULL)),
    -- A skipped task says why (the guest said "do not disturb", for example).
    CONSTRAINT housekeeping_tasks_skip_reason CHECK (status <> 'SKIPPED' OR note IS NOT NULL)
);
CREATE INDEX housekeeping_tasks_day_idx ON app.housekeeping_tasks (property_id, task_on);

-- Damage found in a room check: the Manager approves the charge, with photos (later) and a reason.
CREATE TABLE app.short_stay_damages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    description text NOT NULL CHECK (description = btrim(description)
        AND length(description) BETWEEN 1 AND 500),
    amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
    status text NOT NULL DEFAULT 'WAITING' CHECK (status IN ('WAITING', 'APPROVED', 'REFUSED')),
    asked_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    asked_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    decided_at timestamptz,
    decided_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    decision_note text CHECK (decision_note = btrim(decision_note)
        AND length(decision_note) BETWEEN 1 AND 500),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT short_stay_damages_decided_shape CHECK (
        (status = 'WAITING') = (decided_at IS NULL AND decided_by IS NULL)
        AND (status <> 'WAITING' OR decision_note IS NULL)),
    CONSTRAINT short_stay_damages_refused_reason CHECK (status <> 'REFUSED' OR decision_note IS NOT NULL)
);
CREATE INDEX short_stay_damages_booking_idx ON app.short_stay_damages (booking_id);

-- Free iCal links: the booking site's calendar is read; ours is offered by its private token.
CREATE TABLE app.booking_site_calendars (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
    site_name text NOT NULL CHECK (site_name = btrim(site_name) AND length(site_name) BETWEEN 1 AND 80),
    import_url text CHECK (import_url ~ '^https://[^[:space:]]+$' AND length(import_url) <= 2000),
    export_token text NOT NULL UNIQUE
        DEFAULT replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '')
        CHECK (export_token ~ '^[0-9a-f]{64}$'),
    active boolean NOT NULL DEFAULT true,
    last_read_at timestamptz,
    last_read_ok boolean,
    last_error text CHECK (length(last_error) BETWEEN 1 AND 500),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT booking_site_calendars_one_per_site UNIQUE (unit_id, site_name),
    CONSTRAINT booking_site_calendars_read_shape CHECK (
        (last_read_at IS NULL) = (last_read_ok IS NULL)
        AND (last_error IS NULL OR last_read_ok = false))
);

-- Notes about a guest (a Customer); a problem guest is flagged for the front desk.
CREATE TABLE app.guest_notes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
    booking_id uuid REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    note text NOT NULL CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    problem_guest boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);
CREATE INDEX guest_notes_customer_idx ON app.guest_notes (customer_id, created_at DESC);

-- Never emptied.
CREATE FUNCTION app.reject_short_stay_truncate() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'Short-stay records are never emptied' USING ERRCODE = '55000';
END $$;
REVOKE ALL ON FUNCTION app.reject_short_stay_truncate() FROM PUBLIC;

-- Append-only rows: quotes, price lines, history and guest notes never change.
CREATE FUNCTION app.reject_short_stay_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% rows are never changed or removed', TG_TABLE_NAME USING ERRCODE = '55000';
END $$;
REVOKE ALL ON FUNCTION app.reject_short_stay_change() FROM PUBLIC;

-- A booking moves only forward; what it was booked as never changes. Its dates and price change
-- only while it is Booked or Checked in (a change or an extension), with a new price version.
CREATE FUNCTION app.protect_short_stay_booking() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP <> 'UPDATE'
        OR NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
        OR NEW.booking_number <> OLD.booking_number OR NEW.customer_id <> OLD.customer_id
        OR NEW.source <> OLD.source
        OR NEW.site_name IS DISTINCT FROM OLD.site_name
        OR NEW.quote_id IS DISTINCT FROM OLD.quote_id
        OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by
        OR NEW.version <> OLD.version + 1
        OR OLD.status IN ('CHECKED_OUT', 'CANCELLED', 'NO_SHOW')
        OR (NEW.status <> OLD.status AND NOT (
            (OLD.status = 'BOOKED' AND NEW.status IN ('CHECKED_IN', 'CANCELLED', 'NO_SHOW'))
            OR (OLD.status = 'CHECKED_IN' AND NEW.status = 'CHECKED_OUT')))
        OR NEW.price_version < OLD.price_version
        OR ((NEW.check_in_on, NEW.check_out_on, NEW.total_usd_cents, NEW.unit_id)
            IS DISTINCT FROM (OLD.check_in_on, OLD.check_out_on, OLD.total_usd_cents, OLD.unit_id)
            AND NEW.price_version = OLD.price_version)
        -- After check-in the guest stays in the same Unit and the first night stays.
        OR (OLD.status = 'CHECKED_IN'
            AND (NEW.unit_id <> OLD.unit_id OR NEW.check_in_on <> OLD.check_in_on))
        OR NEW.checked_in_at IS DISTINCT FROM COALESCE(OLD.checked_in_at, NEW.checked_in_at)
    THEN
        RAISE EXCEPTION 'A short-stay booking only moves forward; its history is kept'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.protect_short_stay_booking() FROM PUBLIC;

-- The booking's total is the sum of the lines of its price version (checked at commit).
CREATE FUNCTION app.check_short_stay_total() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_booking uuid := (to_jsonb(NEW) ->> CASE TG_TABLE_NAME
        WHEN 'short_stay_bookings' THEN 'id' ELSE 'booking_id' END)::uuid;
    v_row app.short_stay_bookings%ROWTYPE;
    v_sum bigint;
BEGIN
    SELECT booking.* INTO v_row FROM app.short_stay_bookings AS booking WHERE booking.id = v_booking;
    SELECT sum(line.amount_usd_cents) INTO v_sum FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = v_booking AND line.price_version = v_row.price_version;
    IF v_sum IS NULL OR v_sum <> v_row.total_usd_cents THEN
        RAISE EXCEPTION 'A short-stay booking total must be the sum of its price lines'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_price_lines AS line
               WHERE line.booking_id = v_booking AND line.price_version > v_row.price_version) THEN
        RAISE EXCEPTION 'A price version is used only by its booking' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION app.check_short_stay_total() FROM PUBLIC;

-- One Unit never has a booking and a signed Lease on the same night. The Unit row is locked so
-- two people cannot each pass the check at the same moment.
CREATE FUNCTION app.short_stay_lease_night_taken(p_unit uuid, p_from date, p_to date,
    p_lease_from date, p_lease_to date)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT daterange(p_from, p_to, '[)') && daterange(p_lease_from, p_lease_to, '[]')
$$;
REVOKE ALL ON FUNCTION app.short_stay_lease_night_taken(uuid, date, date, date, date) FROM PUBLIC;

CREATE FUNCTION app.guard_short_stay_nights() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.status NOT IN ('BOOKED', 'CHECKED_IN') THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.units AS unit
                   WHERE unit.id = NEW.unit_id AND unit.property_id = NEW.property_id) THEN
        RAISE EXCEPTION 'The Unit is not in this Property' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM app.units AS unit WHERE unit.id = NEW.unit_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM app.leases AS lease
        WHERE lease.unit_id = NEW.unit_id AND lease.status IN ('SIGNED', 'TERMINATED')
          AND app.short_stay_lease_night_taken(NEW.unit_id, NEW.check_in_on, NEW.check_out_on,
              lease.start_date, CASE WHEN lease.status = 'TERMINATED'
                  THEN lease.actual_termination_date ELSE lease.end_date END)
    ) THEN
        RAISE EXCEPTION 'The Unit has a Lease on one of these nights' USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_short_stay_nights() FROM PUBLIC;

CREATE FUNCTION app.guard_lease_short_stay_nights() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_to date;
BEGIN
    IF NEW.status NOT IN ('SIGNED', 'TERMINATED') OR NEW.start_date IS NULL THEN
        RETURN NEW;
    END IF;
    v_to := CASE WHEN NEW.status = 'TERMINATED' THEN NEW.actual_termination_date ELSE NEW.end_date END;
    PERFORM 1 FROM app.units AS unit WHERE unit.id = NEW.unit_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM app.short_stay_bookings AS booking
        WHERE booking.unit_id = NEW.unit_id AND booking.status IN ('BOOKED', 'CHECKED_IN')
          AND app.short_stay_lease_night_taken(NEW.unit_id, booking.check_in_on,
              booking.check_out_on, NEW.start_date, v_to)
    ) THEN
        RAISE EXCEPTION 'A daily or weekly guest has booked this Unit on one of these days; offer another Unit or a later Start Date'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_lease_short_stay_nights() FROM PUBLIC;

-- Short stay: only a guest's check-in gives this status, and only the check-out takes it away.
CREATE FUNCTION app.guard_short_stay_unit_status() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_guest boolean;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    v_guest := TG_OP = 'UPDATE' AND EXISTS (
        SELECT 1 FROM app.short_stay_bookings AS booking
        WHERE booking.unit_id = NEW.id AND booking.status = 'CHECKED_IN');
    IF NEW.status = 'SHORT_STAY' AND NOT v_guest THEN
        RAISE EXCEPTION 'Only a guest''s check-in makes a Unit Short stay' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'SHORT_STAY' AND v_guest THEN
        RAISE EXCEPTION 'A guest is in this Unit; check the guest out first' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_short_stay_unit_status() FROM PUBLIC;

-- A deposit, a housekeeping task and a damage charge each move forward once.
CREATE FUNCTION app.protect_short_stay_step() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_old jsonb := to_jsonb(OLD);
    v_new jsonb := to_jsonb(NEW);
    v_open text := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN 'HELD'
        WHEN 'housekeeping_tasks' THEN 'TO_DO'
        ELSE 'WAITING' END;
    v_free text[] := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN ARRAY['status', 'kept_usd_cents', 'ended_at', 'ended_by',
            'end_note', 'version']
        WHEN 'housekeeping_tasks' THEN ARRAY['status', 'note', 'done_at', 'done_by', 'version']
        ELSE ARRAY['status', 'decided_at', 'decided_by', 'decision_note', 'version'] END;
BEGIN
    IF TG_OP <> 'UPDATE' OR OLD.status <> v_open OR NEW.status = v_open
        OR (v_new ->> 'version')::integer <> (v_old ->> 'version')::integer + 1
        OR (v_old - v_free) <> (v_new - v_free)
    THEN
        RAISE EXCEPTION '% rows move forward once and are never removed', TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.protect_short_stay_step() FROM PUBLIC;

-- A calendar link is set up again (version + 1) but never removed: it is turned off instead.
CREATE FUNCTION app.protect_booking_site_calendar() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP <> 'UPDATE' OR NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
        OR NEW.unit_id <> OLD.unit_id OR NEW.created_at <> OLD.created_at
        OR NEW.created_by <> OLD.created_by OR NEW.version <> OLD.version + 1
    THEN
        RAISE EXCEPTION 'A booking-site calendar is never removed; turn it off'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.protect_booking_site_calendar() FROM PUBLIC;

CREATE TRIGGER short_stay_bookings_protect BEFORE UPDATE OR DELETE ON app.short_stay_bookings
    FOR EACH ROW EXECUTE FUNCTION app.protect_short_stay_booking();
CREATE TRIGGER short_stay_bookings_nights BEFORE INSERT OR UPDATE ON app.short_stay_bookings
    FOR EACH ROW EXECUTE FUNCTION app.guard_short_stay_nights();
CREATE CONSTRAINT TRIGGER short_stay_bookings_total AFTER INSERT OR UPDATE ON app.short_stay_bookings
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_short_stay_total();
CREATE CONSTRAINT TRIGGER short_stay_price_lines_total AFTER INSERT ON app.short_stay_price_lines
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_short_stay_total();
CREATE TRIGGER leases_short_stay_nights
    BEFORE INSERT OR UPDATE OF status, unit_id, start_date, end_date, actual_termination_date
    ON app.leases FOR EACH ROW EXECUTE FUNCTION app.guard_lease_short_stay_nights();
CREATE TRIGGER units_short_stay_status BEFORE INSERT OR UPDATE OF status ON app.units
    FOR EACH ROW EXECUTE FUNCTION app.guard_short_stay_unit_status();
CREATE TRIGGER short_stay_deposits_protect BEFORE UPDATE OR DELETE ON app.short_stay_deposits
    FOR EACH ROW EXECUTE FUNCTION app.protect_short_stay_step();
CREATE TRIGGER housekeeping_tasks_protect BEFORE UPDATE OR DELETE ON app.housekeeping_tasks
    FOR EACH ROW EXECUTE FUNCTION app.protect_short_stay_step();
CREATE TRIGGER short_stay_damages_protect BEFORE UPDATE OR DELETE ON app.short_stay_damages
    FOR EACH ROW EXECUTE FUNCTION app.protect_short_stay_step();
CREATE TRIGGER booking_site_calendars_protect BEFORE UPDATE OR DELETE ON app.booking_site_calendars
    FOR EACH ROW EXECUTE FUNCTION app.protect_booking_site_calendar();
CREATE TRIGGER short_stay_quotes_protect BEFORE UPDATE OR DELETE ON app.short_stay_quotes
    FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_price_lines_protect BEFORE UPDATE OR DELETE ON app.short_stay_price_lines
    FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_booking_events_protect BEFORE UPDATE OR DELETE ON app.short_stay_booking_events
    FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER guest_notes_protect BEFORE UPDATE OR DELETE ON app.guest_notes
    FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();

-- The Unit status Short stay, counted as occupied.
ALTER TABLE app.units DROP CONSTRAINT units_status_supported;
ALTER TABLE app.units ADD CONSTRAINT units_status_supported CHECK (status IN (
    'VACANT', 'RESERVED', 'OCCUPIED', 'UNDER_MAINTENANCE', 'CLEANING', 'OUT_OF_SERVICE',
    'SHORT_STAY'));

-- Booking and quote numbers.
INSERT INTO app.number_rules (document_type, year, last_number, format)
SELECT kind.document_type, years.year, 0, kind.format
FROM (VALUES ('SHORT_STAY', 'STyy000n'), ('SHORT_STAY_QUOTE', 'SQyy000n'))
    AS kind (document_type, format)
CROSS JOIN (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
          statement_timestamp()))::smallint AS year
      FROM app.properties AS property
      UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
ON CONFLICT (document_type, year) DO NOTHING;

-- The Settings area for the rules.
ALTER TABLE app.business_rule_names DROP CONSTRAINT business_rule_names_area;
ALTER TABLE app.business_rule_names ADD CONSTRAINT business_rule_names_area CHECK (area IN
    ('BILLING', 'RESERVATIONS', 'PRICES', 'QUOTATIONS', 'RIEL_RATE', 'LEDGER', 'STAFF',
     'ATTENDANCE', 'REPAIRS', 'SHORT_STAYS', 'OTHER'));
"""


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate()"
        )
    tables = ", ".join(f"app.{table}" for table in TABLES)
    op.execute(f"REVOKE ALL ON TABLE {tables} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(f"GRANT SELECT ON TABLE {tables} TO prm_runtime")

    # 4. The rules, with the owner's values; "Not used yet" until the next steps use them.
    ranges = "".join(
        f"\n                OR (v_code = {_text(code)} AND NEW.value NOT BETWEEN {low} AND {high})"
        for code, _unit, _value, low, high, _en, _kh in RULES
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_BEFORE + ranges),))
    for code, unit, value, _low, _high, en, kh in RULES:
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_text(code)}, {_text(en)}, {_text(kh)}, {_text(unit)}, 'SHORT_STAYS', false)
                RETURNING id
            )
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            SELECT named.id, {value}, DATE '2026-01-01', {_text(SEED_REASON)},
                (SELECT classification.actor_id FROM app.user_account_classes AS classification
                 WHERE classification.account_class = 'owner')
            FROM named
            """
        )

    # 5. The rights, their permissions and the new group.
    code, en, kh = GROUP
    op.execute(
        "INSERT INTO app.permission_groups (group_code, sort_order, name_en, name_kh, provenance) "
        f"VALUES ({_text(code)}, (SELECT max(sort_order) FROM app.permission_groups) + 1, "
        f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
    )
    capability_rows = ",\n            ".join(
        f"({_text(name)}, pg_catalog.split_part({_text(name)}, '.', 1), {_text(description)}, "
        f"'bundle', '{PROVENANCE}')"
        for name, description in CAPABILITIES
    )
    op.execute(
        "INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance) "
        f"VALUES {capability_rows}"
    )
    for permission, name_en, name_kh, _names in PERMISSIONS:
        # One statement per row: each reads the largest sort order so far.
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(permission)}, {_text(GROUP[0])}, "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(name_en)}, {_text(name_kh)}, '{PROVENANCE}')"
        )
    mapping_rows = ",\n            ".join(
        f"({_text(permission)}, {_text(name)}, '{PROVENANCE}')"
        for permission, _en, _kh, names in PERMISSIONS
        for name in names
    )
    op.execute(
        "INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance) "
        f"VALUES {mapping_rows}"
    )

    # New Properties: Staff see, work the front desk and do housekeeping; the Owner and the
    # Manager get every right.
    _patch(
        SEED,
        (
            (
                STAFF_BEFORE,
                "'problem_reports.read', 'problem_reports.add', "
                + ", ".join(_text(name) for name in STAFF)
                + "]::text[]",
            ),
        ),
    )
    every = _array(OWNER)
    staff = _array(STAFF)
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id
                        WHEN seeded.staff_bundle_id THEN {staff}
                        ELSE {every}
                    END AS added
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, held.capability_id
                FROM app.role_bundle_capabilities AS held
                WHERE held.role_bundle_id = v_default.role_bundle_id
                  AND held.version = v_default.version
                UNION
                SELECT v_default.role_bundle_id, v_default.version + 1, added
                FROM pg_catalog.unnest(v_default.added) AS added;
                SELECT property.timezone_name INTO v_timezone
                FROM app.properties AS property WHERE property.id = v_default.property_id;
                IF v_owner IS NOT NULL THEN
                    INSERT INTO app.audit_events (
                        id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                        reason, authorization_reference, property_id, previous_state,
                        resulting_state, correlation_id, source, outcome
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_at,
                        pg_catalog.timezone(v_timezone, v_at)::date, v_owner,
                        'identity.role_bundle.updated', 'role_bundle', v_default.role_bundle_id,
                        {_text(REASON)}, 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'capabilities_added', pg_catalog.to_jsonb(v_default.added)),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Short stays step 1 migration is forward-only")
