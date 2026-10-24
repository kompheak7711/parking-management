"""Invoice, Receipt and Refund numbers by year (V1-059 part B; DL-071 answer 10, DL-075).

DL-071 answer 10 with the DL-075 amendment; technical points decided by Claude under the owner's
2026-10-23 22:30 rule.

- A number is letters, the 2-digit year and a running number of 4 digits: INV260001,
  RCP260001, RFD260001. The running number restarts at 1 each year for each document type; the
  year is the Asia/Phnom_Penh date of the issue. Past 9999 it simply grows (INV2610000); a
  number is never given twice.
- `app.document_number_series` keeps the letters of each type (2 to 5 capital letters, all
  different), seeded INV, RCP and RFD; they become Settings values later (DL-075).
  `app.document_number_counters` keeps the last number of each type and year. The counter
  belongs to the type, not to the letters, so the number carries on when the letters change and
  never goes back. `app.next_document_number(type, at)` takes the next one; the counter row is
  locked until the transaction ends, so a rolled-back issue leaves no gap.
- Invoices: a draft keeps its internal reference (RENT-..., UTIL-..., INV-yyyymmdd-...) and
  gets no number (DL-071 answer 9). When it is issued, the number replaces the reference, and
  the reference stays in the new `draft_reference` column. A draft dropped (VOID) keeps its
  reference. Nobody else changes `invoice_number` or `draft_reference`.
- Payments: the number of the Receipt series (DL-071: the Payment Number is its Receipt's
  number). Receipts take the number of their Payment; the check that a Receipt number is
  'R-' followed by its id is removed (relaxing).
- Refunds: the number of the Refund series, given when the Refund is recorded (a Refund draft
  of a Reservation Deposit carries an internal reference only). Three functions that returned
  the number they wrote now read the given number back.

Rows recorded before keep their numbers. Each counter starts at the highest number already
used in the new format (a Refund number used to be typed by staff), else at 0, so a number is
never given twice.
"""

from alembic import op

revision = "20270207_195"
down_revision = "20270206_194"
branch_labels = None
depends_on = None

# Each patched function: the text written before and the text written now (exactly once).
FUNCTION_PATCHES = (
    (
        "app.post_final_settlement_deposit_refund",
        "'refund_number','REF-'||p_refund::text",
        "'refund_number',(SELECT r.refund_number FROM app.refunds AS r WHERE r.id=p_refund)",
    ),
    (
        "app.post_settlement_correction_deposit_refund",
        "'refund_number','REF-'||v_refund::text",
        "'refund_number',(SELECT r.refund_number FROM app.refunds AS r WHERE r.id=v_refund)",
    ),
    (
        "app.create_reservation_deposit_outcome",
        "refund_number := p_refund_number;",
        "refund_number := (SELECT r.refund_number FROM app.refunds AS r WHERE r.id=p_outcome_id);",
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.document_number_series (
            document_type text PRIMARY KEY
                CHECK (document_type IN ('INVOICE','RECEIPT','REFUND')),
            letters text NOT NULL UNIQUE CHECK (letters ~ '^[A-Z]{2,5}$')
        );
        INSERT INTO app.document_number_series(document_type, letters)
        VALUES ('INVOICE','INV'), ('RECEIPT','RCP'), ('REFUND','RFD');

        CREATE TABLE app.document_number_counters (
            document_type text NOT NULL
                REFERENCES app.document_number_series(document_type) ON DELETE RESTRICT,
            number_year integer NOT NULL CHECK (number_year BETWEEN 2000 AND 2099),
            last_number bigint NOT NULL CHECK (last_number > 0),
            PRIMARY KEY (document_type, number_year)
        );
        -- Numbers recorded before in the new format (a Refund number was typed by staff, review
        -- round 1) are never given again: each counter starts at the highest one already used.
        INSERT INTO app.document_number_counters(document_type, number_year, last_number)
        SELECT used.document_type, 2000 + used.year_digits, max(used.running_number)
        FROM (
            SELECT 'INVOICE' AS document_type,
                   substring(invoice_number FROM 4 FOR 2)::integer AS year_digits,
                   substring(invoice_number FROM 6)::bigint AS running_number
            FROM app.invoices WHERE invoice_number ~ '^INV[0-9]{6,18}$'
            UNION ALL
            SELECT 'RECEIPT', substring(payment_number FROM 4 FOR 2)::integer,
                   substring(payment_number FROM 6)::bigint
            FROM app.payments WHERE payment_number ~ '^RCP[0-9]{6,18}$'
            UNION ALL
            SELECT 'RECEIPT', substring(receipt_number FROM 4 FOR 2)::integer,
                   substring(receipt_number FROM 6)::bigint
            FROM app.receipts WHERE receipt_number ~ '^RCP[0-9]{6,18}$'
            UNION ALL
            SELECT 'REFUND', substring(refund_number FROM 4 FOR 2)::integer,
                   substring(refund_number FROM 6)::bigint
            FROM app.refunds WHERE refund_number ~ '^RFD[0-9]{6,18}$'
        ) AS used
        WHERE used.running_number > 0
        GROUP BY used.document_type, used.year_digits;

        CREATE FUNCTION app.reject_document_counter_change() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP='UPDATE' AND NEW.document_type=OLD.document_type
               AND NEW.number_year=OLD.number_year AND NEW.last_number>OLD.last_number THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'A document number counter only moves forward' USING ERRCODE='55000';
        END
        $$;
        CREATE TRIGGER document_number_counters_forward
            BEFORE UPDATE OR DELETE ON app.document_number_counters
            FOR EACH ROW EXECUTE FUNCTION app.reject_document_counter_change();
        CREATE TRIGGER document_number_counters_reject_truncate
            BEFORE TRUNCATE ON app.document_number_counters
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_document_counter_change();

        CREATE FUNCTION app.next_document_number(p_document_type text, p_at timestamptz)
        RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE v_year integer; v_letters text; v_number bigint;
        BEGIN
            IF p_at IS NULL OR NOT pg_catalog.isfinite(p_at) THEN
                RAISE EXCEPTION 'A document number needs its issue time' USING ERRCODE='22023';
            END IF;
            SELECT series.letters INTO v_letters
            FROM app.document_number_series AS series
            WHERE series.document_type=p_document_type;
            IF v_letters IS NULL THEN
                RAISE EXCEPTION 'Unknown document type' USING ERRCODE='22023';
            END IF;
            v_year := pg_catalog.date_part('year', p_at AT TIME ZONE 'Asia/Phnom_Penh')::integer;
            INSERT INTO app.document_number_counters AS counter(
                document_type, number_year, last_number
            ) VALUES (p_document_type, v_year, 1)
            ON CONFLICT (document_type, number_year)
            DO UPDATE SET last_number=counter.last_number+1
            RETURNING counter.last_number INTO v_number;
            RETURN v_letters || pg_catalog.lpad((v_year % 100)::text, 2, '0')
                || CASE WHEN v_number < 10000
                        THEN pg_catalog.lpad(v_number::text, 4, '0')
                        ELSE v_number::text END;
        END
        $$;

        ALTER TABLE app.invoices ADD COLUMN draft_reference text;
        ALTER TABLE app.invoices ADD CONSTRAINT invoices_draft_reference_unique
            UNIQUE (draft_reference);

        CREATE FUNCTION app.assign_invoice_document_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.draft_reference IS NOT NULL THEN
                    RAISE EXCEPTION 'An Invoice draft reference is given by the database'
                        USING ERRCODE='55000';
                END IF;
                NEW.draft_reference := NEW.invoice_number;
                IF NEW.status<>'DRAFT' AND NEW.status<>'VOID' THEN
                    NEW.invoice_number := app.next_document_number(
                        'INVOICE', COALESCE(NEW.issued_at, pg_catalog.statement_timestamp())
                    );
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.invoice_number IS DISTINCT FROM OLD.invoice_number
               OR NEW.draft_reference IS DISTINCT FROM OLD.draft_reference THEN
                RAISE EXCEPTION 'An Invoice number is given by the database'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.status='DRAFT' AND NEW.status<>'DRAFT' AND NEW.status<>'VOID' THEN
                NEW.draft_reference := COALESCE(OLD.draft_reference, OLD.invoice_number);
                NEW.invoice_number := app.next_document_number(
                    'INVOICE', COALESCE(NEW.issued_at, pg_catalog.statement_timestamp())
                );
            END IF;
            RETURN NEW;
        END
        $$;
        CREATE TRIGGER invoices_zz_document_number
            BEFORE INSERT OR UPDATE ON app.invoices
            FOR EACH ROW EXECUTE FUNCTION app.assign_invoice_document_number();

        CREATE FUNCTION app.assign_payment_document_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.payment_number := app.next_document_number('RECEIPT', NEW.confirmed_at);
            RETURN NEW;
        END
        $$;
        CREATE TRIGGER a00_payments_document_number
            BEFORE INSERT ON app.payments
            FOR EACH ROW EXECUTE FUNCTION app.assign_payment_document_number();

        CREATE FUNCTION app.assign_receipt_document_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE v_number text;
        BEGIN
            SELECT payment.payment_number INTO STRICT v_number
            FROM app.payments AS payment WHERE payment.id=NEW.payment_id;
            NEW.receipt_number := v_number;
            RETURN NEW;
        END
        $$;
        ALTER TABLE app.receipts DROP CONSTRAINT receipts_check;
        CREATE TRIGGER a00_receipts_document_number
            BEFORE INSERT ON app.receipts
            FOR EACH ROW EXECUTE FUNCTION app.assign_receipt_document_number();

        CREATE FUNCTION app.assign_refund_document_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.refund_number := app.next_document_number('REFUND', NEW.processed_at);
            RETURN NEW;
        END
        $$;
        CREATE TRIGGER a00_refunds_document_number
            BEFORE INSERT ON app.refunds
            FOR EACH ROW EXECUTE FUNCTION app.assign_refund_document_number();

        REVOKE ALL ON app.document_number_series, app.document_number_counters FROM PUBLIC;
        GRANT SELECT ON app.document_number_series, app.document_number_counters TO prm_runtime;
        REVOKE ALL ON FUNCTION app.reject_document_counter_change() FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.next_document_number(text, timestamptz) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.assign_invoice_document_number() FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.assign_payment_document_number() FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.assign_receipt_document_number() FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.assign_refund_document_number() FROM PUBLIC;
        """
    )
    for function_name, before, after in FUNCTION_PATCHES:
        _patch_function(function_name, before, after)


def _patch_function(function_name: str, before: str, after: str) -> None:
    """Rewrite one function; stop the migration when the old text is not there exactly once."""
    op.execute(
        f"""
        DO $patch$
        DECLARE v_definition text; v_count integer;
        BEGIN
            SELECT pg_catalog.pg_get_functiondef(p.oid) INTO STRICT v_definition
            FROM pg_catalog.pg_proc AS p
            WHERE p.oid = '{function_name}'::regproc;
            v_count := (pg_catalog.length(v_definition)
                - pg_catalog.length(pg_catalog.replace(v_definition, $old${before}$old$, '')))
                / pg_catalog.length($old${before}$old$);
            IF v_count <> 1 THEN
                RAISE EXCEPTION '{function_name}: expected text found % times', v_count;
            END IF;
            EXECUTE pg_catalog.replace(v_definition, $old${before}$old$, $new${after}$new$);
        END
        $patch$;
        """
    )


def downgrade() -> None:
    """Forward-only: a given document number must never be given again."""
    raise RuntimeError("document number migration is forward-only")
