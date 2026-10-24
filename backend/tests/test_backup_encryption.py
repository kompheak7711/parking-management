"""V1-059 encrypted backup files (DL-071 answers 1 to 5; DEPLOY-041, DEPLOY-042)."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from property_rental.backup_encryption import (
    BACKUP_FILE_HEADER,
    BackupIntegrityError,
    BackupKeyError,
    decrypt_file,
    encrypt_file,
    load_backup_key,
)

KEY = bytes(range(32))


def _plain(tmp_path: Path, size: int = 3 * 1024 * 1024 + 17) -> Path:
    path = tmp_path / "dump.pgdump"
    path.write_bytes(os.urandom(size))
    return path


def test_a_sealed_backup_opens_to_the_same_bytes(tmp_path: Path) -> None:
    plain = _plain(tmp_path)
    sealed = tmp_path / "dump.enc"
    opened = tmp_path / "opened"
    encrypt_file(plain, sealed, KEY)
    assert sealed.read_bytes().startswith(BACKUP_FILE_HEADER)
    assert plain.read_bytes()[:1024] not in sealed.read_bytes()
    decrypt_file(sealed, opened, KEY)
    assert opened.read_bytes() == plain.read_bytes()
    if os.name == "posix":
        assert sealed.stat().st_mode & 0o077 == 0
        assert opened.stat().st_mode & 0o077 == 0


def test_two_seals_of_the_same_dump_differ(tmp_path: Path) -> None:
    plain = _plain(tmp_path, 1000)
    encrypt_file(plain, tmp_path / "a", KEY)
    encrypt_file(plain, tmp_path / "b", KEY)
    assert (tmp_path / "a").read_bytes() != (tmp_path / "b").read_bytes()


@pytest.mark.parametrize("offset", [0, 12, 30, -1, -20])
def test_any_changed_byte_fails_and_leaves_no_opened_file(tmp_path: Path, offset: int) -> None:
    plain = _plain(tmp_path, 5000)
    sealed = tmp_path / "dump.enc"
    encrypt_file(plain, sealed, KEY)
    data = bytearray(sealed.read_bytes())
    data[offset] ^= 0x01
    sealed.write_bytes(bytes(data))
    opened = tmp_path / "opened"
    with pytest.raises(BackupIntegrityError):
        decrypt_file(sealed, opened, KEY)
    assert not opened.exists()
    assert not (tmp_path / ".opened.partial").exists()


def test_another_key_and_a_truncated_file_fail(tmp_path: Path) -> None:
    plain = _plain(tmp_path, 5000)
    sealed = tmp_path / "dump.enc"
    encrypt_file(plain, sealed, KEY)
    with pytest.raises(BackupIntegrityError):
        decrypt_file(sealed, tmp_path / "opened", bytes(32))
    sealed.write_bytes(sealed.read_bytes()[:-100])
    with pytest.raises(BackupIntegrityError):
        decrypt_file(sealed, tmp_path / "opened", KEY)
    sealed.write_bytes(BACKUP_FILE_HEADER)
    with pytest.raises(BackupIntegrityError, match="truncated"):
        decrypt_file(sealed, tmp_path / "opened", KEY)


def test_the_key_file_must_be_private_and_hold_a_32_byte_base64_key(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text(base64.b64encode(KEY).decode() + "\n", encoding="ascii")
    key_file.chmod(0o600)
    assert load_backup_key(key_file) == KEY
    if os.name == "posix":
        key_file.chmod(0o640)
        with pytest.raises(BackupKeyError, match="owner only"):
            load_backup_key(key_file)
        key_file.chmod(0o600)
    for text in ("not base64 !", base64.b64encode(bytes(16)).decode(), ""):
        key_file.write_text(text, encoding="ascii")
        with pytest.raises(BackupKeyError) as raised:
            load_backup_key(key_file)
        assert text not in str(raised.value) or not text
    with pytest.raises(BackupKeyError, match="unavailable"):
        load_backup_key(tmp_path / "missing")
