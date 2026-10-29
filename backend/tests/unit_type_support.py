"""The Unit Type a test may give a Unit it inserts directly (Parking Step 3, owner 2026-10-29).

A new Property is seeded with the four Parking Types, so a direct insert at the head must use one
of them; a database pinned before migration 227 (no Unit Types list yet) still accepts STUDIO.
"""

from __future__ import annotations


from psycopg import Connection


def seeded_unit_type(connection: Connection[tuple[object, ...]], property_id: object) -> str:
    """The first Unit Type of the Property's Settings list, or STUDIO before migration 227."""
    if connection.execute("SELECT to_regclass('app.unit_setup_items')").fetchone() == (None,):
        return "STUDIO"
    row = connection.execute(
        """
        SELECT code FROM app.unit_setup_items
        WHERE property_id = %s AND list_kind = 'UNIT_TYPE' AND removed_at IS NULL
        ORDER BY sort_order LIMIT 1
        """,
        (property_id,),
    ).fetchone()
    return "STUDIO" if row is None else str(row[0])
