"""Roman Urdu / Urdu / English lexicon for the query parser (F1; released as RUVR lexicon).

Every list holds spelling variants seen in Roman Urdu writing. ``datasets/ruvr/lexicon.tsv`` is
generated from this file (``scripts/export_lexicon.py``), so the public benchmark and the
product never disagree. Add variants here when RUVR queries reveal new spellings.
"""

from __future__ import annotations

COLORS: dict[str, list[str]] = {
    "black": [
        "kaali",
        "kali",
        "kaly",
        "kaala",
        "kala",
        "kaale",
        "kale",
        "kaaly",
        "siyah",
        "black",
        "blak",
        "کالی",
        "کالا",
        "کالے",
        "سیاہ",
    ],
    "white": ["safaid", "sufaid", "safed", "sufed", "safeed", "sufaid", "white", "wite", "سفید"],
    "red": ["laal", "lal", "surkh", "red", "لال", "سرخ"],
    "blue": ["neela", "neeli", "nila", "nili", "neelay", "neele", "blue", "نیلا", "نیلی", "نیلے"],
    "green": ["hara", "hari", "haray", "hare", "sabz", "green", "ہرا", "ہری", "ہرے", "سبز"],
    "yellow": ["peela", "peeli", "pila", "pili", "peelay", "zard", "yellow", "پیلا", "پیلی", "زرد"],
    "gray": ["grey", "gray", "surmai", "surmayi", "khaki", "سرمئی", "گرے"],
    "silver": ["silver", "silvar", "chandi", "سلور", "چاندی"],
    "brown": ["bhoora", "bhoori", "bhura", "bhuri", "brown", "بھورا", "بھوری"],
    "orange": ["orange", "narangi", "نارنجی"],
}

VEHICLES: dict[str, list[str]] = {
    "motorcycle": [
        "bike", "bikes", "baik", "byk", "bik", "motorcycle", "motorcycles", "motorsycle", "motorsaikal",
        "motorsaikil", "motarsaikal", "motor", "honda", "hondaa", "cd70", "cg125", "yamaha",
        "موٹرسائیکل", "موٹر", "بائیک", "بائک", "ہونڈا",
    ],
    "car": ["car", "cars", "gaari", "gaadi", "gari", "gadi", "gaarri", "gaariyan", "گاڑی", "گاڑیاں", "کار"],
    "rickshaw": ["rickshaw", "riksha", "rikshaw", "rickshah", "rikshah", "rikshe", "رکشہ", "رکشا", "رکشے"],
    "qingqi": ["qingqi", "chingchi", "chingchee", "chingi", "چنگچی"],
    "loader_rickshaw": ["loader", "loder", "لوڈر"],
    "bus": ["bus", "coaster", "بس"],
    "truck": ["truck", "trak", "ٹرک"],
    "van": ["van", "hiace", "haiace", "wagon", "وین"],
    "bicycle": ["cycle", "saikal", "saeekal", "bicycle", "سائیکل"],
}  # fmt: skip

PERSON_WORDS = [
    "banda", "bande", "bandey", "bandon", "aadmi", "admi", "log", "logon", "afraad", "afrad", "shakhs",
    "insaan", "person", "persons", "people", "man", "men", "larka", "larke", "larkay", "paidal",
    "بندہ", "بندے", "آدمی", "لوگ", "افراد", "شخص", "پیدل",
]  # fmt: skip

# never inferred: the system has no gender/age/ethnicity classifier (Section 14.5)
DEMOGRAPHIC_WORDS = [
    "aurat",
    "auraten",
    "khatoon",
    "khawateen",
    "larki",
    "larkiyan",
    "bacha",
    "bachay",
    "boorha",
    "عورت",
    "خاتون",
    "لڑکی",
    "بچہ",
]

NUMBERS: dict[str, int] = {
    "ek": 1, "aik": 1, "ik": 1, "one": 1,
    "do": 2, "dou": 2, "two": 2,
    "teen": 3, "tin": 3, "three": 3,
    "char": 4, "chaar": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5,
    "chhe": 6, "chay": 6, "che": 6, "six": 6,
    "saat": 7, "sat": 7, "seven": 7,
    "aath": 8, "ath": 8, "eight": 8,
    "nau": 9, "no": 9, "nine": 9,
    "das": 10, "dus": 10, "ten": 10,
    "gyarah": 11, "giyarah": 11, "eleven": 11,
    "barah": 12, "baara": 12, "twelve": 12,
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10, "گیارہ": 11, "بارہ": 12,
}  # fmt: skip
# tokens that are numbers only when bound to a counted noun ("do sawar", not "dikha do")
WEAK_NUMBERS = {"do", "no", "sat", "tin", "che", "ath"}

RIDER_WORDS = ["sawar", "sawaar", "swar", "savar", "sowar", "riders", "rider", "سوار"]
DOUBLE_RIDING = ["double sawari", "dabal sawari", "doubla", "double", "dabal", "pillion", "pilion", "ڈبل سواری", "ڈبل"]
SINGLE_RIDING = ["akela", "akeli", "akele", "single", "alone", "اکیلا", "اکیلے"]

HELMET_WORDS = ["helmet", "helmat", "hilmet", "ہیلمٹ"]
NEGATIONS = ["nahi", "nahin", "nai", "na", "bina", "baghair", "bghair", "without", "no", "be", "بغیر", "نہیں", "بنا"]

PLACE_WORDS: dict[str, list[str]] = {
    "gate": ["gate", "gait", "geit", "gat", "darwaza", "darwazay", "darwaze", "دروازہ", "دروازے", "گیٹ"],
    "market": ["market", "markeet", "bazaar", "bazar", "bazzar", "dukaan", "dukan", "بازار", "مارکیٹ", "دکان"],
    "street": ["street", "gali", "galli", "sarak", "sadak", "road", "rasta", "گلی", "سڑک"],
    "parking": ["parking", "parkin", "پارکنگ"],
}

DAY_REFS: dict[str, int] = {
    "aaj": 0, "aj": 0, "today": 0, "آج": 0,
    "kal": 1, "kl": 1, "yesterday": 1, "کل": 1,
    "parson": 2, "parsoon": 2, "parso": 2, "پرسوں": 2,
}  # fmt: skip

DAY_PARTS: dict[str, tuple[str, str]] = {
    "raat": ("18:00", "06:00"),
    "subah": ("05:00", "12:00"),
    "dopahar": ("12:00", "15:00"),
    "sehpahar": ("15:00", "17:30"),
    "shaam": ("17:00", "20:00"),
    "aadhi_raat": ("23:00", "02:00"),
}
DAY_PART_WORDS: dict[str, list[str]] = {
    "raat": ["raat", "rat", "raath", "night", "tonight", "رات"],
    "subah": ["subah", "subha", "sobah", "subh", "morning", "صبح"],
    "dopahar": ["dopahar", "dopehar", "dupahar", "dopher", "noon", "afternoon", "دوپہر"],
    "sehpahar": ["sehpahar", "sehpehar", "asr", "عصر", "سہ پہر"],
    "shaam": ["shaam", "sham", "shyam", "evening", "شام"],
    "aadhi_raat": ["aadhi raat", "adhi raat", "midnight", "آدھی رات"],
}

WEEKDAYS: dict[str, int] = {
    "peer": 0, "pir": 0, "somwar": 0, "monday": 0, "پیر": 0,
    "mangal": 1, "tuesday": 1, "منگل": 1,
    "budh": 2, "bud": 2, "wednesday": 2, "بدھ": 2,
    "jumeraat": 3, "jumerat": 3, "thursday": 3, "جمعرات": 3,
    "juma": 4, "jumma": 4, "jummah": 4, "friday": 4, "جمعہ": 4,
    "sanichar": 5, "saturday": 5, "ہفتہ": 5,
    "itwaar": 6, "itwar": 6, "sunday": 6, "اتوار": 6,
}  # fmt: skip

UNITS: dict[str, str] = {
    "ghante": "hours", "ghanta": "hours", "ghanton": "hours", "hours": "hours", "hour": "hours", "گھنٹے": "hours", "گھنٹہ": "hours",
    "minute": "minutes", "minat": "minutes", "mint": "minutes", "min": "minutes", "minutes": "minutes", "منٹ": "minutes",
    "din": "days", "dinon": "days", "days": "days", "day": "days", "دن": "days",
    "hafte": "weeks", "hafta": "weeks", "week": "weeks", "weeks": "weeks", "ہفتے": "weeks",
}  # fmt: skip
PAST_WORDS = [
    "pichle",
    "pichhle",
    "pichli",
    "pichhli",
    "guzre",
    "guzri",
    "guzishta",
    "last",
    "past",
    "پچھلے",
    "پچھلی",
    "گزشتہ",
]
CLOCK_WORDS = ["baje", "bajay", "baj", "bjy", "oclock", "بجے"]
AFTER_WORDS = ["baad", "bad", "after", "بعد"]
BEFORE_WORDS = ["pehle", "pahle", "before", "پہلے"]
NOW_WORDS = ["abhi", "abi", "now", "ابھی"]

INTENT_WORDS: dict[str, list[str]] = {
    "count": ["kitni", "kitne", "kitna", "count", "how many", "کتنی", "کتنے"],
    "trajectory": ["kahan kahan", "kidhar", "raasta", "route", "peecha", "track", "کہاں"],
    "report": ["report", "riport", "saboot", "evidence", "fir", "رپورٹ"],
}

ALERT_TYPE_WORDS: dict[str, list[str]] = {
    "snatch": [
        "chheena",
        "cheena",
        "chhina",
        "chheen",
        "cheen",
        "chhinna",
        "jhapti",
        "snatch",
        "snatching",
        "chhapta",
        "چھینا",
        "چھین",
        "جھپٹی",
    ],
    "loitering": [
        "chakkar",
        "chakar",
        "chakkr",
        "chakker",
        "ghoom",
        "ghum",
        "ghoomna",
        "mandla",
        "mandlana",
        "loiter",
        "loitering",
        "چکر",
        "گھوم",
    ],
    "camera_tamper": ["tamper", "dhaka", "dhak", "camera band", "کیمرہ بند"],
    "person_in_danger": [
        "khatra",
        "khatre",
        "ghera",
        "gher",
        "haathapai",
        "hathapai",
        "larai",
        "jhagra",
        "ghaseet",
        "ghaseeta",
        "zabardasti",
        "agwa",
        "kidnap",
        "girna",
        "gira",
        "stalking",
        "harassment",
        "خطرہ",
        "گھیرا",
        "ہاتھاپائی",
        "لڑائی",
        "جھگڑا",
        "گھسیٹ",
        "زبردستی",
        "اغوا",
    ],
    "vehicle_theft": ["chori", "churai", "churaya", "stolen", "theft", "چوری"],
    "crowd_panic": ["bhagdar", "bhagdad", "bhagdarr", "stampede", "afratafri", "بھگدڑ", "افراتفری"],
    "sos": ["sos", "madad", "panic", "مدد"],
}

STOPWORDS = frozenset(
    ["ke", "ki", "ka", "ko", "mein", "me", "main", "mai", "mei", "pe", "par", "per", "wali", "wala", "wale", "waale", "walay", "se", "tak", "aur", "or", "jo", "the", "tha", "thi", "thay", "hai", "hain", "he", "hy", "koi", "kuch", "sab", "saray", "sare", "yeh", "ye", "woh", "wo", "is", "us", "un", "in", "ne", "bhi", "bas", "sirf", "please", "plz", "zara", "jaldi", "kya", "show", "find", "search", "dhoondo", "dhundo", "dhondo", "dikhao", "dikha", "dikhado", "dikhaiye", "bata", "batao", "paas", "pass", "qareeb", "kareeb", "near", "nazdeek", "clip", "clips", "video", "videos", "footage", "recording", "a", "an", "of", "on", "at", "with", "by", "ko", "ka", "for", "hi", "ho", "raha", "rahi", "rahe", "tha", "gaya", "gayi", "gaye", "aya", "aayi", "aaye", "wapas", "phir", "dobara", "baar", "bar", "wala", "jab", "نے", "کے", "کی", "کا", "کو", "میں", "پر", "سے", "تک", "اور", "والی", "والا", "والے", "دکھاؤ", "دکھائیں", "ڈھونڈو", "پاس", "قریب", "ہے", "ہیں", "تھا", "تھی"]
)  # fmt: skip


def canonical(words: dict[str, list[str]]) -> dict[str, str]:
    """Single-token variant -> canonical key, e.g. ``canonical(COLORS)["kaali"] == "black"``."""
    return {w: k for k, ws in words.items() for w in ws if " " not in w}


def variants_index() -> dict[str, tuple[str, str]]:
    """``variant -> (category, canonical)`` for single-word variants (fuzzy matching)."""
    idx: dict[str, tuple[str, str]] = {}
    for canon, words in COLORS.items():
        for w in words:
            idx.setdefault(w, ("color", canon))
    for canon, words in VEHICLES.items():
        for w in words:
            idx.setdefault(w, ("vehicle", canon))
    for w in PERSON_WORDS:
        idx.setdefault(w, ("person", "person"))
    for canon, words in ALERT_TYPE_WORDS.items():
        for w in words:
            if " " not in w:
                idx.setdefault(w, ("alert_type", canon))
    for canon, words in PLACE_WORDS.items():
        for w in words:
            idx.setdefault(w, ("place", canon))
    for canon, words in DAY_PART_WORDS.items():
        for w in words:
            if " " not in w:
                idx.setdefault(w, ("day_part", canon))
    for w in RIDER_WORDS:
        idx.setdefault(w, ("rider", "rider"))
    for w in HELMET_WORDS:
        idx.setdefault(w, ("helmet", "helmet"))
    return idx
