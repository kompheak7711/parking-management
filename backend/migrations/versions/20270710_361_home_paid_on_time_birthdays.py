# ruff: noqa: E501
"""UI v81 round 4 (owner 08/11/2026): two more Home cards, "Paid on time" and "Birthdays", and the
Customers page Birthdays list. Read-only; no table changes.

- `app.birthday_in_year(date_of_birth, year)`: the birthday in a year; 29 February falls on
  28 February in a year that has no 29th (design v81 Birthdays page rules).
- `app.customer_birthdays(actor, property, allowed)`: the Primary Tenants and Occupants of the
  Property's active Leases (signed, running today) who have a date of birth, each once (Primary
  Tenant first), with the Unit and the next birthday from today on. It checks the person and the
  allowed Property like every report read (`app.report_actor_property`). It never gives the year of
  birth or the age.
- `app.home_page` keeps its arguments, sections and rules and adds, inside the `invoices` section,
  `paid_on_time` (the Invoices whose Due Date fell in the last 12 months and has passed, and how many
  were fully paid by the end of their Due Date), and a new `birthdays` section with the count for
  today and the next 7 days. The application passes the section only with `customers.read`.

New relations: none. The functions are added or replaced in place; nothing is removed.
"""

from alembic import op

revision = "20270710_361"
down_revision = "20270626_360"
branch_labels = None
depends_on = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"
BIRTHDAY_IN_YEAR = "app.birthday_in_year(date,integer)"
BIRTHDAYS = "app.customer_birthdays(uuid,uuid,uuid[])"

BIRTHDAYS_SQL = """    CREATE OR REPLACE FUNCTION app.birthday_in_year(p_date_of_birth date, p_year integer)
    RETURNS date LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,pg_temp AS $$
        SELECT CASE
            WHEN extract(month FROM p_date_of_birth)=2 AND extract(day FROM p_date_of_birth)=29
                AND NOT (p_year % 4 = 0 AND (p_year % 100 <> 0 OR p_year % 400 = 0))
            THEN make_date(p_year, 2, 28)
            ELSE make_date(p_year, extract(month FROM p_date_of_birth)::integer, extract(day FROM p_date_of_birth)::integer)
        END
    $$;
    CREATE OR REPLACE FUNCTION app.customer_birthdays(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(customer_id uuid, customer_name text, role text, unit_id uuid, unit_number text, birthday date)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_today date := timezone(v_timezone, statement_timestamp())::date;
    BEGIN
        RETURN QUERY
        WITH person AS (
            SELECT lease.primary_tenant_id AS customer_id, 'PRIMARY'::text AS role,
                unit.id AS unit_id, unit.unit_number, 1 AS rank
            FROM app.leases lease
            JOIN app.units unit ON unit.id=lease.unit_id
            WHERE unit.property_id=p_property AND lease.status='SIGNED'
              AND (lease.start_date IS NULL OR lease.start_date<=v_today)
              AND (lease.end_date IS NULL OR lease.end_date>=v_today)
            UNION ALL
            SELECT occupancy.customer_id, 'OCCUPANT'::text, unit.id, unit.unit_number, 2
            FROM app.occupancies occupancy
            JOIN app.leases lease ON lease.id=occupancy.lease_id
            JOIN app.units unit ON unit.id=lease.unit_id
            WHERE unit.property_id=p_property AND lease.status='SIGNED'
              AND (lease.end_date IS NULL OR lease.end_date>=v_today)
              AND occupancy.move_in_date<=v_today
              AND (occupancy.move_out_date IS NULL OR occupancy.move_out_date>=v_today)
              AND occupancy.customer_id<>lease.primary_tenant_id
        ), one AS (
            SELECT DISTINCT ON (person.customer_id) person.customer_id, person.role, person.unit_id, person.unit_number
            FROM person ORDER BY person.customer_id, person.rank, person.unit_number
        ), dated AS (
            SELECT one.customer_id, customer.legal_name, one.role, one.unit_id, one.unit_number,
                CASE WHEN app.birthday_in_year(customer.date_of_birth, extract(year FROM v_today)::integer)>=v_today
                    THEN app.birthday_in_year(customer.date_of_birth, extract(year FROM v_today)::integer)
                    ELSE app.birthday_in_year(customer.date_of_birth, extract(year FROM v_today)::integer+1) END AS birthday
            FROM one
            JOIN app.customers customer ON customer.id=one.customer_id
            WHERE customer.date_of_birth IS NOT NULL
        )
        SELECT dated.customer_id, dated.legal_name, dated.role, dated.unit_id, dated.unit_number, dated.birthday
        FROM dated ORDER BY dated.birthday, dated.legal_name, dated.customer_id;
    END $$;
"""

HOME_SQL = """    CREATE OR REPLACE FUNCTION app.home_page(p_actor uuid, p_property uuid, p_allowed uuid[], p_sections text[])
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_at timestamptz := statement_timestamp();
        v_today date;
        v_month_start date;
        v_month_end date;
        v_reading_day date;
        v_cards jsonb := '{}'::jsonb;
        v_todo jsonb := '[]'::jsonb;
        v_part jsonb;
        v_page jsonb;
        v_after uuid;
        v_twenty integer := 0;
        v_thirty integer := 0;
        v_jobs jsonb := '{}'::jsonb;
        v_last_billing timestamptz;
        v_rate_at timestamptz;
        v_money_out bigint;
        v_money_out_count integer;
    BEGIN
        IF p_sections IS NULL OR array_position(p_sections, NULL) IS NOT NULL
            OR EXISTS(SELECT 1 FROM unnest(p_sections) s WHERE s NOT IN ('units', 'invoices', 'payments', 'leases', 'reservations', 'approvals', 'deposit_decisions', 'readings', 'letters', 'settlements', 'birthdays'))
        THEN RAISE EXCEPTION 'Home page sections are invalid' USING ERRCODE='22023'; END IF;
        v_today := timezone(v_timezone, v_at)::date;
        v_month_start := date_trunc('month', v_today)::date;
        v_month_end := (v_month_start + interval '1 month' - interval '1 day')::date;
        -- Meters are read on the 24th (DESIGN.md billing calendar; no reading-day setting is
        -- stored yet). Readings dated from that day on count for it.
        v_reading_day := v_month_start + 23;

        IF 'units' = ANY(p_sections) THEN
            SELECT jsonb_build_object('occupied', count(*) FILTER (WHERE unit.status='OCCUPIED'),
                'reserved', count(*) FILTER (WHERE unit.status='RESERVED'),
                'vacant', count(*) FILTER (WHERE unit.status='VACANT'),
                'total', count(*)) INTO v_part
            FROM app.units unit WHERE unit.property_id=p_property;
            v_cards := v_cards || jsonb_build_object('units_occupied', v_part);
        END IF;

        IF 'invoices' = ANY(p_sections) THEN
            WITH open_invoice AS (
                SELECT invoice.id, invoice.due_date, (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)
                    FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS balance
                FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID')
                  AND app.invoice_property_id(invoice.id)=p_property
            )
            SELECT jsonb_build_object(
                'pending_payment', jsonb_build_object(
                    'amount_usd_cents', COALESCE(sum(balance) FILTER (WHERE balance>0),0),
                    'invoice_count', count(*) FILTER (WHERE balance>0)),
                'overdue', jsonb_build_object(
                    'amount_usd_cents', COALESCE(sum(balance) FILTER (WHERE balance>0 AND due_date<v_today),0),
                    'invoice_count', count(*) FILTER (WHERE balance>0 AND due_date<v_today)))
            INTO v_part FROM open_invoice;
            v_cards := v_cards || v_part;
            -- The billed part of "Paid for this month": Invoices whose Due Date is in this month.
            WITH billed AS (
                SELECT (SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS total,
                    (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS balance
                FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                  AND invoice.due_date BETWEEN v_month_start AND v_month_end
                  AND app.invoice_property_id(invoice.id)=p_property
            )
            SELECT jsonb_build_object('billed_usd_cents', COALESCE(sum(total),0),
                'billed_paid_usd_cents', COALESCE(sum(total-balance),0), 'invoice_count', count(*))
            INTO v_part FROM billed;
            v_cards := jsonb_set(v_cards, '{paid_this_month}',
                COALESCE(v_cards->'paid_this_month','{}'::jsonb) || v_part);
            -- UI v81 round 4 (owner 08/11/2026): "Paid on time". The Invoices whose Due Date fell in
            -- the last 12 months (and has passed), and how many of them were fully paid by the end of
            -- their Due Date, from the allocations posted by then (docs/ui-audit/04_GLOSSARY.md).
            WITH due AS (
                SELECT (SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS total,
                    (SELECT COALESCE(sum(app.invoice_line_payment_value_at(line.id,
                            timezone(v_timezone, (invoice.due_date + 1)::timestamp))),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS paid_by_due
                FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                  AND invoice.due_date < v_today
                  AND invoice.due_date >= (v_today - interval '12 months')::date
                  AND app.invoice_property_id(invoice.id)=p_property
            )
            SELECT jsonb_build_object('on_time', count(*) FILTER (WHERE total>0 AND paid_by_due>=total),
                'invoice_count', count(*) FILTER (WHERE total>0))
            INTO v_part FROM due;
            v_cards := v_cards || jsonb_build_object('paid_on_time', v_part);
            -- To-do: overdue Initial Rent (DL-072 answer 9).
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','overdue_initial_rent',
                    'date', invoice.due_date, 'invoice_id', invoice.id,
                    'invoice_number', invoice.invoice_number, 'lease_id', invoice.lease_id,
                    'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name,
                    'balance_usd_cents', item.balance) ORDER BY invoice.due_date, invoice.id),'[]'::jsonb)
            INTO v_part
            FROM app.invoices invoice
            JOIN app.leases lease ON lease.id=invoice.lease_id
            JOIN app.units unit ON unit.id=lease.unit_id
            JOIN app.customers customer ON customer.id=invoice.customer_id
            CROSS JOIN LATERAL (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)::bigint AS balance
                FROM app.invoice_lines line WHERE line.invoice_id=invoice.id) item
            WHERE unit.property_id=p_property AND invoice.rent_billing_kind='INITIAL'
              AND invoice.status IN ('UNPAID','PARTIALLY_PAID') AND invoice.due_date<v_today
              AND item.balance>0;
            v_todo := v_todo || v_part;
            -- The line under the to-do list: the last finished Rent or Utility billing run and
            -- the next Rent billing day (the 25th, the DL-075 Settings default; no billing-day
            -- setting is stored yet).
            SELECT max(run.completed_at) INTO v_last_billing
            FROM app.billing_runs run
            WHERE run.property_id=p_property AND run.status='SUCCEEDED';
            v_jobs := v_jobs || jsonb_build_object('last_billing_at', v_last_billing,
                'next_billing_date', CASE WHEN extract(day FROM v_today)<=25 THEN v_month_start+24
                    ELSE (v_month_start + interval '1 month')::date+24 END);
        END IF;

        IF 'payments' = ANY(p_sections) THEN
            SELECT jsonb_build_object('received_usd_cents', COALESCE(sum(payment.usd_accounting_value_cents),0),
                'payment_count', count(*)) INTO v_part
            FROM app.payments payment
            WHERE payment.property_id=p_property AND payment.status='RECEIVED'
              AND payment.payment_date BETWEEN v_month_start AND v_month_end;
            v_cards := jsonb_set(v_cards, '{paid_this_month}',
                COALESCE(v_cards->'paid_this_month','{}'::jsonb) || v_part);
            -- The exchange rate in use was last entered at (one rate list for every Property).
            SELECT max(rate.applicable_at) INTO v_rate_at
            FROM app.exchange_rate_records rate WHERE rate.applicable_at<=v_at;
            v_jobs := v_jobs || jsonb_build_object('rate_updated_at', v_rate_at);
        END IF;

        IF 'leases' = ANY(p_sections) THEN
            -- Lease renewal: a signed Lease that ends within 60 days (DL-072 answer 7) and has
            -- no renewal Lease drafted or signed yet.
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','lease_ending', 'date', lease.end_date,
                    'lease_id', lease.id, 'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name)
                    ORDER BY lease.end_date, unit.unit_number, lease.id),'[]'::jsonb)
            INTO v_part
            FROM app.leases lease
            JOIN app.units unit ON unit.id=lease.unit_id
            JOIN app.customers customer ON customer.id=lease.primary_tenant_id
            WHERE unit.property_id=p_property AND lease.status='SIGNED'
              AND lease.end_date BETWEEN v_today AND v_today+60
              AND NOT EXISTS(SELECT 1 FROM app.leases renewal
                  WHERE renewal.predecessor_lease_id=lease.id AND renewal.status IN ('DRAFTED','SIGNED'));
            v_cards := v_cards || jsonb_build_object('lease_renewal', jsonb_build_object(
                'count', jsonb_array_length(v_part), 'end_on_or_before', v_today+60));
            v_todo := v_todo || v_part;
        END IF;

        IF 'reservations' = ANY(p_sections) THEN
            -- Reservations nearing expiry: 14 days or less before the Expiration Date (answer 8).
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','reservation_expiring',
                    'date', reservation.effective_expiration_date, 'reservation_id', reservation.id,
                    'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name)
                    ORDER BY reservation.effective_expiration_date, unit.unit_number, reservation.id),'[]'::jsonb)
            INTO v_part
            FROM app.reservations reservation
            JOIN app.units unit ON unit.id=reservation.unit_id
            JOIN app.customers customer ON customer.id=reservation.customer_id
            WHERE unit.property_id=p_property AND reservation.status='ACTIVE'
              AND reservation.effective_expiration_date<=v_today+14;
            v_todo := v_todo || v_part;
        END IF;

        IF 'approvals' = ANY(p_sections) THEN
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','draft_waiting',
                    'date', timezone(v_timezone, draft.prepared_at)::date, 'draft_id', draft.id,
                    'draft_kind', draft.kind) ORDER BY draft.prepared_at, draft.id),'[]'::jsonb)
            INTO v_part
            FROM app.financial_drafts draft
            WHERE draft.property_id=p_property
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id);
            -- Money out: the drafts that pay money to someone when confirmed (a Refund, or a
            -- Payment returned to the payer).
            SELECT COALESCE(sum(CASE draft.kind
                    WHEN 'REFUND' THEN (draft.payload->>'amount_usd_cents')::bigint
                    ELSE payment.usd_accounting_value_cents END),0)::bigint,
                count(*)
            INTO v_money_out, v_money_out_count
            FROM app.financial_drafts draft
            LEFT JOIN app.payments payment ON draft.kind='PAYMENT_RETURN'
                AND payment.id=(draft.payload->>'payment_id')::uuid
            WHERE draft.property_id=p_property AND draft.kind IN ('REFUND','PAYMENT_RETURN')
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id);
            v_cards := v_cards || jsonb_build_object('waiting_for_approval',
                jsonb_build_object('count', jsonb_array_length(v_part),
                    'money_out_usd_cents', v_money_out, 'money_out_count', v_money_out_count));
            v_todo := v_todo || v_part;
        END IF;

        IF 'deposit_decisions' = ANY(p_sections) THEN
            -- A cancelled Reservation whose Deposit money is held and has no outcome yet.
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','deposit_decision',
                    'date', timezone(v_timezone, reservation.cancelled_at)::date,
                    'reservation_id', reservation.id, 'deposit_id', deposit.id,
                    'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name)
                    ORDER BY reservation.cancelled_at, reservation.id),'[]'::jsonb)
            INTO v_part
            FROM app.reservations reservation
            JOIN app.units unit ON unit.id=reservation.unit_id
            JOIN app.customers customer ON customer.id=reservation.customer_id
            JOIN app.deposits deposit ON deposit.reservation_id=reservation.id
            WHERE unit.property_id=p_property AND reservation.status='CANCELLED'
              AND NOT app.reservation_deposit_has_outcome(deposit.id)
              AND EXISTS(SELECT 1 FROM app.deposit_receipts receipt
                  WHERE receipt.deposit_id=deposit.id
                    AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                        WHERE reversal.deposit_receipt_id=receipt.id));
            v_todo := v_todo || v_part;
        END IF;

        IF 'readings' = ANY(p_sections) THEN
            SELECT jsonb_build_object('count', count(*), 'reading_date', v_reading_day) INTO v_part
            FROM app.utility_meters meter
            JOIN app.units unit ON unit.id=meter.unit_id
            WHERE unit.property_id=p_property AND meter.deactivated_date IS NULL
              AND meter.failure_date IS NULL AND meter.installed_date<=v_today
              AND NOT EXISTS(SELECT 1 FROM app.utility_readings reading
                  WHERE reading.meter_id=meter.id AND reading.reading_date>=v_reading_day);
            v_cards := v_cards || jsonb_build_object('meter_readings_missing', v_part);
            IF (v_part->>'count')::integer>0 AND v_today>=v_reading_day-6 THEN
                v_todo := v_todo || jsonb_build_array(jsonb_build_object('kind','readings_missing',
                    'date', v_reading_day, 'count', (v_part->>'count')::integer));
            END IF;
        END IF;

        IF 'letters' = ANY(p_sections) THEN
            -- Day-20 and day-30 Rent letters due (BR-LEASE-027, DL-073), from the same read the
            -- Rent nonpayment alert list uses.
            v_after := NULL;
            LOOP
                v_page := app.rent_nonpayment_alert_page(p_property, 100, v_after);
                SELECT v_twenty + count(*) FILTER (WHERE (item->>'twenty_day_warning_eligible')::boolean
                        AND NOT COALESCE((item->>'warning_recorded')::boolean,false)),
                    v_thirty + count(*) FILTER (WHERE (item->>'thirty_day_default_eligible')::boolean
                        AND NOT COALESCE((item->>'serious_default_recorded')::boolean,false))
                INTO v_twenty, v_thirty FROM jsonb_array_elements(v_page->'items') item;
                SELECT v_todo || COALESCE(jsonb_agg(jsonb_build_object(
                        'kind', CASE WHEN (item->>'thirty_day_default_eligible')::boolean
                            AND NOT COALESCE((item->>'serious_default_recorded')::boolean,false)
                            THEN 'letter_day_30' ELSE 'letter_day_20' END,
                        'date', app.rent_nonpayment_day_zero((item->>'invoice_id')::uuid)
                            + CASE WHEN (item->>'thirty_day_default_eligible')::boolean
                                AND NOT COALESCE((item->>'serious_default_recorded')::boolean,false)
                                THEN 30 ELSE 20 END,
                        'invoice_id', item->>'invoice_id', 'invoice_number', item->>'invoice_number',
                        'lease_id', item->>'lease_id', 'customer_id', item->>'customer_id',
                        'unit_id', unit.id, 'unit_number', unit.unit_number,
                        'customer_name', customer.legal_name)), '[]'::jsonb)
                INTO v_todo
                FROM jsonb_array_elements(v_page->'items') item
                JOIN app.leases lease ON lease.id=(item->>'lease_id')::uuid
                JOIN app.units unit ON unit.id=lease.unit_id
                JOIN app.customers customer ON customer.id=(item->>'customer_id')::uuid
                WHERE ((item->>'twenty_day_warning_eligible')::boolean
                        AND NOT COALESCE((item->>'warning_recorded')::boolean,false))
                   OR ((item->>'thirty_day_default_eligible')::boolean
                        AND NOT COALESCE((item->>'serious_default_recorded')::boolean,false));
                EXIT WHEN v_page->>'next_cursor' IS NULL;
                v_after := (v_page->>'next_cursor')::uuid;
            END LOOP;
            v_cards := v_cards || jsonb_build_object('letters_due', jsonb_build_object(
                'count', v_twenty+v_thirty, 'day_20', v_twenty, 'day_30', v_thirty));
        END IF;

        IF 'settlements' = ANY(p_sections) THEN
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','settlement_open',
                    'date', timezone(v_timezone, settlement.started_at)::date,
                    'final_settlement_id', settlement.id, 'lease_id', lease.id,
                    'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name)
                    ORDER BY settlement.started_at, settlement.id),'[]'::jsonb)
            INTO v_part
            FROM app.final_settlements settlement
            JOIN app.leases lease ON lease.id=settlement.lease_id
            JOIN app.units unit ON unit.id=lease.unit_id
            JOIN app.customers customer ON customer.id=lease.primary_tenant_id
            WHERE settlement.property_id=p_property AND settlement.closed_at IS NULL;
            v_todo := v_todo || v_part;
            -- "Refund due by" (DL-073 item 4): 7 days after the later of the final inspection
            -- and the final Utility Invoice, while Deposit money of the Lease is still held.
            SELECT COALESCE(jsonb_agg(jsonb_build_object('kind','refund_due',
                    'date', due.due_date, 'lease_id', lease.id,
                    'unit_id', unit.id, 'unit_number', unit.unit_number,
                    'customer_id', customer.id, 'customer_name', customer.legal_name,
                    'held_usd_cents', due.held) ORDER BY due.due_date, lease.id),'[]'::jsonb)
            INTO v_part
            FROM app.leases lease
            JOIN app.units unit ON unit.id=lease.unit_id
            JOIN app.customers customer ON customer.id=lease.primary_tenant_id
            CROSS JOIN LATERAL (
                SELECT GREATEST(
                        (SELECT max(inspection.inspection_date) FROM app.move_out_inspections inspection
                         WHERE inspection.lease_id=lease.id
                           AND NOT EXISTS(SELECT 1 FROM app.move_out_inspections later
                               WHERE later.supersedes_inspection_id=inspection.id)),
                        (SELECT max(invoice.invoice_date) FROM app.utility_invoice_commands command
                         JOIN app.invoices invoice ON invoice.id=command.invoice_id
                         WHERE command.lease_id=lease.id AND command.action='FINAL'
                           AND invoice.status NOT IN ('DRAFT','VOID'))) + 7 AS due_date,
                    (SELECT COALESCE(sum(app.deposit_held_value_at(deposit.id, v_at)),0)
                     FROM app.deposits deposit WHERE deposit.lease_id=lease.id)::bigint AS held,
                    EXISTS(SELECT 1 FROM app.move_out_inspections inspection
                        WHERE inspection.lease_id=lease.id) AS inspected,
                    EXISTS(SELECT 1 FROM app.utility_invoice_commands command
                        JOIN app.invoices invoice ON invoice.id=command.invoice_id
                        WHERE command.lease_id=lease.id AND command.action='FINAL'
                          AND invoice.status NOT IN ('DRAFT','VOID')) AS final_billed
            ) due
            WHERE unit.property_id=p_property AND due.inspected AND due.final_billed AND due.held>0;
            v_todo := v_todo || v_part;
        END IF;

        IF 'birthdays' = ANY(p_sections) THEN
            -- UI v81 round 4 (owner 08/11/2026): the birthdays of Primary Tenants and Occupants of
            -- active Leases, today and the next 7 days (the Customers page lists them).
            SELECT jsonb_build_object('count', count(*), 'from', v_today, 'to', v_today+7) INTO v_part
            FROM app.customer_birthdays(p_actor, p_property, p_allowed) person
            WHERE person.birthday BETWEEN v_today AND v_today+7;
            v_cards := v_cards || jsonb_build_object('birthdays', v_part);
        END IF;

        RETURN jsonb_build_object('as_of', v_at, 'business_date', v_today, 'timezone', v_timezone,
            'cards', v_cards, 'jobs', v_jobs,
            'todo', (SELECT COALESCE(jsonb_agg(item ORDER BY (item->>'date')::date NULLS LAST,
                item->>'kind', item::text),'[]'::jsonb) FROM jsonb_array_elements(v_todo) item));
    END $$;
"""


def upgrade() -> None:
    op.execute(BIRTHDAYS_SQL)
    op.execute(HOME_SQL)
    for function in (HOME, BIRTHDAYS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the reads are part of the forward-only chain."""
    raise RuntimeError("UI v81 round 4 Home cards migration is forward-only")
