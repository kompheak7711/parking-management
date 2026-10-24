"""Focused tests for DB-AUTH-002 password verifier mechanics."""

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type

from property_rental.password_security import (
    ONE_TIME_PASSWORD_ALPHABET,
    PasswordHashService,
    blocked_passwords,
    new_one_time_password,
    one_time_password_forms,
    parse_password_blocklist,
    validate_new_password,
)


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
    assert "correct horse battery staple" not in first.verifier_encoding


def test_hash_metadata_is_immutable_security_policy_evidence() -> None:
    service = PasswordHashService()
    credential = service.hash_password("immutable policy evidence")

    with pytest.raises(TypeError):
        credential.work_factor_metadata["time_cost"] = 1  # type: ignore[index]


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


@pytest.mark.parametrize("legacy_type", [Type.I, Type.D])
def test_verify_password_rejects_non_argon2id_encodings(legacy_type: Type) -> None:
    legacy_hasher = PasswordHasher(type=legacy_type)
    password = "legacy algorithm credential"
    legacy_encoding = legacy_hasher.hash(password)

    result = PasswordHashService().verify_password(password, legacy_encoding)

    assert result.is_valid is False
    assert result.needs_rehash is False


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


BLOCKED = blocked_passwords(["Password1234567", "correcthorsebatterystaple"])


def test_a_new_password_needs_15_to_128_code_points_and_is_not_blocked_or_a_name() -> None:
    """Login sub-slice L4 (owner answer (a) to Q-2026-10-21-155): one rule for every new
    password; the blocklist and the account's names are compared after NFC and case folding,
    and the NFC form is kept. Every refusal says the same thing."""
    assert validate_new_password("a long new password", blocked=BLOCKED) == "a long new password"
    assert validate_new_password("x" * 15, blocked=BLOCKED) == "x" * 15
    assert validate_new_password("x" * 128, blocked=BLOCKED) == "x" * 128
    assert validate_new_password("cafe\u0301 au lait please", blocked=BLOCKED) == (
        "caf\u00e9 au lait please"
    )
    refused = (
        ("x" * 14, ()),
        ("x" * 129, ()),
        ("PASSWORD1234567", ()),
        ("CorrectHorseBatteryStaple", ()),
        ("Sokha.Chan.Manager", ("sokha.chan.manager", "Sokha Chan")),
        ("sokha chan of desk 1", ("", "Sokha Chan of Desk 1")),
    )
    for password, context in refused:
        with pytest.raises(ValueError, match=r"^new password rejected$") as error:
            validate_new_password(password, blocked=BLOCKED, context=context)
        assert password not in str(error.value)
    # 15 code points only before NFC is still too short after it.
    with pytest.raises(ValueError):
        validate_new_password("e\u0301" * 7 + "a", blocked=BLOCKED)


def test_the_blocklist_is_one_password_per_line_in_comparison_form() -> None:
    assert parse_password_blocklist("Password1234567\r\n\nCaf\u00e9-pass\n") == {
        "password1234567",
        "caf\u00e9-pass",
    }
    assert parse_password_blocklist("\n\r\n") == frozenset()


def test_a_one_time_password_is_random_easy_to_type_and_meets_the_rule() -> None:
    """Login sub-slice L4: 4 groups of 4 characters from an alphabet without look-alikes
    (no 0, 1, i, l, o); 19 code points, so it meets the new-password rule."""
    made = {new_one_time_password() for _ in range(50)}
    assert len(made) == 50
    for value in made:
        groups = value.split("-")
        assert [len(group) for group in groups] == [4, 4, 4, 4]
        assert set("".join(groups)) <= set(ONE_TIME_PASSWORD_ALPHABET)
        assert validate_new_password(value, blocked=BLOCKED) == value
    assert not set("01ilo") & set(ONE_TIME_PASSWORD_ALPHABET)


def test_the_one_time_password_in_another_case_or_spacing_is_compared_as_written() -> None:
    """Login sub-slice L4 review round 1: a new password that is the one-time password in
    capitals, without its hyphens or with spaces is compared with the one-time password as it
    was written; any other password only as typed."""
    written = "k7m2-x9qp-4hrt-w3nd"
    assert one_time_password_forms(written) == (written,)
    for typed in ("K7M2-X9QP-4HRT-W3ND", "k7m2x9qp4hrtw3nd", "k7m2 x9qp 4hrt w3nd"):
        assert one_time_password_forms(typed) == (typed, written)
    for typed in ("a long new password of mine", "k7m2-x9qp-4hrt-w3nd-extra", "k1m2x9qp4hrtw3nd"):
        assert one_time_password_forms(typed) == (typed,)
