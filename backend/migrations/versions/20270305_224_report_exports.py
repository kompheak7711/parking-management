# ruff: noqa: E501
"""V1-057 step 4: the audit search record and the export files (DL-072 answers 4, 12 and 14).

1. `app.record_report_activity(actor, property, allowed, kind, capability, details, correlation)`
   writes one audit event for an audit search (`audit.searched`), a report export
   (`report.exported`) or an audit export (`audit.exported`), after the same active-person and
   allowed-Property check as the report reads. The details are the filters, the row count, the
   file type and the file's SHA-256 fingerprint (`file_sha256`); an audit export must carry its
   fingerprint (DL-072 answer 12). Ordinary report views write nothing.
2. `app.report_export_files`: the file of a large export (an export job, API-078), kept 24 hours
   for the person who made it and then deleted (DL-072 answer 4). A small export downloads at
   once and is not stored. The runtime role has no direct access: `app.store_report_export`
   saves a file (checking its fingerprint) and `app.take_report_export` hands it back to the
   same person while it is fresh; each first deletes the files older than 24 hours.

These are not financial records: an export file is a copy of a report, so deleting it after
24 hours removes no history (the audit event of the export stays).
"""

from alembic import op

revision = "20270305_224"
down_revision = "20270304_223"
branch_labels = None
depends_on = None

RECORD = "app.record_report_activity(uuid,uuid,uuid[],text,text,jsonb,uuid)"
STORE = "app.store_report_export(uuid,uuid,uuid[],uuid,text,text,text,text,bytea,text,integer)"
TAKE = "app.take_report_export(uuid,uuid,uuid[],uuid)"

SQL = """
    CREATE TABLE app.report_export_files (
        id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
        property_id uuid NOT NULL REFERENCES app.properties(id),
        actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id),
        report text NOT NULL CHECK (report ~ '^[a-z_]{1,64}$'),
        file_type text NOT NULL CHECK (file_type IN ('xlsx','pdf')),
        file_name text NOT NULL CHECK (file_name ~ '^[A-Za-z0-9_.-]{1,160}$'),
        media_type text NOT NULL CHECK (media_type IN (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/pdf')),
        content bytea NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 26214400),
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        row_count integer NOT NULL CHECK (row_count>=0),
        created_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        CHECK (expires_at=created_at+interval '24 hours')
    );
    CREATE INDEX report_export_files_expires_at ON app.report_export_files(expires_at);
    REVOKE ALL ON app.report_export_files FROM PUBLIC;

    CREATE FUNCTION app.record_report_activity(p_actor uuid, p_property uuid, p_allowed uuid[],
        p_kind text, p_capability text, p_details jsonb, p_correlation uuid)
    RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_at timestamptz := statement_timestamp();
        v_event uuid := gen_random_uuid();
        v_action text;
        v_entity text;
        v_reason text;
    BEGIN
        IF p_details IS NULL OR jsonb_typeof(p_details)<>'object' OR octet_length(p_details::text)>8000
            OR p_correlation IS NULL
        THEN RAISE EXCEPTION 'Report activity details are invalid' USING ERRCODE='22023'; END IF;
        IF p_kind='audit_search' AND p_capability='audit.view' THEN
            v_action := 'audit.searched'; v_entity := 'audit_search';
            v_reason := 'Audit search (DL-072 answer 14)';
        ELSIF p_kind='report_export' AND p_capability='data.export' THEN
            v_action := 'report.exported'; v_entity := 'report_export';
            v_reason := 'Report export (DL-072 answer 14)';
        ELSIF p_kind='audit_export' AND p_capability='audit.export'
            AND COALESCE(p_details->>'file_sha256','') ~ '^[0-9a-f]{64}$' THEN
            v_action := 'audit.exported'; v_entity := 'audit_export';
            v_reason := 'Audit export with its SHA-256 fingerprint (DL-072 answers 12 and 14)';
        ELSE
            RAISE EXCEPTION 'Report activity kind is invalid' USING ERRCODE='22023';
        END IF;
        INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
            entity_type, entity_id, reason, authorization_reference, property_id,
            previous_state, resulting_state, correlation_id, source, outcome)
        VALUES (v_event, v_at, timezone(v_timezone, v_at)::date, p_actor, v_action, v_entity,
            COALESCE((p_details->>'export_id')::uuid, v_event), v_reason, p_capability,
            p_property, NULL, p_details, p_correlation, 'API', 'SUCCEEDED');
        RETURN v_event;
    END $$;

    CREATE FUNCTION app.store_report_export(p_actor uuid, p_property uuid, p_allowed uuid[],
        p_id uuid, p_report text, p_file_type text, p_file_name text, p_media_type text,
        p_content bytea, p_sha256 text, p_row_count integer)
    RETURNS timestamptz LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    DECLARE v_at timestamptz := statement_timestamp();
    BEGIN
        PERFORM app.report_actor_property(p_actor, p_property, p_allowed);
        DELETE FROM app.report_export_files WHERE expires_at<=v_at;
        IF p_content IS NULL OR encode(sha256(p_content),'hex') IS DISTINCT FROM p_sha256 THEN
            RAISE EXCEPTION 'Export file fingerprint does not match' USING ERRCODE='22023';
        END IF;
        INSERT INTO app.report_export_files (id, property_id, actor_id, report, file_type,
            file_name, media_type, content, sha256, row_count, created_at, expires_at)
        VALUES (p_id, p_property, p_actor, p_report, p_file_type, p_file_name, p_media_type,
            p_content, p_sha256, p_row_count, v_at, v_at+interval '24 hours');
        RETURN v_at+interval '24 hours';
    END $$;

    CREATE FUNCTION app.take_report_export(p_actor uuid, p_property uuid, p_allowed uuid[], p_id uuid)
    RETURNS TABLE(report text, file_type text, file_name text, media_type text, content bytea,
        sha256 text, row_count integer, expires_at timestamptz)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column
    BEGIN
        PERFORM app.report_actor_property(p_actor, p_property, p_allowed);
        DELETE FROM app.report_export_files WHERE expires_at<=statement_timestamp();
        RETURN QUERY
        SELECT file.report, file.file_type, file.file_name, file.media_type, file.content,
               file.sha256, file.row_count, file.expires_at
        FROM app.report_export_files file
        WHERE file.id=p_id AND file.property_id=p_property AND file.actor_id=p_actor;
    END $$;
"""


def upgrade() -> None:
    op.execute(SQL)
    for function in (RECORD, STORE, TAKE):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the audit record and export files are part of the forward-only chain."""
    raise RuntimeError("V1-057 report exports migration is forward-only")
