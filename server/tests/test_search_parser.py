from datetime import datetime, timedelta

import pytest
from jikimi_common.timeutil import PK_TZ
from jikimi_server.search.parser import QueryParser, SiteVocab
from jikimi_server.search.time_resolver import TimeSpec, resolve

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=PK_TZ)
SITE = SiteVocab.build(
    [
        {
            "id": "cam-gate-01",
            "name": "Gate camera 1",
            "name_roman": "Gate-1",
            "zones": [{"id": "gate-2", "name": "Gate 2"}],
        },
        {
            "id": "cam-street-02",
            "name": "Market street camera 2",
            "zones": [{"id": "market-front", "name": "Market front"}],
        },
    ]
)
P = QueryParser()


def at(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 11, d, h, m, tzinfo=PK_TZ)


def test_plan_example() -> None:
    q = P.parse("kal raat kaali bike 2 sawar gate pe", NOW, SITE)
    assert q.time_range is not None
    assert (q.time_range.from_, q.time_range.to) == (at(21, 18), at(22, 6))
    assert [(o.type, o.color, o.riders) for o in q.objects] == [("motorcycle", "black", 2)]
    assert q.zones == ["gate-2"] and q.cameras == ["cam-gate-01"]
    assert q.coverage == 1.0 and q.parser_path == "lexicon"
    assert q.text_en.startswith("two people on a black motorcycle near gate-2")


@pytest.mark.parametrize(
    ("query", "color", "vehicle"),
    [
        ("kali baik", "black", "motorcycle"),
        ("kaaaali motorsycle", "black", "motorcycle"),
        ("laal gaari", "red", "car"),
        ("safaid chingchi", "white", "qingqi"),
        ("neeli honda", "blue", "motorcycle"),
        ("کالی موٹر سائیکل", "black", "motorcycle"),
        ("black bike", "black", "motorcycle"),
        ("motorsycl kaali", "black", "motorcycle"),
    ],
)
def test_spelling_variants(query: str, color: str, vehicle: str) -> None:
    q = P.parse(query, NOW, SITE)
    assert [(o.type, o.color) for o in q.objects] == [(vehicle, color)], query


@pytest.mark.parametrize(
    ("query", "riders", "helmet"),
    [
        ("do sawar bike", 2, None),
        ("double sawari", 2, None),
        ("bike par 2 bande", 2, None),
        ("2 bande bike par", 2, None),
        ("akela banda bike pe", 1, None),
        ("bike helmet nahi", None, False),
        ("bina helmet ke bike", None, False),
        ("helmet ke baghair 2 sawar", 2, False),
        ("دو سوار بغیر ہیلمٹ", 2, False),
    ],
)
def test_riders_and_helmet(query: str, riders: int | None, helmet: bool | None) -> None:
    q = P.parse(query, NOW, SITE)
    bike = next(o for o in q.objects if o.type == "motorcycle")
    assert (bike.riders, bike.helmet) == (riders, helmet), query


@pytest.mark.parametrize(
    ("query", "start", "end"),
    [
        ("aaj subah", at(22, 5), at(22, 12)),
        ("kal", at(21, 0), at(22, 0)),
        ("parson shaam", at(20, 17), at(20, 20)),
        ("raat", at(21, 18), at(22, 6)),
        ("pichli raat", at(21, 18), at(22, 6)),
        ("raat 11 baje ke baad", at(21, 23), at(22, 6)),
        ("kal raat 2 baje", at(22, 1, 30), at(22, 2, 30)),
        ("23:30", at(21, 23), at(22, 0)),
        ("pichle 2 ghante", NOW - timedelta(hours=2), NOW),
        ("abhi", NOW - timedelta(minutes=15), NOW),
        ("dopahar 2 se 4 baje tak", at(21, 14), at(21, 16)),
    ],
)
def test_time_phrases(query: str, start: datetime, end: datetime) -> None:
    q = P.parse(query, NOW, SITE)
    assert q.time_range is not None
    assert (q.time_range.from_, q.time_range.to) == (start, end), query


def test_default_range_is_flagged() -> None:
    q = P.parse("kaali bike", NOW, SITE)
    assert q.default_time_range and q.time_range is not None
    assert q.time_range.to - q.time_range.from_ == timedelta(days=7)


def test_alert_types_intent_and_privacy() -> None:
    q = P.parse("kal chheena jhapti wali clips dikhao", NOW, SITE)
    assert q.alert_types == ["snatch"]
    assert P.parse("gate 2 par kitni bikes", NOW, SITE).intent.value == "count"
    q = P.parse("aurat paidal market", NOW, SITE)
    assert any("privacy" in n for n in q.notes)
    assert q.zones == ["market-front"]


def test_weekday_and_unknown_words() -> None:
    q = P.parse("juma ko xyzzy bike", NOW, SITE)  # 2026-11-22 is a Sunday
    assert q.time_range is not None and q.time_range.from_ == at(20, 0)
    assert q.unknown_tokens == ["xyzzy"] and q.coverage < 1


def test_resolve_raat_during_the_night() -> None:
    late = datetime(2026, 11, 22, 23, 15, tzinfo=PK_TZ)
    start, end, _ = resolve(TimeSpec(day_part="raat"), late)
    assert (start, end) == (at(22, 18), at(23, 6))
