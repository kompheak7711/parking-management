"""Explicit synthetic Payment evidence for current-head financial tests only."""

from datetime import datetime
from uuid import UUID, uuid4

from psycopg import Connection


def seed_method(connection: Connection[tuple[object, ...]], actor_id: UUID) -> UUID:
    """Use an accepted fixture method, or explicitly configure one for the test."""
    method = connection.execute(
        "SELECT id FROM app.payment_methods WHERE accepted ORDER BY code LIMIT 1"
    ).fetchone()
    if method is not None:
        return UUID(str(method[0]))
    identity = uuid4()
    connection.execute(
        "INSERT INTO app.payment_methods(id,code,display_name,accepted,created_by,updated_by) "
        "VALUES (%s,%s,'Synthetic cash method',true,%s,%s)",
        (identity, f"TEST-{identity}", actor_id, actor_id),
    )
    return identity


def seed_payment(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    customer_id: UUID,
    amount: int,
    payment_id: UUID | None = None,
    confirmed_at: datetime | None = None,
    lease_id: UUID | None = None,
    scope: str = "NORMAL_CUSTOMER",
    invoice_id: UUID | None = None,
) -> UUID:
    """Create a real synthetic USD receipt; old-revision tests retain old schema."""
    identity = payment_id or uuid4()
    if connection.execute("SELECT to_regclass('app.payments')").fetchone() == (None,):
        return identity
    method = seed_method(connection, actor_id)
    connection.execute(
        """
        INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,
            payment_scope_kind,payment_date,payment_method_id,received_currency,
            received_amount_minor,usd_accounting_value_cents,confirmed_at,
            confirmed_by,authorization_reference,lease_id,identified_invoice_id)
        VALUES (%s,%s,%s,%s,%s,
            (COALESCE(%s,clock_timestamp()) AT TIME ZONE 'Asia/Phnom_Penh')::date,
            %s,'USD',%s,%s,COALESCE(%s,clock_timestamp()),%s,'payments.record',%s,%s)
        """,
        (
            identity,
            f"TEST-{identity}",
            property_id,
            customer_id,
            scope,
            confirmed_at,
            method,
            amount,
            amount,
            confirmed_at,
            actor_id,
            lease_id,
            invoice_id,
        ),
    )
    return identity


def seed_deposit_payment(
    connection: Connection[tuple[object, ...]],
    *,
    deposit_id: UUID,
    actor_id: UUID,
    amount: int,
    confirmed_at: datetime | None = None,
) -> UUID:
    """Provide the exact synthetic source for an existing Deposit receipt."""
    if connection.execute("SELECT to_regclass('app.payments')").fetchone() == (None,):
        return uuid4()
    source = connection.execute(
        "SELECT app.deposit_property_id(id),customer_id FROM app.deposits WHERE id=%s",
        (deposit_id,),
    ).fetchone()
    assert source is not None
    return seed_payment(
        connection,
        actor_id=actor_id,
        property_id=UUID(str(source[0])),
        customer_id=UUID(str(source[1])),
        amount=amount,
        confirmed_at=confirmed_at,
    )
