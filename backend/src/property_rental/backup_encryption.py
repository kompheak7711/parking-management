"""Encrypted backup files (V1-059, DL-071 answers 1 to 5; DEPLOY-041).

A backup file is a PostgreSQL dump sealed with AES-256-GCM from the well-known `cryptography`
library (no home-made cryptography). The file is the 11-byte header, the 12-byte random nonce,
the ciphertext and the 16-byte GCM tag; the header and the nonce are the associated data, so a
changed header, nonce, body or tag fails the check. Decryption writes to a private temporary
file and keeps it only after the tag check passes, so unchecked plaintext is never left behind.
The key is 32 random bytes, kept base64-encoded in a protected file that only its owner may
read; the key and its file content never appear in an error message.
"""

from __future__ import annotations

import base64
import binascii
import os
import stat
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BACKUP_FILE_HEADER: Final = b"PRMBACKUP1\n"
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
KEY_BYTES: Final = 32
CHUNK_BYTES: Final = 1024 * 1024


class BackupKeyError(ValueError):
    """The backup key file is missing, readable by others or not a 32-byte key."""


class BackupIntegrityError(ValueError):
    """A backup file is not a complete, unchanged backup sealed with this key."""


def load_backup_key(path: Path) -> bytes:
    """Read the base64 key from a file only its owner may read; never show its content."""
    try:
        file_status = path.stat()
    except OSError as error:
        raise BackupKeyError("the backup key file is unavailable") from error
    if not stat.S_ISREG(file_status.st_mode):
        raise BackupKeyError("the backup key file is not a regular file")
    if os.name == "posix" and file_status.st_mode & 0o077:
        raise BackupKeyError("the backup key file must be readable by its owner only")
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise BackupKeyError("the backup key file cannot be read as text") from error
    try:
        key = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise BackupKeyError("the backup key file does not hold a base64 key") from error
    if len(key) != KEY_BYTES:
        raise BackupKeyError("the backup key must be 32 bytes")
    return key


def _private_temporary_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.partial")


def _open_private(path: Path) -> int:
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def encrypt_file(source: Path, target: Path, key: bytes) -> None:
    """Seal `source` into `target`; `target` appears only when it is complete."""
    if len(key) != KEY_BYTES:
        raise BackupKeyError("the backup key must be 32 bytes")
    nonce = os.urandom(NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(BACKUP_FILE_HEADER + nonce)
    partial = _private_temporary_path(target)
    try:
        with source.open("rb") as plain, os.fdopen(_open_private(partial), "wb") as sealed:
            sealed.write(BACKUP_FILE_HEADER)
            sealed.write(nonce)
            while chunk := plain.read(CHUNK_BYTES):
                sealed.write(encryptor.update(chunk))
            sealed.write(encryptor.finalize())
            sealed.write(encryptor.tag)
            sealed.flush()
            os.fsync(sealed.fileno())
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def decrypt_file(source: Path, target: Path, key: bytes) -> None:
    """Open `source` into `target`; `target` appears only when the GCM tag check passes."""
    if len(key) != KEY_BYTES:
        raise BackupKeyError("the backup key must be 32 bytes")
    header_bytes = len(BACKUP_FILE_HEADER) + NONCE_BYTES
    size = source.stat().st_size
    if size < header_bytes + TAG_BYTES:
        raise BackupIntegrityError("the backup file is truncated")
    partial = _private_temporary_path(target)
    try:
        with source.open("rb") as sealed:
            if sealed.read(len(BACKUP_FILE_HEADER)) != BACKUP_FILE_HEADER:
                raise BackupIntegrityError("the file is not a backup of this system")
            nonce = sealed.read(NONCE_BYTES)
            sealed.seek(size - TAG_BYTES)
            tag = sealed.read(TAG_BYTES)
            sealed.seek(header_bytes)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(BACKUP_FILE_HEADER + nonce)
            remaining = size - header_bytes - TAG_BYTES
            with os.fdopen(_open_private(partial), "wb") as plain:
                while remaining > 0:
                    chunk = sealed.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise BackupIntegrityError("the backup file is truncated")
                    remaining -= len(chunk)
                    plain.write(decryptor.update(chunk))
                try:
                    plain.write(decryptor.finalize())
                except InvalidTag as error:
                    raise BackupIntegrityError(
                        "the backup file was changed or sealed with another key"
                    ) from error
                plain.flush()
                os.fsync(plain.fileno())
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
