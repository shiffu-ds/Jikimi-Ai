"""What a guard's reply means (F12): ``ack`` | ``false_alarm`` | ``need_help`` | ``None``.

Shared by SMS replies and voice transcripts. Voice replies are free speech ("haan main ne dekh
liya", "یہ غلط الارم ہے", "jaldi aao madad chahiye"), and Whisper writes Urdu in Urdu script,
sometimes in Devanagari or in Roman letters, so every phrase is listed in all three scripts.

* Help beats false alarm beats seen: a guard who asks for help must never be read as "seen".
* A phrase negated within its clause does not count: "madad nahi chahiye", "ghalat nahi hai",
  "nahi dekha". A copula ("hai", "tha", "ہے") ends the clause, so in "chor nahi tha, apna banda
  tha" only the thief is negated; a phrase that is itself negative ("kuch nahi") is only made
  stronger by another "nahi". Help is negated only by the word right after it, so a missed call
  for help stays unlikely ("madad ki zaroorat nahi" still reads as help).
* Only negations ("nahi", "نہیں") count as a false alarm, as in the SMS replies.
* Nothing else is guessed: ``None`` means "ask again / use the buttons". The guard app always
  shows what it understood before anything is sent.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Intent = Literal["ack", "false_alarm", "need_help"]

# fmt: off
_PHRASES: dict[Intent, tuple[str, ...]] = {
    "need_help": (
        "madad", "madat", "help", "sos", "bachao", "police", "polis", "pulis", "jaldi aao", "jaldi aa",
        "jaldi bhejo", "chor", "daku", "dakoo", "dacoit", "thief", "khatra", "khatara", "danger", "aag", "fire",
        "goli", "firing", "zakhmi", "injured", "ambulance", "emergency", "hamla", "attack", "chheen", "cheen",
        "snatch", "robbery", "backup", "bhejo",
        "مدد", "بچاؤ", "بچاو", "پولیس", "جلدی آؤ", "جلدی آو", "جلدی بھیجو", "چور", "ڈاکو", "خطرہ", "خطرا",
        "آگ", "گولی", "فائرنگ", "زخمی", "ایمبولینس", "حملہ", "چھین", "ہیلپ", "بیک اپ", "بھیجو",
        "मदद", "बचाओ", "पुलिस", "जल्दी आओ", "जल्दी भेजो", "चोर", "डाकू", "खतरा", "आग", "गोली", "फायरिंग",
        "घायल", "जख्मी", "एम्बुलेंस", "हमला", "छीन", "हेल्प", "बैकअप", "भेजो",
    ),
    "false_alarm": (
        "ghalat", "galat", "ghalt", "galt", "ghalti", "galti", "jhoota", "jhuta", "false", "fake", "mistake",
        "koi nahi", "koi nai", "kuch nahi", "kuch nai", "kuch bhi nahi", "sab theek", "sab thik", "khairiyat",
        "apna banda", "apna aadmi", "apne log", "billi", "kutta", "janwar", "nothing", "nobody", "no one",
        "all clear", "all good",
        "غلط", "غلطی", "جھوٹا", "جھوٹی", "کوئی نہیں", "کچھ نہیں", "کچھ بھی نہیں", "سب ٹھیک", "خیریت",
        "اپنا بندہ", "اپنا آدمی", "اپنے لوگ", "بلی", "کتا", "جانور", "فالس",
        "गलत", "गलती", "झूठा", "झूठी", "कोई नहीं", "कुछ नहीं", "कुछ भी नहीं", "सब ठीक", "खैरियत",
        "अपना बंदा", "अपना आदमी", "अपने लोग", "बिल्ली", "कुत्ता", "जानवर",
    ),
    "ack": (
        "dekh liya", "dekh lia", "dekhliya", "dekh lya", "daikh liya", "dekha", "dekh raha", "dekh rahi",
        "dekh rha", "dekh leta", "dekhta", "haan", "han", "ok", "okay", "okey", "theek", "thik", "acha",
        "achha", "seen", "ack", "yes", "got it", "on it", "coming", "on my way", "aa raha", "aa rahi",
        "aa gaya", "ja raha", "pohanch", "pahunch", "pohnch", "check kar", "nazar",
        "دیکھ لیا", "دیکھا", "دیکھ رہا", "دیکھ رہی", "دیکھ لیتا", "ہاں", "ٹھیک", "اچھا", "اوکے", "آ رہا",
        "آ رہی", "آ گیا", "جا رہا", "پہنچ", "چیک کر", "نظر",
        "देख लिया", "देखा", "देख रहा", "देख रही", "हां", "ठीक", "अच्छा", "ओके", "आ रहा", "आ रही", "आ गया",
        "जा रहा", "पहुंच", "चेक कर", "नजर",
    ),
}
_NEGATIONS = ("nahi", "nai", "nahin", "nhi", "nahee", "mat", "not", "no", "dont", "never",
              "نہیں", "نہی", "نئیں", "مت", "नहीं", "नही", "मत")
_FILLERS = ("ji", "jee", "bhai", "sir", "saab", "sahab", "yaar", "jaan",
            "جی", "بھائی", "صاحب", "یار", "जी", "भाई", "साहब", "यार")
_COPULAS = ("hai", "hain", "tha", "thi", "the", "ho", "hoon", "hun", "is", "was",
            "ہے", "ہیں", "تھا", "تھی", "تھے", "ہو", "ہوں", "है", "हैं", "था", "थी", "थे", "हो", "हूं")
# fmt: on

# harakat, madda / hamza marks, superscript alef, tatweel, nukta
_MARKS = frozenset("ًٌٍَُِّْٰٕٓٔـ़")
_URDU_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ", "ۀ": "ہ", "ۂ": "ہ", "ة": "ہ", "ھ": "ہ"})
_CLAUSE = re.compile(r"[.,!?;:،۔؟।|\n]+")
_REPEAT = re.compile(r"([a-z])\1+")


def _fold(text: str) -> str:
    """Spelling-tolerant form: Urdu letter variants, marks, nukta, chandrabindu, "haaan" -> "han"."""
    text = text.lower().replace("'", "").replace("’", "")
    chars = ("ं" if ch == "ँ" else ch for ch in unicodedata.normalize("NFD", text) if ch not in _MARKS)
    return _REPEAT.sub(r"\1", unicodedata.normalize("NFC", "".join(chars).translate(_URDU_FOLD)))


def _tokens(clause: str) -> list[str]:
    return "".join(ch if unicodedata.category(ch)[0] in "LMN" else " " for ch in clause).split()


_NEG, _FILL, _COP = (frozenset(_fold(w) for w in ws) for ws in (_NEGATIONS, _FILLERS + _COPULAS, _COPULAS))
_PHRASE_TOKENS: dict[Intent, list[tuple[tuple[str, ...], str, bool]]] = {
    intent: [(words, p, bool(_NEG & set(words))) for p in phrases for words in [tuple(_tokens(_fold(p)))]]
    for intent, phrases in _PHRASES.items()
}


def _negated(words: list[str], start: int, end: int, before: int, after: int) -> bool:
    for i in range(start - 1, max(start - before, 0) - 1, -1):
        if words[i] in _COP:
            break
        if words[i] in _NEG:
            return True
    for w in words[end : end + after]:
        if w in _COP:
            break
        if w in _NEG:
            return True
    return False


def reply_intent(text: str) -> tuple[Intent | None, str | None]:
    """``(intent, the phrase that decided it)`` for an SMS or a transcribed voice reply."""
    clauses = [c for c in (_tokens(part) for part in _CLAUSE.split(_fold(text or ""))) if c]
    for intent in ("need_help", "false_alarm", "ack"):
        before, after = (0, 1) if intent == "need_help" else (2, 2)
        for words in clauses:
            for phrase, shown, negative in _PHRASE_TOKENS[intent]:
                n = len(phrase)
                for i in range(len(words) - n + 1):
                    if tuple(words[i : i + n]) == phrase and (negative or not _negated(words, i, i + n, before, after)):
                        return intent, shown
    words = [w for c in clauses for w in c]
    if any(w in _NEG for w in words) and all(w in _NEG or w in _FILL for w in words):
        return "false_alarm", next(w for w in words if w in _NEG)
    return None, None
