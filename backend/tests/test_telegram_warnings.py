"""Warnings on Telegram (DL-217, owner card 11 Nov 2026): the messages as the tenant reads them."""

from __future__ import annotations

from property_rental.telegram_texts import render

RENT = {
    "unit": "Unit 512",
    "invoice": "INV-2026-0042",
    "due": "05/09/2026",
    "amount": "$800.00",
    "date": "11/11/2026",
}
LEASE = {
    "sequence": 1,
    "unit": "Unit 512",
    "date": "11/11/2026",
    "when": "09/11/2026",
    "text": "Loud music after 22:00.",
    "rule": "Clause 12: quiet hours",
}


def test_the_late_rent_letters_read_as_the_tenant_gets_them() -> None:
    twenty = render("tenant.rent_warning", "en", RENT)
    assert twenty.startswith("⚠️ Rent not paid: 20 days\nUnit 512\n")
    assert "Invoice INV-2026-0042 was due on 05/09/2026." in twenty
    assert "Rent still to pay: $800.00" in twenty
    assert twenty.endswith("The office's paper letter of 11/11/2026 is the official copy.")
    thirty = render("tenant.rent_default", "en", RENT)
    assert thirty.startswith("🔴 Rent not paid: 30 days") and "serious nonpayment" in thirty
    for code in ("tenant.rent_warning", "tenant.rent_default"):
        khmer = render(code, "km", RENT)
        assert "INV-2026-0042" in khmer and "$800.00" in khmer and "11/11/2026" in khmer


def test_a_lease_warning_reads_with_the_words_staff_wrote() -> None:
    english = render("tenant.lease_warning", "en", LEASE)
    assert english.startswith("⚠️ Lease warning 1\nUnit 512\nDate: 11/11/2026\n")
    assert "What happened (09/11/2026): Loud music after 22:00." in english
    assert "Lease rule: Clause 12: quiet hours" in english
    khmer = render("tenant.lease_warning", "km", LEASE)
    assert "Loud music after 22:00." in khmer and "Clause 12: quiet hours" in khmer
