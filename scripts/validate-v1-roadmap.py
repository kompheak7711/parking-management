#!/usr/bin/env python3
"""Validate the finite Property Rental v1 execution roadmap."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "ops/V1_ROADMAP.json"


def main() -> None:
    data = json.loads(ROADMAP.read_text())
    tranches = data["tranches"]
    total = data["total_tranches"]
    assert total == len(tranches) == 60
    ids = [item["id"] for item in tranches]
    orders = [item["order"] for item in tranches]
    assert len(ids) == len(set(ids))
    assert orders == list(range(1, total + 1))
    by_id = {item["id"]: item for item in tranches}
    allowed_statuses = {"complete", "approved_ready", "owner_protected"}
    allowed_profiles = set(data["acceptance_profiles"])
    for item in tranches:
        required = {
            "id",
            "order",
            "phase",
            "task",
            "dependencies",
            "authorities",
            "include",
            "exclude",
            "risk_class",
            "acceptance_profile",
            "authorization",
            "status",
        }
        assert required <= item.keys(), item["id"]
        assert item["status"] in allowed_statuses, item["id"]
        assert item["acceptance_profile"] in allowed_profiles, item["id"]
        assert item["authorities"] and item["include"] and item["exclude"], item["id"]
        for dependency in item["dependencies"]:
            assert dependency in by_id, (item["id"], dependency)
            assert by_id[dependency]["order"] < item["order"], (item["id"], dependency)
    completed = [item for item in tranches if item["status"] == "complete"]
    assert [item["order"] for item in completed] == list(range(1, len(completed) + 1))
    print(f"V1 roadmap valid: {len(completed)}/{total} complete")


if __name__ == "__main__":
    main()
