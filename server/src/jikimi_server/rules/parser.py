"""Roman Urdu -> rule DSL (F11, plan Section 8.11): deterministic and explainable.

    "raat 11 ke baad gate 2 par koi 5 min se zyada ruke to batao"
      -> every day 23:00-05:00, zone gate-2, person, dwell > 300 s; alert medium -> guard

Unclear text never becomes a guessed rule: the parser asks instead (plan: "galat ya ambiguous
rule -> clarification question, guess nahi"). Zones and cameras must exist on the site, so a
rule can never point at something the edge does not know. An LLM can sit behind the same
output (``RuleDraft``) for free-form wording.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from jikimi_contracts.rules_dsl import ALL_DAYS, Rule, RuleDraft
from pydantic import ValidationError

from ..search import lexicon as L
from ..search.normalize import tokenize
from ..search.parser import SiteVocab

_DAY_PART = L.canonical(L.DAY_PART_WORDS)
_PLACE = L.canonical(L.PLACE_WORDS)
_VEHICLE = L.canonical(L.VEHICLES)
_COLOR = L.canonical(L.COLORS)
_PERSON = set(L.PERSON_WORDS)  # counted nouns: "3 se zyada log"
_CAMERA = {"camera", "kamera", "camra", "kamra", "cam", "کیمرہ", "کیمرا"}
_CLOCK = set(L.CLOCK_WORDS)
_AFTER = set(L.AFTER_WORDS)
_BEFORE = set(L.BEFORE_WORDS)
_SE = {"se", "sy", "سے"}
_NUMBER_WORD = {"no", "number", "nambar", "نمبر"}  # "gate number 2"
_UNTIL = {"tak", "tk", "until", "till", "تک"}
_MORE = {"zyada", "ziada", "zayada", "zyda", "zaida", "more", "upar", "زیادہ"}
_LESS = {"kam", "less", "کم"}
_FILLER = _SE | {"ke", "ka", "ki", "کے"}
_DWELL = {
    "ruke", "rukay", "ruka", "rukey", "ruki", "rukna", "rukta", "ruk", "khara", "khade", "khare", "khari",
    "kharay", "baitha", "baithe", "baithay", "dwell", "stay", "stays", "rahe", "rahay", "rahein", "der",
    "رکے", "رکا", "کھڑا", "کھڑے", "کھڑی", "رہے", "دیر",
}  # fmt: skip
_UNIT_S = {"sec": 1, "second": 1, "seconds": 1, "سیکنڈ": 1} | {
    w: 60 if u == "minutes" else 3600 for w, u in L.UNITS.items() if u in ("minutes", "hours")
}
_HALF = {"aadha", "adha", "aadhe", "aadhi", "adhi", "آدھا", "آدھے", "آدھی"}
_URGENT = {"foran", "fauran", "fori", "fouran", "urgent", "zaroor", "zarur", "emergency", "فوراً", "فورا", "فوری"}
_SUPERVISOR = {"supervisor", "supervisr", "incharge", "سپروائزر"}
_OWNER = {"owner", "malik", "maalik", "admin", "مالک"}
_EVERYONE = {"sab", "sabko", "sabhi", "سب"}
_WEEKEND = {"weekend", "chutti", "چھٹی"}
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

_OBJ_UR = {
    "person": "کوئی شخص", "motorcycle": "موٹر سائیکل", "car": "گاڑی", "rickshaw": "رکشہ", "qingqi": "چنگچی",
    "loader_rickshaw": "لوڈر رکشہ", "bus": "بس", "truck": "ٹرک", "van": "وین", "bicycle": "سائیکل",
}  # fmt: skip
_COLOR_UR = {
    "black": "کالی", "white": "سفید", "red": "لال", "blue": "نیلی", "green": "سبز", "yellow": "پیلی",
    "gray": "سرمئی", "silver": "سلور", "brown": "بھوری", "orange": "نارنجی",
}  # fmt: skip


@dataclass
class _Clock:
    hour: int  # as written: 1..12 needs a day part; 0 and 13..23 are already 24 h
    minute: int
    idx: int


@dataclass
class _State:
    toks: list[str]
    used: set[int] = field(default_factory=set)  # tokens already read as a clock, zone or camera number
    questions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def at(self, i: int) -> str:
        return self.toks[i] if 0 <= i < len(self.toks) else ""


def _number(st: _State, i: int) -> int | None:
    """Digits, or a number word; weak words ("do", "no", ...) only before a unit or a counted noun."""
    t, nxt = st.at(i), st.at(i + 1)
    if t.isdigit():
        return int(t)
    n = L.NUMBERS.get(t)
    if (
        n is not None
        and t in L.WEAK_NUMBERS
        and not (nxt in _UNIT_S or nxt in _CLOCK or nxt in _PERSON or nxt in _VEHICLE or nxt in _SE)
    ):
        return None
    return n


def _part_at(toks: list[str], j: int) -> str | None:
    part = _DAY_PART.get(toks[j])
    if part == "raat" and j > 0 and toks[j - 1] in _HALF:
        return "aadhi_raat"
    return part


def _near_part(toks: list[str], idx: int) -> str | None:
    """Day part written next to a clock: "raat 11", "11 baje raat" (never across another number)."""
    for direction in (range(idx - 1, max(-1, idx - 4), -1), range(idx + 1, min(len(toks), idx + 4))):
        for j in direction:
            if toks[j].isdigit() or _HHMM.match(toks[j]):
                break
            if (part := _part_at(toks, j)) is not None:
                return part
    return None


def _to_24h(hour: int, part: str | None) -> int | None:
    """Clock hour + day part -> 0..23; ``None`` while ambiguous ("11 baje": subah ya raat?)."""
    if hour > 23:
        return None
    if hour == 0 or hour >= 13:
        return hour
    if part in ("raat", "aadhi_raat"):
        return hour + 12 if 6 <= hour <= 11 else (0 if hour == 12 else hour)
    if part in ("shaam", "sehpahar"):
        return hour if hour == 12 else hour + 12
    if part == "dopahar":
        return hour + 12 if hour <= 5 else hour
    if part == "subah":
        return hour
    return None


def _clock_at(st: _State, i: int) -> _Clock | None:
    if m := _HHMM.match(st.at(i)):
        return _Clock(int(m.group(1)), int(m.group(2)), i)
    n = _number(st, i)
    if n is None or not 0 <= n <= 23:
        return None
    nxt = st.at(i + 1)
    if nxt in _CLOCK:
        return _Clock(n, 0, i)  # "11 baje"
    if nxt in _UNIT_S or st.at(i + 2) in _UNIT_S:
        return None  # "5 min se zyada" is a duration
    if nxt in _UNTIL or any(w in _AFTER or w in _BEFORE for w in st.toks[i + 1 : i + 4]):
        return _Clock(n, 0, i)  # "5 tak", "11 ke baad", "6 se pehle"
    if nxt in _SE:
        for w in st.toks[i + 1 : i + 5]:
            if w.isdigit() or w in L.NUMBERS or _HHMM.match(w):
                return _Clock(n, 0, i)  # "11 se 5 tak"
            if w in _PERSON or w in _VEHICLE:
                return None  # "3 se zyada log" is a count
    return None


def _schedule(st: _State) -> dict[str, Any] | None:
    """Daily window from clock phrases, or a bare day part ("raat ko")."""
    toks = st.toks
    parts = {p for j in range(len(toks)) if (p := _part_at(toks, j)) is not None}
    clocks = [c for i in range(len(toks)) if (c := _clock_at(st, i)) is not None]
    st.used |= {c.idx for c in clocks}

    def hhmm(c: _Clock, after: str | None = None) -> str | None:
        own = _near_part(toks, c.idx)
        part = own or (next(iter(parts)) if len(parts) == 1 else None)
        h = _to_24h(c.hour, part)
        if own is None and after is not None and 1 <= c.hour <= 12:
            # "subah 9 se 5 tak" -> 17:00; "raat 11 se 5 tak" -> 05:00 (no later reading that day)
            later = [x for x in (c.hour % 12, c.hour % 12 + 12) if x * 60 + c.minute > int(after[:2]) * 60]
            h = later[0] if later else h
        if h is None:
            st.questions.append(f"{c.hour} baje subah ya raat? Maslan 'raat {c.hour} baje' likhein.")
            return None
        return f"{h:02d}:{c.minute:02d}"

    start = end = None
    if len(clocks) >= 2 and any(w in _SE for w in toks[clocks[0].idx + 1 : clocks[1].idx]):
        start = hhmm(clocks[0])
        end = hhmm(clocks[1], after=start)  # "11 se 5 tak"
    elif clocks:
        c = clocks[0]
        if any(w in _BEFORE for w in toks[c.idx + 1 : c.idx + 4]):
            start, end = "00:00", hhmm(c)  # "subah 6 se pehle"
        elif (start := hhmm(c)) is not None:
            h = int(start[:2])
            end = "05:00" if h >= 17 or h < 5 else "23:59"  # "raat 11 ke baad" = till morning
    elif len(parts) > 1:
        st.questions.append("Waqt saaf likhein, maslan 'raat 11 se subah 5 tak'.")
    elif parts:
        start, end = L.DAY_PARTS[next(iter(parts))]
    if start is None or end is None:
        return None
    days = [d for n, d in enumerate(ALL_DAYS) if any(L.WEEKDAYS.get(t) == n for t in toks)]
    if not days and any(t in _WEEKEND for t in toks):
        days = ["sat", "sun"]
    return {"days": days or list(ALL_DAYS), "from": start, "to": end}


def _places(st: _State, vocab: SiteVocab) -> tuple[list[str], list[str]]:
    """Zones/cameras named in the text; anything not on the site becomes a question."""
    zones: list[str] = []
    cameras: list[str] = []
    for i, t in enumerate(st.toks):
        k = i + 2 if st.at(i + 1) in _NUMBER_WORD else i + 1
        nxt = st.at(k)
        num = int(nxt) if nxt.isdigit() else (L.NUMBERS.get(nxt) if nxt not in L.WEAK_NUMBERS else None)
        if t in _CAMERA and num is not None:
            st.used.add(k)
            found = [c.id for c in vocab.cameras if c.number == num]
            if not found:
                known = ", ".join(c.id for c in vocab.cameras) or "-"
                st.questions.append(f"Camera {num} is site par nahi mila. Mojood cameras: {known}.")
            cameras += [c for c in found if c not in cameras]
        elif t in _PLACE:
            if num is not None:
                st.used.add(k)
            place = _PLACE[t]
            matches = [z for z in vocab.zones if place in z.words and (num is None or z.number == num)]
            if not matches:
                known = ", ".join(z.id for z in vocab.zones) or "-"
                label = t if num is None else f"{t} {num}"
                st.questions.append(f"'{label}' naam ka zone is site par nahi mila. Mojood zones: {known}.")
            elif len(matches) > 1:
                st.questions.append(f"Kaunsa {t}? " + " / ".join(z.id for z in matches))
            else:
                z = matches[0]
                zones += [z.id] if z.id not in zones else []
                cameras += [z.camera_id] if z.camera_id not in cameras else []
    return zones, cameras


def _duration_s(st: _State, i: int) -> int | None:
    """``5 min``, ``2 ghante``, ``aadha ghanta``, ``90 sec`` starting at token ``i``."""
    if st.at(i) in _HALF and st.at(i + 1) in _UNIT_S:
        return _UNIT_S[st.at(i + 1)] // 2
    n = _number(st, i)
    if n is None:
        return None
    for j in (i + 1, i + 2):  # "5 min", or one filler: "5 se zyada" is not a unit
        if st.at(j) in _UNIT_S:
            return n * _UNIT_S[st.at(j)]
        if st.at(j) not in _FILLER:
            break
    return None


def _count(st: _State, i: int) -> tuple[int, str] | None:
    """``3 se zyada log`` -> (3, person); ``4 ya zyada bikes`` -> (3, motorcycle); ``5 log`` -> (4, person).

    A negative count means "se kam" (fewer than), which the DSL does not support.
    """
    n = _number(st, i)
    if n is None:
        return None
    ahead: list[str] = []
    for w in st.toks[i + 1 : i + 5]:
        if w.isdigit() or w in _PLACE:
            break
        ahead.append(w)
    noun = next((w for w in ahead if w in _PERSON or w in _VEHICLE), None)
    if noun is None:
        return None
    obj = "person" if noun in _PERSON else _VEHICLE[noun]
    if any(w in _LESS for w in ahead):
        return (-1, obj)
    if any(w in _SE for w in ahead[:2]) and any(w in _MORE for w in ahead):
        return (n, obj)
    return (max(n - 1, 0), obj)  # "4 ya zyada", "5 log": at least n


def _dur_text(s: int) -> tuple[str, str]:
    if s % 3600 == 0:
        return f"{s // 3600} گھنٹے", f"{s // 3600} h"
    if s % 60 == 0:
        return f"{s // 60} منٹ", f"{s // 60} min"
    return f"{s} سیکنڈ", f"{s} s"


def _names(
    sched: dict[str, Any] | None, place: str, obj: str, color: str | None, dwell: int | None, count: int | None
) -> tuple[str, str]:
    if sched is None:
        when_ur, when_en = "ہر وقت", "any time"
    else:
        days = "" if len(sched["days"]) == 7 else " (" + ", ".join(sched["days"]) + ")"
        when_ur, when_en = f"{sched['from']} سے {sched['to']} تک{days}", f"{sched['from']}-{sched['to']}{days}"
    thing_ur = (_COLOR_UR[color] + " " if color in _COLOR_UR else "") + _OBJ_UR.get(obj, obj)
    thing_en = f"{color} {obj}" if color else obj
    d_ur, d_en = _dur_text(dwell) if dwell else ("", "")
    if count is not None:
        many_ur = "لوگ" if obj == "person" else thing_ur
        many_en = "people" if obj == "person" else f"{thing_en}s"
        ur = f"{count} سے زیادہ {many_ur}" + (f"، ہر ایک {d_ur} سے زیادہ" if dwell else " ایک ساتھ")
        en = f"more than {count} {many_en}" + (f", each staying > {d_en}" if dwell else " at once")
    else:
        ur, en = f"{thing_ur} {d_ur} سے زیادہ رکے", f"{thing_en} staying > {d_en}"
    return f"{when_ur}: {place} پر {ur}", f"{en} in {place}, {when_en}"


def _rule_id(core: dict[str, Any]) -> str:
    """Same meaning -> same id, so proposing a rule twice updates it instead of duplicating it."""
    digest = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:6]
    cond = core["condition"]
    what = "-".join(f"{k.split('_')[0]}{v}" for k, v in sorted(cond.items()))
    where = core["zone"] or "-".join(core["camera_ids"])
    base = re.sub(r"[^a-z0-9-]+", "-", f"{where}-{core['object']['type']}-{what}".lower()).strip("-")[:52]
    return f"r-{base}-{digest}"


def _friendly(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(x) for x in err["loc"])
    if "dwell_seconds_gt" in loc:
        return "Ruknay ka waqt kam az kam 10 second aur zyada se zyada 24 ghante ho sakta hai."
    if "count_gt" in loc:
        return "Ginti 0 se 500 ke darmiyan honi chahiye."
    return f"Rule durust nahi ({loc}): {err['msg']}"


def parse_rule(
    text: str, site_id: str, vocab: SiteVocab, created_by: str, labels: dict[str, str] | None = None
) -> RuleDraft:
    st = _State(tokenize(text))
    toks = st.toks
    sched = _schedule(st)
    asked = len(st.questions)
    zones, cameras = _places(st, vocab)
    place_asked = len(st.questions) > asked

    dwell_s: int | None = None
    count_gt: int | None = None
    obj: str | None = None
    for i in range(len(toks)):
        if i in st.used:
            continue
        if dwell_s is None and (d := _duration_s(st, i)) is not None:
            dwell_s = d
        elif count_gt is None and (c := _count(st, i)) is not None:
            if c[0] < 0:
                st.errors.append("'Se kam' wali shart abhi support nahi; 'se zyada' likhein.")
            else:
                count_gt, obj = c
    obj = obj or next((_VEHICLE[t] for t in toks if t in _VEHICLE), "person")
    color = next((_COLOR[t] for t in toks if t in _COLOR), None)
    severity = "high" if any(t in _URGENT for t in toks) else "medium"
    everyone = any(t in _EVERYONE for t in toks)
    notify = ["guard"]
    notify += ["supervisor"] if everyone or any(t in _SUPERVISOR for t in toks) else []
    notify += ["owner"] if everyone or any(t in _OWNER for t in toks) else []

    if not zones and not cameras and not place_asked:
        known = ", ".join(z.id for z in vocab.zones) or "-"
        st.questions.append(f"Kis jagah ke liye? Zone likhein ({known}), maslan 'gate 2 par'.")
    if len(zones) > 1:
        st.questions.append("Aik rule mein aik zone: " + " ya ".join(zones) + "?")
    if dwell_s is None and count_gt is None and not st.errors:
        if any(t in _DWELL for t in toks):
            st.questions.append("Kitni der? Maslan '5 min se zyada ruke'.")
        else:
            st.questions.append("Shart kya hai? Maslan '5 min se zyada ruke' ya '3 se zyada log'.")

    zone = zones[0] if zones else None
    names = labels or {}  # zone / camera id -> name shown in the Urdu rule name
    place = names.get(zone, zone) if zone else ", ".join(names.get(c, c) for c in cameras)
    understood: dict[str, Any] = {
        "schedule": sched,
        "zone": zone,
        "zone_label": place or None,
        "camera_ids": cameras,
        "object": obj,
        "color": color,
        "dwell_s": dwell_s,
        "count_gt": count_gt,
        "severity": severity,
        "notify": notify,
    }
    if st.questions or st.errors:
        return RuleDraft(valid=False, questions=st.questions, errors=st.errors, understood=understood)

    condition = {k: v for k, v in (("dwell_seconds_gt", dwell_s), ("count_gt", count_gt)) if v is not None}
    core = {
        "site_id": site_id,
        "schedule": sched,
        "camera_ids": cameras,
        "zone": zone,
        "object": {"type": obj, "color": color},
        "condition": condition,
        "severity": severity,
        "notify": notify,
    }
    name_ur, name_en = _names(sched, place, obj, color, dwell_s, count_gt)
    try:
        rule = Rule.model_validate(
            {
                "rule_id": _rule_id(core),
                "name_ur": name_ur,
                "name_en": name_en,
                "site_id": site_id,
                "when": {k: core[k] for k in ("schedule", "camera_ids", "zone", "object", "condition")},
                "then": {"alert": {"severity": severity, "notify": notify}},
                "created_by": created_by,
                "source_text": text.strip(),
            }
        )
    except ValidationError as exc:
        return RuleDraft(valid=False, errors=[_friendly(exc)], understood=understood)
    return RuleDraft(valid=True, rule=rule, understood=understood)
