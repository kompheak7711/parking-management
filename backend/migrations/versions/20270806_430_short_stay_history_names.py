"""Owner's review of the short-stay booking page, 16 Nov 2026: History names the person.

The owner's standing rule is that History names the person for every step on every page. The
booking page (Short stays > ST...) listed what happened and when, but not who did it, and its Unit
check card said "Unit checked" with no name. This migration only changes what the booking read
gives; it changes no row.

- ``app.short_stay_booking_json`` (the booking as the screens read it) now gives, for each History
  step, ``by_name``: the person's display name for a step done in the app, or the cleaner's name
  for a step the cleaner reported in the Staff bot (DL-242 keeps the cleaner as ``employee_id`` in
  the step's details); and ``by_app`` true for a step the app did by itself (a service, such as the
  Telegram jobs, with no person named).
- ``room_check`` gains ``done_by_name`` and ``problem_found_by_name``.

The function before this one is kept under the name ``app.short_stay_booking_unnamed_json`` and
called first, as migration 20270716_391 did. No money, Invoice or Lease changes. Forward-only.

Revision ID: 20270806_430
Revises: 20270804_415
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270806_430"
down_revision: str | None = "20270804_415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = r"""
ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_unnamed_json;

CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT found || jsonb_build_object(
        'history', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('kind', event.kind,
                'occurred_at', event.occurred_at, 'actor_id', event.actor_id,
                'note', event.note, 'details', event.details,
                'by_name', COALESCE(person.display_name, cleaner.name_en),
                'by_app', person.actor_id IS NULL AND cleaner.id IS NULL
                    AND actor.identity_kind = 'SERVICE')
                ORDER BY event.event_number)
            FROM app.short_stay_booking_events AS event
            JOIN app.actor_identities AS actor ON actor.actor_id = event.actor_id
            LEFT JOIN app.user_accounts AS person ON person.actor_id = event.actor_id
            LEFT JOIN app.employees AS cleaner
                ON cleaner.id::text = event.details ->> 'employee_id'
            WHERE event.booking_id = p_booking), '[]'::jsonb),
        'room_check', CASE WHEN jsonb_typeof(found -> 'room_check') = 'object'
            THEN (found -> 'room_check') || (
                SELECT jsonb_build_object(
                    'done_by_name', COALESCE(cleaner.name_en, person.display_name),
                    'problem_found_by_name', finder.name_en)
                FROM app.housekeeping_tasks AS task
                LEFT JOIN app.user_accounts AS person ON person.actor_id = task.done_by
                LEFT JOIN app.employees AS cleaner ON cleaner.id = task.done_by_employee
                LEFT JOIN app.employees AS finder ON finder.id = task.problem_found_by
                WHERE task.id::text = found -> 'room_check' ->> 'task_id')
            ELSE found -> 'room_check' END)
    FROM (SELECT app.short_stay_booking_unnamed_json(p_booking) AS found) AS base
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(FUNCTIONS)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
