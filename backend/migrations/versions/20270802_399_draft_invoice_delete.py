"""A Draft Invoice is changed freely and may be deleted (D6, DL-239).

Owner (12 Nov 2026, DL-226, D6). Before, a Draft was changed with a reason kept in its history,
and an unwanted Draft became Void with a reason; nothing was deleted (BR-INV-015). Now a Draft
is changed with no reason asked and may be deleted; the history of an Invoice starts at issue.

What changes:

- New ``app.delete_invoice_draft(property, invoice, actor, expected_version, audit_id)``
  (SECURITY DEFINER, EXECUTE to prm_financial only; the API needs ``invoices.create``). It
  deletes a Draft made by a person (not by a Billing Run) at the expected version, with its
  lines, their calculation parts and source claims, its Draft revision history and its command
  records, and writes one audit event ``invoice.draft_deleted`` with the Draft as it was. The
  charges the lines named stay as records. A Draft that any other record names (found from
  the foreign keys at the time of the call, so a later table is covered too) is refused: it is
  made Void as before.
- The delete passes the history guards only inside that function: a transaction setting
  ``app.draft_delete_invoice_id`` names the one Draft, and only the guards of the Invoice
  header, the Draft revision history and the Invoice command records accept a delete of that
  Draft. Only the migrator role has direct write rights on these tables.
- The Edit Draft change reason is no longer asked by the screen; the API passes a fixed text
  when none is given (no database change).

No issued Invoice can be deleted. No row is changed or deleted by this migration. This
migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270802_399"
down_revision: str | None = "20270801_398"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FLAG = "current_setting('app.draft_delete_invoice_id',true)"

HEADER = "app.protect_invoice_header_history()"
HEADER_DELETE = (
    (
        "            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Invoice history cannot be deleted'",
        "            -- D6 (DL-239): only app.delete_invoice_draft deletes, and only its Draft.\n"
        "            IF TG_OP='DELETE' AND OLD.status='DRAFT'\n"
        "                AND OLD.originating_billing_run_attempt_id IS NULL\n"
        f"                AND OLD.id::text={FLAG} THEN RETURN OLD; END IF;\n"
        "            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Invoice history cannot be deleted'",
        1,
    ),
)

REVISION = "app.protect_invoice_draft_revision_event()"
REVISION_LINE = (
    "            IF TG_OP='INSERT' AND pg_catalog.pg_trigger_depth()>1 THEN RETURN NEW; END IF;"
)
REVISION_DELETE = (
    (
        REVISION_LINE,
        REVISION_LINE + "\n"
        "            -- D6 (DL-239): the Draft's own history goes with the deleted Draft.\n"
        "            IF TG_OP='DELETE' AND OLD.invoice_id::text=\n"
        f"                {FLAG} THEN RETURN OLD; END IF;",
        1,
    ),
)

APPEND_ONLY = "app.reject_invoice_append_only_mutation()"
APPEND_ONLY_RAISE = (
    "RAISE EXCEPTION 'Financial event history is append-only' USING ERRCODE='55000';"
)
APPEND_ONLY_DELETE = (
    (
        f"        BEGIN {APPEND_ONLY_RAISE} END",
        "        BEGIN\n"
        "            -- D6 (DL-239): the command records of a deleted Draft go with it.\n"
        "            -- The inner IF reads invoice_id only on the table that has it.\n"
        "            IF TG_OP='DELETE' AND TG_TABLE_NAME='invoice_commands' THEN\n"
        f"                IF OLD.invoice_id::text={FLAG} THEN RETURN OLD; END IF;\n"
        "            END IF;\n"
        f"            {APPEND_ONLY_RAISE}\n"
        "        END",
        1,
    ),
)

DELETE_DRAFT = r"""
CREATE FUNCTION app.delete_invoice_draft(
    p_property_id uuid, p_invoice_id uuid, p_actor_id uuid, p_expected_version integer,
    p_audit_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog'
AS $function$
DECLARE
    v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz; v_before jsonb;
    v_reference record; v_named boolean;
BEGIN
    IF p_audit_id IS NULL THEN
        RAISE EXCEPTION 'Draft delete evidence is invalid' USING ERRCODE='22023';
    END IF;
    v_timezone := app.require_invoice_command_actor(p_property_id, p_actor_id);
    SELECT * INTO v_invoice FROM app.invoices WHERE id = p_invoice_id FOR UPDATE;
    IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id THEN
        RAISE EXCEPTION 'Invoice was not found' USING ERRCODE = 'P4501';
    END IF;
    IF p_expected_version IS NULL OR v_invoice.version <> p_expected_version THEN
        RAISE EXCEPTION 'Invoice version:%', v_invoice.version USING ERRCODE = 'P4504';
    END IF;
    IF v_invoice.status <> 'DRAFT' OR v_invoice.originating_billing_run_attempt_id IS NOT NULL THEN
        RAISE EXCEPTION 'Only a Draft made by a person can be deleted' USING ERRCODE = 'P4502';
    END IF;
    IF v_invoice.lease_id IS NOT NULL THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('invoice-lease:' || v_invoice.lease_id::text, 0));
    END IF;
    -- Any record outside the Draft's own parts that names the Draft or one of its lines keeps
    -- it: such a Draft belongs to another step and is made Void instead.
    FOR v_reference IN
        SELECT constraint_row.conrelid::regclass AS holder, holder_column.attname AS column_name,
            constraint_row.confrelid::regclass AS target
        FROM pg_catalog.pg_constraint AS constraint_row
        CROSS JOIN LATERAL unnest(constraint_row.conkey, constraint_row.confkey)
            AS pair(holder_number, target_number)
        JOIN pg_catalog.pg_attribute AS holder_column
          ON holder_column.attrelid = constraint_row.conrelid
         AND holder_column.attnum = pair.holder_number
        JOIN pg_catalog.pg_attribute AS target_column
          ON target_column.attrelid = constraint_row.confrelid
         AND target_column.attnum = pair.target_number
        WHERE constraint_row.contype = 'f'
          AND target_column.attname = 'id'
          AND (
            (constraint_row.confrelid = 'app.invoices'::regclass
             AND constraint_row.conrelid NOT IN ('app.invoice_lines'::regclass,
                'app.active_invoice_source_claims'::regclass,
                'app.invoice_draft_revision_events'::regclass,
                'app.invoice_commands'::regclass))
            OR (constraint_row.confrelid = 'app.invoice_lines'::regclass
             AND constraint_row.conrelid NOT IN ('app.active_invoice_source_claims'::regclass,
                'app.invoice_line_calculation_components'::regclass))
          )
    LOOP
        IF v_reference.target = 'app.invoices'::regclass THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE %I = $1)',
                v_reference.holder, v_reference.column_name)
                INTO v_named USING p_invoice_id;
        ELSE
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE %I IN '
                '(SELECT id FROM app.invoice_lines WHERE invoice_id = $1))',
                v_reference.holder, v_reference.column_name)
                INTO v_named USING p_invoice_id;
        END IF;
        IF v_named THEN
            RAISE EXCEPTION 'This Draft belongs to another record; make it Void instead'
                USING ERRCODE = 'P4502';
        END IF;
    END LOOP;
    v_now := clock_timestamp();
    v_before := app.invoice_resource_snapshot(p_invoice_id);
    -- A line or part deleted from a Draft is recorded as Draft history by the line guard, as
    -- user correction is, and the guard checks the person who last changed the Draft.
    PERFORM set_config('app.draft_correction_actor_id', p_actor_id::text, true);
    PERFORM set_config('app.draft_correction_reason', 'Draft Invoice deleted before issue', true);
    IF v_invoice.version = 2147483647 THEN
        RAISE EXCEPTION 'Invoice version cannot advance' USING ERRCODE = 'P4507';
    END IF;
    UPDATE app.invoices SET updated_by = p_actor_id, updated_at = v_now, version = version + 1
        WHERE id = p_invoice_id;
    PERFORM set_config('app.draft_delete_invoice_id', p_invoice_id::text, true);
    DELETE FROM app.invoice_line_calculation_components
        WHERE invoice_line_id IN (SELECT id FROM app.invoice_lines WHERE invoice_id = p_invoice_id);
    DELETE FROM app.invoice_lines WHERE invoice_id = p_invoice_id;
    DELETE FROM app.invoice_draft_revision_events WHERE invoice_id = p_invoice_id;
    DELETE FROM app.invoice_commands WHERE invoice_id = p_invoice_id;
    DELETE FROM app.invoices WHERE id = p_invoice_id;
    PERFORM set_config('app.draft_delete_invoice_id', '', true);
    SET CONSTRAINTS ALL IMMEDIATE;
    INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action, entity_type,
        entity_id, reason, authorization_reference, property_id, previous_state,
        resulting_state, correlation_id, source, outcome, authorization_evidence,
        customer_id, lease_id)
    VALUES (p_audit_id, v_now, timezone(v_timezone, v_now)::date, p_actor_id,
        'invoice.draft_deleted', 'invoice', p_invoice_id, 'Draft Invoice deleted before issue',
        'invoices.create', p_property_id, v_before, NULL, p_audit_id, 'API', 'SUCCEEDED',
        jsonb_build_object('capability', 'invoices.create'),
        v_invoice.customer_id, v_invoice.lease_id);
    RETURN jsonb_build_object('invoice_id', p_invoice_id, 'deleted', true);
END
$function$;
REVOKE ALL ON FUNCTION app.delete_invoice_draft(uuid, uuid, uuid, integer, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.delete_invoice_draft(uuid, uuid, uuid, integer, uuid)
    TO prm_financial;
"""


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _changed(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> str:
    definition = _definition(signature)
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Draft delete source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def upgrade() -> None:
    _run(_changed(HEADER, HEADER_DELETE))
    _run(_changed(REVISION, REVISION_DELETE))
    _run(_changed(APPEND_ONLY, APPEND_ONLY_DELETE))
    _run(DELETE_DRAFT)


def downgrade() -> None:
    raise RuntimeError("the Draft Invoice delete migration is forward-only")
