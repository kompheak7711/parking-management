"""General Ledger starter chart of accounts and the 2027 fiscal year (PR-GL-001; owner Q4).

Revision ID: 20270412_262
Revises: 20270411_261
Create Date: 2026-11-02

Owner approved the ledger database plan on 2026-11-02 21:08
(https://claude.ai/artifact/5nttjeU5y5SaNSHU1etyuK). Seeds only the starter chart and the
current fiscal year, as the owner asked:

- ``app.gl_chart_template``: the starter chart from mock-up v66 with the owner's English and
  Khmer names (read-only). 4100 is "Exchange gain or loss" and 6160 "Customer debt written
  off", the names put to the owner on 2026-11-02; a name can still change later.
  2400 Taxes to pay and 6040 NSSF stay locked until a tax agent confirms the rules (PR-GL-005).
- ``app.gl_start_ledger(property, year, actor)``: copies the template into the Property's
  accounts (missing codes only) and opens the fiscal year with its 12 months and period 13.
  It runs again safely.
- This migration starts the ledger for the existing Property with fiscal year 2027 (the
  ledger start date is 1 January 2027, Q4), as the actor who created the Property. A fresh
  database has no Property yet, so nothing is seeded until the function is called.

Downgrade removes the function and the template only. Seeded accounts and the fiscal year
stay (they are never deleted); migration 20270409_259's downgrade removes them with the
ledger while no entry exists.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270412_262"
down_revision: str | None = "20270411_261"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEDGER_START_YEAR = 2027

# code, English, Khmer, type, flags (contra, control, tax lock, retained, Unit), section,
# cash kind, cash-flow group
A, L, E, INC, C, X = "ASSET", "LIABILITY", "EQUITY", "INCOME", "COST_OF_SALES", "EXPENSE"
CHART: tuple[tuple[str, str, str, str, dict[str, object]], ...] = (
    ("1010", "Cash on hand (USD)", "សាច់ប្រាក់ក្នុងដៃ (USD)", A, {"cash": "CASH_USD"}),
    ("1011", "Cash on hand (KHR)", "សាច់ប្រាក់ក្នុងដៃ (KHR)", A, {"cash": "CASH_KHR"}),
    ("1020", "ABA Bank · USD account", "ធនាគារ ABA · ដុល្លារ", A, {"cash": "BANK"}),
    ("1030", "Petty cash", "សាច់ប្រាក់រាយ", A, {"cash": "PETTY"}),
    ("1100", "Customer debt · Invoices", "បំណុលអតិថិជន · វិក្កយបត្រ", A, {"control": "INVOICES"}),
    (
        "1110",
        "Customer debt · late-payment charges",
        "បំណុលអតិថិជន · ថ្លៃបង់យឺត",
        A,
        {"control": "LATE_CHARGES"},
    ),
    ("1200", "Paid in advance", "បង់ជាមុន", A, {}),
    ("1210", "Salary loans to staff", "ប្រាក់កម្ចីប្រាក់ខែឱ្យបុគ្គលិក", A, {}),
    ("1300", "Stock of products", "ស្តុកផលិតផល", A, {"control": "STOCK"}),
    ("1400", "Staff advances", "ប្រាក់បុរេប្រទានបុគ្គលិក", A, {}),
    ("1500", "Land", "ដី", A, {"long": True, "flow": "INVESTING"}),
    ("1510", "Building", "អគារ", A, {"long": True, "flow": "INVESTING"}),
    (
        "1520",
        "Furniture and appliances in Units",
        "គ្រឿងសង្ហារឹម និងឧបករណ៍ក្នុងបន្ទប់",
        A,
        {"long": True, "flow": "INVESTING", "unit": True},
    ),
    ("1530", "Office equipment", "ឧបករណ៍ការិយាល័យ", A, {"long": True, "flow": "INVESTING"}),
    (
        "1590",
        "Accumulated depreciation",
        "រំលោះបង្គរ",
        A,
        {"long": True, "flow": "INVESTING", "contra": True},
    ),
    ("2010", "Supplier bills to pay", "វិក្កយបត្រអ្នកផ្គត់ផ្គង់ត្រូវបង់", L, {}),
    ("2020", "Costs not billed yet", "ចំណាយមិនទាន់មានវិក្កយបត្រ", L, {}),
    (
        "2050",
        "Rent billed in advance",
        "ឈ្នួលចេញវិក្កយបត្រជាមុន",
        L,
        {"control": "RENT_IN_ADVANCE"},
    ),
    (
        "2100",
        "Security Deposits held",
        "ប្រាក់កក់ធានាដែលកាន់",
        L,
        {"control": "SECURITY_DEPOSITS"},
    ),
    ("2110", "Pet Deposits held", "ប្រាក់កក់សត្វចិញ្ចឹម", L, {"control": "PET_DEPOSITS"}),
    ("2200", "Customer Credit", "ឥណទានអតិថិជន", L, {"control": "CUSTOMER_CREDIT"}),
    ("2210", "Money not used yet", "ប្រាក់មិនទាន់ប្រើ", L, {"control": "MONEY_NOT_USED"}),
    ("2300", "Salaries to pay", "ប្រាក់ខែត្រូវបង់", L, {}),
    ("2310", "Money owed to staff", "ប្រាក់ជំពាក់បុគ្គលិក", L, {}),
    ("2400", "Taxes to pay", "ពន្ធត្រូវបង់", L, {"tax": True}),
    ("2600", "Loans", "ប្រាក់កម្ចី", L, {"long": True, "flow": "FINANCING"}),
    ("3000", "Owner's capital", "ដើមទុនម្ចាស់", E, {"flow": "FINANCING"}),
    ("3100", "Owner's drawings", "ការដកប្រាក់ម្ចាស់", E, {"flow": "FINANCING", "contra": True}),
    (
        "3900",
        "Profit kept from past years",
        "ចំណេញរក្សាទុកពីឆ្នាំមុន",
        E,
        {"retained": True},
    ),
    ("4010", "Rent", "ឈ្នួល", INC, {}),
    ("4020", "Services", "សេវា", INC, {}),
    ("4030", "Electricity billed to Customers", "ភ្លើងគិតពីអតិថិជន", INC, {}),
    ("4040", "Water billed to Customers", "ទឹកគិតពីអតិថិជន", INC, {}),
    ("4050", "Late-payment charges", "ថ្លៃបង់យឺត", INC, {}),
    ("4060", "Move-out cleaning", "សម្អាតពេលចាកចេញ", INC, {}),
    ("4070", "Damage recovered", "សំណងការខូចខាត", INC, {}),
    (
        "4080",
        "Product sales and other charges",
        "ការលក់ផលិតផល និងថ្លៃផ្សេងៗ",
        INC,
        {},
    ),
    ("4090", "Kept deposits", "ប្រាក់កក់ដែលរក្សាទុក", INC, {}),
    ("4100", "Exchange gain or loss", "ចំណេញ ឬខាតពីការប្ដូរប្រាក់", INC, {}),
    ("5010", "Cost of products sold", "ថ្លៃដើមផលិតផលលក់", C, {}),
    ("6010", "Electricity bill (EDC)", "វិក្កយបត្រភ្លើង (EDC)", X, {}),
    ("6020", "Water bill", "វិក្កយបត្រទឹក", X, {}),
    ("6030", "Salaries", "ប្រាក់ខែ", X, {}),
    ("6040", "Staff social security (NSSF)", "សន្តិសុខសង្គម (ប.ស.ស)", X, {"tax": True}),
    ("6050", "Repairs and maintenance", "ជួសជុល និងថែទាំ", X, {"unit": True}),
    ("6060", "Cleaning supplies", "សម្ភារៈសម្អាត", X, {}),
    ("6070", "Internet and phone", "អ៊ីនធឺណិត និងទូរស័ព្ទ", X, {}),
    ("6080", "Trash and city fees", "សំរាម និងថ្លៃក្រុង", X, {}),
    ("6090", "Bank fees", "ថ្លៃធនាគារ", X, {}),
    ("6100", "Taxes and licences", "ពន្ធ និងអាជ្ញាប័ណ្ណ", X, {}),
    ("6110", "Insurance", "ធានារ៉ាប់រង", X, {}),
    ("6120", "Marketing", "ទីផ្សារ", X, {}),
    (
        "6130",
        "Office supplies and printing",
        "សម្ភារៈការិយាល័យ និងបោះពុម្ព",
        X,
        {},
    ),
    ("6140", "Depreciation", "រំលោះ", X, {}),
    ("6150", "Lift service", "សេវាជណ្ដើរយន្ត", X, {}),
    ("6160", "Customer debt written off", "បំណុលអតិថិជនដែលលុបចោល", X, {}),
    ("6170", "Stock lost or broken", "ស្តុកបាត់ ឬខូច", X, {}),
    ("6180", "Cash short or over", "សាច់ប្រាក់ខ្វះ ឬលើស", X, {}),
    ("6190", "Other expenses", "ចំណាយផ្សេងៗ", X, {}),
)


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "'" + str(value).replace("'", "''") + "'"


def _rows() -> str:
    rows = []
    for code, name_en, name_km, account_type, flags in CHART:
        section = (
            ("NON_CURRENT" if flags.get("long") else "CURRENT") if account_type in (A, L) else None
        )
        values = (
            code,
            name_en,
            name_km,
            account_type,
            bool(flags.get("contra")),
            flags.get("control"),
            bool(flags.get("tax")),
            bool(flags.get("retained")),
            bool(flags.get("unit")),
            section,
            flags.get("cash"),
            flags.get("flow") or ("OPERATING" if not flags.get("cash") else None),
        )
        rows.append("(" + ", ".join(_literal(value) for value in values) + ")")
    return ",\n            ".join(rows)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE app.gl_chart_template (
            code text PRIMARY KEY CHECK (code ~ '^[1-6][0-9]{{3}}$'),
            name_en text NOT NULL CHECK (length(btrim(name_en)) BETWEEN 1 AND 120),
            name_km text NOT NULL CHECK (length(btrim(name_km)) BETWEEN 1 AND 120),
            account_type text NOT NULL CHECK (account_type IN
                ('ASSET','LIABILITY','EQUITY','INCOME','COST_OF_SALES','EXPENSE')),
            is_contra boolean NOT NULL,
            control_source text,
            is_tax_locked boolean NOT NULL,
            is_retained_earnings boolean NOT NULL,
            allows_unit boolean NOT NULL,
            bs_section text,
            cash_kind text,
            cash_flow_group text
        );
        INSERT INTO app.gl_chart_template (code, name_en, name_km, account_type, is_contra,
            control_source, is_tax_locked, is_retained_earnings, allows_unit, bs_section,
            cash_kind, cash_flow_group)
        VALUES
            {_rows()};
        CREATE TRIGGER gl_chart_template_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.gl_chart_template
            FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
        CREATE TRIGGER gl_chart_template_reject_truncate BEFORE TRUNCATE ON app.gl_chart_template
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
        GRANT SELECT ON app.gl_chart_template TO prm_runtime, prm_financial;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.gl_start_ledger(p_property uuid, p_year smallint, p_actor uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_added integer;
            v_year uuid;
        BEGIN
            INSERT INTO app.gl_accounts (id, property_id, code, name_en, name_km, account_type,
                is_contra, control_source, is_tax_locked, is_retained_earnings, allows_unit,
                bs_section, cash_kind, cash_flow_group, created_by)
            SELECT gen_random_uuid(), p_property, template.code, template.name_en,
                template.name_km, template.account_type, template.is_contra,
                template.control_source, template.is_tax_locked, template.is_retained_earnings,
                template.allows_unit, template.bs_section, template.cash_kind,
                template.cash_flow_group, p_actor
            FROM app.gl_chart_template AS template
            WHERE NOT EXISTS (SELECT 1 FROM app.gl_accounts AS account
                              WHERE account.property_id = p_property
                                AND account.code = template.code)
            ORDER BY template.code;
            GET DIAGNOSTICS v_added = ROW_COUNT;
            v_year := app.gl_open_fiscal_year(p_property, p_year, p_actor);
            IF v_added > 0 THEN
                PERFORM app.gl_audit(p_property, p_actor, 'ledger.started', 'gl_fiscal_year',
                    v_year, 'Starter chart of accounts and fiscal year ' || p_year,
                    gen_random_uuid(),
                    jsonb_build_object('accounts_added', v_added, 'fiscal_year', p_year));
            END IF;
            RETURN v_year;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_start_ledger(uuid, smallint, uuid) FROM PUBLIC;
        """
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            v_property record;
        BEGIN
            FOR v_property IN SELECT property.id, property.created_by
                              FROM app.properties AS property LOOP
                PERFORM app.gl_start_ledger(v_property.id, {LEDGER_START_YEAR}::smallint,
                    v_property.created_by);
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Remove the start function and the template; seeded accounts and the year stay."""
    op.execute(
        """
        DROP FUNCTION app.gl_start_ledger(uuid, smallint, uuid);
        DROP TABLE app.gl_chart_template;
        """
    )
