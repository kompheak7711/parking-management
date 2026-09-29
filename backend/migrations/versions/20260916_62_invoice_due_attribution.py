# ruff: noqa: E501
"""Preserve approved debit dates and typed within-line financial attribution.

Unpublished V1-055 forward migration under construction. The storage/projection
core now connects Invoice Adjustment commands and atomic evidence. Payment/Credit
posting, populated-history migration, replay and overdue acceptance remain pending.
"""

from alembic import op
from sqlalchemy import text

revision = "20260916_62"
down_revision = "20260915_61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_due_storage()
    create_due_history_readers()
    create_due_integrity_guards()
    create_due_adjustment_commands()
    create_due_application_parts()
    extend_generated_due_proposals()
    create_due_posting_guards()
    extend_atomic_due_posting()
    create_due_designation_builder()
    create_due_preview_wrappers()
    create_due_source_page()
    create_due_overdue_projection()
    connect_due_late_payment_assessment()
    restrict_due_storage()


def create_due_storage() -> None:
    op.execute("""
        CREATE TABLE app.invoice_debit_due_sources (
            invoice_adjustment_id uuid PRIMARY KEY
                REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            approved_due_date date NOT NULL CHECK(isfinite(approved_due_date)),
            governing_source_reference text NOT NULL CHECK(
                governing_source_reference=btrim(governing_source_reference)
                AND length(governing_source_reference) BETWEEN 1 AND 500),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='invoices.adjust')
        );
        CREATE TABLE app.invoice_due_source_parts (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            invoice_line_id uuid NOT NULL REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            debit_adjustment_id uuid REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            payment_detail_id uuid REFERENCES app.payment_allocation_details(id) ON DELETE RESTRICT,
            credit_application_detail_id uuid REFERENCES app.customer_credit_application_details(id) ON DELETE RESTRICT,
            credit_adjustment_id uuid REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            amount_usd_cents bigint NOT NULL CHECK(amount_usd_cents>0),
            part_sequence smallint NOT NULL CHECK(part_sequence>0),
            CHECK(num_nonnulls(payment_detail_id,credit_application_detail_id,credit_adjustment_id)=1)
        );
        CREATE INDEX invoice_due_parts_line_idx ON app.invoice_due_source_parts(invoice_line_id);
        CREATE INDEX invoice_due_parts_debit_idx ON app.invoice_due_source_parts(debit_adjustment_id)
            WHERE debit_adjustment_id IS NOT NULL;
    """)
    for parent in ("payment_detail_id", "credit_application_detail_id", "credit_adjustment_id"):
        op.execute(f"""
            CREATE UNIQUE INDEX invoice_due_parts_{parent}_original_idx
                ON app.invoice_due_source_parts({parent})
                WHERE {parent} IS NOT NULL AND debit_adjustment_id IS NULL;
            CREATE UNIQUE INDEX invoice_due_parts_{parent}_debit_idx
                ON app.invoice_due_source_parts({parent},debit_adjustment_id)
                WHERE {parent} IS NOT NULL AND debit_adjustment_id IS NOT NULL;
            CREATE UNIQUE INDEX invoice_due_parts_{parent}_sequence_idx
                ON app.invoice_due_source_parts({parent},part_sequence)
                WHERE {parent} IS NOT NULL;
        """)


def create_due_history_readers() -> None:
    op.execute("""
        CREATE FUNCTION app.invoice_due_source_history(p_line uuid)
        RETURNS TABLE(source_kind text,source_id uuid,invoice_line_id uuid,approved_due_date date,
            occurred_at timestamptz,amount_usd_cents bigint,reversed_at timestamptz)
        LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT 'ORIGINAL_LINE'::text,line.id,line.id,invoice.due_date,invoice.issued_at,
                line.amount_usd_cents,NULL::timestamptz
            FROM app.invoice_lines line JOIN app.invoices invoice ON invoice.id=line.invoice_id
            WHERE line.id=p_line AND invoice.issued_at IS NOT NULL
            UNION ALL
            SELECT 'DEBIT_ADJUSTMENT',adjustment.id,adjustment.invoice_line_id,due.approved_due_date,
                adjustment.occurred_at,adjustment.amount_usd_cents,reversal.occurred_at
            FROM app.invoice_adjustments adjustment
            LEFT JOIN app.invoice_debit_due_sources due ON due.invoice_adjustment_id=adjustment.id
            LEFT JOIN app.invoice_adjustment_reversals reversal ON reversal.invoice_adjustment_id=adjustment.id
            WHERE adjustment.invoice_line_id=p_line AND adjustment.adjustment_type='DEBIT'
        $$;

        CREATE FUNCTION app.invoice_due_reduction_history(p_line uuid)
        RETURNS TABLE(effect_kind text,effect_id uuid,invoice_line_id uuid,occurred_at timestamptz,
            amount_usd_cents bigint,reversed_at timestamptz)
        LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT 'PAYMENT_ALLOCATION'::text,detail.id,detail.invoice_line_id,allocation.posted_at,
                detail.posted_amount_usd_cents,reversal.occurred_at
            FROM app.payment_allocation_details detail
            JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
            LEFT JOIN app.payment_allocation_reversals reversal ON reversal.payment_allocation_id=allocation.id
            WHERE detail.invoice_line_id=p_line
            UNION ALL
            SELECT 'CUSTOMER_CREDIT_APPLICATION',detail.id,detail.invoice_line_id,application.occurred_at,
                detail.applied_amount_usd_cents,reversal.occurred_at
            FROM app.customer_credit_application_details detail
            JOIN app.customer_credit_applications application ON application.id=detail.customer_credit_application_id
            LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
            WHERE detail.invoice_line_id=p_line
            UNION ALL
            SELECT 'CREDIT_ADJUSTMENT',adjustment.id,adjustment.invoice_line_id,adjustment.occurred_at,
                adjustment.amount_usd_cents,reversal.occurred_at
            FROM app.invoice_adjustments adjustment
            LEFT JOIN app.invoice_adjustment_reversals reversal ON reversal.invoice_adjustment_id=adjustment.id
            WHERE adjustment.invoice_line_id=p_line AND adjustment.adjustment_type='CREDIT'
        $$;

        CREATE FUNCTION app.invoice_due_recorded_parts(p_line uuid)
        RETURNS TABLE(effect_kind text,effect_id uuid,source_kind text,source_id uuid,
            amount_usd_cents bigint,part_sequence smallint)
        LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT CASE WHEN part.payment_detail_id IS NOT NULL THEN 'PAYMENT_ALLOCATION'
                    WHEN part.credit_application_detail_id IS NOT NULL THEN 'CUSTOMER_CREDIT_APPLICATION'
                    ELSE 'CREDIT_ADJUSTMENT' END,
                COALESCE(part.payment_detail_id,part.credit_application_detail_id,part.credit_adjustment_id),
                CASE WHEN part.debit_adjustment_id IS NULL THEN 'ORIGINAL_LINE' ELSE 'DEBIT_ADJUSTMENT' END,
                COALESCE(part.debit_adjustment_id,part.invoice_line_id),part.amount_usd_cents,part.part_sequence
            FROM app.invoice_due_source_parts part WHERE part.invoice_line_id=p_line
        $$;

        CREATE FUNCTION app.invoice_line_due_position_at(p_line uuid,p_as_of timestamptz)
        RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_result jsonb; v_invalid boolean;
        BEGIN
            IF p_line IS NULL OR p_line='00000000-0000-0000-0000-000000000000'
                OR p_as_of IS NULL OR NOT isfinite(p_as_of)
            THEN RAISE EXCEPTION 'A line identity and finite assessment timestamp are required'
                USING ERRCODE='23514'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.invoice_due_source_history(p_line)
                WHERE source_kind='ORIGINAL_LINE') THEN RETURN NULL; END IF;
            WITH sources AS MATERIALIZED (
                SELECT * FROM app.invoice_due_source_history(p_line)
            ), reductions AS MATERIALIZED (
                SELECT * FROM app.invoice_due_reduction_history(p_line)
            ), recorded AS MATERIALIZED (
                SELECT * FROM app.invoice_due_recorded_parts(p_line)
            ), active_sources AS (
                SELECT * FROM sources WHERE occurred_at<=p_as_of AND (reversed_at IS NULL OR reversed_at>p_as_of)
            ), active_reductions AS (
                SELECT * FROM reductions WHERE occurred_at<=p_as_of AND (reversed_at IS NULL OR reversed_at>p_as_of)
            ), legacy_original AS (
                SELECT reduction.* FROM active_reductions reduction
                WHERE NOT EXISTS(SELECT 1 FROM recorded part
                    WHERE part.effect_kind=reduction.effect_kind AND part.effect_id=reduction.effect_id)
                  AND NOT EXISTS(SELECT 1 FROM sources source
                    WHERE source.source_kind='DEBIT_ADJUSTMENT' AND source.occurred_at<=reduction.occurred_at)
            ), effective_parts AS (
                SELECT part.effect_kind,part.effect_id,part.source_kind,part.source_id,part.amount_usd_cents
                FROM recorded part JOIN active_reductions reduction
                    ON reduction.effect_kind=part.effect_kind AND reduction.effect_id=part.effect_id
                UNION ALL
                SELECT effect_kind,effect_id,'ORIGINAL_LINE',p_line,amount_usd_cents FROM legacy_original
            ), balances AS (
                SELECT source.*,source.amount_usd_cents::numeric-COALESCE((
                    SELECT sum(part.amount_usd_cents) FROM effective_parts part
                    WHERE part.source_kind=source.source_kind AND part.source_id=source.source_id),0) AS remaining
                FROM active_sources source
            ), aggregate_balance AS (
                SELECT COALESCE((SELECT sum(amount_usd_cents) FROM active_sources),0)
                    -COALESCE((SELECT sum(amount_usd_cents) FROM active_reductions),0) AS remaining
            ), blockers AS (
                SELECT 'MISSING_APPROVED_DUE_DATE'::text AS code,source_kind AS record_kind,source_id AS record_id
                FROM active_sources WHERE approved_due_date IS NULL
                UNION ALL
                SELECT 'AMBIGUOUS_LEGACY_ATTRIBUTION',reduction.effect_kind,reduction.effect_id
                FROM active_reductions reduction
                WHERE NOT EXISTS(SELECT 1 FROM recorded part
                    WHERE part.effect_kind=reduction.effect_kind AND part.effect_id=reduction.effect_id)
                  AND NOT EXISTS(SELECT 1 FROM legacy_original original
                    WHERE original.effect_kind=reduction.effect_kind AND original.effect_id=reduction.effect_id)
            ), violations AS (
                SELECT EXISTS(SELECT 1 FROM balances WHERE remaining<0 OR remaining>9223372036854775807::numeric)
                    OR EXISTS(SELECT 1 FROM aggregate_balance WHERE remaining<0 OR remaining>9223372036854775807::numeric)
                    OR EXISTS(SELECT 1 FROM effective_parts part WHERE NOT EXISTS(
                        SELECT 1 FROM active_sources source
                        WHERE source.source_kind=part.source_kind AND source.source_id=part.source_id))
                    OR EXISTS(SELECT 1 FROM reductions reduction
                        WHERE EXISTS(SELECT 1 FROM recorded part
                            WHERE part.effect_kind=reduction.effect_kind AND part.effect_id=reduction.effect_id)
                          AND reduction.amount_usd_cents<>(SELECT sum(part.amount_usd_cents) FROM recorded part
                            WHERE part.effect_kind=reduction.effect_kind AND part.effect_id=reduction.effect_id))
                    OR EXISTS(SELECT 1 FROM recorded part
                        LEFT JOIN reductions reduction ON reduction.effect_kind=part.effect_kind AND reduction.effect_id=part.effect_id
                        LEFT JOIN sources source ON source.source_kind=part.source_kind AND source.source_id=part.source_id
                        WHERE reduction.effect_id IS NULL OR source.source_id IS NULL
                          OR source.occurred_at>reduction.occurred_at
                          OR source.reversed_at<=reduction.occurred_at
                          OR (source.reversed_at IS NOT NULL
                              AND (reduction.reversed_at IS NULL OR reduction.reversed_at>source.reversed_at))) AS invalid
            )
            SELECT jsonb_build_object('invoice_line_id',p_line,'as_of',p_as_of,
                'aggregate_outstanding_usd_cents',(SELECT remaining FROM aggregate_balance),
                'attribution_complete',NOT EXISTS(SELECT 1 FROM blockers),
                'amounts',CASE WHEN EXISTS(SELECT 1 FROM blockers) THEN '[]'::jsonb ELSE COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('invoice_line_id',p_line,
                        'source_kind',source_kind,'source_id',source_id,'approved_due_date',approved_due_date,
                        'source_occurred_at',occurred_at,'remaining_usd_cents',remaining)
                        ORDER BY source_kind COLLATE "C",source_id) FROM balances),'[]'::jsonb) END,
                'blockers',COALESCE((SELECT jsonb_agg(jsonb_build_object('code',code,'record_kind',record_kind,
                    'record_id',record_id) ORDER BY code COLLATE "C",record_kind COLLATE "C",record_id) FROM blockers),'[]'::jsonb),
                'proven_original_reductions',COALESCE((SELECT jsonb_agg(jsonb_build_object('effect_kind',effect_kind,
                    'effect_id',effect_id) ORDER BY effect_kind COLLATE "C",effect_id) FROM legacy_original),'[]'::jsonb)),
                invalid INTO v_result,v_invalid FROM violations;
            IF v_invalid THEN RAISE EXCEPTION 'Dated financial history has an invalid source balance or dependency'
                USING ERRCODE='23514'; END IF;
            RETURN v_result;
        END $$;
    """)


def create_due_integrity_guards() -> None:
    op.execute("""
        CREATE FUNCTION app.serialize_invoice_debit_due_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_adjustment app.invoice_adjustments%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_adjustment FROM app.invoice_adjustments WHERE id=NEW.invoice_adjustment_id;
            PERFORM app.lock_payment_allocation_target('INVOICE',v_adjustment.invoice_id);
            IF v_adjustment.adjustment_type<>'DEBIT'
                OR NEW.occurred_at IS DISTINCT FROM v_adjustment.occurred_at
                OR NEW.actor_id IS DISTINCT FROM v_adjustment.actor_id
                OR NEW.authorization_reference IS DISTINCT FROM v_adjustment.authorization_reference
            THEN RAISE EXCEPTION 'Approved due evidence must identify its exact debit event'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoice_debit_due_sources_serialize BEFORE INSERT ON app.invoice_debit_due_sources
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_debit_due_source();

        CREATE FUNCTION app.serialize_invoice_due_source_part()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice uuid;
        BEGIN
            SELECT invoice_id INTO STRICT v_invoice FROM app.invoice_lines WHERE id=NEW.invoice_line_id;
            PERFORM app.lock_payment_allocation_target('INVOICE',v_invoice);
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoice_due_source_parts_serialize BEFORE INSERT ON app.invoice_due_source_parts
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_due_source_part();

        CREATE FUNCTION app.validate_invoice_due_source_part()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_kind text; v_effect uuid; v_parent record; v_total numeric; v_count bigint; v_max integer;
        DECLARE v_source record;
        BEGIN
            v_kind:=CASE WHEN NEW.payment_detail_id IS NOT NULL THEN 'PAYMENT_ALLOCATION'
                WHEN NEW.credit_application_detail_id IS NOT NULL THEN 'CUSTOMER_CREDIT_APPLICATION'
                ELSE 'CREDIT_ADJUSTMENT' END;
            v_effect:=COALESCE(NEW.payment_detail_id,NEW.credit_application_detail_id,NEW.credit_adjustment_id);
            SELECT * INTO v_parent FROM app.invoice_due_reduction_history(NEW.invoice_line_id)
                WHERE effect_kind=v_kind AND effect_id=v_effect;
            IF NOT FOUND THEN RAISE EXCEPTION 'Attribution parent does not identify the same Invoice line'
                USING ERRCODE='23514'; END IF;
            SELECT * INTO v_source FROM app.invoice_due_source_history(NEW.invoice_line_id)
                WHERE source_kind=CASE WHEN NEW.debit_adjustment_id IS NULL THEN 'ORIGINAL_LINE' ELSE 'DEBIT_ADJUSTMENT' END
                  AND source_id=COALESCE(NEW.debit_adjustment_id,NEW.invoice_line_id);
            IF NOT FOUND THEN RAISE EXCEPTION 'Attribution source does not identify the same Invoice line'
                USING ERRCODE='23514'; END IF;
            IF v_source.approved_due_date IS NULL OR v_source.occurred_at>v_parent.occurred_at
                OR v_source.reversed_at<=v_parent.occurred_at
                OR (v_source.reversed_at IS NOT NULL
                    AND (v_parent.reversed_at IS NULL OR v_parent.reversed_at>v_source.reversed_at))
            THEN RAISE EXCEPTION 'Attribution requires an existing approved source and resolved reversal dependencies'
                USING ERRCODE='23514'; END IF;
            SELECT sum(amount_usd_cents),count(*),max(part_sequence) INTO v_total,v_count,v_max
            FROM app.invoice_due_recorded_parts(NEW.invoice_line_id)
            WHERE effect_kind=v_kind AND effect_id=v_effect;
            IF v_total IS DISTINCT FROM v_parent.amount_usd_cents::numeric OR v_count<>v_max
            THEN RAISE EXCEPTION 'Attribution parts must preserve the complete amount and contiguous sequence'
                USING ERRCODE='23514'; END IF;
            -- Positive unique contiguous parts guarantee one immutable sequence1 event.
            -- Every row still checks its source and the complete immutable parent sum.
            -- Late extra parts cannot pass that sum after an earlier complete validation.
            IF NEW.part_sequence=1 THEN
                PERFORM app.invoice_line_due_position_at(NEW.invoice_line_id,v_parent.occurred_at);
            END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER invoice_due_source_parts_complete AFTER INSERT ON app.invoice_due_source_parts
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_due_source_part();

        CREATE FUNCTION app.validate_invoice_due_adjustment_reversal()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_line uuid;
        BEGIN
            SELECT invoice_line_id INTO STRICT v_line FROM app.invoice_adjustments
                WHERE id=NEW.invoice_adjustment_id;
            PERFORM app.invoice_line_due_position_at(v_line,NEW.occurred_at);
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER invoice_adjustment_reversal_due_dependencies
            AFTER INSERT ON app.invoice_adjustment_reversals DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_due_adjustment_reversal();
    """)


def restrict_due_storage() -> None:
    for table in ("invoice_debit_due_sources", "invoice_due_source_parts"):
        op.execute(f"""
            CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_history_mutation();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
    for signature in (
        "app.invoice_due_source_history(uuid)",
        "app.invoice_due_reduction_history(uuid)",
        "app.invoice_due_recorded_parts(uuid)",
        "app.invoice_line_due_position_at(uuid,timestamptz)",
        "app.serialize_invoice_debit_due_source()",
        "app.serialize_invoice_due_source_part()",
        "app.validate_invoice_due_source_part()",
        "app.validate_invoice_due_adjustment_reversal()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Financial due-date and attribution evidence is forward-only")


def create_due_adjustment_commands() -> None:
    """Extend the reviewed command without removing its replay or financial guards."""
    op.execute("""
        CREATE FUNCTION app.invoice_credit_correction_parts(
            p_line uuid,p_amount bigint,p_parts jsonb,p_at timestamptz
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
        DECLARE v_position jsonb; v_parts jsonb; v_part jsonb; v_source jsonb;
        DECLARE v_kind text; v_source_id uuid; v_amount bigint; v_total numeric:=0;
        DECLARE v_seen text[]:=ARRAY[]::text[]; v_identity text;
        BEGIN
            v_position:=app.invoice_line_due_position_at(p_line,p_at);
            IF v_position IS NULL OR (v_position->>'attribution_complete')::boolean IS NOT TRUE
            THEN RAISE EXCEPTION 'Dated amount evidence must be resolved before correction'
                USING ERRCODE='P4507'; END IF;
            v_parts:=p_parts;
            IF v_parts IS NULL THEN
                IF EXISTS(SELECT 1 FROM app.invoice_due_source_history(p_line)
                    WHERE source_kind='DEBIT_ADJUSTMENT' AND occurred_at<=p_at)
                THEN RAISE EXCEPTION 'Credit correction requires explicit source parts'
                    USING ERRCODE='P4502'; END IF;
                v_parts:=jsonb_build_array(jsonb_build_object('source_kind','ORIGINAL_LINE',
                    'source_id',p_line,'amount_usd_cents',p_amount));
            END IF;
            IF jsonb_typeof(v_parts) IS DISTINCT FROM 'array'
            THEN RAISE EXCEPTION 'Credit correction parts must be an array' USING ERRCODE='P4502'; END IF;
            IF jsonb_array_length(v_parts) NOT BETWEEN 1 AND 32767
            THEN RAISE EXCEPTION 'Credit correction parts must be bounded and nonempty'
                USING ERRCODE='P4502'; END IF;
            FOR v_part IN SELECT value FROM jsonb_array_elements(v_parts) LOOP
                IF jsonb_typeof(v_part) IS DISTINCT FROM 'object'
                THEN RAISE EXCEPTION 'Credit correction part must be an object' USING ERRCODE='P4502'; END IF;
                IF NOT (v_part ?& ARRAY['source_kind','source_id','amount_usd_cents'])
                    OR (SELECT count(*) FROM jsonb_object_keys(v_part))<>3
                    OR jsonb_typeof(v_part->'source_kind') IS DISTINCT FROM 'string'
                    OR (v_part->>'source_kind') NOT IN ('ORIGINAL_LINE','DEBIT_ADJUSTMENT')
                    OR jsonb_typeof(v_part->'source_id') IS DISTINCT FROM 'string'
                    OR (v_part->>'source_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    OR jsonb_typeof(v_part->'amount_usd_cents') IS DISTINCT FROM 'number'
                    OR (v_part->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                THEN RAISE EXCEPTION 'Credit correction part identity or amount is invalid'
                    USING ERRCODE='P4502'; END IF;
                v_kind:=v_part->>'source_kind'; v_source_id:=(v_part->>'source_id')::uuid;
                v_amount:=(v_part->>'amount_usd_cents')::bigint;
                v_identity:=v_kind||':'||v_source_id::text;
                IF v_source_id='00000000-0000-0000-0000-000000000000'
                    OR v_amount>9000000000000000 OR v_identity=ANY(v_seen)
                THEN RAISE EXCEPTION 'Credit correction sources must be unique and bounded'
                    USING ERRCODE='P4502'; END IF;
                SELECT value INTO v_source FROM jsonb_array_elements(v_position->'amounts')
                    WHERE value->>'source_kind'=v_kind AND (value->>'source_id')::uuid=v_source_id;
                IF NOT FOUND OR v_amount>(v_source->>'remaining_usd_cents')::bigint
                THEN RAISE EXCEPTION 'Credit correction exceeds its identified available source'
                    USING ERRCODE='P4508'; END IF;
                v_seen:=array_append(v_seen,v_identity); v_total:=v_total+v_amount;
            END LOOP;
            IF v_total IS DISTINCT FROM p_amount::numeric
            THEN RAISE EXCEPTION 'Credit correction parts must preserve the exact amount'
                USING ERRCODE='P4502'; END IF;
            RETURN v_parts;
        END $$;
    """)
    signature = (
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)"
    )
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    replacements = (
        (
            "p_audit_id uuid)",
            "p_audit_id uuid, p_approved_due_date date, p_governing_source_reference text, p_correction_parts jsonb)",
        ),
        (
            "DECLARE v_min_resulting numeric; v_resulting numeric;",
            "DECLARE v_min_resulting numeric; v_resulting numeric;\n"
            "        DECLARE v_due_position jsonb; v_parts jsonb; v_part jsonb; v_sequence integer:=0;",
        ),
        (
            "            WITH line_balances AS (",
            """
            IF p_adjustment_type='DEBIT' THEN
                IF p_approved_due_date IS NULL OR NOT isfinite(p_approved_due_date)
                    OR p_governing_source_reference IS NULL
                    OR p_governing_source_reference<>btrim(p_governing_source_reference)
                    OR length(p_governing_source_reference) NOT BETWEEN 1 AND 500
                    OR p_correction_parts IS NOT NULL
                THEN RAISE EXCEPTION 'New debit requires an approved governing due date and reference'
                    USING ERRCODE='P4502'; END IF;
            ELSIF p_approved_due_date IS NOT NULL OR p_governing_source_reference IS NOT NULL THEN
                RAISE EXCEPTION 'Credit correction cannot introduce a governing due date'
                    USING ERRCODE='P4502';
            END IF;
            WITH line_balances AS (""",
        ),
        (
            "            INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,",
            """
            v_due_position:=app.invoice_line_due_position_at(p_line_id,v_now);
            IF v_due_position IS NULL OR (v_due_position->>'attribution_complete')::boolean IS NOT TRUE
            THEN RAISE EXCEPTION 'Dated amount evidence must be resolved before new Adjustment'
                USING ERRCODE='P4507'; END IF;
            IF p_adjustment_type='CREDIT' THEN
                v_parts:=app.invoice_credit_correction_parts(p_line_id,p_amount,p_correction_parts,v_now);
            END IF;
            SET CONSTRAINTS app.invoice_adjustments_due_complete,app.invoice_due_source_parts_complete DEFERRED;
            INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,""",
        ),
        (
            "            UPDATE app.invoices SET status=app.invoice_application_status(p_invoice_id),",
            """
            IF p_adjustment_type='DEBIT' THEN
                INSERT INTO app.invoice_debit_due_sources(invoice_adjustment_id,approved_due_date,
                    governing_source_reference,occurred_at,actor_id,authorization_reference)
                VALUES(p_adjustment_id,p_approved_due_date,p_governing_source_reference,
                    v_now,p_actor_id,'invoices.adjust');
            ELSE
                FOR v_part IN SELECT value FROM jsonb_array_elements(v_parts) LOOP
                    v_sequence:=v_sequence+1;
                    INSERT INTO app.invoice_due_source_parts(id,invoice_line_id,debit_adjustment_id,
                        credit_adjustment_id,amount_usd_cents,part_sequence)
                    VALUES(gen_random_uuid(),p_line_id,
                        CASE WHEN v_part->>'source_kind'='DEBIT_ADJUSTMENT' THEN (v_part->>'source_id')::uuid END,
                        p_adjustment_id,(v_part->>'amount_usd_cents')::bigint,v_sequence);
                END LOOP;
            END IF;
            UPDATE app.invoices SET status=app.invoice_application_status(p_invoice_id),""",
        ),
        (
            "'invoice_line_id',p_line_id),p_adjustment_id,v_invoice.customer_id,",
            "'invoice_line_id',p_line_id,'approved_due_date',p_approved_due_date,\n"
            "                    'governing_source_reference',p_governing_source_reference,\n"
            "                    'correction_parts',v_parts),p_adjustment_id,v_invoice.customer_id,",
        ),
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError("Invoice due command migration source contract changed")
        definition = definition.replace(before, after)
    op.execute(definition)
    op.execute("""
        CREATE OR REPLACE FUNCTION app.adjust_invoice(
            p_property_id uuid,p_invoice_id uuid,p_line_id uuid,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text,p_expected_version integer,
            p_adjustment_type text,p_amount bigint,p_source_reference text,p_reason text,
            p_adjustment_id uuid,p_audit_id uuid
        ) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT app.adjust_invoice(p_property_id,p_invoice_id,p_line_id,p_actor_id,
                p_idempotency_key,p_request_digest,p_expected_version,p_adjustment_type,p_amount,
                p_source_reference,p_reason,p_adjustment_id,p_audit_id,NULL::date,NULL::text,NULL::jsonb)
        $$;
        CREATE FUNCTION app.validate_new_invoice_adjustment_due()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_position jsonb;
        BEGIN
            IF NEW.adjustment_type='DEBIT' THEN
                IF NOT EXISTS(SELECT 1 FROM app.invoice_debit_due_sources
                    WHERE invoice_adjustment_id=NEW.id)
                THEN RAISE EXCEPTION 'New debit requires atomic approved governing due evidence'
                    USING ERRCODE='23514'; END IF;
            ELSE
                IF NOT EXISTS(SELECT 1 FROM app.invoice_due_source_parts
                    WHERE credit_adjustment_id=NEW.id)
                THEN RAISE EXCEPTION 'New credit correction requires atomic source parts'
                    USING ERRCODE='23514'; END IF;
            END IF;
            v_position:=app.invoice_line_due_position_at(NEW.invoice_line_id,NEW.occurred_at);
            IF v_position IS NULL OR (v_position->>'attribution_complete')::boolean IS NOT TRUE
            THEN RAISE EXCEPTION 'New Adjustment requires complete dated amount attribution'
                USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER invoice_adjustments_due_complete AFTER INSERT ON app.invoice_adjustments
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_new_invoice_adjustment_due();
    """)
    for signature in (
        "app.invoice_credit_correction_parts(uuid,bigint,jsonb,timestamptz)",
        "app.validate_new_invoice_adjustment_due()",
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid,date,text,jsonb)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid,date,text,jsonb) TO prm_financial"
    )


def create_due_application_parts() -> None:
    """Prepare deterministic dated evidence; only authorized callers may expose it."""
    op.execute("""
        CREATE FUNCTION app.invoice_line_due_application_parts(
            p_line uuid,p_amount bigint,p_at timestamptz,p_designated jsonb,p_max_parts integer
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_position jsonb; v_source jsonb; v_part jsonb; v_parts jsonb:='[]';
        DECLARE v_left bigint:=p_amount; v_amount bigint; v_total numeric:=0;
        DECLARE v_kind text; v_id uuid; v_identity text; v_seen text[]:=ARRAY[]::text[];
        BEGIN
            IF p_line IS NULL OR p_line='00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_at IS NULL OR NOT isfinite(p_at) OR p_at>clock_timestamp()+interval '5 seconds'
                OR p_max_parts IS NULL OR p_max_parts NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Dated application input is invalid' USING ERRCODE='P4502'; END IF;
            v_position:=app.invoice_line_due_position_at(p_line,p_at);
            IF v_position IS NULL OR (v_position->>'attribution_complete')::boolean IS NOT TRUE
            THEN RAISE EXCEPTION 'Dated amount evidence must be resolved before application'
                USING ERRCODE='P4507'; END IF;
            IF p_amount>(v_position->>'aggregate_outstanding_usd_cents')::bigint
            THEN RAISE EXCEPTION 'Dated application exceeds the selected line balance'
                USING ERRCODE='P4508'; END IF;
            IF p_designated IS NULL THEN
                FOR v_source IN SELECT value FROM jsonb_array_elements(v_position->'amounts')
                    WHERE (value->>'remaining_usd_cents')::bigint>0
                    ORDER BY (value->>'approved_due_date')::date,
                        (value->>'source_occurred_at')::timestamptz,
                        (value->>'source_kind') COLLATE "C",(value->>'source_id')::uuid
                LOOP
                    EXIT WHEN v_left=0 OR jsonb_array_length(v_parts)=p_max_parts;
                    v_amount:=LEAST(v_left,(v_source->>'remaining_usd_cents')::bigint);
                    v_parts:=v_parts||jsonb_build_array(jsonb_build_object(
                        'source_kind',v_source->'source_kind','source_id',v_source->'source_id',
                        'approved_due_date',v_source->'approved_due_date',
                        'source_occurred_at',v_source->'source_occurred_at',
                        'outstanding_usd_cents',v_source->'remaining_usd_cents',
                        'amount_usd_cents',v_amount));
                    v_left:=v_left-v_amount;
                END LOOP;
            ELSE
                IF jsonb_typeof(p_designated) IS DISTINCT FROM 'array'
                THEN RAISE EXCEPTION 'Designated due parts must be an array' USING ERRCODE='P4502'; END IF;
                IF jsonb_array_length(p_designated) NOT BETWEEN 1 AND p_max_parts
                THEN RAISE EXCEPTION 'Designated due parts must fit the complete bounded selection'
                    USING ERRCODE='P4502'; END IF;
                FOR v_part IN SELECT value FROM jsonb_array_elements(p_designated) LOOP
                    IF jsonb_typeof(v_part) IS DISTINCT FROM 'object'
                    THEN RAISE EXCEPTION 'Designated due part must be an object' USING ERRCODE='P4502'; END IF;
                    IF NOT (v_part ?& ARRAY['source_kind','source_id','amount_usd_cents'])
                        OR (SELECT count(*) FROM jsonb_object_keys(v_part))<>3
                        OR jsonb_typeof(v_part->'source_kind') IS DISTINCT FROM 'string'
                        OR (v_part->>'source_kind') NOT IN ('ORIGINAL_LINE','DEBIT_ADJUSTMENT')
                        OR jsonb_typeof(v_part->'source_id') IS DISTINCT FROM 'string'
                        OR (v_part->>'source_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                        OR jsonb_typeof(v_part->'amount_usd_cents') IS DISTINCT FROM 'number'
                        OR (v_part->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                    THEN RAISE EXCEPTION 'Designated due part identity or amount is invalid'
                        USING ERRCODE='P4502'; END IF;
                    v_kind:=v_part->>'source_kind'; v_id:=(v_part->>'source_id')::uuid;
                    v_amount:=(v_part->>'amount_usd_cents')::bigint; v_identity:=v_kind||':'||v_id::text;
                    IF v_id='00000000-0000-0000-0000-000000000000' OR v_amount>9000000000000000
                        OR v_identity=ANY(v_seen)
                    THEN RAISE EXCEPTION 'Designated due parts must be unique and bounded'
                        USING ERRCODE='P4502'; END IF;
                    SELECT value INTO v_source FROM jsonb_array_elements(v_position->'amounts')
                        WHERE value->>'source_kind'=v_kind AND (value->>'source_id')::uuid=v_id;
                    IF NOT FOUND OR v_amount>(v_source->>'remaining_usd_cents')::bigint
                    THEN RAISE EXCEPTION 'Designation exceeds its selected due source'
                        USING ERRCODE='P4508'; END IF;
                    v_seen:=array_append(v_seen,v_identity); v_total:=v_total+v_amount;
                    v_parts:=v_parts||jsonb_build_array(jsonb_build_object(
                        'source_kind',v_source->'source_kind','source_id',v_source->'source_id',
                        'approved_due_date',v_source->'approved_due_date',
                        'source_occurred_at',v_source->'source_occurred_at',
                        'outstanding_usd_cents',v_source->'remaining_usd_cents',
                        'amount_usd_cents',v_amount));
                END LOOP;
                IF v_total IS DISTINCT FROM p_amount::numeric
                THEN RAISE EXCEPTION 'Designated due parts must preserve the exact line amount'
                    USING ERRCODE='P4502'; END IF;
                v_left:=0;
            END IF;
            RETURN jsonb_build_object('invoice_line_id',p_line,'amount_usd_cents',p_amount-v_left,
                'remaining_requested_usd_cents',v_left,
                'basis',CASE WHEN p_designated IS NULL THEN 'EARLIEST_DUE' ELSE 'CUSTOMER_DESIGNATED' END,
                'parts',v_parts);
        END $$;
        REVOKE ALL ON FUNCTION app.invoice_line_due_application_parts(uuid,bigint,timestamptz,jsonb,integer)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    """)


def extend_generated_due_proposals() -> None:
    """Retain accepted producer guards and order while adding bounded dated parts."""
    payment_replacements = (
        (
            "DECLARE v_next_details jsonb; v_next_target jsonb; v_target jsonb;",
            "DECLARE v_next_details jsonb; v_next_target jsonb; v_target jsonb;\n"
            "        DECLARE v_due jsonb; v_due_part_count integer:=0;",
        ),
        (
            "IF v_sequence>=100 OR v_detail_count>=500 THEN",
            "IF v_sequence>=100 OR v_detail_count>=500 OR v_due_part_count>=500 THEN",
        ),
        (
            "                    v_amount:=LEAST(v_remaining,v_line.outstanding);",
            """
                    BEGIN
                        v_due:=app.invoice_line_due_application_parts(v_line.id,
                            LEAST(v_remaining,v_line.outstanding),p_generated_at,NULL,500-v_due_part_count);
                    EXCEPTION
                        WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                            RAISE EXCEPTION 'Invoice dated sources require a fresh resolved Payment proposal'
                                USING ERRCODE='P4904';
                        WHEN SQLSTATE 'P4502' THEN
                            RAISE EXCEPTION 'Invoice dated Payment proposal input is invalid'
                                USING ERRCODE='P4902';
                    END;
                    v_amount:=(v_due->>'amount_usd_cents')::bigint;""",
        ),
        (
            "WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END));",
            "WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END,\n"
            "                        'due_attribution',jsonb_build_object('basis',v_due->'basis','parts',v_due->'parts')));",
        ),
        (
            "                    v_total:=v_total+v_amount; v_remaining:=v_remaining-v_amount;",
            """
                    v_total:=v_total+v_amount; v_remaining:=v_remaining-v_amount;
                    v_due_part_count:=v_due_part_count+jsonb_array_length(v_due->'parts');
                    IF (v_due->>'remaining_requested_usd_cents')::bigint>0 THEN
                        v_has_more:=true; EXIT;
                    END IF;""",
        ),
    )
    credit_replacements = (
        (
            "DECLARE v_details jsonb:='[]'; v_next jsonb; v_line record;",
            "DECLARE v_details jsonb:='[]'; v_next jsonb; v_line record;\n"
            "        DECLARE v_due jsonb; v_due_part_count integer:=0;",
        ),
        (
            "EXIT WHEN jsonb_array_length(v_details)>=500;",
            "EXIT WHEN jsonb_array_length(v_details)>=500 OR v_due_part_count>=500;",
        ),
        (
            "                v_amount:=LEAST(v_remaining,v_line.outstanding);",
            """
                BEGIN
                    v_due:=app.invoice_line_due_application_parts(v_line.id,
                        LEAST(v_remaining,v_line.outstanding),p_generated_at,NULL,500-v_due_part_count);
                EXCEPTION
                    WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                        RAISE EXCEPTION 'Invoice dated sources require a fresh resolved Credit proposal'
                            USING ERRCODE='P5104';
                    WHEN SQLSTATE 'P4502' THEN
                        RAISE EXCEPTION 'Invoice dated Credit proposal input is invalid'
                            USING ERRCODE='P5102';
                END;
                v_amount:=(v_due->>'amount_usd_cents')::bigint;""",
        ),
        (
            "WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END));",
            "WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END,\n"
            "                    'due_attribution',jsonb_build_object('basis',v_due->'basis','parts',v_due->'parts')));",
        ),
        (
            "                v_details:=v_next; v_remaining:=v_remaining-v_amount;",
            """
                v_details:=v_next; v_remaining:=v_remaining-v_amount;
                v_due_part_count:=v_due_part_count+jsonb_array_length(v_due->'parts');
                EXIT WHEN (v_due->>'remaining_requested_usd_cents')::bigint>0;""",
        ),
    )
    for signature, replacements in (
        ("app.payment_allocation_proposal(uuid,uuid,timestamptz,uuid)", payment_replacements),
        ("app.credit_application_proposal(uuid,uuid,uuid,bigint,timestamptz)", credit_replacements),
    ):
        definition = (
            op.get_bind()
            .execute(
                text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
                {"signature": signature},
            )
            .scalar_one()
        )
        for before, after in replacements:
            if definition.count(before) != 1:
                raise RuntimeError("Generated due proposal migration source contract changed")
            definition = definition.replace(before, after)
        op.execute(definition)


def create_due_posting_guards() -> None:
    """Check exact confirmed source facts and complete every new Invoice detail."""
    op.execute("""
        CREATE FUNCTION app.invoice_due_confirmed_parts(
            p_line uuid,p_amount bigint,p_at timestamptz,p_due jsonb,p_default_only boolean
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_part jsonb; v_selected jsonb:='[]'; v_expected jsonb;
        BEGIN
            IF jsonb_typeof(p_due) IS DISTINCT FROM 'object' OR p_default_only IS NULL
            THEN RAISE EXCEPTION 'Fresh dated confirmation is required' USING ERRCODE='P4502'; END IF;
            IF NOT (p_due ?& ARRAY['basis','parts']) OR (SELECT count(*) FROM jsonb_object_keys(p_due))<>2
                OR jsonb_typeof(p_due->'basis') IS DISTINCT FROM 'string'
                OR p_due->>'basis' NOT IN ('EARLIEST_DUE','CUSTOMER_DESIGNATED')
                OR (p_default_only AND p_due->>'basis'<>'EARLIEST_DUE')
                OR jsonb_typeof(p_due->'parts') IS DISTINCT FROM 'array'
            THEN RAISE EXCEPTION 'Dated confirmation shape or basis is invalid' USING ERRCODE='P4502'; END IF;
            IF jsonb_array_length(p_due->'parts') NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Dated confirmation parts must be bounded' USING ERRCODE='P4502'; END IF;
            FOR v_part IN SELECT value FROM jsonb_array_elements(p_due->'parts') LOOP
                IF jsonb_typeof(v_part) IS DISTINCT FROM 'object'
                THEN RAISE EXCEPTION 'Dated confirmation part must be an object' USING ERRCODE='P4502'; END IF;
                IF NOT (v_part ?& ARRAY['source_kind','source_id','approved_due_date',
                        'source_occurred_at','outstanding_usd_cents','amount_usd_cents'])
                    OR (SELECT count(*) FROM jsonb_object_keys(v_part))<>6
                    OR jsonb_typeof(v_part->'source_kind') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_part->'source_id') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_part->'approved_due_date') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_part->'source_occurred_at') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_part->'outstanding_usd_cents') IS DISTINCT FROM 'number'
                    OR (v_part->>'outstanding_usd_cents') !~ '^(0|[1-9][0-9]{0,18})$'
                    OR jsonb_typeof(v_part->'amount_usd_cents') IS DISTINCT FROM 'number'
                    OR (v_part->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                THEN RAISE EXCEPTION 'Dated confirmation requires exact typed source facts'
                    USING ERRCODE='P4502'; END IF;
                IF (v_part->>'outstanding_usd_cents')::numeric>9223372036854775807
                    OR (v_part->>'amount_usd_cents')::bigint>9000000000000000
                THEN RAISE EXCEPTION 'Dated confirmation amount exceeds its bound' USING ERRCODE='P4502'; END IF;
                v_selected:=v_selected||jsonb_build_array(jsonb_build_object(
                    'source_kind',v_part->'source_kind','source_id',v_part->'source_id',
                    'amount_usd_cents',v_part->'amount_usd_cents'));
            END LOOP;
            v_expected:=app.invoice_line_due_application_parts(p_line,p_amount,p_at,
                CASE WHEN p_due->>'basis'='CUSTOMER_DESIGNATED' THEN v_selected END,500);
            IF (v_expected->>'remaining_requested_usd_cents')::bigint<>0
                OR p_due IS DISTINCT FROM jsonb_build_object('basis',v_expected->'basis','parts',v_expected->'parts')
            THEN RAISE EXCEPTION 'Dated confirmation changed; obtain a fresh preview' USING ERRCODE='P4508'; END IF;
            RETURN v_expected->'parts';
        END $$;

        CREATE FUNCTION app.validate_new_invoice_application_due()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_kind text; v_parent record; v_sum numeric; v_count bigint; v_max integer;
        DECLARE v_header uuid; v_payment uuid; v_batch uuid; v_batch_count bigint;
        BEGIN
            IF NEW.invoice_line_id IS NULL THEN RETURN NULL; END IF;
            v_kind:=CASE WHEN TG_TABLE_NAME='payment_allocation_details'
                THEN 'PAYMENT_ALLOCATION' ELSE 'CUSTOMER_CREDIT_APPLICATION' END;
            SELECT * INTO STRICT v_parent FROM app.invoice_due_reduction_history(NEW.invoice_line_id)
                WHERE effect_kind=v_kind AND effect_id=NEW.id;
            SELECT sum(amount_usd_cents),count(*),max(part_sequence) INTO v_sum,v_count,v_max
                FROM app.invoice_due_recorded_parts(NEW.invoice_line_id)
                WHERE effect_kind=v_kind AND effect_id=NEW.id;
            IF v_count NOT BETWEEN 1 AND 500 OR v_count IS DISTINCT FROM v_max::bigint
                OR v_sum IS DISTINCT FROM v_parent.amount_usd_cents::numeric
            THEN RAISE EXCEPTION 'New Invoice application requires complete atomic dated parts'
                USING ERRCODE='23514'; END IF;
            IF TG_TABLE_NAME='payment_allocation_details' THEN
                SELECT id,payment_id,proposal_batch_id INTO STRICT v_header,v_payment,v_batch
                    FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;
                SELECT count(*) INTO v_batch_count FROM app.invoice_due_source_parts part
                    JOIN app.payment_allocation_details detail ON detail.id=part.payment_detail_id
                    JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
                    WHERE allocation.payment_id=v_payment AND (
                        (v_batch IS NOT NULL AND allocation.proposal_batch_id=v_batch)
                        OR (v_batch IS NULL AND allocation.id=v_header));
            ELSE
                SELECT count(*) INTO v_batch_count FROM app.invoice_due_source_parts part
                    JOIN app.customer_credit_application_details detail ON detail.id=part.credit_application_detail_id
                    WHERE detail.customer_credit_application_id=NEW.customer_credit_application_id;
            END IF;
            IF v_batch_count>500 THEN RAISE EXCEPTION 'Dated application batch exceeds its part bound'
                USING ERRCODE='23514'; END IF;
            PERFORM app.invoice_line_due_position_at(NEW.invoice_line_id,v_parent.occurred_at);
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER payment_details_due_complete
            AFTER INSERT ON app.payment_allocation_details DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_new_invoice_application_due();
        CREATE CONSTRAINT TRIGGER credit_details_due_complete
            AFTER INSERT ON app.customer_credit_application_details DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_new_invoice_application_due();
        REVOKE ALL ON FUNCTION app.invoice_due_confirmed_parts(uuid,bigint,timestamptz,jsonb,boolean),
            app.validate_new_invoice_application_due() FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    """)


def extend_atomic_due_posting() -> None:
    """Append verified parts inside existing locked commands without changing replay."""
    payment_replacements = (
        (
            "DECLARE v_ids jsonb:='[]';",
            "DECLARE v_ids jsonb:='[]';\n"
            "        DECLARE v_due_parts jsonb; v_due_part jsonb; v_due_detail uuid;\n"
            "        DECLARE v_due_sequence integer; v_due_count integer:=0;",
        ),
        (
            "                    SELECT customer_id INTO v_customer FROM app.invoices WHERE id=v_invoice;",
            """
                    SELECT customer_id INTO v_customer FROM app.invoices WHERE id=v_invoice;
                    IF NOT v_generated THEN
                        IF jsonb_typeof(v_target->'invoice_version') IS DISTINCT FROM 'number'
                            OR (v_target->>'invoice_version') !~ '^[1-9][0-9]{0,9}$'
                        THEN RAISE EXCEPTION 'Fresh designated Invoice version is required' USING ERRCODE='P4904'; END IF;
                        IF (v_target->>'invoice_version')::bigint IS DISTINCT FROM
                            (SELECT version::bigint FROM app.invoices WHERE id=v_invoice)
                        THEN RAISE EXCEPTION 'Designated Invoice changed; obtain a fresh preview' USING ERRCODE='P4904'; END IF;
                    END IF;""",
        ),
        (
            "                        INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,",
            """
                        BEGIN
                            v_due_parts:=app.invoice_due_confirmed_parts(v_line.id,
                                (v_detail->>'amount_usd_cents')::bigint,v_now,v_detail->'due_attribution',v_generated);
                        EXCEPTION
                            WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                                RAISE EXCEPTION 'Dated Payment confirmation changed; obtain a fresh preview' USING ERRCODE='P4904';
                            WHEN SQLSTATE 'P4502' THEN
                                RAISE EXCEPTION 'Fresh exact dated Payment confirmation is required' USING ERRCODE='P4902';
                        END;
                        v_due_count:=v_due_count+jsonb_array_length(v_due_parts);
                        IF v_due_count>500 THEN RAISE EXCEPTION 'Payment due-part batch exceeds bound' USING ERRCODE='P4902'; END IF;
                        v_due_detail:=gen_random_uuid(); v_due_sequence:=0;
                        INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,""",
        ),
        (
            "VALUES(gen_random_uuid(),v_id,v_line.id,'INVOICE_LINE',v_line.category,",
            "VALUES(v_due_detail,v_id,v_line.id,'INVOICE_LINE',v_line.category,",
        ),
        (
            "                            v_sequence::smallint,jsonb_build_object('confirmed_detail',v_detail,\n"
            "                                'designation_reference',v_reference));",
            """
                            v_sequence::smallint,jsonb_build_object('confirmed_detail',v_detail,
                                'designation_reference',v_reference));
                        FOR v_due_part IN SELECT value FROM jsonb_array_elements(v_due_parts) LOOP
                            v_due_sequence:=v_due_sequence+1;
                            INSERT INTO app.invoice_due_source_parts(id,invoice_line_id,debit_adjustment_id,
                                payment_detail_id,amount_usd_cents,part_sequence)
                            VALUES(gen_random_uuid(),v_line.id,
                                CASE WHEN v_due_part->>'source_kind'='DEBIT_ADJUSTMENT' THEN (v_due_part->>'source_id')::uuid END,
                                v_due_detail,(v_due_part->>'amount_usd_cents')::bigint,v_due_sequence);
                        END LOOP;""",
        ),
    )
    credit_replacements = (
        (
            "DECLARE v_id uuid:=gen_random_uuid(); v_now timestamptz; v_sequence smallint:=0; v_line app.invoice_lines%ROWTYPE;",
            "DECLARE v_id uuid:=gen_random_uuid(); v_now timestamptz; v_sequence smallint:=0; v_line app.invoice_lines%ROWTYPE;\n"
            "        DECLARE v_due_parts jsonb; v_due_part jsonb; v_due_detail uuid;\n"
            "        DECLARE v_due_sequence integer; v_due_count integer:=0;",
        ),
        (
            "p_intent-ARRAY['mode','invoice_id','late_payment_charge_id','amount_usd_cents','details','designation_reference']<>'{}'",
            "p_intent-ARRAY['mode','invoice_id','late_payment_charge_id','amount_usd_cents','details','designation_reference','invoice_version']<>'{}'",
        ),
        (
            "            v_now:=clock_timestamp();",
            """
            IF v_invoice IS NOT NULL AND v_proposal IS NULL THEN
                IF jsonb_typeof(p_intent->'invoice_version') IS DISTINCT FROM 'number'
                    OR (p_intent->>'invoice_version') !~ '^[1-9][0-9]{0,9}$'
                THEN RAISE EXCEPTION 'Fresh designated Invoice version is required' USING ERRCODE='P5104'; END IF;
                IF (p_intent->>'invoice_version')::bigint IS DISTINCT FROM
                    (SELECT version::bigint FROM app.invoices WHERE id=v_invoice)
                THEN RAISE EXCEPTION 'Designated Invoice changed; obtain a fresh preview' USING ERRCODE='P5104'; END IF;
            END IF;
            v_now:=clock_timestamp();""",
        ),
        (
            "v_detail-ARRAY['invoice_line_id','amount_usd_cents']<>'{}'",
            "v_detail-ARRAY['invoice_line_id','amount_usd_cents','due_attribution']<>'{}'",
        ),
        (
            "                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,invoice_line_id,",
            """
                    BEGIN
                        v_due_parts:=app.invoice_due_confirmed_parts(v_line.id,
                            (v_detail->>'amount_usd_cents')::bigint,v_now,v_detail->'due_attribution',v_proposal IS NOT NULL);
                    EXCEPTION
                        WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                            RAISE EXCEPTION 'Dated Credit confirmation changed; obtain a fresh preview' USING ERRCODE='P5104';
                        WHEN SQLSTATE 'P4502' THEN
                            RAISE EXCEPTION 'Fresh exact dated Credit confirmation is required' USING ERRCODE='P5102';
                    END;
                    v_due_count:=v_due_count+jsonb_array_length(v_due_parts);
                    IF v_due_count>500 THEN RAISE EXCEPTION 'Credit due-part batch exceeds bound' USING ERRCODE='P5102'; END IF;
                    v_due_detail:=gen_random_uuid(); v_due_sequence:=0;
                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,invoice_line_id,""",
        ),
        (
            "VALUES(gen_random_uuid(),v_id,v_line.id,'INVOICE_LINE',v_line.category,",
            "VALUES(v_due_detail,v_id,v_line.id,'INVOICE_LINE',v_line.category,",
        ),
        (
            "                        v_sequence,jsonb_build_object('confirmed_detail',v_detail,'designation_reference',v_reference));",
            """
                        v_sequence,jsonb_build_object('confirmed_detail',v_detail,'designation_reference',v_reference));
                    FOR v_due_part IN SELECT value FROM jsonb_array_elements(v_due_parts) LOOP
                        v_due_sequence:=v_due_sequence+1;
                        INSERT INTO app.invoice_due_source_parts(id,invoice_line_id,debit_adjustment_id,
                            credit_application_detail_id,amount_usd_cents,part_sequence)
                        VALUES(gen_random_uuid(),v_line.id,
                            CASE WHEN v_due_part->>'source_kind'='DEBIT_ADJUSTMENT' THEN (v_due_part->>'source_id')::uuid END,
                            v_due_detail,(v_due_part->>'amount_usd_cents')::bigint,v_due_sequence);
                    END LOOP;""",
        ),
    )
    for signature, replacements in (
        ("app.post_payment_allocations(uuid,uuid,uuid,uuid,text,jsonb)", payment_replacements),
        ("app.post_credit_application(uuid,uuid,uuid,uuid,jsonb)", credit_replacements),
    ):
        definition = (
            op.get_bind()
            .execute(
                text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
                {"signature": signature},
            )
            .scalar_one()
        )
        for before, after in replacements:
            if definition.count(before) != 1:
                raise RuntimeError("Atomic due posting migration source contract changed")
            definition = definition.replace(before, after)
        op.execute(definition)


def create_due_designation_builder() -> None:
    """Build exact read-only designation evidence for authorized outer wrappers."""
    op.execute("""
        CREATE FUNCTION app.invoice_due_designated_details(
            p_invoice uuid,p_amount bigint,p_details jsonb,p_at timestamptz,p_max_parts integer
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_detail jsonb; v_line uuid; v_amount bigint;
        DECLARE v_seen uuid[]:=ARRAY[]::uuid[]; v_sum numeric:=0; v_count integer:=0;
        DECLARE v_selected jsonb; v_details jsonb:='[]'; v_result jsonb;
        BEGIN
            IF p_invoice IS NULL OR p_invoice='00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_at IS NULL OR NOT isfinite(p_at) OR p_at>clock_timestamp()+interval '5 seconds'
                OR p_max_parts IS NULL OR p_max_parts NOT BETWEEN 1 AND 500
                OR jsonb_typeof(p_details) IS DISTINCT FROM 'array'
            THEN RAISE EXCEPTION 'Designated Invoice preview input is invalid' USING ERRCODE='P4502'; END IF;
            IF jsonb_array_length(p_details) NOT BETWEEN 1 AND 500 OR octet_length(p_details::text)>250000
            THEN RAISE EXCEPTION 'Designated Invoice details must be bounded' USING ERRCODE='P4502'; END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice
                AND issued_at IS NOT NULL AND status IN ('UNPAID','PARTIALLY_PAID','PAID');
            IF NOT FOUND THEN RAISE EXCEPTION 'Issued Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_at<GREATEST(v_invoice.issued_at,v_invoice.updated_at,
                    app.allocation_target_latest_at('INVOICE',p_invoice))
            THEN RAISE EXCEPTION 'Designated Invoice preview predates current dependencies'
                USING ERRCODE='P4508'; END IF;
            FOR v_detail IN SELECT value FROM jsonb_array_elements(p_details) LOOP
                IF jsonb_typeof(v_detail) IS DISTINCT FROM 'object'
                THEN RAISE EXCEPTION 'Designated Invoice detail must be an object' USING ERRCODE='P4502'; END IF;
                IF NOT(v_detail ?& ARRAY['invoice_line_id','amount_usd_cents'])
                    OR v_detail-ARRAY['invoice_line_id','amount_usd_cents','source_parts']<>'{}'
                    OR jsonb_typeof(v_detail->'invoice_line_id') IS DISTINCT FROM 'string'
                    OR (v_detail->>'invoice_line_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    OR jsonb_typeof(v_detail->'amount_usd_cents') IS DISTINCT FROM 'number'
                    OR (v_detail->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                THEN RAISE EXCEPTION 'Designated Invoice detail requires exact identity and cents'
                    USING ERRCODE='P4502'; END IF;
                v_line:=(v_detail->>'invoice_line_id')::uuid;
                v_amount:=(v_detail->>'amount_usd_cents')::bigint;
                IF v_amount>9000000000000000 OR v_line=ANY(v_seen)
                    OR NOT EXISTS(SELECT 1 FROM app.invoice_lines WHERE id=v_line AND invoice_id=p_invoice)
                THEN RAISE EXCEPTION 'Designated Invoice lines must be unique and belong to the target'
                    USING ERRCODE='P4502'; END IF;
                IF v_count>=p_max_parts
                THEN RAISE EXCEPTION 'The complete designation must fit its part budget'
                    USING ERRCODE='P4502'; END IF;
                v_selected:=app.invoice_line_due_application_parts(v_line,v_amount,p_at,
                    v_detail->'source_parts',p_max_parts-v_count);
                IF (v_selected->>'remaining_requested_usd_cents')::bigint<>0
                THEN RAISE EXCEPTION 'The complete designated line must fit its part budget'
                    USING ERRCODE='P4502'; END IF;
                v_count:=v_count+jsonb_array_length(v_selected->'parts');
                v_sum:=v_sum+v_amount;v_seen:=array_append(v_seen,v_line);
                v_details:=v_details||jsonb_build_array(jsonb_build_object(
                    'invoice_line_id',v_line,'amount_usd_cents',v_amount,
                    'due_attribution',jsonb_build_object('basis',v_selected->'basis','parts',v_selected->'parts')));
            END LOOP;
            IF v_sum IS DISTINCT FROM p_amount::numeric
            THEN RAISE EXCEPTION 'Designated line amounts must preserve the exact Invoice amount'
                USING ERRCODE='P4502'; END IF;
            v_result:=jsonb_build_object('invoice_id',p_invoice,'invoice_version',v_invoice.version,
                'amount_usd_cents',p_amount,'details',v_details,'part_count',v_count);
            IF octet_length(v_result::text)>200000
            THEN RAISE EXCEPTION 'Complete designation exceeds its bounded evidence envelope'
                USING ERRCODE='P4502'; END IF;
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.invoice_due_designated_details(uuid,bigint,jsonb,timestamptz,integer)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    """)


def create_due_preview_wrappers() -> None:
    """Expose coherent read-only designation preparation through scoped read roles."""
    op.execute("""
        CREATE FUNCTION app.payment_allocation_designation_preview(
            p_property uuid,p_payment uuid,p_actor uuid,p_intent jsonb
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_charge record;
        DECLARE v_at timestamptz:=clock_timestamp(); v_available bigint; v_amount bigint; v_total numeric:=0;
        DECLARE v_target jsonb; v_targets jsonb:='[]'; v_prepared jsonb; v_intent jsonb; v_reference text;
        DECLARE v_invoice_id uuid; v_charge_id uuid; v_customer uuid; v_lease uuid; v_target_invoice uuid;
        DECLARE v_balance numeric; v_latest timestamptz; v_identity text; v_seen text[]:=ARRAY[]::text[];
        DECLARE v_parts integer:=0; v_details integer:=0;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account JOIN app.actor_identities identity
                ON identity.actor_id=account.actor_id WHERE account.actor_id=p_actor
                AND account.lifecycle_state='active' AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Preview requires an active human actor' USING ERRCODE='P4506'; END IF;
            SELECT * INTO v_payment FROM app.payments WHERE id=p_payment AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment was not found' USING ERRCODE='P4901'; END IF;
            v_available:=app.payment_available_value(p_payment);
            IF v_payment.status<>'RECEIVED' OR v_available<=0 OR v_at<v_payment.confirmed_at
            THEN RAISE EXCEPTION 'Payment source changed; refresh before preview' USING ERRCODE='P4904'; END IF;
            IF jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Payment preview intent must be an object' USING ERRCODE='P4902'; END IF;
            IF octet_length(p_intent::text)>250000 OR p_intent->>'mode' IS DISTINCT FROM 'DESIGNATED'
                OR NOT(p_intent ?& ARRAY['mode','targets','designation_reference'])
                OR p_intent-ARRAY['mode','targets','designation_reference']<>'{}'
                OR jsonb_typeof(p_intent->'designation_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'targets') IS DISTINCT FROM 'array'
            THEN RAISE EXCEPTION 'Payment preview designation is invalid' USING ERRCODE='P4902'; END IF;
            v_reference:=p_intent->>'designation_reference';
            IF v_reference<>btrim(v_reference) OR length(v_reference) NOT BETWEEN 1 AND 500
                OR jsonb_array_length(p_intent->'targets') NOT BETWEEN 1 AND 100
            THEN RAISE EXCEPTION 'Payment preview reference or target count is invalid' USING ERRCODE='P4902'; END IF;
            FOR v_target IN SELECT value FROM jsonb_array_elements(p_intent->'targets') LOOP
                IF jsonb_typeof(v_target) IS DISTINCT FROM 'object'
                THEN RAISE EXCEPTION 'Payment preview target must be an object' USING ERRCODE='P4902'; END IF;
                IF jsonb_typeof(v_target->'amount_usd_cents') IS DISTINCT FROM 'number'
                    OR (v_target->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                THEN RAISE EXCEPTION 'Payment preview requires exact positive cents' USING ERRCODE='P4902'; END IF;
                v_amount:=(v_target->>'amount_usd_cents')::bigint;
                IF v_amount>9000000000000000
                THEN RAISE EXCEPTION 'Payment preview amount exceeds bound' USING ERRCODE='P4902'; END IF;
                v_invoice_id:=NULL;v_charge_id:=NULL;
                IF v_target ? 'invoice_id' THEN
                    IF NOT(v_target ?& ARRAY['invoice_id','amount_usd_cents','details'])
                        OR v_target-ARRAY['invoice_id','amount_usd_cents','details']<>'{}'
                        OR jsonb_typeof(v_target->'invoice_id') IS DISTINCT FROM 'string'
                        OR (v_target->>'invoice_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    THEN RAISE EXCEPTION 'Payment Invoice preview target is invalid' USING ERRCODE='P4902'; END IF;
                    v_invoice_id:=(v_target->>'invoice_id')::uuid;
                    SELECT * INTO v_invoice FROM app.invoices WHERE id=v_invoice_id
                        AND app.invoice_property_id(id)=p_property AND issued_at IS NOT NULL
                        AND status IN ('UNPAID','PARTIALLY_PAID','PAID');
                    IF NOT FOUND THEN RAISE EXCEPTION 'Payment target was not found' USING ERRCODE='P4901'; END IF;
                    v_customer:=v_invoice.customer_id;v_lease:=v_invoice.lease_id;v_target_invoice:=v_invoice.id;
                    v_latest:=GREATEST(v_invoice.issued_at,v_invoice.updated_at,
                        app.allocation_target_latest_at('INVOICE',v_invoice.id));
                    v_identity:='INVOICE:'||v_invoice_id::text;
                ELSE
                    IF NOT(v_target ?& ARRAY['late_payment_charge_id','amount_usd_cents'])
                        OR v_target-ARRAY['late_payment_charge_id','amount_usd_cents']<>'{}'
                        OR jsonb_typeof(v_target->'late_payment_charge_id') IS DISTINCT FROM 'string'
                        OR (v_target->>'late_payment_charge_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    THEN RAISE EXCEPTION 'Payment Charge preview target is invalid' USING ERRCODE='P4902'; END IF;
                    v_charge_id:=(v_target->>'late_payment_charge_id')::uuid;
                    SELECT charge.customer_id,invoice.lease_id,invoice.id AS invoice_id,
                        position.remaining_balance_usd_cents AS balance,
                        GREATEST(charge.created_at,charge.payable_at,
                            app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',charge.id)) AS latest
                    INTO v_charge FROM app.late_payment_charges charge
                        JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                        JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
                    WHERE charge.id=v_charge_id AND app.invoice_property_id(invoice.id)=p_property;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Payment target was not found' USING ERRCODE='P4901'; END IF;
                    v_customer:=v_charge.customer_id;v_lease:=v_charge.lease_id;v_target_invoice:=v_charge.invoice_id;
                    v_balance:=v_charge.balance;v_latest:=v_charge.latest;v_identity:='CHARGE:'||v_charge_id::text;
                END IF;
                IF (v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND v_customer IS DISTINCT FROM v_payment.payer_customer_id)
                    OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                        AND v_payment.lease_id IS NOT NULL AND v_lease IS DISTINCT FROM v_payment.lease_id)
                    OR (v_payment.identified_invoice_id IS NOT NULL AND v_target_invoice IS DISTINCT FROM v_payment.identified_invoice_id)
                    OR (v_payment.identified_late_payment_charge_id IS NOT NULL AND v_charge_id IS DISTINCT FROM v_payment.identified_late_payment_charge_id)
                THEN RAISE EXCEPTION 'Payment target was not found in its confirmed context' USING ERRCODE='P4901'; END IF;
                IF v_identity=ANY(v_seen)
                THEN RAISE EXCEPTION 'Payment preview targets must be unique' USING ERRCODE='P4902'; END IF;
                v_seen:=array_append(v_seen,v_identity);v_total:=v_total+v_amount;
                IF v_at<=v_latest OR v_total>v_available
                THEN RAISE EXCEPTION 'Payment source or target changed; request a fresh preview' USING ERRCODE='P4904'; END IF;
                IF v_invoice_id IS NOT NULL THEN
                    IF v_parts>=500 THEN RAISE EXCEPTION 'Complete designation exceeds part budget' USING ERRCODE='P4902'; END IF;
                    v_prepared:=app.invoice_due_designated_details(v_invoice_id,v_amount,v_target->'details',v_at,500-v_parts);
                    v_parts:=v_parts+(v_prepared->>'part_count')::integer;
                    v_details:=v_details+jsonb_array_length(v_prepared->'details');
                    v_targets:=v_targets||jsonb_build_array(v_prepared-'part_count');
                ELSE
                    IF v_amount>v_balance
                    THEN RAISE EXCEPTION 'Payment Charge balance changed; request a fresh preview' USING ERRCODE='P4904'; END IF;
                    v_details:=v_details+1;
                    v_targets:=v_targets||jsonb_build_array(jsonb_build_object(
                        'late_payment_charge_id',v_charge_id,'amount_usd_cents',v_amount));
                END IF;
                IF v_details>500 THEN RAISE EXCEPTION 'Complete designation exceeds detail budget' USING ERRCODE='P4902'; END IF;
            END LOOP;
            v_intent:=jsonb_build_object('mode','DESIGNATED','designation_reference',v_reference,'targets',v_targets);
            IF octet_length(v_intent::text)>200000
            THEN RAISE EXCEPTION 'Complete designation exceeds evidence envelope' USING ERRCODE='P4902'; END IF;
            RETURN jsonb_build_object('property_id',p_property,'payment_id',p_payment,
                'available_usd_cents',v_available,'amount_usd_cents',v_total,'part_count',v_parts,'intent',v_intent);
        EXCEPTION
            WHEN SQLSTATE 'P4501' THEN RAISE EXCEPTION 'Payment target was not found' USING ERRCODE='P4901';
            WHEN SQLSTATE 'P4502' THEN RAISE EXCEPTION 'Payment preview designation is invalid or exceeds its complete budget' USING ERRCODE='P4902';
            WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                RAISE EXCEPTION 'Payment preview requires fresh resolved dated evidence' USING ERRCODE='P4904';
        END $$;

        CREATE FUNCTION app.credit_application_designation_preview(
            p_property uuid,p_credit uuid,p_actor uuid,p_intent jsonb
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_charge record;
        DECLARE v_at timestamptz:=clock_timestamp();v_available bigint;v_amount bigint;v_reference text;
        DECLARE v_invoice_id uuid;v_charge_id uuid;v_prepared jsonb;v_intent jsonb;v_parts integer:=0;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account JOIN app.actor_identities identity
                ON identity.actor_id=account.actor_id WHERE account.actor_id=p_actor
                AND account.lifecycle_state='active' AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Preview requires an active human actor' USING ERRCODE='P4506'; END IF;
            SELECT credit.* INTO v_credit FROM app.customer_credits credit
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.id=p_credit AND payment.property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit was not found' USING ERRCODE='P5101'; END IF;
            v_available:=app.credit_available_value(p_credit);
            IF v_available<=0 OR EXISTS(SELECT 1 FROM app.customer_credit_reversals WHERE customer_credit_id=p_credit)
                OR NOT EXISTS(SELECT 1 FROM app.payments WHERE id=v_credit.source_payment_id AND status='RECEIVED')
                OR v_at<=app.credit_latest_at(p_credit)
            THEN RAISE EXCEPTION 'Credit source changed; refresh before preview' USING ERRCODE='P5104'; END IF;
            IF jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Credit preview intent must be an object' USING ERRCODE='P5102'; END IF;
            IF octet_length(p_intent::text)>250000 OR p_intent->>'mode' IS DISTINCT FROM 'DESIGNATED'
                OR jsonb_typeof(p_intent->'designation_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'amount_usd_cents') IS DISTINCT FROM 'number'
                OR (p_intent->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            THEN RAISE EXCEPTION 'Credit preview requires exact designation and positive cents' USING ERRCODE='P5102'; END IF;
            v_amount:=(p_intent->>'amount_usd_cents')::bigint;v_reference:=p_intent->>'designation_reference';
            IF v_amount>9000000000000000 OR v_reference<>btrim(v_reference) OR length(v_reference) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Credit preview amount or reference is invalid' USING ERRCODE='P5102'; END IF;
            IF v_amount>v_available
            THEN RAISE EXCEPTION 'Credit available amount changed; request a fresh preview' USING ERRCODE='P5104'; END IF;
            IF p_intent ? 'invoice_id' THEN
                IF NOT(p_intent ?& ARRAY['mode','designation_reference','invoice_id','amount_usd_cents','details'])
                    OR p_intent-ARRAY['mode','designation_reference','invoice_id','amount_usd_cents','details']<>'{}'
                    OR jsonb_typeof(p_intent->'invoice_id') IS DISTINCT FROM 'string'
                    OR (p_intent->>'invoice_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                THEN RAISE EXCEPTION 'Credit Invoice preview target is invalid' USING ERRCODE='P5102'; END IF;
                v_invoice_id:=(p_intent->>'invoice_id')::uuid;
                SELECT * INTO v_invoice FROM app.invoices WHERE id=v_invoice_id
                    AND customer_id=v_credit.customer_id AND app.invoice_property_id(id)=p_property
                    AND issued_at IS NOT NULL AND status IN ('UNPAID','PARTIALLY_PAID','PAID');
                IF NOT FOUND THEN RAISE EXCEPTION 'Credit target was not found' USING ERRCODE='P5101'; END IF;
                v_prepared:=app.invoice_due_designated_details(v_invoice_id,v_amount,p_intent->'details',v_at,500);
                v_parts:=(v_prepared->>'part_count')::integer;
                v_intent:=(v_prepared-'part_count')||jsonb_build_object('mode','DESIGNATED','designation_reference',v_reference);
            ELSE
                IF NOT(p_intent ?& ARRAY['mode','designation_reference','late_payment_charge_id','amount_usd_cents'])
                    OR p_intent-ARRAY['mode','designation_reference','late_payment_charge_id','amount_usd_cents']<>'{}'
                    OR jsonb_typeof(p_intent->'late_payment_charge_id') IS DISTINCT FROM 'string'
                    OR (p_intent->>'late_payment_charge_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                THEN RAISE EXCEPTION 'Credit Charge preview target is invalid' USING ERRCODE='P5102'; END IF;
                v_charge_id:=(p_intent->>'late_payment_charge_id')::uuid;
                SELECT position.remaining_balance_usd_cents AS balance,
                    GREATEST(charge.created_at,charge.payable_at,
                        app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',charge.id)) AS latest
                INTO v_charge FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                    JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
                WHERE charge.id=v_charge_id AND charge.customer_id=v_credit.customer_id
                    AND app.invoice_property_id(invoice.id)=p_property;
                IF NOT FOUND THEN RAISE EXCEPTION 'Credit target was not found' USING ERRCODE='P5101'; END IF;
                IF v_amount>v_charge.balance OR v_at<=v_charge.latest
                THEN RAISE EXCEPTION 'Credit Charge changed; request a fresh preview' USING ERRCODE='P5104'; END IF;
                v_intent:=jsonb_build_object('mode','DESIGNATED','designation_reference',v_reference,
                    'late_payment_charge_id',v_charge_id,'amount_usd_cents',v_amount);
            END IF;
            IF octet_length(v_intent::text)>200000
            THEN RAISE EXCEPTION 'Complete Credit designation exceeds evidence envelope' USING ERRCODE='P5102'; END IF;
            RETURN jsonb_build_object('property_id',p_property,'credit_id',p_credit,
                'available_usd_cents',v_available,'amount_usd_cents',v_amount,'part_count',v_parts,'intent',v_intent);
        EXCEPTION
            WHEN SQLSTATE 'P4501' THEN RAISE EXCEPTION 'Credit target was not found' USING ERRCODE='P5101';
            WHEN SQLSTATE 'P4502' THEN RAISE EXCEPTION 'Credit preview designation is invalid or exceeds its complete budget' USING ERRCODE='P5102';
            WHEN SQLSTATE 'P4507' OR SQLSTATE 'P4508' THEN
                RAISE EXCEPTION 'Credit preview requires fresh resolved dated evidence' USING ERRCODE='P5104';
        END $$;
    """)
    for signature in (
        "app.payment_allocation_designation_preview(uuid,uuid,uuid,jsonb)",
        "app.credit_application_designation_preview(uuid,uuid,uuid,jsonb)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime,prm_financial")


def create_due_source_page() -> None:
    """Expose bounded dated choices through the existing financial action context."""
    op.execute("""
        CREATE FUNCTION app.financial_invoice_due_sources_page(
            p_property uuid,p_actor uuid,p_purpose text,p_source uuid,p_invoice uuid,p_line uuid,
            p_limit integer,p_expected text,p_after_kind text,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_context jsonb; v_position jsonb; v_revision text; v_result jsonb;
        DECLARE v_at timestamptz:=statement_timestamp(); v_count bigint;
        DECLARE v_after_due date; v_after_occurred timestamptz;
        BEGIN
            IF p_purpose IS NULL OR p_purpose NOT IN('allocation','credit_application')
                OR p_line IS NULL OR p_line='00000000-0000-0000-0000-000000000000'
                OR p_invoice IS NULL OR p_invoice='00000000-0000-0000-0000-000000000000'
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR (p_expected IS NULL)<>(p_after_kind IS NULL)
                OR (p_expected IS NULL)<>(p_after_id IS NULL)
                OR (p_expected IS NOT NULL AND p_expected !~ '^[0-9a-f]{64}$')
                OR p_after_kind NOT IN('ORIGINAL_LINE','DEBIT_ADJUSTMENT')
                OR p_after_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Invalid dated source page' USING ERRCODE='22023'; END IF;
            v_context:=app.financial_action_context_page(p_property,p_actor,p_purpose,p_source,
                NULL,'INVOICE',p_invoice,1,NULL,NULL);
            IF NOT EXISTS(SELECT 1 FROM app.invoice_lines WHERE id=p_line AND invoice_id=p_invoice)
            THEN RAISE EXCEPTION 'Financial source line was not found' USING ERRCODE='P4501'; END IF;
            IF (v_context->>'unsupported_application')::boolean IS DISTINCT FROM false
                OR v_context->'target'->>'status' NOT IN('UNPAID','PARTIALLY_PAID','PAID')
            THEN RAISE EXCEPTION 'Financial source requires resolved current facts'
                USING ERRCODE='P4507'; END IF;
            v_position:=app.invoice_line_due_position_at(p_line,v_at);
            IF v_position->'attribution_complete' IS DISTINCT FROM 'true'::jsonb
            THEN RAISE EXCEPTION 'Dated source history requires resolved attribution'
                USING ERRCODE='P4507'; END IF;
            v_revision:=encode(sha256(convert_to(jsonb_build_array(
                p_property,p_actor,p_purpose,p_source,p_invoice,p_line,p_limit,
                v_context->'revision_evidence',v_context->'context',v_context->'target',
                v_position-'as_of')::text,'UTF8')),'hex');
            IF p_expected IS NOT NULL AND p_expected<>v_revision
            THEN RAISE EXCEPTION 'Dated sources changed; reload the complete selection'
                USING ERRCODE='P4507'; END IF;
            IF p_after_id IS NOT NULL THEN
                SELECT approved_due_date,source_occurred_at INTO v_after_due,v_after_occurred
                FROM jsonb_to_recordset(v_position->'amounts') AS source(
                    source_kind text,source_id uuid,approved_due_date date,
                    source_occurred_at timestamptz,remaining_usd_cents bigint)
                WHERE remaining_usd_cents>0 AND source_kind=p_after_kind AND source_id=p_after_id;
                IF NOT FOUND THEN RAISE EXCEPTION 'Dated source cursor was not found'
                    USING ERRCODE='22023'; END IF;
            END IF;
            WITH eligible AS MATERIALIZED (
                SELECT source_kind,source_id,approved_due_date,source_occurred_at,
                    remaining_usd_cents
                FROM jsonb_to_recordset(v_position->'amounts') AS source(
                    source_kind text,source_id uuid,approved_due_date date,
                    source_occurred_at timestamptz,remaining_usd_cents bigint)
                WHERE remaining_usd_cents>0
            ), selected AS MATERIALIZED (
                SELECT * FROM eligible WHERE p_after_id IS NULL OR
                    (approved_due_date,source_occurred_at,source_kind COLLATE "C",source_id)>
                    (v_after_due,v_after_occurred,p_after_kind COLLATE "C",p_after_id)
                ORDER BY approved_due_date,source_occurred_at,source_kind COLLATE "C",source_id
                LIMIT p_limit+1
            ), visible AS (
                SELECT * FROM selected ORDER BY approved_due_date,source_occurred_at,
                    source_kind COLLATE "C",source_id LIMIT p_limit
            ) SELECT (SELECT count(*) FROM eligible),jsonb_build_object(
                'property_id',p_property,'purpose',p_purpose,'source_id',p_source,
                'invoice_id',p_invoice,'invoice_line_id',p_line,
                'invoice_version',v_context->'revision_evidence'->'target_invoice_version',
                'revision',v_revision,'as_of',v_at,
                'aggregate_outstanding_usd_cents',v_position->'aggregate_outstanding_usd_cents',
                'item_count',(SELECT count(*) FROM eligible),
                'has_more',(SELECT count(*)>p_limit FROM selected),
                'items',COALESCE((SELECT jsonb_agg(to_jsonb(visible) ORDER BY approved_due_date,
                    source_occurred_at,source_kind COLLATE "C",source_id) FROM visible),'[]'::jsonb)
            ) INTO v_count,v_result;
            IF v_count=0 AND (v_position->>'aggregate_outstanding_usd_cents')::bigint<>0
            THEN RAISE EXCEPTION 'Dated source balances require resolved attribution'
                USING ERRCODE='P4507'; END IF;
            IF octet_length(v_result::text)>100000
            THEN RAISE EXCEPTION 'Dated source page exceeds its response budget'
                USING ERRCODE='54000'; END IF;
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.financial_invoice_due_sources_page(
            uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.financial_invoice_due_sources_page(
            uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid) TO prm_runtime;
    """)


def create_due_overdue_projection() -> None:
    """Project proved dated balances without deciding eligibility or charging fees."""
    op.execute("""
        CREATE FUNCTION app.invoice_due_overdue_position_at(p_invoice uuid,p_as_of timestamptz)
        RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_business_date date;
        DECLARE v_lines bigint; v_unknown bigint; v_sources bigint; v_missing boolean;
        DECLARE v_total numeric; v_overdue numeric; v_not_overdue numeric;
        BEGIN
            IF p_invoice IS NULL OR p_invoice='00000000-0000-0000-0000-000000000000'
                OR p_as_of IS NULL OR NOT isfinite(p_as_of)
            THEN RAISE EXCEPTION 'An Invoice identity and finite assessment timestamp are required'
                USING ERRCODE='23514'; END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice;
            IF NOT FOUND OR v_invoice.issued_at IS NULL OR v_invoice.issued_at>p_as_of
            THEN RETURN NULL; END IF;
            v_business_date:=timezone('Asia/Phnom_Penh',p_as_of)::date;
            WITH positions AS MATERIALIZED (
                SELECT line.id,app.invoice_line_due_position_at(line.id,p_as_of) AS position
                FROM app.invoice_lines line WHERE line.invoice_id=p_invoice
            ), amounts AS MATERIALIZED (
                SELECT (source->>'approved_due_date')::date AS due,
                    (source->>'remaining_usd_cents')::numeric AS remaining
                FROM positions CROSS JOIN LATERAL jsonb_array_elements(position->'amounts') source
            )
            SELECT (SELECT count(*) FROM positions),
                (SELECT count(*) FROM positions WHERE position->'attribution_complete' IS DISTINCT FROM 'true'::jsonb),
                (SELECT count(*) FROM amounts),
                COALESCE((SELECT bool_or(position IS NULL) FROM positions),false),
                COALESCE((SELECT sum((position->>'aggregate_outstanding_usd_cents')::numeric) FROM positions),0),
                COALESCE((SELECT sum(remaining) FROM amounts WHERE due<v_business_date),0),
                COALESCE((SELECT sum(remaining) FROM amounts WHERE due>=v_business_date),0)
            INTO v_lines,v_unknown,v_sources,v_missing,v_total,v_overdue,v_not_overdue;
            IF v_missing OR v_lines=0 OR v_total<0 OR v_total>9223372036854775807::numeric
                OR v_overdue<0 OR v_not_overdue<0
                OR (v_unknown=0 AND v_overdue+v_not_overdue<>v_total)
            THEN RAISE EXCEPTION 'Invoice dated balance evidence is inconsistent'
                USING ERRCODE='23514'; END IF;
            RETURN jsonb_build_object('invoice_id',p_invoice,'source_due_date',v_invoice.due_date,
                'as_of',p_as_of,'business_date',v_business_date,'timezone','Asia/Phnom_Penh',
                'line_count',v_lines,'unknown_line_count',v_unknown,'attribution_complete',v_unknown=0,
                'aggregate_outstanding_usd_cents',v_total::bigint,
                'dated_source_count',CASE WHEN v_unknown=0 THEN v_sources END,
                'overdue_balance_usd_cents',CASE WHEN v_unknown=0 THEN v_overdue::bigint END,
                'not_overdue_balance_usd_cents',CASE WHEN v_unknown=0 THEN v_not_overdue::bigint END);
        END $$;
        REVOKE ALL ON FUNCTION app.invoice_due_overdue_position_at(uuid,timestamptz)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    """)


def connect_due_late_payment_assessment() -> None:
    """Use proved overdue amounts without changing finality, locks or authority."""
    aggregate = (
        "SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)\n"
        "            INTO v_balance FROM app.invoice_lines AS line WHERE line.invoice_id=p_invoice_id;"
    )
    projection = """v_due:=app.invoice_due_overdue_position_at(p_invoice_id,v_now);
            v_balance:=(v_due->>'overdue_balance_usd_cents')::bigint;"""
    review = (
        (
            "DECLARE v_decision jsonb; v_blockers jsonb:='[]'::jsonb; v_lease_status text;",
            "DECLARE v_decision jsonb; v_blockers jsonb:='[]'::jsonb; v_lease_status text;\n"
            "        DECLARE v_due jsonb;",
        ),
        (aggregate, projection),
        (
            "            IF v_balance<=0 THEN",
            """            IF v_due IS NULL
                OR NOT COALESCE((v_due->>'attribution_complete')::boolean,false)
                OR v_balance IS NULL
            THEN
                v_blockers:=v_blockers||jsonb_build_array('DUE_ATTRIBUTION_UNRESOLVED');
            END IF;
            IF v_balance<=0 AND v_invoice.due_date<v_business_date THEN""",
        ),
        (
            "'overdue_balance',jsonb_build_object(\n"
            "                    'currency','USD','minor_units',v_balance),",
            "'overdue_balance',CASE WHEN v_balance IS NOT NULL THEN jsonb_build_object(\n"
            "                    'currency','USD','minor_units',v_balance) END,",
        ),
        (
            "'calculated_default_amount',jsonb_build_object(\n"
            "                    'currency','USD','minor_units',v_default),",
            "'calculated_default_amount',CASE WHEN v_default IS NOT NULL THEN jsonb_build_object(\n"
            "                    'currency','USD','minor_units',v_default) END,\n"
            "                'due_attribution',v_due,",
        ),
    )
    finalizer = (
        ("DECLARE v_lease_status text;", "DECLARE v_lease_status text; v_due jsonb;"),
        (aggregate, projection),
        (
            "                OR v_balance<=0 OR v_balance>9000000000000000",
            """                OR v_due IS NULL
                OR NOT COALESCE((v_due->>'attribution_complete')::boolean,false)
                OR v_balance IS NULL
                OR v_balance<=0 OR v_balance>9000000000000000""",
        ),
        (
            "'overdue_balance_usd_cents',v_balance,'rate_basis_points',1000,",
            "'overdue_balance_usd_cents',v_balance,'rate_basis_points',1000,\n"
            "                    'due_attribution',v_due,",
        ),
    )
    integrity = (
        (
            "DECLARE v_invoice app.invoices%ROWTYPE; v_balance bigint; v_default bigint;",
            "DECLARE v_invoice app.invoices%ROWTYPE; v_balance bigint; v_default bigint;\n"
            "        DECLARE v_due jsonb;",
        ),
        (
            "SELECT COALESCE(sum(app.invoice_line_outstanding_at(id,NEW.assessed_at)),0)\n"
            "                INTO v_balance FROM app.invoice_lines WHERE invoice_id=v_invoice.id;",
            "v_due:=app.invoice_due_overdue_position_at(v_invoice.id,NEW.assessed_at);\n"
            "            v_balance:=(v_due->>'overdue_balance_usd_cents')::bigint;",
        ),
        (
            "IF v_invoice.customer_id<>NEW.customer_id OR v_invoice.due_date<>NEW.source_due_date",
            """IF v_due IS NULL
                OR NOT COALESCE((v_due->>'attribution_complete')::boolean,false)
                OR v_balance IS NULL
                OR v_invoice.customer_id<>NEW.customer_id OR v_invoice.due_date<>NEW.source_due_date""",
        ),
    )
    for signature, replacements in (
        ("app.late_payment_review_snapshot(uuid)", review),
        (
            "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
            finalizer,
        ),
        ("app.validate_late_payment_decision()", integrity),
    ):
        definition = (
            op.get_bind()
            .execute(
                text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
                {"signature": signature},
            )
            .scalar_one()
        )
        for before, after in replacements:
            if definition.count(before) != 1:
                raise RuntimeError("Dated late-payment assessment source contract changed")
            definition = definition.replace(before, after)
        op.execute(definition)
