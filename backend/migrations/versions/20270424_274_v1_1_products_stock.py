# ruff: noqa: E501
"""V1.1 part 4 (owner 2026-11-03 "Continue your task"): Products, prices and stock.

The plan of 01/11/2026 part 4 and the owner's answers of 30/10, 31/10 and 01/11/2026 (mock-up
rounds 16 to 19, DESIGN.md "Products, stock and Quotations" and round 19 "Product prices").

1. ``product_categories`` (Item or Service; Furniture, Appliances, Bedding supplies, Keys and
   locks, Services) and ``products``: SKU made by the app (P0001), names in English and Khmer,
   description, category, measure unit, cost, mark-up, minimum and maximum mark-up (copied from
   the business rules when the product is added), price, reorder level and quantity (Items
   only) and Discontinued. A product is never deleted.
2. Prices (round 19): the cost of an Item is its last Purchase cost; a Service's cost is typed.
   The price is cost x (1 + mark-up), rounded up to the PRICE_ROUND_UP step. A Purchase or a
   new Service cost sets the price again when there is no price yet or when the real mark-up is
   below the minimum or above the maximum; a mark-up change always sets it again. No approval.
   Every price is kept in ``product_price_history``.
3. ``product_transactions`` are append-only: Purchase, Adjustment in, Adjustment out, Transfer
   out and Transfer in (a transfer is a pair with one SM number); Sale comes with the Quotation
   (part 6). Stock is kept at a place in a Unit (a Location: the Unit, one of its Unit features
   and its number, such as Warehouse W01 Cabinet 1) and never goes below 0. Only Items have
   stock; a discontinued product cannot be bought again but its stock can still move. A place
   that holds stock cannot be removed from its Unit.
4. Stock movement numbers SMyy000n in ``number_rules``.
5. New rights: products.read, products.manage, products.prices, stock.purchase, stock.transfer
   and stock.adjust, in five new permissions of the Property group. The Owner role gets them
   all; the Manager role all but products.prices (the Owner sets mark-ups, round 19); the Staff
   role products.read, stock.purchase and stock.transfer.

Not in this part: the ledger entries for stock (the ledger posts them later), Sale and the
Quotation (part 6), the Unit inventory form (part 5), and moving the Regular services into
Service products (part 6, when Create Invoice changes). Technical choices by Claude under the
owner's 2026-10-23 22:30 rule; the price rule is the owner's (round 19).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270424_274"
down_revision: str | None = "20270423_273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-products"
CAPABILITIES = (
    ("products.read", "See products, stock and Locations"),
    ("products.manage", "Add and change products, Service costs and places"),
    ("products.prices", "Change product mark-ups"),
    ("stock.purchase", "Record a Purchase"),
    ("stock.transfer", "Move stock between places"),
    ("stock.adjust", "Adjust stock in or out"),
)
PERMISSIONS = (
    ("PRODUCTS_OPEN", "Open Products, stock and Locations", "បើកផលិតផល ស្តុក និងទីតាំង", ("products.read",)),
    ("PRODUCTS_MANAGE", "Add and change products, Service costs and places", "បន្ថែម និងកែផលិតផល ថ្លៃដើមសេវា និងកន្លែង", ("products.manage",)),
    ("PRODUCT_PRICES", "Change product mark-ups", "ប្ដូរការបូកបន្ថែមលើផលិតផល", ("products.prices",)),
    ("STOCK_MOVE", "Record purchases and move stock", "កត់ត្រាការទិញ និងផ្លាស់ទីស្តុក", ("stock.purchase", "stock.transfer")),
    ("STOCK_ADJUST", "Adjust stock in or out", "កែតម្រូវស្តុកចូល ឬចេញ", ("stock.adjust",)),
)
MANAGER = ("products.read", "products.manage", "stock.purchase", "stock.transfer", "stock.adjust")
STAFF = ("products.read", "stock.purchase", "stock.transfer")
REASON = "Owner plan 2026-11-01 part 4: products and stock rights"

CATEGORIES = (
    ("FURNITURE", "Furniture", "គ្រឿងសង្ហារិម", "ITEM"),
    ("APPLIANCES", "Appliances", "គ្រឿងអគ្គិសនី", "ITEM"),
    ("BEDDING", "Bedding supplies", "គ្រឿងគេង", "ITEM"),
    ("KEYS", "Keys and locks", "សោ និងគន្លឹះ", "ITEM"),
    ("SERVICES", "Services", "សេវាកម្ម", "SERVICE"),
)
# Count, measure, packaging and service units (round 16); whole numbers except the measures.
MEASURE_UNITS = (
    "PIECE", "SET", "PAIR", "METRE", "KILOGRAM", "LITRE", "BOX", "PACK", "BOTTLE",
    "TIME", "HOUR", "BAG",
)
PART_UNITS = ("METRE", "KILOGRAM", "LITRE", "HOUR")

SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'utility_readings.record']::text[]"
OWNER_ONLY_BEFORE = "'ledger.write_off']::text[]"


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
    permission_rows = ",\n            ".join(
        f"({_text(code)}, 'PROPERTY', (SELECT max(sort_order) FROM app.permissions) + 1, "
        f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        for code, en, kh, _names in PERMISSIONS
    )
    mapping_rows = ",\n            ".join(
        f"({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        for code, _en, _kh, names in PERMISSIONS
        for name in names
    )
    category_rows = ",\n            ".join(
        f"({_text(code)}, {_text(en)}, {_text(kh)}, '{kind}', {number})"
        for number, (code, en, kh, kind) in enumerate(CATEGORIES, start=1)
    )
    every = _array([name for name, _ in CAPABILITIES])
    op.execute(
        f"""
        -- 5. The rights and their permissions.
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES
            {capability_rows};
        -- One statement per row: each reads the largest sort order so far.
        """
    )
    for row in permission_rows.split(",\n            "):
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES {row}"
        )
    op.execute(
        f"""
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES
            {mapping_rows};

        -- 1. Categories and products.
        CREATE TABLE app.product_categories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z_]{{1,29}}$'),
            name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
            name_kh text NOT NULL CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 80),
            kind text NOT NULL CHECK (kind IN ('ITEM', 'SERVICE')),
            sort_order integer NOT NULL UNIQUE CHECK (sort_order > 0)
        );
        INSERT INTO app.product_categories (code, name_en, name_kh, kind, sort_order) VALUES
            {category_rows};
        CREATE FUNCTION app.product_categories_are_fixed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR NEW.kind <> OLD.kind OR NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'A product category keeps its code and kind' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.product_categories_are_fixed() FROM PUBLIC;
        CREATE TRIGGER product_categories_fixed BEFORE UPDATE OR DELETE ON app.product_categories
            FOR EACH ROW EXECUTE FUNCTION app.product_categories_are_fixed();

        CREATE SEQUENCE app.product_sku_numbers AS integer START 1;
        CREATE TABLE app.products (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
            sku text NOT NULL UNIQUE CHECK (sku ~ '^P[0-9]{{4,}}$'),
            name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 120),
            name_kh text CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 120),
            description text CHECK (description = btrim(description) AND length(description) BETWEEN 1 AND 500),
            category_id uuid NOT NULL REFERENCES app.product_categories (id) ON DELETE RESTRICT,
            measure_unit text NOT NULL CHECK (measure_unit IN ({", ".join(_text(unit) for unit in MEASURE_UNITS)})),
            cost_usd_cents bigint CHECK (cost_usd_cents > 0),
            mark_up_basis_points integer NOT NULL CHECK (mark_up_basis_points BETWEEN 0 AND 100000),
            min_mark_up_basis_points integer NOT NULL CHECK (min_mark_up_basis_points BETWEEN 0 AND 100000),
            max_mark_up_basis_points integer CHECK (max_mark_up_basis_points BETWEEN 0 AND 100000),
            price_usd_cents bigint CHECK (price_usd_cents > 0),
            reorder_level integer CHECK (reorder_level >= 0),
            reorder_quantity integer CHECK (reorder_quantity > 0),
            discontinued boolean NOT NULL DEFAULT false,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            CONSTRAINT products_mark_up_in_range CHECK (
                min_mark_up_basis_points <= mark_up_basis_points
                AND (max_mark_up_basis_points IS NULL OR mark_up_basis_points <= max_mark_up_basis_points)),
            CONSTRAINT products_price_needs_cost CHECK (price_usd_cents IS NULL OR cost_usd_cents IS NOT NULL)
        );
        CREATE UNIQUE INDEX products_name_once ON app.products (property_id, lower(name_en));
        CREATE INDEX products_category_idx ON app.products (category_id);
        COMMENT ON TABLE app.products IS
            'V1.1 part 4 (DL-121): products and services; never deleted, Discontinued instead.';

        CREATE FUNCTION app.products_are_never_deleted() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A product is never deleted; it can be Discontinued' USING ERRCODE = '55000';
            END IF;
            IF NEW.id <> OLD.id OR NEW.sku <> OLD.sku OR NEW.property_id <> OLD.property_id
                OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by
                OR NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'A product changes only by its next version' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.products_are_never_deleted() FROM PUBLIC;
        CREATE TRIGGER products_change_by_version BEFORE UPDATE OR DELETE ON app.products
            FOR EACH ROW EXECUTE FUNCTION app.products_are_never_deleted();

        -- 2. Every price a product had.
        CREATE TABLE app.product_price_history (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id uuid NOT NULL REFERENCES app.products (id) ON DELETE RESTRICT,
            price_usd_cents bigint NOT NULL CHECK (price_usd_cents > 0),
            cost_usd_cents bigint NOT NULL CHECK (cost_usd_cents > 0),
            mark_up_basis_points integer NOT NULL,
            cause text NOT NULL CHECK (cause IN ('PURCHASE', 'SERVICE_COST', 'MARK_UP')),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
        );
        CREATE INDEX product_price_history_product_idx
            ON app.product_price_history (product_id, created_at DESC);

        -- 3. Stock movements.
        CREATE TABLE app.product_transactions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            movement_number text NOT NULL CHECK (movement_number ~ '^[A-Z]{{2,5}}[0-9]{{6,}}$'),
            product_id uuid NOT NULL REFERENCES app.products (id) ON DELETE RESTRICT,
            kind text NOT NULL CHECK (kind IN ('PURCHASE', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT',
                'TRANSFER_OUT', 'TRANSFER_IN')),
            quantity numeric(12, 3) NOT NULL CHECK (quantity > 0),
            unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
            place_item_id uuid NOT NULL REFERENCES app.unit_setup_items (id) ON DELETE RESTRICT,
            place_number smallint NOT NULL CHECK (place_number BETWEEN 1 AND 9),
            unit_cost_usd_cents bigint CHECK (unit_cost_usd_cents > 0),
            supplier text CHECK (supplier = btrim(supplier) AND length(supplier) BETWEEN 1 AND 200),
            receipt_reference text CHECK (receipt_reference = btrim(receipt_reference)
                AND length(receipt_reference) BETWEEN 1 AND 100),
            reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            business_date date NOT NULL,
            recorded_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
            correlation_id uuid NOT NULL,
            CONSTRAINT product_transactions_purchase_has_cost
                CHECK ((kind = 'PURCHASE') = (unit_cost_usd_cents IS NOT NULL)),
            CONSTRAINT product_transactions_adjustment_has_reason
                CHECK (kind NOT IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT') OR reason IS NOT NULL),
            CONSTRAINT product_transactions_one_side_per_number UNIQUE (movement_number, kind)
        );
        CREATE INDEX product_transactions_place_idx
            ON app.product_transactions (unit_id, place_item_id, place_number, product_id);
        CREATE INDEX product_transactions_product_idx
            ON app.product_transactions (product_id, recorded_at DESC);
        CREATE INDEX product_transactions_recorded_idx ON app.product_transactions (recorded_at DESC);
        COMMENT ON TABLE app.product_transactions IS
            'V1.1 part 4 (DL-121): append-only stock movements; a mistake is fixed with an Adjustment.';

        CREATE FUNCTION app.reject_product_history_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Stock movements and prices are never changed or removed'
                USING ERRCODE = '55000';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_product_history_change() FROM PUBLIC;
        CREATE TRIGGER product_transactions_append_only
            BEFORE UPDATE OR DELETE ON app.product_transactions
            FOR EACH ROW EXECUTE FUNCTION app.reject_product_history_change();
        CREATE TRIGGER product_transactions_no_truncate BEFORE TRUNCATE ON app.product_transactions
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_product_history_change();
        CREATE TRIGGER product_price_history_append_only
            BEFORE UPDATE OR DELETE ON app.product_price_history
            FOR EACH ROW EXECUTE FUNCTION app.reject_product_history_change();
        CREATE TRIGGER product_price_history_no_truncate BEFORE TRUNCATE ON app.product_price_history
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_product_history_change();

        REVOKE ALL ON TABLE app.product_categories, app.products, app.product_price_history,
            app.product_transactions FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.product_categories, app.products, app.product_price_history,
            app.product_transactions TO prm_runtime;
        REVOKE ALL ON SEQUENCE app.product_sku_numbers FROM PUBLIC;

        -- How much of a product is at a place now.
        CREATE FUNCTION app.stock_at(p_product uuid, p_unit uuid, p_item uuid, p_number integer)
        RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT COALESCE(sum(CASE WHEN movement.kind IN ('PURCHASE', 'ADJUSTMENT_IN', 'TRANSFER_IN')
                                     THEN movement.quantity ELSE -movement.quantity END), 0)
            FROM app.product_transactions AS movement
            WHERE movement.product_id = p_product AND movement.unit_id = p_unit
              AND movement.place_item_id = p_item AND movement.place_number = p_number
        $$;
        REVOKE ALL ON FUNCTION app.stock_at(uuid, uuid, uuid, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.stock_at(uuid, uuid, uuid, integer) TO prm_runtime;

        -- A place that holds stock stays in its Unit.
        CREATE FUNCTION app.keep_places_with_stock() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_count integer := CASE WHEN TG_OP = 'DELETE' THEN 0 ELSE NEW.feature_count END;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.product_transactions AS movement
                WHERE movement.unit_id = OLD.unit_id AND movement.place_item_id = OLD.item_id
                  AND movement.place_number > v_count
                GROUP BY movement.product_id, movement.place_number
                HAVING sum(CASE WHEN movement.kind IN ('PURCHASE', 'ADJUSTMENT_IN', 'TRANSFER_IN')
                                THEN movement.quantity ELSE -movement.quantity END) <> 0
            ) THEN
                RAISE EXCEPTION 'A place that holds stock cannot be removed; move the stock first'
                    USING ERRCODE = '55000';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        REVOKE ALL ON FUNCTION app.keep_places_with_stock() FROM PUBLIC;
        CREATE TRIGGER unit_features_keep_places_with_stock
            BEFORE UPDATE OF feature_count OR DELETE ON app.unit_features
            FOR EACH ROW EXECUTE FUNCTION app.keep_places_with_stock();

        -- The price rule (round 19).
        CREATE FUNCTION app.product_rule(p_code text, p_on date)
        RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT CASE p_code
                WHEN 'PRODUCT_MAX_MARK_UP' THEN app.business_rule_value(p_code, p_on)
                ELSE COALESCE(app.business_rule_value(p_code, p_on),
                    CASE p_code WHEN 'PRODUCT_MARK_UP' THEN 2000
                                WHEN 'PRODUCT_MIN_MARK_UP' THEN 1500
                                WHEN 'PRICE_ROUND_UP' THEN 10 END)
                END::integer
            WHERE p_code IN ('PRODUCT_MARK_UP', 'PRODUCT_MIN_MARK_UP', 'PRODUCT_MAX_MARK_UP',
                'PRICE_ROUND_UP')
        $$;
        REVOKE ALL ON FUNCTION app.product_rule(text, date) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.product_rule(text, date) TO prm_runtime;

        CREATE FUNCTION app.product_price_for(p_cost bigint, p_mark_up integer, p_step integer)
        RETURNS bigint LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT (ceil(p_cost::numeric * (10000 + p_mark_up)
                         / (10000::numeric * greatest(COALESCE(p_step, 1), 1)))
                    * greatest(COALESCE(p_step, 1), 1))::bigint
        $$;
        REVOKE ALL ON FUNCTION app.product_price_for(bigint, integer, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.product_price_for(bigint, integer, integer) TO prm_runtime;

        -- The real mark-up of a price over a cost, in basis points (rounded down).
        CREATE FUNCTION app.real_mark_up(p_price bigint, p_cost bigint)
        RETURNS integer LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT floor((p_price - p_cost)::numeric * 10000 / p_cost)::integer
        $$;
        REVOKE ALL ON FUNCTION app.real_mark_up(bigint, bigint) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.real_mark_up(bigint, bigint) TO prm_runtime;

        -- Rights, Property and the business day of one change.
        CREATE FUNCTION app.require_product_right(p_actor uuid, p_capability text, p_property uuid)
        RETURNS date LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_actor IS NULL OR NOT EXISTS (
                SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
                WHERE held.capability_id = p_capability AND held.property_id = p_property
            ) THEN
                RAISE EXCEPTION 'this account may not do this' USING ERRCODE = '42501';
            END IF;
            RETURN timezone(v_timezone, statement_timestamp())::date;
        END $$;
        REVOKE ALL ON FUNCTION app.require_product_right(uuid, text, uuid) FROM PUBLIC;

        CREATE FUNCTION app.product_audit(p_property uuid, p_actor uuid, p_day date, p_action text,
            p_entity_type text, p_entity uuid, p_reason text, p_right text, p_before jsonb,
            p_after jsonb, p_correlation uuid)
        RETURNS void LANGUAGE sql SET search_path = pg_catalog AS $$
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), statement_timestamp(), p_day, p_actor, p_action,
                p_entity_type, p_entity, p_reason, p_right, p_property, p_before, p_after,
                COALESCE(p_correlation, gen_random_uuid()), 'API', 'SUCCEEDED')
        $$;
        REVOKE ALL ON FUNCTION app.product_audit(uuid, uuid, date, text, text, uuid, text, text,
            jsonb, jsonb, uuid) FROM PUBLIC;

        -- Sets the price again from the cost and the mark-up; keeps it in the history.
        CREATE FUNCTION app.reprice_product(p_product uuid, p_cause text, p_actor uuid, p_day date)
        RETURNS bigint LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_product app.products%ROWTYPE;
            v_price bigint;
        BEGIN
            SELECT product.* INTO STRICT v_product FROM app.products AS product
            WHERE product.id = p_product;
            IF v_product.cost_usd_cents IS NULL THEN
                RETURN v_product.price_usd_cents;
            END IF;
            -- A Purchase or a new Service cost sets the price only when there is none or the
            -- real mark-up left its range; a mark-up change always sets it.
            IF p_cause <> 'MARK_UP' AND v_product.price_usd_cents IS NOT NULL
                AND app.real_mark_up(v_product.price_usd_cents, v_product.cost_usd_cents)
                    >= v_product.min_mark_up_basis_points
                AND (v_product.max_mark_up_basis_points IS NULL
                     OR app.real_mark_up(v_product.price_usd_cents, v_product.cost_usd_cents)
                        <= v_product.max_mark_up_basis_points) THEN
                RETURN v_product.price_usd_cents;
            END IF;
            v_price := app.product_price_for(v_product.cost_usd_cents,
                v_product.mark_up_basis_points, app.product_rule('PRICE_ROUND_UP', p_day));
            IF v_price IS DISTINCT FROM v_product.price_usd_cents THEN
                UPDATE app.products AS product
                SET price_usd_cents = v_price, version = product.version + 1,
                    updated_at = statement_timestamp(), updated_by = p_actor
                WHERE product.id = p_product;
                INSERT INTO app.product_price_history (product_id, price_usd_cents, cost_usd_cents,
                    mark_up_basis_points, cause, created_by)
                VALUES (p_product, v_price, v_product.cost_usd_cents,
                    v_product.mark_up_basis_points, p_cause, p_actor);
            END IF;
            RETURN v_price;
        END $$;
        REVOKE ALL ON FUNCTION app.reprice_product(uuid, text, uuid, date) FROM PUBLIC;

        CREATE FUNCTION app.product_category_kind(p_code text)
        RETURNS text LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
        DECLARE v_kind text;
        BEGIN
            SELECT category.kind INTO v_kind FROM app.product_categories AS category
            WHERE category.code = p_code;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No product category has this code' USING ERRCODE = '22023';
            END IF;
            RETURN v_kind;
        END $$;
        REVOKE ALL ON FUNCTION app.product_category_kind(text) FROM PUBLIC;

        CREATE FUNCTION app.check_product_fields(p_kind text, p_measure_unit text,
            p_reorder_level integer, p_reorder_quantity integer)
        RETURNS void LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
        BEGIN
            IF p_kind = 'SERVICE' AND (p_reorder_level IS NOT NULL OR p_reorder_quantity IS NOT NULL) THEN
                RAISE EXCEPTION 'A Service has no reorder level' USING ERRCODE = '22023';
            END IF;
            IF (p_kind = 'SERVICE') <> (p_measure_unit IN ('TIME', 'HOUR', 'BAG')) THEN
                RAISE EXCEPTION 'A Service is counted in times, hours or bags, and an Item is not'
                    USING ERRCODE = '22023';
            END IF;
        END $$;
        REVOKE ALL ON FUNCTION app.check_product_fields(text, text, integer, integer) FROM PUBLIC;

        CREATE FUNCTION app.create_product(p_property uuid, p_name_en text, p_name_kh text,
            p_description text, p_category text, p_measure_unit text, p_reorder_level integer,
            p_reorder_quantity integer, p_service_cost bigint, p_actor uuid, p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_day date := app.require_product_right(p_actor, 'products.manage', p_property);
            v_kind text := app.product_category_kind(p_category);
            v_id uuid := gen_random_uuid();
            v_mark_up integer;
            v_min integer;
            v_max integer;
        BEGIN
            PERFORM app.check_product_fields(v_kind, p_measure_unit, p_reorder_level,
                p_reorder_quantity);
            IF v_kind = 'ITEM' AND p_service_cost IS NOT NULL THEN
                RAISE EXCEPTION 'An Item gets its cost from its Purchases' USING ERRCODE = '22023';
            END IF;
            -- Each product starts with the business rules' mark-ups, kept in range.
            v_mark_up := app.product_rule('PRODUCT_MARK_UP', v_day);
            v_min := least(app.product_rule('PRODUCT_MIN_MARK_UP', v_day), v_mark_up);
            v_max := app.product_rule('PRODUCT_MAX_MARK_UP', v_day);
            IF v_max IS NOT NULL THEN
                v_max := greatest(v_max, v_mark_up);
            END IF;
            INSERT INTO app.products (id, property_id, sku, name_en, name_kh, description,
                category_id, measure_unit, cost_usd_cents, mark_up_basis_points,
                min_mark_up_basis_points, max_mark_up_basis_points, reorder_level,
                reorder_quantity, created_by, updated_by)
            SELECT v_id, p_property, 'P' || lpad(nextval('app.product_sku_numbers')::text, 4, '0'),
                p_name_en, p_name_kh, p_description, category.id, p_measure_unit, p_service_cost,
                v_mark_up, v_min, v_max, p_reorder_level, p_reorder_quantity, p_actor, p_actor
            FROM app.product_categories AS category WHERE category.code = p_category;
            IF p_service_cost IS NOT NULL THEN
                PERFORM app.reprice_product(v_id, 'SERVICE_COST', p_actor, v_day);
            END IF;
            PERFORM app.product_audit(p_property, p_actor, v_day, 'product.created', 'product',
                v_id, 'Product added', 'products.manage', NULL,
                jsonb_build_object('name_en', p_name_en, 'category', p_category,
                    'measure_unit', p_measure_unit, 'cost_usd_cents', p_service_cost),
                p_correlation);
            RETURN v_id;
        END $$;

        CREATE FUNCTION app.change_product(p_product uuid, p_expected_version integer,
            p_name_en text, p_name_kh text, p_description text, p_category text,
            p_measure_unit text, p_reorder_level integer, p_reorder_quantity integer,
            p_discontinued boolean, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_product app.products%ROWTYPE;
            v_old_kind text;
            v_kind text := app.product_category_kind(p_category);
            v_day date;
        BEGIN
            SELECT product.* INTO v_product FROM app.products AS product
            WHERE product.id = p_product FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the product does not exist' USING ERRCODE = '22023';
            END IF;
            v_day := app.require_product_right(p_actor, 'products.manage', v_product.property_id);
            IF p_expected_version IS DISTINCT FROM v_product.version THEN
                RAISE EXCEPTION 'the product changed since it was read' USING ERRCODE = '40001';
            END IF;
            IF p_discontinued IS NULL THEN
                RAISE EXCEPTION 'Discontinued is Yes or No' USING ERRCODE = '22023';
            END IF;
            SELECT category.kind INTO v_old_kind FROM app.product_categories AS category
            WHERE category.id = v_product.category_id;
            IF v_old_kind <> v_kind THEN
                RAISE EXCEPTION 'An Item stays an Item and a Service stays a Service'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM app.check_product_fields(v_kind, p_measure_unit, p_reorder_level,
                p_reorder_quantity);
            IF p_measure_unit <> v_product.measure_unit AND EXISTS (
                SELECT 1 FROM app.product_transactions AS movement WHERE movement.product_id = p_product
            ) THEN
                RAISE EXCEPTION 'The measure unit stays once stock has moved' USING ERRCODE = '22023';
            END IF;
            UPDATE app.products AS product
            SET name_en = p_name_en, name_kh = p_name_kh, description = p_description,
                category_id = (SELECT category.id FROM app.product_categories AS category
                               WHERE category.code = p_category),
                measure_unit = p_measure_unit, reorder_level = p_reorder_level,
                reorder_quantity = p_reorder_quantity, discontinued = p_discontinued,
                version = product.version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor
            WHERE product.id = p_product;
            PERFORM app.product_audit(v_product.property_id, p_actor, v_day, 'product.changed',
                'product', p_product, 'Product changed', 'products.manage',
                jsonb_build_object('version', v_product.version, 'name_en', v_product.name_en,
                    'discontinued', v_product.discontinued),
                jsonb_build_object('version', v_product.version + 1, 'name_en', p_name_en,
                    'discontinued', p_discontinued),
                p_correlation);
            RETURN v_product.version + 1;
        END $$;

        CREATE FUNCTION app.set_product_mark_ups(p_product uuid, p_expected_version integer,
            p_mark_up integer, p_min integer, p_max integer, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_product app.products%ROWTYPE;
            v_day date;
        BEGIN
            SELECT product.* INTO v_product FROM app.products AS product
            WHERE product.id = p_product FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the product does not exist' USING ERRCODE = '22023';
            END IF;
            v_day := app.require_product_right(p_actor, 'products.prices', v_product.property_id);
            IF p_expected_version IS DISTINCT FROM v_product.version THEN
                RAISE EXCEPTION 'the product changed since it was read' USING ERRCODE = '40001';
            END IF;
            IF p_mark_up IS NULL OR p_min IS NULL OR p_min > p_mark_up
                OR (p_max IS NOT NULL AND p_max < p_mark_up) THEN
                RAISE EXCEPTION 'The mark-up is between the minimum and the maximum'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE app.products AS product
            SET mark_up_basis_points = p_mark_up, min_mark_up_basis_points = p_min,
                max_mark_up_basis_points = p_max, version = product.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor
            WHERE product.id = p_product;
            PERFORM app.reprice_product(p_product, 'MARK_UP', p_actor, v_day);
            PERFORM app.product_audit(v_product.property_id, p_actor, v_day,
                'product.mark_up_changed', 'product', p_product, 'Mark-up changed',
                'products.prices',
                jsonb_build_object('mark_up', v_product.mark_up_basis_points,
                    'min', v_product.min_mark_up_basis_points,
                    'max', v_product.max_mark_up_basis_points,
                    'price_usd_cents', v_product.price_usd_cents),
                jsonb_build_object('mark_up', p_mark_up, 'min', p_min, 'max', p_max,
                    'price_usd_cents', (SELECT product.price_usd_cents FROM app.products AS product
                                        WHERE product.id = p_product)),
                p_correlation);
            RETURN (SELECT product.version FROM app.products AS product WHERE product.id = p_product);
        END $$;

        CREATE FUNCTION app.set_service_cost(p_product uuid, p_expected_version integer,
            p_cost bigint, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_product app.products%ROWTYPE;
            v_kind text;
            v_day date;
        BEGIN
            SELECT product.* INTO v_product FROM app.products AS product
            WHERE product.id = p_product FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the product does not exist' USING ERRCODE = '22023';
            END IF;
            v_day := app.require_product_right(p_actor, 'products.manage', v_product.property_id);
            IF p_expected_version IS DISTINCT FROM v_product.version THEN
                RAISE EXCEPTION 'the product changed since it was read' USING ERRCODE = '40001';
            END IF;
            SELECT category.kind INTO v_kind FROM app.product_categories AS category
            WHERE category.id = v_product.category_id;
            IF v_kind <> 'SERVICE' OR p_cost IS NULL OR p_cost <= 0 THEN
                RAISE EXCEPTION 'Only a Service has a typed cost, above 0' USING ERRCODE = '22023';
            END IF;
            UPDATE app.products AS product
            SET cost_usd_cents = p_cost, version = product.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor
            WHERE product.id = p_product;
            PERFORM app.reprice_product(p_product, 'SERVICE_COST', p_actor, v_day);
            PERFORM app.product_audit(v_product.property_id, p_actor, v_day,
                'product.service_cost_changed', 'product', p_product, 'Service cost changed',
                'products.manage', jsonb_build_object('cost_usd_cents', v_product.cost_usd_cents),
                jsonb_build_object('cost_usd_cents', p_cost), p_correlation);
            RETURN (SELECT product.version FROM app.products AS product WHERE product.id = p_product);
        END $$;

        -- A place of a Unit: one of its Unit features and its number.
        CREATE FUNCTION app.assert_place(p_property uuid, p_unit uuid, p_item uuid, p_number integer)
        RETURNS void LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
        BEGIN
            IF p_unit IS NULL OR p_item IS NULL OR p_number IS NULL OR NOT EXISTS (
                SELECT 1 FROM app.unit_features AS feature
                JOIN app.units AS unit ON unit.id = feature.unit_id
                WHERE feature.unit_id = p_unit AND feature.item_id = p_item
                  AND unit.property_id = p_property AND p_number BETWEEN 1 AND feature.feature_count
            ) THEN
                RAISE EXCEPTION 'This place is not in the Unit' USING ERRCODE = '22023';
            END IF;
        END $$;
        REVOKE ALL ON FUNCTION app.assert_place(uuid, uuid, uuid, integer) FROM PUBLIC;

        -- One stock movement: Purchase, Transfer, Adjustment in or Adjustment out. Answers its
        -- SM number.
        CREATE FUNCTION app.record_stock_movement(p_property uuid, p_kind text, p_product uuid,
            p_quantity numeric, p_from_unit uuid, p_from_item uuid, p_from_number integer,
            p_to_unit uuid, p_to_item uuid, p_to_number integer, p_unit_cost bigint,
            p_supplier text, p_receipt_reference text, p_reason text, p_actor uuid,
            p_correlation uuid)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_right text := CASE p_kind WHEN 'PURCHASE' THEN 'stock.purchase'
                                        WHEN 'TRANSFER' THEN 'stock.transfer'
                                        WHEN 'ADJUSTMENT_IN' THEN 'stock.adjust'
                                        WHEN 'ADJUSTMENT_OUT' THEN 'stock.adjust' END;
            v_day date;
            v_product app.products%ROWTYPE;
            v_kind text;
            v_number text;
            v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
        BEGIN
            IF v_right IS NULL THEN
                RAISE EXCEPTION 'Unknown kind of stock movement' USING ERRCODE = '22023';
            END IF;
            v_day := app.require_product_right(p_actor, v_right, p_property);
            -- One movement of a product at a time, so stock never goes below 0.
            SELECT product.* INTO v_product FROM app.products AS product
            WHERE product.id = p_product AND product.property_id = p_property FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the product does not exist' USING ERRCODE = '22023';
            END IF;
            SELECT category.kind INTO v_kind FROM app.product_categories AS category
            WHERE category.id = v_product.category_id;
            IF v_kind <> 'ITEM' THEN
                RAISE EXCEPTION 'A Service has no stock' USING ERRCODE = '22023';
            END IF;
            IF p_quantity IS NULL OR p_quantity <= 0 OR p_quantity <> round(p_quantity, 3)
                OR (v_product.measure_unit NOT IN ({", ".join(_text(unit) for unit in PART_UNITS)})
                    AND p_quantity <> trunc(p_quantity)) THEN
                RAISE EXCEPTION 'The quantity is above 0 and whole for this unit'
                    USING ERRCODE = '22023';
            END IF;
            IF p_kind IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT')
                AND (p_reason IS NULL OR btrim(p_reason) = '') THEN
                RAISE EXCEPTION 'An Adjustment needs a reason' USING ERRCODE = '22023';
            END IF;
            IF p_kind = 'PURCHASE' THEN
                IF v_product.discontinued THEN
                    RAISE EXCEPTION 'A discontinued product cannot be bought again'
                        USING ERRCODE = '55000';
                END IF;
                IF p_unit_cost IS NULL OR p_unit_cost <= 0 THEN
                    RAISE EXCEPTION 'A Purchase needs its cost' USING ERRCODE = '22023';
                END IF;
            ELSIF p_unit_cost IS NOT NULL OR p_supplier IS NOT NULL OR p_receipt_reference IS NOT NULL THEN
                RAISE EXCEPTION 'Only a Purchase has a cost, a supplier and a receipt'
                    USING ERRCODE = '22023';
            END IF;
            IF p_kind IN ('TRANSFER', 'ADJUSTMENT_OUT') THEN
                PERFORM app.assert_place(p_property, p_from_unit, p_from_item, p_from_number);
                IF app.stock_at(p_product, p_from_unit, p_from_item, p_from_number) < p_quantity THEN
                    RAISE EXCEPTION 'There is not enough stock at this place' USING ERRCODE = '55000';
                END IF;
            ELSIF p_from_unit IS NOT NULL OR p_from_item IS NOT NULL OR p_from_number IS NOT NULL THEN
                RAISE EXCEPTION 'Only a Transfer or an Adjustment out takes from a place'
                    USING ERRCODE = '22023';
            END IF;
            IF p_kind IN ('TRANSFER', 'PURCHASE', 'ADJUSTMENT_IN') THEN
                PERFORM app.assert_place(p_property, p_to_unit, p_to_item, p_to_number);
            ELSIF p_to_unit IS NOT NULL OR p_to_item IS NOT NULL OR p_to_number IS NOT NULL THEN
                RAISE EXCEPTION 'An Adjustment out puts nothing in a place' USING ERRCODE = '22023';
            END IF;
            IF p_kind = 'TRANSFER' AND p_from_unit = p_to_unit AND p_from_item = p_to_item
                AND p_from_number = p_to_number THEN
                RAISE EXCEPTION 'A Transfer goes to another place' USING ERRCODE = '22023';
            END IF;
            v_number := app.take_document_number('STOCK_MOVEMENT',
                date_part('year', v_day)::integer);
            IF p_kind IN ('TRANSFER', 'ADJUSTMENT_OUT') THEN
                INSERT INTO app.product_transactions (movement_number, product_id, kind, quantity,
                    unit_id, place_item_id, place_number, reason, business_date, recorded_by,
                    correlation_id)
                VALUES (v_number, p_product,
                    CASE p_kind WHEN 'TRANSFER' THEN 'TRANSFER_OUT' ELSE 'ADJUSTMENT_OUT' END,
                    p_quantity, p_from_unit, p_from_item, p_from_number, NULLIF(btrim(p_reason), ''),
                    v_day, p_actor, v_correlation);
            END IF;
            IF p_kind IN ('TRANSFER', 'PURCHASE', 'ADJUSTMENT_IN') THEN
                INSERT INTO app.product_transactions (movement_number, product_id, kind, quantity,
                    unit_id, place_item_id, place_number, unit_cost_usd_cents, supplier,
                    receipt_reference, reason, business_date, recorded_by, correlation_id)
                VALUES (v_number, p_product,
                    CASE p_kind WHEN 'TRANSFER' THEN 'TRANSFER_IN' ELSE p_kind END,
                    p_quantity, p_to_unit, p_to_item, p_to_number, p_unit_cost,
                    NULLIF(btrim(p_supplier), ''), NULLIF(btrim(p_receipt_reference), ''),
                    NULLIF(btrim(p_reason), ''), v_day, p_actor, v_correlation);
            END IF;
            IF p_kind = 'PURCHASE' THEN
                -- The cost is the last Purchase cost (owner 30/10/2026).
                UPDATE app.products AS product
                SET cost_usd_cents = p_unit_cost, version = product.version + 1,
                    updated_at = statement_timestamp(), updated_by = p_actor
                WHERE product.id = p_product;
                PERFORM app.reprice_product(p_product, 'PURCHASE', p_actor, v_day);
            END IF;
            PERFORM app.product_audit(p_property, p_actor, v_day, 'stock.movement_recorded',
                'product', p_product, COALESCE(NULLIF(btrim(p_reason), ''), 'Stock movement'),
                v_right, NULL,
                jsonb_build_object('movement_number', v_number, 'kind', p_kind,
                    'quantity', p_quantity, 'unit_cost_usd_cents', p_unit_cost),
                v_correlation);
            RETURN v_number;
        END $$;

        -- Add a place to a Unit (Locations › Add place): the next number of a Unit feature.
        CREATE FUNCTION app.add_unit_place(p_unit uuid, p_item uuid, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
            v_day date;
            v_count integer;
        BEGIN
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_unit FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
            END IF;
            v_day := app.require_product_right(p_actor, 'products.manage', v_unit.property_id);
            PERFORM app.assert_unit_setup_item(v_unit.property_id, 'UNIT_FEATURE', p_item);
            SELECT feature.feature_count INTO v_count FROM app.unit_features AS feature
            WHERE feature.unit_id = p_unit AND feature.item_id = p_item FOR UPDATE;
            IF COALESCE(v_count, 0) >= 9 THEN
                RAISE EXCEPTION 'A Unit has at most 9 of one place' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.unit_features AS feature (unit_id, item_id, feature_count)
            VALUES (p_unit, p_item, 1)
            ON CONFLICT (unit_id, item_id) DO UPDATE SET feature_count = feature.feature_count + 1;
            UPDATE app.units AS unit SET version = unit.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor
            WHERE unit.id = p_unit;
            PERFORM app.product_audit(v_unit.property_id, p_actor, v_day, 'unit.place_added',
                'unit', p_unit, 'Place added', 'products.manage', NULL,
                jsonb_build_object('item_id', p_item, 'number', COALESCE(v_count, 0) + 1),
                p_correlation);
            RETURN COALESCE(v_count, 0) + 1;
        END $$;

        -- 4. Stock movement numbers.
        INSERT INTO app.number_rules (document_type, year, last_number, format)
        SELECT 'STOCK_MOVEMENT', year, 0, 'SMyy000n'
        FROM (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
                  statement_timestamp()))::smallint AS year
              FROM app.properties AS property
              UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
        ON CONFLICT (document_type, year) DO NOTHING;
        """
    )
    for signature in (
        "app.create_product(uuid, text, text, text, text, text, integer, integer, bigint, uuid, uuid)",
        "app.change_product(uuid, integer, text, text, text, text, text, integer, integer, boolean, uuid, uuid)",
        "app.set_product_mark_ups(uuid, integer, integer, integer, integer, uuid, uuid)",
        "app.set_service_cost(uuid, integer, bigint, uuid, uuid)",
        "app.record_stock_movement(uuid, text, uuid, numeric, uuid, uuid, integer, uuid, uuid, integer, bigint, text, text, text, uuid, uuid)",
        "app.add_unit_place(uuid, uuid, uuid, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")

    # 5. New Properties: the Manager role does not get products.prices; Staff gets its three.
    _patch(
        SEED,
        (
            (STAFF_BEFORE, "'utility_readings.record', " + ", ".join(_text(n) for n in STAFF) + "]::text[]"),
            (OWNER_ONLY_BEFORE, "'ledger.write_off', 'products.prices']::text[]"),
        ),
    )
    manager = _array(MANAGER)
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
                        WHEN seeded.owner_bundle_id THEN {every}
                        WHEN seeded.manager_bundle_id THEN {manager}
                        ELSE {staff}
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
    raise RuntimeError("V1.1 part 4 migration is forward-only")
