# ruff: noqa: E501
"""Add narrow enforcement discovery and explicitly scoped read-only evaluation."""

from alembic import op

revision = "20260910_51"
down_revision = "20260910_50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The existing Customer trigger needs no PUBLIC execution grant. Revoke it
    # forward so a dedicated evaluator cannot attach this definer to another table.
    # Keep migration16, the trigger definition and all Customer history unchanged.
    op.execute("REVOKE ALL ON FUNCTION app.sync_customer_email_match_key() FROM PUBLIC")
    op.execute(r"""
        CREATE FUNCTION app.lease_enforcement_active_human(p_actor uuid)
        RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts a JOIN app.actor_identities i ON i.actor_id=a.actor_id
                WHERE a.actor_id=p_actor AND a.lifecycle_state='active' AND i.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Lease enforcement actor is not active' USING ERRCODE='P5406'; END IF;
        END $$;

        CREATE FUNCTION app.lease_enforcement_workspaces(p_actor uuid,p_properties uuid[],p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE v_items jsonb;
        BEGIN
            PERFORM app.lease_enforcement_active_human(p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_after='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Enforcement workspace page is invalid' USING ERRCODE='P5402'; END IF;
            SELECT COALESCE(jsonb_agg(to_jsonb(item) ORDER BY item.property_id),'[]'::jsonb) INTO v_items FROM (
                SELECT property_id,name,timezone_name AS timezone FROM app.property_configuration
                WHERE property_id=ANY(p_properties) AND (p_after IS NULL OR property_id>p_after)
                ORDER BY property_id LIMIT p_limit+1) item;
            RETURN jsonb_build_object('items',v_items);
        END $$;

        CREATE FUNCTION app.lease_enforcement_resolve(p_actor uuid,p_properties uuid[],p_kind text,p_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE v_property uuid; v_lease uuid;
        BEGIN
            PERFORM app.lease_enforcement_active_human(p_actor);
            IF p_kind='LEASE' THEN
                SELECT u.property_id,l.id INTO v_property,v_lease FROM app.leases l
                    JOIN app.units u ON u.id=l.unit_id WHERE l.id=p_id AND u.property_id=ANY(p_properties);
            ELSIF p_kind='CASE' THEN
                SELECT u.property_id,l.id INTO v_property,v_lease FROM app.rent_nonpayment_cases c
                    JOIN app.leases l ON l.id=c.lease_id JOIN app.units u ON u.id=l.unit_id
                    WHERE c.id=p_id AND u.property_id=ANY(p_properties);
            ELSE RAISE EXCEPTION 'Enforcement resolver kind is invalid' USING ERRCODE='P5402'; END IF;
            IF v_lease IS NULL THEN RAISE EXCEPTION 'Lease enforcement resource not found' USING ERRCODE='P5401'; END IF;
            RETURN jsonb_build_object('property_id',v_property,'lease_id',v_lease);
        END $$;

        CREATE FUNCTION app.rent_nonpayment_source_context(p_line uuid,p_as_of timestamptz)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
            SELECT jsonb_build_object('rent_invoice_line_id',line.id,'invoice_id',i.id,'invoice_number',i.invoice_number,
                'property_id',u.property_id,'lease_id',l.id,'customer_id',i.customer_id,'due_date',i.due_date,
                'case_id',c.id,'assessment',CASE WHEN c.id IS NOT NULL
                    THEN app.rent_nonpayment_case_snapshot(c.id,p_as_of)->'assessment'
                    ELSE jsonb_build_object('as_of',p_as_of,'timezone','Asia/Phnom_Penh',
                        'business_date',timezone('Asia/Phnom_Penh',p_as_of)::date,
                        'days_overdue',greatest(0,timezone('Asia/Phnom_Penh',p_as_of)::date-i.due_date),
                        'invoice_status',i.status,'source_applicable',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of,
                        'remaining_rent',jsonb_build_object('currency','USD','minor_units',balance.amount),
                        'twenty_day_warning_eligible',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                            AND app.rent_nonpayment_milestone_eligible('TWENTY_DAY_WARNING',i.due_date,p_as_of,balance.amount,false),
                        'thirty_day_default_eligible',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                            AND app.rent_nonpayment_milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',i.due_date,p_as_of,balance.amount,false),
                        'cure_eligible',false,'warning_recorded',false,'serious_default_recorded',false) END)
            FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
            JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
            LEFT JOIN app.rent_nonpayment_cases c ON c.rent_invoice_line_id=line.id
            CROSS JOIN LATERAL (SELECT CASE WHEN i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                THEN app.invoice_line_outstanding_at(line.id,p_as_of) ELSE 0 END AS amount) balance
            WHERE line.id=p_line AND line.category='RENT' AND line.source_lease_id=l.id
        $$;

        CREATE FUNCTION app.rent_nonpayment_alert_page(p_property uuid,p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
        DECLARE v_items jsonb;
        BEGIN
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_after='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Nonpayment alert page is invalid' USING ERRCODE='P5402'; END IF;
            SELECT COALESCE(jsonb_agg(item.context ORDER BY item.id),'[]'::jsonb) INTO v_items FROM (
                SELECT line.id,app.rent_nonpayment_source_context(line.id,statement_timestamp()) AS context
                FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
                JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
                WHERE u.property_id=p_property AND line.category='RENT' AND line.source_lease_id=l.id
                    AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
                    AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-i.due_date>=20
                    AND app.invoice_line_outstanding_at(line.id,statement_timestamp())>0
                    AND (p_after IS NULL OR line.id>p_after) ORDER BY line.id LIMIT p_limit+1
            ) item;
            RETURN jsonb_build_object('items',CASE WHEN jsonb_array_length(v_items)>p_limit THEN v_items-p_limit ELSE v_items END,
                'next_cursor',CASE WHEN jsonb_array_length(v_items)>p_limit THEN v_items->(p_limit-1)->>'rent_invoice_line_id' END,
                'as_of',statement_timestamp(),'business_date',timezone('Asia/Phnom_Penh',statement_timestamp())::date,'timezone','Asia/Phnom_Penh');
        END $$;

        CREATE FUNCTION app.lease_enforcement_context(p_actor uuid,p_property uuid,p_kind text,p_lease uuid,
            p_case uuid,p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
        DECLARE v_items jsonb; v_snapshot jsonb; v_sequence integer;
        BEGIN
            PERFORM app.lease_enforcement_active_human(p_actor);
            IF NOT EXISTS(SELECT 1 FROM app.properties WHERE id=p_property)
            THEN RAISE EXCEPTION 'Enforcement Property not found' USING ERRCODE='P5401'; END IF;
            IF p_kind IS NULL OR p_kind NOT IN ('LEASES','SOURCES','ACTION_CASES','EVENT_CONTEXT','WARNING_CONTEXT','ALERTS')
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_after='00000000-0000-0000-0000-000000000000'
                OR (p_kind IN ('LEASES','ALERTS') AND (p_lease IS NOT NULL OR p_case IS NOT NULL))
                OR (p_kind NOT IN ('LEASES','ALERTS') AND p_lease IS NULL)
                OR ((p_kind='EVENT_CONTEXT') IS DISTINCT FROM (p_case IS NOT NULL))
            THEN RAISE EXCEPTION 'Enforcement context is invalid' USING ERRCODE='P5402'; END IF;
            IF p_lease IS NOT NULL THEN PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor); END IF;
            IF p_kind='ALERTS' THEN RETURN app.rent_nonpayment_alert_page(p_property,p_limit,p_after);
            ELSIF p_kind='WARNING_CONTEXT' THEN
                SELECT max(warning_sequence)+1 INTO v_sequence FROM app.lease_violation_warnings WHERE lease_id=p_lease;
                RETURN jsonb_build_object('property_id',p_property,'lease_id',p_lease,
                    'suggested_sequence',CASE WHEN v_sequence>32767 THEN NULL ELSE COALESCE(v_sequence,1) END,
                    'business_date',timezone('Asia/Phnom_Penh',statement_timestamp())::date);
            ELSIF p_kind='EVENT_CONTEXT' THEN
                SELECT app.rent_nonpayment_case_snapshot(c.id,statement_timestamp()) INTO v_snapshot
                    FROM app.rent_nonpayment_cases c WHERE c.id=p_case AND c.lease_id=p_lease;
                IF v_snapshot IS NULL THEN RAISE EXCEPTION 'Enforcement case not found' USING ERRCODE='P5401'; END IF;
                RETURN v_snapshot-ARRAY['opened_at','opened_by','event_count'];
            ELSIF p_kind='LEASES' THEN
                SELECT COALESCE(jsonb_agg(to_jsonb(item) ORDER BY item.id),'[]'::jsonb) INTO v_items FROM (
                    SELECT l.id,l.start_date,l.end_date,l.status,u.unit_number,p_property AS property_id
                    FROM app.leases l JOIN app.units u ON u.id=l.unit_id
                    WHERE u.property_id=p_property AND (p_after IS NULL OR l.id>p_after)
                    ORDER BY l.id LIMIT p_limit+1) item;
            ELSIF p_kind='SOURCES' THEN
                SELECT COALESCE(jsonb_agg(item.context ORDER BY item.id),'[]'::jsonb) INTO v_items FROM (
                    SELECT line.id,app.rent_nonpayment_source_context(line.id,statement_timestamp()) AS context
                    FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
                    WHERE i.lease_id=p_lease AND line.source_lease_id=p_lease AND line.category='RENT'
                        AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
                        AND NOT EXISTS(SELECT 1 FROM app.rent_nonpayment_cases c WHERE c.rent_invoice_line_id=line.id)
                        AND (p_after IS NULL OR line.id>p_after) ORDER BY line.id LIMIT p_limit+1) item;
            ELSE
                SELECT COALESCE(jsonb_agg(item.context ORDER BY item.id),'[]'::jsonb) INTO v_items FROM (
                    SELECT c.id,app.rent_nonpayment_case_snapshot(c.id,statement_timestamp())-ARRAY['opened_at','opened_by','event_count'] AS context
                    FROM app.rent_nonpayment_cases c WHERE c.lease_id=p_lease AND (p_after IS NULL OR c.id>p_after)
                    ORDER BY c.id LIMIT p_limit+1) item;
            END IF;
            RETURN jsonb_build_object('items',CASE WHEN jsonb_array_length(v_items)>p_limit THEN v_items-p_limit ELSE v_items END,
                'next_cursor',CASE WHEN jsonb_array_length(v_items)>p_limit
                    THEN v_items->(p_limit-1)->>CASE WHEN p_kind='SOURCES' THEN 'rent_invoice_line_id' ELSE 'id' END END);
        END $$;

        CREATE TABLE app.rent_nonpayment_evaluation_principals (
            actor_id uuid PRIMARY KEY REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            database_role name NOT NULL UNIQUE,
            capability text NOT NULL CHECK(capability='rent_nonpayment.evaluate'),
            lifecycle_state text NOT NULL CHECK(lifecycle_state IN ('active','disabled')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK(isfinite(created_at)),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            disabled_at timestamptz CHECK(isfinite(disabled_at)),
            disabled_by uuid REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            CHECK((lifecycle_state='active' AND disabled_at IS NULL AND disabled_by IS NULL)
                OR (lifecycle_state='disabled' AND disabled_at>=created_at AND disabled_at IS NOT NULL AND disabled_by IS NOT NULL))
        );
        CREATE FUNCTION app.protect_nonpayment_evaluation_principal()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                PERFORM app.lease_enforcement_active_human(NEW.created_by);
                IF NEW.lifecycle_state<>'active' OR NEW.disabled_at IS NOT NULL OR NEW.disabled_by IS NOT NULL
                    OR NEW.created_at>clock_timestamp()
                    OR NOT app.nonpayment_evaluation_login_is_restricted(NEW.database_role)
                THEN RAISE EXCEPTION 'Read-only evaluation principal registration is invalid' USING ERRCODE='23514'; END IF;
                INSERT INTO app.actor_identities(actor_id,identity_kind) VALUES(NEW.actor_id,'SERVICE');
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' OR OLD.lifecycle_state<>'active'
                OR to_jsonb(NEW)-ARRAY['lifecycle_state','disabled_at','disabled_by'] IS DISTINCT FROM to_jsonb(OLD)-ARRAY['lifecycle_state','disabled_at','disabled_by']
                OR NEW.lifecycle_state<>'disabled' OR NEW.disabled_at IS NULL OR NEW.disabled_by IS NULL
                OR NEW.disabled_at>clock_timestamp()
            THEN RAISE EXCEPTION 'Evaluation principal history is protected' USING ERRCODE='55000'; END IF;
            PERFORM app.lease_enforcement_active_human(NEW.disabled_by);
            RETURN NEW;
        END $$;
        CREATE TRIGGER nonpayment_evaluation_principal_history BEFORE INSERT OR UPDATE OR DELETE
            ON app.rent_nonpayment_evaluation_principals FOR EACH ROW EXECUTE FUNCTION app.protect_nonpayment_evaluation_principal();
        CREATE TRIGGER nonpayment_evaluation_principal_no_truncate BEFORE TRUNCATE
            ON app.rent_nonpayment_evaluation_principals FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();

        CREATE FUNCTION app.scheduled_rent_nonpayment_evaluation(p_actor uuid,p_property uuid,p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
        BEGIN
            IF current_setting('transaction_read_only')<>'on' OR NOT EXISTS(
                SELECT 1 FROM app.rent_nonpayment_evaluation_principals p JOIN app.actor_identities i ON i.actor_id=p.actor_id
                WHERE p.actor_id=p_actor AND p.property_id=p_property AND p.database_role=session_user
                    AND app.nonpayment_evaluation_login_is_restricted(p.database_role)
                    AND p.capability='rent_nonpayment.evaluate' AND p.lifecycle_state='active' AND i.identity_kind='SERVICE')
            THEN RAISE EXCEPTION 'Read-only nonpayment evaluation is not authorized' USING ERRCODE='P5406'; END IF;
            RETURN app.rent_nonpayment_alert_page(p_property,p_limit,p_after);
        END $$;
        CREATE FUNCTION app.nonpayment_evaluation_login_is_restricted(p_role name)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
            SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname=p_role AND r.rolcanlogin
                AND NOT r.rolsuper AND NOT r.rolcreatedb AND NOT r.rolcreaterole AND NOT r.rolreplication AND NOT r.rolbypassrls
                AND r.rolname NOT IN ('prm_admin','prm_migrator','prm_runtime','prm_financial','prm_bootstrap','prm_backup','prm_restore','prm_human_admin')
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)
                -- Owners retain control and grant options after ordinary ACL revocation.
                -- Include target-database dependencies outside app (for example btree_gist).
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_database b ON b.oid=d.dbid
                    WHERE b.datname=current_database() AND d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass
                        AND d.refobjid=r.oid AND d.deptype='o')
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname=current_database() AND datdba=r.oid
                    UNION ALL SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=r.oid
                    UNION ALL SELECT 1 FROM pg_catalog.pg_class WHERE relowner=r.oid
                    UNION ALL SELECT 1 FROM pg_catalog.pg_proc WHERE proowner=r.oid
                    UNION ALL SELECT 1 FROM pg_catalog.pg_type WHERE typowner=r.oid
                    UNION ALL SELECT 1 FROM pg_catalog.pg_extension WHERE extowner=r.oid)
                AND NOT has_schema_privilege(r.oid,'app','CREATE')
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='app' AND c.relkind IN ('r','p','v','m','f')
                        AND (has_table_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                            OR has_any_column_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='app' AND c.relkind='S' AND has_sequence_privilege(r.oid,c.oid,'SELECT,USAGE,UPDATE'))
                AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc f JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace
                    WHERE n.nspname='app' AND f.prosecdef
                        AND f.oid<>'app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid)'::pg_catalog.regprocedure
                        AND has_function_privilege(r.oid,f.oid,'EXECUTE')))
        $$;
        REVOKE ALL ON TABLE app.rent_nonpayment_evaluation_principals FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    """)
    for signature in (
        "app.lease_enforcement_active_human(uuid)",
        "app.lease_enforcement_workspaces(uuid,uuid[],integer,uuid)",
        "app.lease_enforcement_resolve(uuid,uuid[],text,uuid)",
        "app.rent_nonpayment_source_context(uuid,timestamptz)",
        "app.rent_nonpayment_alert_page(uuid,integer,uuid)",
        "app.lease_enforcement_context(uuid,uuid,text,uuid,uuid,integer,uuid)",
        "app.protect_nonpayment_evaluation_principal()",
        "app.nonpayment_evaluation_login_is_restricted(name)",
        "app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_enforcement_workspaces(uuid,uuid[],integer,uuid) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_enforcement_resolve(uuid,uuid[],text,uuid) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_enforcement_context(uuid,uuid,text,uuid,uuid,integer,uuid) TO prm_runtime"
    )
    # Evaluation logins are separately provisioned with only CONNECT, app USAGE and
    # EXECUTE on scheduled_rent_nonpayment_evaluation. No shared runtime/financial grant.


def downgrade() -> None:
    raise RuntimeError("Lease enforcement and principal history is forward-only")
