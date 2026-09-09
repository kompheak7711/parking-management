"""Read-only Customer financial chronology over retained authoritative facts.

No tables, source mutations, runtime grants, fabricated timestamps or stored balances.
The HTTP boundary is added separately after this projection has been verified.
"""

from alembic import op

revision = "20260909_48"
down_revision = "20260908_47"
branch_labels = None
depends_on = None


def component(
    *,
    kind: str,
    order: int,
    table: str,
    identity: str,
    instant: str,
    customer: str,
    prop: str,
    source: str,
    bucket: str,
    balance_source: str,
    effect: str,
    business_date: str | None = None,
    amount: str = "NULL",
    reference: str = "NULL",
    invoice: str = "NULL",
    line: str = "NULL",
    charge: str = "NULL",
    payment: str = "NULL",
    credit: str = "NULL",
    deposit: str = "NULL",
    refund: str = "NULL",
    category: str = "NULL",
    description: str = "NULL",
    audit: str = "'{}'::jsonb",
) -> str:
    """Assemble static, fully qualified SQL; no user input reaches this builder."""
    day = business_date or (
        f"({instant} AT TIME ZONE (SELECT timezone_name FROM app.properties WHERE id={prop}))::date"
    )
    return f"""
        SELECT {prop}::uuid AS property_id,{customer}::uuid AS customer_id,
            '{kind}'::text AS event_kind,{order}::integer AS event_order,
            {identity}::uuid AS event_id,{instant}::timestamptz AS occurred_at,
            {day} AS business_date,'{table}'::text AS source_table,
            {reference}::text AS source_reference,{amount}::numeric AS recorded_amount_usd_cents,
            {invoice}::uuid AS invoice_id,{line}::uuid AS invoice_line_id,
            {charge}::uuid AS late_payment_charge_id,{payment}::uuid AS payment_id,
            {credit}::uuid AS customer_credit_id,{deposit}::uuid AS deposit_id,
            {refund}::uuid AS refund_id,{bucket}::text AS balance_kind,
            {balance_source}::uuid AS balance_source_id,{effect}::numeric AS effect_usd_cents,
            {category}::text AS category,{description}::text AS description,{audit} AS source_audit
        FROM {source}
    """


def invoice_components() -> list[str]:
    common = dict(customer="i.customer_id", prop="app.invoice_property_id(i.id)", invoice="i.id")
    line = dict(
        line="l.id",
        bucket="'INVOICE'",
        balance_source="l.id",
        category="l.category",
        description="l.description",
    )
    rows = [
        component(
            kind="INVOICE_ISSUED",
            order=10,
            table="invoices",
            identity="i.id",
            instant="i.issued_at",
            business_date="i.invoice_date",
            reference="i.invoice_number",
            source=(
                "app.invoices i JOIN app.invoice_lines l ON "
                "l.invoice_id=i.id WHERE i.issued_at IS NOT NULL"
            ),
            effect="l.amount_usd_cents",
            amount="i.original_total_usd_cents",
            audit="jsonb_build_object('due_date',i.due_date,'lease_id',i.lease_id)",
            **common,
            **line,
        )
    ]
    for reverse in (False, True):
        rows.append(
            component(
                kind="INVOICE_ADJUSTMENT_REVERSED" if reverse else "INVOICE_ADJUSTED",
                order=21 if reverse else 20,
                table="invoice_adjustment_reversals" if reverse else "invoice_adjustments",
                identity="r.id" if reverse else "a.id",
                instant="r.occurred_at" if reverse else "a.occurred_at",
                source="app.invoice_adjustments a JOIN app.invoices i ON i.id=a.invoice_id "
                "JOIN app.invoice_lines l ON l.id=a.invoice_line_id "
                + (
                    "JOIN app.invoice_adjustment_reversals r ON r.invoice_adjustment_id=a.id "
                    if reverse
                    else ""
                )
                + "WHERE i.issued_at IS NOT NULL",
                effect=("-1*" if reverse else "")
                + (
                    "(CASE a.adjustment_type WHEN 'DEBIT' THEN "
                    "a.amount_usd_cents::numeric ELSE "
                    "-a.amount_usd_cents::numeric END)"
                ),
                amount="a.amount_usd_cents",
                reference="i.invoice_number",
                audit="jsonb_build_object('adjustment_id',a.id,'adjustment_type',a.adjustment_type,"
                + (
                    "'reason',r.reason,'reverses_event_id',a.id)"
                    if reverse
                    else "'reason',a.reason,'source_reference',a.source_reference)"
                ),
                **common,
                **line,
            )
        )
    rows.append(
        component(
            kind="INVOICE_VOIDED",
            order=90,
            table="invoice_void_events",
            identity="v.id",
            instant="v.occurred_at",
            reference="i.invoice_number",
            source="app.invoice_void_events v JOIN app.invoices i ON i.id=v.invoice_id "
            "JOIN app.invoice_lines l ON l.invoice_id=i.id WHERE i.issued_at IS NOT NULL",
            effect="-app.invoice_adjusted_line_obligation_at(l.id,v.occurred_at)::numeric",
            audit="jsonb_build_object('reason',v.reason)",
            **common,
            **line,
        )
    )
    # Voiding a never-issued draft is presentation history with no obligation.
    rows.append(
        component(
            kind="DRAFT_INVOICE_VOIDED",
            order=90,
            table="invoice_void_events",
            identity="v.id",
            instant="v.occurred_at",
            reference="i.invoice_number",
            source=(
                "app.invoice_void_events v JOIN app.invoices i ON "
                "i.id=v.invoice_id WHERE i.issued_at IS NULL"
            ),
            bucket="'NONE'",
            balance_source="i.id",
            effect="0",
            audit="jsonb_build_object('reason',v.reason)",
            **common,
        )
    )
    return rows


def charge_components() -> list[str]:
    common = dict(
        customer="c.customer_id",
        prop="app.invoice_property_id(c.source_invoice_id)",
        invoice="c.source_invoice_id",
        charge="c.id",
        bucket="'LATE_PAYMENT_CHARGE'",
        balance_source="c.id",
    )
    return [
        component(
            kind="LATE_PAYMENT_CHARGED",
            order=30,
            table="late_payment_charges",
            identity="c.id",
            instant="c.created_at",
            source="app.late_payment_charges c",
            effect="c.original_amount_usd_cents",
            amount="c.original_amount_usd_cents",
            audit=(
                "jsonb_build_object('payable_at',c.payable_at,'decision_"
                "id',c.late_payment_decision_id)"
            ),
            **common,
        ),
        component(
            kind="LATE_PAYMENT_CORRECTED",
            order=31,
            table="late_payment_charge_corrections",
            identity="r.id",
            instant="r.occurred_at",
            source=(
                "app.late_payment_charge_corrections r JOIN "
                "app.late_payment_charges c ON c.id=r.late_payment_charge_id"
            ),
            effect=(
                "r.resulting_obligation_usd_cents::numeric-r.previous_obligation_usd_cents::numeric"
            ),
            amount="r.amount_usd_cents",
            audit=(
                "jsonb_build_object('correction_kind',r.correction_kind,"
                "'reason',r.reason,'reverses_event_id',r.reverses_correc"
                "tion_id)"
            ),
            **common,
        ),
        component(
            kind="LATE_PAYMENT_WAIVED",
            order=25,
            table="late_payment_decisions",
            identity="d.id",
            instant="d.finalized_at",
            customer="d.customer_id",
            prop="app.invoice_property_id(d.source_invoice_id)",
            invoice="d.source_invoice_id",
            source="app.late_payment_decisions d WHERE d.decision_outcome='WAIVED'",
            bucket="'NONE'",
            balance_source="d.id",
            effect="0",
            amount="d.approved_amount_usd_cents",
            audit="jsonb_build_object('reason',d.reason,'outcome',d.decision_outcome)",
        ),
    ]


def payment_components() -> list[str]:
    common = dict(
        prop="p.property_id",
        customer="p.payer_customer_id",
        payment="p.id",
        reference="p.payment_number",
        bucket="'UNALLOCATED_PAYMENT'",
        balance_source="p.id",
    )
    audit = """jsonb_build_object('received_currency',p.received_currency,
        'received_amount_minor',p.received_amount_minor::text,
        'usd_accounting_value_cents',p.usd_accounting_value_cents::text,
        'payment_scope_kind',p.payment_scope_kind,'payment_method',p.payment_method_name_snapshot,
        'exchange_rate_record_id',p.exchange_rate_record_id,
        'exchange_rate',CASE WHEN fx.id IS NOT NULL THEN jsonb_build_object(
            'reference_rate_khr_per_usd',fx.reference_rate_khr_per_usd::text,
            'markup_basis_points',fx.markup_basis_points::text,
            'system_rate_khr_per_usd',fx.system_rate_khr_per_usd::text,
            'applicable_at',fx.applicable_at,'rate_source',fx.rate_source,
            'channel_actual_currency',fx.channel_actual_currency,
            'channel_actual_amount_minor',fx.channel_actual_amount_minor::text,
            'channel_actual_usd_value_cents',fx.channel_actual_usd_value_cents::text,
            'channel_actual_rate_khr_per_usd',fx.channel_actual_rate_khr_per_usd::text,
            'channel_confirmed_at',fx.channel_confirmed_at) END)"""
    return [
        component(
            kind="PAYMENT_RECEIVED",
            order=40,
            table="payments",
            identity="p.id",
            instant="p.confirmed_at",
            business_date="p.payment_date",
            source=(
                "app.payments p LEFT JOIN app.exchange_rate_records fx ON "
                "fx.id=p.exchange_rate_record_id"
            ),
            effect="p.usd_accounting_value_cents",
            amount="p.usd_accounting_value_cents",
            audit=audit,
            **common,
        ),
        component(
            kind="PAYMENT_REVERSED",
            order=99,
            table="payment_reversals",
            identity="r.id",
            instant="r.occurred_at",
            source="app.payment_reversals r JOIN app.payments p ON p.id=r.payment_id",
            effect="-p.usd_accounting_value_cents::numeric",
            amount="p.usd_accounting_value_cents",
            audit="jsonb_build_object('reason',r.reason,'reverses_event_id',p.id)",
            **common,
        ),
    ]


def application_components(*, credit: bool) -> list[str]:
    rows: list[str] = []
    table = "customer_credit_applications" if credit else "payment_allocations"
    details = "customer_credit_application_details" if credit else "payment_allocation_details"
    detail_fk = "customer_credit_application_id" if credit else "payment_allocation_id"
    reversals = (
        "customer_credit_application_reversals" if credit else "payment_allocation_reversals"
    )
    reversal_fk = "credit_application_id" if credit else "payment_allocation_id"
    paid = "d.applied_amount_usd_cents" if credit else "d.posted_amount_usd_cents"
    source = f"app.{table} a " + (
        (
            "JOIN app.customer_credits c ON c.id=a.customer_credit_id "
            "JOIN app.payments p ON p.id=c.source_payment_id "
        )
        if credit
        else "JOIN app.payments p ON p.id=a.payment_id "
    )
    target_customer = "c.customer_id" if credit else "a.target_customer_id"
    for reverse in (False, True):
        identity = "r.id" if reverse else "a.id"
        instant = "r.occurred_at" if reverse else ("a.occurred_at" if credit else "a.posted_at")
        joins = source + (f"JOIN app.{reversals} r ON r.{reversal_fk}=a.id " if reverse else "")
        kind = (
            ("CREDIT_APPLICATION_REVERSED" if reverse else "CREDIT_APPLIED")
            if credit
            else ("PAYMENT_ALLOCATION_REVERSED" if reverse else "PAYMENT_ALLOCATED")
        )
        audit = (
            "jsonb_build_object('application_id',a.id,'target_kind',a.target_kind,"
            "'target_customer_id'," + target_customer + ","
            "'within_invoice_basis',a.within_invoice_basis"
            + (",'reason',r.reason,'reverses_event_id',a.id)" if reverse else ")")
        )
        common = dict(
            kind=kind,
            order=(71 if reverse else 70) if credit else (51 if reverse else 50),
            table=reversals if reverse else table,
            identity=identity,
            instant=instant,
            prop="p.property_id",
            invoice="a.invoice_id",
            charge="a.late_payment_charge_id",
            payment="p.id",
            credit="c.id" if credit else "NULL",
            amount="a.amount_usd_cents",
            audit=audit,
        )
        # Source consumption belongs to the payer. Target reduction belongs to the
        # obligation owner. Two equal identities still produce exactly one header.
        rows.append(
            component(
                customer="c.customer_id" if credit else "p.payer_customer_id",
                source=joins,
                bucket="'CREDIT'" if credit else "'UNALLOCATED_PAYMENT'",
                balance_source="c.id" if credit else "p.id",
                effect=("" if reverse else "-") + "a.amount_usd_cents::numeric",
                **common,
            )
        )
        rows.append(
            component(
                customer=target_customer,
                source=joins
                + (
                    f"JOIN app.{details} d ON d.{detail_fk}=a.id "
                    "LEFT JOIN app.invoice_lines l ON l.id=d.invoice_line_id"
                ),
                bucket=(
                    "CASE WHEN d.invoice_line_id IS NOT NULL THEN 'INVOICE' ELSE "
                    "'LATE_PAYMENT_CHARGE' END"
                ),
                balance_source="COALESCE(d.invoice_line_id,d.late_payment_charge_id)",
                effect=("" if reverse else "-") + paid + "::numeric",
                line="d.invoice_line_id",
                category="d.invoice_line_category_snapshot",
                description="l.description",
                **common,
            )
        )
    return rows


def credit_components() -> list[str]:
    rows: list[str] = []
    for reverse in (False, True):
        joins = "app.customer_credits c JOIN app.payments p ON p.id=c.source_payment_id " + (
            "JOIN app.customer_credit_reversals r ON r.customer_credit_id=c.id" if reverse else ""
        )
        common = dict(
            kind="CREDIT_RECOGNITION_REVERSED" if reverse else "CREDIT_RECOGNIZED",
            order=61 if reverse else 60,
            table="customer_credit_reversals" if reverse else "customer_credits",
            identity="r.id" if reverse else "c.id",
            instant="r.occurred_at" if reverse else "c.recognized_at",
            prop="p.property_id",
            source=joins,
            credit="c.id",
            payment="p.id",
            amount="c.recognized_usd_cents",
            audit="jsonb_build_object('reason',"
            + ("r.reason,'reverses_event_id',c.id)" if reverse else "c.reason)"),
        )
        rows.append(
            component(
                customer="c.customer_id",
                bucket="'CREDIT'",
                balance_source="c.id",
                effect=("-" if reverse else "") + "c.recognized_usd_cents::numeric",
                **common,
            )
        )
        rows.append(
            component(
                customer="p.payer_customer_id",
                bucket="'UNALLOCATED_PAYMENT'",
                balance_source="p.id",
                effect=("" if reverse else "-") + "c.recognized_usd_cents::numeric",
                **common,
            )
        )
    return rows


def deposit_components() -> list[str]:
    rows: list[str] = []
    common = dict(
        customer="d.customer_id",
        prop="app.deposit_property_id(d.id)",
        deposit="d.id",
        bucket="CASE d.deposit_type WHEN 'SECURITY' THEN 'SECURITY_DEPOSIT' ELSE 'PET_DEPOSIT' END",
        balance_source="d.id",
    )
    # Required amounts are evidence, not received liabilities or Invoice obligations.
    rows.append(
        component(
            kind="DEPOSIT_REQUIREMENT_ADJUSTED",
            order=22,
            table="deposit_required_amount_adjustments",
            identity="a.id",
            instant="a.occurred_at",
            business_date="a.effective_date",
            customer="d.customer_id",
            prop="app.deposit_property_id(d.id)",
            deposit="d.id",
            bucket="'NONE'",
            balance_source="d.id",
            effect="0",
            amount="a.amount_usd_cents",
            source=(
                "app.deposit_required_amount_adjustments a JOIN app.deposits d ON d.id=a.deposit_id"
            ),
            audit=(
                "jsonb_build_object('reason',a.reason,'adjustment_type',"
                "a.adjustment_type,'deposit_type',d.deposit_type)"
            ),
        )
    )
    for reverse in (False, True):
        joins = (
            "app.deposit_receipts a JOIN app.deposits d ON "
            "d.id=a.deposit_id JOIN app.payments p ON p.id=a.payment_id "
        ) + ("JOIN app.deposit_receipt_reversals r ON r.deposit_receipt_id=a.id" if reverse else "")
        base = dict(
            kind="DEPOSIT_RECEIPT_REVERSED" if reverse else "DEPOSIT_RECEIVED",
            order=46 if reverse else 45,
            table="deposit_receipt_reversals" if reverse else "deposit_receipts",
            identity="r.id" if reverse else "a.id",
            instant="r.occurred_at" if reverse else "a.occurred_at",
            source=joins,
            payment="p.id",
            amount="a.amount_usd_cents",
            audit="jsonb_build_object('deposit_type',d.deposit_type"
            + (",'reason',r.reason,'reverses_event_id',a.id)" if reverse else ")"),
        )
        rows.append(
            component(
                effect=("-" if reverse else "") + "a.amount_usd_cents::numeric", **base, **common
            )
        )
        rows.append(
            component(
                effect=("" if reverse else "-") + "a.amount_usd_cents::numeric",
                **base,
                **(
                    common
                    | dict(
                        customer="p.payer_customer_id",
                        prop="p.property_id",
                        bucket="'UNALLOCATED_PAYMENT'",
                        balance_source="p.id",
                    )
                ),
            )
        )
        joins = "app.deposit_dispositions a JOIN app.deposits d ON d.id=a.deposit_id " + (
            "JOIN app.deposit_disposition_reversals r ON r.deposit_disposition_id=a.id"
            if reverse
            else ""
        )
        rows.append(
            component(
                kind="DEPOSIT_DISPOSITION_REVERSED" if reverse else "DEPOSIT_DISPOSED",
                order=81 if reverse else 80,
                table="deposit_disposition_reversals" if reverse else "deposit_dispositions",
                identity="r.id" if reverse else "a.id",
                instant="r.occurred_at" if reverse else "a.occurred_at",
                source=joins,
                amount="a.amount_usd_cents",
                effect=("" if reverse else "-") + "a.amount_usd_cents::numeric",
                audit=(
                    "jsonb_build_object('deposit_type',d.deposit_type,'effec"
                    "tive_date',a.effective_date,'reason',"
                )
                + ("r.reason,'reverses_event_id',a.id)" if reverse else "a.reason)"),
                **common,
            )
        )
    return rows


def refund_components() -> list[str]:
    rows: list[str] = []
    for correction in (False, True):
        joins = (
            "app.refunds f LEFT JOIN app.deposits d ON "
            "d.id=f.source_deposit_id\n"
            "            LEFT JOIN app.customer_credits c ON "
            "c.id=f.source_customer_credit_id\n"
            "            LEFT JOIN app.payments p ON "
            "p.id=COALESCE(f.source_payment_id,c.source_payment_id) "
        ) + ("JOIN app.refund_corrections r ON r.refund_id=f.id" if correction else "")
        rows.append(
            component(
                kind="REFUND_CORRECTED" if correction else "REFUND_PAID",
                order=83 if correction else 82,
                table="refund_corrections" if correction else "refunds",
                identity="r.id" if correction else "f.id",
                instant="r.occurred_at" if correction else "f.processed_at",
                customer="f.recipient_customer_id",
                prop="COALESCE(p.property_id,app.deposit_property_id(d.id))",
                source=joins,
                bucket=(
                    "CASE WHEN f.source_payment_id IS NOT NULL THEN "
                    "'UNALLOCATED_PAYMENT' WHEN c.id IS NOT NULL THEN 'CREDIT' "
                    "WHEN d.deposit_type='SECURITY' THEN 'SECURITY_DEPOSIT' ELSE "
                    "'PET_DEPOSIT' END"
                ),
                balance_source="COALESCE(f.source_payment_id,c.id,d.id)",
                effect="r.source_balance_effect_usd_cents"
                if correction
                else "-f.usd_accounting_value_cents::numeric",
                amount="abs(r.source_balance_effect_usd_cents::numeric)"
                if correction
                else "f.usd_accounting_value_cents",
                reference="f.refund_number",
                payment="p.id",
                credit="c.id",
                deposit="d.id",
                refund="f.id",
                audit="jsonb_build_object('currency',f.refund_currency,'reason',"
                + (
                    (
                        "r.reason,'correction_kind',r.correction_kind,'verified_"
                        "return_currency',r.verified_return_currency,'verified_r"
                        "eturn_amount_minor',r.verified_return_amount_minor::tex"
                        "t,'verified_returned_at',r.verified_returned_at,'revers"
                        "es_event_id',r.reverses_correction_id)"
                    )
                    if correction
                    else "f.reason,'refund_amount_minor',f.refund_amount_minor::text)"
                ),
            )
        )
    return rows


def upgrade() -> None:
    rows = invoice_components() + charge_components() + payment_components()
    rows += application_components(credit=False) + credit_components()
    rows += application_components(credit=True) + deposit_components() + refund_components()
    op.execute(
        "CREATE VIEW app.customer_ledger_effects WITH(security_invoker=true) AS "
        + " UNION ALL ".join(rows)
    )
    op.execute(
        "\n"
        "        CREATE VIEW app.customer_account_ledger "
        "WITH(security_invoker=true) AS\n"
        "        SELECT property_id,customer_id,event_kind,event"
        "_order,event_id,occurred_at,business_date,\n"
        "            source_table,source_reference,recorded_amou"
        "nt_usd_cents,invoice_id,late_payment_charge_id,\n"
        "            payment_id,customer_credit_id,deposit_id,re"
        "fund_id,source_audit,count(*) AS component_count,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='INVOICE'),0) AS invoice_effect_usd_cents,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='LATE_PAYMENT_CHARGE'),0) AS "
        "charge_effect_usd_cents,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='CREDIT'),0) AS credit_effect_usd_cents,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='UNALLOCATED_PAYMENT'),0) AS "
        "payment_effect_usd_cents,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='SECURITY_DEPOSIT'),0) AS "
        "security_deposit_effect_usd_cents,\n"
        "            COALESCE(sum(effect_usd_cents) FILTER(WHERE "
        "balance_kind='PET_DEPOSIT'),0) AS "
        "pet_deposit_effect_usd_cents\n"
        "        FROM app.customer_ledger_effects\n"
        "        GROUP BY property_id,customer_id,event_kind,eve"
        "nt_order,event_id,occurred_at,business_date,\n"
        "            source_table,source_reference,recorded_amou"
        "nt_usd_cents,invoice_id,late_payment_charge_id,\n"
        "            payment_id,customer_credit_id,deposit_id,re"
        "fund_id,source_audit;\n"
        "\n"
        "        CREATE VIEW app.customer_ledger_history "
        "WITH(security_invoker=true) AS\n"
        "        SELECT e.*,\n"
        "            sum(invoice_effect_usd_cents) OVER w AS "
        "invoice_after_usd_cents,\n"
        "            sum(charge_effect_usd_cents) OVER w AS "
        "charge_after_usd_cents,\n"
        "            sum(credit_effect_usd_cents) OVER w AS "
        "credit_after_usd_cents,\n"
        "            sum(payment_effect_usd_cents) OVER w AS "
        "payment_after_usd_cents,\n"
        "            sum(security_deposit_effect_usd_cents) OVER w "
        "AS security_deposit_after_usd_cents,\n"
        "            sum(pet_deposit_effect_usd_cents) OVER w AS "
        "pet_deposit_after_usd_cents\n"
        "        FROM app.customer_account_ledger e\n"
        "        WINDOW w AS (PARTITION BY property_id,customer_id "
        "ORDER BY occurred_at\n"
        "            RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT "
        "ROW);\n"
        "        COMMENT ON VIEW app.customer_ledger_history IS\n"
        "            'Position after all committed source events at "
        "the displayed instant, including equal-time peers. Display "
        "order uses occurred_at,event_order,event_kind,event_id. "
        "Filters apply after this history projection.';\n"
        "\n"
        "        CREATE VIEW app.customer_ledger_balance_sources "
        "WITH(security_invoker=true) AS\n"
        "        SELECT app.invoice_property_id(i.id) AS "
        "property_id,i.customer_id,'INVOICE'::text AS balance_kind,\n"
        "            l.id AS balance_source_id,i.id AS "
        "invoice_id,l.id AS invoice_line_id,NULL::uuid AS "
        "late_payment_charge_id,\n"
        "            l.category,l.description,app.invoice_line_o"
        "utstanding(l.id)::numeric AS balance_usd_cents\n"
        "        FROM app.invoices i JOIN app.invoice_lines l ON "
        "l.invoice_id=i.id\n"
        "        WHERE i.issued_at IS NOT NULL AND i.status<>'VOID'\n"
        "        UNION ALL SELECT "
        "app.invoice_property_id(c.source_invoice_id),c.customer"
        "_id,'LATE_PAYMENT_CHARGE',\n"
        "            c.id,c.source_invoice_id,NULL,c.id,'LATE_PA"
        "YMENT_CHARGE','Late-payment "
        "charge',p.remaining_balance_usd_cents::numeric\n"
        "            FROM app.late_payment_charges c JOIN "
        "app.late_payment_charge_financial_position p ON "
        "p.late_payment_charge_id=c.id\n"
        "        UNION ALL SELECT "
        "p.property_id,c.customer_id,'CREDIT',c.id,NULL,NULL,NUL"
        "L,NULL,NULL,app.credit_available_value(c.id)::numeric\n"
        "            FROM app.customer_credits c JOIN app.payments p "
        "ON p.id=c.source_payment_id\n"
        "        UNION ALL SELECT "
        "p.property_id,p.payer_customer_id,'UNALLOCATED_PAYMENT'"
        ",p.id,NULL,NULL,NULL,NULL,NULL,\n"
        "            app.payment_available_value(p.id)::numeric FROM "
        "app.payments p\n"
        "        UNION ALL SELECT "
        "app.deposit_property_id(d.id),d.customer_id,\n"
        "            CASE d.deposit_type WHEN 'SECURITY' THEN "
        "'SECURITY_DEPOSIT' ELSE 'PET_DEPOSIT' END,\n"
        "            d.id,NULL,NULL,NULL,NULL,NULL,app.deposit_h"
        "eld_value_at(d.id,'infinity')::numeric FROM app.deposits d;\n"
        "\n"
        "        CREATE VIEW app.customer_financial_position "
        "WITH(security_invoker=true) AS\n"
        "        SELECT property_id,customer_id,\n"
        "            COALESCE(sum(greatest(balance_usd_cents,0)) "
        "FILTER(WHERE balance_kind='INVOICE'),0) AS "
        "invoice_outstanding_usd_cents,\n"
        "            COALESCE(sum(greatest(balance_usd_cents,0)) "
        "FILTER(WHERE balance_kind='LATE_PAYMENT_CHARGE'),0) AS "
        "charge_outstanding_usd_cents,\n"
        "            COALESCE(sum(greatest(balance_usd_cents,0)) "
        "FILTER(WHERE balance_kind "
        "IN('INVOICE','LATE_PAYMENT_CHARGE')),0) AS "
        "total_owed_usd_cents,\n"
        "            COALESCE(sum(balance_usd_cents) FILTER(WHERE "
        "balance_kind='CREDIT'),0) AS available_credit_usd_cents,\n"
        "            COALESCE(sum(balance_usd_cents) FILTER(WHERE "
        "balance_kind='UNALLOCATED_PAYMENT'),0) AS "
        "unallocated_payment_usd_cents,\n"
        "            COALESCE(sum(balance_usd_cents) FILTER(WHERE "
        "balance_kind='SECURITY_DEPOSIT'),0) AS "
        "security_deposit_held_usd_cents,\n"
        "            COALESCE(sum(balance_usd_cents) FILTER(WHERE "
        "balance_kind='PET_DEPOSIT'),0) AS "
        "pet_deposit_held_usd_cents\n"
        "        FROM app.customer_ledger_balance_sources GROUP BY "
        "property_id,customer_id;\n"
        "    "
    )
    for view in (
        "customer_ledger_effects",
        "customer_account_ledger",
        "customer_ledger_history",
        "customer_ledger_balance_sources",
        "customer_financial_position",
    ):
        op.execute(
            f"REVOKE ALL ON TABLE app.{view} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Customer ledger projections are forward-only; downgrade is not supported")
