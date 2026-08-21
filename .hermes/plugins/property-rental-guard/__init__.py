"""Load the repository-owned Property Rental Hermes guard."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def register(ctx) -> None:
    repository = Path(os.environ["PROPERTY_RENTAL_REPO"]).resolve()
    scripts = repository / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from openclaw_hermes_guard import register_plugin

    register_plugin(ctx)
