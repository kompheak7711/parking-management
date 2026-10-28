# ruff: noqa: E501
"""Report broken on a Utility Meter (V1-060 B6; DL-104).

Revision ID: 20270329_248
Revises: 20270328_247
Create Date: 2026-10-28

The owner asked on 2026-10-28 how staff report a broken meter or change its status. The
owner-approved DESIGN.md "Meter dialogs" already has "Report broken": the date it was found broken
and a reason, both required; the meter then shows "Broken since ..." and its readings are no longer
accepted. A broken meter must be replaced; there is no "stop without replacing" action
(BR-UTIL-006, DB-UTIL-001; owner, 13/10/2026). Until now the failure date was written only by
Replace meter, so a meter found broken stayed "Working" until the new meter was put in.

- app.utility_meter_failure_reports (append-only, one per Meter) keeps the date found broken, the
  reason, who reported it and when, with the request key and digest of the command.
- app.report_utility_meter_failure_api sets the Meter's failure_date before any replacement: only
  a current Meter that is not broken yet, at the expected version, on a date not before the Meter
  was put in or its latest Reading and not after today in Phnom Penh. From then on the existing
  guards refuse its Readings after that date, and the guard that keeps a failure date once set
  makes Replace meter use the same date.
- utility_api_commands accepts the new action REPORT_METER_FAILURE for the command replay.

The function is SECURITY DEFINER with a fixed search_path and EXECUTE to prm_runtime only, like
the other Utility API commands; the table is read by prm_runtime and prm_financial and written
only by the function.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270329_248"
down_revision: str | None = "20270328_247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "app.report_utility_meter_failure_api(uuid,uuid,integer,date,text,uuid,uuid,text)"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.utility_api_commands DROP CONSTRAINT utility_api_commands_action_check;
        ALTER TABLE app.utility_api_commands ADD CONSTRAINT utility_api_commands_action_check
            CHECK (action IN ('INSTALL_METER','REPLACE_METER','RECORD_READING',
                'RECORD_READING_BATCH','CORRECT_READING','REPORT_METER_FAILURE'));

        CREATE TABLE app.utility_meter_failure_reports (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'::uuid),
            meter_id uuid NOT NULL UNIQUE REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            failure_date date NOT NULL,
            reason text NOT NULL CHECK (
                length(btrim(reason)) BETWEEN 1 AND 500 AND reason=btrim(reason)
            ),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            expected_meter_version integer NOT NULL CHECK (expected_meter_version>0),
            request_idempotency_key uuid NOT NULL,
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{64}$'),
            CONSTRAINT utility_meter_failure_reports_chronology CHECK (
                timezone('Asia/Phnom_Penh',occurred_at)::date>=failure_date
            ),
            CONSTRAINT utility_meter_failure_reports_api_command_fk
                FOREIGN KEY(actor_id,request_idempotency_key,meter_id,request_digest)
                REFERENCES app.utility_api_commands(
                    actor_id,idempotency_key,resource_id,request_digest
                ) ON DELETE RESTRICT
        );
        COMMENT ON TABLE app.utility_meter_failure_reports IS
            'V1-060 B6 (DL-104): Report broken; the Meter keeps the same failure_date until it is replaced';
        CREATE TRIGGER utility_meter_failure_reports_append_only
            BEFORE UPDATE OR DELETE ON app.utility_meter_failure_reports
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_meter_failure_reports_reject_truncate
            BEFORE TRUNCATE ON app.utility_meter_failure_reports
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_utility_history_mutation();

        CREATE FUNCTION app.report_utility_meter_failure_api(
            p_meter_id uuid,p_report_id uuid,p_expected_version integer,p_failure_date date,
            p_reason text,p_actor_id uuid,p_idempotency_key uuid,p_request_digest text
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_meter app.utility_meters%ROWTYPE; v_property_id uuid;
                v_replay app.utility_api_commands%ROWTYPE; v_latest date;
        BEGIN
            IF p_meter_id IS NULL OR p_report_id IS NULL
                OR p_report_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_expected_version IS NULL OR p_expected_version<1
                OR p_failure_date IS NULL OR p_reason IS NULL
                OR length(btrim(p_reason)) NOT BETWEEN 1 AND 500 OR p_reason<>btrim(p_reason)
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Meter failure report is invalid' USING ERRCODE='22023'; END IF;
            SELECT * INTO v_meter FROM app.utility_meters WHERE id=p_meter_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Meter was not found' USING ERRCODE='P0002'; END IF;
            SELECT property_id INTO STRICT v_property_id FROM app.units WHERE id=v_meter.unit_id;
            PERFORM app.assert_active_financial_actor(p_actor_id,v_property_id);
            PERFORM app.lock_utility_unit_type(v_meter.unit_id,v_meter.utility_type);
            PERFORM app.lock_utility_meter_sequence(p_meter_id);
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'REPORT_METER_FAILURE' OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay.resource_id;
            END IF;
            SELECT * INTO STRICT v_meter FROM app.utility_meters WHERE id=p_meter_id FOR UPDATE;
            IF v_meter.version<>p_expected_version THEN
                RAISE EXCEPTION 'Utility Meter version changed' USING ERRCODE='PRV01',DETAIL=v_meter.version::text;
            END IF;
            IF v_meter.deactivated_date IS NOT NULL OR v_meter.failure_date IS NOT NULL THEN
                RAISE EXCEPTION 'Utility Meter is already broken or replaced' USING ERRCODE='55000';
            END IF;
            -- A Reading after the failure date would be a Reading of a broken Meter.
            SELECT max(reading_date) INTO v_latest FROM app.utility_readings
             WHERE meter_id=p_meter_id;
            IF p_failure_date<v_meter.installed_date OR p_failure_date<v_latest
                OR p_failure_date>timezone('Asia/Phnom_Penh',statement_timestamp())::date
            THEN RAISE EXCEPTION 'Meter failure date is outside the Meter history' USING ERRCODE='23514';
            END IF;
            UPDATE app.utility_meters SET failure_date=p_failure_date,version=version+1,
                updated_at=statement_timestamp(),updated_by=p_actor_id
             WHERE id=p_meter_id;
            INSERT INTO app.utility_api_commands(actor_id,idempotency_key,action,request_digest,resource_id)
            VALUES(p_actor_id,p_idempotency_key,'REPORT_METER_FAILURE',p_request_digest,p_meter_id);
            INSERT INTO app.utility_meter_failure_reports(id,meter_id,failure_date,reason,actor_id,
                occurred_at,expected_meter_version,request_idempotency_key,request_digest)
            VALUES(p_report_id,p_meter_id,p_failure_date,p_reason,p_actor_id,statement_timestamp(),
                p_expected_version,p_idempotency_key,p_request_digest);
            RETURN p_meter_id;
        END $$;
    """)
    op.execute(
        "REVOKE ALL ON TABLE app.utility_meter_failure_reports "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT ON TABLE app.utility_meter_failure_reports TO prm_runtime, prm_financial"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("V1-060 Report broken meter migration is forward-only")
