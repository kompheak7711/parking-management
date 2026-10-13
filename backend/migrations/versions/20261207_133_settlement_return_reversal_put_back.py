# ruff: noqa: E501
"""A return reversal's Credit put-back goes back on its own line (V1-056 sub-slice 10e-3e).

BR-CREDIT-006, BR-CREDIT-008, BR-SETTLE-013, BR-SETTLE-016; DB-CREDIT-002; owner answer (b) to
Q-2026-10-13-104 (a Credit part put back on an Invoice with Rent or Service lines goes back on its
own line, even where the Rent-first rule would choose another line today; only for a put-back
linked to the correction, on the same line, never more than the amount reversed there; the 10e-3c
put-back too) and owner answer (a) to Q-2026-10-13-106 (a new label "put back by a correction",
written only by a correction's put-back; staff cannot choose it):

- Relaxed CHECKs: `customer_credit_applications.within_invoice_basis` and
  `customer_credit_application_details.attribution_basis` accept `PUT_BACK_BY_CORRECTION`. The
  existing CHECKs keep it off a Late-payment Charge and keep the proposal fields and the
  designation empty.
- New BEFORE INSERT trigger `customer_credit_applications_put_back` (new internal
  `app.validate_credit_application_put_back()`): the label is written only on a row linked to a
  correction of its Final Settlement confirmed in this transaction, or on the re-posted rest of a
  row that has it (the release re-post of migration 67, which the confirm of a later `REFUND`
  correction writes after closure, migration 100).
- `app.post_final_settlement_credit_application` (exact-text patches): for a `RETURN_REVERSAL`
  correction draft the step's restored Credit application is the stored source's `reapply` entry
  at the step's position (the n-th step is the n-th part applied again); on an Invoice with Rent or
  Service lines without a Customer designation the row and its detail get the label and no
  proposal, on the step's line; every put-back's detail trace names
  `restores_credit_application_id`. A designated part and a Late-payment Charge keep their labels.
- `app.assert_settlement_correction_credit_application` (exact-text patches): the label is the
  expected basis of a `RETURN_REVERSAL` correction's step on such an Invoice without a
  designation.
- `app.validate_credit_application_complete` (exact-text patch): the header and its details agree
  on the label.
- `app.assert_settlement_correction_credit_application_confirmed` (exact-text patch, deferred):
  new internal `app.settlement_correction_put_back_allowed(...)`: a `RETURN_REVERSAL` correction's
  Credit application names, in its detail, the source entry's application, which has one detail,
  the same Credit, target and line, and a reversal linked to the same correction; all put-backs
  naming it are together at most that detail's amount; the label is there exactly on an Invoice
  with Rent or Service lines without a designation. Any other correction's Credit application
  names no restored application and has no label.
- `app.assert_settlement_return_reversal_allowed` (exact-text patch): the sub-slice 10e-3d-2a
  refusal of a Credit part that the Rent-first order would put on another line ends.

Additive and relaxing: no existing row has the new label or a `restores_credit_application_id`
trace; the new checks see only rows written from now on. No grant changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261207_133"
down_revision = "20261206_132"
branch_labels = None
depends_on = None

LABEL = "PUT_BACK_BY_CORRECTION"

CHECKS = {
    (
        "app.customer_credit_applications",
        "customer_credit_applications_within_invoice_basis_check",
    ): "CHECK ((within_invoice_basis = ANY (ARRAY['RENT_THEN_RECURRING_SERVICES_PROPOSAL'::text, 'CUSTOMER_DESIGNATED'::text, 'OTHER_APPLICABLE_OBLIGATION'::text, 'NOT_APPLICABLE'::text])))",
    (
        "app.customer_credit_application_details",
        "customer_credit_application_details_attribution_basis_check",
    ): "CHECK ((attribution_basis = ANY (ARRAY['RENT_FIRST_PROPOSAL'::text, 'SERVICE_PROPOSAL'::text, 'CUSTOMER_DESIGNATED'::text, 'OTHER_CONFIRMED'::text, 'DIRECT_LATE_PAYMENT_CHARGE'::text])))",
}

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3e (owner answer (a) to Q-2026-10-13-106): only a correction's put-back, or
    -- the re-posted rest of one (the release re-post of migrations 67 and 100), carries the label
    -- "put back by a correction".
    CREATE FUNCTION app.validate_credit_application_put_back()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF NOT ((NEW.final_settlement_id IS NOT NULL
                AND app.settlement_correction_linked(NEW.final_settlement_id,
                    'customer_credit_applications',NEW.id) IS TRUE)
            OR EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases release
                JOIN app.customer_credit_applications replaced
                    ON replaced.id=release.reversed_credit_application_id
                WHERE release.replacement_credit_application_id=NEW.id
                  AND release.source_kind='CREDIT_APPLICATION'
                  AND replaced.within_invoice_basis='PUT_BACK_BY_CORRECTION'))
        THEN RAISE EXCEPTION 'Only a correction''s put-back is labelled put back by a correction'
            USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER customer_credit_applications_put_back BEFORE INSERT
        ON app.customer_credit_applications FOR EACH ROW
        WHEN (NEW.within_invoice_basis='PUT_BACK_BY_CORRECTION')
        EXECUTE FUNCTION app.validate_credit_application_put_back();

    -- Sub-slice 10e-3e (owner answer (b) to Q-2026-10-13-104): a return reversal's Credit
    -- application restores the payment the same correction reversed: the source entry of its
    -- step names it, it has one detail, the same Credit, target and line, a reversal linked to
    -- this correction, and every put-back naming it is together at most its amount there; the
    -- label is there exactly on an Invoice with Rent or Service lines without a designation. Any
    -- other correction's Credit application names no restored payment and has no label. Never
    -- NULL.
    CREATE FUNCTION app.settlement_correction_put_back_allowed(p_correction uuid,
            p_application app.customer_credit_applications,
            p_detail app.customer_credit_application_details,p_sequence integer)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        WITH draft AS (
            SELECT draft.payload FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
            WHERE correction.id=p_correction
        ), restored AS (
            SELECT application.id,application.customer_credit_id,application.target_kind,
                application.invoice_id,application.late_payment_charge_id,
                detail.invoice_line_id AS detail_line_id,
                detail.late_payment_charge_id AS detail_charge_id,
                detail.applied_amount_usd_cents AS detail_amount
            FROM app.customer_credit_applications application
            JOIN app.customer_credit_application_details detail
                ON detail.customer_credit_application_id=application.id
            WHERE application.id::text=p_detail.calculation_trace->>'restores_credit_application_id'
              AND (SELECT count(*) FROM app.customer_credit_application_details other
                  WHERE other.customer_credit_application_id=application.id)=1
        )
        SELECT COALESCE(CASE WHEN (SELECT payload->>'variant' FROM draft)
                IS DISTINCT FROM 'RETURN_REVERSAL'
            THEN p_detail.calculation_trace->'restores_credit_application_id' IS NULL
                AND p_application.within_invoice_basis<>'PUT_BACK_BY_CORRECTION'
            -- Review round 2: a step before the first never reads the source list from its end.
            ELSE p_sequence>=1
                AND jsonb_typeof(p_detail.calculation_trace->'restores_credit_application_id')='string'
                AND (SELECT payload->'source'->'reapply'->(p_sequence-1)->>'source_kind' FROM draft)='CREDIT'
                AND (SELECT payload->'source'->'reapply'->(p_sequence-1)->>'application_id' FROM draft)
                    =p_detail.calculation_trace->>'restores_credit_application_id'
                AND EXISTS(SELECT 1 FROM restored
                    JOIN app.customer_credit_application_reversals reversal
                        ON reversal.credit_application_id=restored.id
                    JOIN app.settlement_correction_effects effect
                        ON effect.credit_application_reversal_id=reversal.id
                    WHERE effect.settlement_correction_id=p_correction
                      AND restored.customer_credit_id=p_application.customer_credit_id
                      AND restored.target_kind=p_application.target_kind
                      AND restored.invoice_id IS NOT DISTINCT FROM p_application.invoice_id
                      AND restored.late_payment_charge_id IS NOT DISTINCT FROM p_application.late_payment_charge_id
                      AND restored.detail_line_id IS NOT DISTINCT FROM p_detail.invoice_line_id
                      AND restored.detail_charge_id IS NOT DISTINCT FROM p_detail.late_payment_charge_id
                      AND (SELECT COALESCE(sum(other.applied_amount_usd_cents),0)
                          FROM app.customer_credit_application_details other
                          WHERE other.calculation_trace->>'restores_credit_application_id'=restored.id::text
                            AND other.id IS DISTINCT FROM p_detail.id)
                          +p_detail.applied_amount_usd_cents<=restored.detail_amount)
                AND (p_application.within_invoice_basis='PUT_BACK_BY_CORRECTION')
                    =(p_application.target_kind='INVOICE'
                        AND p_application.customer_designation_reference IS NULL
                        AND EXISTS(SELECT 1 FROM app.invoice_lines line
                            WHERE line.invoice_id=p_application.invoice_id
                              AND line.category IN ('RENT','SERVICE_CHARGES')))
            END,false)
    $$;
"""

INTERNAL = (
    "app.validate_credit_application_put_back()",
    "app.settlement_correction_put_back_allowed(uuid,app.customer_credit_applications,app.customer_credit_application_details,integer)",
)

WRITER = "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)"
WRITER_REPLACEMENTS = (
    (
        "v_basis text; v_detail_basis text; v_proposal jsonb; v_at timestamptz;\n",
        "v_basis text; v_detail_basis text; v_proposal jsonb; v_at timestamptz; v_restores text;\n",
    ),
    (
        "            v_reference:=CASE WHEN jsonb_typeof(v_step->'customer_designation')='string'\n"
        "                THEN v_step->>'customer_designation' END;\n",
        "            v_reference:=CASE WHEN jsonb_typeof(v_step->'customer_designation')='string'\n"
        "                THEN v_step->>'customer_designation' END;\n"
        "            -- Sub-slice 10e-3e (owner answers (b) to Q-2026-10-13-104 and (a) to\n"
        "            -- Q-2026-10-13-106): a return reversal's step restores the Credit application it\n"
        "            -- reversed; the n-th step of its plan is the n-th part applied again of its stored\n"
        "            -- source.\n"
        "            IF v_draft.kind='SETTLEMENT_CORRECTION' AND v_draft.payload->>'variant'='RETURN_REVERSAL' THEN\n"
        "                v_restores:=v_draft.payload->'source'->'reapply'->(p_step-1)->>'application_id';\n"
        "                IF v_draft.payload->'source'->'reapply'->(p_step-1)->>'source_kind' IS DISTINCT FROM 'CREDIT'\n"
        "                    OR v_restores IS NULL\n"
        "                    OR v_restores !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'\n"
        "                THEN RAISE EXCEPTION 'The draft step is not a Customer Credit step' USING ERRCODE='22023'; END IF;\n"
        "            END IF;\n",
    ),
    (
        "            ELSIF v_charge IS NOT NULL THEN\n"
        "                v_basis:='NOT_APPLICABLE'; v_detail_basis:='DIRECT_LATE_PAYMENT_CHARGE';\n",
        "            ELSIF v_charge IS NOT NULL THEN\n"
        "                v_basis:='NOT_APPLICABLE'; v_detail_basis:='DIRECT_LATE_PAYMENT_CHARGE';\n"
        "            -- Sub-slice 10e-3e: a put-back on an Invoice with Rent or Service lines goes back on\n"
        "            -- its own line (the step's line), put back by a correction; it is not a new Rent-first\n"
        "            -- allocation, so the proposal is not asked.\n"
        "            ELSIF v_restores IS NOT NULL AND EXISTS(SELECT 1 FROM app.invoice_lines line\n"
        "                WHERE line.invoice_id=v_invoice AND line.category IN ('RENT','SERVICE_CHARGES'))\n"
        "            THEN\n"
        "                v_basis:='PUT_BACK_BY_CORRECTION'; v_detail_basis:='PUT_BACK_BY_CORRECTION';\n",
    ),
    (
        "                    'confirmed_detail',v_step,'designation_reference',v_reference));\n",
        "                    'confirmed_detail',v_step,'designation_reference',v_reference)\n"
        "                -- Sub-slice 10e-3e: a put-back names the payment it restores.\n"
        "                ||CASE WHEN v_restores IS NOT NULL\n"
        "                    THEN jsonb_build_object('restores_credit_application_id',v_restores)\n"
        "                    ELSE '{}'::jsonb END);\n",
    ),
)

SOURCE_CHECK = (
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)"
)
SOURCE_CHECK_REPLACEMENTS = (
    (
        "v_lease app.leases%ROWTYPE; v_target_lease uuid; v_steps jsonb;\n",
        "v_lease app.leases%ROWTYPE; v_target_lease uuid; v_steps jsonb; v_variant text;\n",
    ),
    (
        "            ELSE '[]'::jsonb END INTO v_steps\n",
        "            ELSE '[]'::jsonb END,draft.payload->>'variant' INTO v_steps,v_variant\n",
    ),
    (
        "                      WHEN step->>'target_kind'='LATE_PAYMENT_CHARGE' THEN 'NOT_APPLICABLE'\n",
        "                      WHEN step->>'target_kind'='LATE_PAYMENT_CHARGE' THEN 'NOT_APPLICABLE'\n"
        "                      -- Sub-slice 10e-3e: a return reversal's put-back (every Credit step of its\n"
        "                      -- plan) on an Invoice with Rent or Service lines.\n"
        "                      WHEN v_variant='RETURN_REVERSAL' AND EXISTS(SELECT 1 FROM app.invoice_lines line\n"
        "                          WHERE line.invoice_id=p_application.invoice_id\n"
        "                            AND line.category IN ('RENT','SERVICE_CHARGES')) THEN 'PUT_BACK_BY_CORRECTION'\n",
    ),
)

COMPLETE = "app.validate_credit_application_complete()"
COMPLETE_REPLACEMENTS = (
    (
        "                        OR (v_header.within_invoice_basis='OTHER_APPLICABLE_OBLIGATION' AND detail.attribution_basis<>'OTHER_CONFIRMED')))\n",
        "                        OR (v_header.within_invoice_basis='OTHER_APPLICABLE_OBLIGATION' AND detail.attribution_basis<>'OTHER_CONFIRMED')\n"
        "                        -- Sub-slice 10e-3e: the header and its details agree on put back by a correction.\n"
        "                        OR ((v_header.within_invoice_basis='PUT_BACK_BY_CORRECTION')\n"
        "                            IS DISTINCT FROM (detail.attribution_basis='PUT_BACK_BY_CORRECTION'))))\n",
    ),
)

CONFIRMED = "app.assert_settlement_correction_credit_application_confirmed(app.customer_credit_applications)"
CONFIRMED_REPLACEMENTS = (
    (
        "pays exactly the obligation of its Credit step, once'\n"
        "            USING ERRCODE='23514'; END IF;\n",
        "pays exactly the obligation of its Credit step, once'\n"
        "            USING ERRCODE='23514'; END IF;\n"
        "        -- Sub-slice 10e-3e (owner answer (b) to Q-2026-10-13-104): a put-back restores, on the same\n"
        "        -- line, at most the payment the same return reversal reversed.\n"
        "        IF NOT app.settlement_correction_put_back_allowed(v_correction.id,p_application,v_detail,\n"
        "            v_sequence)\n"
        "        THEN RAISE EXCEPTION 'A put-back by a correction restores, on the same line, at most the payment the same return reversal reversed'\n"
        "            USING ERRCODE='23514'; END IF;\n",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """        -- Sub-slice 10e-3d-2a (review round 1): a Credit part applied again without a
        -- Customer designation on an Invoice with Rent or Service lines follows the Rent-first
        -- proposal, which pays the line of the oldest reversed application of that Invoice
        -- first; a part on a newer one would be refused at the confirm, so it is refused here
        -- and waits for the owner (Q-2026-10-13-104). The listed applications are newest first.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'reapply') item
            JOIN jsonb_array_elements(p_source->'credit_applications')
                WITH ORDINALITY reapplied(application,position)
                ON reapplied.application->>'id'=item->>'application_id'
            WHERE item->>'source_kind'='CREDIT' AND item->>'target_kind'='INVOICE_LINE'
              AND jsonb_typeof(item->'customer_designation') IS DISTINCT FROM 'string'
              AND EXISTS(SELECT 1 FROM app.invoice_lines line
                  WHERE line.invoice_id::text=reapplied.application->>'invoice_id'
                    AND line.category IN ('RENT','SERVICE_CHARGES'))
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'credit_applications')
                      WITH ORDINALITY older(application,position)
                  WHERE older.application->>'invoice_id'=reapplied.application->>'invoice_id'
                    AND older.position>reapplied.position))
        THEN RAISE EXCEPTION 'A part applied again on an Invoice with Rent or Service lines would not follow the Rent-first order; reversing this return waits for the owner'
            USING ERRCODE='55000'; END IF;
""",
        """        -- Sub-slice 10e-3e (owner answer (b) to Q-2026-10-13-104): a Credit part applied again on
        -- an Invoice with Rent or Service lines goes back on its own line, put back by a
        -- correction, so the Rent-first order no longer decides it; the sub-slice 10e-3d-2a
        -- refusal ends.
""",
    ),
)

PATCHES = (
    (WRITER, WRITER_REPLACEMENTS),
    (SOURCE_CHECK, SOURCE_CHECK_REPLACEMENTS),
    (COMPLETE, COMPLETE_REPLACEMENTS),
    (CONFIRMED, CONFIRMED_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
)


def _assert_checks() -> None:
    """The two CHECKs this migration relaxes are exactly the ones migration 41 created."""
    found = {
        (str(row[0]), str(row[1])): str(row[2])
        for row in op.get_bind()
        .execute(
            text(
                "SELECT conrelid::regclass::text,conname,pg_catalog.pg_get_constraintdef(oid) "
                "FROM pg_catalog.pg_constraint WHERE contype='c' AND conname = ANY(:names)"
            ),
            {"names": [name for _, name in CHECKS]},
        )
        .all()
    }
    if found != CHECKS:
        raise RuntimeError("Credit application put-back contract changed")


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
            raise RuntimeError(f"Settlement return reversal put-back contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _assert_checks()
    op.execute(f"""
        -- Relaxed (owner answer (a) to Q-2026-10-13-106): the label "put back by a correction".
        ALTER TABLE app.customer_credit_applications
            DROP CONSTRAINT customer_credit_applications_within_invoice_basis_check,
            ADD CONSTRAINT customer_credit_applications_within_invoice_basis_check CHECK (
                within_invoice_basis IN ('RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED',
                    'OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE','{LABEL}'));
        ALTER TABLE app.customer_credit_application_details
            DROP CONSTRAINT customer_credit_application_details_attribution_basis_check,
            ADD CONSTRAINT customer_credit_application_details_attribution_basis_check CHECK (
                attribution_basis IN ('RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL','CUSTOMER_DESIGNATED',
                    'OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE','{LABEL}'));
    """)
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement return reversal put-back migration is forward-only")
