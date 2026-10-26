"""Roman Urdu -> Devanagari, so a phone's *Hindi* voice can read an Urdu alert aloud.

Many Android phones ship a Hindi text-to-speech voice and no Urdu one, and spoken Urdu and Hindi
are one language (Hindustani). The alerts' Roman Urdu text comes from fixed templates, so a
dictionary for their words plus spelling rules for the rest (camera and zone names) gives
Devanagari that a Hindi voice pronounces as Urdu - the guard hears "Gate-2 par 23:41 baje ...",
not letters. Nukta letters (क़ ख़ ग़ ज़ फ़) keep the Urdu sounds where the voice supports them.
"""

from __future__ import annotations

import re

# words of the alert templates whose spelling rules would get wrong (and English loanwords)
WORDS = {
    "par": "पर", "baje": "बजे", "ke": "के", "ki": "की", "ka": "का", "ko": "को", "se": "से", "mein": "में",
    "hai": "है", "hain": "हैं", "nahi": "नहीं", "aur": "और", "ya": "या", "ye": "ये", "yahan": "यहाँ",
    "min": "मिनट", "km": "किलोमीटर", "bike": "बाइक", "gaari": "गाड़ी", "gari": "गाड़ी", "car": "कार",
    "rickshaw": "रिक्शा", "camera": "कैमरा", "cameras": "कैमरों", "gate": "गेट", "guard": "गार्ड",
    "supervisor": "सुपरवाइज़र", "check": "चेक", "rule": "रूल", "sos": "एस ओ एस", "video": "वीडियो",
    "phone": "फ़ोन", "laga": "लगा", "foran": "फ़ौरन", "etimad": "एतिमाद", "darmiyana": "दरमियाना",
    "zyada": "ज़्यादा", "bohat": "बहुत", "kam": "कम", "qareeb": "क़रीब", "qareebi": "क़रीबी",
    "afraad": "अफ़राद", "paidal": "पैदल", "shakhs": "शख़्स", "bilkul": "बिल्कुल", "jaanch": "जांच",
    "karein": "करें", "chakkar": "चक्कर", "martaba": "मर्तबा", "guzre": "गुज़रे", "guzra": "गुज़रा",
    "aahista": "आहिस्ता", "hue": "हुए", "hui": "हुई", "hua": "हुआ", "ruke": "रुके", "ruka": "रुका",
    "tak": "तक", "aaye": "आए", "haath": "हाथ", "tez": "तेज़", "tezi": "तेज़ी", "harkat": "हरकत",
    "phir": "फिर", "door": "दूर", "gaye": "गए", "sawar": "सवार", "shakhs.": "शख़्स।", "mashkook": "मशकूक",
    "madad": "मदद", "maangi": "मांगी", "rabta": "राबता", "darmiyan": "दरमियान", "laga chuke": "लगा चुके",
    "chuke": "चुके", "raasta": "रास्ता", "aam": "आम", "dinon": "दिनों", "jaisa": "जैसा", "jaisi": "जैसी",
    "ilaqe": "इलाक़े", "taqreeban": "तक़रीबन", "tasdeeq": "तसदीक़", "shuda": "शुदा", "wardaat": "वारदात",
    "wali": "वाली", "wala": "वाला", "dekhi": "देखी", "gayi": "गई", "sirf": "सिर्फ़", "nazar": "नज़र",
    "rakhein": "रखें", "batayein": "बताएं", "khud": "ख़ुद", "karwai": "कार्रवाई", "na": "न", "paas": "पास",
    "suni": "सुनी", "awaaz": "आवाज़", "firing": "फ़ायरिंग", "cheekh": "चीख़", "sheesha": "शीशा",
    "toot": "टूट", "toota": "टूटा", "tootne": "टूटने", "patakhe": "पटाख़े", "kaali": "काली", "kaala": "काला", "safaid": "सफ़ेद",
    "laal": "लाल", "safed": "सफ़ेद", "neeli": "नीली", "neela": "नीला", "hari": "हरी", "hara": "हरा",
    "peeli": "पीली", "peela": "पीला", "silver": "सिल्वर", "sunehri": "सुनहरी", "bhoori": "भूरी",
    "bhoora": "भूरा", "naranji": "नारंजी", "dhaka": "ढका", "dhanka": "ढंका", "dhundla": "धुंधला",
    "ghuma": "घुमा", "ghumaya": "घुमाया", "band": "बंद", "jamna": "जमना", "jam": "जम", "naya": "नया",
    "rukh": "रुख़", "qabool": "क़बूल", "kar": "कर", "liya": "लिया", "gaya": "गया", "zones": "ज़ोन",
    "dobara": "दोबारा", "dekh": "देख", "lein": "लें", "aksar": "अक्सर", "hota": "होता", "pattern": "पैटर्न",
    "is": "इस", "aisa": "ऐसा", "bhi": "भी", "baar": "बार", "darja": "दर्जा", "mode": "मोड", "chand": "चाँद",
    "raat": "रात", "eid": "ईद", "ramazan": "रमज़ान", "muharram": "मुहर्रम", "bazaar": "बाज़ार",
    "raahgeer": "राहगीर", "peeche": "पीछे", "qadam": "क़दम", "kuch": "कुछ", "chal": "चल", "raha": "रहा",
    "rahi": "रही", "rukta": "रुकता", "jata": "जाता", "khairiyat": "ख़ैरियत", "maloom": "मालूम", "gher": "घेर",
    "rakha": "रखा", "chaaron": "चारों", "taraf": "तरफ़", "haathapai": "हाथापाई", "zor": "ज़ोर",
    "zabardasti": "ज़बरदस्ती", "kheench": "खींच", "bithaya": "बिठाया", "chali": "चली", "chala": "चला",
    "zaroorat": "ज़रूरत", "call": "कॉल", "achanak": "अचानक", "gir": "गिर", "utha": "उठा", "jaayein": "जाएं",
    "girne": "गिरने", "pehle": "पहले", "bhaag": "भाग", "khari": "खड़ी", "jhuk": "झुक", "karta": "करता",
    "dhakel": "धकेल", "malik": "मालिक", "intezar": "इंतज़ार", "log": "लोग", "jagah": "जगह",
    "mukhtalif": "मुख़्तलिफ़", "simt": "सिम्त", "bhaagne": "भागने", "lage": "लगे", "bhagdar": "भगदड़",
    "waqt": "वक़्त", "aas": "आस", "koi": "कोई", "second": "सेकंड", "baat": "बात", "zameen": "ज़मीन",
    "para": "पड़ा", "khatra": "ख़तरा", "kisi": "किसी", "sakta": "सकता", "un": "उन", "tha": "था", "thi": "थी",
    "aaya": "आया", "ja": "जा", "dekhein": "देखें", "woh": "वो", "liye": "लिए", "use": "उसे",
}  # fmt: skip

_CONS = [
    ("chh", "छ"), ("kh", "ख़"), ("gh", "ग़"), ("ch", "च"), ("sh", "श"), ("th", "थ"), ("dh", "ध"), ("ph", "फ"),
    ("bh", "भ"), ("jh", "झ"), ("b", "ब"), ("p", "प"), ("t", "त"), ("d", "द"), ("k", "क"), ("g", "ग"),
    ("j", "ज"), ("z", "ज़"), ("f", "फ़"), ("q", "क़"), ("s", "स"), ("h", "ह"), ("m", "म"), ("n", "न"),
    ("l", "ल"), ("r", "र"), ("v", "व"), ("w", "व"), ("y", "य"), ("x", "क्स"), ("c", "क"),
]  # fmt: skip
_VOWELS = [  # (roman, independent letter, sign after a consonant)
    ("aa", "आ", "ा"), ("ai", "ऐ", "ै"), ("au", "औ", "ौ"), ("ee", "ई", "ी"), ("oo", "ऊ", "ू"), ("ei", "ए", "े"),
    ("a", "अ", ""), ("i", "इ", "ि"), ("u", "उ", "ु"), ("e", "ए", "े"), ("o", "ओ", "ो"),
]  # fmt: skip
_TOKEN = re.compile(r"[A-Za-z]+")


def _word(w: str) -> str:
    out: list[str] = []
    i, prev_cons = 0, False
    while i < len(w):
        for rom, dev in _CONS:
            if w.startswith(rom, i):
                if prev_cons and out and out[-1] == dev:  # doubled consonant: chakkar -> चक्कर
                    out.append("्")
                if rom == "n" and prev_cons is False and out and i + 1 < len(w) and w[i + 1] not in "aeiou":
                    out.append("ं")  # nasal before a consonant: jaanch -> जांच
                    i += 1
                    prev_cons = False
                    break
                out.append(dev)
                i += len(rom)
                prev_cons = True
                break
        else:
            for rom, ind, sign in _VOWELS:
                if w.startswith(rom, i):
                    final_i = rom == "i" and i + 1 == len(w)
                    if prev_cons:
                        out.append("ी" if final_i else sign)
                    else:
                        out.append("ई" if final_i else ind)
                    i += len(rom)
                    prev_cons = False
                    break
            else:
                out.append(w[i])
                i += 1
                prev_cons = False
    return "".join(out)


def roman_to_devanagari(text: str) -> str:
    """Devanagari for a Roman Urdu sentence; digits, times and punctuation stay as they are."""
    text = re.sub(r"\blaga chuke\b", WORDS["laga chuke"], text, flags=re.IGNORECASE)

    def one(m: re.Match[str]) -> str:
        w = m.group(0).lower()
        return WORDS.get(w) or _word(w)

    return _TOKEN.sub(one, text).replace(". ", "। ").rstrip(".") + ("।" if text.rstrip().endswith(".") else "")
