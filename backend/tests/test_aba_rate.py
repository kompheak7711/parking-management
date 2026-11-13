"""ABA's riel rate from ABA PayWay (DL-181; owner card 12/11/2026 "ABA PayWay rate API")."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from property_rental import payway
from property_rental.aba_rate import PayWayExchangeRateProvider, provider_from_files
from property_rental.configuration_api import ExchangeRateSourceUnavailable
from test_aba_invoice_qr import CONFIG, NOW, expected_hash


def answer(rates: dict[str, Any], code: str = "00") -> payway.PostJson:
    def post(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        assert address == f"https://{payway.SANDBOX_HOST}{payway.RATE_PATH}"
        assert body == {
            "req_time": "20261111030405",
            "merchant_id": "ec000001",
            "hash": expected_hash("20261111030405", "ec000001"),
        }
        return 200, json.dumps({"status": {"code": code}, "exchange_rates": rates}).encode()

    return post


def test_abas_usd_sell_rate_is_read_exactly() -> None:
    rates = {"usd": {"sell": "4025.50", "buy": "4010"}, "eur": {"sell": "4461.07", "buy": "4258"}}
    rate = payway.exchange_rate(CONFIG, now=NOW, post_json=answer(rates))
    assert rate == payway.PayWayRate(Decimal("4025.50"), NOW)


@pytest.mark.parametrize(
    ("rates", "code", "error"),
    [
        ({"eur": {"sell": "4461.07"}}, "00", "payway_rate_no_usd"),
        ({"usd": {"sell": "40.25"}}, "00", "payway_rate_odd"),
        ({"usd": {"sell": "4025,5"}}, "00", "payway_rate_odd"),
        ({"usd": {"sell": None}}, "00", "payway_rate_odd"),
        ({"usd": {"sell": "4025"}}, "1", "payway_refused_1"),
    ],
)
def test_no_usable_usd_rate_is_a_fixed_code(rates: dict[str, Any], code: str, error: str) -> None:
    with pytest.raises(payway.PayWayError, match=error):
        payway.exchange_rate(CONFIG, now=NOW, post_json=answer(rates, code))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def test_the_rate_is_asked_at_most_once_an_hour() -> None:
    clock, asked = Clock(), []

    def read() -> payway.PayWayRate:
        asked.append(clock.now)
        return payway.PayWayRate(Decimal("4025") + len(asked), clock.now)

    provider = PayWayExchangeRateProvider(read, clock=clock)
    first = provider.current_sell_rate()
    assert first.reference_rate_khr_per_usd == Decimal("4026")
    assert first.applicable_at == NOW
    assert first.source_reference == (
        "ABA PayWay exchange rate, USD Sell 4026 KHR, read 2026-11-11 03:04 UTC"
    )
    clock.now = NOW + timedelta(minutes=59)
    assert provider.current_sell_rate() == first
    clock.now = NOW + timedelta(hours=1)
    assert provider.current_sell_rate().reference_rate_khr_per_usd == Decimal("4027")
    assert len(asked) == 2


def test_without_abas_answer_the_rate_is_not_available_and_staff_type_it() -> None:
    clock, asked = Clock(), []

    def down() -> payway.PayWayRate:
        asked.append(clock.now)
        raise payway.PayWayError("payway_unreachable")

    provider = PayWayExchangeRateProvider(down, clock=clock)
    with pytest.raises(ExchangeRateSourceUnavailable):
        provider.current_sell_rate()
    assert provider.last_error == "payway_unreachable"
    # Not asked again at every page view: 5 minutes later.
    clock.now = NOW + timedelta(minutes=4)
    with pytest.raises(ExchangeRateSourceUnavailable):
        provider.current_sell_rate()
    assert len(asked) == 1
    clock.now = NOW + timedelta(minutes=5)
    with pytest.raises(ExchangeRateSourceUnavailable):
        provider.current_sell_rate()
    assert len(asked) == 2


def test_an_old_rate_is_never_used_after_the_hour() -> None:
    clock, answers = Clock(), [payway.PayWayRate(Decimal("4025"), NOW)]

    def read() -> payway.PayWayRate:
        if answers:
            return answers.pop()
        raise payway.PayWayError("payway_http_503")

    provider = PayWayExchangeRateProvider(read, clock=clock)
    provider.current_sell_rate()
    clock.now = NOW + timedelta(hours=2)
    with pytest.raises(ExchangeRateSourceUnavailable):
        provider.current_sell_rate()


def test_the_rate_is_off_until_the_payway_keys_are_saved(tmp_path: Path) -> None:
    assert provider_from_files(host=None, merchant_id_file=None, api_key_file=None) is None
    missing = provider_from_files(
        host=payway.SANDBOX_HOST,
        merchant_id_file=str(tmp_path / "aba_merchant_id"),
        api_key_file=str(tmp_path / "aba_api_key"),
    )
    assert missing is None
    (tmp_path / "aba_merchant_id").write_text("ec000001\n")
    (tmp_path / "aba_api_key").write_text("test-api-key-not-real\n")
    ready = provider_from_files(
        host=payway.SANDBOX_HOST,
        merchant_id_file=str(tmp_path / "aba_merchant_id"),
        api_key_file=str(tmp_path / "aba_api_key"),
    )
    assert isinstance(ready, PayWayExchangeRateProvider)
    with pytest.raises(payway.PayWayError, match="payway_host_unknown"):
        provider_from_files(
            host="evil.example.com",
            merchant_id_file=str(tmp_path / "aba_merchant_id"),
            api_key_file=str(tmp_path / "aba_api_key"),
        )
