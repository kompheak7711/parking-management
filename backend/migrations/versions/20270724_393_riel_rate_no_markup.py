"""DL-228 (owner 13 Nov 2026, card "Always 0%, no setting"): the riel rate has no mark-up.

Before this migration a riel Payment used ABA's USD Sell rate times 1.005 (0.5% mark-up),
rounded up to a whole riel (BR-MONEY-005 to 008). The owner asked to remove the 0.5% and chose a
fixed 0%, not a Settings value. From now on the System Exchange Rate is ABA's Sell rate itself,
rounded up to a whole riel.

1. ``app.exchange_rate_records.markup_basis_points`` accepts 0 (every new record) or 50 (records
   saved before this change). The formula check reads the record's own mark-up, so each old
   record still proves its 0.5% and each new record proves 0%.
2. ``app.execute_exchange_rate`` (Settings rate confirm) and ``app.confirm_khr_payment``
   (Receive payment in riel) write 0 and no longer multiply by 1.005.
3. The Settings rule "Riel rate: ABA Sell rate plus" (``RIEL_RATE_MARK_UP``, seeded at 0.5% by
   migration 271, never used by the program) is removed: the owner chose no setting, so the
   screen must not show a 0.5% that the app does not use. The rule only ever held setting
   values, never a money record (DL-121 (E); the precedent is migration 267's asset life rules).

No riel Payment or rate record is changed: financial records are append-only. Function
signatures and grants stay the same. Forward-only.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270724_393"
down_revision: str | None = "20270723_392"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIRM = "app.confirm_khr_payment(uuid,uuid,uuid,jsonb,jsonb)"
CONFIRM_CHANGES = (
    ("v_system:=ceil(v_reference*1.005)::bigint;", "v_system:=ceil(v_reference)::bigint;"),
    ("VALUES(v_fx_id,v_reference,50,v_system,", "VALUES(v_fx_id,v_reference,0,v_system,"),
    ("'markup_basis_points',50,", "'markup_basis_points',0,"),
)
EXECUTE = (
    "app.execute_exchange_rate(uuid,uuid,text,uuid,numeric,bigint,text,text,"
    "timestamp with time zone,uuid,jsonb)"
)
EXECUTE_CHANGES = (
    ("p_rate_id, p_reference_rate_khr_per_usd, 50,", "p_rate_id, p_reference_rate_khr_per_usd, 0,"),
)

REMOVE_RULE = """
    ALTER TABLE app.business_rules DISABLE TRIGGER business_rules_append_only_row;
    DELETE FROM app.business_rules WHERE rule_name_id IN (
        SELECT id FROM app.business_rule_names WHERE code = 'RIEL_RATE_MARK_UP'
    );
    ALTER TABLE app.business_rules ENABLE TRIGGER business_rules_append_only_row;
    ALTER TABLE app.business_rule_names DISABLE TRIGGER business_rule_names_guard_row;
    DELETE FROM app.business_rule_names WHERE code = 'RIEL_RATE_MARK_UP';
    ALTER TABLE app.business_rule_names ENABLE TRIGGER business_rule_names_guard_row;
"""


def _markup_check_name() -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint"
                " WHERE conrelid = 'app.exchange_rate_records'::regclass AND contype = 'c'"
                " AND pg_catalog.pg_get_constraintdef(oid) LIKE '%markup_basis_points = 50%'"
            )
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError("Riel mark-up check contract changed")
    return str(names[0])


def _patch(signature: str, changes: Sequence[tuple[str, str]]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in changes:
        if definition.count(before) != 1:
            raise RuntimeError(f"Riel mark-up source contract changed: {signature}")
        definition = definition.replace(before, after)
    op.execute(definition)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE app.exchange_rate_records
            DROP CONSTRAINT {_markup_check_name()},
            DROP CONSTRAINT exchange_rate_system_formula,
            ADD CONSTRAINT exchange_rate_markup_known CHECK (markup_basis_points IN (0, 50)),
            ADD CONSTRAINT exchange_rate_system_formula CHECK (
                system_rate_khr_per_usd = ceil(
                    reference_rate_khr_per_usd * (10000 + markup_basis_points) / 10000
                )::bigint
            )
        """
    )
    _patch(CONFIRM, CONFIRM_CHANGES)
    _patch(EXECUTE, EXECUTE_CHANGES)
    op.execute(REMOVE_RULE)


def downgrade() -> None:
    raise RuntimeError("The riel mark-up migration is forward-only")
