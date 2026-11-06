"""Open the items the Telegram relay sealed for the office (bots plan, "The relay", job 3).

The relay on Cloudflare seals every message and photo with the office's public key before it
stores it, so only the office computer, which holds the private key, can open what waits there.

A sealed item is bytes:

    b"CS1" | key length (2 bytes, big-endian) | the AES key wrapped with RSA-OAEP (SHA-256)
           | nonce (12 bytes) | AES-256-GCM ciphertext with its 16-byte tag

The associated data of the AES-GCM step is the item's own relay id, so a sealed item cannot be
moved under another id. The relay (relay/src/seal.ts) writes this format; the test vector in
tests/fixtures/telegram_relay/ is made by the relay code and opened here.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC: Final = b"CS1"
NONCE_BYTES: Final = 12
MAX_SEALED_BYTES: Final = 30 * 1024 * 1024


class SealError(ValueError):
    """The sealed item cannot be opened (wrong key, changed bytes, or not a sealed item)."""


def load_office_private_key(path: Path) -> rsa.RSAPrivateKey:
    """The office private key (PEM, PKCS#8, no password; the file is a protected secret)."""
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise SealError("the office key cannot be read") from error
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
        raise SealError("the office key must be an RSA key of 3072 bits or more")
    return key


def open_sealed(key: rsa.RSAPrivateKey, sealed: bytes, item_id: str) -> bytes:
    """The plain bytes of one sealed item; SealError when anything does not match."""
    if len(sealed) > MAX_SEALED_BYTES or len(sealed) < len(MAGIC) + 2 + NONCE_BYTES + 16:
        raise SealError("not a sealed item")
    if not sealed.startswith(MAGIC):
        raise SealError("not a sealed item")
    (wrapped_length,) = struct.unpack_from(">H", sealed, len(MAGIC))
    start = len(MAGIC) + 2
    wrapped = sealed[start : start + wrapped_length]
    nonce = sealed[start + wrapped_length : start + wrapped_length + NONCE_BYTES]
    body = sealed[start + wrapped_length + NONCE_BYTES :]
    if len(wrapped) != wrapped_length or len(nonce) != NONCE_BYTES or len(body) < 16:
        raise SealError("not a sealed item")
    try:
        secret = key.decrypt(
            wrapped,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except ValueError as error:
        raise SealError("the item was not sealed for this office") from error
    if len(secret) != 32:
        raise SealError("not a sealed item")
    try:
        return AESGCM(secret).decrypt(nonce, body, item_id.encode("utf-8"))
    except InvalidTag as error:
        raise SealError("the sealed item was changed") from error


def seal_for_tests(public_key: rsa.RSAPublicKey, plain: bytes, item_id: str) -> bytes:
    """The same format the relay writes; used by the tests and the local fake relay only."""
    import os

    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(NONCE_BYTES)
    wrapped = public_key.encrypt(
        secret,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    body = AESGCM(secret).encrypt(nonce, plain, item_id.encode("utf-8"))
    return MAGIC + struct.pack(">H", len(wrapped)) + wrapped + nonce + body
