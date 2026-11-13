"""ABA PayWay, the calls the Invoice QR needs (ABA QR plan, owner 11 Nov 2026).

- ``generate_qr``: a KHQR for one Invoice, with the USD amount and our transaction id inside.
- ``check_transaction``: what ABA says about a transaction (paid, waiting, cancelled ...).
- ``close_transaction``: cancel an old QR when a new one replaces it (a part payment).
- ``exchange_rate``: ABA's own USD Sell rate in riel (DL-181), as on ababank.com.

PayWay's documents: developer.payway.com.kh (QR API, Check transaction, Close transaction).
Every call is signed with the merchant's API key: base64 of HMAC-SHA512 over the request
values in PayWay's fixed order. The API key is read from a secret file and never logged; only
fixed codes leave this module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

TIMEOUT_SECONDS: Final = 15
SANDBOX_HOST: Final = "checkout-sandbox.payway.com.kh"
LIVE_HOST: Final = "checkout.payway.com.kh"
QR_PATH: Final = "/api/payment-gateway/v1/payments/generate-qr"
CHECK_PATH: Final = "/api/payment-gateway/v1/payments/check-transaction-2"
# ABA's Check transaction only knows transactions made in the last 7 days; older ones are read
# with Get a transaction details (same fields, at most 10 calls a minute).
DETAIL_PATH: Final = "/api/payment-gateway/v1/payments/transaction-detail"
CLOSE_PATH: Final = "/api/payment-gateway/v1/payments/close-transaction"
RATE_PATH: Final = "/api/payment-gateway/v1/exchange-rate"
# PayWay: a QR lives 3 minutes to 30 days, given in minutes.
MIN_LIFETIME_MINUTES: Final = 3
MAX_LIFETIME_MINUTES: Final = 30 * 24 * 60
TRAN_ID: Final = re.compile(r"[A-Za-z0-9-]{1,20}")
QR_TEMPLATE: Final = "template3_color"

# A poster sends JSON to an address and gives back (HTTP status, answer). Tests replace it.
PostJson = Callable[[str, dict[str, Any]], tuple[int, bytes]]


class PayWayError(Exception):
    """A PayWay call failed. ``code`` is a fixed word, safe for logs and the health page."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PayWayConfig:
    host: str
    merchant_id: str
    api_key: str
    callback_url: str | None = None


@dataclass(frozen=True)
class PayWayQr:
    tran_id: str
    qr_string: str
    amount_cents: int
    currency: str


@dataclass(frozen=True)
class PayWayTransaction:
    """ABA's answer about one transaction. ``status`` is PayWay's word (APPROVED, PENDING ...);
    ``amount_cents`` and ``currency`` are what was paid, kept as ABA sent them."""

    tran_id: str
    status: str
    status_code: int | None
    amount_cents: int | None
    currency: str | None
    apv: str | None
    paid_at: str | None

    @property
    def paid(self) -> bool:
        return self.status == "APPROVED" and self.status_code == 0


def _post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
    request = urllib.request.Request(
        address,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Python's own name ("Python-urllib/3.x") is refused by some bank firewalls.
            "User-Agent": "CHETANA-Residence/1.0",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
        ) as answer:
            return int(answer.status), answer.read(2_000_000)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def load_config(
    *, host: str, merchant_id_file: Path, api_key_file: Path, callback_url: str | None
) -> PayWayConfig | None:
    """PayWay as set up on the office computer, or None when it is not set up yet."""
    if host not in (SANDBOX_HOST, LIVE_HOST):
        raise PayWayError("payway_host_unknown")
    try:
        merchant_id = merchant_id_file.read_text(encoding="utf-8").strip()
        api_key = api_key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,30}", merchant_id) or len(api_key) < 8:
        return None
    if callback_url is not None and not callback_url.startswith("https://"):
        raise PayWayError("payway_callback_not_https")
    return PayWayConfig(host, merchant_id, api_key, callback_url)


def request_time(now: datetime | None = None) -> str:
    """PayWay's req_time: UTC, YYYYMMDDHHmmss."""
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d%H%M%S")


def sign(api_key: str, *values: str) -> str:
    """base64(HMAC-SHA512(api_key, the values joined)), PayWay's hash."""
    digest = hmac.new(api_key.encode("utf-8"), "".join(values).encode("utf-8"), hashlib.sha512)
    return base64.b64encode(digest.digest()).decode("ascii")


def amount_text(cents: int) -> str:
    """Cents as PayWay's amount: "353.00"."""
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 1:
        raise PayWayError("payway_amount_invalid")
    return f"{cents // 100}.{cents % 100:02d}"


def cents_of(value: Any) -> int | None:
    """ABA's amount (0.1, "353.00") in cents, without floating-point rounding."""
    if isinstance(value, bool) or value is None:
        return None
    text = format(value, "f") if isinstance(value, float) else str(value).strip()
    match = re.fullmatch(r"(\d{1,9})(?:\.(\d{1,6}))?", text)
    if match is None:
        return None
    part = (match.group(2) or "").ljust(2, "0")
    if part[2:].strip("0"):
        return None  # more than cents: not a USD amount we can take as it is
    return int(match.group(1)) * 100 + int(part[:2])


def _status(answer: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        document = json.loads(answer)
    except ValueError as error:
        raise PayWayError("payway_bad_answer") from error
    if not isinstance(document, dict):
        raise PayWayError("payway_bad_answer")
    status = document.get("status")
    if not isinstance(status, dict):
        raise PayWayError("payway_bad_answer")
    return document, status


def _call(
    config: PayWayConfig, path: str, body: dict[str, Any], post_json: PostJson
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        http_status, answer = post_json(f"https://{config.host}{path}", body)
    except Exception as error:
        raise PayWayError("payway_unreachable") from error
    if http_status == 429:
        raise PayWayError("payway_too_many")
    if http_status != 200:
        raise PayWayError(
            f"payway_http_{http_status}" if 100 <= http_status <= 599 else "payway_failed"
        )
    return _status(answer)


def generate_qr(
    config: PayWayConfig,
    *,
    tran_id: str,
    amount_cents: int,
    lifetime_minutes: int,
    now: datetime | None = None,
    post_json: PostJson = _post_json,
) -> PayWayQr:
    """Ask PayWay for the KHQR of one transaction in USD."""
    if not TRAN_ID.fullmatch(tran_id):
        raise PayWayError("payway_tran_id_invalid")
    lifetime = max(MIN_LIFETIME_MINUTES, min(MAX_LIFETIME_MINUTES, int(lifetime_minutes)))
    callback = (
        base64.b64encode(config.callback_url.encode("utf-8")).decode("ascii")
        if config.callback_url
        else ""
    )
    fields = {
        "req_time": request_time(now),
        "merchant_id": config.merchant_id,
        "tran_id": tran_id,
        "amount": amount_text(amount_cents),
        "payment_option": "abapay_khqr",
        "callback_url": callback,
        "currency": "USD",
        "lifetime": str(lifetime),
        "qr_image_template": QR_TEMPLATE,
    }
    # PayWay's order: req_time, merchant_id, tran_id, amount, items, first_name, last_name,
    # email, phone, purchase_type, payment_option, callback_url, return_deeplink, currency,
    # custom_fields, return_params, payout, lifetime, qr_image_template (empty ones add nothing).
    fields["hash"] = sign(
        config.api_key,
        fields["req_time"],
        fields["merchant_id"],
        fields["tran_id"],
        fields["amount"],
        fields["payment_option"],
        fields["callback_url"],
        fields["currency"],
        fields["lifetime"],
        fields["qr_image_template"],
    )
    body: dict[str, Any] = {key: value for key, value in fields.items() if value != ""}
    body["lifetime"] = lifetime
    document, status = _call(config, QR_PATH, body, post_json)
    if str(status.get("code")) not in ("0", "00"):
        raise PayWayError(f"payway_refused_{_safe_code(status.get('code'))}")
    qr_string = document.get("qrString")
    if (
        not isinstance(qr_string, str)
        or not qr_string.startswith("000201")
        or len(qr_string) > 1000
    ):
        raise PayWayError("payway_bad_answer")
    currency = document.get("currency", "USD")
    paid_amount = cents_of(document.get("amount", amount_text(amount_cents)))
    if currency != "USD" or paid_amount != amount_cents:
        raise PayWayError("payway_qr_amount_differs")
    return PayWayQr(tran_id, qr_string, amount_cents, "USD")


def check_transaction(
    config: PayWayConfig,
    tran_id: str,
    *,
    now: datetime | None = None,
    post_json: PostJson = _post_json,
    older: bool = False,
) -> PayWayTransaction:
    """What ABA says about one transaction: Check transaction for one made in the last 7 days,
    Get a transaction details (``older``) for an older one."""
    if not TRAN_ID.fullmatch(tran_id):
        raise PayWayError("payway_tran_id_invalid")
    req_time = request_time(now)
    body = {
        "req_time": req_time,
        "merchant_id": config.merchant_id,
        "tran_id": tran_id,
        "hash": sign(config.api_key, req_time, config.merchant_id, tran_id),
    }
    document, status = _call(config, DETAIL_PATH if older else CHECK_PATH, body, post_json)
    code = str(status.get("code"))
    if code == "6":
        return PayWayTransaction(tran_id, "NOT_FOUND", None, None, None, None, None)
    if code != "00":
        raise PayWayError(f"payway_refused_{_safe_code(code)}")
    if status.get("tran_id") not in (None, tran_id):
        raise PayWayError("payway_bad_answer")
    data = document.get("data")
    if not isinstance(data, dict):
        raise PayWayError("payway_bad_answer")
    word = data.get("payment_status")
    number = data.get("payment_status_code")
    currency = data.get("payment_currency")
    apv, paid_at = data.get("apv"), data.get("transaction_date")
    return PayWayTransaction(
        tran_id=tran_id,
        status=word if isinstance(word, str) and word.isupper() and len(word) <= 20 else "UNKNOWN",
        status_code=number if isinstance(number, int) and not isinstance(number, bool) else None,
        amount_cents=cents_of(data.get("payment_amount")),
        currency=currency if currency in ("USD", "KHR") else None,
        apv=apv if isinstance(apv, str) and 0 < len(apv) <= 40 else None,
        paid_at=paid_at if isinstance(paid_at, str) and len(paid_at) <= 40 else None,
    )


def close_transaction(
    config: PayWayConfig,
    tran_id: str,
    *,
    now: datetime | None = None,
    post_json: PostJson = _post_json,
) -> bool:
    """Cancel a QR that is replaced; True when ABA closed it or never had it."""
    if not TRAN_ID.fullmatch(tran_id):
        raise PayWayError("payway_tran_id_invalid")
    req_time = request_time(now)
    body = {
        "req_time": req_time,
        "merchant_id": config.merchant_id,
        "tran_id": tran_id,
        "hash": sign(config.api_key, req_time, config.merchant_id, tran_id),
    }
    _, status = _call(config, CLOSE_PATH, body, post_json)
    return str(status.get("code")) in ("00", "0", "5")


@dataclass(frozen=True)
class PayWayRate:
    """ABA's Sell rate: riel for one US dollar, exactly as ABA wrote it."""

    sell_khr_per_usd: Decimal
    read_at: datetime


def _rate(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = format(value, "f") if isinstance(value, float) else str(value).strip()
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,6})?", text):
        return None
    try:
        rate = Decimal(text)
    except InvalidOperation:
        return None
    # A US dollar has cost between 3,000 and 6,000 riel for decades; anything else is not it.
    return rate if Decimal(3000) <= rate <= Decimal(6000) else None


def exchange_rate(
    config: PayWayConfig,
    *,
    now: datetime | None = None,
    post_json: PostJson = _post_json,
) -> PayWayRate:
    """ABA's USD Sell rate in riel. Raises a fixed code when ABA gives no usable USD rate."""
    moment = now or datetime.now(UTC)
    req_time = request_time(moment)
    body = {
        "req_time": req_time,
        "merchant_id": config.merchant_id,
        "hash": sign(config.api_key, req_time, config.merchant_id),
    }
    document, status = _call(config, RATE_PATH, body, post_json)
    if str(status.get("code")) not in ("00", "0"):
        raise PayWayError(f"payway_refused_{_safe_code(status.get('code'))}")
    rates = document.get("exchange_rates")
    if not isinstance(rates, dict):
        raise PayWayError("payway_bad_answer")
    usd = rates.get("usd") or rates.get("USD")
    if not isinstance(usd, dict):
        raise PayWayError("payway_rate_no_usd")
    sell = _rate(usd.get("sell"))
    if sell is None:
        raise PayWayError("payway_rate_odd")
    return PayWayRate(sell, moment)


def _safe_code(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[0-9A-Za-z]{1,8}", text) else "unknown"
