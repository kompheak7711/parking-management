# ruff: noqa: E501
"""V1.1 part 6 (owner 2026-11-03 "Continue your task"): Quotations and the Products Invoice.

The plan of 01/11/2026 part 6 and the owner's answers of 30/10/2026 (mock-up round 16, DESIGN.md
"Products, stock and Quotations"):

1. ``quotations`` and ``quotation_lines``: a Quotation (QTyy000n in ``number_rules``) for one
   Customer, with up to 20 lines of products picked from the products table at their price, a
   note, and a "valid until" day (today plus the QUOTATION_DAYS business rule, 7). A price is
   never above the list price; a lower price needs the right "Lower a price" (a Manager or the
   Owner) and a reason, and the line keeps the list price. A Quotation can be made when stock
   is 0.
2. A changed Quotation is a new Quotation that replaces the old one (REPLACED); the Customer signs
   the new one. A Quotation the Customer refused is REFUSED with a reason. A waiting Quotation
   past its day shows as Expired.
3. "Customer signed" (``app.sign_quotation``): staff give the day the Customer signed and, for
   each Item, the place its stock is taken from. In one transaction the app records each line as
   an Invoice item charge, issues the Invoice at once (due on the issue day plus the one-time
   charge due days, as every hand-made Invoice) and takes the Items out of stock (Sale, with its
   own SM number). There is no reason box and no Manager wait. When an Item is not in stock the
   Quotation waits.
4. A voided Invoice from a Quotation puts its Items back where they were taken from (Sale
   returned), with new SM numbers.
5. Reports: a line from a Quotation counts in the new bar "Products and services"
   (``PRODUCT_CHARGES`` in ``app.report_income_facts``).
6. The old Settings › Regular services become Service products (unit Time, no cost yet: a Manager
   or the Owner types the cost, and the price follows the mark-up). Old Invoices keep their lines.
7. New rights quotations.read, quotations.make and quotations.lower_price in three permissions
   of the Money group. The Owner and Manager roles get all three; the Staff role sees
   Quotations (the Owner can tick "Make Quotations" for Staff in Roles).

Not in this part: ledger entries for stock (the General Ledger work posts the Sale's cost).
Technical choices by Claude under the owner's 2026-10-23 22:30 rule; no money rule changes.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270425_275"
down_revision: str | None = "20270424_274"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-quotations"
CAPABILITIES = (
    ("quotations.read", "See Quotations"),
    ("quotations.make", "Make Quotations and record the Customer's answer"),
    ("quotations.lower_price", "Lower a price on a Quotation"),
)
PERMISSIONS = (
    ("QUOTATIONS_OPEN", "See Quotations", "មើលសម្រង់តម្លៃ", ("quotations.read",)),
    ("QUOTATIONS_MAKE", "Make Quotations and record the Customer's answer", "ធ្វើសម្រង់តម្លៃ និងកត់ត្រាចម្លើយអតិថិជន", ("quotations.make",)),
    ("QUOTATION_LOWER_PRICE", "Lower a price on a Quotation", "បញ្ចុះតម្លៃលើសម្រង់តម្លៃ", ("quotations.lower_price",)),
)
OWNER = ("quotations.read", "quotations.make", "quotations.lower_price")
STAFF = ("quotations.read",)
REASON = "Owner plan 2026-11-01 part 6: Quotation rights"

SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'stock.purchase', 'stock.transfer']::text[]"
INCOME_FACTS = "app.report_income_facts(uuid,uuid,uuid[])"
INCOME_BEFORE = (
    "                   CASE WHEN EXISTS(SELECT 1 FROM app.regular_service_charges link\n"
)
INCOME_AFTER = (
    "                   -- V1.1 part 6 (DL-123): a line from a Quotation counts in Products and services.\n"
    "                   CASE WHEN EXISTS(SELECT 1 FROM app.quotation_lines quoted\n"
    "                       WHERE quoted.charge_id=line.authorized_obligation_id)\n"
    "                       THEN 'PRODUCT_CHARGES'\n"
    "                   WHEN EXISTS(SELECT 1 FROM app.regular_service_charges link\n"
)

# Stock that comes in: a Sale returned by a void counts like a Transfer in.
IN_KINDS = "'PURCHASE', 'ADJUSTMENT_IN', 'TRANSFER_IN', 'SALE_RETURN'"


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


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
    capability_rows = ",\n            ".join(
        f"({_text(name)}, pg_catalog.split_part({_text(name)}, '.', 1), {_text(description)}, "
        f"'bundle', '{PROVENANCE}')"
        for name, description in CAPABILITIES
    )
    mapping_rows = ",\n            ".join(
        f"({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        for code, _en, _kh, names in PERMISSIONS
        for name in names
    )
    op.execute(
        f"""
        -- 7. The rights and their permissions.
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES
            {capability_rows};
        """
    )
    for code, en, kh, _names in PERMISSIONS:
        # One statement per row: each reads the largest sort order so far.
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(code)}, 'MONEY', "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        )
    op.execute(
        f"""
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES
            {mapping_rows};

        -- 1. Quotations and their lines.
        CREATE TABLE app.quotations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
            quotation_number text NOT NULL UNIQUE CHECK (quotation_number ~ '^[A-Z]{{2,5}}[0-9]{{6,}}$'),
            customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
            lease_id uuid REFERENCES app.leases (id) ON DELETE RESTRICT,
            note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 200),
            made_on date NOT NULL,
            valid_until date NOT NULL CHECK (valid_until >= made_on),
            total_usd_cents bigint NOT NULL CHECK (total_usd_cents > 0),
            lowered_reason text CHECK (lowered_reason = btrim(lowered_reason)
                AND length(lowered_reason) BETWEEN 1 AND 500),
            replaces_id uuid UNIQUE REFERENCES app.quotations (id) ON DELETE RESTRICT,
            status text NOT NULL DEFAULT 'WAITING'
                CHECK (status IN ('WAITING', 'SIGNED', 'REPLACED', 'REFUSED')),
            signed_on date,
            signed_at timestamptz,
            signed_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            invoice_id uuid UNIQUE REFERENCES app.invoices (id) ON DELETE RESTRICT,
            refused_reason text CHECK (refused_reason = btrim(refused_reason)
                AND length(refused_reason) BETWEEN 1 AND 500),
            closed_at timestamptz,
            closed_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            CONSTRAINT quotations_signed_shape CHECK (
                (status = 'SIGNED') = (signed_on IS NOT NULL AND signed_at IS NOT NULL
                    AND signed_by IS NOT NULL AND invoice_id IS NOT NULL)),
            CONSTRAINT quotations_signed_in_time CHECK (
                signed_on IS NULL OR signed_on BETWEEN made_on AND valid_until),
            CONSTRAINT quotations_refused_shape CHECK (
                (status = 'REFUSED') = (refused_reason IS NOT NULL)),
            CONSTRAINT quotations_closed_shape CHECK (
                (status = 'WAITING') = (closed_at IS NULL AND closed_by IS NULL))
        );
        CREATE INDEX quotations_property_idx ON app.quotations (property_id, created_at DESC);
        CREATE INDEX quotations_customer_idx ON app.quotations (customer_id);
        COMMENT ON TABLE app.quotations IS
            'V1.1 part 6 (DL-123): Quotations; signing issues the Products Invoice and takes the Items out of stock.';

        CREATE TABLE app.quotation_lines (
            quotation_id uuid NOT NULL REFERENCES app.quotations (id) ON DELETE RESTRICT,
            line_position smallint NOT NULL CHECK (line_position BETWEEN 1 AND 20),
            product_id uuid NOT NULL REFERENCES app.products (id) ON DELETE RESTRICT,
            quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 999),
            list_price_usd_cents bigint NOT NULL CHECK (list_price_usd_cents > 0),
            price_usd_cents bigint NOT NULL CHECK (price_usd_cents > 0),
            charge_id uuid UNIQUE
                REFERENCES app.authorized_nonrecurring_obligations (id) ON DELETE RESTRICT,
            PRIMARY KEY (quotation_id, line_position),
            CONSTRAINT quotation_lines_never_above_list CHECK (price_usd_cents <= list_price_usd_cents)
        );
        CREATE INDEX quotation_lines_product_idx ON app.quotation_lines (product_id);

        -- A Quotation changes only from Waiting to Signed, Replaced or Refused; its lines keep
        -- their prices (a line only gets the charge of its Invoice item when it is signed).
        CREATE FUNCTION app.protect_quotation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' OR OLD.status <> 'WAITING'
                OR NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
                OR NEW.quotation_number <> OLD.quotation_number
                OR NEW.customer_id <> OLD.customer_id
                OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
                OR NEW.note IS DISTINCT FROM OLD.note OR NEW.made_on <> OLD.made_on
                OR NEW.valid_until <> OLD.valid_until OR NEW.total_usd_cents <> OLD.total_usd_cents
                OR NEW.lowered_reason IS DISTINCT FROM OLD.lowered_reason
                OR NEW.replaces_id IS DISTINCT FROM OLD.replaces_id
                OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by
                OR NEW.version <> OLD.version + 1 OR NEW.status = 'WAITING'
            THEN
                RAISE EXCEPTION 'A Quotation is never changed; a new one replaces it'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.protect_quotation() FROM PUBLIC;
        CREATE TRIGGER quotations_protect BEFORE UPDATE OR DELETE ON app.quotations
            FOR EACH ROW EXECUTE FUNCTION app.protect_quotation();

        CREATE FUNCTION app.protect_quotation_line() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' OR OLD.charge_id IS NOT NULL OR NEW.charge_id IS NULL
                OR NEW.quotation_id <> OLD.quotation_id
                OR NEW.line_position <> OLD.line_position OR NEW.product_id <> OLD.product_id
                OR NEW.quantity <> OLD.quantity
                OR NEW.list_price_usd_cents <> OLD.list_price_usd_cents
                OR NEW.price_usd_cents <> OLD.price_usd_cents
            THEN
                RAISE EXCEPTION 'A Quotation line is never changed' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.protect_quotation_line() FROM PUBLIC;
        CREATE TRIGGER quotation_lines_protect BEFORE UPDATE OR DELETE ON app.quotation_lines
            FOR EACH ROW EXECUTE FUNCTION app.protect_quotation_line();

        CREATE FUNCTION app.reject_quotation_truncate() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Quotations are never emptied' USING ERRCODE = '55000';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_quotation_truncate() FROM PUBLIC;
        CREATE TRIGGER quotations_no_truncate BEFORE TRUNCATE ON app.quotations
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_quotation_truncate();
        CREATE TRIGGER quotation_lines_no_truncate BEFORE TRUNCATE ON app.quotation_lines
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_quotation_truncate();

        -- 3 and 4. Sales and returned Sales are stock movements of a Quotation.
        ALTER TABLE app.product_transactions DROP CONSTRAINT product_transactions_kind_check;
        ALTER TABLE app.product_transactions ADD CONSTRAINT product_transactions_kind_check
            CHECK (kind IN ('PURCHASE', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'TRANSFER_OUT',
                'TRANSFER_IN', 'SALE', 'SALE_RETURN'));
        ALTER TABLE app.product_transactions ADD COLUMN quotation_id uuid,
            ADD COLUMN quotation_line smallint;
        ALTER TABLE app.product_transactions ADD CONSTRAINT product_transactions_quotation_line_fkey
            FOREIGN KEY (quotation_id, quotation_line)
            REFERENCES app.quotation_lines (quotation_id, line_position) ON DELETE RESTRICT;
        ALTER TABLE app.product_transactions ADD CONSTRAINT product_transactions_sale_has_quotation
            CHECK ((kind IN ('SALE', 'SALE_RETURN'))
                = (quotation_id IS NOT NULL AND quotation_line IS NOT NULL));
        CREATE INDEX product_transactions_quotation_idx ON app.product_transactions (quotation_id)
            WHERE quotation_id IS NOT NULL;

        CREATE OR REPLACE FUNCTION app.stock_at(p_product uuid, p_unit uuid, p_item uuid, p_number integer)
        RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT COALESCE(sum(CASE WHEN movement.kind IN ({IN_KINDS})
                                     THEN movement.quantity ELSE -movement.quantity END), 0)
            FROM app.product_transactions AS movement
            WHERE movement.product_id = p_product AND movement.unit_id = p_unit
              AND movement.place_item_id = p_item AND movement.place_number = p_number
        $$;

        CREATE OR REPLACE FUNCTION app.keep_places_with_stock() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_count integer := CASE WHEN TG_OP = 'DELETE' THEN 0 ELSE NEW.feature_count END;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.product_transactions AS movement
                WHERE movement.unit_id = OLD.unit_id AND movement.place_item_id = OLD.item_id
                  AND movement.place_number > v_count
                GROUP BY movement.product_id, movement.place_number
                HAVING sum(CASE WHEN movement.kind IN ({IN_KINDS})
                                THEN movement.quantity ELSE -movement.quantity END) <> 0
            ) THEN
                RAISE EXCEPTION 'A place that holds stock cannot be removed; move the stock first'
                    USING ERRCODE = '55000';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;

        -- Quotation numbers.
        INSERT INTO app.number_rules (document_type, year, last_number, format)
        SELECT 'QUOTATION', year, 0, 'QTyy000n'
        FROM (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
                  statement_timestamp()))::smallint AS year
              FROM app.properties AS property
              UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
        ON CONFLICT (document_type, year) DO NOTHING;
        UPDATE app.business_rule_names SET used_by_app = true WHERE code = 'QUOTATION_DAYS';

        -- How a Quotation reads: its state today (Expired is a Waiting one past its day).
        CREATE FUNCTION app.quotation_json(p_quotation uuid) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'quotation_id', quotation.id,
                'quotation_number', quotation.quotation_number,
                'status', quotation.status,
                'state', CASE WHEN quotation.status = 'WAITING'
                    AND quotation.valid_until < timezone(property.timezone_name, statement_timestamp())::date
                    THEN 'EXPIRED' ELSE quotation.status END,
                'customer_id', quotation.customer_id,
                'customer_name', customer.legal_name,
                'customer_phone', customer.phone_number,
                'lease_id', quotation.lease_id,
                'unit_number', unit.unit_number,
                'note', quotation.note,
                'made_on', quotation.made_on,
                'valid_until', quotation.valid_until,
                'due_days', app.one_time_charge_due_days(property.id,
                    timezone(property.timezone_name, statement_timestamp())::date),
                'total_usd_cents', quotation.total_usd_cents,
                'lowered_reason', quotation.lowered_reason,
                'replaces_id', quotation.replaces_id,
                'replaces_number', replaced.quotation_number,
                'replaced_by_id', successor.id,
                'replaced_by_number', successor.quotation_number,
                'signed_on', quotation.signed_on,
                'signed_at', quotation.signed_at,
                'signed_by_name', signer.display_name,
                'invoice_id', quotation.invoice_id,
                'invoice_number', invoice.invoice_number,
                'invoice_status', invoice.status,
                'refused_reason', quotation.refused_reason,
                'closed_at', quotation.closed_at,
                'closed_by_name', closer.display_name,
                'created_at', quotation.created_at,
                'created_by_name', maker.display_name,
                'version', quotation.version,
                'lines', (
                    SELECT jsonb_agg(jsonb_build_object(
                        'position', line.line_position,
                        'product_id', product.id,
                        'sku', product.sku,
                        'name_en', product.name_en,
                        'name_kh', product.name_kh,
                        'kind', category.kind,
                        'measure_unit', product.measure_unit,
                        'quantity', line.quantity,
                        'list_price_usd_cents', line.list_price_usd_cents,
                        'price_usd_cents', line.price_usd_cents,
                        'amount_usd_cents', line.quantity::bigint * line.price_usd_cents,
                        'taken_from', (
                            SELECT jsonb_build_object('unit_id', sale.unit_id,
                                'unit_number', place_unit.unit_number,
                                'item_id', sale.place_item_id, 'number', sale.place_number,
                                'name_en', item.name_en, 'name_kh', item.name_km,
                                'movement_number', sale.movement_number)
                            FROM app.product_transactions AS sale
                            JOIN app.units AS place_unit ON place_unit.id = sale.unit_id
                            JOIN app.unit_setup_items AS item ON item.id = sale.place_item_id
                            WHERE sale.quotation_id = quotation.id AND sale.kind = 'SALE'
                              AND sale.quotation_line = line.line_position)
                    ) ORDER BY line.line_position)
                    FROM app.quotation_lines AS line
                    JOIN app.products AS product ON product.id = line.product_id
                    JOIN app.product_categories AS category ON category.id = product.category_id
                    WHERE line.quotation_id = quotation.id)
            )
            FROM app.quotations AS quotation
            JOIN app.properties AS property ON property.id = quotation.property_id
            JOIN app.customers AS customer ON customer.id = quotation.customer_id
            LEFT JOIN app.leases AS lease ON lease.id = quotation.lease_id
            LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
            LEFT JOIN app.quotations AS replaced ON replaced.id = quotation.replaces_id
            LEFT JOIN app.quotations AS successor ON successor.replaces_id = quotation.id
            LEFT JOIN app.invoices AS invoice ON invoice.id = quotation.invoice_id
            LEFT JOIN app.user_accounts AS maker ON maker.actor_id = quotation.created_by
            LEFT JOIN app.user_accounts AS signer ON signer.actor_id = quotation.signed_by
            LEFT JOIN app.user_accounts AS closer ON closer.actor_id = quotation.closed_by
            WHERE quotation.id = p_quotation
        $$;
        REVOKE ALL ON FUNCTION app.quotation_json(uuid) FROM PUBLIC;

        CREATE FUNCTION app.quotations_read(p_property uuid, p_actor uuid) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.require_product_right(p_actor, 'quotations.read', p_property);
            RETURN COALESCE((
                SELECT jsonb_agg(app.quotation_json(recent.id) ORDER BY recent.created_at DESC,
                    recent.quotation_number DESC)
                FROM (SELECT quotation.id, quotation.created_at, quotation.quotation_number
                      FROM app.quotations AS quotation
                      WHERE quotation.property_id = p_property
                      ORDER BY quotation.created_at DESC, quotation.quotation_number DESC
                      LIMIT 300) AS recent), '[]'::jsonb);
        END $$;

        CREATE FUNCTION app.quotation_read(p_property uuid, p_quotation uuid, p_actor uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.require_product_right(p_actor, 'quotations.read', p_property);
            IF NOT EXISTS (SELECT 1 FROM app.quotations AS quotation
                           WHERE quotation.id = p_quotation AND quotation.property_id = p_property) THEN
                RAISE EXCEPTION 'the Quotation does not exist' USING ERRCODE = '22023';
            END IF;
            RETURN app.quotation_json(p_quotation);
        END $$;

        -- 1 and 2. Make a Quotation, or a new one that replaces a waiting one.
        CREATE FUNCTION app.make_quotation(p_property uuid, p_customer uuid, p_lease uuid,
            p_note text, p_replaces uuid, p_lowered_reason text, p_lines jsonb, p_actor uuid,
            p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_day date := app.require_product_right(p_actor, 'quotations.make', p_property);
            v_id uuid := gen_random_uuid();
            v_line jsonb;
            v_position integer := 0;
            v_rows jsonb := '[]'::jsonb;
            v_product_id uuid;
            v_product app.products%ROWTYPE;
            v_kind text;
            v_quantity numeric;
            v_price numeric;
            v_total bigint := 0;
            v_lowered boolean := false;
            v_old app.quotations%ROWTYPE;
            v_reason text := NULLIF(btrim(p_lowered_reason), '');
            v_note text := NULLIF(btrim(p_note), '');
            v_days integer;
            v_number text;
        BEGIN
            IF p_customer IS NULL OR NOT EXISTS (
                SELECT 1 FROM app.customers AS customer
                WHERE customer.id = p_customer AND customer.deactivated_at IS NULL) THEN
                RAISE EXCEPTION 'the Customer does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_lease IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
                WHERE lease.id = p_lease AND unit.property_id = p_property
                  AND lease.primary_tenant_id = p_customer) THEN
                RAISE EXCEPTION 'The Lease is not this Customer''s' USING ERRCODE = '22023';
            END IF;
            IF v_note IS NOT NULL AND length(v_note) > 200 THEN
                RAISE EXCEPTION 'The note is at most 200 letters' USING ERRCODE = '22023';
            END IF;
            IF p_lines IS NULL OR jsonb_typeof(p_lines) <> 'array'
                OR jsonb_array_length(p_lines) NOT BETWEEN 1 AND 20 THEN
                RAISE EXCEPTION 'A Quotation has 1 to 20 lines' USING ERRCODE = '22023';
            END IF;
            IF p_replaces IS NOT NULL THEN
                SELECT quotation.* INTO v_old FROM app.quotations AS quotation
                WHERE quotation.id = p_replaces AND quotation.property_id = p_property FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'the Quotation does not exist' USING ERRCODE = '22023';
                END IF;
                IF v_old.status <> 'WAITING' OR v_old.valid_until < v_day THEN
                    RAISE EXCEPTION 'Only a waiting Quotation can be replaced' USING ERRCODE = '55000';
                END IF;
                IF v_old.customer_id <> p_customer THEN
                    RAISE EXCEPTION 'A new version is for the same Customer' USING ERRCODE = '22023';
                END IF;
            END IF;
            -- Every line is read and checked first; then the Quotation and its lines are saved.
            FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
                v_position := v_position + 1;
                IF jsonb_typeof(v_line) <> 'object'
                    OR jsonb_typeof(v_line -> 'product_id') <> 'string'
                    OR jsonb_typeof(v_line -> 'quantity') <> 'number'
                    OR jsonb_typeof(v_line -> 'price_usd_cents') <> 'number' THEN
                    RAISE EXCEPTION 'A Quotation line is invalid' USING ERRCODE = '22023';
                END IF;
                BEGIN
                    v_quantity := (v_line ->> 'quantity')::numeric;
                    v_price := (v_line ->> 'price_usd_cents')::numeric;
                    v_product_id := (v_line ->> 'product_id')::uuid;
                EXCEPTION WHEN data_exception THEN
                    RAISE EXCEPTION 'A Quotation line is invalid' USING ERRCODE = '22023';
                END;
                IF v_quantity <> trunc(v_quantity) OR v_quantity NOT BETWEEN 1 AND 999
                    OR v_price <> trunc(v_price) OR v_price NOT BETWEEN 1 AND 999999999 THEN
                    RAISE EXCEPTION 'A quantity is a whole number from 1 to 999 and a price above 0'
                        USING ERRCODE = '22023';
                END IF;
                SELECT product.* INTO v_product FROM app.products AS product
                WHERE product.id = v_product_id AND product.property_id = p_property;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'the product does not exist' USING ERRCODE = '22023';
                END IF;
                SELECT category.kind INTO v_kind FROM app.product_categories AS category
                WHERE category.id = v_product.category_id;
                IF v_product.price_usd_cents IS NULL THEN
                    RAISE EXCEPTION 'A product without a price cannot be quoted' USING ERRCODE = '55000';
                END IF;
                IF v_product.discontinued AND v_kind = 'SERVICE' THEN
                    RAISE EXCEPTION 'A discontinued Service cannot be quoted' USING ERRCODE = '55000';
                END IF;
                IF v_price > v_product.price_usd_cents THEN
                    RAISE EXCEPTION 'A price is never above the list price' USING ERRCODE = '22023';
                END IF;
                IF v_price < v_product.price_usd_cents THEN
                    v_lowered := true;
                END IF;
                v_rows := v_rows || jsonb_build_array(jsonb_build_object(
                    'position', v_position, 'product_id', v_product.id,
                    'quantity', v_quantity::integer, 'list', v_product.price_usd_cents,
                    'price', v_price::bigint));
                v_total := v_total + v_quantity::bigint * v_price::bigint;
            END LOOP;
            IF v_lowered THEN
                PERFORM app.require_product_right(p_actor, 'quotations.lower_price', p_property);
                IF v_reason IS NULL OR length(v_reason) > 500 THEN
                    RAISE EXCEPTION 'A lower price needs a reason' USING ERRCODE = '22023';
                END IF;
            ELSE
                v_reason := NULL;
            END IF;
            v_number := app.take_document_number('QUOTATION', date_part('year', v_day)::integer);
            v_days := COALESCE(app.business_rule_value('QUOTATION_DAYS', v_day), 7)::integer;
            INSERT INTO app.quotations (id, property_id, quotation_number, customer_id, lease_id,
                note, made_on, valid_until, total_usd_cents, lowered_reason, replaces_id, created_by)
            VALUES (v_id, p_property, v_number, p_customer, p_lease, v_note, v_day,
                v_day + greatest(v_days, 0), v_total, v_reason, p_replaces, p_actor);
            INSERT INTO app.quotation_lines (quotation_id, line_position, product_id, quantity,
                list_price_usd_cents, price_usd_cents)
            SELECT v_id, (row.value ->> 'position')::smallint, (row.value ->> 'product_id')::uuid,
                (row.value ->> 'quantity')::integer, (row.value ->> 'list')::bigint,
                (row.value ->> 'price')::bigint
            FROM jsonb_array_elements(v_rows) AS row(value);
            IF p_replaces IS NOT NULL THEN
                UPDATE app.quotations AS quotation
                SET status = 'REPLACED', closed_at = statement_timestamp(), closed_by = p_actor,
                    version = quotation.version + 1
                WHERE quotation.id = p_replaces;
            END IF;
            PERFORM app.product_audit(p_property, p_actor, v_day, 'quotation.made', 'quotation',
                v_id, COALESCE(v_reason, 'Quotation made'), 'quotations.make', NULL,
                jsonb_build_object('quotation_number', v_number, 'total_usd_cents', v_total,
                    'replaces_id', p_replaces), p_correlation);
            RETURN v_id;
        END $$;

        CREATE FUNCTION app.refuse_quotation(p_property uuid, p_quotation uuid,
            p_expected_version integer, p_reason text, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_day date := app.require_product_right(p_actor, 'quotations.make', p_property);
            v_quotation app.quotations%ROWTYPE;
            v_reason text := NULLIF(btrim(p_reason), '');
        BEGIN
            SELECT quotation.* INTO v_quotation FROM app.quotations AS quotation
            WHERE quotation.id = p_quotation AND quotation.property_id = p_property FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Quotation does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_expected_version IS DISTINCT FROM v_quotation.version THEN
                RAISE EXCEPTION 'the Quotation changed since it was read' USING ERRCODE = '40001';
            END IF;
            IF v_quotation.status <> 'WAITING' THEN
                RAISE EXCEPTION 'Only a waiting Quotation can be refused' USING ERRCODE = '55000';
            END IF;
            IF v_reason IS NULL OR length(v_reason) > 500 THEN
                RAISE EXCEPTION 'Enter why the Customer refused' USING ERRCODE = '22023';
            END IF;
            UPDATE app.quotations AS quotation
            SET status = 'REFUSED', refused_reason = v_reason, closed_at = statement_timestamp(),
                closed_by = p_actor, version = quotation.version + 1
            WHERE quotation.id = p_quotation;
            PERFORM app.product_audit(p_property, p_actor, v_day, 'quotation.refused', 'quotation',
                p_quotation, v_reason, 'quotations.make',
                jsonb_build_object('status', 'WAITING'), jsonb_build_object('status', 'REFUSED'),
                p_correlation);
            RETURN v_quotation.version + 1;
        END $$;

        -- 3. Customer signed: the Invoice is issued and the Items leave stock, all or nothing.
        CREATE FUNCTION app.sign_quotation(p_property uuid, p_quotation uuid,
            p_expected_version integer, p_signed_on date, p_takes jsonb, p_actor uuid,
            p_correlation uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_day date := app.require_product_right(p_actor, 'quotations.make', p_property);
            v_quotation app.quotations%ROWTYPE;
            v_line record;
            v_take jsonb;
            v_items jsonb := '[]'::jsonb;
            v_charge uuid;
            v_invoice uuid := gen_random_uuid();
            v_issued jsonb;
            v_version integer;
            v_number text;
            v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
            v_digest text;
        BEGIN
            SELECT quotation.* INTO v_quotation FROM app.quotations AS quotation
            WHERE quotation.id = p_quotation AND quotation.property_id = p_property FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Quotation does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_expected_version IS DISTINCT FROM v_quotation.version THEN
                RAISE EXCEPTION 'the Quotation changed since it was read' USING ERRCODE = '40001';
            END IF;
            IF v_quotation.status <> 'WAITING' THEN
                RAISE EXCEPTION 'Only a waiting Quotation can be signed' USING ERRCODE = '55000';
            END IF;
            IF p_signed_on IS NULL OR p_signed_on < v_quotation.made_on OR p_signed_on > v_day THEN
                RAISE EXCEPTION 'The Customer signed between the Quotation day and today'
                    USING ERRCODE = '22023';
            END IF;
            IF p_signed_on > v_quotation.valid_until THEN
                RAISE EXCEPTION 'The Quotation was no longer valid on that day' USING ERRCODE = '55000';
            END IF;
            IF p_takes IS NULL OR jsonb_typeof(p_takes) <> 'object' THEN
                RAISE EXCEPTION 'Choose where each Item is taken from' USING ERRCODE = '22023';
            END IF;
            -- The products of the Quotation, in one order, so two signings never wait on each other.
            PERFORM 1 FROM app.products AS product
            WHERE product.id IN (SELECT line.product_id FROM app.quotation_lines AS line
                                 WHERE line.quotation_id = p_quotation)
            ORDER BY product.id FOR UPDATE;
            FOR v_line IN
                SELECT line.*, product.name_en, category.kind
                FROM app.quotation_lines AS line
                JOIN app.products AS product ON product.id = line.product_id
                JOIN app.product_categories AS category ON category.id = product.category_id
                WHERE line.quotation_id = p_quotation ORDER BY line.line_position
            LOOP
                v_charge := gen_random_uuid();
                v_items := v_items || jsonb_build_array(jsonb_build_object(
                    'charge_id', v_charge, 'description', v_line.name_en,
                    'quantity', v_line.quantity, 'unit_price_usd_cents', v_line.price_usd_cents));
            END LOOP;
            v_digest := encode(sha256(convert_to('quotation-sign:' || p_quotation::text, 'UTF8')), 'hex');
            PERFORM app.create_items_invoice_draft(p_property, p_actor, gen_random_uuid(), v_digest,
                v_invoice, gen_random_uuid(), v_correlation, v_quotation.customer_id,
                v_quotation.lease_id,
                'Quotation ' || v_quotation.quotation_number || ' signed by the Customer on '
                    || to_char(p_signed_on, 'DD/MM/YYYY'),
                'Quotation ' || v_quotation.quotation_number, v_items);
            -- Each line keeps the charge of its Invoice item.
            UPDATE app.quotation_lines AS line SET charge_id = (item.value ->> 'charge_id')::uuid
            FROM jsonb_array_elements(v_items) WITH ORDINALITY AS item(value, position)
            WHERE line.quotation_id = p_quotation AND line.line_position = item.position;
            SELECT invoice.version INTO v_version FROM app.invoices AS invoice
            WHERE invoice.id = v_invoice;
            v_issued := app.issue_invoice(p_property, v_invoice, p_actor, gen_random_uuid(),
                v_digest, v_version, gen_random_uuid(), v_correlation, NULL, NULL);
            UPDATE app.quotations AS quotation
            SET status = 'SIGNED', signed_on = p_signed_on, signed_at = statement_timestamp(),
                signed_by = p_actor, invoice_id = v_invoice, closed_at = statement_timestamp(),
                closed_by = p_actor, version = quotation.version + 1
            WHERE quotation.id = p_quotation;
            -- The Items leave stock (a Service has none).
            FOR v_line IN
                SELECT line.*, category.kind
                FROM app.quotation_lines AS line
                JOIN app.products AS product ON product.id = line.product_id
                JOIN app.product_categories AS category ON category.id = product.category_id
                WHERE line.quotation_id = p_quotation AND category.kind = 'ITEM'
                ORDER BY line.line_position
            LOOP
                v_take := p_takes -> v_line.line_position::text;
                IF v_take IS NULL OR jsonb_typeof(v_take) <> 'object' THEN
                    RAISE EXCEPTION 'Choose where each Item is taken from' USING ERRCODE = '22023';
                END IF;
                PERFORM app.assert_place(p_property, (v_take ->> 'unit_id')::uuid,
                    (v_take ->> 'item_id')::uuid, (v_take ->> 'number')::integer);
                IF app.stock_at(v_line.product_id, (v_take ->> 'unit_id')::uuid,
                        (v_take ->> 'item_id')::uuid, (v_take ->> 'number')::integer)
                    < v_line.quantity THEN
                    RAISE EXCEPTION 'An Item is not in stock at that place; the Quotation waits'
                        USING ERRCODE = '55000';
                END IF;
                v_number := app.take_document_number('STOCK_MOVEMENT',
                    date_part('year', v_day)::integer);
                INSERT INTO app.product_transactions (movement_number, product_id, kind, quantity,
                    unit_id, place_item_id, place_number, reason, business_date, recorded_by,
                    correlation_id, quotation_id, quotation_line)
                VALUES (v_number, v_line.product_id, 'SALE', v_line.quantity,
                    (v_take ->> 'unit_id')::uuid, (v_take ->> 'item_id')::uuid,
                    (v_take ->> 'number')::integer,
                    'Quotation ' || v_quotation.quotation_number || ' · '
                        || (v_issued ->> 'invoice_number'),
                    v_day, p_actor, v_correlation, p_quotation, v_line.line_position);
            END LOOP;
            PERFORM app.product_audit(p_property, p_actor, v_day, 'quotation.signed', 'quotation',
                p_quotation, 'Customer signed', 'quotations.make',
                jsonb_build_object('status', 'WAITING'),
                jsonb_build_object('status', 'SIGNED', 'invoice_id', v_invoice,
                    'invoice_number', v_issued ->> 'invoice_number'),
                v_correlation);
            RETURN app.quotation_json(p_quotation);
        END $$;

        -- 4. A voided Invoice from a Quotation puts its Items back where they were taken from.
        CREATE FUNCTION app.return_quotation_stock() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_quotation app.quotations%ROWTYPE;
            v_sale record;
            v_day date;
        BEGIN
            SELECT quotation.* INTO v_quotation FROM app.quotations AS quotation
            WHERE quotation.invoice_id = NEW.id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_day
            FROM app.properties AS property WHERE property.id = v_quotation.property_id;
            FOR v_sale IN
                SELECT sale.* FROM app.product_transactions AS sale
                WHERE sale.quotation_id = v_quotation.id AND sale.kind = 'SALE'
                  AND NOT EXISTS (SELECT 1 FROM app.product_transactions AS back
                                  WHERE back.quotation_id = v_quotation.id
                                    AND back.kind = 'SALE_RETURN'
                                    AND back.quotation_line = sale.quotation_line)
                ORDER BY sale.quotation_line
            LOOP
                INSERT INTO app.product_transactions (movement_number, product_id, kind, quantity,
                    unit_id, place_item_id, place_number, reason, business_date, recorded_by,
                    correlation_id, quotation_id, quotation_line)
                VALUES (app.take_document_number('STOCK_MOVEMENT', date_part('year', v_day)::integer),
                    v_sale.product_id, 'SALE_RETURN', v_sale.quantity, v_sale.unit_id,
                    v_sale.place_item_id, v_sale.place_number,
                    'Invoice ' || NEW.invoice_number || ' voided', v_day,
                    NEW.updated_by, gen_random_uuid(), v_quotation.id, v_sale.quotation_line);
            END LOOP;
            RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION app.return_quotation_stock() FROM PUBLIC;
        CREATE TRIGGER invoices_return_quotation_stock AFTER UPDATE OF status ON app.invoices
            FOR EACH ROW WHEN (NEW.status = 'VOID' AND OLD.status IS DISTINCT FROM 'VOID')
            EXECUTE FUNCTION app.return_quotation_stock();

        -- 6. The Regular services become Service products (no cost yet).
        INSERT INTO app.products (property_id, sku, name_en, name_kh, category_id, measure_unit,
            mark_up_basis_points, min_mark_up_basis_points, max_mark_up_basis_points,
            created_by, updated_by)
        SELECT service.property_id,
            'P' || lpad(nextval('app.product_sku_numbers')::text, 4, '0'),
            service.name_en, service.name_km, category.id, 'TIME',
            app.product_rule('PRODUCT_MARK_UP', CURRENT_DATE),
            least(app.product_rule('PRODUCT_MIN_MARK_UP', CURRENT_DATE),
                app.product_rule('PRODUCT_MARK_UP', CURRENT_DATE)),
            CASE WHEN app.product_rule('PRODUCT_MAX_MARK_UP', CURRENT_DATE) IS NULL THEN NULL
                 ELSE greatest(app.product_rule('PRODUCT_MAX_MARK_UP', CURRENT_DATE),
                     app.product_rule('PRODUCT_MARK_UP', CURRENT_DATE)) END,
            service.created_by, service.created_by
        FROM (SELECT * FROM app.regular_services ORDER BY created_at, id) AS service
        JOIN app.product_categories AS category ON category.code = 'SERVICES'
        WHERE service.removed_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM app.products AS product
                          WHERE product.property_id = service.property_id
                            AND lower(product.name_en) = lower(service.name_en));

        REVOKE ALL ON TABLE app.quotations, app.quotation_lines FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.quotations, app.quotation_lines TO prm_runtime;
        """
    )
    for signature in (
        "app.quotations_read(uuid, uuid)",
        "app.quotation_read(uuid, uuid, uuid)",
        "app.make_quotation(uuid, uuid, uuid, text, uuid, text, jsonb, uuid, uuid)",
        "app.refuse_quotation(uuid, uuid, integer, text, uuid, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    sign = "app.sign_quotation(uuid, uuid, integer, date, jsonb, uuid, uuid)"
    op.execute(f"REVOKE ALL ON FUNCTION {sign} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {sign} TO prm_financial")

    _patch(
        INCOME_FACTS,
        ((INCOME_BEFORE, INCOME_AFTER),),
    )
    # 7. New Properties: Staff sees Quotations; the Owner and Manager get every bundle right.
    _patch(
        SEED,
        (
            (
                STAFF_BEFORE,
                "'stock.purchase', 'stock.transfer', "
                + ", ".join(_text(name) for name in STAFF)
                + "]::text[]",
            ),
        ),
    )
    every = _array(OWNER)
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
    raise RuntimeError("V1.1 part 6 migration is forward-only")
