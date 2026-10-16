# ruff: noqa: E501
"""An Adjustment reversal puts the Credit back on the Adjustment's own line (V1-056 sub-slice 10f-1b).

BR-CREDIT-006, BR-CREDIT-008, BR-INV-044; DB-CREDIT-002, DB-INV-010; owner answer (a) to
Q-2026-10-16-118 point 1: an ADJUSTMENT_REVERSAL always puts the Credit back on the Adjustment's
own line, with the label "put back by a correction" (PUT_BACK_BY_CORRECTION, sub-slice 10e-3e),
even when an earlier line still owes; a put-back restores what was there before and is not a new
allocation (answer (b) to Q-2026-10-13-104); never more than the release or the line's unpaid
rest.

- `app.adjustment_reversal_source` (exact-text patch): the 10f-1 refusal of a put-back that the
  Rent-first order would put on another line ends.
- `app.confirm_adjustment_reversal` (exact-text patches): no Rent-first proposal; every put-back
  carries the label on the row and its one detail (no proposal fields, no proposed amount), on the
  Adjustment's line, with the same trace (the reversal and the release).
- `app.validate_credit_application_put_back` (exact-text patch): the label is also allowed on a
  row with no Final Settlement that a confirmed ADJUSTMENT_REVERSAL decision of this transaction
  lists among its put-backs.
- New deferred constraint trigger `customer_credit_applications_adjustment_put_back` (new
  internal `app.validate_adjustment_reversal_put_back()` and
  `app.adjustment_reversal_put_back_allowed(...)`): a labelled row with no Final Settlement that
  such a decision lists (and that is not the re-posted rest of a release) has one detail, is
  listed with the same Credit, amount and release, names that decision's reversal and the
  release, is on the reversed Adjustment's Invoice and line with the release's Credit, and all
  put-backs naming the release are together at most the released amount (23514 otherwise).

Additive and relaxing: the new check is an AFTER INSERT trigger, so it sees only rows written from
now on, and it leaves alone the re-posted rest of a release (the only rows with the label and no
Final Settlement so far: the release re-post of migration 20261003_67, written after closure by
the correction confirms of migrations 20261104_100, 20261107_103 and 20261117_113). No grant
changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261220_146"
down_revision = "20261219_145"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10f-1b (owner answer (a) to Q-2026-10-16-118 point 1): an Adjustment reversal's
    -- put-back is listed by the decision of this transaction with the same Credit, amount and
    -- release, names that decision's reversal and the release in its one detail, is on the
    -- reversed Adjustment's Invoice and line with the release's Credit, and all put-backs naming
    -- the release are together at most the released amount. Never NULL.
    CREATE FUNCTION app.adjustment_reversal_put_back_allowed(
            p_application app.customer_credit_applications,
            p_detail app.customer_credit_application_details)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT bool_or(
                p_application.target_kind='INVOICE'
                AND p_application.final_settlement_id IS NULL
                AND p_application.within_invoice_basis='PUT_BACK_BY_CORRECTION'
                AND p_application.customer_designation_reference IS NULL
                AND p_detail.customer_credit_application_id=p_application.id
                AND p_detail.obligation_kind='INVOICE_LINE'
                AND p_detail.attribution_basis='PUT_BACK_BY_CORRECTION'
                AND p_detail.applied_amount_usd_cents=p_application.amount_usd_cents
                AND p_application.invoice_id=adjustment.invoice_id
                AND p_detail.invoice_line_id=adjustment.invoice_line_id
                AND release.invoice_adjustment_id=adjustment.id
                AND COALESCE(release.customer_credit_id,released.customer_credit_id)
                    =p_application.customer_credit_id
                AND jsonb_typeof(p_detail.calculation_trace->'invoice_adjustment_reversal_id')='string'
                AND p_detail.calculation_trace->>'invoice_adjustment_reversal_id'=reversal.id::text
                AND decision.result->'put_backs' @> jsonb_build_array(jsonb_build_object(
                    'credit_application_id',p_application.id,
                    'customer_credit_id',p_application.customer_credit_id,
                    'amount_usd_cents',p_application.amount_usd_cents,
                    'invoice_credit_excess_release_id',release.id))
                AND (SELECT COALESCE(sum(other.applied_amount_usd_cents),0)
                    FROM app.customer_credit_application_details other
                    WHERE other.calculation_trace->>'invoice_credit_excess_release_id'=release.id::text
                      AND other.calculation_trace ? 'invoice_adjustment_reversal_id'
                      AND other.id IS DISTINCT FROM p_detail.id)
                    +p_detail.applied_amount_usd_cents<=release.released_usd_cents)
            FROM app.financial_draft_decisions decision
            JOIN app.financial_drafts draft ON draft.id=decision.draft_id
            JOIN app.invoice_adjustment_reversals reversal
                ON reversal.id::text=decision.result->>'invoice_adjustment_reversal_id'
            JOIN app.invoice_adjustments adjustment ON adjustment.id=reversal.invoice_adjustment_id
            JOIN app.invoice_credit_excess_releases release
                ON release.id::text=p_detail.calculation_trace->>'invoice_credit_excess_release_id'
            LEFT JOIN app.customer_credit_applications released
                ON released.id=release.reversed_credit_application_id
            WHERE draft.kind='ADJUSTMENT_REVERSAL' AND decision.decision='CONFIRMED'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()),false)
    $$;

    -- Sub-slice 10f-1b: the deferred check of a labelled row with no Final Settlement that a
    -- confirmed ADJUSTMENT_REVERSAL decision of this transaction lists. The BEFORE INSERT label
    -- trigger refuses every other such row, except the re-posted rest of a release (the release
    -- re-post of migration 20261003_67, also written by migrations 20261104_100, 20261107_103 and
    -- 20261117_113, keeps the label on that rest), which this check leaves alone.
    CREATE FUNCTION app.validate_adjustment_reversal_put_back()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_application app.customer_credit_applications%ROWTYPE;
        v_detail app.customer_credit_application_details%ROWTYPE; v_count integer;
    BEGIN
        IF EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases release
            WHERE release.replacement_credit_application_id=NEW.id)
            OR NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                JOIN app.financial_drafts draft ON draft.id=decision.draft_id
                WHERE draft.kind='ADJUSTMENT_REVERSAL' AND decision.decision='CONFIRMED'
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp()
                  AND decision.result->'put_backs' @> jsonb_build_array(
                      jsonb_build_object('credit_application_id',NEW.id)))
        THEN RETURN NULL; END IF;
        SELECT * INTO STRICT v_application FROM app.customer_credit_applications WHERE id=NEW.id;
        SELECT count(*) INTO v_count FROM app.customer_credit_application_details detail
        WHERE detail.customer_credit_application_id=NEW.id;
        SELECT * INTO v_detail FROM app.customer_credit_application_details detail
        WHERE detail.customer_credit_application_id=NEW.id;
        IF v_count<>1 OR app.adjustment_reversal_put_back_allowed(v_application,v_detail) IS NOT TRUE
        THEN RAISE EXCEPTION 'An Adjustment reversal put-back goes back only on its Adjustment''s line, within its release'
            USING ERRCODE='23514'; END IF;
        RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER customer_credit_applications_adjustment_put_back AFTER INSERT
        ON app.customer_credit_applications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        WHEN (NEW.within_invoice_basis='PUT_BACK_BY_CORRECTION' AND NEW.final_settlement_id IS NULL)
        EXECUTE FUNCTION app.validate_adjustment_reversal_put_back();
"""

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.adjustment_reversal_source(uuid,uuid)",
        (
            (
                "            -- Q-2026-10-16-118 point 1 (fail closed until the owner answers): the Rent-first order\n"
                "            -- (Rent, then Service Charges, then other lines, by line sequence) must choose the\n"
                "            -- Adjustment's line, so no line before it may still owe.\n"
                "            WHEN v_put_total>0 AND EXISTS(SELECT 1 FROM app.invoice_lines other\n"
                "                WHERE other.invoice_id=v_invoice.id AND other.id<>v_line.id\n"
                "                  AND (CASE other.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,\n"
                "                        other.line_sequence,other.id)\n"
                "                    <(CASE v_line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,\n"
                "                        v_line.line_sequence,v_line.id)\n"
                "                  AND app.invoice_line_outstanding(other.id)>0) THEN\n"
                "                'The Credit put-back would go on another line by the Rent-first order; this waits for the owner'\n",
                "            -- Sub-slice 10f-1b (owner answer (a) to Q-2026-10-16-118 point 1): the put-back goes\n"
                "            -- back on the Adjustment's own line, also when an earlier line still owes.\n",
            ),
        ),
    ),
    (
        "app.confirm_adjustment_reversal(uuid,uuid,uuid,text)",
        (
            (
                "        -- The put-back: each part of a release's Credit still available, on the Adjustment's line,\n"
                "        -- with the Rent-first proposal for its amount (BR-CREDIT-006), which must put the whole\n"
                "        -- amount on that line (Q-2026-10-16-118 point 1); the approver applies it as the Credit\n"
                "        -- writers do (credits.apply), each dated after the one before.\n",
                "        -- The put-back: each part of a release's Credit still available goes back on the\n"
                "        -- Adjustment's own line with the label put back by a correction and no Rent-first\n"
                "        -- proposal (sub-slice 10f-1b, owner answer (a) to Q-2026-10-16-118 point 1: it restores\n"
                "        -- what was there before); the approver applies it as the Credit writers do\n"
                "        -- (credits.apply), each dated after the one before.\n",
            ),
            (
                "            v_proposal:=app.credit_application_proposal(p_property,(v_item->>'customer_credit_id')::uuid,\n"
                "                v_invoice.id,v_put,v_put_at);\n"
                "            IF (v_proposal->>'amount_usd_cents')::bigint IS DISTINCT FROM v_put\n"
                "                OR jsonb_array_length(v_proposal->'details') IS DISTINCT FROM 1\n"
                "                OR v_proposal->'details'->0->>'invoice_line_id' IS DISTINCT FROM v_line.id::text\n"
                "            THEN RAISE EXCEPTION 'The Credit put-back would go on another line by the Rent-first order; this waits for the owner'\n"
                "                USING ERRCODE='55000'; END IF;\n",
                "",
            ),
            (
                "'INVOICE',v_invoice.id,NULL,NULL,v_put,'RENT_THEN_RECURRING_SERVICES_PROPOSAL',NULL,\n"
                "                v_put_at,v_proposal,v_put_at,p_actor,'credits.apply');\n",
                "'INVOICE',v_invoice.id,NULL,NULL,v_put,'PUT_BACK_BY_CORRECTION',NULL,\n"
                "                NULL,NULL,v_put_at,p_actor,'credits.apply');\n",
            ),
            (
                "'INVOICE_LINE',v_line.category,v_put,v_put,v_proposal->'details'->0->>'attribution_basis',1,\n",
                "'INVOICE_LINE',v_line.category,NULL,v_put,'PUT_BACK_BY_CORRECTION',1,\n",
            ),
        ),
    ),
    (
        "app.validate_credit_application_put_back()",
        (
            (
                "                  AND replaced.within_invoice_basis='PUT_BACK_BY_CORRECTION'))\n",
                "                  AND replaced.within_invoice_basis='PUT_BACK_BY_CORRECTION')\n"
                "            -- Sub-slice 10f-1b: the put-back of an ADJUSTMENT_REVERSAL confirmed in this\n"
                "            -- transaction that lists this row (its line and release are checked when\n"
                "            -- deferred, app.adjustment_reversal_put_back_allowed).\n"
                "            OR (NEW.final_settlement_id IS NULL AND EXISTS(SELECT 1\n"
                "                FROM app.financial_draft_decisions decision\n"
                "                JOIN app.financial_drafts draft ON draft.id=decision.draft_id\n"
                "                WHERE draft.kind='ADJUSTMENT_REVERSAL' AND decision.decision='CONFIRMED'\n"
                "                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n"
                "                  AND decision.decided_at>=transaction_timestamp()\n"
                "                  AND decision.result->'put_backs' @> jsonb_build_array(\n"
                "                      jsonb_build_object('credit_application_id',NEW.id)))))\n",
            ),
        ),
    ),
)

INTERNAL = (
    "app.adjustment_reversal_put_back_allowed(app.customer_credit_applications,app.customer_credit_application_details)",
    "app.validate_adjustment_reversal_put_back()",
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
            raise RuntimeError(f"Adjustment reversal put-back contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Adjustment reversal put-back migration is forward-only")
