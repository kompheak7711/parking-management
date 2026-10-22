"""Hidden characters and spaces in names and reasons (DL-081, Q-2026-10-22-169 (a) and
Q-2026-10-22-170 (a)).

Khmer keyboards put an invisible space (U+200B) between words, so a name or a reason is saved
without it; it only marks where a line may break and never changes how the text looks. The
other characters below are invisible or change how the text around them shows: two names must
never look the same, and a reason must never hide text in the audit history. The API refuses
them in a reason; the database name checks of migrations `20270120_177`, `20270124_181` and
`20270126_183` refuse them in a name (review round 1 of sub-slice L2c added the variation
selectors, U+180B to U+180F, U+2800, U+FFF0 to U+FFF8, U+1BCA0 to U+1BCA3, U+1D173 to U+1D17A
and U+E0080 to U+E0FFF).

Odd and double spaces in a name are tidied, not refused (Q-2026-10-22-170 (a), login sub-slice
L2d): every space separator becomes U+0020, a run of them one, and none stays at either end; the
sign-in lookup tidies the typed username the same way.
"""

import re
from typing import Final

ZERO_WIDTH_SPACE: Final = "\u200b"
HIDDEN_NAME_CHARACTERS: Final = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff"
    "\uffa0\ufff0-\ufffb\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)
# A reason keeps the zero-width non-joiner and joiner (U+200C, U+200D), which Khmer text uses,
# and the emoji variation selector U+FE0F, which the emoji keyboard adds (Q-2026-10-22-170).
HIDDEN_REASON_CHARACTERS: Final = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b\u200e\u200f\u2028\u2029\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0e\ufeff"
    "\uffa0\ufff0-\ufffb\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)


# The space separators (Unicode category Zs). Tabs, line breaks and other control characters are
# not spaces: they are left for the database name checks to refuse.
SPACE_SEPARATORS: Final = re.compile("[\u0020\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")


def without_zero_width_spaces(value: str) -> str:
    """The text without U+200B, which a Khmer keyboard puts between words."""
    return value.replace(ZERO_WIDTH_SPACE, "")


def tidy_spaces(value: str) -> str:
    """Each run of space separators as one U+0020, none at either end (Q-2026-10-22-170 (a):
    a name typed with odd or double spaces is tidied, not refused)."""
    return SPACE_SEPARATORS.sub(" ", value).strip(" ")
