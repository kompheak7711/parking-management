"""Helpers of the PostgreSQL administration flow (login slice sub-slice L2b-2)."""

import sys
import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.access_admin_api import (
    AccessAdministrationNotFound,
    AccessAdministrationRejected,
    AccessAdministrationUnavailable,
)
from property_rental.access_admin_flow import (
    CORRELATION_NAMESPACE,
    KNOWN_REFUSALS,
    _page,
    _refusal,
    correlation_id,
    normalized_name,
    normalized_username,
)
from property_rental.local_authentication import normalize_local_username
from property_rental.visible_text import SPACE_SEPARATORS


def test_the_request_id_is_the_correlation_id_or_a_stable_uuid5_of_it() -> None:
    request_id = uuid4()
    assert correlation_id(str(request_id)) == request_id
    assert correlation_id("access-admin-test") == correlation_id("access-admin-test")
    assert correlation_id("access-admin-test").version == 5
    assert correlation_id("access-admin-test") != correlation_id("access-admin-other")
    assert CORRELATION_NAMESPACE == UUID("6d3c1f0e-5b7a-4c2e-9f41-0a8e2b7d5c13")


def test_names_are_nfc_with_single_spaces_and_usernames_lower_case() -> None:
    decomposed = "Cafe\u0301   Owner\u00a0Desk\u3000"
    assert normalized_name(decomposed) == "Caf\u00e9 Owner Desk"
    assert normalized_name("\u179f\u17bb\u1781\u17b6  \u1785\u17b6\u1793\u17cb") == (
        "\u179f\u17bb\u1781\u17b6 \u1785\u17b6\u1793\u17cb"
    )
    # Review round 1: control characters and line breaks are not folded into spaces; the
    # database name check refuses them.
    for kept in ("Dara\tSok", "Dara\nSok", "Dara\u2028Sok", "Dara\x1fSok"):
        assert normalized_name(kept) == kept
    assert normalized_username(" Dara.Sok ") == "dara.sok"
    assert normalized_username("Cafe\u0301") == "caf\u00e9"
    # Review round 1 (security): no white space but U+0020 in a username. Q-2026-10-22-170 (a)
    # (sub-slice L2d): other spaces are now tidied into one U+0020 instead of refused.
    for spaced in ("ann\u00a0lee", "ann\u2009lee", "ann\u3000lee"):
        assert normalized_username(spaced) == "ann lee"
    with pytest.raises(AccessAdministrationRejected) as caught:
        normalized_username("ann\tlee")
    assert (caught.value.status_code, caught.value.code) == (422, "INVALID_NAME")


def test_database_errors_become_stable_refusals_without_database_text() -> None:
    def rejected(exc: psycopg.Error) -> tuple[int, str]:
        refusal = _refusal(exc)
        assert isinstance(refusal, AccessAdministrationRejected)
        assert "app." not in refusal.message
        return refusal.status_code, refusal.code

    assert rejected(psycopg.errors.SerializationFailure()) == (412, "STALE_VERSION")
    assert rejected(psycopg.errors.UniqueViolation()) == (409, "CONFLICT")
    assert rejected(psycopg.errors.InvalidParameterValue()) == (422, "VALIDATION_ERROR")
    assert rejected(psycopg.errors.CheckViolation()) == (409, "TRY_AGAIN")
    assert rejected(psycopg.errors.DeadlockDetected()) == (409, "TRY_AGAIN")
    assert rejected(psycopg.DataError()) == (422, "VALIDATION_ERROR")
    assert isinstance(_refusal(psycopg.errors.NoDataFound()), AccessAdministrationNotFound)
    # Review round 1: a 42501 other than the Owner check (for example a missing grant) is a
    # misconfiguration, not a refusal of the actor.
    for unknown in (
        psycopg.errors.InsufficientPrivilege(),
        psycopg.errors.ObjectNotInPrerequisiteState(),
        psycopg.errors.UndefinedFunction(),
        psycopg.OperationalError(),
    ):
        assert isinstance(_refusal(unknown), AccessAdministrationUnavailable)


def test_pages_follow_the_text_order_after_the_cursor() -> None:
    items = ["c", "a", "d", "b"]
    first, cursor = _page(items, lambda item: item, None, 2)
    assert (first, cursor) == (("a", "b"), "b")
    second, cursor = _page(items, lambda item: item, cursor, 2)
    assert (second, cursor) == (("c", "d"), None)


def test_every_known_database_message_is_word_for_word_in_the_migrations() -> None:
    """Review round 1: a later change of a database message must not quietly turn its refusal
    into a generic or an unavailable answer."""
    versions = Path(__file__).parents[1] / "migrations" / "versions"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in versions.glob("*.py"))
    messages = [key for key in KNOWN_REFUSALS if " " in key]
    assert set(KNOWN_REFUSALS) - set(messages) == {
        "user_accounts_normalized_username_key",
        "role_bundles_property_lower_name_key",
        "role_bundles_name_check",
        # Q-2026-10-22-169 (a): the bundle name check of sub-slice L2c (migration 20270126_183).
        "role_bundles_name_visible_check",
    }
    for message in messages:
        assert f"'{message}'" in sources, message


def test_names_usernames_and_the_sign_in_lookup_lose_the_zero_width_space() -> None:
    """DL-081, Q-2026-10-22-169 (a) (sub-slice L2c): every save path removes U+200B from a name
    and a username, and the sign-in lookup uses the creation rule (NFC, U+200B removed)."""
    sokha, chan = "\u179f\u17bb\u1781\u17b6", "\u1785\u17b6\u1793\u17cb"
    assert normalized_name(f"\u200b{sokha}\u200b {chan}\u200b") == f"{sokha} {chan}"
    assert normalized_name(f"{sokha}\u200b\u200b{chan}") == f"{sokha}{chan}"
    assert normalized_username("\u200bDara.Sok\u200b ") == "dara.sok"
    assert normalize_local_username(" Cafe\u0301\u200b.Desk ") == "caf\u00e9.desk"
    assert normalize_local_username("Dara.Sok") == normalized_username("Dara.Sok")


def test_usernames_are_tidied_like_the_sign_in_lookup_and_other_white_space_is_refused() -> None:
    """DL-081, Q-2026-10-22-170 (a) (sub-slice L2d): a username typed with odd or double spaces
    is saved with one ordinary space between words and none at either end, exactly as the
    sign-in lookup tidies the typed username; a tab or a line break is still refused."""
    for typed in (
        "Sokha  Chan",
        " Sokha\u00a0Chan ",
        "Sokha\u3000\u2009 Chan",
        "\u200bSokha \u202f Chan\u205f",
        "SOKHA\u1680CHAN",
    ):
        assert normalized_username(typed) == "sokha chan", typed
        assert normalize_local_username(typed) == "sokha chan", typed
    assert normalized_name("Sokha  Chan") == "Sokha Chan"
    for refused in ("Sokha\tChan", "Sokha\nChan", "Sokha\u2028Chan", "Sokha\x85Chan"):
        with pytest.raises(AccessAdministrationRejected) as caught:
            normalized_username(refused)
        assert (caught.value.status_code, caught.value.code) == (422, "INVALID_NAME")


def test_the_tidied_spaces_are_exactly_the_unicode_space_separators() -> None:
    """DL-081, Q-2026-10-22-170 (a) (sub-slice L2d review round 1): the spaces that are tidied
    are exactly the code points of Unicode category Zs, so every space a keyboard can type is
    tidied and nothing else is."""
    space_separators = {
        point for point in range(sys.maxunicode + 1) if unicodedata.category(chr(point)) == "Zs"
    }
    tidied = {
        point
        for point in range(sys.maxunicode + 1)
        if not 0xD800 <= point <= 0xDFFF and SPACE_SEPARATORS.fullmatch(chr(point))
    }
    assert tidied == space_separators
