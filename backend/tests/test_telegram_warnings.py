"""Warnings on Telegram (DL-217, owner card 11 Nov 2026): the messages as the tenant reads them."""

from __future__ import annotations

from property_rental.telegram_texts import render

RENT = {
    "unit": "Unit 512",
    "invoice": "INV-2026-0042",
    "due": "05/09/2026",
    "amount": "$800.00",
    "date": "11/11/2026",
    "letter_day": "30/09/2026",
}
LEASE = {
    "sequence": 1,
    "unit": "Unit 512",
    "date": "11/11/2026",
    "when": "09/11/2026",
    "text": "Loud music after 22:00.",
    "rule": "Clause 12: quiet hours",
}


def test_the_three_rent_notices_read_as_the_tenant_gets_them() -> None:
    # DL-237 (owner 13 Nov 2026): notices on day 10, 20 and 25, counted from the 1st.
    for code, number in (
        ("tenant.rent_notice_1", 1),
        ("tenant.rent_warning", 2),
        ("tenant.rent_notice_3", 3),
    ):
        english = render(code, "en", RENT)
        assert f"Rent not paid: notice {number} of 3" in english.split("\n")[0]
        assert english.split("\n")[1] == "Unit 512"
        assert "Invoice INV-2026-0042 was due on 05/09/2026." in english
        assert "Rent still to pay: $800.00" in english
        # The message is the notice: it must not name a paper letter nobody printed.
        assert "official copy" not in english
        assert english.endswith("Ask the office if you want this notice on paper.")
        khmer = render(code, "km", RENT)
        assert "INV-2026-0042" in khmer and "$800.00" in khmer and "05/09/2026" in khmer
    first = render("tenant.rent_notice_1", "en", RENT)
    assert "a termination letter may be issued from 30/09/2026" in first
    last = render("tenant.rent_notice_3", "en", RENT)
    assert last.startswith("🔴") and "This is the last notice." in last
    assert "before 30/09/2026" in last
    assert "30/09/2026" in render("tenant.rent_notice_3", "km", RENT)


def test_the_termination_letter_reads_as_the_tenant_gets_it() -> None:
    # A message queued before DL-237 has no letter day: the two older codes still read.
    old = {name: value for name, value in RENT.items() if name != "letter_day"}
    letter = render("tenant.rent_default", "en", old)
    assert letter.startswith("🔴 Termination letter\nUnit 512\n")
    assert "still not paid after three notices" in letter
    assert "termination letter under your Lease on 11/11/2026" in letter
    assert letter.endswith("The office's paper letter is the official copy.")
    assert "Rent not paid: notice 2 of 3" in render("tenant.rent_warning", "en", old)
    khmer = render("tenant.rent_default", "km", old)
    assert "INV-2026-0042" in khmer and "$800.00" in khmer and "11/11/2026" in khmer


def test_a_lease_warning_reads_with_the_words_staff_wrote() -> None:
    english = render("tenant.lease_warning", "en", LEASE)
    assert english.startswith("⚠️ Lease warning 1\nUnit 512\nDate: 11/11/2026\n")
    assert "What happened (09/11/2026): Loud music after 22:00." in english
    assert "Lease rule: Clause 12: quiet hours" in english
    khmer = render("tenant.lease_warning", "km", LEASE)
    assert "Loud music after 22:00." in khmer and "Clause 12: quiet hours" in khmer
