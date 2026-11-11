"""Notices on Telegram (DL-216, owner 11 Nov 2026): the notice as the tenant reads it."""

from __future__ import annotations

from property_rental.telegram_texts import render


def test_a_notice_reads_with_the_office_heading_and_keeps_long_words() -> None:
    words = "The water is off tomorrow from 09:00 to 11:00. " * 30
    english = render("tenant.notice", "en", {"notice": words.strip()})
    assert english.startswith("📢 Notice from the office\n\nThe water is off")
    assert english.endswith("to 11:00.") and len(english) > 1000
    khmer = render("tenant.notice", "km", {"notice": "គ្មានទឹក"})
    assert khmer == "📢 សេចក្តីជូនដំណឹងពីការិយាល័យ\n\nគ្មានទឹក"
