"""Close the manual late-payment decision and the free charge corrections (V1-056 slice 11g-3;
DL-087, DL-076 answers 1 and 4).

DL-076 answers 1 and 4: the late-payment charge is added by the automatic pass of slice 11g-1,
with no Manager decision, and it changes only by a reduction or waiver with one of three fixed
reasons (slice 11g-2). From the Property's first finished pass on (a row in
`app.late_payment_charge_runs`):

1. `app.finalize_late_payment_decision` refuses a person's decision (P4603).
2. `app.correct_late_payment_charge` refuses every free correction: a REDUCTION or
   CHARGE_REVERSAL without a fixed reason, and a REDUCTION_REVERSAL, which would raise the
   amount (P4603).

Both refusals come after the replay check and the actor and Property lock, so an exact repeat
of an earlier request still gets its stored answer; they also come before the input and target
checks, so after the first pass a malformed request answers 409 too. The decisions and corrections recorded
before stay as history; the Final Settlement late-charge commands do not use these functions
and are not changed.

3. `app.late_payment_review_snapshot` adds the blocker `AUTOMATIC_CHARGE_ONLY` once a finished
   pass has covered the Invoice's charge day (the day after its Due Date), so no Invoice reads as
   waiting for a manual decision: the old Invoices screen hides the decision form, and the Final
   Settlement preview no longer raises `LATE_PAYMENT_DECISION_MISSING` for an Invoice the pass
   did not charge (an Invoice already overdue before the first pass gets no charge, owner answer
   of 2026-10-25). Until a pass has covered that day the preview still waits for an unpaid or
   partly paid Invoice, so such a Final Settlement cannot close before the pass writes its
   charge (review round 2). An Invoice paid in full after its charge moment but before the pass
   is not waited for (a gap from slice 11g-1, on the slice 12 list).
4. `app.late_payment_charge_snapshot` adds `manual_corrections_open: false` from the first pass
   on (the key is absent before), so the old screen hides the free correction form.

Additive: two refusals and two read additions in existing functions; no table, grant or data
change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270212_200"
down_revision = "20270211_199"
branch_labels = None
depends_on = None

ANCHOR = "            v_timezone:=app.require_late_payment_actor(p_property_id,p_actor_id);\n"


def _refusal(words: str) -> str:
    return (
        ANCHOR
        + "            -- V1-056 slice 11g-3 (DL-087): from the first automatic pass on, the pass\n"
        + "            -- adds each charge and only a reduction with a fixed reason changes it.\n"
        + "            IF EXISTS (SELECT 1 FROM app.late_payment_charge_runs run\n"
        + "                WHERE run.property_id=p_property_id)\n"
        + f"            THEN RAISE EXCEPTION '{words}'\n"
        + "                USING ERRCODE='P4603'; END IF;\n"
    )


PATCHES = (
    (
        "app.finalize_late_payment_decision"
        "(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
        _refusal("Late-payment charges are added automatically; a manual decision is refused"),
    ),
    (
        "app.correct_late_payment_charge"
        "(uuid,uuid,uuid,uuid,text,text,text,bigint,uuid,text,uuid,uuid)",
        _refusal("A late-payment charge changes only by a reduction with a fixed reason"),
    ),
)


REVIEW = "app.late_payment_review_snapshot(uuid)"
REVIEW_BEFORE = "            IF v_decision IS NOT NULL THEN\n"
REVIEW_AFTER = (
    "            -- V1-056 slice 11g-3 (DL-087): once a finished pass covered the charge day no\n"
    "            -- Invoice waits for a manual decision; before that the preview still waits.\n"
    "            IF EXISTS (SELECT 1 FROM app.late_payment_charge_runs run\n"
    "                WHERE run.property_id=v_property_id\n"
    "                    AND run.business_date>=v_invoice.due_date+1) THEN\n"
    "                v_blockers:=v_blockers||jsonb_build_array('AUTOMATIC_CHARGE_ONLY');\n"
    "            END IF;\n" + REVIEW_BEFORE
)
CHARGE = "app.late_payment_charge_snapshot(uuid)"
CHARGE_BEFORE = (
    "                'created_at',v_charge.created_at,"
    "'created_by',COALESCE(v_charge.created_by,v_charge.created_by_service)\n"
    "            );\n"
)
CHARGE_AFTER = (
    "                'created_at',v_charge.created_at,"
    "'created_by',COALESCE(v_charge.created_by,v_charge.created_by_service)\n"
    "            )\n"
    "            -- V1-056 slice 11g-3 (DL-087): the free corrections are closed.\n"
    "            ||CASE WHEN EXISTS (SELECT 1 FROM app.late_payment_charge_runs run\n"
    "                    WHERE run.property_id=v_property_id)\n"
    "                THEN jsonb_build_object('manual_corrections_open',false) ELSE '{}'::jsonb END;\n"
)


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Late-payment contract changed: {signature}")
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    for signature, after in PATCHES:
        _patch(signature, ANCHOR, after)
    _patch(REVIEW, REVIEW_BEFORE, REVIEW_AFTER)
    _patch(CHARGE, CHARGE_BEFORE, CHARGE_AFTER)


def downgrade() -> None:
    raise RuntimeError("Manual late-payment command closure migration is forward-only")
