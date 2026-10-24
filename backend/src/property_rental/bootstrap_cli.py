"""Controlling-TTY-only protected initial Owner bootstrap command."""

from __future__ import annotations

import argparse
import os
import select
import stat
import termios
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast
from uuid import uuid4

import psycopg

from property_rental.initial_owner_bootstrap import (
    BOOTSTRAP_ACKNOWLEDGEMENT,
    RECOVERY_CODE_COUNT,
    BootstrapFailed,
    BootstrapPasswordPolicy,
    BootstrapRequest,
    BootstrapSecretBundle,
    InitialOwnerBootstrapClosureConnection,
    InitialOwnerBootstrapService,
    PostgresInitialOwnerBootstrapRepository,
)
from property_rental.password_security import PasswordHashService
from property_rental.recovery_code_security import (
    Argon2idRecoveryCodeVerifierProvider,
    SecureRecoveryCodeGenerator,
)
from property_rental.totp_security import (
    Aes256GcmTotpSecretProtector,
    TotpSecretGenerator,
    TotpService,
)

DEFAULT_CEREMONY_TIMEOUT_SECONDS: Final = 120
MAX_DATABASE_URL_BYTES: Final = 4096
MAX_BLOCKLIST_BYTES: Final = 32 * 1024 * 1024
TOTP_KEY_BYTES: Final = 32
TerminalAttributes = list[int | list[bytes | int]]


def _read_fd(fd: int, *, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65_536, maximum_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_bytes:
            raise ValueError("protected input exceeds its bounded size")
    return b"".join(chunks)


def read_root_controlled_totp_key(fd: int) -> bytes:
    """Read a 32-byte key only from an already-open root-owned private regular file."""
    metadata = os.fstat(fd)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("TOTP protection key source is not root-controlled")
    encoded = _read_fd(fd, maximum_bytes=128).strip()
    try:
        key = bytes.fromhex(encoded.decode("ascii")) if len(encoded) == 64 else encoded
    except (UnicodeDecodeError, ValueError):
        raise ValueError("TOTP protection key source is invalid") from None
    if len(key) != TOTP_KEY_BYTES:
        raise ValueError("TOTP protection key source is invalid")
    return key


class ControllingTerminal:
    """Read and write secret material exclusively through one controlling TTY descriptor."""

    def __init__(self, path: Path = Path("/dev/tty")) -> None:
        self._fd = os.open(path, os.O_RDWR)
        if not os.isatty(self._fd):
            os.close(self._fd)
            raise OSError("controlling TTY unavailable")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        os.close(self._fd)

    def _write(self, value: str, *, deadline: float | None = None) -> None:
        remaining = memoryview(value.encode("utf-8"))
        while remaining:
            timeout = None if deadline is None else deadline - time.monotonic()
            if timeout is not None and timeout <= 0:
                raise TimeoutError("bootstrap ceremony deadline expired")
            if deadline is not None:
                _, writable, _ = select.select([], [self._fd], [], timeout)
                if not writable:
                    raise TimeoutError("bootstrap ceremony deadline expired")
            written = os.write(self._fd, remaining)
            if written <= 0:
                raise OSError("controlling TTY write failed")
            remaining = remaining[written:]

    def _readline(
        self,
        *,
        deadline: float | None,
        echo: bool = True,
        prompt: str | None = None,
    ) -> str:
        original: TerminalAttributes | None = None
        if not echo:
            original = termios.tcgetattr(self._fd)
            protected = original.copy()
            protected[3] = cast(int, protected[3]) & ~termios.ECHO
            termios.tcsetattr(self._fd, termios.TCSANOW, protected)
        try:
            if prompt is not None:
                self._write(prompt, deadline=deadline)
            value = bytearray()
            while len(value) <= 4096:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return ""
                readable, _, _ = select.select([self._fd], [], [], remaining)
                if not readable:
                    return ""
                character = os.read(self._fd, 1)
                if not character or character in {b"\n", b"\r"}:
                    break
                value.extend(character)
            if len(value) > 4096:
                raise ValueError("TTY input exceeds its bounded size")
            return value.decode("utf-8")
        finally:
            if original is not None:
                termios.tcsetattr(self._fd, termios.TCSANOW, original)
                self._write("\n")

    def read_password(self) -> str:
        first = self._readline(deadline=None, echo=False, prompt="Initial Owner password: ")
        second = self._readline(deadline=None, echo=False, prompt="Confirm password: ")
        if first != second:
            raise ValueError("bootstrap password confirmation failed")
        return first

    def present_totp_and_read_code(self, secret: str, *, deadline: float) -> str:
        self._write(
            "Enroll this TOTP secret now; it will not be shown again:\n"
            f"{secret}\nEnter the current six-digit code: ",
            deadline=deadline,
        )
        return self._readline(deadline=deadline)

    def present_recovery_codes(self, codes: tuple[str, ...], *, deadline: float) -> None:
        if len(codes) != RECOVERY_CODE_COUNT:
            raise ValueError("invalid recovery-code presentation")
        self._write(
            "Store these 10 single-use recovery codes now; they will not be shown again:\n",
            deadline=deadline,
        )
        for code in codes:
            self._write(f"{code}\n", deadline=deadline)

    def read_acknowledgement(self, *, deadline: float) -> str:
        self._write(f"Type exactly '{BOOTSTRAP_ACKNOWLEDGEMENT}' to commit: ", deadline=deadline)
        return self._readline(deadline=deadline)


class RealBootstrapMaterialFactory:
    """Compose existing password, TOTP protection, and recovery verifier mechanics."""

    def __init__(
        self,
        *,
        totp_key: bytes,
        totp_key_identifier: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._passwords = PasswordHashService()
        self._totp_generator = TotpSecretGenerator()
        self._totp_service = TotpService()
        self._totp_protector = Aes256GcmTotpSecretProtector(
            key=totp_key,
            key_identifier=totp_key_identifier,
        )
        self._recovery_generator = SecureRecoveryCodeGenerator()
        self._recovery_verifiers = Argon2idRecoveryCodeVerifierProvider()
        self._clock = clock

    def create(
        self, *, request: BootstrapRequest, normalized_password: str
    ) -> BootstrapSecretBundle:
        password = self._passwords.hash_password(normalized_password)
        totp = self._totp_generator.generate()
        protected_totp = self._totp_protector.protect(
            totp,
            actor_id=request.actor_id,
            enrollment_id=request.enrollment_id,
        )
        recovery_plaintexts: list[str] = []
        recovery_encodings: list[str] = []
        recovery_algorithm = ""
        recovery_work_factors: dict[str, int] = {}
        for _ in range(RECOVERY_CODE_COUNT):
            plaintext = self._recovery_generator.generate().get_secret_value()
            if plaintext in recovery_plaintexts:
                raise RuntimeError("duplicate recovery-code material")
            verifier = self._recovery_verifiers.encode(plaintext)
            if recovery_algorithm and (
                verifier.algorithm != recovery_algorithm
                or dict(verifier.work_factor_metadata) != recovery_work_factors
            ):
                raise RuntimeError("inconsistent recovery verifier policy")
            recovery_plaintexts.append(plaintext)
            recovery_encodings.append(verifier.verifier_encoding)
            recovery_algorithm = verifier.algorithm
            recovery_work_factors = dict(verifier.work_factor_metadata)
        return BootstrapSecretBundle(
            password_verifier=password.verifier_encoding,
            password_algorithm=password.algorithm,
            password_work_factors=password.work_factor_metadata,
            totp_plaintext=totp.get_base32_value(),
            totp_ciphertext=protected_totp.ciphertext,
            totp_nonce=protected_totp.nonce,
            totp_key_identifier=protected_totp.key_identifier,
            recovery_plaintexts=tuple(recovery_plaintexts),
            recovery_verifiers=tuple(recovery_encodings),
            recovery_algorithm=recovery_algorithm,
            recovery_work_factors=recovery_work_factors,
        )

    def verify_totp(self, bundle: BootstrapSecretBundle, candidate: str) -> bool:
        from property_rental.totp_security import TotpSecret

        return self._totp_service.verify_code(
            candidate,
            TotpSecret.from_base32(bundle.totp_plaintext),
            at_time=int(self._clock()),
        )


def _parser() -> argparse.ArgumentParser:
    # No shortened option names, so `scripts/local/bootstrap-owner.sh` can refuse the options it
    # sets itself (login sub-slice L7c).
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--audit-name", required=True)
    parser.add_argument("--database-url-fd", type=int, default=3)
    parser.add_argument("--totp-key-fd", type=int, default=4)
    parser.add_argument("--password-blocklist-fd", type=int, default=5)
    parser.add_argument("--totp-key-identifier", required=True)
    parser.add_argument(
        "--ceremony-timeout-seconds", type=int, default=DEFAULT_CEREMONY_TIMEOUT_SECONDS
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        database_url = (
            _read_fd(
                parsed.database_url_fd,
                maximum_bytes=MAX_DATABASE_URL_BYTES,
            )
            .decode("utf-8")
            .strip()
        )
        blocklist_text = _read_fd(
            parsed.password_blocklist_fd,
            maximum_bytes=MAX_BLOCKLIST_BYTES,
        ).decode("utf-8")
        blocked = {
            line.removesuffix("\r")
            for line in blocklist_text.split("\n")
            if line.removesuffix("\r")
        }
        if not database_url or not blocked:
            raise ValueError("required protected bootstrap source is empty")
        totp_key = read_root_controlled_totp_key(parsed.totp_key_fd)
        request = BootstrapRequest(
            actor_id=uuid4(),
            correlation_id=uuid4(),
            enrollment_id=uuid4(),
            recovery_set_id=uuid4(),
            recovery_code_ids=tuple(uuid4() for _ in range(RECOVERY_CODE_COUNT)),
            username=parsed.username,
            display_name=parsed.display_name,
            audit_name=parsed.audit_name,
        )
        with psycopg.connect(database_url) as connection, ControllingTerminal() as terminal:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                if cursor.fetchone() != ("prm_bootstrap",):
                    raise RuntimeError("dedicated bootstrap database identity required")
            service = InitialOwnerBootstrapService(
                repository=PostgresInitialOwnerBootstrapRepository(
                    cast(InitialOwnerBootstrapClosureConnection, connection)
                ),
                terminal=terminal,
                password_policy=BootstrapPasswordPolicy(blocked_passwords=blocked),
                material_factory=RealBootstrapMaterialFactory(
                    totp_key=totp_key,
                    totp_key_identifier=parsed.totp_key_identifier,
                ),
                ceremony_timeout_seconds=parsed.ceremony_timeout_seconds,
            )
            service.run(request)
        return 0
    except (BootstrapFailed, OSError, UnicodeError, ValueError, RuntimeError, psycopg.Error):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
