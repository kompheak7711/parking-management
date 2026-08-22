"""RFC 6238 TOTP mechanics and authenticated enrollment-secret protection."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOTP_SECRET_ENTROPY_BYTES: Final = 20
AES_256_KEY_BYTES: Final = 32
AES_GCM_NONCE_BYTES: Final = 12
TOTP_DEFAULT_DIGITS: Final = 6
TOTP_DEFAULT_PERIOD_SECONDS: Final = 30
TOTP_DEFAULT_ALGORITHM: Final = "sha1"
AES_256_GCM_ALGORITHM: Final = "aes-256-gcm"

TotpAlgorithm = Literal["sha1", "sha256", "sha512"]
_HASH_FACTORIES: Final = {
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


@dataclass(frozen=True, slots=True)
class TotpParameters:
    """RFC 6238 parameters persisted with protected enrollment material."""

    algorithm: TotpAlgorithm = TOTP_DEFAULT_ALGORITHM
    digits: int = TOTP_DEFAULT_DIGITS
    period_seconds: int = TOTP_DEFAULT_PERIOD_SECONDS

    def __post_init__(self) -> None:
        if self.algorithm not in _HASH_FACTORIES:
            raise ValueError("unsupported TOTP algorithm")
        if self.digits not in {6, 8}:
            raise ValueError("TOTP digits must be 6 or 8")
        if self.period_seconds <= 0:
            raise ValueError("TOTP period must be positive")


_DEFAULT_TOTP_PARAMETERS: Final = TotpParameters()


@dataclass(frozen=True, slots=True)
class TotpSecret:
    """Secret TOTP seed whose representation never exposes its value."""

    _secret_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self._secret_bytes) < TOTP_SECRET_ENTROPY_BYTES:
            raise ValueError("TOTP secret must contain at least 160 bits")

    @classmethod
    def from_bytes(cls, secret_bytes: bytes) -> TotpSecret:
        """Construct validated secret material from a trusted cryptographic boundary."""
        return cls(bytes(secret_bytes))

    @classmethod
    def from_base32(cls, encoded: str) -> TotpSecret:
        """Decode unpadded RFC 4648 Base32 enrollment material."""
        normalized = encoded.strip().upper()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("invalid Base32 TOTP secret")
        padding = "=" * (-len(normalized) % 8)
        try:
            decoded = base64.b32decode(normalized + padding, casefold=False)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid Base32 TOTP secret") from error
        return cls.from_bytes(decoded)

    def get_bytes(self) -> bytes:
        """Return seed bytes only to an explicitly authorized cryptographic boundary."""
        return self._secret_bytes

    def get_base32_value(self) -> str:
        """Return provisioning material only to an explicitly authorized enrollment boundary."""
        return base64.b32encode(self._secret_bytes).rstrip(b"=").decode("ascii")


class TotpSecretGenerator:
    """Generate TOTP seeds from operating-system cryptographic entropy."""

    def __init__(self, *, entropy_source: Callable[[int], bytes] = secrets.token_bytes) -> None:
        self._entropy_source = entropy_source

    def generate(self) -> TotpSecret:
        """Generate one independent 160-bit enrollment seed."""
        entropy = self._entropy_source(TOTP_SECRET_ENTROPY_BYTES)
        if len(entropy) != TOTP_SECRET_ENTROPY_BYTES:
            raise RuntimeError("TOTP entropy source returned an invalid length")
        return TotpSecret.from_bytes(entropy)


class TotpService:
    """Generate and compare exact-counter RFC 6238 codes without applying access policy."""

    def generate_code(
        self,
        secret: TotpSecret,
        *,
        at_time: int,
        parameters: TotpParameters = _DEFAULT_TOTP_PARAMETERS,
    ) -> str:
        """Generate the code for one Unix-time counter."""
        if at_time < 0:
            raise ValueError("TOTP time cannot be negative")
        counter = at_time // parameters.period_seconds
        digest = hmac.digest(
            secret.get_bytes(),
            struct.pack(">Q", counter),
            _HASH_FACTORIES[parameters.algorithm],
        )
        offset = digest[-1] & 0x0F
        binary_code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFF_FFFF
        return f"{binary_code % (10**parameters.digits):0{parameters.digits}d}"

    def verify_code(
        self,
        candidate: str,
        secret: TotpSecret,
        *,
        at_time: int,
        parameters: TotpParameters = _DEFAULT_TOTP_PARAMETERS,
    ) -> bool:
        """Compare one candidate for the exact counter and fail closed on malformed input."""
        if (
            len(candidate) != parameters.digits
            or not candidate.isascii()
            or not candidate.isdigit()
        ):
            return False
        expected = self.generate_code(secret, at_time=at_time, parameters=parameters)
        return hmac.compare_digest(candidate, expected)


@dataclass(frozen=True, slots=True)
class ProtectedTotpSecret:
    """Opaque authenticated ciphertext accepted by MFA enrollment persistence."""

    ciphertext: bytes = field(repr=False)
    nonce: bytes
    key_identifier: str
    encryption_algorithm: str


class TotpSecretProtectionError(RuntimeError):
    """Generic fail-closed protected-material error without secret details."""


class Aes256GcmTotpSecretProtector:
    """Protect TOTP seeds with AES-256-GCM and enrollment-bound associated data."""

    def __init__(
        self,
        *,
        key: bytes,
        key_identifier: str,
        nonce_source: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if len(key) != AES_256_KEY_BYTES:
            raise ValueError("AES-256-GCM key must contain exactly 32 bytes")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", key_identifier) is None:
            raise ValueError("key identifier is invalid")
        self._aead = AESGCM(key)
        self._key_identifier = key_identifier
        self._nonce_source = nonce_source

    def protect(
        self,
        secret: TotpSecret,
        *,
        actor_id: UUID,
        enrollment_id: UUID,
    ) -> ProtectedTotpSecret:
        """Encrypt and authenticate one seed without retaining plaintext material."""
        nonce = self._nonce_source(AES_GCM_NONCE_BYTES)
        if len(nonce) != AES_GCM_NONCE_BYTES:
            raise RuntimeError("AES-GCM nonce source returned an invalid length")
        associated_data = self._associated_data(
            actor_id=actor_id,
            enrollment_id=enrollment_id,
            key_identifier=self._key_identifier,
        )
        ciphertext = self._aead.encrypt(nonce, secret.get_bytes(), associated_data)
        return ProtectedTotpSecret(
            ciphertext=ciphertext,
            nonce=nonce,
            key_identifier=self._key_identifier,
            encryption_algorithm=AES_256_GCM_ALGORITHM,
        )

    def unprotect(
        self,
        protected: ProtectedTotpSecret,
        *,
        actor_id: UUID,
        enrollment_id: UUID,
    ) -> TotpSecret:
        """Authenticate and decrypt one seed, returning only a secret wrapper."""
        if (
            protected.encryption_algorithm != AES_256_GCM_ALGORITHM
            or protected.key_identifier != self._key_identifier
            or not isinstance(protected.nonce, bytes)
            or len(protected.nonce) != AES_GCM_NONCE_BYTES
            or not isinstance(protected.ciphertext, bytes)
        ):
            raise TotpSecretProtectionError("protected TOTP material is invalid")
        associated_data = self._associated_data(
            actor_id=actor_id,
            enrollment_id=enrollment_id,
            key_identifier=protected.key_identifier,
        )
        try:
            plaintext = self._aead.decrypt(
                protected.nonce,
                protected.ciphertext,
                associated_data,
            )
            return TotpSecret.from_bytes(plaintext)
        except (InvalidTag, ValueError) as error:
            raise TotpSecretProtectionError("protected TOTP material is invalid") from error

    @staticmethod
    def _associated_data(*, actor_id: UUID, enrollment_id: UUID, key_identifier: str) -> bytes:
        return (
            f"property-rental:totp:v1:{actor_id}:{enrollment_id}:"
            f"{AES_256_GCM_ALGORITHM}:{key_identifier}"
        ).encode()
