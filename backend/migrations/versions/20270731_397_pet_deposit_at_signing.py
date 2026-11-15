"""The Pet Deposit for a pet kept from the start is received at Sign Lease (D4, DL-234).

Owner (12 Nov 2026, DL-226, D4). Before, the Pet Deposit was due within five days after the
Lease Start Date and staff made it and received it by hand after the signing (BR-DEP-010).
Now it is received at Sign Lease, with the Security Deposit and the Initial Rent.

What changes (BR-DEP-010, BR-DEP-006):

- New append-only table ``app.lease_planned_pet_deposits``: each save of the draft's Pet Deposit
  amount, as ``app.lease_planned_security_deposits`` keeps the Security Deposit (DL-101). The
  latest row wins.
- New ``app.set_lease_planned_pet_deposit`` (SECURITY DEFINER, EXECUTE to prm_runtime; right
  ``leases.draft``) saves the amount on a drafted Lease that is not a renewal and whose terms
  approve a pet with a Pet Deposit.
- ``app.lease_signing_preview`` also gives ``pet_deposit_required`` and
  ``planned_pet_deposit_usd_cents``.
- ``app.sign_lease_with_payment``: the total due at signing is the Initial Rent + the Security
  Deposit still to pay + the Pet Deposit. A draft whose terms ask for a Pet Deposit is not
  signed until its amount is recorded, and the person needs the right to manage deposits. The
  signing makes the Pet Deposit for the approved pet and receives it in full from the same
  Payment. The result adds ``pet_deposit_usd_cents``, ``pet_deposit_id`` and
  ``pet_deposit_receipt_id``.

A renewal takes no Pet Deposit at signing, as before. A pet approved after the signing keeps
the step by hand. No row is changed or deleted. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270731_397"
down_revision: str | None = "20270730_396"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = r"""
CREATE TABLE app.lease_planned_pet_deposits (
    id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
    property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
    lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
    required_usd_cents bigint NOT NULL
        CHECK (required_usd_cents BETWEEN 1 AND 9000000000000000),
    reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
    actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
    audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
    recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at))
);
COMMENT ON TABLE app.lease_planned_pet_deposits IS
    'The Pet Deposit a draft Lease takes at signing (D4, DL-234); latest row wins';
CREATE INDEX lease_planned_pet_deposits_lease_idx
    ON app.lease_planned_pet_deposits(lease_id, recorded_at, id);
CREATE TRIGGER lease_planned_pet_deposits_reject_mutation BEFORE UPDATE OR DELETE
    ON app.lease_planned_pet_deposits FOR EACH ROW
    EXECUTE FUNCTION app.reject_lease_append_only_mutation();
CREATE TRIGGER lease_planned_pet_deposits_reject_truncate BEFORE TRUNCATE
    ON app.lease_planned_pet_deposits FOR EACH STATEMENT
    EXECUTE FUNCTION app.reject_lease_storage_truncate();
REVOKE ALL ON app.lease_planned_pet_deposits FROM PUBLIC, prm_runtime, prm_bootstrap;

CREATE FUNCTION app.lease_planned_pet_deposit(p_lease_id uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT planned.required_usd_cents FROM app.lease_planned_pet_deposits AS planned
    WHERE planned.lease_id = p_lease_id
    ORDER BY planned.recorded_at DESC, planned.id DESC LIMIT 1
$$;
REVOKE ALL ON FUNCTION app.lease_planned_pet_deposit(uuid) FROM PUBLIC;

-- The pet approval whose Pet Deposit the signing takes: the latest approval of a Lease that is
-- not a renewal, when its terms ask for a Pet Deposit. Empty when the signing takes none.
CREATE FUNCTION app.lease_signing_pet_approval_id(p_lease_id uuid) RETURNS uuid
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT approval.id FROM app.lease_pet_approvals AS approval
    JOIN app.leases AS lease ON lease.id = approval.lease_id
    WHERE approval.lease_id = p_lease_id AND lease.predecessor_lease_id IS NULL
      AND approval.deposit_required_by_signed_terms
    ORDER BY approval.approved_date DESC, approval.approved_at DESC, approval.id DESC LIMIT 1
$$;
REVOKE ALL ON FUNCTION app.lease_signing_pet_approval_id(uuid) FROM PUBLIC;

CREATE FUNCTION app.lease_signing_pet_terms(p_lease_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object(
        'pet_deposit_required', app.lease_signing_pet_approval_id(p_lease_id) IS NOT NULL,
        'planned_pet_deposit_usd_cents', app.lease_planned_pet_deposit(p_lease_id))
$$;
REVOKE ALL ON FUNCTION app.lease_signing_pet_terms(uuid) FROM PUBLIC;

CREATE FUNCTION app.set_lease_planned_pet_deposit(
    p_property_id uuid, p_lease_id uuid, p_id uuid, p_actor_id uuid,
    p_required_usd_cents bigint, p_reason text, p_authorization_reference text
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_lease app.leases%ROWTYPE;
    v_saved app.lease_planned_pet_deposits%ROWTYPE;
    v_timezone text;
    v_before bigint;
    v_now timestamptz := clock_timestamp();
    v_audit uuid := gen_random_uuid();
BEGIN
    IF p_property_id IS NULL OR p_lease_id IS NULL OR p_actor_id IS NULL
        OR p_id IS NULL OR p_id = '00000000-0000-0000-0000-000000000000'::uuid
        OR p_authorization_reference IS DISTINCT FROM 'leases.draft'
        OR p_required_usd_cents IS NULL
        OR p_required_usd_cents NOT BETWEEN 1 AND 9000000000000000
        OR p_reason IS NULL OR p_reason <> btrim(p_reason)
        OR length(p_reason) NOT BETWEEN 1 AND 500
    THEN
        RAISE EXCEPTION 'Planned Pet Deposit evidence is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM app.user_accounts AS account
    WHERE account.actor_id = p_actor_id AND account.lifecycle_state = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'An active user saves a planned Pet Deposit' USING ERRCODE = '55000';
    END IF;
    SELECT lease.* INTO v_lease FROM app.leases AS lease
    JOIN app.units AS unit ON unit.id = lease.unit_id
    WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
    FOR UPDATE OF lease;
    IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
    -- The same identity again is a replay of the same save only.
    SELECT planned.* INTO v_saved FROM app.lease_planned_pet_deposits AS planned
    WHERE planned.id = p_id;
    IF FOUND THEN
        IF v_saved.property_id <> p_property_id OR v_saved.lease_id <> p_lease_id
            OR v_saved.required_usd_cents <> p_required_usd_cents
            OR v_saved.reason <> p_reason
        THEN
            RAISE EXCEPTION 'This Pet Deposit save was already used for another amount'
                USING ERRCODE = '23505';
        END IF;
        RETURN app.lease_planned_pet_deposit(p_lease_id);
    END IF;
    IF v_lease.status <> 'DRAFTED' THEN
        RAISE EXCEPTION 'Only a drafted Lease takes a planned Pet Deposit' USING ERRCODE = '55000';
    END IF;
    IF v_lease.predecessor_lease_id IS NOT NULL THEN
        RAISE EXCEPTION 'A renewal Lease takes no Pet Deposit at signing' USING ERRCODE = '55000';
    END IF;
    IF app.lease_signing_pet_approval_id(p_lease_id) IS NULL THEN
        RAISE EXCEPTION 'The Lease terms ask for no Pet Deposit' USING ERRCODE = '55000';
    END IF;
    v_before := app.lease_planned_pet_deposit(p_lease_id);
    IF v_before IS NOT DISTINCT FROM p_required_usd_cents THEN RETURN v_before; END IF;
    SELECT property.timezone_name INTO v_timezone
    FROM app.properties AS property WHERE property.id = p_property_id;
    INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
        entity_type, entity_id, reason, authorization_reference, property_id,
        previous_state, resulting_state, correlation_id, source, outcome,
        authorization_evidence, customer_id, lease_id, unit_id)
    VALUES (v_audit, v_now, timezone(v_timezone, v_now)::date, p_actor_id,
        'lease.pet_deposit.planned', 'lease_planned_pet_deposit', p_id,
        p_reason, p_authorization_reference, p_property_id,
        jsonb_build_object('required_usd_cents', v_before),
        jsonb_build_object('required_usd_cents', p_required_usd_cents),
        p_id, 'API', 'SUCCEEDED',
        jsonb_build_object('capability', p_authorization_reference, 'lease_id', p_lease_id),
        v_lease.primary_tenant_id, p_lease_id, v_lease.unit_id);
    INSERT INTO app.lease_planned_pet_deposits(id, property_id, lease_id,
        required_usd_cents, reason, actor_id, audit_event_id, recorded_at)
    VALUES (p_id, p_property_id, p_lease_id, p_required_usd_cents, p_reason, p_actor_id,
        v_audit, v_now);
    RETURN p_required_usd_cents;
END $$;
REVOKE ALL ON FUNCTION
    app.set_lease_planned_pet_deposit(uuid, uuid, uuid, uuid, bigint, text, text)
    FROM PUBLIC, prm_runtime, prm_bootstrap;
GRANT EXECUTE ON FUNCTION
    app.set_lease_planned_pet_deposit(uuid, uuid, uuid, uuid, bigint, text, text)
    TO prm_runtime;
"""

PREVIEW = "app.lease_signing_preview(uuid, uuid)"
PREVIEW_PET = (
    (
        "app.lease_planned_security_deposit(p_lease_id))",
        "app.lease_planned_security_deposit(p_lease_id))\n"
        "                || app.lease_signing_pet_terms(p_lease_id)",
        2,
    ),
)

SIGN = (
    "app.sign_lease_with_payment("
    "uuid, uuid, uuid, text, uuid, integer, uuid[], text, jsonb, boolean)"
)
SIGN_PET = (
    (
        "v_result jsonb;",
        "v_result jsonb;\n"
        "            v_pet_approval uuid;\n"
        "            v_pet bigint := 0;\n"
        "            v_pet_date date;\n"
        "            v_pet_id uuid;\n"
        "            v_pet_receipt uuid;",
        1,
    ),
    (
        "v_total := v_rent + v_deposit;",
        """-- D4 (DL-234): the Pet Deposit of a pet kept from the start is received at signing.
            v_pet_approval := app.lease_signing_pet_approval_id(p_lease_id);
            IF v_pet_approval IS NOT NULL THEN
                v_pet := app.lease_planned_pet_deposit(p_lease_id);
                IF v_pet IS NULL THEN
                    RAISE EXCEPTION 'Record the Pet Deposit on the draft first'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT p_may_create_deposit THEN
                    RAISE EXCEPTION 'A Pet Deposit made at signing needs deposits.manage'
                        USING ERRCODE = '42501';
                END IF;
            END IF;
            v_total := v_rent + v_deposit + v_pet;""",
        1,
    ),
    (
        "SET CONSTRAINTS ALL IMMEDIATE;",
        """-- 7. D4 (DL-234): the Pet Deposit for the approved pet, made at the draft's amount and
            -- received in full from the same Payment.
            IF v_pet > 0 THEN
                SET CONSTRAINTS ALL DEFERRED;
                SELECT GREATEST(v_today, approval.approved_date) INTO STRICT v_pet_date
                FROM app.lease_pet_approvals AS approval WHERE approval.id = v_pet_approval;
                v_pet_id := gen_random_uuid();
                PERFORM app.create_pet_deposit_v2(p_property_id, p_actor_id,
                    md5('lease-sign-payment:pet:' || v_scope)::uuid,
                    encode(sha256(convert_to('lease-sign-payment:pet:' || p_digest, 'UTF8')),
                        'hex'),
                    v_pet_id, p_lease_id, v_pet_approval, v_pet, v_pet_date,
                    'Pet Deposit agreed on the draft Lease, received at signing.',
                    'deposits.manage');
                v_pet_receipt := gen_random_uuid();
                PERFORM app.record_lease_deposit_receipt(p_property_id, p_actor_id,
                    md5('lease-sign-payment:pet-receipt:' || v_scope)::uuid,
                    encode(sha256(convert_to('lease-sign-payment:pet-receipt:' || p_digest,
                        'UTF8')), 'hex'),
                    v_pet_receipt, v_pet_id, v_payment.id, v_pet,
                    'Pet Deposit received at signing.', 'payments.allocate');
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;""",
        1,
    ),
    (
        "'deposit_receipt_id', v_deposit_receipt);",
        "'deposit_receipt_id', v_deposit_receipt,\n"
        "                'pet_deposit_usd_cents', v_pet,\n"
        "                'pet_deposit_id', v_pet_id,\n"
        "                'pet_deposit_receipt_id', v_pet_receipt);",
        1,
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _changed(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> str:
    definition = _definition(signature)
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Pet Deposit source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def upgrade() -> None:
    _run(TABLE)
    _run(_changed(PREVIEW, PREVIEW_PET))
    _run(_changed(SIGN, SIGN_PET))


def downgrade() -> None:
    raise RuntimeError("the Pet Deposit at signing migration is forward-only")
