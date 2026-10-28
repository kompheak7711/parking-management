# ruff: noqa: E501
"""Many items on one Miscellaneous Invoice (V1-060 B6; DL-103).

Revision ID: 20270328_247
Revises: 20270327_246
Create Date: 2026-10-28

The owner asked on 2026-10-28 why two charges make two Invoices, and chose "Yes, build it now" on the
decision card with four rules: (1) the quantity is a whole number, the unit price is in US dollars
and cents, and the amount is the quantity times the unit price exactly, with no rounding; (2) when a
Customer pays only part of the Invoice, the money pays the items from the top down (the payment and
Credit proposals already order the lines of one category by their sequence); (3) one reason and one
approval for the whole Invoice; (4) at most 20 items on one Invoice.

- Each item is its own approved one-time charge (app.authorized_nonrecurring_obligations), so a
  line still bills exactly one charge. The charge now keeps the item's whole quantity and unit
  price; a check makes the amount exactly the quantity times the unit price.
- app.create_items_invoice_draft records every item's charge and the Miscellaneous Draft in one
  transaction, with one reason and one approval reference for all of them.
- app.replace_invoice_draft_items changes the items of such a Draft: an item that stays the same
  keeps its charge, a new or changed item gets a new charge, and an item taken off is withdrawn by
  deleting its Draft line (the Draft revision history keeps it, with the reason for the change).
  Only a Draft whose every line bills an item charge can be changed this way (not the move-out
  cleaning charge, a Damage charge or a correction charge), and every charge on it shares the one
  reason and approval reference.
- The Final Settlement preview lists a charge taken off a Draft like a charge a draft correction
  replaced (information, not a blocking issue): staff withdrew it with a reason.

Both commands are SECURITY DEFINER, EXECUTE to prm_financial only, and use the Invoice command
replay of their action ('create' or 'correct').
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270328_247"
down_revision: str | None = "20270327_246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = "app.create_items_invoice_draft(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb)"
REPLACE = "app.replace_invoice_draft_items(uuid,uuid,uuid,uuid,text,integer,uuid,uuid,text,text,text,jsonb,uuid)"
INTERNAL = (
    "app.invoice_items_input(jsonb)",
    "app.record_invoice_item_charge(uuid,uuid,text,timestamp with time zone,uuid,uuid,uuid,uuid,text,integer,bigint,text,text)",
    "app.insert_invoice_item_line(uuid,uuid,integer,uuid,timestamp with time zone)",
)
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"

REMOVED_BEFORE = (
    "                    'replaced',EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text\n"
    "                          AND revision.after_state->>'authorized_obligation_id'\n"
    "                              IS DISTINCT FROM obligation.id::text),\n"
)
REMOVED_AFTER = (
    "                    'replaced',EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text\n"
    "                          AND revision.after_state->>'authorized_obligation_id'\n"
    "                              IS DISTINCT FROM obligation.id::text)\n"
    "                        -- DL-103: an item Edit items took off a Draft was withdrawn with a reason too.\n"
    "                        OR EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='DELETE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text),\n"
)


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
            raise RuntimeError(f"Invoice items source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.authorized_nonrecurring_obligations
            ADD COLUMN quantity integer,
            ADD COLUMN unit_price_usd_cents bigint,
            ADD CONSTRAINT authorized_nonrecurring_item_price CHECK (
                (quantity IS NULL AND unit_price_usd_cents IS NULL)
                OR (quantity IS NOT NULL AND unit_price_usd_cents IS NOT NULL
                    AND quantity BETWEEN 1 AND 9999
                    AND unit_price_usd_cents BETWEEN 1 AND 999999999
                    AND category = 'MISCELLANEOUS_CHARGES'
                    AND quantity::bigint * unit_price_usd_cents = authorized_amount_usd_cents)
            );
        COMMENT ON COLUMN app.authorized_nonrecurring_obligations.quantity IS
            'DL-103: the whole quantity of an item typed on Create Invoice; NULL for every other charge';
        COMMENT ON COLUMN app.authorized_nonrecurring_obligations.unit_price_usd_cents IS
            'DL-103: the unit price of the item in US cents; the amount is exactly quantity times this';

        -- The items of a request: 1 to 20 objects, each with exactly these four keys.
        CREATE FUNCTION app.invoice_items_input(p_items jsonb)
        RETURNS TABLE(item_position integer, charge_id uuid, description text, quantity integer,
            unit_price_usd_cents bigint)
        LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
        DECLARE v_item jsonb; v_ids uuid[]:='{}'::uuid[]; v_id uuid;
            v_quantity numeric; v_price numeric;
        BEGIN
            IF p_items IS NULL OR jsonb_typeof(p_items)<>'array'
                OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
            item_position:=0;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
                item_position:=item_position+1;
                IF jsonb_typeof(v_item)<>'object' THEN
                    RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
                IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v_item) AS key)
                    IS DISTINCT FROM ARRAY['charge_id','description','quantity','unit_price_usd_cents']
                    OR jsonb_typeof(v_item->'charge_id')<>'string'
                    OR jsonb_typeof(v_item->'description')<>'string'
                    OR jsonb_typeof(v_item->'quantity')<>'number'
                    OR jsonb_typeof(v_item->'unit_price_usd_cents')<>'number'
                THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
                BEGIN
                    v_id:=(v_item->>'charge_id')::uuid;
                    v_quantity:=(v_item->>'quantity')::numeric;
                    v_price:=(v_item->>'unit_price_usd_cents')::numeric;
                EXCEPTION WHEN data_exception THEN
                    RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023';
                END;
                description:=v_item->>'description';
                IF v_id='00000000-0000-0000-0000-000000000000'::uuid OR v_id=ANY(v_ids)
                    OR description<>btrim(description) OR length(description) NOT BETWEEN 1 AND 1000
                    OR v_quantity NOT BETWEEN 1 AND 9999 OR v_quantity<>trunc(v_quantity)
                    OR v_price NOT BETWEEN 1 AND 999999999 OR v_price<>trunc(v_price)
                THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
                v_ids:=v_ids||v_id;
                charge_id:=v_id;
                quantity:=v_quantity::integer;
                unit_price_usd_cents:=v_price::bigint;
                RETURN NEXT;
            END LOOP;
        END $$;

        -- One item's approved charge and its audit event, as app.record_one_time_charge writes a
        -- Miscellaneous charge, with the quantity and the unit price.
        CREATE FUNCTION app.record_invoice_item_charge(
            p_property uuid, p_actor uuid, p_timezone text, p_now timestamptz, p_id uuid,
            p_customer uuid, p_lease uuid, p_unit uuid, p_description text, p_quantity integer,
            p_unit_price bigint, p_reason text, p_evidence text
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_audit uuid:=gen_random_uuid(); v_amount bigint:=p_quantity::bigint*p_unit_price;
        BEGIN
            IF EXISTS (SELECT 1 FROM app.authorized_nonrecurring_obligations WHERE id=p_id) THEN
                RAISE EXCEPTION 'One-time charge identity was reused' USING ERRCODE='23505';
            END IF;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
                correlation_id,source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,p_now,timezone(p_timezone,p_now)::date,p_actor,
                'invoice.one_time_charge.recorded','authorized_nonrecurring_obligation',p_id,p_reason,
                'invoices.create',p_property,'{}'::jsonb,
                jsonb_build_object('category','MISCELLANEOUS_CHARGES','amount_usd_cents',v_amount,
                    'quantity',p_quantity,'unit_price_usd_cents',p_unit_price,
                    'description',p_description,'evidence_reference',p_evidence,
                    'inspection_damage_finding_id',NULL),
                p_id,'API','SUCCEEDED',jsonb_build_object('capability','invoices.create'),
                p_customer,p_lease,p_unit);
            INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,category,
                inspection_damage_finding_id,description,authorized_amount_usd_cents,
                governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,
                authorization_reference,due_date_rule,reason,evidence_reference,audit_event_id,
                quantity,unit_price_usd_cents)
            VALUES(p_id,p_customer,p_lease,'MISCELLANEOUS_CHARGES',NULL,p_description,v_amount,NULL,
                'BR-INV-018','one-time-charge:' || p_id::text,p_now,p_actor,'invoices.create',
                'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS',p_reason,p_evidence,v_audit,p_quantity,
                p_unit_price);
        END $$;

        -- The Draft line of one item charge at its place on the Invoice. The trace also keeps the
        -- one reason and approval reference, so Edit items can show them and keep the same items.
        CREATE FUNCTION app.insert_invoice_item_line(
            p_invoice_id uuid, p_actor uuid, p_position integer, p_charge uuid, p_now timestamptz
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_charge app.authorized_nonrecurring_obligations%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_charge FROM app.authorized_nonrecurring_obligations
            WHERE id=p_charge;
            INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,
                amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,
                last_changed_at,created_by,last_changed_by)
            VALUES (gen_random_uuid(),p_invoice_id,p_position,'MISCELLANEOUS_CHARGES',
                v_charge.description,v_charge.authorized_amount_usd_cents,p_charge,
                jsonb_build_object('formula','authorized_source_quantity_times_unit_price',
                    'authorized_obligation_id',p_charge,
                    'authorized_amount_usd_cents',v_charge.authorized_amount_usd_cents,
                    'quantity',v_charge.quantity,
                    'unit_price_usd_cents',v_charge.unit_price_usd_cents,
                    'reason',v_charge.reason,'evidence_reference',v_charge.evidence_reference,
                    'source_reference',v_charge.source_reference),
                p_now,p_now,p_actor,p_actor);
        END $$;

        CREATE FUNCTION app.create_items_invoice_draft(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_invoice_id uuid, p_audit_id uuid, p_correlation_id uuid, p_customer_id uuid,
            p_lease_id uuid, p_reason text, p_evidence_reference text, p_items jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_replay jsonb; v_result jsonb; v_timezone text; v_now timestamptz;
            v_business_date date; v_unit uuid; v_primary uuid; v_total bigint:=0; v_item record;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'create',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_invoice_id IS NULL OR p_invoice_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_audit_id IS NULL OR p_correlation_id IS NULL OR p_customer_id IS NULL
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_evidence_reference IS NULL OR p_evidence_reference<>btrim(p_evidence_reference)
                OR length(p_evidence_reference) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
            PERFORM count(*) FROM app.invoice_items_input(p_items);
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            IF p_lease_id IS NOT NULL THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('invoice-lease:' || p_lease_id::text,0));
                SELECT lease.unit_id,lease.primary_tenant_id INTO v_unit,v_primary
                FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease_id AND unit.property_id=p_property_id;
                IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                    USING ERRCODE='P0002'; END IF;
                IF v_primary<>p_customer_id THEN
                    RAISE EXCEPTION 'One-time charge Customer does not match the Lease'
                        USING ERRCODE='22023'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM app.customers WHERE id=p_customer_id) THEN
                RAISE EXCEPTION 'Customer was not found' USING ERRCODE='P0002';
            END IF;
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            FOR v_item IN SELECT * FROM app.invoice_items_input(p_items) ORDER BY item_position LOOP
                PERFORM app.record_invoice_item_charge(p_property_id,p_actor_id,v_timezone,v_now,
                    v_item.charge_id,p_customer_id,p_lease_id,v_unit,v_item.description,
                    v_item.quantity,v_item.unit_price_usd_cents,p_reason,p_evidence_reference);
                v_total:=v_total+v_item.quantity::bigint*v_item.unit_price_usd_cents;
            END LOOP;
            INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,
                status,invoice_date,due_date,original_total_usd_cents,due_date_rule,
                due_date_source,created_at,created_by,updated_at,updated_by)
            VALUES (p_invoice_id,'INV-'||to_char(v_business_date,'YYYYMMDD')||'-'||
                    upper(substr(replace(p_invoice_id::text,'-',''),1,12)),
                p_customer_id,p_lease_id,'MISCELLANEOUS_CHARGES','DRAFT',v_business_date,NULL,
                v_total,'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS','BR-INV-018',v_now,p_actor_id,v_now,
                p_actor_id);
            FOR v_item IN SELECT * FROM app.invoice_items_input(p_items) ORDER BY item_position LOOP
                PERFORM app.insert_invoice_item_line(p_invoice_id,p_actor_id,v_item.item_position,
                    v_item.charge_id,v_now);
            END LOOP;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.created','invoice',
                p_invoice_id,'Invoice DRAFT created from typed items','invoices.create',
                p_property_id,'{}'::jsonb,v_result,p_correlation_id,'API','SUCCEEDED',
                jsonb_build_object('capability','invoices.create','authorized_obligation_ids',
                    (SELECT jsonb_agg(item.charge_id ORDER BY item.item_position)
                     FROM app.invoice_items_input(p_items) AS item)),
                p_customer_id,p_lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'create',
                p_idempotency_key,p_request_digest,p_invoice_id,201::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.replace_invoice_draft_items(
            p_property_id uuid, p_invoice_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_expected_version integer, p_customer_id uuid,
            p_lease_id uuid, p_reason text, p_evidence_reference text, p_change_reason text,
            p_items jsonb, p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_invoice app.invoices%ROWTYPE;
            v_charge app.authorized_nonrecurring_obligations%ROWTYPE; v_item record;
            v_timezone text; v_now timestamptz; v_unit uuid; v_primary uuid; v_total bigint:=0;
            v_kept uuid[]:='{}'::uuid[]; v_lock_lease uuid;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'correct',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_audit_id IS NULL OR p_customer_id IS NULL
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_evidence_reference IS NULL OR p_evidence_reference<>btrim(p_evidence_reference)
                OR length(p_evidence_reference) NOT BETWEEN 1 AND 500
                OR p_change_reason IS NULL OR p_change_reason<>btrim(p_change_reason)
                OR length(p_change_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
            PERFORM count(*) FROM app.invoice_items_input(p_items);
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504';
            END IF;
            IF v_invoice.version=2147483647 THEN
                RAISE EXCEPTION 'Invoice version cannot advance' USING ERRCODE='P4507';
            END IF;
            IF v_invoice.status<>'DRAFT' OR v_invoice.originating_billing_run_attempt_id IS NOT NULL
                OR v_invoice.primary_category<>'MISCELLANEOUS_CHARGES'
                OR NOT EXISTS (SELECT 1 FROM app.invoice_lines WHERE invoice_id=p_invoice_id)
                OR EXISTS (SELECT 1 FROM app.invoice_lines AS line
                    JOIN app.authorized_nonrecurring_obligations AS charge
                      ON charge.id=line.authorized_obligation_id
                    WHERE line.invoice_id=p_invoice_id AND charge.quantity IS NULL)
            THEN RAISE EXCEPTION 'Only a Draft made from typed items can be changed'
                USING ERRCODE='P4502'; END IF;
            FOR v_lock_lease IN SELECT DISTINCT lease_id
                FROM unnest(ARRAY[v_invoice.lease_id,p_lease_id]) AS leases(lease_id)
                WHERE lease_id IS NOT NULL ORDER BY lease_id LOOP
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('invoice-lease:' || v_lock_lease::text,0));
            END LOOP;
            IF p_lease_id IS NOT NULL THEN
                SELECT lease.unit_id,lease.primary_tenant_id INTO v_unit,v_primary
                FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease_id AND unit.property_id=p_property_id;
                IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                    USING ERRCODE='P0002'; END IF;
                IF v_primary<>p_customer_id THEN
                    RAISE EXCEPTION 'One-time charge Customer does not match the Lease'
                        USING ERRCODE='22023'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM app.customers WHERE id=p_customer_id) THEN
                RAISE EXCEPTION 'Customer was not found' USING ERRCODE='P0002';
            END IF;
            -- An item that stays keeps its charge: the charge is on this Draft with the same values
            -- and the same reason and approval reference. Any other known charge is a reused id.
            FOR v_item IN SELECT * FROM app.invoice_items_input(p_items) ORDER BY item_position LOOP
                SELECT * INTO v_charge FROM app.authorized_nonrecurring_obligations
                WHERE id=v_item.charge_id;
                IF FOUND THEN
                    IF NOT EXISTS (SELECT 1 FROM app.invoice_lines WHERE invoice_id=p_invoice_id
                            AND authorized_obligation_id=v_item.charge_id)
                        OR v_charge.customer_id<>p_customer_id
                        OR v_charge.lease_id IS DISTINCT FROM p_lease_id
                        OR v_charge.description<>v_item.description
                        OR v_charge.quantity IS DISTINCT FROM v_item.quantity
                        OR v_charge.unit_price_usd_cents IS DISTINCT FROM v_item.unit_price_usd_cents
                        OR v_charge.reason IS DISTINCT FROM p_reason
                        OR v_charge.evidence_reference IS DISTINCT FROM p_evidence_reference
                    THEN RAISE EXCEPTION 'One-time charge identity was reused'
                        USING ERRCODE='23505'; END IF;
                    v_kept:=v_kept||v_item.charge_id;
                END IF;
                v_total:=v_total+v_item.quantity::bigint*v_item.unit_price_usd_cents;
            END LOOP;
            v_now:=clock_timestamp();
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            PERFORM set_config('app.draft_correction_actor_id',p_actor_id::text,true);
            PERFORM set_config('app.draft_correction_reason',p_change_reason,true);
            UPDATE app.invoices SET customer_id=p_customer_id,lease_id=p_lease_id,
                original_total_usd_cents=v_total,version=version+1,updated_at=v_now,
                updated_by=p_actor_id
            WHERE id=p_invoice_id;
            -- A changed or removed item's line goes; the Draft revision history keeps it.
            DELETE FROM app.invoice_lines WHERE invoice_id=p_invoice_id
                AND NOT (authorized_obligation_id=ANY(v_kept));
            -- Kept lines that move wait past the last place, so no two lines share a place.
            UPDATE app.invoice_lines AS line SET line_sequence=100+item.item_position,
                last_changed_by=p_actor_id
            FROM app.invoice_items_input(p_items) AS item
            WHERE line.invoice_id=p_invoice_id AND line.authorized_obligation_id=item.charge_id
              AND line.line_sequence<>item.item_position;
            FOR v_item IN SELECT * FROM app.invoice_items_input(p_items) ORDER BY item_position LOOP
                IF NOT (v_item.charge_id=ANY(v_kept)) THEN
                    PERFORM app.record_invoice_item_charge(p_property_id,p_actor_id,v_timezone,
                        v_now,v_item.charge_id,p_customer_id,p_lease_id,v_unit,v_item.description,
                        v_item.quantity,v_item.unit_price_usd_cents,p_reason,p_evidence_reference);
                    PERFORM app.insert_invoice_item_line(p_invoice_id,p_actor_id,
                        v_item.item_position,v_item.charge_id,v_now);
                END IF;
            END LOOP;
            UPDATE app.invoice_lines AS line SET line_sequence=item.item_position,
                last_changed_by=p_actor_id
            FROM app.invoice_items_input(p_items) AS item
            WHERE line.invoice_id=p_invoice_id AND line.authorized_obligation_id=item.charge_id
              AND line.line_sequence=100+item.item_position;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,timezone(v_timezone,v_now)::date,p_actor_id,
                'invoice.draft_corrected','invoice',p_invoice_id,p_change_reason,'invoices.create',
                p_property_id,v_before,v_result,p_idempotency_key,'API','SUCCEEDED',
                jsonb_build_object('capability','invoices.create','authorized_obligation_ids',
                    (SELECT jsonb_agg(item.charge_id ORDER BY item.item_position)
                     FROM app.invoice_items_input(p_items) AS item)),
                p_customer_id,p_lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'correct',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;
    """)
    _patch(PREVIEW, ((REMOVED_BEFORE, REMOVED_AFTER),))
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (CREATE, REPLACE):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("V1-060 Invoice items migration is forward-only")
