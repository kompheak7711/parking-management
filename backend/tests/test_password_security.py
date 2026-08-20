"""Focused tests for DB-AUTH-002 password verifier mechanics."""

import pytest
from argon2 import PasswordHasher

from property_rental.password_security import PasswordHashService


def test_hash_password_returns_salted_argon2id_credential_material() -> None:
    service = PasswordHashService()

    first = service.hash_password("correct horse battery staple")
    second = service.hash_password("correct horse battery staple")

    assert first.verifier_encoding.startswith("$argon2id$v=19$")
    assert second.verifier_encoding.startswith("$argon2id$v=19$")
    assert first.verifier_encoding != second.verifier_encoding
    assert first.algorithm == "argon2id"
    assert first.work_factor_metadata == {
        "version": 19,
        "memory_cost": 65_536,
        "time_cost": 3,
        "parallelism": 4,
        "hash_len": 32,
        "salt_len": 16,
    }


def test_verify_password_accepts_current_encoding_without_rehash() -> None:
    service = PasswordHashService()
    credential = service.hash_password("current credential")

    result = service.verify_password("current credential", credential.verifier_encoding)

    assert result.is_valid is True
    assert result.needs_rehash is False


@pytest.mark.parametrize("failure_kind", ["mismatch", "malformed"])
def test_verify_password_fails_closed_without_exposing_secret(failure_kind: str) -> None:
    secret = "must-not-escape-verification"
    service = PasswordHashService()
    verifier_encoding = (
        service.hash_password("different password").verifier_encoding
        if failure_kind == "mismatch"
        else "not-a-verifier"
    )

    result = service.verify_password(secret, verifier_encoding)

    assert result.is_valid is False
    assert result.needs_rehash is False
    assert secret not in repr(result)


def test_verify_password_marks_valid_older_work_factor_for_rehash() -> None:
    older_hasher = PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)
    older_encoding = older_hasher.hash("credential requiring upgrade")
    service = PasswordHashService()

    result = service.verify_password("credential requiring upgrade", older_encoding)

    assert result.is_valid is True
    assert result.needs_rehash is True


def test_password_hashing_normalizes_unicode_to_nfc_before_hashing_and_verification() -> None:
    service = PasswordHashService()
    decomposed = "Cafe\u0301 password phrase"
    composed = "Café password phrase"

    credential = service.hash_password(decomposed)

    assert service.verify_password(composed, credential.verifier_encoding).is_valid is True


def test_password_verification_uses_the_complete_value_without_truncation() -> None:
    service = PasswordHashService()
    accepted = "x" * 128
    credential = service.hash_password(accepted)

    assert service.verify_password(accepted, credential.verifier_encoding).is_valid is True
    assert service.verify_password(accepted + "y", credential.verifier_encoding).is_valid is False
