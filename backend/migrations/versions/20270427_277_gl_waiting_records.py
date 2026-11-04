# ruff: noqa: E501
"""General Ledger "Needs check" shows every record that cannot post yet (phase 6 step 6 fix).

Owner test 04/11/2026: balanced Opening balances were refused with "Clear the Needs check list
first" while the screen showed nothing waiting. ``app.gl_post_opening_balances`` refuses for the
records kept in ``app.gl_posting_problems`` and also for app records whose problem the posting
job has not met yet (it runs with the billing worker). The screens read only the kept list.

- ``app.gl_waiting_records(property)``: the kept list, plus every app record from the ledger's
  first day to today that has a problem, has no ledger entry and is not kept yet (seen now).
  The Opening balances sheet counts it and the Needs check list shows it, so both agree with
  the refusal. Read only; nothing here writes, and the posting job still keeps the list.

The runtime login cannot read ``app.gl_app_record_events`` by itself, so this reads it for the
route, which has checked ``ledger.read``. Technical choice by Claude under the owner's
2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270427_277"
down_revision: str | None = "20270426_276"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "app.gl_waiting_records(uuid)"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.gl_waiting_records(p_property uuid)
        RETURNS TABLE (posting_key text, source_type text, source_id uuid, event_date date,
            problem text, first_seen_at timestamptz, last_seen_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT kept.posting_key, kept.source_type, kept.source_id, kept.event_date,
                kept.problem, kept.first_seen_at, kept.last_seen_at
            FROM app.gl_posting_problems AS kept
            WHERE kept.property_id = p_property
            UNION ALL
            SELECT event.posting_key, event.source_type, event.source_id, event.event_date,
                event.problem, statement_timestamp(), statement_timestamp()
            FROM (SELECT min(period.starts_on) AS day FROM app.gl_periods AS period
                  WHERE period.property_id = p_property) AS start
            CROSS JOIN LATERAL app.gl_app_record_events(p_property, start.day,
                app.gl_today(p_property)) AS event
            WHERE start.day IS NOT NULL AND event.problem IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM app.gl_posting_problems AS known
                  WHERE known.posting_key = event.posting_key)
              AND NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
                  WHERE entry.posting_key = event.posting_key)
        $$;
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC; "
        f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO prm_runtime"
    )


def downgrade() -> None:
    """A read only, so removing it loses nothing."""
    op.execute(f"DROP FUNCTION {FUNCTION}")
