"""Automated validation for the TEST-117 traceability manifest."""

import ast
import json
import re
from pathlib import Path
from typing import Final, TypedDict, cast

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "ops" / "traceability.json"
# V1-058 R2 moved the Unit screen tests to units/UnitsPage.test.tsx. Only the test_path of
# these entries changed; the history checks below read them as first recorded.
MOVED_TEST_PATHS: Final = {
    "TEST-FE-027": "frontend/src/UnitManagement.test.tsx",
    "TEST-FE-028": "frontend/src/UnitManagement.test.tsx",
    "TEST-FE-029": "frontend/src/UnitManagement.test.tsx",
    "TEST-FE-030": "frontend/src/UnitManagement.test.tsx",
}
# V1-058 R7b-6e bills every Service, so this test's name and notes changed; the history checks
# below read the entry as first recorded.
CHANGED_ENTRIES: Final[dict[str, dict[str, object]]] = {
    "test_initial_invoice_preserves_rent_service_components_and_bills_every_service": {
        "test_id": (
            "test_initial_invoice_preserves_rent_service_components_and_excludes_unapproved_type"
        ),
        "notes": (
            "A real authenticated financial-role call creates one issued Initial Rent Invoice "
            "with reconstructable July proration and August full-month components for Rent and "
            "Trash Collection. Distinct effective Service rates remain linked at component level, "
            "while equally configured Internet is not billed."
        ),
    },
    # V1-061 removes the plain signing route that signed with no money; these tests changed.
    "test_signer_renewal_and_termination_are_explicit_commands_and_plain_signing_is_gone": {
        "test_id": "test_signer_signing_renewal_and_termination_are_explicit_commands",
    },
    "TEST-FE-186": {
        "notes": (
            "Explicit Lease signing sends CSRF, idempotency, and optimistic If-Match evidence."
        ),
    },
    "TEST-FE-189": {
        "notes": (
            "Signers remain distinct from Occupants and final signing requires explicit "
            "confirmation and reason evidence."
        ),
    },
    "test_the_signature_route_takes_no_signing_time_from_the_request": {
        "test_id": "test_signing_routes_take_no_signing_time_from_the_request",
    },
    "TEST-FE-675": {
        "notes": (
            "The Lease screen sends the Lease signing with exactly the event id and the "
            "reason, no device time (owner answer (a) to Q-2026-10-14-110; V1-056 signing "
            "time from the database clock)."
        ),
    },
    "test_the_plain_sign_route_is_removed": {
        "test_id": "test_sign_route_forwards_the_reservation_the_signing_completes",
        "notes": (
            "V1-058: POST /leases/{id}/sign takes an optional reservation_id and passes it to"
            " the signing command, so signing completes the Reservation (the database checks "
            "Unit, Customer and dates)."
        ),
    },
    "test_sign_with_reservation_then_http_lease_move_in_and_cancel_draft": {
        "test_id": "test_http_sign_with_reservation_then_lease_move_in_and_cancel_draft",
    },
}


def as_first_recorded(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return the entries with each moved test path and changed entry put back as first recorded."""
    return [
        {**entry, "test_path": MOVED_TEST_PATHS[str(entry["test_id"])]}
        if entry["test_id"] in MOVED_TEST_PATHS
        else {**entry, **CHANGED_ENTRIES[str(entry["test_id"])]}
        if entry["test_id"] in CHANGED_ENTRIES
        else entry
        for entry in entries
    ]


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


V1_017_AUTHORITIES: Final = {
    "API-100",
    "TEST-133",
    "TEST-134",
    "SEC-073",
    "SEC-074",
    "SEC-075",
    "DEPLOY-070",
    "DEPLOY-071",
    "DEPLOY-072",
    "DL-059",
}
V1_017_SECURITY_CLAUSE_TESTS: Final = {
    "supplied-and-normalized-password-code-point-bounds": (
        "test_password_policy_revalidates_nfc_result_without_waiving_supplied_length",
    ),
    "complete-normalized-password-blocklist-hash-and-verification": (
        "test_password_policy_blocks_the_complete_untruncated_128_code_point_value",
        "test_password_verification_uses_the_complete_value_without_truncation",
    ),
    "spaces-paste-password-managers-unicode-no-composition-no-rotation": (
        "test_password_policy_accepts_boundaries_spaces_and_nfc_without_composition_rules",
    ),
    "compromised-common-expected-project-context-rejection": (
        "test_password_policy_rejects_length_blocklist_and_project_context",
    ),
    "one-absolute-monotonic-ceremony-deadline": (
        "test_ceremony_deadline_never_resets_and_timeout_before_commit_rolls_back",
        "test_tty_timeout_is_not_extended_by_trickled_input",
    ),
    "exactly-ten-random-single-use-codes-with-independent-salts": (
        "test_production_recovery_factory_persists_random_codes_with_independent_salts",
    ),
    "controlling-tty-once-only-and-no-process-output": (
        "test_recovery_codes_are_written_to_the_dedicated_tty_descriptor_not_stdout",
        "test_main_uses_protected_descriptors_and_dedicated_identity_without_process_output",
    ),
    "root-controlled-totp-key-and-confirmed-mfa": (
        "test_totp_key_reader_requires_root_owned_private_regular_descriptor",
        "test_bootstrap_identity_atomically_persists_complete_owner_and_permanently_loses_mutation",
    ),
    "atomic-postgresql-failure-rollback": (
        "test_real_postgresql_production_service_pseudo_tty_failure_rolls_back_every_effect",
        "test_bootstrap_acknowledgement_rollback_removes_every_effect_and_preserves_one_time_grant",
    ),
    "safe-cluster-role-and-target-database-least-privilege": (
        "test_operational_database_identities_have_separate_least_privilege",
        "test_protected_bootstrap_migration_requires_preprovisioned_bounded_role",
        "test_protected_bootstrap_migration_rejects_overprivileged_existing_cluster_role",
        "test_protected_bootstrap_migration_rejects_unsafe_role_membership",
        "test_protected_bootstrap_migration_rejects_preexisting_object_privilege",
        "test_protected_bootstrap_migration_rejects_target_database_ownership",
        "test_protected_bootstrap_migration_rejects_public_table_authority",
    ),
    "pre-existing-postgresql-large-object-authority-fails-closed": (
        "test_protected_bootstrap_migration_accepts_large_object_without_bootstrap_authority",
        "test_protected_bootstrap_migration_rejects_large_object_ownership",
        "test_protected_bootstrap_migration_rejects_direct_large_object_acl_authority",
        "test_protected_bootstrap_migration_rejects_effective_large_object_role_authority",
        "test_protected_bootstrap_migration_rejects_public_large_object_authority",
        "test_protected_bootstrap_migration_fails_closed_when_large_object_state_is_unprovable",
    ),
    "password-file-source-inventory-consistency": (
        "test_readme_password_file_inventory_matches_env_compose_and_postgres_init",
    ),
    "permanent-closure-mutation-revocation-and-repeat-audit": (
        "test_bootstrap_identity_atomically_persists_complete_owner_and_permanently_loses_mutation",
        "test_closed_bootstrap_audits_through_preflight_without_reading_or_generating_secrets",
    ),
    "no-bootstrap-or-reset-http-backdoor": (
        "test_fastapi_openapi_inventory_has_no_bootstrap_or_unauthenticated_owner_reset_route",
    ),
    "recovery-cannot-create-ordinary-owner-reset": (
        "test_recovery_code_orchestration_cannot_be_used_as_an_owner_reset",
    ),
    "secret-free-immutable-bootstrap-audit": (
        "test_initial_owner_bootstrap_history_rejects_update_delete_and_truncate",
        "test_closed_bootstrap_audits_through_preflight_without_reading_or_generating_secrets",
    ),
}


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


def collect_financial_unit_test_ids(path: Path) -> set[str]:
    """Collect both ordinary and parameterized names in new financial unit suites."""
    return set(
        re.findall(r"(?:\b(?:it|test)\(\s*|\)\(\s*)[\"'](TEST-[A-Z0-9-]+)\b", path.read_text())
    )


def collect_financial_browser_test_ids(path: Path) -> set[str]:
    """The real-browser harness returns a stable id only after its assertions pass."""
    return set(
        re.findall(r"(?:passed\.push\(\s*|return\s+)[\"'](TEST-[A-Z0-9-]+)[\"']", path.read_text())
    )


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

    # Preserve the existing Python/component inventory and register the bounded
    # financial unit/browser suites; do not waive or remove any prior mapping.
    for name in (
        "financialJson.test.ts",
        "billingJournal.test.ts",
        "sealedIntentStore.test.ts",
        "financialContracts.test.ts",
        "financialClient.test.ts",
        "financialRecovery.test.ts",
        "financialReferenceClient.test.ts",
        "financialUi.test.ts",
        "financialUiContext.test.ts",
        "FinancialWorkspaces.test.tsx",
        "FinancialManagement.test.tsx",
        "App.test.tsx",
        "FinancialConfirmation.test.tsx",
        "customerLedgerClient.test.ts",
        "leaseEnforcementClient.test.ts",
        "leaseEnforcementRecovery.test.ts",
        "LeaseEnforcementManagement.test.tsx",
        "CustomerAccountLedger.test.tsx",
    ):
        executable_ids.update(collect_financial_unit_test_ids(FRONTEND_TEST_DIRECTORY / name))
    # V1-058 screen rebuild: client tests that carry numbered TEST-FE ids beside older names.
    for name in (
        "unitClient.test.ts",
        "adminClient.test.ts",
        "invoiceClient.test.ts",
        "history/historyClient.test.ts",
        "moveout/moveoutClient.test.ts",
        "moveout/plan.test.ts",
        "settings/serviceSettingsClient.test.ts",
        "leases/leaseServices.test.ts",
        "shell/buttons.test.ts",
    ):
        executable_ids.update(
            identifier
            for identifier in collect_financial_unit_test_ids(FRONTEND_TEST_DIRECTORY / name)
            if re.fullmatch(r"TEST-FE-\d+", identifier)
        )
    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "financialRecovery.browser.ts"
        )
    )

    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "financialCommands.browser.ts"
        )
    )

    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "financialReferences.browser.ts"
        )
    )

    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "financialWorkflows.browser.ts"
        )
    )

    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "customerLedger.browser.tsx"
        )
    )

    executable_ids.update(
        collect_financial_browser_test_ids(
            FRONTEND_TEST_DIRECTORY / "test" / "leaseEnforcement.browser.tsx"
        )
    )

    assert executable_ids == manifest_ids


def test_protected_initial_owner_bootstrap_has_complete_v1_017_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    bootstrap_entries = [
        entry
        for entry in entries
        if entry["status"] == "implemented"
        and (
            entry["test_path"].endswith("test_initial_owner_bootstrap_cli.py")
            or entry["test_id"].startswith("test_bootstrap_")
            or entry["test_id"]
            == "test_protected_initial_owner_bootstrap_has_complete_v1_017_traceability"
        )
    ]

    assert bootstrap_entries
    assert V1_017_AUTHORITIES <= {
        identifier for entry in bootstrap_entries for identifier in entry["upstream_ids"]
    }
    expected_clauses = {
        "supplied-and-normalized-password-code-point-bounds",
        "complete-normalized-password-blocklist-hash-and-verification",
        "spaces-paste-password-managers-unicode-no-composition-no-rotation",
        "compromised-common-expected-project-context-rejection",
        "one-absolute-monotonic-ceremony-deadline",
        "exactly-ten-random-single-use-codes-with-independent-salts",
        "controlling-tty-once-only-and-no-process-output",
        "root-controlled-totp-key-and-confirmed-mfa",
        "atomic-postgresql-failure-rollback",
        "safe-cluster-role-and-target-database-least-privilege",
        "pre-existing-postgresql-large-object-authority-fails-closed",
        "password-file-source-inventory-consistency",
        "permanent-closure-mutation-revocation-and-repeat-audit",
        "no-bootstrap-or-reset-http-backdoor",
        "recovery-cannot-create-ordinary-owner-reset",
        "secret-free-immutable-bootstrap-audit",
    }
    assert set(V1_017_SECURITY_CLAUSE_TESTS) == expected_clauses
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    for test_ids in V1_017_SECURITY_CLAUSE_TESTS.values():
        assert test_ids
        for test_id in test_ids:
            assert entries_by_id[test_id]["status"] == "implemented"


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
        "test_hash_metadata_is_immutable_security_policy_evidence": {
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
        "test_verify_password_rejects_non_argon2id_encodings": {
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
        "test_attempt_limiter_rejects_nonpositive_security_configuration": {
            "API-096",
            "TEST-108",
            "SEC-012",
            "DL-055",
        },
        "test_authentication_throttles_normalized_username_variants_before_lookup": {
            "DB-AUTH-001",
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
        "test_mfa_policy_audit_evidence_is_immutable": {
            "PR-CAP-009",
            "API-096",
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
        "test_logout_revocation_cannot_be_bypassed_by_fresh_activity": {
            "API-097",
            "TEST-131",
            "SEC-017",
            "DL-057",
        },
        "test_production_authorizer_keeps_session_state_and_high_value_capabilities_independent": {
            "PR-CAP-009",
            "TEST-135",
            "SEC-070",
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


def test_session_revocation_orchestration_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-004",
        "PR-CAP-009",
        "API-097",
        "TEST-131",
        "TEST-132",
        "SEC-015",
        "SEC-017",
        "DL-057",
    }
    expected_test_ids = {
        "test_password_reset_revokes_every_applicable_session_through_browser_boundary",
        "test_revocation_request_rejects_invalid_nonsecret_context",
        "test_revocation_request_rejects_unapproved_trigger",
        "test_audit_failure_fails_closed_without_exposing_internal_exception",
        "test_clock_failure_fails_closed_without_exposing_provider_detail",
        "test_browser_boundary_failure_is_generic_and_has_no_partial_result",
        "test_each_approved_trigger_records_the_exact_revocation_reason",
        "test_revocation_audit_evidence_is_fixed_bounded_and_secret_free",
        "test_session_revocation_orchestration_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_initial_owner_bootstrap_closure_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-005",
        "API-100",
        "TEST-133",
        "TEST-134",
        "SEC-073",
        "SEC-074",
        "SEC-075",
        "DL-059",
    }
    expected_test_ids = {
        "test_guard_returns_established_result_from_transactional_repository",
        "test_postgres_repository_uses_only_the_guard_in_the_caller_transaction",
        "test_postgres_repository_returns_generic_failure_to_transaction_owner",
        "test_postgres_repository_rejects_missing_or_malformed_database_result",
        "test_request_requires_uuid_target_and_correlation_identifiers",
        "test_initial_owner_bootstrap_closure_storage_is_bounded_and_secret_free",
        "test_initial_owner_bootstrap_closes_once_and_audits_repeated_attempt",
        "test_initial_owner_bootstrap_closure_does_not_infer_role_from_mfa_policy",
        "test_initial_owner_bootstrap_history_rejects_update_delete_and_truncate",
        "test_runtime_cannot_observe_or_invoke_initial_owner_bootstrap_guard",
        "test_concurrent_initial_owner_bootstrap_attempts_establish_exactly_one_owner",
        "test_initial_owner_bootstrap_closure_migration_refuses_destructive_downgrade",
        "test_initial_owner_bootstrap_closure_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_totp_mfa_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {"DB-AUTH-003", "API-096", "TEST-128", "SEC-013", "DL-056"}
    expected_test_ids = {
        "test_totp_matches_rfc_6238_sha1_vectors",
        "test_totp_matches_rfc_6238_algorithm_vectors",
        "test_totp_verification_accepts_exact_counter_and_rejects_wrong_or_malformed_codes",
        "test_secret_generator_requests_fixed_os_entropy_and_returns_base32_material",
        "test_aes_gcm_protection_round_trips_only_with_bound_enrollment_context",
        "test_aes_gcm_protection_rejects_wrong_key_tampering_and_invalid_material",
        "test_aes_gcm_unprotect_rejects_non_byte_material",
        "test_totp_operations_do_not_emit_or_represent_secret_material",
        "test_totp_enrollments_store_only_protected_material_separate_from_account_authority",
        "test_totp_enrollments_reject_unprotected_or_malformed_verifier_material",
        "test_totp_enrollment_lifecycle_preserves_secret_and_single_live_enrollment",
        "test_runtime_has_only_bounded_totp_enrollment_privileges",
        "test_totp_enrollment_migration_refuses_destructive_downgrade",
        "test_totp_mfa_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_browser_session_persistence_foundation_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-004",
        "API-097",
        "TEST-131",
        "SEC-015",
        "SEC-017",
        "DL-057",
    }
    expected_test_ids = {
        "test_browser_sessions_store_only_bounded_protected_lifetime_and_revocation_state",
        "test_browser_sessions_reject_unprotected_or_incomplete_token_verifiers",
        "test_browser_session_creation_rejects_invalid_fixed_lifetime_state",
        "test_browser_session_creation_rejects_revocation_before_creation",
        "test_browser_session_activity_and_revocation_are_forward_only_and_retain_history",
        "test_browser_session_activity_cannot_revive_an_expired_session",
        "test_runtime_has_only_bounded_browser_session_lifecycle_privileges",
        "test_runtime_can_persist_and_advance_bounded_browser_session_lifecycle",
        "test_browser_session_migration_refuses_destructive_downgrade",
        "test_browser_session_persistence_foundation_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_authentication_api_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "API-008",
        "API-009",
        "API-010",
        "API-096",
        "API-097",
        "SEC-012",
        "SEC-013",
        "SEC-014",
        "SEC-015",
        "SEC-016",
        "SEC-017",
        "SEC-018",
        "TEST-108",
        "TEST-128",
        "TEST-131",
        "TEST-132",
    }
    expected_test_ids = {
        "test_successful_local_login_sets_protected_session_and_csrf_cookies",
        "test_valid_password_requiring_mfa_sets_only_short_lived_preauthentication_cookie",
        "test_mfa_required_login_expires_any_existing_authenticated_session",
        "test_authenticated_login_expires_any_stale_preauthentication_capability",
        "test_login_rejection_is_generic_and_sets_no_authentication_cookie",
        "test_totp_challenge_requires_preauthentication_and_csrf_then_establishes_session",
        "test_recovery_code_challenge_is_transported_exactly_and_establishes_session",
        "test_rejected_mfa_challenge_returns_generic_unauthorized",
        "test_required_mfa_enrollment_returns_one_time_totp_provisioning_material",
        "test_confirmed_mfa_enrollment_activates_totp_and_establishes_session",
        "test_authenticated_session_inspection_returns_only_bounded_non_secret_state",
        "test_logout_requires_csrf_revokes_current_session_and_clears_browser_material",
        "test_reauthentication_records_additional_evidence_without_granting_authority",
        "test_authentication_routes_fail_closed_when_no_runtime_flow_is_configured",
        "test_rate_limited_login_returns_generic_429_without_account_disclosure",
        "test_authentication_mutations_reject_missing_origin_and_csrf_evidence",
        "test_authentication_mutations_reject_wrong_origin_and_mismatched_csrf_evidence",
        "test_sms_mfa_is_not_an_accepted_authentication_method",
        "test_authentication_api_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_account_recovery_orchestration_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    routed_authorities = {
        "DB-AUTH-002",
        "DB-AUTH-003",
        "DB-AUTH-004",
        "DB-AUTH-005",
        "PR-CAP-009",
        "API-098",
        "API-099",
        "TEST-129",
        "TEST-130",
        "SEC-071",
        "SEC-072",
        "SEC-075",
        "DL-058",
    }
    expected_test_ids = {
        "test_authorized_owner_administrative_recovery_applies_mutation_and_revocation_atomically",
        "test_administrative_recovery_never_broadens_the_approved_matrix",
        "test_rate_limit_is_checked_before_authorization_or_secret_work",
        "test_owner_recovery_code_path_requires_owner_self_target_and_no_credential_mutation",
        "test_recovery_code_orchestration_cannot_be_used_as_an_owner_reset",
        "test_emergency_owner_recovery_requires_controlled_procedure_identity",
        "test_emergency_recovery_rejects_missing_procedure_or_non_owner_target",
        "test_administrative_and_emergency_paths_require_an_actual_recovery_mutation",
        "test_authorization_or_repository_failure_is_generic_and_secret_free",
        "test_invalid_recovery_code_is_outwardly_equivalent_to_authorization_denial_and_audited",
        "test_rejected_recovery_fails_closed_when_immutable_audit_is_unavailable",
        "test_recovery_audit_evidence_is_bounded_and_secret_free",
        "test_recovery_reason_and_procedure_are_bounded_safe_identifiers",
        "test_trusted_authorizer_resolves_classes_and_requires_password_preauthorization",
        "test_trusted_authorizer_fails_closed_for_unknown_target_or_unverified_proof",
        "test_trusted_authorizer_requires_registered_emergency_procedure_for_resolved_owner",
        "test_postgres_administrative_recovery_mutates_revokes_and_audits_in_one_transaction",
        "test_postgres_owner_recovery_code_is_consumed_with_revocation_and_audit_atomically",
        "test_postgres_recovery_rolls_back_every_effect_when_a_required_step_fails",
        "test_postgres_recovery_rejects_a_requested_bundle_that_mutates_nothing",
        "test_account_recovery_audit_storage_is_bounded_immutable_and_secret_free",
        "test_account_recovery_functions_are_the_only_runtime_password_and_audit_boundary",
        "test_account_recovery_repository_atomically_resets_password_revokes_sessions_and_audits",
        "test_owner_recovery_code_consumption_revocation_and_audit_are_one_transaction",
        "test_account_recovery_audit_history_rejects_change_and_destruction",
        "test_account_recovery_migration_refuses_destructive_downgrade",
        "test_account_recovery_orchestration_has_bounded_traceability",
    }

    for test_id in expected_test_ids:
        entry = entries_by_id[test_id]
        assert entry["status"] == "implemented"
        assert routed_authorities == set(entry["upstream_ids"])


def test_reservation_and_deposit_persistence_has_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_test_ids = {
        "test_activation_persists_one_reservation_and_continuing_security_deposit",
        "test_authorized_variance_is_preserved_and_replay_is_idempotent",
        "test_extension_is_single_bounded_and_preserves_original_history",
        "test_expired_reservation_cannot_be_retroactively_extended",
        "test_extension_notice_requires_atomic_reservation_update",
        "test_database_rejects_invalid_dates_statuses_and_history_rewrite",
        "test_received_deposit_cannot_exceed_required_liability",
        "test_activation_bundle_requires_exact_accepted_receipt",
        "test_concurrent_attempts_hold_one_unit_exactly_once",
        "test_runtime_is_read_only_except_for_bounded_commands",
        "test_reservation_migration_is_forward_only",
        "test_v1_029_upgrade_preserves_v1_028_property_unit_and_customer_data",
        "test_reservation_and_deposit_persistence_has_bounded_traceability",
    }
    required_authorities = {
        *(f"BR-RES-{index:03d}" for index in range(1, 11)),
        "BR-RES-014",
        "BR-RES-015",
        "BR-RES-017",
        "BR-RES-018",
        "BR-RES-019",
        *(f"BR-DEP-{index:03d}" for index in range(1, 7)),
        *(f"DB-RES-{index:03d}" for index in range(1, 4)),
        "DB-DEP-001",
        "DB-DEP-002",
        "TEST-024",
        "TEST-025",
        "TEST-027",
    }

    scoped_entries = [entries_by_id[test_id] for test_id in expected_test_ids]
    assert all(entry["status"] == "implemented" for entry in scoped_entries)
    assert required_authorities <= {
        authority for entry in scoped_entries for authority in entry["upstream_ids"]
    }


def test_reservation_lifecycle_services_have_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_test_ids = {
        "test_postgres_service_creates_extends_and_cancels_one_stable_reservation",
        "test_customer_cancellation_is_atomic_idempotent_and_preserves_deposit",
        "test_property_cancellation_requires_coordination_and_creates_refund",
        "test_expiration_uses_end_of_date_is_bounded_and_preserves_classification",
        "test_version_checked_extension_replays_then_rejects_stale_new_command",
        "test_concurrent_extension_and_cancellation_have_one_version_winner",
        "test_database_prevents_summary_drift_illegal_transition_and_history_loss",
        "test_runtime_role_has_only_bounded_lifecycle_authority",
        "test_reservation_lifecycle_migration_is_forward_only",
        "test_reservation_lifecycle_services_have_bounded_traceability",
    }
    implemented_authorities = {
        *(f"BR-RES-{index:03d}" for index in range(3, 13)),
        *(f"BR-RES-{index:03d}" for index in range(15, 21)),
        *(f"PR-RES-{index:03d}" for index in range(3, 13)),
        *(f"PR-RES-{index:03d}" for index in range(15, 21)),
        "TEST-024",
        "TEST-025",
        "TEST-027",
        "DL-034",
        "DL-037",
    }
    held_whole_clause_claims = {
        "BR-RES-013",
        "BR-RES-014",
        "BR-RES-021",
        "BR-RES-022",
        "PR-RES-013",
        "PR-RES-014",
        "PR-RES-021",
        "PR-RES-022",
        "TEST-026",
        "TEST-028",
        "TEST-029",
    }

    scoped_entries = [entries_by_id[test_id] for test_id in expected_test_ids]
    routed = {authority for entry in scoped_entries for authority in entry["upstream_ids"]}
    assert all(entry["status"] == "implemented" for entry in scoped_entries)
    assert implemented_authorities <= routed
    assert held_whole_clause_claims.isdisjoint(routed)


def test_reservation_deposit_outcomes_have_bounded_traceability() -> None:
    raw_manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    entries = cast(list[TraceabilityEntry], raw_manifest["entries"])
    entries_by_id = {entry["test_id"]: entry for entry in entries}
    expected_test_ids = {
        "test_outcome_correction_digest_binds_replacement_and_evidence",
        "test_financial_commands_require_trusted_separate_capabilities",
        "test_customer_and_property_outcomes_preserve_exact_source_links_and_audit",
        "test_identical_concurrent_cancellation_creates_one_outcome",
        "test_duplicate_refund_number_rolls_back_cancellation_and_availability",
        "test_correction_replaces_outcome_without_erasing_financial_history",
        "test_concurrent_stale_outcome_correction_has_one_exact_winner",
        "test_financial_history_is_append_only_and_runtime_is_least_privilege",
        "test_reservation_outcome_migration_is_forward_only",
        "test_v1_031_migration_requires_preprovisioned_bounded_financial_role",
        "test_v1_031_migration_requires_preprovisioned_financial_role_before_schema_change",
        "test_v1_031_migration_rejects_overprivileged_financial_role_before_schema_change",
        "test_v1_031_migration_rejects_effective_public_relation_authority",
        "test_v1_031_migration_rejects_effective_public_default_authority",
        "test_v1_031_migration_rejects_effective_public_large_object_authority",
        "test_v1_031_upgrade_preserves_and_completes_v1_030_pending_outcome",
        "test_reservation_deposit_outcomes_have_bounded_traceability",
    }
    required_authorities = {
        "BR-RES-020",
        "BR-RES-021",
        "BR-RES-022",
        "PR-RES-020",
        "PR-RES-021",
        "PR-RES-022",
        "BR-REFUND-001",
        "BR-REFUND-002",
        "BR-REFUND-003",
        "BR-REFUND-004",
        "BR-REFUND-009",
        "BR-REFUND-010",
        "BR-REFUND-011",
        "BR-REFUND-012",
        "TEST-029",
        "DL-028",
        "DL-034",
        "DL-035",
        "DL-036",
        "DL-044",
    }
    held_authorities = {
        "BR-REFUND-005",
        "BR-REFUND-006",
        "BR-REFUND-007",
        "BR-REFUND-008",
        "BR-REFUND-013",
        "TEST-030",
    }

    scoped_entries = [entries_by_id[test_id] for test_id in expected_test_ids]
    routed = {authority for entry in scoped_entries for authority in entry["upstream_ids"]}
    assert all(entry["status"] == "implemented" for entry in scoped_entries)
    assert required_authorities <= routed
    assert held_authorities.isdisjoint(routed)


def test_v1052_payment_reversal_context_preserves_prior_manifest_and_complete_stage_maps() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    historical = json.dumps(
        as_first_recorded(entries[:1598]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(historical).hexdigest()
        == "a121fe8e1adc5075d7bfedbc5e7c93f55206d1893180cba73b6eebf00777cb5f"
    )
    required = {
        "test_payment_reversal_context_limit_is_bounded",
        "test_payment_reversal_context_same_snapshot_bounded_page_and_original_source",
        "test_payment_reversal_context_database_complete_large_pages_and_revision_change",
        "test_payment_reversal_context_database_coherent_snapshot_during_new_refund",
        "test_payment_reversal_context_http_safe_source_and_changed_snapshot_errors",
        "test_payment_reversal_context_action_grant_precedes_database",
        "test_payment_reversal_context_fresh_identity_source_and_outage_fail_closed",
        "test_payment_reversal_context_http_rejects_invalid_queries_before_projection",
        "test_payment_reversal_context_http_identity_and_scope_precede_projection",
        "TEST-FE-357",
        "test_payment_reversal_context_database_allocation_impact_unwind_and_historical_results",
        "test_payment_reversal_context_database_partial_full_refund_returns_and_correction_reversal",
        "TEST-FE-362",
        "TEST-FE-363",
        "test_payment_reversal_context_database_unsupported_future_application_is_explicit",
        "test_payment_reversal_context_database_statement_deadline_is_unavailable",
        "test_payment_reversal_context_database_action_only_original_fx_and_no_writes",
        "test_payment_reversal_context_database_pet_refund_and_return_use_deposit_revision",
        "test_payment_reversal_context_database_other_payment_target_change_invalidates_result",
        "TEST-FE-359",
        "TEST-FE-361",
        "TEST-FE-366",
        "test_payment_reversal_context_changed_revision_rejects_continuation",
        "TEST-FE-364",
        "test_payment_reversal_context_refuses_incomplete_or_malformed_projection",
        "TEST-FE-360",
        "test_payment_reversal_context_database_migration_privileges_and_readonly_transaction",
        "test_payment_reversal_context_database_charge_result_matches_authoritative_position",
        "TEST-FE-358",
        "TEST-FE-365",
        "test_payment_reversal_context_database_credit_application_dependencies_and_results",
        "test_payment_reversal_context_database_shared_deposit_descendants_deduplicated_and_guarded",
        "test_payment_reversal_context_database_fresh_actor_precedes_source",
        "test_payment_reversal_context_cursor_is_finite_canonical",
        "test_payment_reversal_context_database_missing_property_source_and_cursor",
        "test_payment_reversal_context_http_action_only_success_no_store_and_scope",
    }
    required.add(
        "test_v1052_payment_reversal_context_preserves_prior_manifest_and_complete_stage_maps"
    )
    required.add("test_payment_reversal_context_database_void_invoice_has_zero_current_balance")
    registered = {
        entry["test_id"]: entry for entry in entries[1598:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all(
        {"API-060", "UI-073", "UI-074", "SEC-022", "DB-PAY-006"} <= set(entry["upstream_ids"])
        for entry in registered.values()
    )


def test_v1052_reversal_context_correction_preserves_failed_candidate_trace() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    retained = json.dumps(
        as_first_recorded(entries[:1636]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(retained).hexdigest()
        == "247671c11d722ea1f42e604924148bc2c5da2685eab669c34f159fa8bef8fb11"
    )
    required = {f"TEST-FE-{number}" for number in range(367, 374)}
    required.add("test_v1052_reversal_context_correction_preserves_failed_candidate_trace")
    registered = {
        entry["test_id"]: entry for entry in entries[1636:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all(
        {"API-060", "UI-073", "UI-074", "DB-PAY-006", "SEC-022"} <= set(entry["upstream_ids"])
        for entry in registered.values()
    )


def test_v1052_financial_action_context_preserves_accepted_trace_and_requires_stage_maps() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    original = json.dumps(
        as_first_recorded(entries[:1644]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(original).hexdigest()
        == "bf884c4c65aca66bf120e00bd0e2636dc6519899e6e2f124c92305a374e22f4c"
    )
    required = {
        "test_financial_action_context_http_only_own_action_needed",
        "TEST-FE-378",
        "TEST-FE-377",
        "test_financial_action_context_utf8_budget_counts_combined_source_and_context",
        "test_financial_action_context_http_actor_property_and_read_only_headers",
        "test_financial_action_context_purpose_is_finite",
        "test_financial_action_context_database_credit_application_original_and_reversal",
        "TEST-FE-379",
        "TEST-FE-374",
        "test_financial_action_context_database_payment_receipt_fx_and_no_writes",
        "test_financial_action_context_database_statement_deadline_is_unavailable",
        "TEST-FE-387",
        "test_financial_action_context_deposit_refund_has_no_invented_payment",
        "test_financial_action_context_database_complete_500_line_sources_and_stale_pages",
        "test_financial_action_context_http_general_read_never_implies_action",
        "test_financial_action_context_database_direct_sql_rejects_malformed_arguments",
        "TEST-FE-381",
        "test_financial_action_context_database_deposit_refund_return_and_correction_source",
        "TEST-FE-376",
        "TEST-FE-388",
        "test_financial_action_context_http_unauthenticated_and_default_flow_fail_closed",
        "test_financial_action_context_database_migration_privileges_and_forward_only",
        "test_financial_action_context_rejects_invalid_identity_target_and_cursor",
        "test_financial_action_context_database_missing_sources_do_not_leak",
        "test_financial_action_context_database_shared_deposit_guard_changes_source_context",
        "test_financial_action_context_http_selected_targets_captured_exactly",
        "test_financial_action_context_database_coherent_snapshot_during_new_refund",
        "TEST-FE-380",
        "TEST-FE-382",
        "test_financial_action_context_never_synthesizes_an_action_grant",
        "test_financial_action_context_database_selected_correction_beyond_max_history_page",
        "TEST-FE-385",
        "test_financial_action_context_malformed_projection_fails_closed",
        "TEST-FE-386",
        "test_financial_action_context_http_rejects_invalid_queries_before_dispatch",
        "test_v1052_financial_action_context_preserves_accepted_trace_and_requires_stage_maps",
        "TEST-FE-375",
        "test_financial_action_context_database_refund_original_return_and_exact_correction",
        "test_financial_action_context_http_reversal_cannot_supply_replacement_target",
        "test_financial_action_context_database_invoice_debit_preserves_original_and_adjusted",
        "test_financial_action_context_reversal_cannot_replace_original_target_or_refund",
        "test_financial_action_context_continuation_binds_source_target_and_current_facts",
        "TEST-FE-384",
        "test_financial_action_context_database_normal_credit_and_third_party_target_scope",
        "TEST-FE-383",
        "test_financial_action_context_database_future_deposit_application_is_explicit",
        "test_financial_action_context_database_charge_remains_separate_from_invoice",
        "test_financial_action_context_page_limits_are_strict",
        "test_financial_action_context_database_allocation_original_and_current_target",
        "test_financial_action_context_database_credit_recognition_and_reversal_position",
        "test_financial_action_context_sole_action_grant_uses_one_bounded_read_snapshot",
        "test_financial_action_context_database_fresh_human_before_source",
        "test_financial_action_context_database_historical_void_target_is_zero",
        "test_financial_action_context_database_actual_utf8_projection_budget",
        "TEST-FE-389",
        "test_financial_action_context_http_safe_correlated_failure",
    }
    registered = {
        entry["test_id"]: entry for entry in entries[1644:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all(
        {"API-011", "API-012", "SEC-022"} <= set(entry["upstream_ids"])
        for entry in registered.values()
    )


def test_v1052_action_context_review_correction_preserves_all_prior_trace() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    original = json.dumps(
        as_first_recorded(entries[:1700]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(original).hexdigest()
        == "a82b06cb07cd4ec11204a484a73ae6712bde97181d057bfa88b8e9e4ebf63e34"
    )
    required = {
        "test_financial_action_context_database_zero_balance_retains_invoice_cardinality_and_totals",
        "TEST-FE-397",
        "test_financial_action_context_http_preserves_exact_collection_count_and_invoice_totals",
        "TEST-FE-394",
        "TEST-FE-396",
        "test_v1052_action_context_review_correction_preserves_all_prior_trace",
        "TEST-FE-392",
        "TEST-FE-390",
        "TEST-FE-398",
        "TEST-FE-399",
        "TEST-FE-393",
        "TEST-FE-401",
        "test_financial_action_context_database_draft_revision_invalidates_old_pages",
        "test_financial_action_context_database_khr_credit_preserves_exact_original_fx",
        "TEST-FE-391",
        "TEST-FE-400",
        "TEST-FE-395",
    }
    registered = {
        entry["test_id"]: entry for entry in entries[1700:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all(
        {"API-011", "API-012", "SEC-022"} <= set(entry["upstream_ids"])
        for entry in registered.values()
    )


def test_v1052_action_context_review_aa_preserves_all_prior_trace() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    original = json.dumps(
        as_first_recorded(entries[:1717]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(original).hexdigest()
        == "91d34416a20b699bf8a695c0c801dc8a42e278f695e3bb1bc2c2550ddff00858"
    )
    required = {
        "TEST-FE-408",
        "test_financial_action_context_database_review_aa_refund_multiple_and_parent_reversal",
        "TEST-FE-410",
        "test_financial_action_context_database_review_aa_historical_receipt_identity",
        "test_v1052_action_context_review_aa_preserves_all_prior_trace",
        "test_financial_action_context_database_review_aa_legacy_reservation_null_evidence",
        "TEST-FE-412",
        "TEST-FE-403",
        "TEST-FE-411",
        "test_financial_action_context_database_review_aa_multiple_applications",
        "TEST-FE-404",
        "TEST-FE-406",
        "TEST-FE-409",
        "TEST-FE-402",
        "TEST-FE-407",
        "TEST-FE-405",
    }
    registered = {
        entry["test_id"]: entry for entry in entries[1717:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all(
        {"API-011", "API-012", "SEC-022"} <= set(entry["upstream_ids"])
        for entry in registered.values()
    )


def test_v1052_financial_staff_ui_preserves_accepted_trace_and_requires_helper_maps() -> None:
    import hashlib

    entries = json.loads(MANIFEST_PATH.read_text())["entries"]
    original = json.dumps(
        as_first_recorded(entries[:1733]), sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(original).hexdigest()
        == "236f98a553757325765189177ebe9d3154ca3e18b261e9a826d8a42405784441"
    )
    required = {
        "TEST-FE-415",
        "TEST-FE-421",
        "test_v1052_financial_staff_ui_preserves_accepted_trace_and_requires_helper_maps",
        "TEST-FE-417",
        "TEST-FE-418",
        "TEST-FE-413",
        "TEST-FE-414",
        "TEST-FE-416",
        "TEST-FE-420",
        "TEST-FE-422",
        "TEST-FE-419",
        "TEST-FE-423",
    }
    registered = {
        entry["test_id"]: entry for entry in entries[1733:] if entry["test_id"] in required
    }
    assert set(registered) == required
    assert all(entry["status"] == "implemented" for entry in registered.values())
    assert all("TEST-117" in entry["upstream_ids"] for entry in registered.values())
