"""Roman Urdu SMS (GSM 7-bit, <= 160 chars) and reply parsing (F4, plan Section 8.8).

Urdu script needs UCS-2 (70 chars per SMS), so offline SMS are Roman Urdu::

    JIKIMI: Gate-2 par mashkook bike (2 sawar) 4 chakkar, 23:41. Code A7F2. Jawab: 1=dekh liya

Replies: ``1`` / ``dekh liya`` = ack, ``2`` / ``ghalat`` = false alarm, ``3`` / ``madad`` = need
help. A 4-character code picks a specific alert when several are open (improvement: a bare
"1" was ambiguous in plan v2.3); without a code the latest alert sent to that number is used.
Other text, in Roman or Urdu script, is read like a voice reply (``jikimi_common.intents``).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from jikimi_common.intents import reply_intent
from jikimi_contracts import AlertCandidate, AlertType

GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
MAX_LEN = 160
_REPLACE = {"–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..", "\t": " "}

_TAMPER_ROMAN = {
    "covered": "dhaka hua / andhera",
    "blur": "dhundla",
    "moved": "ka rukh badla",
    "frozen": "ruka hua",
    "offline": "band / signal nahi",
}


def to_gsm7(text: str) -> str:
    out = []
    for ch in text:
        ch = _REPLACE.get(ch, ch)
        if ch in GSM7_BASIC:
            out.append(ch)
            continue
        base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
        out.append(base if base and all(c in GSM7_BASIC for c in base) else "")
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def is_gsm7(text: str) -> bool:
    return all(ch in GSM7_BASIC for ch in text)


def format_alert_sms(alert: AlertCandidate, where: str, local_time: datetime, code: str) -> str:
    f = alert.features
    hhmm = local_time.strftime("%H:%M")
    vehicle = {"motorcycle": "bike", "car": "gaari", "rickshaw": "rickshaw", "qingqi": "chingchi"}.get(
        str(f.get("vehicle", "motorcycle")), "gaari"
    )
    tail = f"Code {code}. Jawab: 1=dekh liya 2=ghalat"
    if alert.type == AlertType.LOITERING:
        body = f"{where} par mashkook {vehicle} ({f.get('riders', 1)} sawar) {f.get('passes', 0)} chakkar, {hhmm}."
    elif alert.type == AlertType.SNATCH:
        body = f"{where} par {vehicle} sawar paidal ke qareeb tez harkat, {hhmm}. Foran jaanch karein."
    elif alert.type == AlertType.TAMPER:
        body = f"{where} camera {_TAMPER_ROMAN.get(str(f.get('check')), 'kharab')}, {hhmm}. Check karein."
    elif alert.type == AlertType.SOS:
        body = f"SOS {where} se, {hhmm}. Guard ko foran madad chahiye."
    elif alert.type == AlertType.RULE:
        body = f"{where}: rule '{f.get('rule_name_en') or f.get('rule_id')}', {hhmm}."
    else:
        body = f"{where} par mashkook harkat, {hhmm}."
    text = to_gsm7(f"JIKIMI: {body} {tail}")
    if len(text) > MAX_LEN:
        room = MAX_LEN - len(to_gsm7(f"JIKIMI: .. {tail}"))
        text = to_gsm7(f"JIKIMI: {to_gsm7(body)[: max(room, 10)]}.. {tail}")
    return text[:MAX_LEN]


_ACK = {"1", "ok", "okay", "dekh", "dekha", "dekhliya", "haan", "han", "ha", "ji", "seen", "ack"}
_FALSE = {"2", "ghalat", "galat", "ghalt", "false", "nahi", "nai"}
_HELP = {"3", "madad", "help", "sos", "bachao"}
_MENU = {"1": "ack", "2": "false_alarm", "3": "need_help"}
_CODE = re.compile(r"\b([0-9A-F]{4})\b")


def parse_reply(text: str) -> tuple[str | None, str | None]:
    """``("ack" | "false_alarm" | "need_help" | None, code | None)``."""
    raw = text.strip()
    code_m = _CODE.search(raw.upper())
    code = code_m.group(1) if code_m else None
    words = re.findall(r"[a-z0-9]+", raw.lower())
    if code:
        words = [w for w in words if w != code.lower()]
    joined = "".join(words[:2])
    first = words[0] if words else ""
    if first in _MENU:
        return _MENU[first], code
    # free text in any script, read like a voice reply ("bhai dekh liya", "madad nahi chahiye")
    intent, _ = reply_intent(re.sub(code, " ", raw, flags=re.IGNORECASE) if code else raw)
    if intent is not None:
        return intent, code
    for vocab, action in ((_HELP, "need_help"), (_FALSE, "false_alarm"), (_ACK, "ack")):
        if first in vocab or joined in vocab:
            return action, code
    return None, code
