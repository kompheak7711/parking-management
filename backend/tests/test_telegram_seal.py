"""Opening what the Telegram relay sealed (bots plan, "Testing": sealed items open only with the
office key)."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from property_rental.telegram_seal import (
    SealError,
    load_office_private_key,
    open_sealed,
    seal_for_tests,
)

RELAY = Path(__file__).resolve().parents[2] / "relay"


@pytest.fixture(scope="module")
def office_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def test_a_sealed_item_opens_with_the_office_key_under_its_own_id(
    office_key: rsa.RSAPrivateKey,
) -> None:
    sealed = seal_for_tests(office_key.public_key(), b'{"v":1}', "item-0001")
    assert open_sealed(office_key, sealed, "item-0001") == b'{"v":1}'
    with pytest.raises(SealError):
        open_sealed(office_key, sealed, "item-0002")
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    with pytest.raises(SealError):
        open_sealed(other, sealed, "item-0001")
    changed = bytearray(sealed)
    changed[-1] ^= 1
    with pytest.raises(SealError):
        open_sealed(office_key, bytes(changed), "item-0001")
    for broken in (b"", b"XX1" + sealed[3:], sealed[:20]):
        with pytest.raises(SealError):
            open_sealed(office_key, broken, "item-0001")


def test_the_office_key_file_must_be_a_strong_rsa_key(tmp_path: Path) -> None:
    weak = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "office.pem"
    path.write_bytes(
        weak.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(SealError):
        load_office_private_key(path)
    with pytest.raises(SealError):
        load_office_private_key(tmp_path / "missing.pem")


def _node_with_types() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    major, minor = (int(part) for part in version.stdout.strip().lstrip("v").split(".")[:2])
    return node if (major, minor) >= (22, 6) else None


def test_what_the_relay_code_seals_opens_here(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    node = _node_with_types()
    if node is None:
        pytest.skip("Node.js 22.6 or newer is needed to run the relay code")
    public = tmp_path / "office.pub.pem"
    public.write_bytes(
        office_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    result = subprocess.run(
        [
            node,
            "--experimental-strip-types",
            "--no-warnings",
            str(RELAY / "test" / "seal-cli.ts"),
            str(public),
            "item-7777",
            "សួស្តី hello",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    sealed = base64.b64decode(result.stdout)
    assert open_sealed(office_key, sealed, "item-7777").decode() == "សួស្តី hello"
