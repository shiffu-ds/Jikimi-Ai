"""Text normalization for Roman Urdu and Urdu script, plus a tiny fuzzy matcher."""

from __future__ import annotations

import re
import unicodedata

_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC_TO_URDU = str.maketrans(
    {"ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ", "ة": "ہ", "ۀ": "ہ", "ؤ": "و", "أ": "ا", "إ": "ا"}
)
_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
_TOKEN = re.compile(r"\d{1,2}:\d{2}|[\w؀-ۿ]+", re.UNICODE)
_REPEAT = re.compile(r"([a-z])\1{2,}")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text).translate(_URDU_DIGITS).translate(_ARABIC_TO_URDU)
    t = _DIACRITICS.sub("", t).lower()
    t = t.replace("‌", " ").replace("‍", "")
    return _REPEAT.sub(r"\1\1", t)  # kaaaali -> kaali


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def is_urdu(token: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in token)


def damerau(a: str, b: str, max_d: int = 2) -> int:
    """Optimal string alignment distance with early exit above ``max_d``."""
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > max_d:
            return max_d + 1
        prev2, prev = prev, cur
    return prev[-1]


def fuzzy_lookup(token: str, vocab: dict[str, tuple[str, str]]) -> tuple[str, tuple[str, str]] | None:
    """Closest vocabulary word: distance 1 for 4-7 letters, 2 for longer; ties -> None."""
    if len(token) < 4 or token.isdigit():
        return None
    max_d = 1 if len(token) < 8 else 2
    best: list[tuple[int, str]] = []
    for word in vocab:
        if is_urdu(word) != is_urdu(token) or abs(len(word) - len(token)) > max_d:
            continue
        d = damerau(token, word, max_d)
        if d <= max_d:
            best.append((d, word))
    if not best:
        return None
    best.sort()
    top = [w for d, w in best if d == best[0][0]]
    cats = {vocab[w] for w in top}
    if len(cats) > 1:
        return None
    return top[0], vocab[top[0]]
