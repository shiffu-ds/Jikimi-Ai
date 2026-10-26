"""Alert explanations ("Urdu wajah", F5) in Urdu script, Roman Urdu and English.

Template-first by design (plan Section 8.4): templates are deterministic, auditable and work
offline on the edge (SMS needs Roman Urdu without any LLM). An LLM may only *polish* them.

Language rules (Section 13.1): neutral words only ("mashkook harkat", "jaanch karein"), never
"chor"; no identity, ethnicity or gender words; the human decides.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Explanation:
    ur: str
    roman: str
    en: str


@dataclass(frozen=True)
class CameraNames:
    id: str
    name: str | None = None
    name_ur: str | None = None
    name_roman: str | None = None

    @property
    def en(self) -> str:
        return self.name or self.id

    @property
    def ur(self) -> str:
        return self.name_ur or self.en

    @property
    def roman(self) -> str:
        return self.name_roman or self.en


# type -> (urdu, roman, english, urdu_gender)
_OBJECTS: dict[str, tuple[str, str, str, str]] = {
    "motorcycle": ("موٹر سائیکل", "bike", "motorcycle", "f"),
    "bicycle": ("سائیکل", "cycle", "bicycle", "f"),
    "car": ("گاڑی", "gaari", "car", "f"),
    "van": ("وین", "van", "van", "f"),
    "bus": ("بس", "bus", "bus", "f"),
    "truck": ("ٹرک", "truck", "truck", "m"),
    "rickshaw": ("رکشہ", "rickshaw", "rickshaw", "m"),
    "qingqi": ("چنگچی", "chingchi", "qingqi", "m"),
    "loader_rickshaw": ("لوڈر رکشہ", "loader", "loader rickshaw", "m"),
    "donkey_cart": ("گدھا گاڑی", "gadha gaari", "donkey cart", "f"),
    "person": ("شخص", "banda", "person", "m"),
}

# color -> (urdu feminine, urdu masculine, roman feminine, roman masculine, english)
_COLORS: dict[str, tuple[str, str, str, str, str]] = {
    "black": ("کالی", "کالا", "kaali", "kaala", "black"),
    "white": ("سفید", "سفید", "safaid", "safaid", "white"),
    "red": ("لال", "لال", "laal", "laal", "red"),
    "blue": ("نیلی", "نیلا", "neeli", "neela", "blue"),
    "green": ("ہری", "ہرا", "hari", "hara", "green"),
    "yellow": ("پیلی", "پیلا", "peeli", "peela", "yellow"),
    "gray": ("سرمئی", "سرمئی", "surmai", "surmai", "grey"),
    "silver": ("سلور", "سلور", "silver", "silver", "silver"),
    "brown": ("بھوری", "بھورا", "bhoori", "bhoora", "brown"),
    "orange": ("نارنجی", "نارنجی", "narangi", "narangi", "orange"),
}

_TAMPER: dict[str, tuple[str, str, str]] = {
    "covered": (
        "کیمرہ ڈھکا ہوا ہے یا مکمل اندھیرا ہے",
        "camera dhaka hua hai ya bilkul andhera hai",
        "the camera is covered or completely dark",
    ),
    "blur": (
        "کیمرے کی تصویر دھندلی ہو گئی ہے",
        "camera ki tasveer dhundli ho gayi hai",
        "the camera image became blurry",
    ),
    "moved": (
        "کیمرے کا رخ بدل دیا گیا ہے",
        "camera ka rukh badal diya gaya hai",
        "the camera was moved or rotated",
    ),
    "view_accepted": (
        "کیمرے کا نیا رخ قبول کر لیا گیا؛ زونز دوبارہ دیکھ لیں",
        "camera ka naya rukh qabool kar liya gaya; zones dobara dekh lein",
        "the camera's new view was accepted; check that the zones still fit",
    ),
    "frozen": (
        "کیمرے کی تصویر رک گئی ہے",
        "camera ki tasveer ruk gayi hai",
        "the camera image is frozen",
    ),
    "offline": (
        "کیمرے سے سگنل نہیں آ رہا",
        "camera se signal nahi aa raha",
        "there is no signal from the camera",
    ),
}


def object_names(obj_type: str | None, color: str | None = None) -> tuple[str, str, str]:
    """``("کالی موٹر سائیکل", "kaali bike", "black motorcycle")``."""
    ur, roman, en, gender = _OBJECTS.get(
        obj_type or "", (obj_type or "چیز", obj_type or "cheez", obj_type or "object", "f")
    )
    if color and color in _COLORS:
        c_ur_f, c_ur_m, c_ro_f, c_ro_m, c_en = _COLORS[color]
        c_ur, c_ro = (c_ur_f, c_ro_f) if gender == "f" else (c_ur_m, c_ro_m)
        return f"{c_ur} {ur}", f"{c_ro} {roman}", f"{c_en} {en}"
    return ur, roman, en


def confidence_words(p_value: float | None, raw_score: float | None = None) -> tuple[str, str, str]:
    if p_value is None:
        s = raw_score or 0.0
        p_value = 0.005 if s >= 0.8 else 0.03 if s >= 0.6 else 0.2
    if p_value <= 0.001:
        return "بہت زیادہ", "bohat zyada", "very high"
    if p_value <= 0.01:
        return "زیادہ", "zyada", "high"
    if p_value <= 0.05:
        return "درمیانہ", "darmiyana", "medium"
    return "کم", "kam", "low"


def _pct(p: float) -> str:
    pct = p * 100.0
    if pct < 0.1:
        return "0.1%"
    if pct < 1:
        return f"{pct:.1f}%"
    return f"{pct:.0f}%"


# F16: the p-value compares against the calibration set of the day's mode
MODE_DAYS: dict[str, tuple[str, str, str]] = {
    "ramadan": ("رمضان کے دنوں میں", "Ramzan ke dinon mein", "Ramadan"),
    "chand_raat": ("چاند رات کو", "Chand Raat ko", "Chand Raat"),
    "eid": ("عید کے دنوں میں", "Eid ke dinon mein", "Eid"),
    "muharram": ("محرم کے دنوں میں", "Muharram ke dinon mein", "Muharram"),
    "independence_day": ("14 اگست کو", "14 August ko", "14 August"),
    "bazaar_day": ("بازار کے دن", "bazaar ke din", "market-day"),
}


def pvalue_text(p_value: float | None, mode: str = "normal") -> tuple[str, str, str] | None:
    """Plain-language conformal p-value (Section 12.1 "kyun?" panel). ``mode`` is the mode whose
    calibration set produced the p-value (F16)."""
    if p_value is None:
        return None
    if mode in MODE_DAYS:
        ur, roman, en = MODE_DAYS[mode]
        if p_value > 0.2:
            return (
                f"ایسا پیٹرن {ur} بھی اکثر ہوتا ہے",
                f"Aisa pattern {roman} bhi aksar hota hai",
                f"A pattern like this is common in {en} activity",
            )
        pct = _pct(p_value)
        return (
            f"ایسا پیٹرن {ur} {pct} سے کم ہوتا ہے",
            f"Is jaisa pattern {roman} {pct} se kam hota hai",
            f"A pattern like this happens in less than {pct} of {en} activity",
        )
    if p_value > 0.2:
        return (
            "ایسا پیٹرن عام دنوں میں بھی اکثر ہوتا ہے",
            "Aisa pattern aam dinon mein bhi aksar hota hai",
            "A pattern like this is common on normal days",
        )
    pct = _pct(p_value)
    return (
        f"ایسا پیٹرن عام دنوں میں {pct} سے کم ہوتا ہے",
        f"Is jaisa pattern aam dinon mein {pct} se kam hota hai",
        f"A pattern like this happens in less than {pct} of normal activity",
    )


def _people(n: int) -> tuple[str, str, str]:
    if n <= 1:
        return "ایک فرد", "ek fard", "one person"
    return f"{n} افراد", f"{n} afraad", f"{n} people"


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _loitering(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    passes = int(f.get("passes", f.get("passes_15m", 0)) or 0)
    window = int(f.get("window_min", 15) or 15)
    riders = int(f.get("riders", 1) or 1)
    slow = int(f.get("slowdowns_near_ped", 0) or 0)
    dwell_min = int(float(f.get("dwell_s", 0) or 0) // 60)
    o_ur, o_ro, o_en = object_names(str(f.get("vehicle", "motorcycle")), f.get("color"))
    p_ur, p_ro, p_en = _people(riders)
    verb_ur = "گزرا" if riders <= 1 else "گزرے"
    if f.get("cross_camera"):  # F2 Tier 2: one bike's route across several cameras
        n_cams = len(f.get("cameras") or []) or 2
        return Explanation(
            ur=f"{cam.ur} پر {t} بجے: {p_ur} {o_ur} پر {window} منٹ میں {n_cams} کیمروں کے درمیان {passes} چکر لگا چکے؛ یہ راستہ عام دنوں جیسا نہیں۔ اعتماد: {conf[0]}۔",
            roman=f"{cam.roman} par {t} baje: {p_ro} {o_ro} par {window} min mein {n_cams} cameras ke darmiyan {passes} chakkar laga chuke; ye raasta aam dinon jaisa nahi. Etimad: {conf[1]}.",
            en=f"{t} at {cam.en}: {p_en} on a {o_en} made {passes} passes across {n_cams} cameras in {window} min; an unusual route for this site. Confidence: {conf[2]}.",
        )
    extra_ur = extra_ro = extra_en = ""
    if slow:
        extra_ur += f"؛ {slow} بار پیدل شخص کے قریب آہستہ ہوئے"
        extra_ro += f"; {slow} baar paidal ke qareeb aahista hue"
        extra_en += f"; slowed down near a pedestrian {slow} time(s)"
    if dwell_min >= 1:
        extra_ur += f"؛ {dwell_min} منٹ تک رکے"
        extra_ro += f"; {dwell_min} min tak ruke"
        extra_en += f"; stayed for {dwell_min} min"
    return Explanation(
        ur=f"{cam.ur} پر {t} بجے: {p_ur} {o_ur} پر {window} منٹ میں {passes} مرتبہ {verb_ur}{extra_ur}۔ اعتماد: {conf[0]}۔",
        roman=f"{cam.roman} par {t} baje: {p_ro} {o_ro} par {window} min mein {passes} martaba guzre{extra_ro}. Etimad: {conf[1]}.",
        en=f"{t} at {cam.en}: {p_en} on a {o_en} passed {passes} times in {window} min{extra_en}. Confidence: {conf[2]}.",
    )


def _context(f: Mapping[str, Any]) -> tuple[str, str, str]:
    """Night and an empty street: why it matters more (person-safety alerts)."""
    night, alone = bool(f.get("night")), bool(f.get("alone"))
    if night and alone:
        return (
            "؛ رات کا وقت ہے اور آس پاس کوئی نہیں",
            "; raat ka waqt hai aur aas paas koi nahi",
            "; it is night and nobody else is around",
        )
    if night:
        return "؛ رات کا وقت ہے", "; raat ka waqt hai", "; it is night"
    if alone:
        return "؛ آس پاس کوئی نہیں", "; aas paas koi nahi", "; nobody else is around"
    return "", "", ""


def _secs(s: Any) -> tuple[str, str, str]:
    n = round(float(s or 0))
    if n < 90:
        return f"{n} سیکنڈ", f"{n} second", f"{n} s"
    m = round(n / 60)
    return f"{m} منٹ", f"{m} min", f"{m} min"


def _snatch(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    if f.get("on_foot"):
        c_ur, c_ro, c_en = _context(f)
        ph_ur, ph_ro, ph_en = (
            (" (جو فون پر بات کر رہا تھا)", " (jo phone par baat kar raha tha)", " who was on the phone")
            if f.get("item") == "phone"
            else ("", "", "")
        )
        return Explanation(
            ur=(
                f"{cam.ur} پر {t} بجے: ایک شخص پیدل ایک راہگیر{ph_ur} کے بالکل قریب آیا، ہاتھ کی تیز حرکت ہوئی "
                f"اور پھر وہ بھاگ کر دور چلا گیا{c_ur}۔ فوراً جانچ کریں۔ اعتماد: {conf[0]}۔"
            ),
            roman=(
                f"{cam.roman} par {t} baje: ek shakhs paidal ek raahgeer{ph_ro} ke bilkul qareeb aaya, haath ki tez "
                f"harkat hui aur phir woh bhaag kar door chala gaya{c_ro}. Foran jaanch karein. Etimad: {conf[1]}."
            ),
            en=(
                f"{t} at {cam.en}: someone on foot came right up to a pedestrian{ph_en}, a fast hand movement was "
                f"seen, then they ran off{c_en}. Check immediately. Confidence: {conf[2]}."
            ),
        )
    riders = int(f.get("riders", 2) or 2)
    o_ur, o_ro, o_en = object_names(str(f.get("vehicle", "motorcycle")), f.get("color"))
    p_ur, p_ro, p_en = _people(riders)
    return Explanation(
        ur=(
            f"{cam.ur} پر {t} بجے: {o_ur} پر سوار {p_ur} ایک پیدل شخص کے بالکل قریب آئے، "
            f"ہاتھ کی تیز حرکت ہوئی اور پھر تیزی سے دور چلے گئے۔ فوراً جانچ کریں۔ اعتماد: {conf[0]}۔"
        ),
        roman=(
            f"{cam.roman} par {t} baje: {o_ro} par {p_ro} paidal shakhs ke bilkul qareeb aaye, "
            f"haath ki tez harkat hui aur phir tezi se door gaye. Foran jaanch karein. Etimad: {conf[1]}."
        ),
        en=(
            f"{t} at {cam.en}: {p_en} on a {o_en} came very close to a pedestrian, a fast hand "
            f"movement was seen, then they sped away. Check immediately. Confidence: {conf[2]}."
        ),
    )


def _tamper(cam: CameraNames, t: str, f: Mapping[str, Any]) -> Explanation:
    ur, ro, en = _TAMPER.get(str(f.get("check", "offline")), _TAMPER["offline"])
    return Explanation(
        ur=f"{cam.ur} پر {t} بجے: {ur}۔ کیمرہ فوراً چیک کریں۔",
        roman=f"{cam.roman} par {t} baje: {ro}. Camera foran check karein.",
        en=f"{t} at {cam.en}: {en}. Check the camera now.",
    )


def _rule(cam: CameraNames, t: str, f: Mapping[str, Any]) -> Explanation:
    name_ur = str(f.get("rule_name_ur") or f.get("rule_id") or "قاعدہ")
    name_en = str(f.get("rule_name_en") or f.get("rule_id") or "rule")
    o_ur, o_ro, o_en = object_names(str(f.get("object", "person")))
    if f.get("dwell_s") is not None:
        mins = max(1, round(float(f["dwell_s"]) / 60))
        d_ur, d_ro, d_en = (
            f"{o_ur} {mins} منٹ سے رکا ہوا ہے",
            f"{o_ro} {mins} min se ruka hua hai",
            f"{o_en} has stayed for {mins} min",
        )
    else:
        n = int(f.get("count", 0) or 0)
        d_ur, d_ro, d_en = f"{n} {o_ur} موجود", f"{n} {o_ro} maujood", f"{n} x {o_en} present"
    return Explanation(
        ur=f"{cam.ur} پر {t} بجے: قاعدہ «{name_ur}» لاگو ہوا ({d_ur})۔",
        roman=f"{cam.roman} par {t} baje: rule '{f.get('rule_name_roman') or name_en}' laga ({d_ro}).",
        en=f"{t} at {cam.en}: rule '{name_en}' triggered ({d_en}).",
    )


def _sos(cam: CameraNames, t: str) -> Explanation:
    return Explanation(
        ur=f"{cam.ur} سے {t} بجے SOS: گارڈ نے فوری مدد مانگی ہے۔ فوراً رابطہ کریں۔",
        roman=f"{cam.roman} se {t} baje SOS: guard ne foran madad maangi hai. Foran rabta karein.",
        en=f"SOS from {cam.en} at {t}: the guard asked for immediate help. Respond now.",
    )


def _network(cam: CameraNames, t: str, f: Mapping[str, Any]) -> Explanation:
    """F21: no accusation, no instruction to act - the guard watches and reports."""
    riders = int(f.get("riders", 1) or 1)
    o_ur, o_ro, o_en = object_names(str(f.get("vehicle", "motorcycle")), f.get("color"))
    p_ur, p_ro, p_en = _people(riders)
    km = float(f.get("distance_km", 1.0) or 1.0)
    return Explanation(
        ur=(
            f"{cam.ur} پر {t} بجے: قریبی علاقے (تقریباً {km:.1f} کلومیٹر) کی تصدیق شدہ واردات والی بائیک جیسی "
            f"{o_ur} ({p_ur}) یہاں دیکھی گئی۔ صرف نظر رکھیں اور سپروائزر کو بتائیں، خود کارروائی نہ کریں۔"
        ),
        roman=(
            f"{cam.roman} par {t} baje: qareebi ilaqe (taqreeban {km:.1f} km) ki tasdeeq shuda wardaat wali bike jaisi "
            f"{o_ro} ({p_ro}) yahan dekhi gayi. Sirf nazar rakhein aur supervisor ko batayein, khud karwai na karein."
        ),
        en=(
            f"{t} at {cam.en}: a {o_en} ({p_en}) like the bike in a confirmed incident at a neighbouring site "
            f"(about {km:.1f} km away) was seen here. Watch and tell the supervisor; do not act on your own."
        ),
    )


def _audio(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    kind = str(f.get("sound", "loud sound"))
    names = {
        "firing": ("فائرنگ جیسی آواز", "firing jaisi awaaz", "a gunshot-like sound"),
        "scream": ("چیخ کی آواز", "cheekh ki awaaz", "a scream"),
        "glass_break": ("شیشہ ٹوٹنے کی آواز", "sheesha tootne ki awaaz", "glass breaking"),
    }
    ur, ro, en = names.get(kind, ("تیز آواز", "tez awaaz", "a loud sound"))
    return Explanation(
        ur=f"{cam.ur} کے پاس {t} بجے {ur} سنی گئی۔ جانچ کریں۔ اعتماد: {conf[0]}۔",
        roman=f"{cam.roman} ke paas {t} baje {ro} suni gayi. Jaanch karein. Etimad: {conf[1]}.",
        en=f"{en.capitalize()} was heard near {cam.en} at {t}. Please check. Confidence: {conf[2]}.",
    )


def _danger(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    """Person in danger: what was seen, in plain words, and what to do. Never who anyone is."""
    pattern = str(f.get("pattern") or "")
    c_ur, c_ro, c_en = _context(f)
    head_ur, head_ro, head_en = f"{cam.ur} پر {t} بجے: ", f"{cam.roman} par {t} baje: ", f"{t} at {cam.en}: "
    go_ur, go_ro, go_en = "فوراً جا کر جانچ کریں", "Foran ja kar jaanch karein", "Go and check now"
    if pattern == "following":
        d_ur, d_ro, d_en = _secs(f.get("follow_s"))
        n = int(f.get("stops_matched", 0) or 0)
        what = (
            f"ایک شخص {d_ur} سے ایک راہگیر کے کچھ قدم پیچھے چل رہا ہے؛ وہ رکتا ہے تو یہ بھی رک جاتا ہے ({n} بار)",
            f"ek shakhs {d_ro} se ek raahgeer ke kuch qadam peeche chal raha hai; woh rukta hai to ye bhi ruk jata hai ({n} baar)",
            f"someone has kept a few steps behind a pedestrian for {d_en}, stopping when they stop ({n} times)",
        )
        go_ur, go_ro, go_en = (
            "نظر رکھیں اور قریب جا کر خیریت معلوم کریں",
            "Nazar rakhein aur qareeb ja kar khairiyat maloom karein",
            "Keep watch and go over to check they are all right",
        )
    elif pattern == "surrounded":
        n = int(f.get("people_around", 3) or 3)
        d_ur, d_ro, d_en = _secs(f.get("duration_s"))
        what = (
            f"{n} افراد نے ایک شخص کو چاروں طرف سے گھیر رکھا ہے ({d_ur} سے)",
            f"{n} afraad ne ek shakhs ko chaaron taraf se gher rakha hai ({d_ro} se)",
            f"{n} people have closed in around one person from all sides (for {d_en})",
        )
    elif pattern == "struggle":
        d_ur, d_ro, d_en = _secs(f.get("struggle_s"))
        what = (
            f"دو افراد کے درمیان ہاتھا پائی یا زور زبردستی جیسی حرکت ({d_ur})",
            f"do afraad ke darmiyan haathapai ya zor zabardasti jaisi harkat ({d_ro})",
            f"two people pushing and pulling each other, like a struggle or a fight ({d_en})",
        )
    elif pattern == "dragged":
        d_ur, d_ro, d_en = _secs(f.get("dragged_s"))
        what = (
            f"ایک شخص کو کوئی زبردستی ساتھ کھینچ کر لے جا رہا ہے ({d_ur})",
            f"ek shakhs ko koi zabardasti saath kheench kar le ja raha hai ({d_ro})",
            f"someone is being pulled along against their will ({d_en})",
        )
    elif pattern == "forced_into_vehicle":
        o_ur, o_ro, o_en = object_names(str(f.get("vehicle") or "car"))
        gender = _OBJECTS.get(str(f.get("vehicle") or "car"), ("", "", "", "f"))[3]
        went_ur, went_ro = ("چلی گئی", "chali gayi") if gender == "f" else ("چلا گیا", "chala gaya")
        what = (
            f"ہاتھا پائی کے بعد ایک شخص کو {o_ur} میں بٹھایا گیا اور {o_ur} فوراً {went_ur}",
            f"haathapai ke baad ek shakhs ko {o_ro} mein bithaya gaya aur {o_ro} foran {went_ro}",
            f"after a struggle, a person was put into a {o_en} that drove off at once",
        )
        go_ur, go_ro, go_en = (
            "فوراً سپروائزر کو بتائیں اور ضرورت ہو تو 15 پر کال کریں",
            "Foran supervisor ko batayein aur zaroorat ho to 15 par call karein",
            "Tell the supervisor now and call 15 if needed",
        )
    elif pattern == "fall":
        d_ur, d_ro, d_en = _secs(f.get("down_s"))
        if f.get("sudden"):
            what = (
                f"ایک شخص اچانک گر گیا اور {d_ur} سے اٹھا نہیں",
                f"ek shakhs achanak gir gaya aur {d_ro} se utha nahi",
                f"a person suddenly fell and has not got up for {d_en}",
            )
        else:
            what = (
                f"ایک شخص {d_ur} سے زمین پر پڑا ہے",
                f"ek shakhs {d_ro} se zameen par para hai",
                f"a person has been lying on the ground for {d_en}",
            )
        if f.get("after_contact"):
            what = (
                what[0] + "؛ گرنے سے پہلے کوئی ان کے بالکل قریب تھا",
                what[1] + "; girne se pehle koi un ke bilkul qareeb tha",
                what[2] + "; someone was right next to them just before",
            )
        go_ur, go_ro, go_en = "فوراً مدد کے لیے جائیں", "Foran madad ke liye jaayein", "Go and help now"
    else:
        what = ("کسی کو خطرہ ہو سکتا ہے", "kisi ko khatra ho sakta hai", "someone may be in danger")
    return Explanation(
        ur=f"{head_ur}{what[0]}{c_ur}۔ {go_ur}۔ اعتماد: {conf[0]}۔",
        roman=f"{head_ro}{what[1]}{c_ro}. {go_ro}. Etimad: {conf[1]}.",
        en=f"{head_en}{what[2]}{c_en}. {go_en}. Confidence: {conf[2]}.",
    )


def _theft(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    """A parked bike taken after a long time at it: the guard checks whether it is the owner."""
    o_ur, o_ro, o_en = object_names(str(f.get("vehicle") or "motorcycle"), f.get("color"))
    d_ur, d_ro, d_en = _secs(f.get("tamper_s"))
    if f.get("pushed"):
        v_ur, v_ro, v_en = "اسے دھکیل کر لے گیا", "use dhakel kar le gaya", "pushed it away"
    else:
        v_ur, v_ro, v_en = "اسے چلا کر لے گیا", "use chala kar le gaya", "rode off on it"
    a_ur = a_ro = a_en = ""
    if f.get("accomplice"):
        a_ur, a_ro, a_en = (
            "؛ قریب ایک اور بائیک انتظار کر رہی تھی",
            "; qareeb ek aur bike intezar kar rahi thi",
            "; another bike was waiting nearby",
        )
    return Explanation(
        ur=f"{cam.ur} پر {t} بجے: کھڑی ہوئی {o_ur} کے پاس ایک شخص {d_ur} تک جھک کر کچھ کرتا رہا، پھر {v_ur}{a_ur}۔ دیکھیں کہ یہ مالک ہی ہے۔ اعتماد: {conf[0]}۔",
        roman=f"{cam.roman} par {t} baje: khari hui {o_ro} ke paas ek shakhs {d_ro} tak jhuk kar kuch karta raha, phir {v_ro}{a_ro}. Dekhein ke ye malik hi hai. Etimad: {conf[1]}.",
        en=f"{t} at {cam.en}: someone spent {d_en} bent over a parked {o_en}, then {v_en}{a_en}. Check whether it is the owner. Confidence: {conf[2]}.",
    )


def _crowd(cam: CameraNames, t: str, f: Mapping[str, Any], conf: tuple[str, str, str]) -> Explanation:
    n = int(f.get("runners", 0) or 0)
    h_ur = h_ro = h_en = ""
    if f.get("heard") == "firing":
        h_ur, h_ro, h_en = (
            "؛ فائرنگ جیسی آواز بھی سنی گئی",
            "; firing jaisi awaaz bhi suni gayi",
            "; a gunshot-like sound was heard too",
        )
    elif f.get("heard") == "scream":
        h_ur, h_ro, h_en = "؛ چیخ کی آواز بھی سنی گئی", "; cheekh ki awaaz bhi suni gayi", "; a scream was heard too"
    return Explanation(
        ur=f"{cam.ur} پر {t} بجے: {n} لوگ اچانک ایک جگہ سے مختلف سمتوں میں بھاگنے لگے (بھگدڑ){h_ur}۔ فوراً جانچ کریں۔ اعتماد: {conf[0]}۔",
        roman=f"{cam.roman} par {t} baje: {n} log achanak ek jagah se mukhtalif simt mein bhaagne lage (bhagdar){h_ro}. Foran jaanch karein. Etimad: {conf[1]}.",
        en=f"{t} at {cam.en}: {n} people suddenly ran away from one spot in different directions{h_en}. Check now. Confidence: {conf[2]}.",
    )


def explain_alert(
    alert_type: str,
    features: Mapping[str, Any],
    camera: CameraNames,
    local_time: datetime,
    p_value: float | None = None,
    raw_score: float | None = None,
) -> Explanation:
    t = _hhmm(local_time)
    conf = confidence_words(p_value, raw_score)
    if alert_type == "loitering":
        return _loitering(camera, t, features, conf)
    if alert_type == "snatch":
        return _snatch(camera, t, features, conf)
    if alert_type == "camera_tamper":
        return _tamper(camera, t, features)
    if alert_type == "rule":
        return _rule(camera, t, features)
    if alert_type == "sos":
        return _sos(camera, t)
    if alert_type == "audio_event":
        return _audio(camera, t, features, conf)
    if alert_type == "network_match":
        return _network(camera, t, features)
    if alert_type == "person_in_danger":
        return _danger(camera, t, features, conf)
    if alert_type == "vehicle_theft":
        return _theft(camera, t, features, conf)
    if alert_type == "crowd_panic":
        return _crowd(camera, t, features, conf)
    return Explanation(
        ur=f"{camera.ur} پر {t} بجے مشکوک حرکت۔ جانچ کریں۔",
        roman=f"{camera.roman} par {t} baje mashkook harkat. Jaanch karein.",
        en=f"Suspicious activity at {camera.en} at {t}. Please check.",
    )


# Words that must never appear in an explanation (explanation audit, Section 14.5)
FORBIDDEN_WORDS: frozenset[str] = frozenset({"chor", "چور", "thief", "criminal", "mujrim", "مجرم", "dakoo", "ڈاکو"})


def is_neutral(text: str) -> bool:
    words = {w for w in re.split(r"[^\w]+", text.lower()) if w}
    return words.isdisjoint(FORBIDDEN_WORDS)
