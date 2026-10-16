"""The 8a-1 allow functions need the row's own correlation and a draft naming the obligation
(V1-056 sub-slice 10c-3c-1).

Owner answer 3 to Q-2026-10-10-69 and answer (a) to Q-2026-10-10-70 (an approved tightening): an
Invoice Adjustment or a Late-payment Charge correction on an obligation a Deposit application paid
at Final Settlement passes the 8a-1 refusal only when it is linked to a correction of that closed
Settlement confirmed in this transaction by its approver (sub-slices 10c-2a-3 and 10c-3b-2), its
reference or correlation names that correction, and the correction's draft names exactly this
obligation (BR-SETTLE-012, BR-SETTLE-013, BR-AUTH-010, DB-SETTLE-005). Each case is a hand-built
correction after a real closure, always rolled back; the real writers stay covered by the
committed real-path tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from test_deposit_application_reversal_migration import begin
from test_final_settlement_migration import one
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_migration import LINK, REASON, invoice_of
from test_settlement_correction_plan_migration import closed_case, failure
from test_settlement_late_charge_deposit_refund_migration import deposit_settled_case
from test_settlement_return_reversal_migration import app_catalog

REVISION = "20261217_143"
ADJUSTMENT_ALLOWED = "app.settlement_correction_adjustment_allowed(uuid,uuid,uuid,uuid,text)"
CHARGE_ALLOWED = "app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid,uuid)"
REFUSAL = "app.refuse_deposit_applied_obligation_change()"
DEPOSIT_APPLIED = "A Deposit application paid this obligation at Final Settlement"
OVER_ADJUSTED = "Invoice Adjustment would violate the issued obligation"
OVER_REDUCED = "Late-payment correction resulting balance is invalid"
ADJUSTMENT = (
    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
    "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
    "VALUES (%s,%s,%s,'CREDIT',100,%s,%s,app.credit_excess_instant(%s,NULL),%s,"
    "'financial.approve')"
)
CHARGE_CORRECTION = (
    "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,correction_kind,"
    "amount_usd_cents,reverses_correction_id,reason,previous_obligation_usd_cents,"
    "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,correlation_id) "
    "VALUES (%s,%s,'REDUCTION',1000,NULL,%s,8000,7000,"
    "app.settlement_late_charge_instant(%s,NULL),%s,'financial.approve',%s)"
)


def named_draft(url: str, case: dict[str, Any], **payload: Any) -> UUID:
    """A hand-built SETTLEMENT_CORRECTION draft of the case's Settlement with the given keys."""
    draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "'final_settlements.prepare',%s,NULL,%s)",
            (
                case["prop"],
                case["human"],
                draft,
                Jsonb({"final_settlement_id": str(case["settlement"]), **payload}),
                REASON,
            ),
        )
    return draft


def adjusting(
    case: dict[str, Any], draft: UUID, line: UUID, *, reference: str | None = None
) -> Callable[[psycopg.Connection[Any]], None]:
    """Inside a hand-built correction of the draft, a linked 100 credit Adjustment of the line by
    the approver; the new allow function must answer true for the row it wrote."""
    invoice = invoice_of(case["url"], line)

    def action(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, draft)
        adjustment = uuid4()
        source = reference or f"settlement-correction:{correction}"
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        connection.execute(
            ADJUSTMENT, (adjustment, invoice, line, source, REASON, invoice, case["person"])
        )
        assert connection.execute(
            f"SELECT {ADJUSTMENT_ALLOWED.split('(')[0]}(%s,%s,%s,%s,%s)",
            (invoice, line, adjustment, case["person"], source),
        ).fetchone() == (True,)

    return action


def reducing(
    case: dict[str, Any], draft: UUID, *, correlation: UUID | None = None
) -> Callable[[psycopg.Connection[Any]], None]:
    """Inside a hand-built correction of the draft, a linked 1,000 REDUCTION of the Charge by the
    approver; the new allow function must answer true for the row it wrote."""
    charge = case["charge"]

    def action(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, draft)
        row = uuid4()
        correlated = correlation or correction
        connection.execute(LINK, (correction, "late_payment_charge_correction_id", row))
        connection.execute(
            CHARGE_CORRECTION, (row, charge, REASON, charge, case["person"], correlated)
        )
        assert connection.execute(
            f"SELECT {CHARGE_ALLOWED.split('(')[0]}(%s,%s,%s,%s)",
            (charge, row, case["person"], correlated),
        ).fetchone() == (True,)

    return action


def test_an_adjustment_passes_8a_1_only_with_its_correction_s_reference_and_a_draft_naming_its_line(
    migrated_database_url: str,
) -> None:
    """The Security Deposit and the remaining Pet Deposit paid the other Damage line at closure.
    A linked 100 credit Adjustment of that line by the approver, its reference the correction's
    and the draft a REFUND or CHARGE_REDUCTION naming exactly that Invoice and line, passes the
    8a-1 refusal (the new allow function answers true) and is then refused at commit, because the
    line would be paid above its new amount (23514). The same row with another correction's
    reference, or under a draft naming another line, another Invoice, another variant or a
    target_kind, is refused by 8a-1 (55000). Nothing is written."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    line, pet_line = case["other_line"], case["pet_line"]
    invoice, pet_invoice = invoice_of(url, line), invoice_of(url, pet_line)
    named = {"invoice_id": str(invoice), "invoice_line_id": str(line)}
    before = one(url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice)
    for variant, key in (("REFUND", "refund"), ("CHARGE_REDUCTION", "reduction")):
        draft = named_draft(url, case, variant=variant, **{key: named})
        assert failure(url, adjusting(case, draft, line)) == ("23514", OVER_ADJUSTED), variant
    refund = named_draft(url, case, variant="REFUND", refund=named)
    refused = (
        adjusting(case, refund, line, reference=f"settlement-correction:{uuid4()}"),
        adjusting(
            case,
            named_draft(
                url,
                case,
                variant="REFUND",
                refund={"invoice_id": str(invoice), "invoice_line_id": str(pet_line)},
            ),
            line,
        ),
        adjusting(
            case,
            named_draft(
                url,
                case,
                variant="REFUND",
                refund={"invoice_id": str(pet_invoice), "invoice_line_id": str(line)},
            ),
            line,
        ),
        adjusting(case, named_draft(url, case, variant="EXTRA_CHARGE", refund=named), line),
        adjusting(
            case,
            named_draft(
                url, case, variant="REFUND", target_kind="LATE_PAYMENT_CHARGE", refund=named
            ),
            line,
        ),
        adjusting(case, named_draft(url, case, variant="REFUND", reduction=named), line),
    )
    # Each insert is refused by 8a-1 before the action asks the allow function.
    for index, action in enumerate(refused):
        assert failure(url, action) == ("55000", DEPOSIT_APPLIED), index
    assert (
        one(url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice)
        == before
    )
    with psycopg.connect(url) as connection:
        # Outside a confirming transaction the new function answers false for any row.
        assert connection.execute(
            f"SELECT {ADJUSTMENT_ALLOWED.split('(')[0]}(%s,%s,%s,%s,%s)",
            (invoice, line, uuid4(), case["person"], "settlement-correction:x"),
        ).fetchone() == (False,)


def test_a_charge_correction_passes_8a_1_only_with_its_correction_s_correlation_and_a_named_charge(
    migrated_database_url: str,
) -> None:
    """The remaining Pet Deposit paid the whole Late-payment Charge (8,000) at closure. A linked
    1,000 REDUCTION of the Charge by the approver, its correlation the correction and the draft a
    REFUND or CHARGE_REDUCTION with target_kind LATE_PAYMENT_CHARGE naming exactly that Charge,
    passes the 8a-1 refusal (the new allow function answers true) and is then refused at commit,
    because the Charge would be paid above its new amount (23514). The same row with another
    correlation, or under a draft naming another Charge, with no target_kind or another variant, is
    refused by 8a-1 (P4603). Nothing is written."""
    url = migrated_database_url
    case = deposit_settled_case(url, 8_000)
    charge = str(case["charge"])
    count = (
        "SELECT count(*) FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=%s"
    )
    before = one(url, count, case["charge"])
    for variant, key in (("REFUND", "refund"), ("CHARGE_REDUCTION", "reduction")):
        draft = named_draft(
            url,
            case,
            variant=variant,
            target_kind="LATE_PAYMENT_CHARGE",
            **{key: {"late_payment_charge_id": charge}},
        )
        assert failure(url, reducing(case, draft)) == ("23514", OVER_REDUCED), variant
    named = {"late_payment_charge_id": charge}
    refund = named_draft(
        url, case, variant="REFUND", target_kind="LATE_PAYMENT_CHARGE", refund=named
    )
    refused = (
        reducing(case, refund, correlation=uuid4()),
        reducing(
            case,
            named_draft(
                url,
                case,
                variant="REFUND",
                target_kind="LATE_PAYMENT_CHARGE",
                refund={"late_payment_charge_id": str(uuid4())},
            ),
        ),
        reducing(case, named_draft(url, case, variant="REFUND", refund=named)),
        reducing(
            case,
            named_draft(
                url, case, variant="EXTRA_CHARGE", target_kind="LATE_PAYMENT_CHARGE", refund=named
            ),
        ),
        reducing(
            case,
            named_draft(
                url, case, variant="REFUND", target_kind="LATE_PAYMENT_CHARGE", reduction=named
            ),
        ),
    )
    # Each insert is refused by 8a-1 before the action asks the allow function.
    for index, action in enumerate(refused):
        assert failure(url, action) == ("P4603", DEPOSIT_APPLIED), index
    assert one(url, count, case["charge"]) == before


def test_the_allow_hardening_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 143 adds only the two new allow functions (no application role or PUBLIC may call
    them; SECURITY DEFINER with the fixed search path) and changes only the 8a-1 refusal (its body
    exactly the old one with the module's replacements, each anchor found once; privileges, owner,
    definer and settings kept), whose two calls now use the new functions; the old three-argument
    functions stay, unchanged and with no caller; no constraint or trigger changes; it is
    forward-only."""
    url = migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261216_142"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert revision.module.NEW_FUNCTIONS == (ADJUSTMENT_ALLOWED, CHARGE_ALLOWED)
    with psycopg.connect(url) as connection:
        for function in (ADJUSTMENT_ALLOWED, CHARGE_ALLOWED):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
            assert connection.execute(
                "SELECT prosecdef,proconfig::text FROM pg_catalog.pg_proc "
                "WHERE oid=%s::regprocedure",
                (function,),
            ).fetchone() == (True, "{search_path=pg_catalog}"), function
        found = connection.execute(
            "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (REFUSAL,)
        ).fetchone()
        assert found is not None
        source = str(found[0])
    assert "NEW.invoice_id,NEW.id,NEW.actor_id)" not in source
    assert "NEW.late_payment_charge_id,NEW.id,NEW.actor_id)" not in source
    with _temporary_migration_database("settlement_correction_allow_hardening") as temporary:
        alembic_command.upgrade(config, "20261216_142")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {ADJUSTMENT_ALLOWED, CHARGE_ALLOWED}
    assert set(before_functions) <= set(after_functions)
    patched = dict(revision.module.PATCHES)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(patched)
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement, count in replacements:
            assert body.count(anchor) == count, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
