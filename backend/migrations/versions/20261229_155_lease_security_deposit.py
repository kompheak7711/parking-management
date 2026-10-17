# ruff: noqa: E501
"""The walk-in Lease's Security Deposit and a second receipt before signing (V1-056 sub-slice 10e-2b-4c).

BR-DEP-001, BR-DEP-002, BR-DEP-004, BR-DEP-005, BR-DEP-006, DL-008, DL-009, DL-066; DB-DEP-001,
DB-DEP-002; owner answers to Q-2026-10-17-124 (point 1 (a): staff enter a walk-in Lease's required
Security Deposit total from the Lease terms with a new `deposits.manage` command; point 2 (a): its
first receipt may be any amount above 0, never above the required total; point 3: a second receipt
into a Reservation's Security Deposit before signing is allowed, never above the required total)
and the owner note of 2026-10-17 on DL-009 (extra money paid before signing follows DL-009 as
written; review round 1 found that the Reservation outcome code refused a Deposit with a reversed
receipt, so it now classifies the active receipts, below).

- `deposits_source_shape` gains a third branch (relaxing): a Security Deposit with a Lease, no
  Reservation and no pet approval (a walk-in Lease's).
- app.validate_reservation_security_deposit returns at once for such a row; the Reservation
  continuity check stays for every Reservation Deposit.
- app.validate_deposit_source (the deferred source check) checks such a row: its Lease is SIGNED,
  its Primary Tenant is the Deposit's Customer, it was signed through the new path with no
  Reservation (a `lease_signing_outcomes` row with no Reservation, and no Reservation names it as
  its resulting Lease), it is not a renewal, and no other Security Deposit names the Lease.
- app.validate_deposit_receipt: for a Security Deposit with no Reservation, the first receipt may be
  any amount above 0 (no accepted amount), never above the required total (the existing bound),
  and no receipt comes before the Lease's signing (unknown reads as never).
- New app.create_lease_security_deposit (SECURITY DEFINER, EXECUTE only to the financial role; the
  Deposit service checks the Property scope and `deposits.manage`): input first (22023); the
  idempotency lock and the replay (action `deposit.security.create`, a relaxing widening of
  `deposit_commands_action_check`); an active financial actor; the SIGNED Lease of the Property,
  locked (P0002 otherwise); then refused: a closed Final Settlement of the Lease (P5S01), a Lease
  signed from a Reservation or through the old path (55000; its Security Deposit is the
  Reservation's, BR-DEP-005), a renewal Lease (55000; Q-2026-10-18-129), a Lease that already has a
  Security Deposit (55000). The required effective date is the business date of the Lease's signing
  in the Property's time zone. It writes the Deposit, the `deposit.security.created` audit event and
  the command record; the result is the Deposit snapshot.
- app.record_lease_deposit_receipt: a Deposit with no Lease is a Reservation's Security Deposit; its
  receipt is recorded only while the Reservation is ACTIVE and its effective expiration date has
  not passed in the Property's time zone (55000 otherwise). The Reservation row is locked (FOR
  SHARE) before the Deposit, the order signing uses, so a signing, cancellation or expiration waits
  for the receipt, and a receipt that waited reads the committed state. The Lease checks run only
  for a Deposit with a Lease.
- Review round 1 (security): the create runs at READ COMMITTED only (55000), as the receipt
  writer; the deferred source check also refuses linking a Reservation's Deposit to a Lease that
  already has a walk-in Security Deposit (the old Reservation move-in reads no signing outcome).
- Review round 1 (independent; the owner note on DL-009: fix the Reservation outcome code inside
  this sub-slice if it cannot handle a Deposit holding more than the accepted amount): with a
  second receipt, a reversed receipt can leave a Reservation Deposit holding money; the outcome
  draft source, the outcome insert check, the outcome writer and the outcome correction classify
  only active receipts, and the draft source no longer refuses a Deposit with a reversed receipt.
- Review round 2 (independent): app.cancel_reservation and app.expire_reservation also report
  (and store in their command result) only active receipts as the Deposit's received amount.

Exact-text patches of ten existing functions (each replacement checked to match once), one new
function, two relaxed checks; no table, trigger or other grant changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261229_155"
down_revision = "20261228_154"
branch_labels = None
depends_on = None

SQL = r"""
    ALTER TABLE app.deposit_commands
        DROP CONSTRAINT deposit_commands_action_check,
        ADD CONSTRAINT deposit_commands_action_check CHECK (action IN (
            'deposit.pet.create', 'deposit.required.adjust', 'deposit.receipt.reverse',
            'deposit.disposition.record', 'deposit.disposition.reverse',
            'deposit.pet_refund.qualify', 'deposit.pet_departure.record',
            'deposit.pet_refund.review', 'deposit.reservation_disposition.correct',
            'deposit.receipt.record', 'deposit.security.create'
        ));

    ALTER TABLE app.deposits
        DROP CONSTRAINT deposits_source_shape,
        ADD CONSTRAINT deposits_source_shape CHECK (
            (deposit_type = 'SECURITY' AND reservation_id IS NOT NULL
                AND pet_approval_id IS NULL)
            OR
            (deposit_type = 'SECURITY' AND reservation_id IS NULL
                AND lease_id IS NOT NULL AND pet_approval_id IS NULL)
            OR
            (deposit_type = 'PET' AND reservation_id IS NULL
                AND lease_id IS NOT NULL AND pet_approval_id IS NOT NULL)
        );

    -- Sub-slice 10e-2b-4c (owner answer (a) to Q-2026-10-17-124 point 1): staff enter a walk-in
    -- Lease's required Security Deposit total from the Lease terms under deposits.manage.
    CREATE FUNCTION app.create_lease_security_deposit(
        p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid, p_request_digest text,
        p_deposit_id uuid, p_lease_id uuid, p_required_usd_cents bigint, p_reason text,
        p_authorization_reference text
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_lease app.leases%ROWTYPE; v_effective date;
        BEGIN
            IF p_property_id IS NULL OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_deposit_id IS NULL OR p_lease_id IS NULL
                OR '00000000-0000-0000-0000-000000000000'::uuid IN (p_property_id,p_actor_id,
                    p_idempotency_key,p_deposit_id,p_lease_id)
                OR p_authorization_reference IS DISTINCT FROM 'deposits.manage'
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_required_usd_cents IS NULL OR p_required_usd_cents <= 0
                OR p_reason IS NULL OR btrim(p_reason) = '' OR p_reason <> btrim(p_reason)
                OR length(p_reason) > 1000
            THEN RAISE EXCEPTION 'Security Deposit evidence is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.security.create-' || p_idempotency_key::text, 0));
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.security.create',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            -- Review round 1 (security): at a stricter isolation level two creates could both
            -- read an older snapshot after the Lease lock; the service runs at READ COMMITTED.
            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
                RAISE EXCEPTION 'A Security Deposit is created at READ COMMITTED'
                    USING ERRCODE='55000'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            -- The Lease row lock makes two creates for one Lease wait for each other; the second
            -- reads the first one's Deposit below and is refused.
            SELECT lease.* INTO v_lease FROM app.leases lease
            JOIN app.units unit ON unit.id=lease.unit_id
            WHERE lease.id=p_lease_id AND unit.property_id=p_property_id AND lease.status='SIGNED'
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Signed Lease was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS(SELECT 1 FROM app.final_settlements settlement
                WHERE settlement.lease_id=p_lease_id AND settlement.closed_at IS NOT NULL)
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
            -- BR-DEP-005: a Lease signed from a Reservation keeps the Reservation's Security
            -- Deposit; a Lease signed through the old path (no signing outcome) keeps its
            -- Reservation move-in path.
            IF NOT EXISTS(SELECT 1 FROM app.lease_signing_outcomes outcome
                    WHERE outcome.lease_id=p_lease_id AND outcome.reservation_id IS NULL)
                OR EXISTS(SELECT 1 FROM app.reservations reservation
                    WHERE reservation.resulting_lease_id=p_lease_id)
            THEN RAISE EXCEPTION 'Only a walk-in Lease''s Security Deposit is created here'
                USING ERRCODE='55000'; END IF;
            -- Q-2026-10-18-129: no rule says whether a renewal keeps its predecessor's Security
            -- Deposit or gets a new one; refused until the owner answers.
            IF v_lease.predecessor_lease_id IS NOT NULL THEN
                RAISE EXCEPTION 'A renewal Lease''s Security Deposit is not created here'
                    USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.deposits deposit
                WHERE deposit.lease_id=p_lease_id AND deposit.deposit_type='SECURITY')
            THEN RAISE EXCEPTION 'The Lease already has a Security Deposit' USING ERRCODE='55000'; END IF;
            -- The obligation starts at the signing, as a Reservation Deposit's starts at its
            -- Reservation date; no device clock reaches it.
            SELECT timezone(property.timezone_name,v_lease.signed_at)::date INTO STRICT v_effective
            FROM app.properties property WHERE property.id=p_property_id;
            INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,lease_id,
                pet_approval_id,required_usd_cents,required_effective_date,created_by,updated_by)
            VALUES(p_deposit_id,'SECURITY',v_lease.primary_tenant_id,NULL,p_lease_id,NULL,
                p_required_usd_cents,v_effective,p_actor_id,p_actor_id);
            SET CONSTRAINTS app.deposits_validate_source IMMEDIATE;
            v_result := app.deposit_resource_snapshot(p_deposit_id);
            PERFORM app.record_deposit_audit(p_deposit_id,'deposit.security.created','deposit',
                p_deposit_id,p_deposit_id,p_reason,p_authorization_reference,p_actor_id,
                p_idempotency_key,v_result);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.security.create',
                p_idempotency_key,p_request_digest,p_deposit_id,p_reason,p_authorization_reference,
                v_result);
            RETURN v_result;
        END;
    $$;
"""

GRANTED = (
    "app.create_lease_security_deposit(uuid,uuid,uuid,text,uuid,uuid,bigint,text,text)",
)

CONTINUITY = "app.validate_reservation_security_deposit()"
CONTINUITY_REPLACEMENTS = (
    (
        "            IF NEW.deposit_type = 'PET' THEN RETURN NEW; END IF;\n",
        "            -- Sub-slice 10e-2b-4c: a walk-in Lease's Security Deposit has no Reservation; the\n"
        "            -- deferred source check (app.validate_deposit_source) checks its Lease.\n"
        "            IF NEW.deposit_type = 'PET' OR NEW.reservation_id IS NULL THEN RETURN NEW; END IF;\n",
    ),
)

SOURCE = "app.validate_deposit_source()"
SOURCE_REPLACEMENTS = (
    (
        "            IF NEW.deposit_type = 'SECURITY' THEN\n"
        "                IF NOT EXISTS (\n"
        "                    SELECT 1 FROM app.reservations AS reservation\n",
        "            IF NEW.deposit_type = 'SECURITY' AND NEW.reservation_id IS NULL THEN\n"
        "                -- Sub-slice 10e-2b-4c (owner answer (a) to Q-2026-10-17-124 point 1): a walk-in\n"
        "                -- Lease's Security Deposit: a SIGNED Lease of the Deposit's Customer, signed\n"
        "                -- through the new path with no Reservation, not a renewal, and no other\n"
        "                -- Security Deposit of that Lease.\n"
        "                IF NOT EXISTS (\n"
        "                    SELECT 1 FROM app.leases AS lease\n"
        "                    JOIN app.lease_signing_outcomes AS outcome ON outcome.lease_id = lease.id\n"
        "                    WHERE lease.id = NEW.lease_id\n"
        "                      AND lease.primary_tenant_id = NEW.customer_id\n"
        "                      AND lease.status = 'SIGNED'\n"
        "                      AND lease.predecessor_lease_id IS NULL\n"
        "                      AND outcome.reservation_id IS NULL\n"
        "                ) OR EXISTS (\n"
        "                    SELECT 1 FROM app.reservations AS reservation\n"
        "                    WHERE reservation.resulting_lease_id = NEW.lease_id\n"
        "                ) OR EXISTS (\n"
        "                    SELECT 1 FROM app.deposits AS other\n"
        "                    WHERE other.lease_id = NEW.lease_id AND other.deposit_type = 'SECURITY'\n"
        "                      AND other.id <> NEW.id\n"
        "                ) THEN\n"
        "                    RAISE EXCEPTION 'A walk-in Security Deposit requires a signed walk-in Lease with no other Security Deposit'\n"
        "                        USING ERRCODE = '23514';\n"
        "                END IF;\n"
        "            ELSIF NEW.deposit_type = 'SECURITY' THEN\n"
        "                IF NOT EXISTS (\n"
        "                    SELECT 1 FROM app.reservations AS reservation\n",
    ),
    (
        "                    RAISE EXCEPTION 'Security Deposit sources do not match'\n"
        "                        USING ERRCODE = '23514';\n"
        "                END IF;\n"
        "            ELSIF NOT EXISTS (\n",
        "                    RAISE EXCEPTION 'Security Deposit sources do not match'\n"
        "                        USING ERRCODE = '23514';\n"
        "                END IF;\n"
        "                -- Sub-slice 10e-2b-4c (review round 1, security): a Reservation's Deposit is\n"
        "                -- not linked to a Lease that already has a walk-in Security Deposit (one\n"
        "                -- Security Deposit per Lease; the old Reservation move-in reads no signing\n"
        "                -- outcome).\n"
        "                IF NEW.lease_id IS NOT NULL AND EXISTS (\n"
        "                    SELECT 1 FROM app.deposits AS other\n"
        "                    WHERE other.lease_id = NEW.lease_id AND other.deposit_type = 'SECURITY'\n"
        "                      AND other.reservation_id IS NULL AND other.id <> NEW.id\n"
        "                ) THEN\n"
        "                    RAISE EXCEPTION 'Security Deposit sources do not match'\n"
        "                        USING ERRCODE = '23514';\n"
        "                END IF;\n"
        "            ELSIF NOT EXISTS (\n",
    ),
)

# Review round 1 (independent B1; owner note of 2026-10-17 on DL-009: "if the Reservation outcome
# code cannot handle a Deposit that holds more than the accepted amount, fix that inside
# 10e-2b-4c"): with a second receipt, a reversed receipt (a bounced Payment's return, or a receipt
# reversal) can leave a Reservation Deposit holding money; the outcome then classifies the money
# the Deposit holds, its active receipts, instead of refusing every Deposit with a reversed receipt.
ACTIVE_RECEIPTS = (
    "            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint\n"
    "            INTO v_received\n"
    "            FROM app.deposit_receipts AS receipt\n"
    "            WHERE receipt.deposit_id = v_deposit_id;\n",
    "            -- Sub-slice 10e-2b-4c (review round 1): only active receipts are classified.\n"
    "            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint\n"
    "            INTO v_received\n"
    "            FROM app.deposit_receipts AS receipt\n"
    "            WHERE receipt.deposit_id = v_deposit_id\n"
    "              AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
    "                  WHERE reversal.deposit_receipt_id = receipt.id);\n",
)

DRAFT_SOURCE = "app.reservation_deposit_draft_source(uuid,uuid,text)"
DRAFT_SOURCE_REPLACEMENTS = (
    (
        "            -- The outcome functions classify every receipt; a corrected receipt has no rule yet.\n"
        "            IF EXISTS (\n"
        "                SELECT 1 FROM app.deposit_receipts AS receipt\n"
        "                JOIN app.deposit_receipt_reversals AS reversal\n"
        "                  ON reversal.deposit_receipt_id = receipt.id\n"
        "                WHERE receipt.deposit_id = v_deposit_id\n"
        "            ) THEN\n"
        "                RAISE EXCEPTION 'Reservation Deposit has a reversed receipt'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n"
        "            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint INTO v_received\n"
        "            FROM app.deposit_receipts AS receipt WHERE receipt.deposit_id = v_deposit_id;\n",
        "            -- Sub-slice 10e-2b-4c (review round 1): the outcome functions classify the money\n"
        "            -- the Deposit holds, its active receipts; a reversed receipt is not received.\n"
        "            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint INTO v_received\n"
        "            FROM app.deposit_receipts AS receipt WHERE receipt.deposit_id = v_deposit_id\n"
        "              AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
        "                  WHERE reversal.deposit_receipt_id = receipt.id);\n",
    ),
)
# Review round 2 (independent S1): the cancellation and the expiration also report (and store in
# their command result) only the money the Deposit holds, its active receipts.
REPORTED_RECEIPTS = (
    "            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id\n"
    "            WHERE deposit.reservation_id = p_reservation_id\n",
    "            -- Sub-slice 10e-2b-4c (review round 2): only active receipts are reported.\n"
    "            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id\n"
    "                AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
    "                    WHERE reversal.deposit_receipt_id = receipt.id)\n"
    "            WHERE deposit.reservation_id = p_reservation_id\n",
)
CANCELLATION = (
    "app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)"
)
EXPIRATION = "app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)"
OUTCOME_CHECK = "app.validate_reservation_financial_outcome()"
OUTCOME_WRITER = "app.create_reservation_deposit_outcome(uuid,text,uuid,text,text,uuid,text,uuid)"
OUTCOME_CORRECTION = (
    "app.correct_reservation_deposit_outcome("
    "uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)"
)

RECEIPT = "app.validate_deposit_receipt()"
RECEIPT_REPLACEMENTS = (
    (
        "                WHERE acceptance.reservation_id=v_deposit.reservation_id;\n"
        "                IF NEW.occurred_at > clock_timestamp()+interval '5 seconds'\n"
        "                    OR NEW.occurred_at < v_accepted_at\n"
        "                    OR (v_received=0 AND NEW.amount_usd_cents<>v_accepted\n",
        "                WHERE acceptance.reservation_id=v_deposit.reservation_id;\n"
        "                -- Sub-slice 10e-2b-4c (owner answers (a) to Q-2026-10-17-124 points 1 and 2):\n"
        "                -- a walk-in Lease's Security Deposit has no Reservation and no accepted\n"
        "                -- amount; its first receipt may be any amount above 0 (never above the\n"
        "                -- required total, checked below), and no receipt comes before the Lease's\n"
        "                -- signing (unknown reads as never).\n"
        "                IF v_deposit.reservation_id IS NULL THEN\n"
        "                    SELECT lease.signed_at INTO v_accepted_at\n"
        "                    FROM app.leases AS lease WHERE lease.id=v_deposit.lease_id;\n"
        "                    v_accepted_at := COALESCE(v_accepted_at,'infinity'::timestamptz);\n"
        "                END IF;\n"
        "                IF NEW.occurred_at > clock_timestamp()+interval '5 seconds'\n"
        "                    OR NEW.occurred_at < v_accepted_at\n"
        "                    OR (v_received=0 AND v_deposit.reservation_id IS NOT NULL\n"
        "                        AND NEW.amount_usd_cents<>v_accepted\n",
    ),
)

WRITER = "app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)"
WRITER_REPLACEMENTS = (
    (
        "            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;\n"
        "            PERFORM app.serialize_deposit_state(p_deposit_id);\n",
        "            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;\n"
        "            -- Sub-slice 10e-2b-4c: a Reservation's Deposit before signing: the Reservation is\n"
        "            -- locked before the Deposit, the order signing uses, so a signing, cancellation or\n"
        "            -- expiration waits for this receipt, and a receipt that waited reads the\n"
        "            -- committed state below (after a signing the Deposit has its Lease).\n"
        "            PERFORM 1 FROM app.reservations reservation\n"
        "            WHERE reservation.id=(SELECT deposit.reservation_id FROM app.deposits deposit\n"
        "                WHERE deposit.id=p_deposit_id AND deposit.lease_id IS NULL)\n"
        "            FOR SHARE OF reservation;\n"
        "            PERFORM app.serialize_deposit_state(p_deposit_id);\n",
    ),
    (
        "            IF v_deposit.lease_id IS NULL THEN\n"
        "                RAISE EXCEPTION 'The Deposit has no Lease yet; this receipt is not recorded here'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            -- Read after the Deposit lock: the closing confirm also locks every Deposit of the\n"
        "            -- Lease, so a closure committed while this writer waited is read here.\n"
        "            IF EXISTS(SELECT 1 FROM app.final_settlements settlement\n"
        "                WHERE settlement.lease_id=v_deposit.lease_id AND settlement.closed_at IS NOT NULL)\n"
        "            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'\n"
        "                USING ERRCODE='P5S01'; END IF;\n"
        "            SELECT lease.status INTO v_status FROM app.leases lease WHERE lease.id=v_deposit.lease_id;\n"
        "            IF v_status IS NULL OR v_status NOT IN ('SIGNED','TERMINATED') THEN\n"
        "                RAISE EXCEPTION 'The Deposit''s Lease is not signed' USING ERRCODE='55000'; END IF;\n",
        "            IF v_deposit.lease_id IS NULL THEN\n"
        "                -- Sub-slice 10e-2b-4c (owner answer to Q-2026-10-17-124 point 3): a second\n"
        "                -- receipt into a Reservation's Security Deposit before signing, never above the\n"
        "                -- required total (the receipt table's bound), only while the Reservation is\n"
        "                -- ACTIVE and its effective expiration date has not passed (the signing rule).\n"
        "                IF v_deposit.deposit_type IS DISTINCT FROM 'SECURITY' OR NOT EXISTS(\n"
        "                    SELECT 1 FROM app.reservations reservation\n"
        "                    JOIN app.units unit ON unit.id=reservation.unit_id\n"
        "                    JOIN app.properties property ON property.id=unit.property_id\n"
        "                    WHERE reservation.id=v_deposit.reservation_id\n"
        "                      AND reservation.status='ACTIVE'\n"
        "                      AND timezone(property.timezone_name,clock_timestamp())::date\n"
        "                          <= reservation.effective_expiration_date)\n"
        "                THEN RAISE EXCEPTION 'The Deposit''s Reservation is not active; this receipt is not recorded here'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            ELSE\n"
        "                -- Read after the Deposit lock: the closing confirm also locks every Deposit of\n"
        "                -- the Lease, so a closure committed while this writer waited is read here.\n"
        "                IF EXISTS(SELECT 1 FROM app.final_settlements settlement\n"
        "                    WHERE settlement.lease_id=v_deposit.lease_id AND settlement.closed_at IS NOT NULL)\n"
        "                THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'\n"
        "                    USING ERRCODE='P5S01'; END IF;\n"
        "                SELECT lease.status INTO v_status FROM app.leases lease WHERE lease.id=v_deposit.lease_id;\n"
        "                IF v_status IS NULL OR v_status NOT IN ('SIGNED','TERMINATED') THEN\n"
        "                    RAISE EXCEPTION 'The Deposit''s Lease is not signed' USING ERRCODE='55000'; END IF;\n"
        "            END IF;\n",
    ),
)

PATCHES = (
    (CONTINUITY, CONTINUITY_REPLACEMENTS),
    (SOURCE, SOURCE_REPLACEMENTS),
    (RECEIPT, RECEIPT_REPLACEMENTS),
    (WRITER, WRITER_REPLACEMENTS),
    (DRAFT_SOURCE, DRAFT_SOURCE_REPLACEMENTS),
    (OUTCOME_CHECK, (ACTIVE_RECEIPTS,)),
    (OUTCOME_WRITER, (ACTIVE_RECEIPTS,)),
    (OUTCOME_CORRECTION, (ACTIVE_RECEIPTS,)),
    (CANCELLATION, (REPORTED_RECEIPTS,)),
    (EXPIRATION, (REPORTED_RECEIPTS,)),
)


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
            raise RuntimeError(f"Lease Security Deposit contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for function in GRANTED:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Lease Security Deposit migration is forward-only")
