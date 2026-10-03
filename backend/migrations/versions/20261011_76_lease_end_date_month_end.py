# ruff: noqa: E501
"""Require a Lease End Date on the last day of a calendar month (BR-LEASE-031, DL-069).

Owner-approved tightening (DL-069 and the V1-056 plan answer of 2026-10-03): the check lives
in the Lease draft, draft update and signing functions only. No table constraint is added and
no existing Lease row is read, changed or revalidated. An idempotent replay of an earlier
accepted command still returns its recorded result, because the check runs after the replay.
"""

from alembic import op
from sqlalchemy import text

revision = "20261011_76"
down_revision = "20261010_75"
branch_labels = None
depends_on = None

REPLAY = "IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;\n"
DRAFT_CHECK = (
    REPLAY
    + """            IF p_end_date IS NOT NULL
                AND p_end_date <> (date_trunc('month', p_end_date) + interval '1 month - 1 day')::date
            THEN
                RAISE EXCEPTION 'Lease End Date must be the last day of a calendar month'
                    USING ERRCODE = '22023';
            END IF;
"""
)
SIGN_ANCHOR = "THEN RAISE EXCEPTION 'Lease terms are incomplete' USING ERRCODE = '23514'; END IF;\n"
SIGN_CHECK = (
    SIGN_ANCHOR
    + """            IF v_lease.end_date
                <> (date_trunc('month', v_lease.end_date) + interval '1 month - 1 day')::date
            THEN
                RAISE EXCEPTION 'Lease End Date must be the last day of a calendar month'
                    USING ERRCODE = '22023';
            END IF;
"""
)
TARGETS = (
    (
        "app.create_lease_draft(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,uuid,text,uuid)",
        REPLAY,
        DRAFT_CHECK,
    ),
    (
        "app.create_lease_draft_with_terms(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,uuid,jsonb,jsonb,jsonb,jsonb,uuid,text,uuid)",
        REPLAY,
        DRAFT_CHECK,
    ),
    (
        "app.update_lease_draft(uuid,uuid,text,uuid,uuid,integer,date,date,bigint,text,text,uuid)",
        REPLAY,
        DRAFT_CHECK,
    ),
    (
        "app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)",
        SIGN_ANCHOR,
        SIGN_CHECK,
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for signature, anchor, replacement in TARGETS:
        definition = bind.execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        ).scalar_one()
        if definition.count(anchor) != 1:
            raise RuntimeError(f"Lease End Date source contract changed: {signature}")
        op.execute(definition.replace(anchor, replacement, 1))


def downgrade() -> None:
    raise RuntimeError("Lease End Date month-end check is forward-only")
