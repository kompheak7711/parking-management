"""Protected runtime key material for the API (login sub-slice L3c-1, DL-081, Q-155, Q-175).

The TOTP protection key comes only from a protected file whose path is the setting
`APP_TOTP_KEY_FILE` (never an ordinary environment value, SEC-073); the checks are the bootstrap's
own (`read_root_controlled_totp_key`: a root-owned regular file without group or other access).
On the Mac mini the start-up wrapper opens the file and passes it as an inherited descriptor, so
the path may be `/dev/fd/<n>`. Each other use of the key gets its own key derived with HKDF, so
the protection key itself only protects sign-in code secrets. No key is ever printed.
"""

import os
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from property_rental.bootstrap_cli import read_root_controlled_totp_key

DERIVED_KEY_BYTES: Final = 32
SIGN_IN_TRY_KEY_INFO: Final = b"property-rental:sign-in-try-digest:v1"
TOTP_KEY_IDENTIFIER_INFO: Final = b"property-rental:totp-key-identifier:v1"
TOTP_KEY_IDENTIFIER_BYTES: Final = 16


class ProtectedKeyUnavailable(RuntimeError):
    """The protected key file is missing, unreadable or not protected; no detail is given."""


def read_protected_totp_key(path: str) -> bytes:
    """Read the 32-byte TOTP protection key from a protected file, or refuse."""
    try:
        # Not blocking on a FIFO and not taking a terminal (review round 1); the checks below
        # refuse anything but a protected regular file.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except (OSError, ValueError):
        raise ProtectedKeyUnavailable("the protected key file cannot be opened") from None
    try:
        # A `/dev/fd/<n>` path shares the inherited descriptor's offset on macOS; read from the
        # start every time.
        os.lseek(descriptor, 0, os.SEEK_SET)
        return read_root_controlled_totp_key(descriptor)
    except (OSError, ValueError):
        raise ProtectedKeyUnavailable("the protected key file is not usable") from None
    finally:
        os.close(descriptor)


def derive_sign_in_try_key(protection_key: bytes) -> bytes:
    """The key of the wrong-try digests (owner answer (a) to Q-2026-10-23-175), derived with
    HKDF-SHA256 so that it is never the protection key itself."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=DERIVED_KEY_BYTES,
        salt=None,
        info=SIGN_IN_TRY_KEY_INFO,
    ).derive(protection_key)


def derive_totp_key_identifier(protection_key: bytes) -> str:
    """The key identifier stored with a sign-in code that the API sets up (login sub-slice
    L3c-2b, decided under the owner's 2026-10-22 rule): a name of the protection key derived
    with HKDF-SHA256, so another key file gets another name and the key itself is never stored
    or shown."""
    name = HKDF(
        algorithm=hashes.SHA256(),
        length=TOTP_KEY_IDENTIFIER_BYTES,
        salt=None,
        info=TOTP_KEY_IDENTIFIER_INFO,
    ).derive(protection_key)
    return f"runtime-{name.hex()}"
