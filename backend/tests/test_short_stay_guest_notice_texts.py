"""Short-stay guest notices on Telegram (DL-238, owner 14 Nov 2026): the messages as the guest
reads them."""

from __future__ import annotations

from property_rental.telegram_texts import TEXTS, render

STAY = {
    "unit": "U508",
    "date": "15/11/2026",
    "time": "12:00",
    "until": "18:00",
    "fee": "$5.00",
}


def test_the_check_out_reminder_names_the_time_and_the_late_check_out() -> None:
    paid = render("tenant.ss_check_out", "en", STAY)
    assert paid.startswith("🧳 Check-out reminder\nU508\n")
    assert "Your check-out is tomorrow, 15/11/2026, at 12:00." in paid
    assert "Late check-out until 18:00 costs $5.00." in paid
    free = render("tenant.ss_check_out_free", "en", STAY)
    assert "Late check-out until 18:00 is free for your stay." in free and "$5.00" not in free
    late = render("tenant.ss_check_out_late", "en", STAY)
    assert "at 18:00 (late check-out)" in late and "costs" not in late
    for code in ("tenant.ss_check_out", "tenant.ss_check_out_free", "tenant.ss_check_out_late"):
        khmer = render(code, "km", STAY)
        assert "U508" in khmer and "15/11/2026" in khmer


def test_the_late_check_out_notice_adds_no_money() -> None:
    late = render("tenant.ss_late", "en", {"unit": "U508", "time": "12:00"})
    assert late == (
        "⏰ Check-out time has passed\nU508\nCheck-out time today was 12:00.\n"
        "Please check out now, or come to the front desk if you need more time."
    )
    assert "$" not in render("tenant.ss_late", "km", {"unit": "U508", "time": "12:00"})


def test_the_two_house_rule_warnings_and_the_unpaid_charge() -> None:
    fields = {"unit": "U508", "date": "14/11/2026", "text": "Loud music after 22:00."}
    first = render("tenant.ss_warning_1", "en", fields)
    assert first.startswith("⚠️ House-rule warning 1\nU508\nDate: 14/11/2026")
    assert "What happened: Loud music after 22:00." in first
    assert first.endswith("A second warning is the final warning.")
    final = render("tenant.ss_warning_2", "en", fields)
    assert final.startswith("🔴 Final house-rule warning")
    # The owner's rule for an early end: unused nights stay paid.
    assert "the manager may end your stay early. Nights not used are not paid back." in final
    charge = {"unit": "U508", "invoice": "INV-1", "amount": "$5.00"}
    unpaid = render("tenant.ss_unpaid", "en", charge)
    assert "Invoice INV-1: $5.00 still to pay." in unpaid
    for code in ("tenant.ss_warning_1", "tenant.ss_warning_2"):
        assert "Loud music after 22:00." in render(code, "km", fields)
    # Guests read both languages; every short-stay text has both.
    assert all({"km", "en"} <= set(TEXTS[code]) for code in TEXTS if code.startswith("tenant.ss_"))
