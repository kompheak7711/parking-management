"""Joint Inspection at move-in and move-out (DL-201, DL-243).

The owner's rules of 7 Nov 2026 (DL-201 C), the plan and the seven answers the owner approved on
16 Nov 2026 ("Yes to all advice"), and the screen pictures the owner approved the same day:

1. ``joint_inspections``: one record per Lease and kind (MOVE_IN or MOVE_OUT), numbered
   JIyy000n in ``number_rules``. It starts as a Draft that saves as staff go; it is Done when the
   tenant and then the staff member have signed on the tablet. A Done record never changes; a
   Manager or the Owner fixes a mistake with a new inspection that replaces it, with a reason,
   and the old one stays as Replaced (DL-115 D).
2. ``joint_inspection_lines``: what the form lists, copied when the inspection starts, so a later
   change to the Unit never changes the record. Each place of the Unit comes from its Unit
   features and their count (Bedroom 1, Bedroom 2); a place is Good or Broken (answer 7). The
   built-in features (Built-in type) are their own lines, Good or Broken. Each Unit inventory
   item is a line under its place, or under "Other items" when it has none: Good, Broken or
   Missing. Broken or Missing needs a note. A move-out line keeps the move-in result beside it.
3. Keys given or returned (door keys, key cards, mailbox keys, other keys) and the electricity
   and water meter numbers, each with an optional photo. The numbers stay on the inspection only
   (answer 2): the read shows the reading of that day in Utilities beside it, so the screen can
   warn; no Utility Reading or Invoice changes.
4. ``joint_inspection_files``: up to 5 photos per line, one photo per meter and the two
   signatures (answer 1). The files are on the office computer; the database keeps the
   fingerprint. Any change after a signature takes both signatures off.
5. When it is Done (answer 3): each Broken or Missing line makes a Unit Problem report (source
   JOINT_INSPECTION) with the Lease and tenant, except a move-out line that is the same as at
   move-in (that problem was reported at move-in) and a line a replaced inspection already
   reported the same way.
6. Move-out damage (answer 4): a move-out line that is worse than at move-in may be ticked
   "Tenant caused" (and "Caused by a pet"). Done makes the move-out inspection of V1 for the
   Lease, with one damage finding per ticked line, so the Damage charge and the Final Settlement
   work as before; a later move-out inspection replaces the one in force. Nothing is charged by
   the inspection itself (DL-115).
7. Rights: ``joint_inspections.record`` (Staff, Manager, Owner) and ``joint_inspections.replace``
   (Manager, Owner). Reading needs ``units.read``, as the Inspections page.

No hard stop anywhere else (answer 5). Technical choices by Claude under the owner's 2026-10-23
22:30 rule. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270805_423"
down_revision: str | None = "20270804_422"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-2-joint-inspections"
CAPABILITIES = (
    ("joint_inspections.record", "Do move-in and move-out Joint Inspections"),
    ("joint_inspections.replace", "Replace a finished Joint Inspection with a new one"),
)
PERMISSIONS = (
    (
        "JOINT_INSPECTIONS_RECORD",
        "Do Joint Inspections",
        "ធ្វើការត្រួតពិនិត្យរួម",
        "joint_inspections.record",
    ),
    (
        "JOINT_INSPECTIONS_REPLACE",
        "Replace a Joint Inspection",
        "ជំនួសការត្រួតពិនិត្យរួម",
        "joint_inspections.replace",
    ),
)
EVERY = ("joint_inspections.record", "joint_inspections.replace")
STAFF = ("joint_inspections.record",)
REASON = "Owner 2026-11-16: Joint Inspection rights (Staff do them; a Manager replaces one)"
SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'visit_requests.read', 'visit_requests.work']::text[]"
STAFF_AFTER = (
    "'visit_requests.read', 'visit_requests.work', 'joint_inspections.record']::text[]"
)

TABLES = r"""
    -- 1. The inspection. What it records changes only while it is a Draft, through the
    -- functions below; a Done record is locked (only Done -> Replaced).
    CREATE TABLE app.joint_inspections (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        lease_id uuid NOT NULL REFERENCES app.leases (id) ON DELETE RESTRICT,
        unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
        customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
        inspection_number text NOT NULL UNIQUE CHECK (inspection_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        kind text NOT NULL CHECK (kind IN ('MOVE_IN', 'MOVE_OUT')),
        status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'DONE', 'REPLACED')),
        inspection_date date NOT NULL CHECK (isfinite(inspection_date)),
        tenant_name text NOT NULL CHECK (tenant_name = btrim(tenant_name)
            AND length(tenant_name) BETWEEN 1 AND 300),
        move_in_id uuid REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        replaces_id uuid UNIQUE REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        replace_reason text CHECK (replace_reason = btrim(replace_reason)
            AND length(replace_reason) BETWEEN 1 AND 500),
        door_keys smallint CHECK (door_keys BETWEEN 0 AND 99),
        key_cards smallint CHECK (key_cards BETWEEN 0 AND 99),
        mailbox_keys smallint CHECK (mailbox_keys BETWEEN 0 AND 99),
        other_keys smallint CHECK (other_keys BETWEEN 0 AND 99),
        other_keys_note text CHECK (other_keys_note = btrim(other_keys_note)
            AND length(other_keys_note) BETWEEN 1 AND 200),
        done_at timestamptz,
        done_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        replaced_at timestamptz,
        replaced_by_id uuid REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        move_out_inspection_id uuid UNIQUE REFERENCES app.move_out_inspections (id)
            ON DELETE RESTRICT,
        version integer NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT joint_inspections_replace_pair CHECK ((replaces_id IS NULL) = (replace_reason IS NULL)
            AND replaces_id IS DISTINCT FROM id),
        CONSTRAINT joint_inspections_done_shape CHECK (
            (status = 'DRAFT' AND done_at IS NULL AND done_by IS NULL AND replaced_at IS NULL
                AND replaced_by_id IS NULL)
            OR (status = 'DONE' AND done_at IS NOT NULL AND done_by IS NOT NULL
                AND replaced_at IS NULL AND replaced_by_id IS NULL)
            OR (status = 'REPLACED' AND done_at IS NOT NULL AND done_by IS NOT NULL
                AND replaced_at IS NOT NULL AND replaced_by_id IS NOT NULL)),
        CONSTRAINT joint_inspections_move_in_shape CHECK (kind = 'MOVE_OUT'
            OR (move_in_id IS NULL AND move_out_inspection_id IS NULL)),
        CONSTRAINT joint_inspections_other_keys_note CHECK (other_keys_note IS NULL
            OR other_keys > 0)
    );
    CREATE UNIQUE INDEX joint_inspections_one_draft ON app.joint_inspections (lease_id, kind)
        WHERE status = 'DRAFT';
    CREATE UNIQUE INDEX joint_inspections_one_done ON app.joint_inspections (lease_id, kind)
        WHERE status = 'DONE';
    CREATE INDEX joint_inspections_property_idx ON app.joint_inspections (property_id, created_at DESC);
    CREATE INDEX joint_inspections_unit_idx ON app.joint_inspections (unit_id, created_at DESC);
    COMMENT ON TABLE app.joint_inspections IS
        'DL-201 and DL-243: the move-in and move-out Joint Inspection of a Lease, the only record of condition.';

    -- 2. The lines, copied from the Unit when the inspection starts.
    CREATE TABLE app.joint_inspection_lines (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        inspection_id uuid NOT NULL REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 500),
        line_kind text NOT NULL CHECK (line_kind IN ('PLACE', 'BUILT_IN', 'ITEM')),
        place_item_id uuid REFERENCES app.unit_setup_items (id) ON DELETE RESTRICT,
        place_number smallint CHECK (place_number BETWEEN 1 AND 9),
        group_en text NOT NULL CHECK (group_en = btrim(group_en) AND length(group_en) BETWEEN 1 AND 120),
        group_km text CHECK (group_km = btrim(group_km) AND length(group_km) BETWEEN 1 AND 120),
        item_name text CHECK (item_name = btrim(item_name) AND length(item_name) BETWEEN 1 AND 120),
        item_name_km text CHECK (item_name_km = btrim(item_name_km)
            AND length(item_name_km) BETWEEN 1 AND 120),
        item_type_name text CHECK (item_type_name = btrim(item_type_name)
            AND length(item_type_name) BETWEEN 1 AND 120),
        item_type_name_km text CHECK (item_type_name_km = btrim(item_type_name_km)
            AND length(item_type_name_km) BETWEEN 1 AND 120),
        quantity integer CHECK (quantity BETWEEN 1 AND 999),
        result text CHECK (result IN ('GOOD', 'BROKEN', 'MISSING')),
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
        tenant_caused boolean NOT NULL DEFAULT false,
        pet_caused boolean NOT NULL DEFAULT false,
        move_in_result text CHECK (move_in_result IN ('GOOD', 'BROKEN', 'MISSING')),
        move_in_note text CHECK (move_in_note = btrim(move_in_note)
            AND length(move_in_note) BETWEEN 1 AND 500),
        problem_report_id uuid REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        finding_id uuid UNIQUE REFERENCES app.inspection_damage_findings (id) ON DELETE RESTRICT,
        CONSTRAINT joint_inspection_lines_ordinal UNIQUE (inspection_id, ordinal),
        CONSTRAINT joint_inspection_lines_place_pair CHECK ((place_item_id IS NULL) = (place_number IS NULL)),
        CONSTRAINT joint_inspection_lines_kind_shape CHECK (
            (line_kind = 'PLACE' AND place_item_id IS NOT NULL AND item_name IS NULL AND quantity IS NULL)
            OR (line_kind = 'BUILT_IN' AND place_item_id IS NULL AND item_name IS NOT NULL
                AND quantity IS NULL)
            OR (line_kind = 'ITEM' AND item_name IS NOT NULL AND item_type_name IS NOT NULL
                AND quantity IS NOT NULL)),
        CONSTRAINT joint_inspection_lines_missing_item CHECK (result IS DISTINCT FROM 'MISSING'
            OR line_kind = 'ITEM'),
        CONSTRAINT joint_inspection_lines_ticks CHECK ((NOT tenant_caused OR result IN ('BROKEN', 'MISSING'))
            AND (NOT pet_caused OR tenant_caused))
    );
    CREATE INDEX joint_inspection_lines_report_idx ON app.joint_inspection_lines (problem_report_id)
        WHERE problem_report_id IS NOT NULL;

    -- 3. The meters of the Unit when the inspection starts, with the number staff read.
    CREATE TABLE app.joint_inspection_meters (
        inspection_id uuid NOT NULL REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        utility_type text NOT NULL CHECK (utility_type IN ('ELECTRICITY', 'WATER')),
        meter_id uuid NOT NULL REFERENCES app.utility_meters (id) ON DELETE RESTRICT,
        serial_number text NOT NULL,
        measurement_unit_code text NOT NULL,
        reading numeric(20, 6) CHECK (reading >= 0 AND reading < 'Infinity'::numeric),
        PRIMARY KEY (inspection_id, utility_type)
    );

    -- 4. Photos, meter photos and the two signatures. A file is taken off (removed_at) only
    -- while the inspection is a Draft; nothing is deleted.
    CREATE TABLE app.joint_inspection_files (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        inspection_id uuid NOT NULL REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        line_id uuid REFERENCES app.joint_inspection_lines (id) ON DELETE RESTRICT,
        role text NOT NULL CHECK (role IN ('PHOTO', 'ELECTRICITY', 'WATER', 'TENANT_SIGNATURE',
            'STAFF_SIGNATURE')),
        media_type text NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'image/webp')),
        byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 10485760),
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        storage_key text NOT NULL CHECK (storage_key
            ~ '^inspections/[0-9a-f-]{36}/[0-9a-f-]{36}\.(jpg|png|webp)$'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        removed_at timestamptz,
        removed_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT joint_inspection_files_line CHECK ((role = 'PHOTO') = (line_id IS NOT NULL)),
        CONSTRAINT joint_inspection_files_removed CHECK ((removed_at IS NULL) = (removed_by IS NULL))
    );
    CREATE INDEX joint_inspection_files_inspection_idx ON app.joint_inspection_files (inspection_id)
        WHERE removed_at IS NULL;

    -- Locks: a Done or Replaced inspection never changes, except Done -> Replaced; its lines,
    -- meters and files never change. Nothing is deleted or emptied.
    CREATE FUNCTION app.protect_joint_inspection() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF TG_OP <> 'UPDATE' THEN
            RAISE EXCEPTION 'Joint Inspections are never deleted' USING ERRCODE = '55000';
        END IF;
        IF OLD.status = 'DRAFT' THEN
            RETURN NEW;
        END IF;
        IF OLD.status = 'DONE' AND NEW.status = 'REPLACED'
            AND (to_jsonb(NEW) - ARRAY['status', 'replaced_at', 'replaced_by_id', 'version'])
                = (to_jsonb(OLD) - ARRAY['status', 'replaced_at', 'replaced_by_id', 'version']) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'A finished Joint Inspection never changes; replace it with a new one'
            USING ERRCODE = '55000';
    END $$;
    CREATE TRIGGER joint_inspections_protect BEFORE UPDATE OR DELETE ON app.joint_inspections
        FOR EACH ROW EXECUTE FUNCTION app.protect_joint_inspection();

    CREATE FUNCTION app.protect_joint_inspection_part() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_status text;
    BEGIN
        IF TG_OP <> 'UPDATE' THEN
            RAISE EXCEPTION 'Joint Inspection records are never deleted' USING ERRCODE = '55000';
        END IF;
        IF NEW.inspection_id IS DISTINCT FROM OLD.inspection_id THEN
            RAISE EXCEPTION 'A Joint Inspection record stays with its inspection' USING ERRCODE = '55000';
        END IF;
        SELECT inspection.status INTO v_status FROM app.joint_inspections AS inspection
        WHERE inspection.id = OLD.inspection_id;
        IF v_status IS DISTINCT FROM 'DRAFT' THEN
            RAISE EXCEPTION 'A finished Joint Inspection never changes; replace it with a new one'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER joint_inspection_lines_protect BEFORE UPDATE OR DELETE ON app.joint_inspection_lines
        FOR EACH ROW EXECUTE FUNCTION app.protect_joint_inspection_part();
    CREATE TRIGGER joint_inspection_meters_protect BEFORE UPDATE OR DELETE ON app.joint_inspection_meters
        FOR EACH ROW EXECUTE FUNCTION app.protect_joint_inspection_part();
    CREATE TRIGGER joint_inspection_files_protect BEFORE UPDATE OR DELETE ON app.joint_inspection_files
        FOR EACH ROW EXECUTE FUNCTION app.protect_joint_inspection_part();

    CREATE FUNCTION app.reject_joint_inspection_truncate() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Joint Inspections are never emptied' USING ERRCODE = '55000';
    END $$;
    CREATE TRIGGER joint_inspections_no_truncate BEFORE TRUNCATE ON app.joint_inspections
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_joint_inspection_truncate();
    CREATE TRIGGER joint_inspection_lines_no_truncate BEFORE TRUNCATE ON app.joint_inspection_lines
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_joint_inspection_truncate();
    CREATE TRIGGER joint_inspection_meters_no_truncate BEFORE TRUNCATE ON app.joint_inspection_meters
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_joint_inspection_truncate();
    CREATE TRIGGER joint_inspection_files_no_truncate BEFORE TRUNCATE ON app.joint_inspection_files
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_joint_inspection_truncate();

    REVOKE ALL ON TABLE app.joint_inspections, app.joint_inspection_lines,
        app.joint_inspection_meters, app.joint_inspection_files FROM PUBLIC;
    GRANT SELECT ON TABLE app.joint_inspections, app.joint_inspection_lines,
        app.joint_inspection_meters, app.joint_inspection_files TO prm_runtime;

    -- A Problem report made by a Joint Inspection says so (relaxing the list of sources).
    ALTER TABLE app.problem_reports DROP CONSTRAINT problem_reports_source_check;
    ALTER TABLE app.problem_reports ADD CONSTRAINT problem_reports_source_check CHECK (source IN (
        'PHONE', 'WALKIN', 'SEEN', 'INSPECTION', 'TENANT_BOT', 'STAFF_BOT', 'ROOM_CHECK',
        'JOINT_INSPECTION'));

    -- Numbers JIyy000n, like the other documents (the letters can be changed in Settings).
    INSERT INTO app.number_rules (document_type, year, last_number, format)
    SELECT 'JOINT_INSPECTION', rule.year, 0, 'JIyy000n'
    FROM app.number_rules AS rule WHERE rule.document_type = 'UNIT_PROBLEM'
    ON CONFLICT (document_type, year) DO NOTHING;
"""

FUNCTIONS = r"""
    -- How bad a result is: Good < Broken < Missing (a line with no move-in record counts Good).
    CREATE FUNCTION app.joint_inspection_rank(p_result text) RETURNS integer
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE p_result WHEN 'BROKEN' THEN 1 WHEN 'MISSING' THEN 2 ELSE 0 END
    $$;

    -- The line's name as the Problem report and the damage finding say it.
    CREATE FUNCTION app.joint_inspection_line_text(p_line app.joint_inspection_lines)
    RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE p_line.line_kind
                   WHEN 'PLACE' THEN p_line.group_en
                   WHEN 'BUILT_IN' THEN p_line.item_name
                   ELSE p_line.group_en || ', ' || p_line.item_name
               END
            || ': ' || CASE p_line.result WHEN 'MISSING' THEN 'missing' ELSE 'broken' END
            || COALESCE('. ' || p_line.note, '')
    $$;

    -- An inspection of this Property, locked for a change. A wrong Property reads as not found.
    CREATE FUNCTION app.joint_inspection_for_change(p_property uuid, p_id uuid, p_version integer)
    RETURNS app.joint_inspections LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_row app.joint_inspections%ROWTYPE;
    BEGIN
        SELECT inspection.* INTO v_row FROM app.joint_inspections AS inspection
        WHERE inspection.id = p_id AND inspection.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Joint Inspection does not exist' USING ERRCODE = '22023';
        END IF;
        IF v_row.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'This Joint Inspection is finished and cannot change' USING ERRCODE = '55000';
        END IF;
        IF p_version IS NOT NULL AND v_row.version <> p_version THEN
            RAISE EXCEPTION 'The Joint Inspection changed since it was read. Reload it.'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_row;
    END $$;

    -- The right to change a Draft: a replacement is the Manager's.
    CREATE FUNCTION app.joint_inspection_require(p_actor uuid, p_property uuid,
        p_row app.joint_inspections) RETURNS date
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    BEGIN
        RETURN app.require_product_right(p_actor,
            CASE WHEN p_row.replaces_id IS NULL THEN 'joint_inspections.record'
                 ELSE 'joint_inspections.replace' END, p_property);
    END $$;

    -- Any change after a signature takes both signatures off: the tenant signs what they see.
    CREATE FUNCTION app.joint_inspection_unsign(p_id uuid, p_actor uuid) RETURNS void
    LANGUAGE sql SET search_path = pg_catalog AS $$
        UPDATE app.joint_inspection_files AS file
        SET removed_at = clock_timestamp(), removed_by = p_actor
        WHERE file.inspection_id = p_id AND file.removed_at IS NULL
          AND file.role IN ('TENANT_SIGNATURE', 'STAFF_SIGNATURE')
    $$;

    -- 1. Start a Draft from the Lease's Unit as it is today.
    CREATE FUNCTION app.joint_inspection_start(p_property uuid, p_lease uuid, p_kind text,
        p_replaces uuid, p_reason text, p_actor uuid, p_correlation uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_id uuid := gen_random_uuid();
        v_lease app.leases%ROWTYPE;
        v_unit app.units%ROWTYPE;
        v_old app.joint_inspections%ROWTYPE;
        v_move_in uuid;
        v_record uuid;
        v_name text;
        v_reason text := NULLIF(btrim(p_reason), '');
        v_number text;
        v_ordinal integer := 0;
        v_place record;
        v_item record;
        v_n integer;
    BEGIN
        IF p_kind IS NULL OR p_kind NOT IN ('MOVE_IN', 'MOVE_OUT') THEN
            RAISE EXCEPTION 'Choose move-in or move-out' USING ERRCODE = '22023';
        END IF;
        v_day := app.require_product_right(p_actor, CASE WHEN p_replaces IS NULL
            THEN 'joint_inspections.record' ELSE 'joint_inspections.replace' END, p_property);
        SELECT lease.* INTO v_lease FROM app.leases AS lease
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE lease.id = p_lease AND unit.property_id = p_property
        FOR UPDATE OF lease;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Lease does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_kind = 'MOVE_IN' AND v_lease.status <> 'SIGNED'
            OR p_kind = 'MOVE_OUT' AND v_lease.status NOT IN ('SIGNED', 'TERMINATED') THEN
            RAISE EXCEPTION 'A Joint Inspection needs a signed Lease' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.joint_inspections AS draft
                WHERE draft.lease_id = p_lease AND draft.kind = p_kind AND draft.status = 'DRAFT') THEN
            RAISE EXCEPTION 'This inspection is already started. Open it and go on.'
                USING ERRCODE = '55000';
        END IF;
        IF p_replaces IS NULL THEN
            IF v_reason IS NOT NULL THEN
                RAISE EXCEPTION 'A reason is only for a replacement' USING ERRCODE = '22023';
            END IF;
            IF EXISTS (SELECT 1 FROM app.joint_inspections AS done
                    WHERE done.lease_id = p_lease AND done.kind = p_kind AND done.status = 'DONE') THEN
                RAISE EXCEPTION 'This inspection is done. A Manager can replace it.'
                    USING ERRCODE = '55000';
            END IF;
        ELSE
            SELECT old.* INTO v_old FROM app.joint_inspections AS old
            WHERE old.id = p_replaces AND old.property_id = p_property FOR UPDATE;
            IF NOT FOUND OR v_old.lease_id <> p_lease OR v_old.kind <> p_kind THEN
                RAISE EXCEPTION 'the Joint Inspection to replace does not exist' USING ERRCODE = '22023';
            END IF;
            IF v_old.status <> 'DONE' THEN
                RAISE EXCEPTION 'Only a finished Joint Inspection can be replaced' USING ERRCODE = '55000';
            END IF;
            IF v_reason IS NULL OR length(v_reason) > 500 THEN
                RAISE EXCEPTION 'Say why it is replaced, at most 500 letters' USING ERRCODE = '22023';
            END IF;
        END IF;
        SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = v_lease.unit_id;
        SELECT btrim(customer.legal_name) INTO v_name FROM app.customers AS customer
        WHERE customer.id = v_lease.primary_tenant_id;
        IF p_kind = 'MOVE_OUT' THEN
            SELECT done.id INTO v_move_in FROM app.joint_inspections AS done
            WHERE done.lease_id = p_lease AND done.kind = 'MOVE_IN' AND done.status = 'DONE';
        END IF;
        v_number := app.take_document_number('JOINT_INSPECTION', date_part('year', v_day)::integer);
        INSERT INTO app.joint_inspections (id, property_id, lease_id, unit_id, customer_id,
            inspection_number, kind, inspection_date, tenant_name, move_in_id, replaces_id,
            replace_reason, created_by)
        VALUES (v_id, p_property, p_lease, v_unit.id, v_lease.primary_tenant_id, v_number, p_kind,
            v_day, left(COALESCE(v_name, 'Tenant'), 300), v_move_in, p_replaces, v_reason, p_actor);

        SELECT record.id INTO v_record FROM app.unit_inventory_records AS record
        WHERE record.unit_id = v_unit.id ORDER BY record.record_number DESC LIMIT 1;

        -- Places (every Unit feature that is not built in), each with its items.
        FOR v_place IN
            SELECT feature.item_id, feature.feature_count, item.name_en, item.name_km
            FROM app.unit_features AS feature
            JOIN app.unit_setup_items AS item ON item.id = feature.item_id
            JOIN app.unit_setup_items AS kind ON kind.id = item.feature_type_item_id
            WHERE feature.unit_id = v_unit.id AND kind.code <> 'BUILT_IN'
            ORDER BY kind.sort_order, item.sort_order, item.name_en
        LOOP
            FOR v_n IN 1 .. v_place.feature_count LOOP
                v_ordinal := v_ordinal + 1;
                INSERT INTO app.joint_inspection_lines (inspection_id, ordinal, line_kind,
                    place_item_id, place_number, group_en, group_km)
                VALUES (v_id, v_ordinal, 'PLACE', v_place.item_id, v_n,
                    left(v_place.name_en || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120),
                    left(v_place.name_km || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120));
                FOR v_item IN
                    SELECT line.item_name, line.quantity, kind.name_en AS type_en, kind.name_km AS type_km
                    FROM jsonb_to_recordset(COALESCE(app.unit_inventory_items_json(v_record), '[]'::jsonb))
                        AS line(item_type_item_id uuid, item_name text, where_item_id uuid,
                            where_number integer, quantity integer)
                    JOIN app.unit_setup_items AS kind ON kind.id = line.item_type_item_id
                    WHERE v_record IS NOT NULL AND line.where_item_id = v_place.item_id
                      AND COALESCE(line.where_number, 1) = v_n
                LOOP
                    v_ordinal := v_ordinal + 1;
                    INSERT INTO app.joint_inspection_lines (inspection_id, ordinal, line_kind,
                        place_item_id, place_number, group_en, group_km, item_name, item_type_name,
                        item_type_name_km, quantity)
                    VALUES (v_id, v_ordinal, 'ITEM', v_place.item_id, v_n,
                        left(v_place.name_en || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120),
                        left(v_place.name_km || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120),
                        left(btrim(v_item.item_name), 120), left(v_item.type_en, 120),
                        left(v_item.type_km, 120), least(greatest(v_item.quantity, 1), 999));
                END LOOP;
            END LOOP;
        END LOOP;

        -- Built-in features (a built-in wardrobe, a wall air conditioner).
        FOR v_place IN
            SELECT feature.item_id, feature.feature_count, item.name_en, item.name_km
            FROM app.unit_features AS feature
            JOIN app.unit_setup_items AS item ON item.id = feature.item_id
            JOIN app.unit_setup_items AS kind ON kind.id = item.feature_type_item_id
            WHERE feature.unit_id = v_unit.id AND kind.code = 'BUILT_IN'
            ORDER BY item.sort_order, item.name_en
        LOOP
            FOR v_n IN 1 .. v_place.feature_count LOOP
                v_ordinal := v_ordinal + 1;
                INSERT INTO app.joint_inspection_lines (inspection_id, ordinal, line_kind,
                    group_en, group_km, item_name, item_name_km)
                VALUES (v_id, v_ordinal, 'BUILT_IN', 'Built-in', 'ភ្ជាប់ជាប់',
                    left(v_place.name_en || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120),
                    left(v_place.name_km || CASE WHEN v_place.feature_count > 1 THEN ' ' || v_n ELSE '' END, 120));
            END LOOP;
        END LOOP;

        -- Items with no place (or a place the Unit no longer has).
        FOR v_item IN
            SELECT line.item_name, line.quantity, kind.name_en AS type_en, kind.name_km AS type_km
            FROM jsonb_to_recordset(COALESCE(app.unit_inventory_items_json(v_record), '[]'::jsonb))
                AS line(item_type_item_id uuid, item_name text, where_item_id uuid,
                    where_number integer, quantity integer)
            JOIN app.unit_setup_items AS kind ON kind.id = line.item_type_item_id
            WHERE v_record IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.unit_features AS feature
                JOIN app.unit_setup_items AS item ON item.id = feature.item_id
                JOIN app.unit_setup_items AS type ON type.id = item.feature_type_item_id
                WHERE feature.unit_id = v_unit.id AND feature.item_id = line.where_item_id
                  AND type.code <> 'BUILT_IN'
                  AND COALESCE(line.where_number, 1) <= feature.feature_count)
        LOOP
            v_ordinal := v_ordinal + 1;
            INSERT INTO app.joint_inspection_lines (inspection_id, ordinal, line_kind, group_en,
                group_km, item_name, item_type_name, item_type_name_km, quantity)
            VALUES (v_id, v_ordinal, 'ITEM', 'Other items', 'របស់ផ្សេងៗ',
                left(btrim(v_item.item_name), 120), left(v_item.type_en, 120),
                left(v_item.type_km, 120), least(greatest(v_item.quantity, 1), 999));
        END LOOP;

        -- The meters in use in the Unit today.
        INSERT INTO app.joint_inspection_meters (inspection_id, utility_type, meter_id,
            serial_number, measurement_unit_code)
        SELECT v_id, meter.utility_type, meter.id, meter.serial_number, meter.measurement_unit_code
        FROM app.utility_meters AS meter
        WHERE meter.unit_id = v_unit.id AND meter.deactivated_date IS NULL
          AND meter.installed_date <= v_day;

        -- A move-out shows the move-in result beside each line.
        IF v_move_in IS NOT NULL THEN
            UPDATE app.joint_inspection_lines AS line
            SET move_in_result = earlier.result, move_in_note = earlier.note
            FROM app.joint_inspection_lines AS earlier
            WHERE line.inspection_id = v_id AND earlier.inspection_id = v_move_in
              AND earlier.line_kind = line.line_kind
              AND earlier.group_en = line.group_en
              AND lower(COALESCE(earlier.item_name, '')) = lower(COALESCE(line.item_name, ''))
              AND COALESCE(earlier.item_type_name, '') = COALESCE(line.item_type_name, '');
        END IF;

        -- A replacement starts from what the replaced inspection said, photos included.
        IF p_replaces IS NOT NULL THEN
            UPDATE app.joint_inspection_lines AS line
            SET result = earlier.result, note = earlier.note,
                tenant_caused = earlier.tenant_caused, pet_caused = earlier.pet_caused
            FROM app.joint_inspection_lines AS earlier
            WHERE line.inspection_id = v_id AND earlier.inspection_id = p_replaces
              AND earlier.line_kind = line.line_kind
              AND earlier.group_en = line.group_en
              AND lower(COALESCE(earlier.item_name, '')) = lower(COALESCE(line.item_name, ''))
              AND COALESCE(earlier.item_type_name, '') = COALESCE(line.item_type_name, '');
            UPDATE app.joint_inspection_lines AS line
            SET tenant_caused = false, pet_caused = false
            WHERE line.inspection_id = v_id AND line.tenant_caused AND line.move_in_result IS NOT NULL
              AND app.joint_inspection_rank(line.result) <= app.joint_inspection_rank(line.move_in_result);
            UPDATE app.joint_inspections AS inspection
            SET door_keys = v_old.door_keys, key_cards = v_old.key_cards,
                mailbox_keys = v_old.mailbox_keys, other_keys = v_old.other_keys,
                other_keys_note = v_old.other_keys_note
            WHERE inspection.id = v_id;
            UPDATE app.joint_inspection_meters AS meter SET reading = earlier.reading
            FROM app.joint_inspection_meters AS earlier
            WHERE meter.inspection_id = v_id AND earlier.inspection_id = p_replaces
              AND earlier.utility_type = meter.utility_type AND earlier.meter_id = meter.meter_id;
            INSERT INTO app.joint_inspection_files (inspection_id, line_id, role, media_type,
                byte_size, sha256, storage_key, created_by)
            SELECT v_id, line.id, file.role, file.media_type, file.byte_size, file.sha256,
                file.storage_key, p_actor
            FROM app.joint_inspection_files AS file
            LEFT JOIN app.joint_inspection_lines AS earlier ON earlier.id = file.line_id
            LEFT JOIN app.joint_inspection_lines AS line ON line.inspection_id = v_id
                AND line.line_kind = earlier.line_kind AND line.group_en = earlier.group_en
                AND lower(COALESCE(line.item_name, '')) = lower(COALESCE(earlier.item_name, ''))
                AND COALESCE(line.item_type_name, '') = COALESCE(earlier.item_type_name, '')
            WHERE file.inspection_id = p_replaces AND file.removed_at IS NULL
              AND file.role IN ('PHOTO', 'ELECTRICITY', 'WATER')
              AND (file.role <> 'PHOTO' OR line.id IS NOT NULL);
        END IF;

        PERFORM app.product_audit(p_property, p_actor, v_day, 'joint_inspection.started',
            'joint_inspection', v_id,
            CASE WHEN p_replaces IS NULL THEN 'Joint Inspection started' ELSE v_reason END,
            CASE WHEN p_replaces IS NULL THEN 'joint_inspections.record'
                 ELSE 'joint_inspections.replace' END, NULL,
            jsonb_build_object('inspection_number', v_number, 'kind', p_kind, 'lease_id', p_lease,
                'replaces_id', p_replaces, 'lines', v_ordinal), p_correlation);
        RETURN v_id;
    END $$;

    -- 2. Save what staff marked. Only what is sent changes.
    CREATE FUNCTION app.joint_inspection_save(p_property uuid, p_id uuid, p_version integer,
        p_changes jsonb, p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_row app.joint_inspections%ROWTYPE;
        v_entry jsonb;
        v_line app.joint_inspection_lines%ROWTYPE;
        v_result text;
        v_note text;
        v_tenant boolean;
        v_pet boolean;
        v_keys jsonb;
        v_key text;
        v_count integer;
        v_reading numeric;
        v_changed boolean := false;
    BEGIN
        IF p_changes IS NULL OR jsonb_typeof(p_changes) <> 'object'
            OR p_changes - ARRAY['lines', 'keys', 'meters'] <> '{}'::jsonb THEN
            RAISE EXCEPTION 'The change is invalid' USING ERRCODE = '22023';
        END IF;
        SELECT inspection.* INTO v_row FROM app.joint_inspections AS inspection
        WHERE inspection.id = p_id AND inspection.property_id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Joint Inspection does not exist' USING ERRCODE = '22023';
        END IF;
        PERFORM app.joint_inspection_require(p_actor, p_property, v_row);
        v_row := app.joint_inspection_for_change(p_property, p_id, p_version);

        IF p_changes ? 'lines' THEN
            IF jsonb_typeof(p_changes -> 'lines') <> 'array' OR jsonb_array_length(p_changes -> 'lines') > 500 THEN
                RAISE EXCEPTION 'The lines are invalid' USING ERRCODE = '22023';
            END IF;
            FOR v_entry IN SELECT value FROM jsonb_array_elements(p_changes -> 'lines') LOOP
                IF jsonb_typeof(v_entry) <> 'object'
                    OR v_entry - ARRAY['line_id', 'result', 'note', 'tenant_caused', 'pet_caused'] <> '{}'::jsonb
                    OR jsonb_typeof(v_entry -> 'line_id') IS DISTINCT FROM 'string' THEN
                    RAISE EXCEPTION 'A line is invalid' USING ERRCODE = '22023';
                END IF;
                BEGIN
                    SELECT line.* INTO v_line FROM app.joint_inspection_lines AS line
                    WHERE line.id = (v_entry ->> 'line_id')::uuid AND line.inspection_id = p_id
                    FOR UPDATE;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'A line is invalid' USING ERRCODE = '22023';
                END;
                IF v_line.id IS NULL THEN
                    RAISE EXCEPTION 'A line is not in this inspection' USING ERRCODE = '22023';
                END IF;
                v_result := CASE WHEN v_entry ? 'result' THEN v_entry ->> 'result' ELSE v_line.result END;
                IF v_result IS NOT NULL AND v_result NOT IN ('GOOD', 'BROKEN', 'MISSING')
                    OR v_result = 'MISSING' AND v_line.line_kind <> 'ITEM' THEN
                    RAISE EXCEPTION 'A place is Good or Broken; an item is Good, Broken or Missing'
                        USING ERRCODE = '22023';
                END IF;
                v_note := CASE WHEN v_entry ? 'note'
                    THEN app.problem_text(v_entry, 'note', 500, 'A note is at most 500 letters')
                    ELSE v_line.note END;
                v_tenant := CASE WHEN v_entry ? 'tenant_caused'
                    THEN (v_entry ->> 'tenant_caused')::boolean ELSE v_line.tenant_caused END;
                v_pet := CASE WHEN v_entry ? 'pet_caused'
                    THEN (v_entry ->> 'pet_caused')::boolean ELSE v_line.pet_caused END;
                IF v_result IS NULL OR v_result = 'GOOD' THEN
                    v_tenant := false;
                END IF;
                IF NOT COALESCE(v_tenant, false) THEN
                    v_pet := false;
                END IF;
                IF COALESCE(v_tenant, false) AND (v_row.kind <> 'MOVE_OUT'
                    OR v_row.move_in_id IS NOT NULL AND v_line.move_in_result IS NOT NULL
                        AND app.joint_inspection_rank(v_result) <= app.joint_inspection_rank(v_line.move_in_result)) THEN
                    RAISE EXCEPTION 'Tenant caused is only for a move-out line that is worse than at move-in'
                        USING ERRCODE = '22023';
                END IF;
                IF v_result IS DISTINCT FROM v_line.result OR v_note IS DISTINCT FROM v_line.note
                    OR COALESCE(v_tenant, false) IS DISTINCT FROM v_line.tenant_caused
                    OR COALESCE(v_pet, false) IS DISTINCT FROM v_line.pet_caused THEN
                    UPDATE app.joint_inspection_lines AS line
                    SET result = v_result, note = v_note, tenant_caused = COALESCE(v_tenant, false),
                        pet_caused = COALESCE(v_pet, false)
                    WHERE line.id = v_line.id;
                    v_changed := true;
                END IF;
                v_line := NULL;
            END LOOP;
        END IF;

        IF p_changes ? 'keys' THEN
            v_keys := p_changes -> 'keys';
            IF jsonb_typeof(v_keys) <> 'object' OR v_keys - ARRAY['door_keys', 'key_cards',
                    'mailbox_keys', 'other_keys', 'other_keys_note'] <> '{}'::jsonb THEN
                RAISE EXCEPTION 'The keys are invalid' USING ERRCODE = '22023';
            END IF;
            FOREACH v_key IN ARRAY ARRAY['door_keys', 'key_cards', 'mailbox_keys', 'other_keys'] LOOP
                IF v_keys ? v_key AND jsonb_typeof(v_keys -> v_key) <> 'null' AND (
                    jsonb_typeof(v_keys -> v_key) <> 'number'
                    OR (v_keys ->> v_key) !~ '^[0-9]{1,2}$') THEN
                    RAISE EXCEPTION 'Write how many keys, 0 to 99' USING ERRCODE = '22023';
                END IF;
            END LOOP;
            UPDATE app.joint_inspections AS inspection SET
                door_keys = CASE WHEN v_keys ? 'door_keys' THEN (v_keys ->> 'door_keys')::smallint ELSE inspection.door_keys END,
                key_cards = CASE WHEN v_keys ? 'key_cards' THEN (v_keys ->> 'key_cards')::smallint ELSE inspection.key_cards END,
                mailbox_keys = CASE WHEN v_keys ? 'mailbox_keys' THEN (v_keys ->> 'mailbox_keys')::smallint ELSE inspection.mailbox_keys END,
                other_keys = CASE WHEN v_keys ? 'other_keys' THEN (v_keys ->> 'other_keys')::smallint ELSE inspection.other_keys END,
                other_keys_note = CASE WHEN v_keys ? 'other_keys_note'
                    THEN app.problem_text(v_keys, 'other_keys_note', 200, 'The note on other keys is at most 200 letters')
                    ELSE inspection.other_keys_note END
            WHERE inspection.id = p_id;
            v_changed := true;
        END IF;

        IF p_changes ? 'meters' THEN
            IF jsonb_typeof(p_changes -> 'meters') <> 'array' THEN
                RAISE EXCEPTION 'The meter numbers are invalid' USING ERRCODE = '22023';
            END IF;
            FOR v_entry IN SELECT value FROM jsonb_array_elements(p_changes -> 'meters') LOOP
                IF jsonb_typeof(v_entry) <> 'object' OR v_entry - ARRAY['utility_type', 'reading'] <> '{}'::jsonb
                    OR NOT EXISTS (SELECT 1 FROM app.joint_inspection_meters AS meter
                        WHERE meter.inspection_id = p_id AND meter.utility_type = v_entry ->> 'utility_type') THEN
                    RAISE EXCEPTION 'This meter is not in the inspection' USING ERRCODE = '22023';
                END IF;
                IF jsonb_typeof(v_entry -> 'reading') = 'null' THEN
                    v_reading := NULL;
                ELSIF jsonb_typeof(v_entry -> 'reading') <> 'string'
                    OR (v_entry ->> 'reading') !~ '^[0-9]{1,13}(\.[0-9]{1,6})?$' THEN
                    RAISE EXCEPTION 'Write the meter number with at most 6 decimals' USING ERRCODE = '22023';
                ELSE
                    v_reading := (v_entry ->> 'reading')::numeric;
                END IF;
                UPDATE app.joint_inspection_meters AS meter SET reading = v_reading
                WHERE meter.inspection_id = p_id AND meter.utility_type = v_entry ->> 'utility_type'
                  AND meter.reading IS DISTINCT FROM v_reading;
                IF FOUND THEN
                    v_changed := true;
                END IF;
            END LOOP;
        END IF;

        IF v_changed THEN
            PERFORM app.joint_inspection_unsign(p_id, p_actor);
            UPDATE app.joint_inspections AS inspection SET version = inspection.version + 1
            WHERE inspection.id = p_id;
        END IF;
    END $$;

    -- 3. A photo, a meter photo or a signature, after the API kept the file.
    CREATE FUNCTION app.joint_inspection_add_file(p_property uuid, p_id uuid, p_version integer,
        p_file jsonb, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_row app.joint_inspections%ROWTYPE;
        v_file uuid := gen_random_uuid();
        v_role text := p_file ->> 'role';
        v_line uuid;
    BEGIN
        IF p_file IS NULL OR jsonb_typeof(p_file) <> 'object' OR p_file - ARRAY['role', 'line_id',
                'media_type', 'byte_size', 'sha256', 'storage_key'] <> '{}'::jsonb
            OR v_role IS NULL OR v_role NOT IN ('PHOTO', 'ELECTRICITY', 'WATER',
                'TENANT_SIGNATURE', 'STAFF_SIGNATURE') THEN
            RAISE EXCEPTION 'The file is invalid' USING ERRCODE = '22023';
        END IF;
        SELECT inspection.* INTO v_row FROM app.joint_inspections AS inspection
        WHERE inspection.id = p_id AND inspection.property_id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Joint Inspection does not exist' USING ERRCODE = '22023';
        END IF;
        PERFORM app.joint_inspection_require(p_actor, p_property, v_row);
        -- A signature is for the version the tenant read; a photo goes with any version.
        v_row := app.joint_inspection_for_change(p_property, p_id,
            CASE WHEN v_role LIKE '%SIGNATURE' THEN p_version END);
        IF v_role = 'PHOTO' THEN
            BEGIN
                v_line := (p_file ->> 'line_id')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'The line is invalid' USING ERRCODE = '22023';
            END;
            IF v_line IS NULL OR NOT EXISTS (SELECT 1 FROM app.joint_inspection_lines AS line
                    WHERE line.id = v_line AND line.inspection_id = p_id) THEN
                RAISE EXCEPTION 'The line is not in this inspection' USING ERRCODE = '22023';
            END IF;
            IF (SELECT count(*) FROM app.joint_inspection_files AS file
                    WHERE file.line_id = v_line AND file.removed_at IS NULL) >= 5 THEN
                RAISE EXCEPTION 'A line has at most 5 photos' USING ERRCODE = '22023';
            END IF;
        ELSIF p_file ? 'line_id' AND jsonb_typeof(p_file -> 'line_id') <> 'null' THEN
            RAISE EXCEPTION 'Only a photo belongs to a line' USING ERRCODE = '22023';
        END IF;
        IF v_role IN ('ELECTRICITY', 'WATER') AND NOT EXISTS (SELECT 1 FROM app.joint_inspection_meters AS meter
                WHERE meter.inspection_id = p_id AND meter.utility_type = v_role) THEN
            RAISE EXCEPTION 'This meter is not in the inspection' USING ERRCODE = '22023';
        END IF;
        IF v_role LIKE '%SIGNATURE' THEN
            IF EXISTS (SELECT 1 FROM app.joint_inspection_lines AS line WHERE line.inspection_id = p_id
                    AND (line.result IS NULL OR line.result <> 'GOOD' AND line.note IS NULL))
                OR EXISTS (SELECT 1 FROM app.joint_inspection_meters AS meter
                    WHERE meter.inspection_id = p_id AND meter.reading IS NULL)
                OR v_row.door_keys IS NULL OR v_row.key_cards IS NULL OR v_row.mailbox_keys IS NULL
                OR v_row.other_keys IS NULL THEN
                RAISE EXCEPTION 'Mark every line, write a note for each problem, the keys and the meter numbers before signing'
                    USING ERRCODE = '22023';
            END IF;
            IF v_role = 'STAFF_SIGNATURE' AND NOT EXISTS (SELECT 1 FROM app.joint_inspection_files AS file
                    WHERE file.inspection_id = p_id AND file.role = 'TENANT_SIGNATURE'
                      AND file.removed_at IS NULL) THEN
                RAISE EXCEPTION 'The tenant signs first' USING ERRCODE = '22023';
            END IF;
        END IF;
        -- A new meter photo or signature takes the place of the one before.
        IF v_role <> 'PHOTO' THEN
            UPDATE app.joint_inspection_files AS file
            SET removed_at = clock_timestamp(), removed_by = p_actor
            WHERE file.inspection_id = p_id AND file.role = v_role AND file.removed_at IS NULL;
        END IF;
        -- A new tenant signature, or a change of the photos, needs the staff to sign again.
        IF v_role IN ('PHOTO', 'ELECTRICITY', 'WATER') THEN
            PERFORM app.joint_inspection_unsign(p_id, p_actor);
        ELSIF v_role = 'TENANT_SIGNATURE' THEN
            UPDATE app.joint_inspection_files AS file
            SET removed_at = clock_timestamp(), removed_by = p_actor
            WHERE file.inspection_id = p_id AND file.role = 'STAFF_SIGNATURE' AND file.removed_at IS NULL;
        END IF;
        BEGIN
            INSERT INTO app.joint_inspection_files (id, inspection_id, line_id, role, media_type,
                byte_size, sha256, storage_key, created_by)
            VALUES (v_file, p_id, v_line, v_role, p_file ->> 'media_type',
                (p_file ->> 'byte_size')::integer, p_file ->> 'sha256', p_file ->> 'storage_key', p_actor);
        EXCEPTION WHEN check_violation OR invalid_text_representation OR numeric_value_out_of_range THEN
            RAISE EXCEPTION 'The file is invalid' USING ERRCODE = '22023';
        END;
        IF NOT (p_file ->> 'storage_key') LIKE 'inspections/' || p_id::text || '/%' THEN
            RAISE EXCEPTION 'The file is invalid' USING ERRCODE = '22023';
        END IF;
        RETURN v_file;
    END $$;

    -- 4. Take a photo off a Draft.
    CREATE FUNCTION app.joint_inspection_remove_file(p_property uuid, p_file uuid, p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_file app.joint_inspection_files%ROWTYPE;
        v_row app.joint_inspections%ROWTYPE;
    BEGIN
        SELECT file.* INTO v_file FROM app.joint_inspection_files AS file
        JOIN app.joint_inspections AS inspection ON inspection.id = file.inspection_id
        WHERE file.id = p_file AND inspection.property_id = p_property;
        IF NOT FOUND OR v_file.removed_at IS NOT NULL THEN
            RAISE EXCEPTION 'the photo does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT inspection.* INTO v_row FROM app.joint_inspections AS inspection
        WHERE inspection.id = v_file.inspection_id;
        PERFORM app.joint_inspection_require(p_actor, p_property, v_row);
        PERFORM app.joint_inspection_for_change(p_property, v_file.inspection_id, NULL);
        UPDATE app.joint_inspection_files AS file
        SET removed_at = clock_timestamp(), removed_by = p_actor WHERE file.id = p_file;
        IF v_file.role IN ('PHOTO', 'ELECTRICITY', 'WATER') THEN
            PERFORM app.joint_inspection_unsign(v_file.inspection_id, p_actor);
        END IF;
    END $$;

    -- Where a file is, to send it to a person who may read the inspection.
    CREATE FUNCTION app.joint_inspection_file(p_property uuid, p_file uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_found jsonb;
    BEGIN
        PERFORM app.require_product_right(p_actor, 'units.read', p_property);
        SELECT jsonb_build_object('storage_key', file.storage_key, 'sha256', file.sha256,
            'media_type', file.media_type)
        INTO v_found
        FROM app.joint_inspection_files AS file
        JOIN app.joint_inspections AS inspection ON inspection.id = file.inspection_id
        WHERE file.id = p_file AND inspection.property_id = p_property;
        IF v_found IS NULL THEN
            RAISE EXCEPTION 'the file does not exist' USING ERRCODE = '22023';
        END IF;
        RETURN v_found;
    END $$;

    -- 5. Finish: Done, the Problem reports and, at move-out, the damage findings.
    CREATE FUNCTION app.joint_inspection_finish(p_property uuid, p_id uuid, p_version integer,
        p_actor uuid, p_correlation uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_row app.joint_inspections%ROWTYPE;
        v_line app.joint_inspection_lines%ROWTYPE;
        v_old_line app.joint_inspection_lines%ROWTYPE;
        v_lease app.leases%ROWTYPE;
        v_type uuid;
        v_report uuid;
        v_number text;
        v_numbers text[] := '{}';
        v_findings jsonb := '[]'::jsonb;
        v_finding uuid;
        v_lines uuid[] := '{}';
        v_finding_ids uuid[] := '{}';
        v_intent jsonb;
        v_current uuid;
        v_old_move_out uuid;
        v_move_out uuid;
        v_label text := '';
    BEGIN
        SELECT inspection.* INTO v_row FROM app.joint_inspections AS inspection
        WHERE inspection.id = p_id AND inspection.property_id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Joint Inspection does not exist' USING ERRCODE = '22023';
        END IF;
        v_day := app.joint_inspection_require(p_actor, p_property, v_row);
        v_row := app.joint_inspection_for_change(p_property, p_id, p_version);
        IF NOT EXISTS (SELECT 1 FROM app.joint_inspection_files AS file WHERE file.inspection_id = p_id
                AND file.role = 'TENANT_SIGNATURE' AND file.removed_at IS NULL)
            OR NOT EXISTS (SELECT 1 FROM app.joint_inspection_files AS file WHERE file.inspection_id = p_id
                AND file.role = 'STAFF_SIGNATURE' AND file.removed_at IS NULL) THEN
            RAISE EXCEPTION 'The tenant and the staff member must both sign' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.joint_inspection_lines AS line WHERE line.inspection_id = p_id
                AND (line.result IS NULL OR line.result <> 'GOOD' AND line.note IS NULL))
            OR EXISTS (SELECT 1 FROM app.joint_inspection_meters AS meter
                WHERE meter.inspection_id = p_id AND meter.reading IS NULL) THEN
            RAISE EXCEPTION 'Mark every line, write a note for each problem, the keys and the meter numbers before signing'
                USING ERRCODE = '22023';
        END IF;
        SELECT lease.* INTO v_lease FROM app.leases AS lease WHERE lease.id = v_row.lease_id FOR UPDATE;

        -- Answer 3: a Problem report for each Broken or Missing line.
        FOR v_line IN SELECT line.* FROM app.joint_inspection_lines AS line
                WHERE line.inspection_id = p_id AND line.result IN ('BROKEN', 'MISSING')
                ORDER BY line.ordinal LOOP
            v_report := NULL;
            -- The same problem at move-in was reported then.
            CONTINUE WHEN v_row.kind = 'MOVE_OUT' AND v_line.move_in_result = v_line.result;
            -- A replaced inspection that already reported it the same way keeps that report.
            IF v_row.replaces_id IS NOT NULL THEN
                SELECT earlier.* INTO v_old_line FROM app.joint_inspection_lines AS earlier
                WHERE earlier.inspection_id = v_row.replaces_id AND earlier.line_kind = v_line.line_kind
                  AND earlier.group_en = v_line.group_en
                  AND lower(COALESCE(earlier.item_name, '')) = lower(COALESCE(v_line.item_name, ''))
                  AND COALESCE(earlier.item_type_name, '') = COALESCE(v_line.item_type_name, '')
                  AND earlier.result = v_line.result AND earlier.problem_report_id IS NOT NULL;
                v_report := v_old_line.problem_report_id;
                v_old_line := NULL;
            END IF;
            IF v_report IS NULL THEN
                SELECT kind.id INTO v_type FROM app.problem_types AS kind
                WHERE kind.code = CASE
                    WHEN v_line.line_kind = 'ITEM' THEN 'FURNITURE'
                    WHEN v_line.line_kind = 'BUILT_IN' AND v_line.item_name ILIKE '%air conditioner%'
                        THEN 'AIR_CONDITIONER'
                    ELSE 'OTHER' END;
                IF v_type IS NULL THEN
                    SELECT kind.id INTO v_type FROM app.problem_types AS kind WHERE kind.code = 'OTHER';
                END IF;
                v_report := gen_random_uuid();
                v_number := app.take_document_number('UNIT_PROBLEM', date_part('year', v_day)::integer);
                INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id,
                    lease_id, customer_id, place_item_id, place_number, problem_type_id, description,
                    urgent, always_urgent, may_enter, best_time, source, reported_by, created_by)
                VALUES (v_report, p_property, v_number, 'UNIT', v_row.unit_id, v_row.lease_id,
                    v_row.customer_id, v_line.place_item_id, v_line.place_number, v_type,
                    left(CASE v_row.kind WHEN 'MOVE_IN' THEN 'Move-in' ELSE 'Move-out' END
                        || ' Joint Inspection ' || v_row.inspection_number || ': '
                        || app.joint_inspection_line_text(v_line), 1000),
                    false, false, false, 'ANY', 'JOINT_INSPECTION', NULL, p_actor);
                PERFORM app.problem_report_event(v_report, 'RECEIVED', NULL,
                    jsonb_build_object('source', 'JOINT_INSPECTION', 'joint_inspection_id', p_id,
                        'inspection_number', v_row.inspection_number), p_actor);
                PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added',
                    'problem_report', v_report, 'Problem found at a Joint Inspection',
                    'joint_inspections.record', NULL, jsonb_build_object('report_number', v_number,
                        'kind', 'UNIT', 'source', 'JOINT_INSPECTION',
                        'inspection_number', v_row.inspection_number), p_correlation);
                v_numbers := v_numbers || v_number;
            END IF;
            UPDATE app.joint_inspection_lines AS line SET problem_report_id = v_report
            WHERE line.id = v_line.id;
        END LOOP;

        -- Answer 4: a move-out makes the V1 move-out inspection with the ticked lines.
        IF v_row.kind = 'MOVE_OUT' THEN
            FOR v_line IN SELECT line.* FROM app.joint_inspection_lines AS line
                    WHERE line.inspection_id = p_id AND line.tenant_caused ORDER BY line.ordinal LOOP
                v_finding := gen_random_uuid();
                v_findings := v_findings || jsonb_build_array(jsonb_build_object(
                    'finding_id', v_finding,
                    'description', left(app.joint_inspection_line_text(v_line), 1000),
                    'pet_related', v_line.pet_caused));
                v_lines := v_lines || v_line.id;
                v_finding_ids := v_finding_ids || v_finding;
            END LOOP;
            SELECT current.id INTO v_current FROM app.move_out_inspections AS current
            WHERE current.lease_id = v_row.lease_id AND NOT EXISTS (
                SELECT 1 FROM app.move_out_inspections AS later
                WHERE later.supersedes_inspection_id = current.id)
            ORDER BY current.completed_at DESC LIMIT 1;
            v_move_out := gen_random_uuid();
            v_label := 'Joint Inspection ' || v_row.inspection_number;
            v_intent := jsonb_build_object(
                'inspection_id', v_move_out,
                'expected_lease_version', v_lease.version,
                'inspection_date', to_jsonb(v_row.inspection_date),
                'result_text', left('Move-out ' || v_label || ', signed by the tenant and the staff member. '
                    || jsonb_array_length(v_findings) || ' damage finding(s) the tenant caused.', 5000),
                'authorization_reference', v_label,
                'evidence_reference', v_label || ' (signed on the tablet)',
                'reason', 'Move-out Joint Inspection',
                'findings', v_findings,
                'supersedes_inspection_id', to_jsonb(v_current));
            BEGIN
                PERFORM app.move_out_inspection_record(p_property, v_row.lease_id, p_actor,
                    gen_random_uuid(),
                    encode(sha256(convert_to(v_intent::text, 'UTF8')), 'hex'),
                    v_intent, 'joint-inspection-' || p_id::text);
            EXCEPTION WHEN SQLSTATE 'P5S01' THEN
                RAISE EXCEPTION 'The Final Settlement of this Lease is closed, so its move-out inspection cannot change'
                    USING ERRCODE = '55000';
            END;
            -- Each ticked line keeps the link to its damage finding.
            UPDATE app.joint_inspection_lines AS line SET finding_id = link.finding
            FROM unnest(v_lines, v_finding_ids) AS link(line_id, finding)
            WHERE line.id = link.line_id;
            UPDATE app.joint_inspections AS inspection SET move_out_inspection_id = v_move_out
            WHERE inspection.id = p_id;
        END IF;

        IF v_row.replaces_id IS NOT NULL THEN
            UPDATE app.joint_inspections AS old
            SET status = 'REPLACED', replaced_at = clock_timestamp(), replaced_by_id = p_id,
                version = old.version + 1
            WHERE old.id = v_row.replaces_id AND old.status = 'DONE';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'The inspection to replace changed. Reload it.' USING ERRCODE = '40001';
            END IF;
        END IF;
        UPDATE app.joint_inspections AS inspection
        SET status = 'DONE', done_at = clock_timestamp(), done_by = p_actor,
            version = inspection.version + 1
        WHERE inspection.id = p_id;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'joint_inspection.done',
            'joint_inspection', p_id, 'Joint Inspection signed by the tenant and the staff member',
            CASE WHEN v_row.replaces_id IS NULL THEN 'joint_inspections.record'
                 ELSE 'joint_inspections.replace' END, NULL,
            jsonb_build_object('inspection_number', v_row.inspection_number, 'kind', v_row.kind,
                'reports', to_jsonb(v_numbers), 'damage_findings', jsonb_array_length(v_findings),
                'replaces_id', v_row.replaces_id), p_correlation);
        RETURN jsonb_build_object('inspection_number', v_row.inspection_number,
            'reports', to_jsonb(v_numbers), 'damage_findings', jsonb_array_length(v_findings));
    END $$;

    -- 6. One inspection with its lines, meters, files and the Utilities reading of that day.
    CREATE FUNCTION app.joint_inspection_json(p_id uuid) RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'inspection_id', inspection.id,
            'inspection_number', inspection.inspection_number,
            'kind', inspection.kind,
            'status', inspection.status,
            'version', inspection.version,
            'inspection_date', inspection.inspection_date,
            'lease_id', inspection.lease_id,
            'lease_number', number.lease_number,
            'lease_status', lease.status,
            'unit_id', inspection.unit_id,
            'unit_number', unit.unit_number,
            'customer_id', inspection.customer_id,
            'tenant_name', inspection.tenant_name,
            'move_in_id', inspection.move_in_id,
            'move_in_number', move_in.inspection_number,
            'replaces', CASE WHEN old.id IS NULL THEN NULL ELSE jsonb_build_object(
                'inspection_id', old.id, 'inspection_number', old.inspection_number) END,
            'replace_reason', inspection.replace_reason,
            'replaced_by', CASE WHEN newer.id IS NULL THEN NULL ELSE jsonb_build_object(
                'inspection_id', newer.id, 'inspection_number', newer.inspection_number) END,
            'keys', jsonb_build_object('door_keys', inspection.door_keys,
                'key_cards', inspection.key_cards, 'mailbox_keys', inspection.mailbox_keys,
                'other_keys', inspection.other_keys, 'other_keys_note', inspection.other_keys_note),
            'move_in_keys', CASE WHEN move_in.id IS NULL THEN NULL ELSE jsonb_build_object(
                'door_keys', move_in.door_keys, 'key_cards', move_in.key_cards,
                'mailbox_keys', move_in.mailbox_keys, 'other_keys', move_in.other_keys) END,
            'started_by', starter.display_name,
            'created_at', inspection.created_at,
            'done_at', inspection.done_at,
            'done_by', finisher.display_name,
            'lines', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'line_id', line.id, 'ordinal', line.ordinal, 'line_kind', line.line_kind,
                    'place_item_id', line.place_item_id, 'place_number', line.place_number,
                    'group_en', line.group_en, 'group_km', line.group_km,
                    'item_name', line.item_name, 'item_name_km', line.item_name_km,
                    'item_type_name', line.item_type_name, 'item_type_name_km', line.item_type_name_km,
                    'quantity', line.quantity, 'result', line.result, 'note', line.note,
                    'tenant_caused', line.tenant_caused, 'pet_caused', line.pet_caused,
                    'move_in_result', line.move_in_result, 'move_in_note', line.move_in_note,
                    'problem_report', CASE WHEN report.id IS NULL THEN NULL ELSE jsonb_build_object(
                        'report_id', report.id, 'report_number', report.report_number) END,
                    'finding_id', line.finding_id,
                    'photos', COALESCE((SELECT jsonb_agg(jsonb_build_object('file_id', file.id,
                            'media_type', file.media_type) ORDER BY file.created_at)
                        FROM app.joint_inspection_files AS file
                        WHERE file.line_id = line.id AND file.removed_at IS NULL), '[]'::jsonb))
                    ORDER BY line.ordinal)
                FROM app.joint_inspection_lines AS line
                LEFT JOIN app.problem_reports AS report ON report.id = line.problem_report_id
                WHERE line.inspection_id = inspection.id), '[]'::jsonb),
            'meters', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'utility_type', meter.utility_type, 'serial_number', meter.serial_number,
                    'measurement_unit_code', meter.measurement_unit_code,
                    'reading', meter.reading::text,
                    'utilities_reading', (SELECT reading.reading_value::text FROM app.utility_readings AS reading
                        WHERE reading.meter_id = meter.meter_id
                          AND reading.reading_date = inspection.inspection_date),
                    'move_in_reading', (SELECT earlier.reading::text FROM app.joint_inspection_meters AS earlier
                        WHERE earlier.inspection_id = inspection.move_in_id
                          AND earlier.utility_type = meter.utility_type),
                    'photo', (SELECT jsonb_build_object('file_id', file.id, 'media_type', file.media_type)
                        FROM app.joint_inspection_files AS file
                        WHERE file.inspection_id = inspection.id AND file.role = meter.utility_type
                          AND file.removed_at IS NULL))
                    ORDER BY meter.utility_type)
                FROM app.joint_inspection_meters AS meter
                WHERE meter.inspection_id = inspection.id), '[]'::jsonb),
            'signatures', jsonb_build_object(
                'tenant', (SELECT jsonb_build_object('file_id', file.id, 'signed_at', file.created_at)
                    FROM app.joint_inspection_files AS file WHERE file.inspection_id = inspection.id
                      AND file.role = 'TENANT_SIGNATURE' AND file.removed_at IS NULL),
                'staff', (SELECT jsonb_build_object('file_id', file.id, 'signed_at', file.created_at,
                        'name', signer.display_name)
                    FROM app.joint_inspection_files AS file
                    LEFT JOIN app.user_accounts AS signer ON signer.actor_id = file.created_by
                    WHERE file.inspection_id = inspection.id
                      AND file.role = 'STAFF_SIGNATURE' AND file.removed_at IS NULL)),
            'move_out_inspection_id', inspection.move_out_inspection_id)
        FROM app.joint_inspections AS inspection
        JOIN app.leases AS lease ON lease.id = inspection.lease_id
        JOIN app.units AS unit ON unit.id = inspection.unit_id
        LEFT JOIN app.lease_numbers AS number ON number.lease_id = inspection.lease_id
        LEFT JOIN app.joint_inspections AS move_in ON move_in.id = inspection.move_in_id
        LEFT JOIN app.joint_inspections AS old ON old.id = inspection.replaces_id
        LEFT JOIN app.joint_inspections AS newer ON newer.id = inspection.replaced_by_id
        LEFT JOIN app.user_accounts AS starter ON starter.actor_id = inspection.created_by
        LEFT JOIN app.user_accounts AS finisher ON finisher.actor_id = inspection.done_by
        WHERE inspection.id = p_id
    $$;

    CREATE FUNCTION app.joint_inspection_read(p_property uuid, p_id uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_product_right(p_actor, 'units.read', p_property);
        IF NOT EXISTS (SELECT 1 FROM app.joint_inspections AS inspection
                WHERE inspection.id = p_id AND inspection.property_id = p_property) THEN
            RAISE EXCEPTION 'the Joint Inspection does not exist' USING ERRCODE = '22023';
        END IF;
        RETURN app.joint_inspection_json(p_id);
    END $$;

    -- 7. The list for the Inspections page, or one Lease's inspections (newest first, at most 200).
    CREATE FUNCTION app.joint_inspections_read(p_property uuid, p_actor uuid, p_lease uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_product_right(p_actor, 'units.read', p_property);
        RETURN COALESCE((SELECT jsonb_agg(row ORDER BY row_created DESC, row_id DESC)
            FROM (
                SELECT inspection.created_at AS row_created, inspection.id AS row_id,
                    jsonb_build_object(
                        'inspection_id', inspection.id,
                        'inspection_number', inspection.inspection_number,
                        'kind', inspection.kind,
                        'status', inspection.status,
                        'inspection_date', inspection.inspection_date,
                        'lease_id', inspection.lease_id,
                        'lease_number', number.lease_number,
                        'unit_id', inspection.unit_id,
                        'unit_number', unit.unit_number,
                        'tenant_name', inspection.tenant_name,
                        'problems', (SELECT count(*) FROM app.joint_inspection_lines AS line
                            WHERE line.inspection_id = inspection.id AND line.result IN ('BROKEN', 'MISSING')),
                        'new_problems', CASE WHEN inspection.kind = 'MOVE_OUT' THEN (
                            SELECT count(*) FROM app.joint_inspection_lines AS line
                            WHERE line.inspection_id = inspection.id AND line.result IN ('BROKEN', 'MISSING')
                              AND app.joint_inspection_rank(line.result)
                                  > app.joint_inspection_rank(line.move_in_result)) END,
                        'marked', (SELECT count(*) FROM app.joint_inspection_lines AS line
                            WHERE line.inspection_id = inspection.id AND line.result IS NOT NULL),
                        'lines', (SELECT count(*) FROM app.joint_inspection_lines AS line
                            WHERE line.inspection_id = inspection.id),
                        'replaces_number', old.inspection_number,
                        'replaced_by_number', newer.inspection_number,
                        'done_at', inspection.done_at) AS row
                FROM app.joint_inspections AS inspection
                JOIN app.units AS unit ON unit.id = inspection.unit_id
                LEFT JOIN app.lease_numbers AS number ON number.lease_id = inspection.lease_id
                LEFT JOIN app.joint_inspections AS old ON old.id = inspection.replaces_id
                LEFT JOIN app.joint_inspections AS newer ON newer.id = inspection.replaced_by_id
                WHERE inspection.property_id = p_property
                  AND (p_lease IS NULL OR inspection.lease_id = p_lease)
                ORDER BY inspection.created_at DESC, inspection.id DESC
                LIMIT 200
            ) AS rows), '[]'::jsonb);
    END $$;
"""

INNER_FUNCTIONS = (
    "app.joint_inspection_rank(text)",
    "app.joint_inspection_line_text(app.joint_inspection_lines)",
    "app.joint_inspection_for_change(uuid, uuid, integer)",
    "app.joint_inspection_require(uuid, uuid, app.joint_inspections)",
    "app.joint_inspection_unsign(uuid, uuid)",
    "app.joint_inspection_json(uuid)",
    "app.protect_joint_inspection()",
    "app.protect_joint_inspection_part()",
    "app.reject_joint_inspection_truncate()",
)
APP_FUNCTIONS = (
    "app.joint_inspection_start(uuid, uuid, text, uuid, text, uuid, uuid)",
    "app.joint_inspection_save(uuid, uuid, integer, jsonb, uuid)",
    "app.joint_inspection_add_file(uuid, uuid, integer, jsonb, uuid)",
    "app.joint_inspection_remove_file(uuid, uuid, uuid)",
    "app.joint_inspection_file(uuid, uuid, uuid)",
    "app.joint_inspection_finish(uuid, uuid, integer, uuid, uuid)",
    "app.joint_inspection_read(uuid, uuid, uuid)",
    "app.joint_inspections_read(uuid, uuid, uuid)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


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
        raise RuntimeError(f"{signature} does not have the expected text")
    op.execute(text(definition.replace(before, after)))


def upgrade() -> None:
    for name, description in CAPABILITIES:
        op.execute(
            "INSERT INTO app.capabilities (capability_id, family, description, grant_path, "
            f"provenance) VALUES ({_text(name)}, 'joint_inspections', {_text(description)}, "
            f"'bundle', '{PROVENANCE}')"
        )
    for code, en, kh, name in PERMISSIONS:
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(code)}, 'LEASING', "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        )
        op.execute(
            "INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance) "
            f"VALUES ({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        )
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in INNER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in APP_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")

    _patch(SEED, STAFF_BEFORE, STAFF_AFTER)
    every = _array(EVERY)
    staff = _array(STAFF)
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id
                        WHEN seeded.staff_bundle_id THEN {staff}
                        ELSE {every}
                    END AS added
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, held.capability_id
                FROM app.role_bundle_capabilities AS held
                WHERE held.role_bundle_id = v_default.role_bundle_id
                  AND held.version = v_default.version
                UNION
                SELECT v_default.role_bundle_id, v_default.version + 1, added
                FROM pg_catalog.unnest(v_default.added) AS added;
                SELECT property.timezone_name INTO v_timezone
                FROM app.properties AS property WHERE property.id = v_default.property_id;
                IF v_owner IS NOT NULL THEN
                    INSERT INTO app.audit_events (
                        id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                        reason, authorization_reference, property_id, previous_state,
                        resulting_state, correlation_id, source, outcome
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_at,
                        pg_catalog.timezone(v_timezone, v_at)::date, v_owner,
                        'identity.role_bundle.updated', 'role_bundle', v_default.role_bundle_id,
                        {_text(REASON)}, 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'capabilities_added', pg_catalog.to_jsonb(v_default.added)),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("the Joint Inspection migration is forward-only")
