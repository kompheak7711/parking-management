"""Focused deterministic tests for recovery-code cryptographic providers."""

import logging
from collections.abc import Callable
from dataclasses import fields

import pytest

from property_rental.recovery_code_security import (
    RECOVERY_CODE_ALPHABET,
    RECOVERY_CODE_ENTROPY_BYTES,
    Argon2idRecoveryCodeVerifierProvider,
    RecoveryCodeGenerator,
    RecoveryCodeVerifierProvider,
    SecureRecoveryCodeGenerator,
    canonical_recovery_code,
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
    """Login sub-slice L7a (Q-2026-10-24-188): each code takes 8 fresh bytes and shows their
    first 60 bits as 12 Crockford Base32 symbols in three groups of four."""
    entropy = DeterministicEntropySource([bytes(range(8)), bytes(range(8, 16))])

    first, second = generate_twice(lambda: SecureRecoveryCodeGenerator(entropy_source=entropy))

    assert entropy.requested_sizes == [RECOVERY_CODE_ENTROPY_BYTES, RECOVERY_CODE_ENTROPY_BYTES]
    assert RECOVERY_CODE_ENTROPY_BYTES == 8
    assert first == "000G-40R4-0M30"
    assert second == "104G-M2RC-1M70"
    assert first != second


@pytest.mark.parametrize(
    ("entropy", "code"),
    [(b"\xff" * 8, "ZZZZ-ZZZZ-ZZZZ"), (bytes(8), "0000-0000-0000")],
)
def test_a_recovery_code_is_twelve_symbols_of_the_hand_copy_alphabet(
    entropy: bytes, code: str
) -> None:
    """Login sub-slice L7a: the edges of the 60 bits; the alphabet is 32 distinct symbols with
    no I, L, O or U, so no code ever shows them."""
    assert len(set(RECOVERY_CODE_ALPHABET)) == len(RECOVERY_CODE_ALPHABET) == 32
    assert not set(RECOVERY_CODE_ALPHABET) & set("ILOU")
    generated = SecureRecoveryCodeGenerator(entropy_source=lambda _size: entropy).generate()

    assert generated.get_secret_value() == code
    assert not set(code) & set("ILOU")


def test_a_recovery_code_matches_in_any_case_with_or_without_dashes_and_look_alikes() -> None:
    """Login sub-slice L7a: a code is checked as typed in any case, with or without its dashes
    and spaces, with I or L read as 1 and O as 0; another code, or a symbol outside the
    alphabet, does not match; an older 43-sign code still matches only as written."""
    provider = Argon2idRecoveryCodeVerifierProvider()
    verifier = provider.encode("1KQ0-M2XD-9PRT").verifier_encoding

    for typed in (
        "1KQ0-M2XD-9PRT",
        "1kq0m2xd9prt",
        " 1KQ0 M2XD 9PRT ",
        "IKQO-M2XD-9PRT",
        "lkqo-m2xd-9prt",
    ):
        assert provider.matches(typed, verifier) is True, typed
    for wrong in (
        "1KQ0-M2XD-9PRV",
        "1KQ0-M2XD-9PRU",
        "1KQ0-M2XD",
        "1KQ0-M2XD-9PRT-0000",
        "1KQ0\tM2XD\x1c9PRT",
        "\u0131KQ0-M2XD-9PRT",
        "\uff11KQ0-M2XD-9PRT",
    ):
        assert provider.matches(wrong, verifier) is False, wrong

    older = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    older_verifier = provider.encode(older).verifier_encoding
    assert provider.matches(older, older_verifier) is True
    assert provider.matches(older.lower(), older_verifier) is False
    assert provider.matches(None, verifier) is False  # type: ignore[arg-type]


def test_the_canonical_form_keeps_anything_that_is_not_a_code_as_given() -> None:
    """Login sub-slice L7a: only the 12-symbol shape is changed for the check."""
    assert canonical_recovery_code("7kq4 m2xd-9prt") == "7KQ4M2XD9PRT"
    assert canonical_recovery_code("not-a-code") == "not-a-code"
    assert canonical_recovery_code("7KQ4-M2XD-9PR") == "7KQ4-M2XD-9PR"
    # Only ASCII: a dotless i or a long s, which Python turns into I or S, is not read as a code.
    assert canonical_recovery_code("\u0131kq0m2xd9prt") == "\u0131kq0m2xd9prt"
    assert canonical_recovery_code("7kq4-m2xd-9p\u017ft") == "7kq4-m2xd-9p\u017ft"


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
    entropy = DeterministicEntropySource([bytes(range(8))])
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
    # Login sub-slice L7a: nor the form the check uses.
    canonical = secret.replace("-", "")
    assert canonical not in captured.out + captured.err + caplog.text
