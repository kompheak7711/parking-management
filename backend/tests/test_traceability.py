"""Automated validation for the TEST-117 traceability manifest."""

import ast
import json
from pathlib import Path
from typing import Final, TypedDict, cast

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "ops" / "traceability.json"
TEST_DIRECTORIES: Final = (REPOSITORY_ROOT / "backend" / "tests",)
ALLOWED_LEVELS: Final = {
    "unit",
    "domain",
    "DB",
    "API",
    "integration",
    "UI",
    "E2E",
    "migration",
    "security",
    "operational",
}
ALLOWED_STATUSES: Final = {
    "implemented",
    "blocked by approved open decision",
    "planned",
}
UPSTREAM_PREFIXES: Final = (
    "BR-",
    "PR-",
    "DB-",
    "API-",
    "UI-",
    "SEC-",
    "DEPLOY-",
    "TEST-",
)


class TraceabilityEntry(TypedDict):
    """Required TEST-117 manifest entry shape."""

    test_id: str
    upstream_ids: list[str]
    test_level: str
    test_path: str
    status: str
    notes: str


def collect_test_ids(path: Path) -> set[str]:
    """Collect module-level and class-contained pytest function identifiers."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def test_traceability_manifest_covers_executable_tests() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    assert raw_manifest["schema_version"] == 1
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    assert entries

    manifest_ids: set[str] = set()
    for entry in entries:
        assert set(entry) == {
            "test_id",
            "upstream_ids",
            "test_level",
            "test_path",
            "status",
            "notes",
        }
        assert entry["test_id"].startswith(("TEST-", "test_"))
        assert entry["test_id"] not in manifest_ids
        manifest_ids.add(entry["test_id"])
        assert entry["upstream_ids"]
        assert all(identifier.startswith(UPSTREAM_PREFIXES) for identifier in entry["upstream_ids"])
        assert entry["test_level"] in ALLOWED_LEVELS
        assert entry["status"] in ALLOWED_STATUSES
        assert entry["notes"].strip()
        test_path = REPOSITORY_ROOT / entry["test_path"]
        assert test_path.is_file()
        if entry["status"] == "implemented" and entry["test_id"].startswith("test_"):
            assert entry["test_id"] in collect_test_ids(test_path)

    executable_ids: set[str] = set()
    for test_directory in TEST_DIRECTORIES:
        for test_path in test_directory.glob("test_*.py"):
            executable_ids.update(collect_test_ids(test_path))

    assert executable_ids == manifest_ids
