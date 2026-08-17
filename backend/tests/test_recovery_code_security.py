"""Focused deterministic tests for recovery-code cryptographic providers."""

import logging
from collections.abc import Callable
from dataclasses import fields

import pytest

from property_rental.recovery_code_security import (
    RECOVERY_CODE_ENTROPY_BYTES,
    Argon2idRecoveryCodeVerifierProvider,
    RecoveryCodeGenerator,
    RecoveryCodeVerifierProvider,
    SecureRecoveryCodeGenerator,
)


class DeterministicEntropySource:
    def __init__(self, outputs: list[bytes]) -> None:
        self._outputs = iter(outputs)
        self.requested_sizes: list[int] = []

    def __call__(self, size: int) -> bytes:
        self.requested_sizes.append(size)
        return next(self._outputs)


def generate_twice(generator_factory: Callable[[], RecoveryCodeGenerator]) -> tuple[str, str]:
    generator = generator_factory()
    return (
        generator.generate().get_secret_value(),
        generator.generate().get_secret_value(),
    )


def test_secure_generator_requests_independent_high_entropy_material() -> None:
    entropy = DeterministicEntropySource([bytes(range(32)), bytes(range(32, 64))])

    first, second = generate_twice(lambda: SecureRecoveryCodeGenerator(entropy_source=entropy))

    assert entropy.requested_sizes == [RECOVERY_CODE_ENTROPY_BYTES, RECOVERY_CODE_ENTROPY_BYTES]
    assert first == "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    assert second == "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8"
    assert first != second


def test_verifier_provider_contract_encodes_and_verifies_independently_salted_codes() -> None:
    provider: RecoveryCodeVerifierProvider = Argon2idRecoveryCodeVerifierProvider()
    secret = "independent-high-entropy-recovery-code"

    first = provider.encode(secret)
    second = provider.encode(secret)

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
    assert provider.matches(secret, first.verifier_encoding) is True
    assert provider.matches("different-recovery-code", first.verifier_encoding) is False


@pytest.mark.parametrize("malformed_code", ["", "   ", "code\nwith-control"])
def test_verifier_provider_rejects_malformed_code_input(malformed_code: str) -> None:
    provider = Argon2idRecoveryCodeVerifierProvider()

    with pytest.raises(ValueError, match="invalid recovery-code material"):
        provider.encode(malformed_code)


@pytest.mark.parametrize(
    ("candidate", "verifier_encoding"),
    [
        ("", "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$ZGlnaWVzdA"),
        ("   ", "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$ZGlnaWVzdA"),
        ("candidate", ""),
        ("candidate", "not-an-opaque-verifier"),
        ("candidate", "$different$parameters$material"),
    ],
)
def test_verifier_provider_fails_closed_for_malformed_verification_input(
    candidate: str,
    verifier_encoding: str,
) -> None:
    provider = Argon2idRecoveryCodeVerifierProvider()

    assert provider.matches(candidate, verifier_encoding) is False


def test_verifier_output_is_non_plaintext_and_has_no_reversible_material() -> None:
    provider = Argon2idRecoveryCodeVerifierProvider()
    secret = "non-reversible-recovery-code-material"

    verifier = provider.encode(secret)

    assert secret not in verifier.verifier_encoding
    assert {field.name for field in fields(verifier)} == {
        "verifier_encoding",
        "algorithm",
        "work_factor_metadata",
    }
    assert not hasattr(verifier, "recovery_code")
    assert not hasattr(verifier, "decode")
    assert not hasattr(verifier, "decrypt")


def test_code_and_verifier_operations_do_not_emit_or_represent_secret_material(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entropy = DeterministicEntropySource([bytes(range(32))])
    generator: RecoveryCodeGenerator = SecureRecoveryCodeGenerator(entropy_source=entropy)
    provider: RecoveryCodeVerifierProvider = Argon2idRecoveryCodeVerifierProvider()
    code = generator.generate()
    secret = code.get_secret_value()

    with caplog.at_level(logging.DEBUG):
        verifier = provider.encode(secret)
        result = provider.matches(secret, verifier.verifier_encoding)

    captured = capsys.readouterr()
    assert result is True
    assert secret not in repr(code)
    assert secret not in repr(verifier)
    assert secret not in repr(result)
    assert secret not in captured.out
    assert secret not in captured.err
    assert secret not in caplog.text
