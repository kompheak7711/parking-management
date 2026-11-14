# ruff: noqa: E501
"""Unpaid Rent: notices on day 10, 20 and 25, the termination letter on day 30 (DL-237).

Owner (13 Nov 2026): "First notice: 10 days count from day first. Second notice: 20 days. Third
notice: 25 days. issue termination letter on 30 days. notice will send automatically since we
build telegram." With the owner's "all yes" of the same day to four points:

1. The termination letter of day 30 is a step of a Manager or the Owner. The app shows it as ready
   and nothing ends a Lease by itself.
2. The three notices go by themselves from 09:00 (Asia/Phnom_Penh), only while the Rent is still
   unpaid at that moment. Paying the Rent in full stops the next ones; a part payment does not.
3. A Lease with no Telegram link gets no notice by itself: staff see it the same day, give the
   paper letter and record it, as before.
4. No notice goes before the Due Date has passed (Settings allow a Due Date from day 1 to 28).

What changes:

- Two more kinds of ``app.rent_nonpayment_events``: ``TEN_DAY_NOTICE`` (first notice) and
  ``TWENTY_FIVE_DAY_NOTICE`` (third notice). ``TWENTY_DAY_WARNING`` is the second notice and
  ``THIRTY_DAY_SERIOUS_DEFAULT`` is the day-30 step, now the termination letter. The stored words
  stay, so every older record and the Deposit rule of BR-LEASE-028 read as before.
- ``app.rent_notice_first_day`` says the first day of each step: day N of the billed month, and
  never before the day after the Due Date. Every check of a step uses it.
- The day-30 step needs the three notices on the same case (BR-LEASE-024: three written letters).
- ``app.rent_notices_run`` (``telegram.operate``, run by the Telegram pull job) records the next
  notice of each unpaid monthly Rent line whose Lease has a live Telegram link: in order, one a
  day. ``app.telegram_warnings_queue`` then sends it, as it does for what staff record.
- Home counts what a person must do: a notice for a Lease with no Telegram link, and a termination
  letter that is ready. (Before, Home read the flags one level too high and always counted 0.)

No row is changed or deleted: two checks are widened and two unique indexes are added.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the days, the automatic
sending and the four points are the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270726_413"
down_revision: str | None = "20270725_378"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEND_HOUR = 9
NOTICES = "'TEN_DAY_NOTICE','TWENTY_DAY_WARNING','TWENTY_FIVE_DAY_NOTICE'"
STEPS = f"{NOTICES},'THIRTY_DAY_SERIOUS_DEFAULT'"

TABLES = f"""
    ALTER TABLE app.rent_nonpayment_events
        DROP CONSTRAINT rent_nonpayment_events_event_kind_check,
        ADD CONSTRAINT rent_nonpayment_events_event_kind_check CHECK (event_kind IN
            ({STEPS},'CURE','AUTHORIZED_FOLLOW_UP')),
        ADD CONSTRAINT rent_nonpayment_events_notice_reference CHECK (
            event_kind NOT IN ('TEN_DAY_NOTICE','TWENTY_FIVE_DAY_NOTICE')
            OR notice_document_reference IS NOT NULL);
    CREATE UNIQUE INDEX rent_nonpayment_first_notice_once_idx
        ON app.rent_nonpayment_events (rent_nonpayment_case_id) WHERE event_kind = 'TEN_DAY_NOTICE';
    CREATE UNIQUE INDEX rent_nonpayment_third_notice_once_idx
        ON app.rent_nonpayment_events (rent_nonpayment_case_id)
        WHERE event_kind = 'TWENTY_FIVE_DAY_NOTICE';

    ALTER TABLE app.telegram_warning_notices
        DROP CONSTRAINT telegram_warning_notices_warning_kind_check,
        DROP CONSTRAINT telegram_warning_notices_source,
        ADD CONSTRAINT telegram_warning_notices_warning_kind_check CHECK (warning_kind IN
            ('LEASE_WARNING', 'RENT_10', 'RENT_20', 'RENT_25', 'RENT_30')),
        ADD CONSTRAINT telegram_warning_notices_source CHECK (
            (warning_kind = 'LEASE_WARNING' AND lease_warning_id IS NOT NULL AND rent_event_id IS NULL)
            OR (warning_kind IN ('RENT_10', 'RENT_20', 'RENT_25', 'RENT_30')
                AND rent_event_id IS NOT NULL AND lease_warning_id IS NULL));
"""

FUNCTIONS = f"""
    -- The day of the billed month each step belongs to (BR-LEASE-026).
    CREATE FUNCTION app.rent_notice_day(p_kind text) RETURNS integer
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE p_kind WHEN 'TEN_DAY_NOTICE' THEN 10 WHEN 'TWENTY_DAY_WARNING' THEN 20
            WHEN 'TWENTY_FIVE_DAY_NOTICE' THEN 25 WHEN 'THIRTY_DAY_SERIOUS_DEFAULT' THEN 30 END
    $$;

    -- The first day a step may be taken: day N counted from the 1st of the billed month (day 30
    -- of February is 2 March), and never before the day after the Due Date.
    CREATE FUNCTION app.rent_notice_first_day(p_kind text, p_period_start date, p_due date)
    RETURNS date LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT greatest(p_period_start + app.rent_notice_day(p_kind) - 1, p_due + 1)
    $$;

    -- The "day zero" the older checks count from, for one kind of step: a step is open when
    -- today minus this day is at least the step's day. Other kinds count from the 1st as before.
    CREATE FUNCTION app.rent_notice_day_zero(p_invoice uuid, p_kind text) RETURNS date
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN invoice.rent_billing_kind = 'RECURRING' THEN COALESCE(
            app.rent_notice_first_day(p_kind, invoice.billing_period_start, invoice.due_date)
                - app.rent_notice_day(p_kind),
            invoice.billing_period_start - 1) END
        FROM app.invoices AS invoice WHERE invoice.id = p_invoice
    $$;

    CREATE OR REPLACE FUNCTION app.rent_nonpayment_milestone_eligible(p_kind text,p_due date,
        p_as_of timestamptz,p_balance bigint,p_prior_milestone boolean)
    RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT COALESCE(CASE
            WHEN p_kind IN ({STEPS}) THEN p_balance>0
                AND timezone('Asia/Phnom_Penh',p_as_of)::date-p_due>=app.rent_notice_day(p_kind)
            WHEN p_kind='CURE' THEN p_balance=0 AND p_prior_milestone
            WHEN p_kind='AUTHORIZED_FOLLOW_UP' THEN p_balance>=0
            ELSE false END,false)
    $$;

    -- The three notices of one case are all given.
    CREATE FUNCTION app.rent_notices_all_given(p_case uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT count(DISTINCT event.event_kind) = 3 FROM app.rent_nonpayment_events AS event
        WHERE event.rent_nonpayment_case_id = p_case AND event.event_kind IN ({NOTICES})
    $$;

    -- The next notice that goes by itself: the first one not given whose day has come, one a
    -- day, and none after the termination letter.
    CREATE FUNCTION app.rent_notice_next(p_period_start date, p_due date, p_today date,
        p_given text[], p_given_today boolean)
    RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN p_given_today OR 'THIRTY_DAY_SERIOUS_DEFAULT' = ANY (p_given) THEN NULL
            WHEN p_today >= app.rent_notice_first_day(missing.kind, p_period_start, p_due)
            THEN missing.kind END
        FROM (SELECT (SELECT step.kind
                      FROM unnest(ARRAY[{NOTICES}]) WITH ORDINALITY AS step (kind, place)
                      WHERE step.kind <> ALL (p_given) ORDER BY step.place LIMIT 1) AS kind) AS missing
    $$;

    CREATE FUNCTION app.rent_notice_hour_reached(p_now timestamptz) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT extract(hour FROM timezone('Asia/Phnom_Penh', p_now)) >= {SEND_HOUR}
    $$;

    -- Somebody of the Lease is linked to the Tenant bot today.
    CREATE FUNCTION app.rent_notice_telegram_linked(p_lease uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT EXISTS (
            SELECT 1 FROM app.tenant_telegram_links AS link
            JOIN app.leases AS lease ON lease.id = link.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE link.lease_id = p_lease AND link.property_id = unit.property_id
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                            app.gl_today(unit.property_id)))
    $$;

    -- Who may record a step: staff as before, and for a notice that goes by itself the account
    -- the Telegram pull job runs with (telegram.operate).
    CREATE FUNCTION app.rent_notice_scope(p_property uuid, p_lease uuid, p_actor uuid,
        p_by_itself boolean)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        IF p_by_itself AND EXISTS (
                SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
                WHERE held.capability_id = 'telegram.operate' AND held.property_id = p_property)
            AND EXISTS (SELECT 1 FROM app.leases AS lease
                JOIN app.units AS unit ON unit.id = lease.unit_id
                WHERE lease.id = p_lease AND unit.property_id = p_property)
        THEN RETURN; END IF;
        PERFORM app.lease_enforcement_scope(p_property, p_lease, p_actor);
    END $$;

    -- What the screens and the checks read about one Rent line: what is open now, what is given.
    CREATE FUNCTION app.rent_notice_assessment(p_invoice uuid, p_due date, p_as_of timestamptz,
        p_balance bigint, p_first boolean, p_second boolean, p_third boolean, p_letter boolean)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
        SET timezone = 'UTC' AS $$
        SELECT jsonb_build_object('as_of',p_as_of,'timezone','Asia/Phnom_Penh',
            'business_date',timezone('Asia/Phnom_Penh',p_as_of)::date,
            'days_overdue',greatest(0,timezone('Asia/Phnom_Penh',p_as_of)::date-p_due),
            'invoice_status',i.status,'source_applicable',source.applicable,
            'remaining_rent',jsonb_build_object('currency','USD','minor_units',p_balance),
            'ten_day_notice_eligible',source.applicable AND NOT p_first
                AND app.rent_nonpayment_milestone_eligible('TEN_DAY_NOTICE',
                    app.rent_notice_day_zero(i.id,'TEN_DAY_NOTICE'),p_as_of,p_balance,false),
            'twenty_day_warning_eligible',source.applicable AND NOT p_second
                AND app.rent_nonpayment_milestone_eligible('TWENTY_DAY_WARNING',
                    app.rent_notice_day_zero(i.id,'TWENTY_DAY_WARNING'),p_as_of,p_balance,false),
            'twenty_five_day_notice_eligible',source.applicable AND NOT p_third
                AND app.rent_nonpayment_milestone_eligible('TWENTY_FIVE_DAY_NOTICE',
                    app.rent_notice_day_zero(i.id,'TWENTY_FIVE_DAY_NOTICE'),p_as_of,p_balance,false),
            'thirty_day_default_eligible',source.applicable AND NOT p_letter
                AND p_first AND p_second AND p_third
                AND app.rent_nonpayment_milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',
                    app.rent_notice_day_zero(i.id,'THIRTY_DAY_SERIOUS_DEFAULT'),p_as_of,p_balance,false),
            'cure_eligible',source.applicable
                AND app.rent_nonpayment_milestone_eligible('CURE',app.rent_nonpayment_day_zero(i.id),
                    p_as_of,p_balance,p_first OR p_second OR p_third OR p_letter),
            'ten_day_notice_recorded',p_first,'warning_recorded',p_second,
            'twenty_five_day_notice_recorded',p_third,'serious_default_recorded',p_letter,
            'telegram_linked',app.rent_notice_telegram_linked(i.lease_id),
            'step_days',CASE WHEN i.rent_billing_kind='RECURRING' THEN jsonb_build_object(
                'TEN_DAY_NOTICE',app.rent_notice_first_day('TEN_DAY_NOTICE',i.billing_period_start,i.due_date),
                'TWENTY_DAY_WARNING',app.rent_notice_first_day('TWENTY_DAY_WARNING',i.billing_period_start,i.due_date),
                'TWENTY_FIVE_DAY_NOTICE',app.rent_notice_first_day('TWENTY_FIVE_DAY_NOTICE',i.billing_period_start,i.due_date),
                'THIRTY_DAY_SERIOUS_DEFAULT',app.rent_notice_first_day('THIRTY_DAY_SERIOUS_DEFAULT',i.billing_period_start,i.due_date))
                END)
        FROM app.invoices i
        CROSS JOIN LATERAL (SELECT i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of AS applicable) source
        WHERE i.id=p_invoice
    $$;

    CREATE OR REPLACE FUNCTION app.rent_nonpayment_case_snapshot(p_case uuid,p_as_of timestamptz)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        SELECT jsonb_build_object(
            'id',c.id,'lease_id',c.lease_id,'customer_id',c.customer_id,
            'property_id',app.invoice_property_id(c.invoice_id),'invoice_id',c.invoice_id,
            'rent_invoice_line_id',c.rent_invoice_line_id,'due_date_snapshot',c.due_date_snapshot,
            'opened_at',c.opened_at,'opened_by',c.opened_by,
            'assessment',app.rent_notice_assessment(c.invoice_id,c.due_date_snapshot,p_as_of,
                balance.amount,history.first_notice,history.warning,history.third_notice,
                history.serious_default),
            'event_count',history.event_count)
        FROM app.rent_nonpayment_cases c JOIN app.invoices i ON i.id=c.invoice_id
        CROSS JOIN LATERAL (SELECT CASE WHEN i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
            THEN app.invoice_line_outstanding_at(c.rent_invoice_line_id,p_as_of) ELSE 0 END AS amount) balance
        CROSS JOIN LATERAL (SELECT count(*) AS event_count,
            COALESCE(bool_or(event_kind='TEN_DAY_NOTICE'),false) AS first_notice,
            COALESCE(bool_or(event_kind='TWENTY_DAY_WARNING'),false) AS warning,
            COALESCE(bool_or(event_kind='TWENTY_FIVE_DAY_NOTICE'),false) AS third_notice,
            COALESCE(bool_or(event_kind='THIRTY_DAY_SERIOUS_DEFAULT'),false) AS serious_default
            FROM app.rent_nonpayment_events e WHERE e.rent_nonpayment_case_id=c.id AND e.occurred_at<=p_as_of) history
        WHERE c.id=p_case
    $$;

    CREATE OR REPLACE FUNCTION app.rent_nonpayment_source_context(p_line uuid,p_as_of timestamptz)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
        SELECT jsonb_build_object('rent_invoice_line_id',line.id,'invoice_id',i.id,'invoice_number',i.invoice_number,
            'property_id',u.property_id,'lease_id',l.id,'customer_id',i.customer_id,'due_date',i.due_date,
            'case_id',c.id,'assessment',CASE WHEN c.id IS NOT NULL
                THEN app.rent_nonpayment_case_snapshot(c.id,p_as_of)->'assessment'
                ELSE app.rent_notice_assessment(i.id,i.due_date,p_as_of,balance.amount,
                    false,false,false,false) END)
        FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
        JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
        LEFT JOIN app.rent_nonpayment_cases c ON c.rent_invoice_line_id=line.id
        CROSS JOIN LATERAL (SELECT CASE WHEN i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
            THEN app.invoice_line_outstanding_at(line.id,p_as_of) ELSE 0 END AS amount) balance
        WHERE line.id=p_line AND line.category='RENT' AND line.source_lease_id=l.id
    $$;

    -- The step a person must do for one Rent line: the termination letter when it is ready,
    -- or the next notice when nobody of the Lease is linked to the Tenant bot.
    CREATE FUNCTION app.rent_notice_person_step(p_assessment jsonb) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE
            WHEN (p_assessment->>'thirty_day_default_eligible')::boolean THEN 'THIRTY_DAY_SERIOUS_DEFAULT'
            WHEN (p_assessment->>'telegram_linked')::boolean THEN NULL
            WHEN (p_assessment->>'ten_day_notice_eligible')::boolean THEN 'TEN_DAY_NOTICE'
            WHEN (p_assessment->>'twenty_day_warning_eligible')::boolean THEN 'TWENTY_DAY_WARNING'
            WHEN (p_assessment->>'twenty_five_day_notice_eligible')::boolean THEN 'TWENTY_FIVE_DAY_NOTICE'
        END
    $$;

    -- The notices that go by themselves, without the hour of the day. Not open to the
    -- application's database account: app.rent_notices_run is.
    CREATE FUNCTION app.rent_notices_send(p_property uuid, p_actor uuid) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET timezone = 'UTC' AS $$
    DECLARE
        v_today date := timezone('Asia/Phnom_Penh', statement_timestamp())::date;
        v_row record;
        v_invoice app.invoices%ROWTYPE;
        v_event app.rent_nonpayment_events%ROWTYPE;
        v_case uuid;
        v_id uuid;
        v_kind text;
        v_number integer;
        v_balance bigint;
        v_now timestamptz;
        v_given text[];
        v_given_today boolean;
        v_evidence jsonb := jsonb_build_object('capability', 'telegram.operate',
            'rule', 'BR-LEASE-026', 'decision', 'DL-237');
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        FOR v_row IN
            SELECT line.id AS line_id, invoice.id AS invoice_id, lease.id AS lease_id
            FROM app.invoice_lines AS line
            JOIN app.invoices AS invoice ON invoice.id = line.invoice_id
            JOIN app.leases AS lease ON lease.id = invoice.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE unit.property_id = p_property AND line.category = 'RENT'
              AND line.source_lease_id = lease.id AND invoice.rent_billing_kind = 'RECURRING'
              AND invoice.status IN ('UNPAID', 'PARTIALLY_PAID') AND invoice.issued_at IS NOT NULL
              AND v_today >= app.rent_notice_first_day('TEN_DAY_NOTICE',
                  invoice.billing_period_start, invoice.due_date)
              AND app.rent_notice_telegram_linked(lease.id)
            ORDER BY line.id
        LOOP
            SELECT * INTO v_invoice FROM app.invoices WHERE id = v_row.invoice_id FOR UPDATE;
            CONTINUE WHEN v_invoice.status NOT IN ('UNPAID', 'PARTIALLY_PAID');
            PERFORM 1 FROM app.invoice_lines WHERE id = v_row.line_id FOR SHARE;
            -- Only the Rent line counts, at this moment.
            v_balance := app.invoice_line_outstanding(v_row.line_id);
            CONTINUE WHEN v_balance <= 0;
            v_case := (SELECT rent_case.id FROM app.rent_nonpayment_cases AS rent_case
                       WHERE rent_case.rent_invoice_line_id = v_row.line_id);
            SELECT COALESCE(array_agg(event.event_kind), '{{}}'),
                COALESCE(bool_or(event.event_date = v_today AND event.event_kind IN ({NOTICES})), false)
            INTO v_given, v_given_today
            FROM app.rent_nonpayment_events AS event WHERE event.rent_nonpayment_case_id = v_case;
            v_kind := app.rent_notice_next(v_invoice.billing_period_start, v_invoice.due_date,
                v_today, v_given, v_given_today);
            CONTINUE WHEN v_kind IS NULL;
            v_now := clock_timestamp();
            -- Midnight passed while the run worked: the next run goes on.
            EXIT WHEN timezone('Asia/Phnom_Penh', v_now)::date <> v_today;
            IF v_case IS NULL THEN
                v_case := gen_random_uuid();
                INSERT INTO app.rent_nonpayment_cases VALUES (v_case, v_row.lease_id,
                    v_invoice.customer_id, v_invoice.id, v_row.line_id, v_invoice.due_date, v_now, p_actor);
                INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                    entity_type, entity_id, reason, authorization_reference, property_id,
                    previous_state, resulting_state, correlation_id, source, outcome,
                    authorization_evidence, linked_source_event_id, customer_id, lease_id)
                VALUES (gen_random_uuid(), v_now, v_today, p_actor, 'rent_nonpayment.case_manage',
                    'rent_nonpayment_case', v_case, 'Opened for the Rent notices that go by themselves (DL-237)',
                    'telegram.operate', p_property, NULL, app.rent_nonpayment_case_snapshot(v_case, v_now),
                    gen_random_uuid(), 'SCHEDULED', 'SUCCEEDED', v_evidence, v_case,
                    v_invoice.customer_id, v_row.lease_id);
            END IF;
            v_number := CASE v_kind WHEN 'TEN_DAY_NOTICE' THEN 1 WHEN 'TWENTY_DAY_WARNING' THEN 2 ELSE 3 END;
            v_id := gen_random_uuid();
            INSERT INTO app.rent_nonpayment_events VALUES (v_id, v_case, v_kind, v_today, v_balance,
                'TG-' || v_invoice.invoice_number || '-' || v_number,
                'Sent by Telegram: by the Tenant bot, by itself',
                'Notice ' || v_number || ' of 3 (day ' || app.rent_notice_day(v_kind)
                    || ') sent by itself for unpaid Rent (BR-LEASE-026, DL-237)',
                v_now, p_actor, NULL)
            RETURNING * INTO v_event;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence, linked_source_event_id, customer_id, lease_id)
            VALUES (gen_random_uuid(), v_now, v_today, p_actor, 'rent_nonpayment.event_post',
                'rent_nonpayment_event', v_id, v_event.reason, 'telegram.operate', p_property, NULL,
                to_jsonb(v_event) || jsonb_build_object('lease_id', v_row.lease_id,
                    'customer_id', v_invoice.customer_id, 'property_id', p_property,
                    'invoice_id', v_invoice.id, 'rent_invoice_line_id', v_row.line_id,
                    'due_date_snapshot', v_invoice.due_date),
                gen_random_uuid(), 'SCHEDULED', 'SUCCEEDED', v_evidence, v_id,
                v_invoice.customer_id, v_row.lease_id);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- Run by the Telegram pull job, about once a minute: nothing before {SEND_HOUR}:00.
    CREATE FUNCTION app.rent_notices_run(p_property uuid, p_actor uuid) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF NOT app.rent_notice_hour_reached(statement_timestamp()) THEN
            RETURN 0;
        END IF;
        RETURN app.rent_notices_send(p_property, p_actor);
    END $$;

    CREATE OR REPLACE FUNCTION app.telegram_warnings_since(p_property uuid, p_since timestamptz)
    RETURNS TABLE (kind text, source_id uuid, lease_id uuid, occurred_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT 'LEASE_WARNING', warning.id, warning.lease_id, warning.occurred_at
        FROM app.lease_violation_warnings AS warning
        JOIN app.leases AS lease ON lease.id = warning.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE unit.property_id = p_property AND warning.occurred_at >= p_since
        UNION ALL
        SELECT 'RENT_' || app.rent_notice_day(event.event_kind),
            event.id, rent_case.lease_id, event.occurred_at
        FROM app.rent_nonpayment_events AS event
        JOIN app.rent_nonpayment_cases AS rent_case ON rent_case.id = event.rent_nonpayment_case_id
        JOIN app.leases AS lease ON lease.id = rent_case.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE unit.property_id = p_property AND event.occurred_at >= p_since
          AND event.event_kind IN ({STEPS})
    $$;

    -- The warning message's fields, with the dates as the tenant reads them.
    CREATE OR REPLACE FUNCTION app.telegram_warning_details(p_kind text, p_source uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_details jsonb;
    BEGIN
        IF p_kind = 'LEASE_WARNING' THEN
            SELECT jsonb_build_object(
                    'sequence', warning.warning_sequence,
                    'unit', unit.unit_number,
                    'date', to_char(warning.warning_date, 'DD/MM/YYYY'),
                    'when', to_char(warning.violation_date, 'DD/MM/YYYY'),
                    'text', warning.violation_description,
                    'rule', warning.lease_provision)
            INTO v_details
            FROM app.lease_violation_warnings AS warning
            JOIN app.leases AS lease ON lease.id = warning.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE warning.id = p_source;
        ELSE
            SELECT jsonb_build_object(
                    'unit', unit.unit_number,
                    'invoice', invoice.invoice_number,
                    'due', to_char(rent_case.due_date_snapshot, 'DD/MM/YYYY'),
                    'amount', app.telegram_usd(event.remaining_rent_usd_cents),
                    'date', to_char(event.event_date, 'DD/MM/YYYY'),
                    -- The first day the termination letter may be given.
                    'letter_day', to_char(app.rent_notice_first_day('THIRTY_DAY_SERIOUS_DEFAULT',
                        invoice.billing_period_start, invoice.due_date), 'DD/MM/YYYY'))
            INTO v_details
            FROM app.rent_nonpayment_events AS event
            JOIN app.rent_nonpayment_cases AS rent_case ON rent_case.id = event.rent_nonpayment_case_id
            JOIN app.invoices AS invoice ON invoice.id = rent_case.invoice_id
            JOIN app.leases AS lease ON lease.id = rent_case.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE event.id = p_source;
        END IF;
        IF v_details IS NULL THEN
            RAISE EXCEPTION 'Unknown warning' USING ERRCODE = '22023';
        END IF;
        RETURN v_details;
    END $$;
"""

# Each older function is read from the database and changed in place, so everything else in it
# stays as the migration before left it (the way of migration 68).
PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.validate_rent_nonpayment_event()",
        (
            (
                "PERFORM app.lease_enforcement_scope(app.invoice_property_id(v_case.invoice_id),v_case.lease_id,NEW.actor_id);",
                "PERFORM app.rent_notice_scope(app.invoice_property_id(v_case.invoice_id),v_case.lease_id,NEW.actor_id,\n"
                f"                NEW.event_kind IN ({NOTICES}));",
            ),
            (
                "app.rent_nonpayment_milestone_eligible(NEW.event_kind,app.rent_nonpayment_day_zero(v_case.invoice_id),",
                "app.rent_nonpayment_milestone_eligible(NEW.event_kind,app.rent_notice_day_zero(v_case.invoice_id,NEW.event_kind),",
            ),
            (
                "AND previous.event_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT')))",
                f"AND previous.event_kind IN ({STEPS})))\n"
                "                -- BR-LEASE-024: the termination letter comes after the three notices.\n"
                "                OR (NEW.event_kind='THIRTY_DAY_SERIOUS_DEFAULT' AND NOT app.rent_notices_all_given(v_case.id))",
            ),
        ),
    ),
    (
        "app.validate_rent_nonpayment_case()",
        (
            (
                "PERFORM app.lease_enforcement_scope(app.invoice_property_id(NEW.invoice_id),NEW.lease_id,NEW.opened_by);",
                "PERFORM app.rent_notice_scope(app.invoice_property_id(NEW.invoice_id),NEW.lease_id,NEW.opened_by,true);",
            ),
        ),
    ),
    (
        "app.rent_nonpayment_alert_page(uuid,integer,uuid)",
        (
            (
                "AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-(i.billing_period_start-1)>=20",
                "AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-(i.billing_period_start-1)>=10\n"
                "                    -- No step before the Due Date has passed (DL-237).\n"
                "                    AND timezone('Asia/Phnom_Penh',statement_timestamp())::date>i.due_date",
            ),
        ),
    ),
    (
        "app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text)",
        (
            (
                "OR (p_intent->>'event_kind') NOT IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT','CURE','AUTHORIZED_FOLLOW_UP')",
                f"OR (p_intent->>'event_kind') NOT IN ({STEPS},'CURE','AUTHORIZED_FOLLOW_UP')",
            ),
            (
                "IF (v_kind='TWENTY_DAY_WARNING' AND p_intent->>'notice_document_reference' IS NULL)",
                f"IF (v_kind IN ({NOTICES}) AND p_intent->>'notice_document_reference' IS NULL)",
            ),
            (
                "IF (v_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT') AND",
                f"IF (v_kind IN ({STEPS}) AND",
            ),
            (
                "app.rent_nonpayment_milestone_eligible(v_kind,app.rent_nonpayment_day_zero(v_case.invoice_id),v_now,v_balance,",
                "app.rent_nonpayment_milestone_eligible(v_kind,app.rent_notice_day_zero(v_case.invoice_id,v_kind),v_now,v_balance,",
            ),
            (
                "AND event_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT')))",
                f"AND event_kind IN ({STEPS})))\n"
                "                        OR (v_kind='THIRTY_DAY_SERIOUS_DEFAULT' AND NOT app.rent_notices_all_given(p_case))",
            ),
        ),
    ),
    (
        "app.telegram_warnings_queue(uuid,uuid)",
        (
            (
                "WHEN 'RENT_20' THEN 'tenant.rent_warning'",
                "WHEN 'RENT_10' THEN 'tenant.rent_notice_1'\n"
                "                         WHEN 'RENT_20' THEN 'tenant.rent_warning'\n"
                "                         WHEN 'RENT_25' THEN 'tenant.rent_notice_3'",
            ),
        ),
    ),
)

HOME = "app.home_page(uuid,uuid,uuid[],text[])"
HOME_FROM = "IF 'letters' = ANY(p_sections) THEN"
HOME_TO = "v_cards := v_cards || jsonb_build_object('letters_due'"
HOME_LETTERS = """IF 'letters' = ANY(p_sections) THEN
            -- Unpaid Rent steps a person must do (BR-LEASE-026, DL-237): a notice of day 10, 20
            -- or 25 for a Lease with no Telegram link, and the termination letter of day 30.
            -- From the same read the Rent nonpayment alert list uses.
            v_after := NULL;
            LOOP
                v_page := app.rent_nonpayment_alert_page(p_property, 100, v_after);
                SELECT v_twenty + count(*) FILTER (WHERE step.kind <> 'THIRTY_DAY_SERIOUS_DEFAULT'),
                    v_thirty + count(*) FILTER (WHERE step.kind = 'THIRTY_DAY_SERIOUS_DEFAULT')
                INTO v_twenty, v_thirty
                FROM jsonb_array_elements(v_page->'items') item
                CROSS JOIN LATERAL (SELECT app.rent_notice_person_step(item->'assessment') AS kind) step
                WHERE step.kind IS NOT NULL;
                SELECT v_todo || COALESCE(jsonb_agg(jsonb_build_object(
                        'kind', CASE WHEN step.kind = 'THIRTY_DAY_SERIOUS_DEFAULT'
                            THEN 'letter_day_30' ELSE 'letter_day_20' END,
                        'date', (item->'assessment'->'step_days'->>step.kind)::date,
                        'invoice_id', item->>'invoice_id', 'invoice_number', item->>'invoice_number',
                        'lease_id', item->>'lease_id', 'customer_id', item->>'customer_id',
                        'unit_id', unit.id, 'unit_number', unit.unit_number,
                        'customer_name', customer.legal_name)), '[]'::jsonb)
                INTO v_todo
                FROM jsonb_array_elements(v_page->'items') item
                CROSS JOIN LATERAL (SELECT app.rent_notice_person_step(item->'assessment') AS kind) step
                JOIN app.leases lease ON lease.id=(item->>'lease_id')::uuid
                JOIN app.units unit ON unit.id=lease.unit_id
                JOIN app.customers customer ON customer.id=(item->>'customer_id')::uuid
                WHERE step.kind IS NOT NULL;
                EXIT WHEN v_page->>'next_cursor' IS NULL;
                v_after := (v_page->>'next_cursor')::uuid;
            END LOOP;
            """

INTERNAL = (
    "app.rent_notice_day(text)",
    "app.rent_notice_first_day(text,date,date)",
    "app.rent_notice_day_zero(uuid,text)",
    "app.rent_notices_all_given(uuid)",
    "app.rent_notice_next(date,date,date,text[],boolean)",
    "app.rent_notice_hour_reached(timestamptz)",
    "app.rent_notice_telegram_linked(uuid)",
    "app.rent_notice_scope(uuid,uuid,uuid,boolean)",
    "app.rent_notice_assessment(uuid,date,timestamptz,bigint,boolean,boolean,boolean,boolean)",
    "app.rent_notice_person_step(jsonb)",
    "app.rent_notices_send(uuid,uuid)",
)
RUNTIME = ("app.rent_notices_run(uuid,uuid)",)


def _definition(signature: str) -> str:
    found = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    return str(found)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Rent notice source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(text(definition.replace(":", "\\:")))


def _home_letters() -> None:
    definition = _definition(HOME)
    if definition.count(HOME_FROM) != 1 or definition.count(HOME_TO) != 1:
        raise RuntimeError(f"Rent notice source contract changed: {HOME}")
    start, end = definition.index(HOME_FROM), definition.index(HOME_TO)
    if start > end:
        raise RuntimeError(f"Rent notice source contract changed: {HOME}")
    op.execute(text((definition[:start] + HOME_LETTERS + definition[end:]).replace(":", "\\:")))


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    _home_letters()
    for signature in INTERNAL + RUNTIME:
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Rent notice days migration is forward-only")
