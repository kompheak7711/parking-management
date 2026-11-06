"""Daily and weekly rent, phase 7 (owner test 06/11/2026): a Refund button after a free cancel.

A free cancel turns the money paid into Customer Credit of the guest (step 4b); the desk then pays
it back with the usual Refund, a draft that a ``financial.approve`` holder confirms. The owner chose
(06/11/2026 03:20, card "How should a free cancel give the money back to the guest?") a Refund
button on the cancelled booking, so staff no longer look for the Credit.

The booking read now carries ``refund`` after a free cancel:

- ``credits``: each Customer Credit the free cancel made, with what is left of it;
- ``left_usd_cents``: what is left to give back;
- ``waiting_usd_cents``: Refund drafts of those Credits still waiting for approval;
- ``refunded_usd_cents``: what was given back already.

The button records a Refund draft of each Credit through the existing Refund draft route, so the
approval, the Refund number and the trail stay as for every Refund. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270611_351"
down_revision: str | None = "20270610_350"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = r"""
-- The Customer Credits a free cancel made: the paid money of each credit adjustment.
CREATE FUNCTION app.short_stay_refund_sources(p_booking uuid) RETURNS SETOF uuid
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT DISTINCT coalesce(released.customer_credit_id, application.customer_credit_id)
    FROM app.invoice_credit_excess_releases AS released
    JOIN app.invoice_adjustments AS adjustment ON adjustment.id = released.invoice_adjustment_id
    LEFT JOIN app.customer_credit_applications AS application
        ON application.id = released.reversed_credit_application_id
    WHERE adjustment.reason = 'Free cancel: the money paid comes back'
      AND adjustment.invoice_id IN (SELECT app.short_stay_invoices(p_booking))
$$;
REVOKE ALL ON FUNCTION app.short_stay_refund_sources(uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_refund_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN count(*) = 0 THEN NULL ELSE jsonb_build_object(
        'credits', jsonb_agg(jsonb_build_object('credit_id', item.id,
            'left_usd_cents', item.left_cents) ORDER BY item.id),
        'left_usd_cents', sum(item.left_cents),
        'waiting_usd_cents', sum(item.waiting_cents),
        'refunded_usd_cents', sum(item.refunded_cents)) END
    FROM (
        SELECT source.id,
            greatest(app.credit_available_value(source.id), 0) AS left_cents,
            coalesce((SELECT sum((draft.payload ->> 'amount_usd_cents')::bigint)
                FROM app.financial_drafts AS draft
                WHERE draft.kind = 'REFUND' AND draft.payload ->> 'source_kind' = 'CREDIT'
                  AND draft.payload ->> 'source_id' = source.id::text
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions AS decision
                                  WHERE decision.draft_id = draft.id)), 0) AS waiting_cents,
            coalesce((SELECT sum(refund.usd_accounting_value_cents) FROM app.refunds AS refund
                WHERE refund.source_customer_credit_id = source.id), 0) AS refunded_cents
        FROM app.short_stay_refund_sources(p_booking) AS source(id)
        WHERE source.id IS NOT NULL
    ) AS item
$$;
REVOKE ALL ON FUNCTION app.short_stay_refund_json(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT found.booking || CASE WHEN jsonb_typeof(found.booking -> 'credit') = 'object'
        THEN jsonb_build_object('credit', (found.booking -> 'credit') || jsonb_build_object(
            'left_usd_cents', app.short_stay_credit_left(p_booking),
            'ended', (SELECT jsonb_build_object('left_usd_cents', ended.left_usd_cents,
                    'invoice_id', ended.invoice_id, 'invoice_number', invoice.invoice_number,
                    'at', ended.ended_at)
                FROM app.short_stay_credit_ends AS ended
                LEFT JOIN app.invoices AS invoice ON invoice.id = ended.invoice_id
                WHERE ended.booking_id = p_booking)))
        ELSE '{}'::jsonb END
        || jsonb_build_object('refund', app.short_stay_refund_json(p_booking))
    FROM (SELECT app.short_stay_booking_guest_json(p_booking) AS booking) AS found
$$;
"""


def upgrade() -> None:
    op.execute(FUNCTIONS)


def downgrade() -> None:
    raise NotImplementedError("Short-stay migrations are forward-only")
