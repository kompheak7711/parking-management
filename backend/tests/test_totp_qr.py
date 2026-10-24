"""The QR picture of a new sign-in code's provisioning link (login sub-slice L6)."""

import re

import pytest
import qrcode  # type: ignore[import-untyped]
from qrcode.constants import ERROR_CORRECT_M  # type: ignore[import-untyped]

from property_rental.totp_qr import QR_QUIET_ZONE_MODULES, provisioning_qr_svg

LINK = (
    "otpauth://totp/CHETANA%20Residence:sokha?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    "&issuer=CHETANA%20Residence&algorithm=SHA1&digits=6&period=30"
)


def dark_squares(svg: str) -> set[tuple[int, int]]:
    path = re.search(r'<path fill="#000" d="([^"]*)"/>', svg)
    assert path is not None
    return {
        (int(column), int(row))
        for column, row in re.findall(r"M(\d+),(\d+)h1v1h-1z", path.group(1))
    }


def test_the_picture_draws_exactly_the_dark_modules_of_the_link() -> None:
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=QR_QUIET_ZONE_MODULES)
    code.add_data(LINK)
    code.make(fit=True)
    matrix = code.get_matrix()
    expected = {
        (column, row)
        for row, cells in enumerate(matrix)
        for column, dark in enumerate(cells)
        if dark
    }

    svg = provisioning_qr_svg(LINK)

    assert dark_squares(svg) == expected
    size = len(matrix)
    assert f'viewBox="0 0 {size} {size}"' in svg
    assert f'<rect width="{size}" height="{size}" fill="#fff"/>' in svg
    # The quiet zone stays white on every side.
    assert all(
        QR_QUIET_ZONE_MODULES <= column < size - QR_QUIET_ZONE_MODULES
        and QR_QUIET_ZONE_MODULES <= row < size - QR_QUIET_ZONE_MODULES
        for column, row in expected
    )


def test_the_picture_is_plain_svg_without_a_script_a_link_or_the_secret_as_text() -> None:
    svg = provisioning_qr_svg(LINK)

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" ')
    assert svg.endswith("</svg>")
    assert "<script" not in svg
    assert "href" not in svg
    assert "<?xml" not in svg
    assert "JBSWY3DPEHPK3PXP" not in svg
    assert provisioning_qr_svg(LINK) == svg


@pytest.mark.parametrize(
    "link",
    ["", "https://example.test/", "otpauth://hotp/CHETANA:sokha?secret=JBSWY3DP"],
)
def test_the_picture_is_refused_for_anything_but_a_totp_link(link: str) -> None:
    with pytest.raises(ValueError, match="invalid TOTP provisioning material"):
        provisioning_qr_svg(link)
