"""The QR picture of a new sign-in code's provisioning link (login sub-slice L6).

The picture is built on the server with the approved `qrcode` library, so the secret never
leaves the one-time enrollment answer for another service or library in the browser. Only the
module matrix comes from the library; the SVG text is written here: dark squares on a white
background with the standard four-module quiet zone, no script, no link and no XML header.
"""

from typing import Final

import qrcode  # type: ignore[import-untyped]
from qrcode.constants import ERROR_CORRECT_M  # type: ignore[import-untyped]

QR_QUIET_ZONE_MODULES: Final = 4


def provisioning_qr_svg(provisioning_uri: str) -> str:
    """An SVG QR code of the `otpauth://totp/` link, scaled by the viewBox."""
    if not provisioning_uri.startswith("otpauth://totp/"):
        raise ValueError("invalid TOTP provisioning material")
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=QR_QUIET_ZONE_MODULES)
    code.add_data(provisioning_uri)
    code.make(fit=True)
    matrix: list[list[bool]] = code.get_matrix()
    size = len(matrix)
    squares = "".join(
        f"M{column},{row}h1v1h-1z"
        for row, cells in enumerate(matrix)
        for column, dark in enumerate(cells)
        if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges"><rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path fill="#000" d="{squares}"/></svg>'
    )
