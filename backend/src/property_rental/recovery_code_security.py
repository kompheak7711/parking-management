"""Bounded recovery-code generation and irreversible verifier provider contracts."""

import base64
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

RECOVERY_CODE_ENTROPY_BYTES: Final = 32
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


class SecureRecoveryCodeGenerator:
    """Generate URL-safe recovery codes from operating-system cryptographic entropy."""

    def __init__(self, *, entropy_source: Callable[[int], bytes] = secrets.token_bytes) -> None:
        self._entropy_source = entropy_source

    def generate(self) -> RecoveryCodeMaterial:
        """Generate one independent code with a fixed cryptographic entropy floor."""
        entropy = self._entropy_source(RECOVERY_CODE_ENTROPY_BYTES)
        if len(entropy) != RECOVERY_CODE_ENTROPY_BYTES:
            raise RuntimeError("recovery-code entropy source returned an invalid length")
        encoded = base64.urlsafe_b64encode(entropy).rstrip(b"=").decode("ascii")
        return RecoveryCodeMaterial(encoded)


class Argon2idRecoveryCodeVerifierProvider:
    """Encode recovery codes irreversibly with independently salted Argon2id."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher.from_parameters(_ARGON2ID_PARAMETERS)

    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial:
        """Return opaque verifier material compatible with recovery-code persistence."""
        if not _is_valid_code_material(recovery_code):
            raise ValueError("invalid recovery-code material")
        encoding = self._hasher.hash(recovery_code)
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
        """Fail closed when a candidate mismatches or verifier material is malformed."""
        if not _is_valid_code_material(candidate) or not verifier_encoding.startswith(
            f"${ARGON2ID_ALGORITHM}$"
        ):
            return False
        try:
            return self._hasher.verify(verifier_encoding, candidate)
        except (InvalidHashError, VerificationError):
            return False


def _is_valid_code_material(value: str) -> bool:
    return bool(value) and all(
        character.isprintable() and not character.isspace() for character in value
    )
