# ruff: noqa: E501
"""Problem reports: a Problem report from a move-out inspection finding (DL-132).

Mock-up round 32 A6 and the Problem report PRD idea 6 ("from an inspection finding, one tap"),
approved by the owner on 03/11/2026:

1. ``app.problem_report_inspection_links``: one Problem report for one inspection finding,
   append-only. A finding has at most one report.
2. ``app.add_problem_report`` takes the source ``INSPECTION`` with a ``finding_id``: the report
   is a Unit Problem in the inspected Lease's Unit, from an inspection still in force, and the
   finding must not have a report yet. Any other source refuses a ``finding_id``.
3. ``app.problem_report_finding`` (``problem_reports.add``): what the New Problem report form
   copies from a finding (the Unit, the text, the inspection day), and the report it already has.
4. ``app.problem_report_json`` gains ``finding`` (the inspection, its day and the finding's text).

The finding alone still charges nothing; the Damage charge stays on the move-out steps. Photos
wait for the Telegram shared media files. Technical choices by Claude under the owner's
2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270512_292"
down_revision: str | None = "20270511_291"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADD = "app.add_problem_report(uuid, jsonb, uuid, uuid)"
ADD_SOURCE_BEFORE = "IF v_source IS NULL OR v_source NOT IN ('PHONE', 'WALKIN', 'SEEN') THEN"
ADD_SOURCE_AFTER = (
    "IF v_source IS NULL OR v_source NOT IN ('PHONE', 'WALKIN', 'SEEN', 'INSPECTION') THEN"
)
ADD_EVENT_BEFORE = """PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', v_source), p_actor);"""
ADD_EVENT_AFTER = """PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', v_source), p_actor);
        -- DL-132: a report made from a move-out inspection finding keeps the link.
        IF v_source = 'INSPECTION' OR p_report ? 'finding_id' THEN
            INSERT INTO app.problem_report_inspection_links (report_id, finding_id, created_by)
            VALUES (v_id, app.problem_report_finding_for(p_property, p_report, v_kind, v_unit,
                v_source), p_actor);
        END IF;"""

READ_JSON = "app.problem_report_json(uuid, boolean)"
JSON_BEFORE = "'done_at', base.done_at,"
JSON_AFTER = (
    "'done_at', base.done_at,\n            'finding', app.problem_report_finding_json(base.id),"
)

TABLES = """
    CREATE TABLE app.problem_report_inspection_links (
        report_id uuid PRIMARY KEY REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        finding_id uuid NOT NULL UNIQUE
            REFERENCES app.inspection_damage_findings (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
            CHECK (isfinite(created_at)),
        created_by uuid NOT NULL REFERENCES app.user_accounts (actor_id) ON DELETE RESTRICT
    );
    CREATE TRIGGER problem_report_inspection_links_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_inspection_links
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_inspection_links_no_truncate BEFORE TRUNCATE
        ON app.problem_report_inspection_links
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
"""

FUNCTIONS = """
    -- The finding a new report comes from: in this Property, in the report's Unit, from an
    -- inspection still in force, and with no report yet.
    CREATE FUNCTION app.problem_report_finding_for(p_property uuid, p_report jsonb,
        p_kind text, p_unit uuid, p_source text) RETURNS uuid
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_finding uuid;
        v_unit uuid;
        v_replaced boolean;
    BEGIN
        IF p_source <> 'INSPECTION' THEN
            RAISE EXCEPTION 'Only a report from an inspection has a finding' USING ERRCODE = '22023';
        END IF;
        BEGIN
            v_finding := (p_report ->> 'finding_id')::uuid;
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Choose the inspection finding' USING ERRCODE = '22023';
        END;
        IF v_finding IS NULL THEN
            RAISE EXCEPTION 'Choose the inspection finding' USING ERRCODE = '22023';
        END IF;
        IF p_kind <> 'UNIT' THEN
            RAISE EXCEPTION 'A report from an inspection finding is a Unit Problem'
                USING ERRCODE = '22023';
        END IF;
        SELECT lease.unit_id, EXISTS (SELECT 1 FROM app.move_out_inspections AS later
                WHERE later.supersedes_inspection_id = inspection.id)
        INTO v_unit, v_replaced
        FROM app.inspection_damage_findings AS finding
        JOIN app.move_out_inspections AS inspection ON inspection.id = finding.inspection_id
        JOIN app.leases AS lease ON lease.id = inspection.lease_id
        WHERE finding.id = v_finding AND inspection.property_id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the inspection finding does not exist' USING ERRCODE = '22023';
        END IF;
        IF v_unit IS DISTINCT FROM p_unit THEN
            RAISE EXCEPTION 'The report must be in the inspected Unit' USING ERRCODE = '22023';
        END IF;
        IF v_replaced THEN
            RAISE EXCEPTION 'This inspection was replaced by a new one' USING ERRCODE = '55000';
        END IF;
        IF EXISTS (SELECT 1 FROM app.problem_report_inspection_links AS link
                   WHERE link.finding_id = v_finding) THEN
            RAISE EXCEPTION 'This finding already has a Problem report' USING ERRCODE = '55000';
        END IF;
        RETURN v_finding;
    END $$;
    REVOKE ALL ON FUNCTION app.problem_report_finding_for(uuid, jsonb, text, uuid, text) FROM PUBLIC;

    -- The finding of one report, on every read of it.
    CREATE FUNCTION app.problem_report_finding_json(p_report uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object('finding_id', finding.id, 'inspection_id', inspection.id,
            'lease_id', inspection.lease_id, 'inspection_date', inspection.inspection_date,
            'ordinal', finding.ordinal, 'description', finding.description)
        FROM app.problem_report_inspection_links AS link
        JOIN app.inspection_damage_findings AS finding ON finding.id = link.finding_id
        JOIN app.move_out_inspections AS inspection ON inspection.id = finding.inspection_id
        WHERE link.report_id = p_report
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_finding_json(uuid) FROM PUBLIC;

    -- What the New Problem report form copies from a finding, and its report if it has one.
    CREATE FUNCTION app.problem_report_finding(p_property uuid, p_actor uuid, p_finding uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_found jsonb;
    BEGIN
        PERFORM app.require_product_right(p_actor, 'problem_reports.add', p_property);
        SELECT jsonb_build_object('finding_id', finding.id, 'inspection_id', inspection.id,
            'lease_id', inspection.lease_id, 'inspection_date', inspection.inspection_date,
            'ordinal', finding.ordinal, 'description', finding.description,
            'pet_related', finding.pet_related, 'unit_id', unit.id,
            'unit_number', unit.unit_number,
            'replaced', EXISTS (SELECT 1 FROM app.move_out_inspections AS later
                WHERE later.supersedes_inspection_id = inspection.id),
            'report', (SELECT jsonb_build_object('report_id', report.id,
                    'report_number', report.report_number)
                FROM app.problem_report_inspection_links AS link
                JOIN app.problem_reports AS report ON report.id = link.report_id
                WHERE link.finding_id = finding.id))
        INTO v_found
        FROM app.inspection_damage_findings AS finding
        JOIN app.move_out_inspections AS inspection ON inspection.id = finding.inspection_id
        JOIN app.leases AS lease ON lease.id = inspection.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE finding.id = p_finding AND inspection.property_id = p_property;
        IF v_found IS NULL THEN
            RAISE EXCEPTION 'the inspection finding does not exist' USING ERRCODE = '22023';
        END IF;
        RETURN v_found;
    END $$;
    REVOKE ALL ON FUNCTION app.problem_report_finding(uuid, uuid, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.problem_report_finding(uuid, uuid, uuid) TO prm_runtime;
"""


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
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    _patch(ADD, ((ADD_SOURCE_BEFORE, ADD_SOURCE_AFTER), (ADD_EVENT_BEFORE, ADD_EVENT_AFTER)))
    _patch(READ_JSON, ((JSON_BEFORE, JSON_AFTER),))
    op.execute("GRANT SELECT ON TABLE app.problem_report_inspection_links TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("The Problem report from a finding migration is forward-only")
