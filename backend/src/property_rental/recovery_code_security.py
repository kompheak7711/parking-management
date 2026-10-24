"""Bounded recovery-code generation and irreversible verifier provider contracts."""

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

# Login sub-slice L7a (Q-2026-10-24-188): 12 symbols of Crockford's Base32 (60 random bits),
# shown in three groups of four such as 7KQ4-M2XD-9PRT, so a person can copy one by hand. The
# check reads any case, with or without the dashes and spaces, and I or L as 1 and O as 0.
RECOVERY_CODE_ENTROPY_BYTES: Final = 8
RECOVERY_CODE_SYMBOLS: Final = 12
RECOVERY_CODE_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SYMBOL_BITS: Final = 5
_LOOK_ALIKES: Final = str.maketrans({"I": "1", "L": "1", "O": "0"})
ARGON2ID_ALGORITHM: Final = "argon2id"
_ARGON2ID_PARAMETERS: Final = RFC_9106_LOW_MEMORY


@dataclass(frozen=True, slots=True)
class RecoveryCodeMaterial:
    """Secret recovery-code material whose representation never exposes its value."""

    _secret_value: str = field(repr=False)

    def get_secret_value(self) -> str:
        """Return code material only to an explicitly authorized presentation boundary."""
        return self._secret_value


class RecoveryCodeGenerator(Protocol):
    """Provider-neutral contract for independent recovery-code generation."""

    def generate(self) -> RecoveryCodeMaterial: ...


@dataclass(frozen=True, slots=True)
class RecoveryCodeVerifierMaterial:
    """Opaque algorithm-neutral values accepted by recovery-code persistence."""

    verifier_encoding: str
    algorithm: str
    work_factor_metadata: Mapping[str, int]


class RecoveryCodeVerifierProvider(Protocol):
    """Provider-neutral contract for irreversible encoding and verification."""

    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial: ...

    def matches(self, candidate: str, verifier_encoding: str) -> bool: ...


def canonical_recovery_code(value: str) -> str:
    """The form a recovery code is hashed and checked in: a code of the L7a shape typed in any
    case, with or without dashes and ASCII spaces, becomes its 12 capital symbols; anything else (an
    older 43-sign code, text that is not all ASCII, or something that is no code) stays as given,
    so it can still match only its own verifier."""
    compact = value.replace(" ", "").replace("-", "").upper().translate(_LOOK_ALIKES)
    if (
        value.isascii()
        and len(compact) == RECOVERY_CODE_SYMBOLS
        and all(symbol in RECOVERY_CODE_ALPHABET for symbol in compact)
    ):
        return compact
    return value


class SecureRecoveryCodeGenerator:
    """Generate recovery codes from operating-system cryptographic entropy."""

    def __init__(self, *, entropy_source: Callable[[int], bytes] = secrets.token_bytes) -> None:
        self._entropy_source = entropy_source

    def generate(self) -> RecoveryCodeMaterial:
        """Generate one independent code of 60 random bits, shown as XXXX-XXXX-XXXX."""
        entropy = self._entropy_source(RECOVERY_CODE_ENTROPY_BYTES)
        if len(entropy) != RECOVERY_CODE_ENTROPY_BYTES:
            raise RuntimeError("recovery-code entropy source returned an invalid length")
        # The first 60 of the 64 bits, five bits per symbol.
        bits = int.from_bytes(entropy, "big") >> (
            RECOVERY_CODE_ENTROPY_BYTES * 8 - RECOVERY_CODE_SYMBOLS * _SYMBOL_BITS
        )
        symbols = "".join(
            RECOVERY_CODE_ALPHABET[(bits >> (_SYMBOL_BITS * place)) & 0b11111]
            for place in reversed(range(RECOVERY_CODE_SYMBOLS))
        )
        return RecoveryCodeMaterial("-".join(symbols[start : start + 4] for start in (0, 4, 8)))


class Argon2idRecoveryCodeVerifierProvider:
    """Encode recovery codes irreversibly with independently salted Argon2id."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher.from_parameters(_ARGON2ID_PARAMETERS)

    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial:
        """Return opaque verifier material compatible with recovery-code persistence."""
        if not _is_valid_code_material(recovery_code):
            raise ValueError("invalid recovery-code material")
        encoding = self._hasher.hash(canonical_recovery_code(recovery_code))
        parameters = _ARGON2ID_PARAMETERS
        return RecoveryCodeVerifierMaterial(
            verifier_encoding=encoding,
            algorithm=ARGON2ID_ALGORITHM,
            work_factor_metadata=MappingProxyType(
                {
                    "version": parameters.version,
                    "memory_cost": parameters.memory_cost,
                    "time_cost": parameters.time_cost,
                    "parallelism": parameters.parallelism,
                    "hash_len": parameters.hash_len,
                    "salt_len": parameters.salt_len,
                }
            ),
        )

    def matches(self, candidate: str, verifier_encoding: str) -> bool:
        """Fail closed when a candidate mismatches or verifier material is malformed. The
        candidate is checked in its canonical form (L7a), as the code was hashed."""
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or not verifier_encoding.startswith(f"${ARGON2ID_ALGORITHM}$")
        ):
            return False
        canonical = canonical_recovery_code(candidate.strip())
        if not _is_valid_code_material(canonical):
            return False
        try:
            return self._hasher.verify(verifier_encoding, canonical)
        except (InvalidHashError, VerificationError):
            return False


def _is_valid_code_material(value: str) -> bool:
    return bool(value) and all(
        character.isprintable() and not character.isspace() for character in value
    )
