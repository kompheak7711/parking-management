"""Salted adaptive password verifier mechanics for DB-AUTH-002, the shared rule for every new
password and the one-time password of the Owner's reset (login sub-slice L4)."""

import secrets
from collections.abc import Iterable, Mapping
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
# The owner-approved rule of every new password (SEC-073, API-100, owner answer (a) to
# Q-2026-10-21-155): 15 to 128 code points before and after NFC, not on the local blocklist.
PASSWORD_MIN_CODE_POINTS: Final = 15
PASSWORD_MAX_CODE_POINTS: Final = 128
# The one-time password (Q-2026-10-24-185 point 2): 4 groups of 4 signs that are easy to read
# aloud (no 0, 1, i, l or o), about 79 bits.
ONE_TIME_PASSWORD_ALPHABET: Final = "23456789abcdefghjkmnpqrstuvwxyz"
ONE_TIME_PASSWORD_GROUPS: Final = 4
ONE_TIME_PASSWORD_GROUP_LENGTH: Final = 4


def password_comparison_value(value: str) -> str:
    """The form a password is compared in with the blocklist and the account's names."""
    return normalize("NFC", value).casefold()


def blocked_passwords(values: Iterable[str]) -> frozenset[str]:
    """The blocklist in its comparison form."""
    return frozenset(password_comparison_value(value) for value in values)


def parse_password_blocklist(text: str) -> frozenset[str]:
    """One blocked password per line (a final CR removed, empty lines skipped), as the
    protected bootstrap reads it."""
    return blocked_passwords(
        line.removesuffix("\r") for line in text.split("\n") if line.removesuffix("\r")
    )


def validate_new_password(
    password: str,
    *,
    blocked: frozenset[str],
    context: tuple[str, ...] = (),
) -> str:
    """The NFC form of an acceptable new password, or `ValueError`: 15 to 128 code points
    before and after NFC, not on the blocklist (in comparison form, see `blocked_passwords`) and
    not one of the account's own names."""
    if len(password) < PASSWORD_MIN_CODE_POINTS or len(password) > PASSWORD_MAX_CODE_POINTS:
        raise ValueError("new password rejected")
    normalized = normalize("NFC", password)
    comparison = password_comparison_value(normalized)
    contextual_values = {
        password_comparison_value(value)
        for value in context
        if value and password_comparison_value(value)
    }
    if (
        not normalized
        or len(normalized) < PASSWORD_MIN_CODE_POINTS
        or len(normalized) > PASSWORD_MAX_CODE_POINTS
        or comparison in blocked
        or comparison in contextual_values
    ):
        raise ValueError("new password rejected")
    return normalized


def one_time_password_forms(password: str) -> tuple[str, ...]:
    """The typed password, and the one-time password it may be written from (login sub-slice L4
    review round 1): the same letters and digits in another case, without the hyphens or with
    spaces count as the one-time password too, so they are compared with its verifier."""
    letters = "".join(
        character
        for character in password.casefold()
        if character.isascii() and character.isalnum()
    )
    group_count = ONE_TIME_PASSWORD_GROUPS * ONE_TIME_PASSWORD_GROUP_LENGTH
    if len(letters) != group_count or not set(letters) <= set(ONE_TIME_PASSWORD_ALPHABET):
        return (password,)
    written = "-".join(
        letters[start : start + ONE_TIME_PASSWORD_GROUP_LENGTH]
        for start in range(0, group_count, ONE_TIME_PASSWORD_GROUP_LENGTH)
    )
    return (password,) if written == password else (password, written)


def new_one_time_password() -> str:
    """A random one-time password such as `k7m2-x9qp-4hrt-w3nd`; it meets the new-password rule
    (19 code points)."""
    return "-".join(
        "".join(
            secrets.choice(ONE_TIME_PASSWORD_ALPHABET)
            for _ in range(ONE_TIME_PASSWORD_GROUP_LENGTH)
        )
        for _ in range(ONE_TIME_PASSWORD_GROUPS)
    )


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
