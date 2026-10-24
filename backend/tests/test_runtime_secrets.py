"""Login sub-slice L3c-1: the protected key file, its derived key and the start-up rule (DL-081,
owner answers (a) to Q-2026-10-21-155 and Q-2026-10-23-175, SEC-073)."""

import asyncio
import io
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

import property_rental.app as app_module
from property_rental.app import create_app
from property_rental.auth_api import UnavailableAuthenticationFlow
from property_rental.bootstrap_cli import MAX_BLOCKLIST_BYTES
from property_rental.logging import create_application_logger
from property_rental.runtime_secrets import (
    PasswordBlocklistUnavailable,
    ProtectedKeyUnavailable,
    derive_sign_in_try_key,
    derive_totp_key_identifier,
    read_password_blocklist,
    read_protected_totp_key,
)
from property_rental.settings import Settings
from property_rental.totp_security import Aes256GcmTotpSecretProtector

KEY_HEX = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
UNUSED_DATABASE = "postgresql://unused.invalid/unused"
BLOCKLIST = frozenset({"password1234567"})


@pytest.mark.skipif(os.geteuid() == 0, reason="a file root writes is root-owned")
def test_the_key_reader_refuses_a_missing_or_unprotected_file_without_its_content(
    tmp_path: Path,
) -> None:
    """A file the test user owns is not root-controlled, and a missing file cannot be opened;
    both refuse with a plain message that holds neither the path's content nor the key."""
    unprotected = tmp_path / "totp_key"
    unprotected.write_text(KEY_HEX, encoding="ascii")
    os.chmod(unprotected, 0o600)
    for path in (str(unprotected), str(tmp_path / "missing")):
        with pytest.raises(ProtectedKeyUnavailable) as refused:
            read_protected_totp_key(path)
        assert KEY_HEX not in str(refused.value) and str(tmp_path) not in str(refused.value)


def test_the_key_reader_accepts_a_root_controlled_file_through_the_bootstrap_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the descriptor reported as a root-owned private regular file (the bootstrap's own
    checks), the 64 hex characters give the 32-byte key; group or other access still refuses; an
    inherited descriptor read to its end is read again from the start (review round 2)."""
    key_file = tmp_path / "totp_key"
    key_file.write_text(KEY_HEX + "\n", encoding="ascii")
    real_fstat = os.fstat

    def as_root(mode: int) -> Callable[[int], os.stat_result]:
        def fstat(descriptor: int) -> os.stat_result:
            found = real_fstat(descriptor)
            fields = list(found)
            fields[stat.ST_MODE] = stat.S_IFREG | mode
            fields[stat.ST_UID] = 0
            return os.stat_result(fields)

        return fstat

    monkeypatch.setattr(os, "fstat", as_root(0o600))
    assert read_protected_totp_key(str(key_file)) == bytes.fromhex(KEY_HEX)
    monkeypatch.setattr(os, "fstat", as_root(0o640))
    with pytest.raises(ProtectedKeyUnavailable):
        read_protected_totp_key(str(key_file))

    # Review round 2: a `/dev/fd/<n>` path whose inherited descriptor was already read to the end
    # is read again from the start (it shares the offset on macOS).
    monkeypatch.setattr(os, "fstat", as_root(0o600))
    inherited = os.open(key_file, os.O_RDONLY)
    try:
        while os.read(inherited, 4096):
            pass
        assert read_protected_totp_key(f"/dev/fd/{inherited}") == bytes.fromhex(KEY_HEX)
    finally:
        os.close(inherited)


def test_an_inherited_descriptor_that_is_closed_a_pipe_or_not_root_owned_is_refused(
    tmp_path: Path,
) -> None:
    """The copy of an inherited `/dev/fd/<n>` (login sub-slice L7c review round 3) keeps the old
    refusals: a closed descriptor, a pipe (refused at once, never waiting), and, when not run as
    root, a private file the person owns."""
    closed = os.open(tmp_path, os.O_RDONLY)
    os.close(closed)
    with pytest.raises(ProtectedKeyUnavailable, match="cannot be opened"):
        read_protected_totp_key(f"/dev/fd/{closed}")
    reading, writing = os.pipe()
    try:
        with pytest.raises(ProtectedKeyUnavailable, match="not usable"):
            read_protected_totp_key(f"/dev/fd/{reading}")
    finally:
        os.close(reading)
        os.close(writing)
    if os.geteuid() != 0:
        own = tmp_path / "totp_protection_key"
        own.write_text(KEY_HEX + "\n", encoding="ascii")
        os.chmod(own, 0o600)
        inherited = os.open(own, os.O_RDONLY)
        try:
            with pytest.raises(ProtectedKeyUnavailable, match="not usable"):
                read_protected_totp_key(f"/dev/fd/{inherited}")
        finally:
            os.close(inherited)


@pytest.mark.skipif(os.geteuid() != 0, reason="only root can make a root-only key and drop")
def test_an_inherited_root_only_key_is_read_after_the_drop_to_another_user(
    tmp_path: Path,
) -> None:
    """The local run (login sub-slice L7c review round 2): the helper opens the root-only key as
    root, puts it on a descriptor and drops to the person who ran sudo; the API then reads
    `/dev/fd/<n>`. Opening that path again is refused on Linux (the file is root-only), so the
    reader copies the descriptor instead."""
    key_file = tmp_path / "totp_protection_key"
    key_file.write_text(KEY_HEX + "\n", encoding="ascii")
    os.chmod(key_file, 0o600)
    reading, writing = os.pipe()
    child = os.fork()
    if child == 0:  # pragma: no cover - runs in the child
        outcome = b"failed"
        try:
            inherited = os.open(key_file, os.O_RDONLY)
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            try:
                os.open(f"/dev/fd/{inherited}", os.O_RDONLY)
                reopened = b"reopened"
            except PermissionError:
                reopened = b"refused"
            key = read_protected_totp_key(f"/dev/fd/{inherited}")
            outcome = reopened + (b" key" if key == bytes.fromhex(KEY_HEX) else b" wrong")
        finally:
            os.write(writing, outcome)
            os._exit(0)
    os.close(writing)
    os.waitpid(child, 0)
    with os.fdopen(reading, "rb") as answer:
        result = answer.read()
    assert result.endswith(b" key")
    if os.uname().sysname == "Linux":
        assert result == b"refused key"


def test_the_wrong_try_key_is_derived_and_never_the_protection_key() -> None:
    """HKDF-SHA256 with a fixed purpose: 32 bytes, the same for the same key, different for
    another key, and never the protection key itself."""
    protection = bytes.fromhex(KEY_HEX)
    derived = derive_sign_in_try_key(protection)
    assert len(derived) == 32 and derived != protection
    assert derive_sign_in_try_key(protection) == derived
    assert derive_sign_in_try_key(bytes(32)) != derived


def test_the_key_identifier_of_a_new_sign_in_code_names_the_key_without_showing_it() -> None:
    """Login sub-slice L3c-2b: the identifier stored with a sign-in code set up at sign-in is
    derived with HKDF-SHA256 under its own purpose: a valid key identifier, the same for the same
    key, another for another key, and neither the key nor the wrong-try key."""
    protection = bytes.fromhex(KEY_HEX)
    identifier = derive_totp_key_identifier(protection)
    assert re.fullmatch(r"runtime-[0-9a-f]{32}", identifier) is not None
    assert derive_totp_key_identifier(protection) == identifier
    assert derive_totp_key_identifier(bytes(32)) != identifier
    assert KEY_HEX[:16] not in identifier
    assert derive_sign_in_try_key(protection).hex()[:32] not in identifier
    Aes256GcmTotpSecretProtector(key=protection, key_identifier=identifier)


def test_the_two_protected_paths_are_settings_and_production_needs_the_key_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settings read only the two paths; with a database, `staging` and `production` refuse
    to start without the key file, and an unprotected key file refuses in any environment;
    development without a key file starts."""
    monkeypatch.setenv("APP_TOTP_KEY_FILE", "/dev/fd/4")
    monkeypatch.setenv("APP_PASSWORD_BLOCKLIST_FILE", "/usr/local/etc/prm/blocklist.txt")
    settings = Settings()
    assert settings.totp_key_file == "/dev/fd/4"
    assert settings.password_blocklist_file == "/usr/local/etc/prm/blocklist.txt"
    monkeypatch.delenv("APP_TOTP_KEY_FILE")
    monkeypatch.delenv("APP_PASSWORD_BLOCKLIST_FILE")

    # Review round 1: an allowed list; every other environment name refuses.
    for environment in ("staging", "production", "Production", "prod", "staging-2"):
        with pytest.raises(ProtectedKeyUnavailable):
            create_app(Settings(environment=environment, database_url=SecretStr(UNUSED_DATABASE)))
    unprotected = tmp_path / "totp_key"
    unprotected.write_text(KEY_HEX, encoding="ascii")
    if os.geteuid() != 0:
        with pytest.raises(ProtectedKeyUnavailable):
            create_app(
                Settings(database_url=SecretStr(UNUSED_DATABASE), totp_key_file=str(unprotected))
            )
    for environment in ("development", "test"):
        assert (
            create_app(Settings(environment=environment, database_url=SecretStr(UNUSED_DATABASE)))
            is not None
        )


def test_create_app_gives_the_derived_key_to_the_sign_in_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (independent reviewer's set-up): with the key file, also in `production`,
    the app starts and gives the sign-in flow the key derived from it; without one, in
    `development`, the flow gets no key. Login sub-slice L3c-2a: the flow also gets the
    protection key itself, to check sign-in codes, and none without the key file."""
    monkeypatch.delenv("APP_TOTP_KEY_FILE", raising=False)
    seen: list[bytes | None] = []
    protection_keys: list[bytes | None] = []

    def recording_flow(
        database_url: str,
        *,
        sign_in_try_key: bytes | None = None,
        totp_protection_key: bytes | None = None,
        password_blocklist: frozenset[str] = frozenset(),
    ) -> UnavailableAuthenticationFlow:
        seen.append(sign_in_try_key)
        protection_keys.append(totp_protection_key)
        blocklists.append(password_blocklist)
        return UnavailableAuthenticationFlow()

    blocklists: list[frozenset[str]] = []
    monkeypatch.setattr(app_module, "read_protected_totp_key", lambda _: bytes.fromhex(KEY_HEX))
    monkeypatch.setattr(app_module, "read_password_blocklist", lambda _: BLOCKLIST)
    monkeypatch.setattr(app_module, "PostgresAuthenticationFlow", recording_flow)
    create_app(
        Settings(
            environment="production",
            database_url=SecretStr(UNUSED_DATABASE),
            totp_key_file="/dev/fd/9",
            password_blocklist_file="/dev/fd/8",
        )
    )
    create_app(Settings(environment="development", database_url=SecretStr(UNUSED_DATABASE)))
    assert seen == [derive_sign_in_try_key(bytes.fromhex(KEY_HEX)), None]
    assert protection_keys == [bytes.fromhex(KEY_HEX), None]
    # Login sub-slice L4: the flow also gets the blocklist, and none without the file.
    assert blocklists == [BLOCKLIST, frozenset()]


def start_and_stop(app: FastAPI) -> None:
    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run_lifespan())


def test_a_start_with_a_database_and_no_key_file_logs_a_warning_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner item 4 of 2026-10-23: `APP_ENVIRONMENT` defaults to `development`, so an app started
    with a database and without the key file logs one warning at start-up; the log shows no
    key, no path and no database URL. With the key file, or without a database, there is no
    warning."""
    monkeypatch.delenv("APP_TOTP_KEY_FILE", raising=False)
    monkeypatch.setattr(app_module, "read_protected_totp_key", lambda _: bytes.fromhex(KEY_HEX))
    monkeypatch.setattr(app_module, "read_password_blocklist", lambda _: BLOCKLIST)
    for settings, warned in (
        (Settings(database_url=SecretStr(UNUSED_DATABASE)), True),
        (Settings(environment="test", database_url=SecretStr(UNUSED_DATABASE)), True),
        (
            Settings(
                environment="production",
                database_url=SecretStr(UNUSED_DATABASE),
                totp_key_file="/dev/fd/9",
                password_blocklist_file="/dev/fd/8",
            ),
            False,
        ),
        (Settings(environment="development", database_url=None), False),
    ):
        stream = io.StringIO()
        logger = create_application_logger(
            service="property-rental-backend",
            environment=settings.environment,
            level="INFO",
            stream=stream,
        )
        start_and_stop(create_app(settings, application_logger=logger))
        entries = [json.loads(line) for line in stream.getvalue().splitlines()]
        warnings = [entry for entry in entries if entry["severity"] == "WARNING"]
        expected = [{"event": "security.protected_key_file_missing"}] if warned else []
        assert [{"event": entry["event"]} for entry in warnings] == expected
        assert [entry["event"] for entry in entries if entry["severity"] == "INFO"] == [
            "application.started",
            "application.stopping",
        ]
        for secret in (UNUSED_DATABASE, KEY_HEX, "/dev/fd/9", "/dev/fd/8"):
            assert secret not in stream.getvalue()


def test_the_password_blocklist_is_read_once_and_needed_with_a_database_outside_development(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Login sub-slice L4 (owner answer (a) to Q-2026-10-21-155): the blocklist is a regular
    file of one password per line; a missing, empty, too large or non-regular file refuses
    without its content, and with a database every environment but `development` and `test`
    refuses to start without it (an empty setting counts as unset)."""
    blocklist = tmp_path / "blocklist.txt"
    blocklist.write_bytes(b"Password1234567\n\ncorrecthorsebatterystaple\r\n")
    assert read_password_blocklist(str(blocklist)) == {
        "password1234567",
        "correcthorsebatterystaple",
    }
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"\n\r\n\n")
    large = tmp_path / "large.txt"
    large.write_bytes(b"a" * (MAX_BLOCKLIST_BYTES + 1))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for path in (tmp_path / "missing.txt", empty, large, fifo, tmp_path):
        with pytest.raises(PasswordBlocklistUnavailable) as refused:
            read_password_blocklist(str(path))
        assert str(path) not in str(refused.value)
        assert "correcthorse" not in str(refused.value)

    monkeypatch.delenv("APP_PASSWORD_BLOCKLIST_FILE", raising=False)
    monkeypatch.setattr(app_module, "read_protected_totp_key", lambda _: bytes.fromhex(KEY_HEX))
    for blocklist_file in (None, ""):
        with pytest.raises(PasswordBlocklistUnavailable):
            create_app(
                Settings(
                    environment="production",
                    database_url=SecretStr(UNUSED_DATABASE),
                    totp_key_file="/dev/fd/9",
                    password_blocklist_file=blocklist_file,
                )
            )
    assert (
        create_app(
            Settings(
                environment="production",
                database_url=SecretStr(UNUSED_DATABASE),
                totp_key_file="/dev/fd/9",
                password_blocklist_file=str(blocklist),
            )
        )
        is not None
    )
    with pytest.raises(PasswordBlocklistUnavailable):
        create_app(Settings(password_blocklist_file=str(empty)))
    for environment in ("development", "test"):
        assert (
            create_app(Settings(environment=environment, database_url=SecretStr(UNUSED_DATABASE)))
            is not None
        )
    assert create_app(Settings(environment="production")) is not None
