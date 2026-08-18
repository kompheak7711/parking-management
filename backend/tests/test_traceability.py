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
        "test_hash_password_returns_salted_argon2id_credential_material": {
            "TEST-108",
            "SEC-011",
            "DL-055",
        },
        "test_verify_password_accepts_current_encoding_without_rehash": {
            "TEST-108",
            "SEC-011",
            "DL-055",
        },
        "test_verify_password_fails_closed_without_exposing_secret": {
            "TEST-108",
            "SEC-011",
            "DL-055",
        },
        "test_verify_password_marks_valid_older_work_factor_for_rehash": {
            "TEST-108",
            "SEC-011",
            "DL-055",
        },
    }

    for test_id, references in expected_references.items():
        assert references <= set(credential_entries[test_id]["upstream_ids"])

    logging_entry = next(
        entry
        for entry in entries
        if entry["test_id"] == "test_log_formatter_ignores_non_allowlisted_extra_fields"
    )
    assert "SEC-043" in logging_entry["upstream_ids"]


def test_local_login_security_requirements_have_implemented_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_references = {
        "test_repository_normalizes_username_through_local_account_persistence": {
            "DB-AUTH-001",
            "TEST-108",
            "SEC-009",
            "DL-055",
        },
        "test_authenticates_active_local_account_with_phase_2e_verifier": {
            "PR-CAP-009",
            "DB-AUTH-002",
            "API-096",
            "TEST-108",
            "SEC-010",
            "DL-055",
        },
        "test_rejections_are_generic_and_perform_one_argon2id_verification": {
            "API-096",
            "TEST-108",
            "SEC-010",
            "DL-055",
        },
        "test_attempt_limiter_enforces_account_and_source_bounds": {
            "API-096",
            "TEST-108",
            "SEC-012",
            "DL-055",
        },
        "test_rate_limited_authentication_is_generic_and_skips_account_lookup": {
            "API-096",
            "TEST-108",
            "SEC-012",
            "DL-055",
        },
        "test_local_login_security_requirements_have_implemented_traceability": {"TEST-002"},
    }

    for test_id, references in expected_references.items():
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert references <= set(entry["upstream_ids"])


def test_mfa_policy_requirements_have_implemented_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_references = {
        "test_mfa_policy_matrix_controls_normal_actor_establishment": {
            "PR-CAP-009",
            "API-096",
            "TEST-128",
            "SEC-013",
            "DL-056",
        },
        "test_optional_unenrolled_actor_keeps_only_separately_granted_capabilities": {
            "PR-CAP-009",
            "TEST-128",
            "SEC-013",
            "DL-056",
        },
        "test_invalid_mfa_policy_evidence_fails_closed_without_actor_establishment": {
            "TEST-128",
            "SEC-013",
            "DL-056",
        },
        "test_invalid_mfa_policy_values_are_sanitized_before_audit_recording": {
            "TEST-128",
            "SEC-013",
            "DL-056",
        },
        "test_mfa_policy_requirements_have_implemented_traceability": {"TEST-002"},
    }

    for test_id, references in expected_references.items():
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert references <= set(entry["upstream_ids"])


def test_browser_session_lifetime_requirements_have_implemented_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_references = {
        "test_session_expires_at_fixed_thirty_minute_inactivity_boundary": {
            "PR-CAP-009",
            "API-097",
            "TEST-131",
            "SEC-017",
            "DL-057",
        },
        "test_recent_activity_never_extends_fixed_twenty_four_hour_absolute_expiry": {
            "PR-CAP-009",
            "API-097",
            "TEST-131",
            "SEC-017",
            "DL-057",
        },
        "test_explicit_revocation_fails_closed_for_evaluation_and_activity": {
            "API-097",
            "TEST-131",
            "SEC-017",
            "DL-057",
        },
        "test_session_audit_evidence_is_fixed_bounded_and_secret_free": {
            "SEC-015",
            "SEC-017",
            "DL-057",
        },
        "test_browser_session_lifetime_requirements_have_implemented_traceability": {
            "TEST-002",
            "TEST-131",
            "SEC-017",
            "DL-057",
        },
    }

    for test_id, references in expected_references.items():
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert references <= set(entry["upstream_ids"])


def test_administrative_recovery_requirements_have_implemented_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {"PR-CAP-009", "API-099", "TEST-130", "SEC-072", "SEC-075", "DL-058"}
    expected_test_ids = {
        "test_administrative_recovery_authorization_matrix_grants_only_owner_to_manager_or_staff",
        "test_self_recovery_is_not_granted_for_any_account_class",
        "test_unknown_actor_or_target_class_fails_closed",
        "test_recovery_authorization_audit_evidence_is_bounded_and_secret_free",
        "test_administrative_recovery_requirements_have_implemented_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_lifecycle_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {"PR-CAP-009", "API-098", "TEST-129", "SEC-071", "SEC-075", "DL-058"}
    expected_test_ids = {
        "test_protected_presentation_is_recorded_only_once_without_returning_code_material",
        "test_unprotected_presentation_fails_closed_without_changing_state",
        "test_successful_use_consumes_only_the_matching_code",
        "test_consumed_code_reuse_is_rejected_without_state_change",
        "test_regeneration_invalidates_every_old_verifier_and_rejects_old_code",
        "test_unprotected_regeneration_is_rejected_without_invalidating_codes",
        "test_invalid_lifecycle_state_fails_closed_before_verification",
        "test_unmatched_or_ambiguous_verification_is_generically_rejected",
        "test_code_cannot_be_consumed_before_protected_presentation_is_recorded",
        "test_presentation_and_regeneration_fail_closed_on_invalid_state",
        "test_verification_provider_failure_is_a_secret_free_closed_rejection",
        "test_lifecycle_audit_evidence_is_fixed_bounded_and_excludes_secret_material",
        "test_recovery_code_lifecycle_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_persistence_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-003",
        "PR-CAP-009",
        "API-098",
        "TEST-129",
        "SEC-071",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_recovery_code_storage_has_bounded_set_and_code_columns",
        "test_recovery_codes_have_independent_immutable_identities_and_consumption",
        "test_recovery_code_set_identity_and_completed_invalidation_are_immutable",
        "test_recovery_codes_reject_unprotected_or_incomplete_verifier_material",
        "test_recovery_code_lifecycle_timestamps_require_complete_provenance",
        "test_runtime_has_only_bounded_recovery_code_lifecycle_privileges",
        "test_runtime_can_insert_bounded_recovery_code_verifier_rows",
        "test_recovery_code_migration_refuses_destructive_downgrade",
        "test_recovery_code_persistence_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_cryptographic_provider_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-003",
        "PR-CAP-009",
        "API-098",
        "TEST-129",
        "SEC-071",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_secure_generator_requests_independent_high_entropy_material",
        "test_verifier_provider_contract_encodes_and_verifies_independently_salted_codes",
        "test_verifier_provider_rejects_malformed_code_input",
        "test_verifier_provider_fails_closed_for_malformed_verification_input",
        "test_verifier_output_is_non_plaintext_and_has_no_reversible_material",
        "test_code_and_verifier_operations_do_not_emit_or_represent_secret_material",
        "test_recovery_code_cryptographic_provider_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_set_issuance_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-003",
        "PR-CAP-009",
        "API-098",
        "TEST-129",
        "SEC-071",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_authorized_issuance_persists_independent_verifiers_before_one_time_return",
        "test_unauthorized_caller_is_rejected_before_secret_generation_or_persistence",
        "test_authorization_provider_failure_is_a_generic_pre_generation_rejection",
        "test_provider_failure_is_generic_and_never_persists_partial_set",
        "test_persistence_failure_records_secret_free_generic_failure_evidence",
        "test_duplicate_generated_material_fails_before_persisting_a_non_independent_set",
        "test_issuance_contract_rejects_empty_set_configuration",
        "test_issuance_request_rejects_invalid_nonsecret_context",
        "test_postgres_repository_commits_complete_set_and_verifiers_as_one_transaction",
        "test_postgres_repository_rolls_back_deterministically_on_partial_insert_failure",
        "test_issuance_does_not_represent_log_or_retain_plaintext_in_service_state",
        "test_caller_owned_presentation_releases_plaintext_only_once",
        "test_published_generator_and_verifier_satisfy_issuance_provider_contracts",
        "test_recovery_code_set_issuance_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_consumption_orchestration_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-003",
        "PR-CAP-009",
        "API-098",
        "TEST-129",
        "SEC-071",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_consumption_composes_lifecycle_verifier_and_atomic_repository_once",
        "test_non_active_matching_code_has_one_generic_outcome_without_persistence",
        "test_persistence_failure_fails_closed_with_secret_free_immutable_evidence",
        "test_postgres_repository_locks_exact_set_and_conditionally_consumes_one_row",
        "test_postgres_repository_rolls_back_when_conditional_consumption_loses_race",
        "test_committed_postgres_evidence_keeps_success_truthful_when_audit_sink_fails",
        "test_recovery_code_consumption_adapter_is_atomic_and_single_use_on_postgresql",
        "test_recovery_code_consumption_orchestration_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])


def test_recovery_code_regeneration_orchestration_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-003",
        "PR-CAP-009",
        "API-098",
        "TEST-129",
        "SEC-071",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_authorized_regeneration_atomically_replaces_prior_set_before_one_time_return",
        "test_unauthorized_regeneration_is_rejected_before_secret_generation",
        "test_authorization_failure_is_a_generic_pre_generation_rejection",
        "test_rejection_audit_failure_remains_generic_and_pre_generation",
        "test_replacement_persistence_failure_is_generic_and_preserves_prior_set",
        "test_failure_audit_unavailability_preserves_one_generic_closed_failure",
        "test_duplicate_replacement_material_fails_before_prior_set_invalidation",
        "test_published_providers_create_independently_salted_replacement_verifiers",
        "test_regeneration_request_rejects_invalid_nonsecret_context",
        "test_persisted_regeneration_remains_truthful_when_secondary_audit_sink_fails",
        "test_postgres_repository_locks_invalidates_and_inserts_replacement_in_one_transaction",
        "test_postgres_repository_rolls_back_when_replacement_insert_fails",
        "test_postgres_repository_rejects_missing_or_invalidated_prior_set_without_replacement",
        "test_recovery_code_regeneration_is_atomic_and_invalidates_prior_set_on_postgresql",
        "test_recovery_code_regeneration_orchestration_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities <= set(entry["upstream_ids"])
