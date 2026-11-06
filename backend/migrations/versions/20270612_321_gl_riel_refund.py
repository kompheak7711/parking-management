# ruff: noqa: E501
"""General Ledger: a Refund paid straight from a riel account (DL-161).

Owner 05/11/2026 07:25: "Refund straight from riel account." The tenant's Refund stays in
dollars (``refund_currency`` is always USD); the ledger also needs the riel that left the riel
account, so the riel account keeps its riel and is valued right at month end.

- A Refund method may now go to a riel account (riel cash or a riel bank account such as 1021).
  A Payment Method still may not: its riel goes to its own riel account (DL-160).
- ``app.gl_refund_riel``: the riel paid for one Refund, typed once in Ledger > Needs check
  (append-only, one row per Refund).
- A Refund whose method account keeps riel waits in Needs check with "Type the riel paid for
  this Refund" until its riel is typed; then it posts DR the source, CR the riel account with
  the riel on the line.
- ``app.gl_record_refund_riel`` writes the riel (right ``ledger.money_move``, like other money
  out of a cash or bank account; Claude's choice) and one audit event.
- A Refund correction on a riel account cannot post yet; it waits in Needs check.
- ``app.gl_waiting_records`` shows the problem as it is now: a record that was waiting for a
  method account or for its riel, and has them now, says it posts at the next run.

Forward-only: Refunds posted out of a riel account cannot be read back by the old functions.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270612_321"
down_revision: str | None = "20270625_336"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RIEL_KINDS = "('CASH_KHR', 'BANK_KHR')"
TYPE_RIEL = "Type the riel paid for this Refund"
CORRECTION_WAITS = "A Refund correction on a riel account cannot post yet"
READY = "Ready: it posts at the next run"

# function signature -> ((old text, new text, times it must appear), ...)
PATCHES: dict[str, tuple[tuple[str, str, int], ...]] = {
    "app.gl_app_record_events(uuid, date, date)": (
        (
            "    SELECT r.*, rm.refund_method_id, account.code AS method_code, d.code AS deposit_code,\n",
            "    SELECT r.*, rm.refund_method_id, account.code AS method_code,\n"
            "        account.cash_kind AS method_kind, riel_paid.riel_minor AS riel_paid,\n"
            "        d.code AS deposit_code,\n",
            1,
        ),
        (
            "        SELECT a.code FROM app.gl_method_accounts AS map\n",
            "        SELECT a.code, a.cash_kind FROM app.gl_method_accounts AS map\n",
            1,
        ),
        (
            "    ) AS account ON true\n",
            "    ) AS account ON true\n"
            "    LEFT JOIN app.gl_refund_riel AS riel_paid ON riel_paid.refund_id = r.id\n",
            1,
        ),
        (
            "        CASE WHEN r.method_code IS NULL THEN 'No ledger account is set for the Refund method' END,\n",
            "        CASE WHEN r.method_code IS NULL THEN 'No ledger account is set for the Refund method'\n"
            f"            WHEN r.method_kind IN {RIEL_KINDS} AND r.riel_paid IS NULL\n"
            f"            THEN '{TYPE_RIEL}' END,\n",
            1,
        ),
        (
            "            jsonb_build_object('account', r.method_code, 'credit_cents', r.usd_accounting_value_cents,\n"
            "                'memo', r.refund_number, 'customer_id', r.recipient_customer_id))\n",
            "            jsonb_build_object('account', r.method_code, 'credit_cents', r.usd_accounting_value_cents,\n"
            "                'memo', r.refund_number, 'customer_id', r.recipient_customer_id,\n"
            f"                'original_currency', CASE WHEN r.method_kind IN {RIEL_KINDS} THEN 'KHR' END,\n"
            f"                'original_amount_minor', CASE WHEN r.method_kind IN {RIEL_KINDS}\n"
            "                    THEN r.riel_paid END))\n",
            1,
        ),
        (
            "        CASE WHEN k.correction_kind <> 'RECOVERED_BY_CHARGE' AND r.method_code IS NULL\n"
            "            THEN 'No ledger account is set for the Refund method' END,\n",
            "        CASE WHEN k.correction_kind <> 'RECOVERED_BY_CHARGE' AND r.method_code IS NULL\n"
            "            THEN 'No ledger account is set for the Refund method'\n"
            f"            WHEN k.correction_kind <> 'RECOVERED_BY_CHARGE' AND r.method_kind IN {RIEL_KINDS}\n"
            f"            THEN '{CORRECTION_WAITS}' END,\n",
            1,
        ),
    ),
    "app.gl_check_method_account()": (
        (
            "AND account.cash_kind <> 'BANK_KHR') THEN",
            "AND (account.cash_kind <> 'BANK_KHR' OR NEW.refund_method_id IS NOT NULL)) THEN",
            1,
        ),
    ),
    "app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid, text)": (
        (
            "    IF v_account.cash_kind = 'BANK_KHR' THEN\n",
            "    IF v_account.cash_kind = 'BANK_KHR' AND p_refund_method IS NULL THEN\n",
            1,
        ),
    ),
}

STRUCTURE = r"""
CREATE TABLE app.gl_refund_riel (
    id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
    property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
    refund_id uuid NOT NULL UNIQUE REFERENCES app.refunds(id) ON DELETE RESTRICT,
    riel_minor bigint NOT NULL CHECK (riel_minor BETWEEN 1 AND 9000000000000000),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
);
CREATE INDEX gl_refund_riel_property_idx ON app.gl_refund_riel (property_id);
COMMENT ON TABLE app.gl_refund_riel IS
    'The riel that left a riel account for one dollar Refund (owner 05/11/2026), typed once.';
CREATE TRIGGER gl_refund_riel_reject_update_or_delete BEFORE UPDATE OR DELETE
    ON app.gl_refund_riel FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
CREATE TRIGGER gl_refund_riel_reject_truncate BEFORE TRUNCATE ON app.gl_refund_riel
    FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
REVOKE ALL ON TABLE app.gl_refund_riel FROM PUBLIC, prm_runtime, prm_bootstrap;
GRANT SELECT ON TABLE app.gl_refund_riel TO prm_runtime, prm_financial;
"""

FUNCTIONS = rf"""
-- The riel paid for a Refund whose method account keeps riel. Only a Refund that waits for it,
-- in this Property's ledger and not posted yet.
CREATE FUNCTION app.gl_record_refund_riel(p_property uuid, p_actor uuid, p_refund uuid,
    p_riel_minor bigint, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_zone text;
    v_at timestamptz;
    v_number text;
    v_problem text;
    v_id uuid := gen_random_uuid();
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.money_move');
    IF p_riel_minor IS NULL OR p_riel_minor < 1 THEN
        RAISE EXCEPTION 'Type the riel paid, more than 0' USING ERRCODE = '22023';
    END IF;
    SELECT property.timezone_name INTO STRICT v_zone FROM app.properties AS property
    WHERE property.id = p_property;
    SELECT refund.processed_at, refund.refund_number INTO v_at, v_number
    FROM app.refunds AS refund WHERE refund.id = p_refund;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No such Refund' USING ERRCODE = 'P0002';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('gl-refund-riel:' || p_refund::text, 0));
    IF EXISTS (SELECT 1 FROM app.gl_refund_riel AS typed WHERE typed.refund_id = p_refund) THEN
        RAISE EXCEPTION 'The riel for Refund % is already typed', v_number USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
               WHERE entry.posting_key = 'refund:' || p_refund) THEN
        RAISE EXCEPTION 'Refund % is already in the ledger', v_number USING ERRCODE = '55000';
    END IF;
    SELECT event.problem INTO v_problem
    FROM app.gl_app_record_events(p_property, timezone(v_zone, v_at)::date,
        timezone(v_zone, v_at)::date) AS event
    WHERE event.posting_key = 'refund:' || p_refund;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No such Refund' USING ERRCODE = 'P0002';
    END IF;
    IF v_problem IS DISTINCT FROM '{TYPE_RIEL}' THEN
        RAISE EXCEPTION 'Refund % does not wait for riel: its method account keeps dollars',
            v_number USING ERRCODE = '55000';
    END IF;
    INSERT INTO app.gl_refund_riel (id, property_id, refund_id, riel_minor, created_by)
    VALUES (v_id, p_property, p_refund, p_riel_minor, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.refund_riel.recorded', 'gl_refund_riel',
        v_id, 'Riel paid for Refund ' || v_number, p_correlation,
        jsonb_build_object('refund_id', p_refund, 'riel_minor', p_riel_minor));
    RETURN v_id;
END $$;

-- Needs check: the kept list with each record's problem as it is now, plus the records the
-- posting job has not met yet. A record whose method account or riel is now in says so.
CREATE OR REPLACE FUNCTION app.gl_waiting_records(p_property uuid)
RETURNS TABLE (posting_key text, source_type text, source_id uuid, event_date date,
    problem text, first_seen_at timestamptz, last_seen_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    WITH live AS (
        SELECT event.posting_key, event.source_type, event.source_id, event.event_date,
            event.problem
        FROM (SELECT min(period.starts_on) AS day FROM app.gl_periods AS period
              WHERE period.property_id = p_property) AS start
        CROSS JOIN LATERAL app.gl_app_record_events(p_property, start.day,
            app.gl_today(p_property)) AS event
        WHERE start.day IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
              WHERE entry.posting_key = event.posting_key)
    )
    SELECT kept.posting_key, kept.source_type, kept.source_id, kept.event_date,
        CASE WHEN live.problem IS NOT NULL THEN live.problem
            WHEN live.posting_key IS NOT NULL
                AND (kept.problem LIKE 'No ledger account is set for the %'
                     OR kept.problem = '{TYPE_RIEL}')
            THEN '{READY}'
            ELSE kept.problem END,
        kept.first_seen_at, kept.last_seen_at
    FROM app.gl_posting_problems AS kept
    LEFT JOIN live ON live.posting_key = kept.posting_key
    WHERE kept.property_id = p_property
    UNION ALL
    SELECT live.posting_key, live.source_type, live.source_id, live.event_date, live.problem,
        statement_timestamp(), statement_timestamp()
    FROM live
    WHERE live.problem IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM app.gl_posting_problems AS known
          WHERE known.posting_key = live.posting_key)
$$;
"""

RUNTIME = ("app.gl_record_refund_riel(uuid, uuid, uuid, bigint, uuid)",)


def _literal_colons(sql: str) -> str:
    """Keep ``'refund:...'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _patch(signature: str, changes: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new, times in changes:
        if definition.count(old) != times:
            raise RuntimeError(f"{signature} changed: expected {times} of {old!r}")
        definition = definition.replace(old, new)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(_literal_colons(definition))


def upgrade() -> None:
    op.execute(STRUCTURE)
    # The events read the new table, so it comes first.
    for signature, changes in PATCHES.items():
        _patch(signature, changes)
    op.execute(_literal_colons(FUNCTIONS))
    for function in RUNTIME:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime"
        )


def downgrade() -> None:
    raise RuntimeError("The riel Refund migration is forward-only")
