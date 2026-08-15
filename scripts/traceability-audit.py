"""Fail when newly introduced material BR/PR identifiers lack TEST-117 mappings."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Final, TypedDict, cast

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "ops" / "traceability.json"
REQUIREMENT_PATHS: Final = (
    "docs/002_BUSINESS_RULES.md",
    "docs/003_PRODUCT_REQUIREMENTS.md",
)
MATERIAL_IDENTIFIER: Final = re.compile(
    r"^\+#{2,4}\s+(?P<identifier>(?:BR|PR)-[A-Z]+-\d{3})\b"
)
ZERO_SHA: Final = "0" * 40


class TraceabilityEntry(TypedDict):
    """Fields used from one traceability manifest entry."""

    upstream_ids: list[str]


def git(*arguments: str) -> str:
    """Run a read-only Git command from the repository root."""
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def resolve_base(requested_base: str) -> str:
    """Resolve the event base, falling back to the checked-out commit's parent."""
    if requested_base and requested_base != ZERO_SHA:
        git("cat-file", "-e", f"{requested_base}^{{commit}}")
        return requested_base

    try:
        git("cat-file", "-e", "HEAD^1^{commit}")
    except subprocess.CalledProcessError:
        return git("hash-object", "-t", "tree", "/dev/null").strip()
    return "HEAD^1"


def added_material_identifiers(diff: str) -> set[str]:
    """Collect requirement identifiers from newly added normative headings."""
    identifiers: set[str] = set()
    for line in diff.splitlines():
        match = MATERIAL_IDENTIFIER.match(line)
        if match:
            identifiers.add(match.group("identifier"))
    return identifiers


def mapped_identifiers() -> set[str]:
    """Collect all upstream identifiers represented in the TEST-117 manifest."""
    manifest = cast(
        dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    )
    entries = cast(list[TraceabilityEntry], manifest["entries"])
    return {identifier for entry in entries for identifier in entry["upstream_ids"]}


def main() -> int:
    """Audit newly introduced material requirements against traceability mappings."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base", default="", help="Git commit before the proposed change"
    )
    arguments = parser.parse_args()

    base = resolve_base(arguments.base)
    diff = git(
        "diff",
        "--unified=0",
        "--diff-filter=AM",
        base,
        "HEAD",
        "--",
        *REQUIREMENT_PATHS,
    )
    introduced = added_material_identifiers(diff)
    missing = sorted(introduced - mapped_identifiers())

    if missing:
        print("Unmapped material requirement identifiers: " + ", ".join(missing))
        return 1

    print(
        f"TEST-118 rule coverage audit passed ({len(introduced)} new material identifiers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
