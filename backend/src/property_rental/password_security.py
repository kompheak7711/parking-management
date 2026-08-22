"""Salted adaptive password verifier mechanics for DB-AUTH-002."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from unicodedata import normalize

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

ARGON2ID_ALGORITHM: Final = "argon2id"
_ARGON2ID_ENCODING_PREFIX: Final = f"${ARGON2ID_ALGORITHM}$"
_ARGON2ID_PARAMETERS: Final = RFC_9106_LOW_MEMORY


@dataclass(frozen=True, slots=True)
class PasswordCredentialMaterial:
    """Algorithm-neutral values accepted by password credential persistence."""

    verifier_encoding: str
    algorithm: str
    work_factor_metadata: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    """Secret-free password verification outcome."""

    is_valid: bool
    needs_rehash: bool


class PasswordHashService:
    """Create current salted adaptive password verifier material."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher.from_parameters(_ARGON2ID_PARAMETERS)

    def hash_password(self, password: str) -> PasswordCredentialMaterial:
        """Hash a password with the current Argon2id policy and a fresh random salt."""
        encoding = self._hasher.hash(normalize("NFC", password))
        parameters = _ARGON2ID_PARAMETERS
        metadata = MappingProxyType(
            {
                "version": parameters.version,
                "memory_cost": parameters.memory_cost,
                "time_cost": parameters.time_cost,
                "parallelism": parameters.parallelism,
                "hash_len": parameters.hash_len,
                "salt_len": parameters.salt_len,
            }
        )
        return PasswordCredentialMaterial(
            verifier_encoding=encoding,
            algorithm=ARGON2ID_ALGORITHM,
            work_factor_metadata=metadata,
        )

    def verify_password(self, password: str, verifier_encoding: str) -> PasswordVerification:
        """Verify a password and identify verifier material below the current policy."""
        if not verifier_encoding.startswith(_ARGON2ID_ENCODING_PREFIX):
            return PasswordVerification(is_valid=False, needs_rehash=False)
        try:
            is_valid = self._hasher.verify(verifier_encoding, normalize("NFC", password))
        except (InvalidHashError, VerificationError):
            return PasswordVerification(is_valid=False, needs_rehash=False)
        return PasswordVerification(
            is_valid=is_valid,
            needs_rehash=is_valid and self._hasher.check_needs_rehash(verifier_encoding),
        )
