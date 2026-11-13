"""ABA's riel rate for the app (DL-181; owner card 12 Nov 2026: "ABA PayWay rate API").

The System Exchange Rate rule stays as it is (BR-MONEY-005 to 008): ABA's USD Sell rate times
1.005, rounded up to a whole riel, kept with each riel Payment when it is confirmed. This module
only answers "what is ABA's Sell rate now": it asks ABA PayWay at most once an hour and keeps the
answer in memory. When ABA cannot be asked, or gives no usable USD rate, the answer is "not
available" and staff may type ABA's rate by hand, as before (BR-MONEY-008).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from property_rental import payway
from property_rental.configuration_api import ExchangeRateQuote, ExchangeRateSourceUnavailable

KEEP_FOR: Final = timedelta(hours=1)  # owner card: read every hour
WAIT_AFTER_FAILURE: Final = timedelta(minutes=5)  # do not ask ABA again at every page view

Clock = Callable[[], datetime]
ReadRate = Callable[[], payway.PayWayRate]


class PayWayExchangeRateProvider:
    """``ExchangeRateProvider`` backed by ABA PayWay's Exchange rate API."""

    def __init__(self, read_rate: ReadRate, *, clock: Clock = lambda: datetime.now(UTC)) -> None:
        self._read_rate = read_rate
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: payway.PayWayRate | None = None
        self._failed_at: datetime | None = None
        self.last_error: str | None = None

    def __repr__(self) -> str:
        return "PayWayExchangeRateProvider()"

    def current_sell_rate(self) -> ExchangeRateQuote:
        now = self._clock()
        with self._lock:
            kept = self._kept
            if kept is None or now - kept.read_at >= KEEP_FOR:
                if self._failed_at is not None and now - self._failed_at < WAIT_AFTER_FAILURE:
                    raise ExchangeRateSourceUnavailable
                try:
                    kept = self._read_rate()
                except payway.PayWayError as error:
                    self._kept, self._failed_at, self.last_error = None, now, error.code
                    raise ExchangeRateSourceUnavailable from error
                except Exception as error:
                    self._kept, self._failed_at = None, now
                    self.last_error = "payway_failed"
                    raise ExchangeRateSourceUnavailable from error
                self._kept, self._failed_at, self.last_error = kept, None, None
        read_at = kept.read_at.astimezone(UTC)
        return ExchangeRateQuote(
            reference_rate_khr_per_usd=kept.sell_khr_per_usd,
            source_reference=(
                f"ABA PayWay exchange rate, USD Sell {kept.sell_khr_per_usd} KHR, "
                f"read {read_at:%Y-%m-%d %H:%M} UTC"
            ),
            applicable_at=read_at,
        )


def provider_from_files(
    *, host: str | None, merchant_id_file: str | None, api_key_file: str | None
) -> PayWayExchangeRateProvider | None:
    """The provider when the PayWay key files are set and readable, else None (not set up)."""
    if not host or not merchant_id_file or not api_key_file:
        return None
    config = payway.load_config(
        host=host,
        merchant_id_file=Path(merchant_id_file),
        api_key_file=Path(api_key_file),
        callback_url=None,
    )
    if config is None:
        return None
    return PayWayExchangeRateProvider(lambda: payway.exchange_rate(config))
