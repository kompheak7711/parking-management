"""Focused deterministic tests for RFC 6238 TOTP and protected enrollment material."""

import logging
import uuid
from collections.abc import Callable
from typing import cast

import pytest

from property_rental.totp_security import (
    TOTP_SECRET_ENTROPY_BYTES,
    Aes256GcmTotpSecretProtector,
    ProtectedTotpSecret,
    TotpAlgorithm,
    TotpParameters,
    TotpSecret,
    TotpSecretGenerator,
    TotpSecretProtectionError,
    TotpService,
)


class DeterministicEntropySource:
    def __init__(self, output: bytes) -> None:
        self._output = output
        self.requested_sizes: list[int] = []

    def __call__(self, size: int) -> bytes:
        self.requested_sizes.append(size)
        return self._output


@pytest.mark.parametrize(
    ("at_time", "expected_code"),
    [
        (59, "94287082"),
        (1_111_111_109, "07081804"),
        (1_111_111_111, "14050471"),
        (1_234_567_890, "89005924"),
        (2_000_000_000, "69279037"),
        (20_000_000_000, "65353130"),
    ],
)
def test_totp_matches_rfc_6238_sha1_vectors(at_time: int, expected_code: str) -> None:
    secret = TotpSecret.from_bytes(b"12345678901234567890")
    parameters = TotpParameters(algorithm="sha1", digits=8, period_seconds=30)

    generated = TotpService().generate_code(secret, at_time=at_time, parameters=parameters)

    assert generated == expected_code


@pytest.mark.parametrize(
    ("algorithm", "secret_bytes", "expected_code"),
    [
        ("sha1", b"12345678901234567890", "94287082"),
        ("sha256", b"12345678901234567890123456789012", "46119246"),
        (
            "sha512",
            b"1234567890123456789012345678901234567890123456789012345678901234",
            "90693936",
        ),
    ],
)
def test_totp_matches_rfc_6238_algorithm_vectors(
    algorithm: TotpAlgorithm,
    secret_bytes: bytes,
    expected_code: str,
) -> None:
    parameters = TotpParameters(algorithm=algorithm, digits=8, period_seconds=30)

    generated = TotpService().generate_code(
        TotpSecret.from_bytes(secret_bytes),
        at_time=59,
        parameters=parameters,
    )

    assert generated == expected_code


def test_totp_verification_accepts_exact_counter_and_rejects_wrong_or_malformed_codes() -> None:
    service = TotpService()
    secret = TotpSecret.from_bytes(b"12345678901234567890")

    expected = service.generate_code(secret, at_time=1_700_000_000)

    assert service.verify_code(expected, secret, at_time=1_700_000_000) is True
    assert service.verify_code("000000", secret, at_time=1_700_000_000) is False
    assert service.verify_code(expected, secret, at_time=1_700_000_030) is False
    assert service.verify_code("12345", secret, at_time=1_700_000_000) is False
    assert service.verify_code("12345a", secret, at_time=1_700_000_000) is False


def test_secret_generator_requests_fixed_os_entropy_and_returns_base32_material() -> None:
    entropy = DeterministicEntropySource(bytes(range(TOTP_SECRET_ENTROPY_BYTES)))

    secret = TotpSecretGenerator(entropy_source=entropy).generate()

    assert entropy.requested_sizes == [TOTP_SECRET_ENTROPY_BYTES]
    assert secret.get_base32_value() == "AAAQEAYEAUDAOCAJBIFQYDIOB4IBCEQT"
    assert bytes(range(TOTP_SECRET_ENTROPY_BYTES)).hex() not in repr(secret)
    assert secret.get_base32_value() not in repr(secret)


def test_aes_gcm_protection_round_trips_only_with_bound_enrollment_context() -> None:
    actor_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    enrollment_id = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    nonce = bytes(range(12))
    nonce_source: Callable[[int], bytes] = DeterministicEntropySource(nonce)
    protector = Aes256GcmTotpSecretProtector(
        key=bytes(range(32)),
        key_identifier="test-key-2026-08",
        nonce_source=nonce_source,
    )
    secret = TotpSecret.from_bytes(b"12345678901234567890")

    protected = protector.protect(secret, actor_id=actor_id, enrollment_id=enrollment_id)

    assert protected.encryption_algorithm == "aes-256-gcm"
    assert protected.key_identifier == "test-key-2026-08"
    assert protected.nonce == nonce
    assert protected.ciphertext != secret.get_bytes()
    assert secret.get_base32_value() not in repr(protected)
    assert protector.unprotect(protected, actor_id=actor_id, enrollment_id=enrollment_id) == secret

    with pytest.raises(TotpSecretProtectionError, match="protected TOTP material is invalid"):
        protector.unprotect(protected, actor_id=uuid.uuid4(), enrollment_id=enrollment_id)


def test_aes_gcm_protection_rejects_wrong_key_tampering_and_invalid_material() -> None:
    actor_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()
    protector = Aes256GcmTotpSecretProtector(
        key=bytes(range(32)),
        key_identifier="current-key",
        nonce_source=lambda size: b"n" * size,
    )
    protected = protector.protect(
        TotpSecret.from_bytes(b"12345678901234567890"),
        actor_id=actor_id,
        enrollment_id=enrollment_id,
    )
    tampered = ProtectedTotpSecret(
        ciphertext=protected.ciphertext[:-1] + bytes([protected.ciphertext[-1] ^ 1]),
        nonce=protected.nonce,
        key_identifier=protected.key_identifier,
        encryption_algorithm=protected.encryption_algorithm,
    )
    wrong_key = Aes256GcmTotpSecretProtector(
        key=b"x" * 32,
        key_identifier="current-key",
        nonce_source=lambda size: b"z" * size,
    )

    for candidate_protector, candidate_material in (
        (protector, tampered),
        (wrong_key, protected),
    ):
        with pytest.raises(TotpSecretProtectionError, match="protected TOTP material is invalid"):
            candidate_protector.unprotect(
                candidate_material,
                actor_id=actor_id,
                enrollment_id=enrollment_id,
            )

    with pytest.raises(ValueError, match="AES-256-GCM key must contain exactly 32 bytes"):
        Aes256GcmTotpSecretProtector(key=b"short", key_identifier="bad")

    for invalid_key_identifier in ("", " key-1", "key 1", "x" * 129):
        with pytest.raises(ValueError, match="key identifier"):
            Aes256GcmTotpSecretProtector(
                key=bytes(range(32)),
                key_identifier=invalid_key_identifier,
            )


@pytest.mark.parametrize("invalid_field", ["nonce", "ciphertext"])
def test_aes_gcm_unprotect_rejects_non_byte_material(invalid_field: str) -> None:
    actor_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()
    protector = Aes256GcmTotpSecretProtector(
        key=bytes(range(32)),
        key_identifier="current-key",
        nonce_source=lambda size: b"n" * size,
    )
    protected = protector.protect(
        TotpSecret.from_bytes(b"12345678901234567890"),
        actor_id=actor_id,
        enrollment_id=enrollment_id,
    )
    malformed = ProtectedTotpSecret(
        ciphertext=(
            cast(bytes, "not-byte-ciphertext")
            if invalid_field == "ciphertext"
            else protected.ciphertext
        ),
        nonce=(cast(bytes, "n" * 12) if invalid_field == "nonce" else protected.nonce),
        key_identifier=protected.key_identifier,
        encryption_algorithm=protected.encryption_algorithm,
    )

    with pytest.raises(TotpSecretProtectionError, match="protected TOTP material is invalid"):
        protector.unprotect(malformed, actor_id=actor_id, enrollment_id=enrollment_id)


def test_totp_operations_do_not_emit_or_represent_secret_material(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = TotpSecret.from_bytes(b"secret-material-12345")
    protector = Aes256GcmTotpSecretProtector(
        key=bytes(range(32)),
        key_identifier="current-key",
        nonce_source=lambda size: b"n" * size,
    )
    actor_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()

    with caplog.at_level(logging.DEBUG):
        protected = protector.protect(secret, actor_id=actor_id, enrollment_id=enrollment_id)
        code = TotpService().generate_code(secret, at_time=1_700_000_000)
        verified = TotpService().verify_code(code, secret, at_time=1_700_000_000)

    captured = capsys.readouterr()
    base32_secret = secret.get_base32_value()
    assert verified is True
    assert base32_secret not in repr(secret)
    assert base32_secret not in repr(protected)
    assert base32_secret not in captured.out
    assert base32_secret not in captured.err
    assert base32_secret not in caplog.text
