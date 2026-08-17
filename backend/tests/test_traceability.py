"""Automated validation for the TEST-117 traceability manifest."""

import ast
import json
import re
from pathlib import Path
from typing import Final, TypedDict, cast

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "ops" / "traceability.json"
PYTHON_TEST_DIRECTORY: Final = REPOSITORY_ROOT / "backend" / "tests"
FRONTEND_TEST_DIRECTORY: Final = REPOSITORY_ROOT / "frontend" / "src"
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
    "UI component",
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
    "DL-",
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


def collect_frontend_test_ids(path: Path) -> set[str]:
    """Collect stable TEST-* identifiers from Vitest test names."""
    return set(re.findall(r'\b(?:it|test)\(\s*["\'](TEST-[A-Z0-9-]+)\b', path.read_text()))


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
    for test_path in PYTHON_TEST_DIRECTORY.glob("test_*.py"):
        executable_ids.update(collect_test_ids(test_path))
    for test_path in FRONTEND_TEST_DIRECTORY.glob("**/*.test.tsx"):
        executable_ids.update(collect_frontend_test_ids(test_path))

    assert executable_ids == manifest_ids


def test_password_credential_requirements_have_implemented_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    credential_entries = {
        entry["test_id"]: entry
        for entry in entries
        if entry["status"] == "implemented" and "DB-AUTH-002" in entry["upstream_ids"]
    }
    expected_references = {
        "test_password_credentials_store_only_bounded_verifier_material": {
            "TEST-108",
            "SEC-011",
            "SEC-014",
            "DL-055",
        },
        "test_password_credentials_reject_incomplete_verifier_records": {
            "TEST-010",
            "TEST-108",
            "SEC-011",
        },
        "test_runtime_has_only_bounded_password_credential_privileges": {
            "TEST-111",
        },
        "test_password_credential_requirements_have_implemented_traceability": {"TEST-002"},
    }

    for test_id, references in expected_references.items():
        assert references <= set(credential_entries[test_id]["upstream_ids"])

    logging_entry = next(
        entry
        for entry in entries
        if entry["test_id"] == "test_log_formatter_ignores_non_allowlisted_extra_fields"
    )
    assert "SEC-043" in logging_entry["upstream_ids"]
