# ruff: noqa: E501
"""V1-057 step 1: the report and export rights, and the Home page read (API-076, DL-072, DL-079).

1. Three new catalog rights (bundle grant path; capability names decided by Claude under the
   owner's 2026-10-23 22:30 rule, from the DL-072 answer 5 access the owner set):
   `reports.read` (the money reports and the four totals by Unit and month), `audit.export` (the
   audit history file, separate from the audit search `audit.view`, SEC-032) and `data.export`
   (a report file). The Staff reports (Unit occupancy, Lease dates and Utility consumption
   without amounts) need only the read rights Staff already hold, so no Staff bundle changes.
2. Each Property's default Owner and Manager bundles get a new version holding their current set
   plus the three rights (DL-072 answer 5: Owner and Manager get every report, audit search,
   audit export and data export), through the normal version history, with one audit event
   each. New Properties get them through the seed function, which gives the Owner and Manager
   bundles every `bundle` catalog row.
3. `app.report_actor_property(actor, property, allowed)`: the bounded-read guard of the V1-057
   reads. The database checks the active human actor and that the Property is one of those the
   application passes from the actor's grants; the application checks the capabilities.
4. `app.home_page(actor, property, allowed, sections)`: the eight Home cards and the dated
   to-do items (DL-079 answer 9, DESIGN.md Home). The application passes the sections the
   actor may see, from the read rights each needs; a section not passed is left out whole.

New relations: none. New functions only, plus new bundle versions; nothing is removed.
"""

import re

from alembic import op

revision = "20270301_220"
down_revision = "20270218_206"
branch_labels = None
depends_on = None

NEW_CAPABILITIES = (
    ("audit.export", "Export the audit history"),
    ("data.export", "Export report data"),
    ("reports.read", "Read the money reports and the totals by Unit and month"),
)
REASON = (
    "Owner answer DL-072 answer 5: the Owner and the Manager get every report, the audit export "
    "and the data export"
)
GUARD = "app.report_actor_property(uuid,uuid,uuid[])"
HOME = "app.home_page(uuid,uuid,uuid[],text[])"
SECTIONS = (
    "units",
    "invoices",
    "payments",
    "leases",
    "reservations",
    "approvals",
    "deposit_decisions",
    "readings",
    "letters",
    "settlements",
)

GUARD_SQL = """
    CREATE FUNCTION app.report_actor_property(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE v_timezone text;
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
            JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
            WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
              AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'Report reader is not an active person' USING ERRCODE='42501'; END IF;
        IF p_property IS NULL OR NOT p_property=ANY(COALESCE(p_allowed,'{}'::uuid[]))
        THEN RAISE EXCEPTION 'Report Property is not allowed' USING ERRCODE='42501'; END IF;
        SELECT property.timezone_name INTO v_timezone FROM app.properties property
        WHERE property.id=p_property;
        IF v_timezone IS NULL
        THEN RAISE EXCEPTION 'Report Property is not allowed' USING ERRCODE='42501'; END IF;
        RETURN v_timezone;
    END $$;
"""

# The Home page. Amounts are integer cents; every count and amount is worked out from the
# records as they are at the statement time, in the Property's own time zone.
HOME_SQL = """
    CREATE FUNCTION app.home_page(p_actor uuid, p_property uuid, p_allowed uuid[], p_sections text[])
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
    BEGIN
        IF p_sections IS NULL OR array_position(p_sections, NULL) IS NOT NULL
            OR EXISTS(SELECT 1 FROM unnest(p_sections) s WHERE s NOT IN (__SECTIONS__))
        THEN RAISE EXCEPTION 'Home page sections are invalid' USING ERRCODE='22023'; END IF;
        v_today := timezone(v_timezone, v_at)::date;
        v_month_start := date_trunc('month', v_today)::date;
        v_month_end := (v_month_start + interval '1 month' - interval '1 day')::date;
        -- Meters are read on the 24th (DESIGN.md billing calendar; no reading-day setting is
        -- stored yet). Readings dated from that day on count for it.
        v_reading_day := v_month_start + 23;

        IF 'units' = ANY(p_sections) THEN
            SELECT jsonb_build_object('occupied', count(*) FILTER (WHERE unit.status='OCCUPIED'),
                'total', count(*)) INTO v_part
            FROM app.units unit WHERE unit.property_id=p_property;
            v_cards := v_cards || jsonb_build_object('units_occupied', v_part);
        END IF;

        IF 'invoices' = ANY(p_sections) THEN
            WITH open_invoice AS (
                SELECT invoice.id, invoice.due_date, (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)
                    FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS balance
                FROM app.invoices invoice
                LEFT JOIN app.leases lease ON lease.id=invoice.lease_id
                LEFT JOIN app.units unit ON unit.id=lease.unit_id
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID')
                  AND (unit.id IS NULL OR unit.property_id=p_property)
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
                LEFT JOIN app.leases lease ON lease.id=invoice.lease_id
                LEFT JOIN app.units unit ON unit.id=lease.unit_id
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                  AND invoice.due_date BETWEEN v_month_start AND v_month_end
                  AND (unit.id IS NULL OR unit.property_id=p_property)
            )
            SELECT jsonb_build_object('billed_usd_cents', COALESCE(sum(total),0),
                'billed_paid_usd_cents', COALESCE(sum(total-balance),0), 'invoice_count', count(*))
            INTO v_part FROM billed;
            v_cards := jsonb_set(v_cards, '{paid_this_month}',
                COALESCE(v_cards->'paid_this_month','{}'::jsonb) || v_part);
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
        END IF;

        IF 'payments' = ANY(p_sections) THEN
            SELECT jsonb_build_object('received_usd_cents', COALESCE(sum(payment.usd_accounting_value_cents),0),
                'payment_count', count(*)) INTO v_part
            FROM app.payments payment
            WHERE payment.property_id=p_property AND payment.status='RECEIVED'
              AND payment.payment_date BETWEEN v_month_start AND v_month_end;
            v_cards := jsonb_set(v_cards, '{paid_this_month}',
                COALESCE(v_cards->'paid_this_month','{}'::jsonb) || v_part);
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
            v_cards := v_cards || jsonb_build_object('waiting_for_approval',
                jsonb_build_object('count', jsonb_array_length(v_part)));
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

        RETURN jsonb_build_object('as_of', v_at, 'business_date', v_today, 'timezone', v_timezone,
            'cards', v_cards,
            'todo', (SELECT COALESCE(jsonb_agg(item ORDER BY (item->>'date')::date NULLS LAST,
                item->>'kind', item::text),'[]'::jsonb) FROM jsonb_array_elements(v_todo) item));
    END $$;
"""


def upgrade() -> None:
    """Add the three rights, give them to the default Owner and Manager bundles, add the reads."""
    assert all(re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name) for name, _ in NEW_CAPABILITIES)
    for capability, description in NEW_CAPABILITIES:
        op.execute(
            "INSERT INTO app.capabilities "
            "(capability_id, family, description, grant_path, provenance) VALUES "
            f"('{capability}', pg_catalog.split_part('{capability}', '.', 1), '{description}', "
            "'bundle', 'v1-057-reports')"
        )
    added = ", ".join(f"'{capability}'" for capability, _ in NEW_CAPABILITIES)
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
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (seeded.owner_bundle_id, seeded.manager_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, given
                FROM (
                    SELECT held.capability_id AS given FROM app.role_bundle_capabilities AS held
                    WHERE held.role_bundle_id = v_default.role_bundle_id
                      AND held.version = v_default.version
                    UNION
                    SELECT listed FROM pg_catalog.unnest(ARRAY[{added}]::text[]) AS listed
                ) AS next_set;
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
                        '{REASON}', 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'added_capability_ids', pg_catalog.to_jsonb(ARRAY[{added}]::text[])
                        ),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END;
        $$
        """
    )
    op.execute(GUARD_SQL)
    op.execute(HOME_SQL.replace("__SECTIONS__", ", ".join(f"'{s}'" for s in SECTIONS)))
    for function in (GUARD, HOME):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {HOME} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the rights and reads are part of the forward-only chain."""
    raise RuntimeError("V1-057 report rights migration is forward-only")
