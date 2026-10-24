"""Lexicon-first Roman Urdu / Urdu / English query parser (F1, ADR-012).

"kal raat kaali bike 2 sawar gate pe" ->
    time: yesterday 18:00 .. today 06:00, objects: [motorcycle, black, riders=2], zones: [gate-2]

Deterministic and fast on a 2-core CPU (< 5 ms). Only when coverage is low does the server
ask an LLM for structured output (``llm_fallback.py``), and even then time phrases are resolved
here, never by the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from jikimi_contracts.search import ObjectQuery, ParsedQuery, SearchIntent, TimeRange

from . import lexicon as L
from .normalize import fuzzy_lookup, tokenize
from .time_resolver import TimeSpec, resolve

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass
class ZoneEntry:
    id: str
    camera_id: str
    words: set[str]
    number: int | None


@dataclass
class CameraEntry:
    id: str
    words: set[str]
    number: int | None


@dataclass
class SiteVocab:
    cameras: list[CameraEntry] = field(default_factory=list)
    zones: list[ZoneEntry] = field(default_factory=list)

    @classmethod
    def build(cls, cameras: list[dict[str, object]]) -> SiteVocab:
        vocab = cls()
        for cam in cameras:
            cid = str(cam["id"])
            words = set(
                tokenize(
                    " ".join(str(cam.get(k) or "") for k in ("id", "name", "name_ur", "name_roman")).replace("-", " ")
                )
            )
            nums = [int(w) for w in words if w.isdigit()]
            vocab.cameras.append(CameraEntry(cid, words, nums[0] if nums else None))
            for z in cam.get("zones") or []:  # type: ignore[union-attr]
                zd = dict(z)  # type: ignore[call-overload]
                zw = set(tokenize(" ".join(str(zd.get(k) or "") for k in ("id", "name", "name_ur")).replace("-", " ")))
                zn = [int(w) for w in zw if w.isdigit()]
                vocab.zones.append(ZoneEntry(str(zd["id"]), cid, zw, zn[0] if zn else None))
        return vocab


def _num(tok: str) -> int | None:
    if tok.isdigit():
        return int(tok)
    return L.NUMBERS.get(tok)


_DAY_PART = L.canonical(L.DAY_PART_WORDS)
_COLOR = L.canonical(L.COLORS)
_VEHICLE = L.canonical(L.VEHICLES)
_PLACE = L.canonical(L.PLACE_WORDS)
_ALERT = L.canonical(L.ALERT_TYPE_WORDS)
_INTENT = L.canonical(L.INTENT_WORDS)
_PERSON = set(L.PERSON_WORDS)
_RIDER = set(L.RIDER_WORDS)
_HELMET = set(L.HELMET_WORDS)
_NEG = set(L.NEGATIONS)
_SINGLE = set(L.SINGLE_RIDING)
_DOUBLE = {w for w in L.DOUBLE_RIDING if " " not in w}
_CLOCK = set(L.CLOCK_WORDS)
_PAST = set(L.PAST_WORDS)
_AFTER = set(L.AFTER_WORDS)
_BEFORE = set(L.BEFORE_WORDS)
_NOW = set(L.NOW_WORDS)
_DEMOGRAPHIC = set(L.DEMOGRAPHIC_WORDS)
_CAMERA = {"camera", "kamera", "camra", "kamra", "cam", "کیمرہ", "کیمرا"}
_FUZZY_VOCAB = L.variants_index()

_NUM_EN = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
_TYPE_EN = {
    "motorcycle": "motorcycle",
    "car": "car",
    "rickshaw": "rickshaw",
    "qingqi": "qingqi",
    "loader_rickshaw": "loader rickshaw",
    "bus": "bus",
    "truck": "truck",
    "van": "van",
    "bicycle": "bicycle",
    "person": "person",
    "any": "vehicle",
}


class QueryParser:
    def parse(self, text: str, now: datetime, site: SiteVocab | None = None) -> ParsedQuery:
        toks = tokenize(text)
        spec = TimeSpec()
        objects: list[ObjectQuery] = []
        alert_types: list[str] = []
        intent = SearchIntent.FIND_CLIPS
        places: list[tuple[str, int | None]] = []
        cameras: list[str] = []
        unknown: list[str] = []
        notes: list[str] = []
        recognized = 0
        pending_color: str | None = None
        pending_riders: int | None = None
        pending_helmet: bool | None = None
        pending_people: int | None = None
        past = False

        def current() -> ObjectQuery | None:
            return objects[-1] if objects else None

        def vehicle_for_riders() -> ObjectQuery:
            for o in reversed(objects):
                if o.type in ("motorcycle", "bicycle", "any"):
                    if o.type == "any":
                        o.type = "motorcycle"
                    return o
            o = ObjectQuery(type="motorcycle", color=pending_color)
            objects.append(o)
            return o

        i = 0
        n = len(toks)
        while i < n:
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < n else ""
            nxt2 = toks[i + 2] if i + 2 < n else ""
            pair = f"{t} {nxt}"
            step = 1
            hit = True

            # ---- multi-word phrases -------------------------------------------------
            if pair in ("double sawari", "dabal sawari", "ڈبل سواری"):
                pending_riders = 2
                vehicle_for_riders().riders = 2
                step = 2
            elif pair in ("aadhi raat", "adhi raat", "آدھی رات"):
                spec.day_part = "aadhi_raat"
                spec.phrases.append(pair)
                step = 2
            elif pair in ("kahan kahan", "how many"):
                intent = SearchIntent.TRAJECTORY if pair == "kahan kahan" else SearchIntent.COUNT
                step = 2
            elif t in ("motor", "موٹر") and nxt in ("cycle", "saikal", "sycle", "saikil", "سائیکل"):
                o = ObjectQuery(type="motorcycle", color=pending_color, helmet=pending_helmet, riders=pending_riders)
                objects.append(o)
                pending_color = None
                step = 2
            elif t in _HELMET and (nxt in _NEG or (nxt in ("ke", "کے") and nxt2 in _NEG)):
                pending_helmet = False
                step = 2 if nxt in _NEG else 3
            elif t in _NEG and nxt in _HELMET:
                pending_helmet = False
                step = 2
            elif (m := _HHMM.match(t)) is not None:
                spec.clock = (int(m.group(1)), int(m.group(2)))
                spec.phrases.append(t)
            elif _num(t) is not None and (nxt in _CLOCK or (nxt in ("se",) and _num(nxt2) is not None)):
                h = _num(t) or 0
                if nxt in ("se",):
                    # "2 se 4 baje tak" / "2 se 4"
                    spec.clock, spec.clock_end = (h, 0), (_num(nxt2) or 0, 0)
                    step = 3
                    while i + step < n and toks[i + step] in _CLOCK | {"tak"}:
                        step += 1
                else:
                    spec.clock = (h, 0)
                    step = 2
                    if i + step < n and toks[i + step] in ("ke", "kay", "کے") and i + step + 1 < n:
                        follow = toks[i + step + 1]
                        if follow in _AFTER:
                            spec.after, step = True, step + 2
                        elif follow in _BEFORE:
                            spec.before, step = True, step + 2
                    elif (
                        i + step < n
                        and toks[i + step] in ("se", "سے")
                        and i + step + 1 < n
                        and toks[i + step + 1] in _BEFORE
                    ):
                        spec.before, step = True, step + 2
                spec.phrases.append(" ".join(toks[i : i + step]))
            elif (
                _num(t) is not None
                and nxt in ("ke", "kay", "کے")
                and nxt2 in _AFTER | _BEFORE
                and (spec.day_part or spec.day_offset is not None)
            ):
                spec.clock = (_num(t) or 0, 0)
                spec.after, spec.before = nxt2 in _AFTER, nxt2 in _BEFORE
                spec.phrases.append(f"{t} {nxt} {nxt2}")
                step = 3
            elif t in _PAST and (nxt in L.UNITS or (_num(nxt) is not None and nxt2 in L.UNITS)):
                if nxt in L.UNITS:
                    spec.last_amount, spec.last_unit, step = 1, L.UNITS[nxt], 2
                else:
                    spec.last_amount, spec.last_unit, step = float(_num(nxt) or 1), L.UNITS[nxt2], 3
                spec.phrases.append(" ".join(toks[i : i + step]))
            elif _num(t) is not None and nxt in L.UNITS and (past or nxt2 in _BEFORE):
                spec.last_amount, spec.last_unit = float(_num(t) or 1), L.UNITS[nxt]
                step = 3 if nxt2 in _BEFORE else 2
                spec.phrases.append(" ".join(toks[i : i + step]))
            elif t in _CAMERA and _num(nxt) is not None:
                num = _num(nxt)
                for cam in site.cameras if site else []:
                    if cam.number == num:
                        cameras.append(cam.id)
                step = 2
            elif t in _PLACE and (
                _num(nxt) is not None or (nxt in ("no", "number", "nambar", "نمبر") and _num(nxt2) is not None)
            ):
                num = _num(nxt) if _num(nxt) is not None and nxt not in ("no",) else _num(nxt2)
                places.append((_PLACE[t], num))
                step = 2 if (_num(nxt) is not None and nxt != "no") else 3
            elif _num(t) is not None and nxt in ("number", "nambar", "نمبر") and nxt2 in _PLACE:
                places.append((_PLACE[nxt2], _num(t)))
                step = 3
            # ---- counted nouns ----------------------------------------------------------
            elif _num(t) is not None and (nxt in _RIDER or nxt in _PERSON):
                count = _num(t) or 1
                if nxt in _RIDER or any(o.type in ("motorcycle", "bicycle") for o in objects):
                    vehicle_for_riders().riders = count
                else:
                    pending_riders = count  # "2 bande bike par": applied when the bike appears
                    pending_people = count
                step = 2
            elif _num(t) is not None and nxt in _VEHICLE:
                objects.append(ObjectQuery(type=_VEHICLE[nxt], color=pending_color, helmet=pending_helmet))
                pending_color = None
                step = 2
            elif _num(t) is not None and nxt in _ALERT and _ALERT[nxt] == "loitering":
                alert_types.append("loitering")
                notes.append(f"min_passes={_num(t)}")
                step = 2
            # ---- single words -----------------------------------------------------------
            elif t in L.STOPWORDS or (t in L.WEAK_NUMBERS and t not in _VEHICLE):
                hit = False
                recognized += 1
            elif t in _COLOR:
                cur = current()
                if cur is not None and cur.color is None and i > 0 and toks[i - 1] in _VEHICLE:
                    cur.color = _COLOR[t]  # "bike kaali"
                else:
                    pending_color = _COLOR[t]
            elif t in _VEHICLE:
                o = ObjectQuery(type=_VEHICLE[t], color=pending_color, helmet=pending_helmet)
                if pending_riders and o.type in ("motorcycle", "bicycle"):
                    o.riders = pending_riders
                objects.append(o)
                pending_color = None
            elif t in _RIDER:
                vehicle_for_riders().riders = vehicle_for_riders().riders or 1
            elif t in _DOUBLE:
                vehicle_for_riders().riders = 2
            elif t in _SINGLE:
                vehicle_for_riders().riders = 1
            elif t in _HELMET:
                pending_helmet = True if pending_helmet is None else pending_helmet
            elif t in _PERSON:
                if not any(o.type == "person" for o in objects) and not any(o.type == "motorcycle" for o in objects):
                    objects.append(ObjectQuery(type="person", color=pending_color))
                    pending_color = None
            elif t in _PLACE:
                places.append((_PLACE[t], None))
            elif t in L.DAY_REFS:
                spec.day_offset = L.DAY_REFS[t]
                spec.phrases.append(t)
            elif t in L.WEEKDAYS and not (t in ("hafta", "hafte") and (past or nxt in L.UNITS)):
                spec.weekday = L.WEEKDAYS[t]
                spec.phrases.append(t)
            elif t in _DAY_PART:
                spec.day_part = _DAY_PART[t]
                spec.phrases.append(t)
            elif t in _NOW:
                spec.now_window = True
                spec.phrases.append(t)
            elif t in _PAST:
                past = True
                if nxt in ("raat", "rat", "رات"):
                    spec.day_offset = 1 if spec.day_offset is None else spec.day_offset
            elif t in _ALERT:
                if _ALERT[t] not in alert_types:
                    alert_types.append(_ALERT[t])
            elif t in _INTENT:
                intent = SearchIntent(_INTENT[t])
            elif t in _DEMOGRAPHIC:
                notes.append("privacy: gender/age filters are not supported (no demographic inference)")
                if not any(o.type == "person" for o in objects):
                    objects.append(ObjectQuery(type="person"))
            elif t in _CAMERA:
                pass
            elif _num(t) is not None:
                hit = False  # a bare number we could not bind
                unknown.append(t)
            elif site is not None and any(t in c.words for c in site.cameras):
                cameras.extend(c.id for c in site.cameras if t in c.words and c.id not in cameras)
            else:
                fz = fuzzy_lookup(t, _FUZZY_VOCAB)
                if fz is not None:
                    toks[i] = fz[0]
                    continue  # re-run this position with the corrected spelling
                hit = False
                unknown.append(t)
            if hit:
                recognized += 1
            i += step

        # leftover adjectives without a noun: "kaali wali" -> any vehicle of that colour
        if pending_color is not None:
            target = next((o for o in objects if o.color is None and o.type != "person"), None)
            if target is not None:
                target.color = pending_color
            else:
                objects.append(ObjectQuery(type="any", color=pending_color))
        if pending_helmet is not None:
            for o in objects:
                if o.type in ("motorcycle", "bicycle", "any") and o.helmet is None:
                    o.helmet = pending_helmet
            if not objects:
                objects.append(ObjectQuery(type="motorcycle", helmet=pending_helmet))
        if pending_people is not None and not any(o.riders for o in objects):
            objects.append(ObjectQuery(type="person"))
            notes.append(f"people={pending_people}")

        start, end, default = resolve(spec, now)
        zones, zone_cams = self._resolve_places(places, site)
        cameras = list(dict.fromkeys(cameras + zone_cams))
        total = recognized + len(unknown)
        coverage = recognized / total if total else 1.0
        parsed = ParsedQuery(
            time_range=TimeRange(**{"from": start, "to": end}),
            time_phrase=" ".join(spec.phrases) or None,
            default_time_range=default,
            cameras=cameras,
            zones=zones,
            objects=objects,
            alert_types=alert_types,
            intent=intent,
            parser_path="lexicon",
            coverage=round(coverage, 3),
            unknown_tokens=unknown,
            notes=notes,
        )
        parsed.text_en = describe(parsed)
        return parsed

    @staticmethod
    def _resolve_places(places: list[tuple[str, int | None]], site: SiteVocab | None) -> tuple[list[str], list[str]]:
        zones: list[str] = []
        cams: list[str] = []
        if site is None:
            return [f"{p}-{n}" if n is not None else p for p, n in places], cams
        for place, num in places:
            matches = [z for z in site.zones if place in z.words and (num is None or z.number == num)]
            if not matches and num is not None:
                matches = [z for z in site.zones if place in z.words]
            zones.extend(z.id for z in matches if z.id not in zones)
            cam_matches = [c.id for c in site.cameras if place in c.words]
            for cid in [z.camera_id for z in matches] + cam_matches:
                if cid not in cams:
                    cams.append(cid)
        return zones, cams


def describe(p: ParsedQuery) -> str:
    """English description used for text embeddings (SigLIP) and in the UI."""
    parts = []
    for o in p.objects:
        noun = _TYPE_EN.get(o.type, o.type)
        desc = f"{o.color} {noun}" if o.color else noun
        if o.riders:
            who = f"{_NUM_EN.get(o.riders, str(o.riders))} {'person' if o.riders == 1 else 'people'}"
            desc = f"{who} on a {desc}"
        if o.helmet is False:
            desc += " without helmet"
        elif o.helmet is True:
            desc += " with helmet"
        parts.append(desc)
    if p.alert_types:
        parts.append("(" + ", ".join(p.alert_types) + ")")
    text = ", ".join(parts) or "any activity"
    if p.zones:
        text += " near " + ", ".join(p.zones)
    if p.time_phrase:
        text += f" [{p.time_phrase}]"
    return text
