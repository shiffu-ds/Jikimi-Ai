from datetime import UTC, date, datetime
from datetime import time as dtime
from uuid import UUID

import pytest
from jikimi_common.config import deep_merge, resolve_env_refs
from jikimi_common.explain import CameraNames, explain_alert, is_neutral, pvalue_text
from jikimi_common.ids import clip_id_for, evidence_id, short_code, uuid7, uuid7_time_ms
from jikimi_common.intents import reply_intent
from jikimi_common.timeutil import PK_TZ, in_daily_window


class TestIds:
    def test_uuid7_is_version_7_and_time_ordered(self) -> None:
        ids = [uuid7() for _ in range(2000)]
        assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
        assert ids == sorted(ids)  # monotonic even within one millisecond
        assert len(set(ids)) == len(ids)
        assert abs(uuid7_time_ms(ids[0]) - datetime.now(UTC).timestamp() * 1000) < 5000

    def test_codes(self) -> None:
        u = UUID("0192f3a4-7c1e-7b2a-9f10-3c5d6e7fa7f2")
        assert short_code(u) == "A7F2"
        assert evidence_id(date(2026, 10, 22), 7) == "EV-2026-10-22-0007"
        assert clip_id_for(u, datetime(2026, 11, 21, tzinfo=PK_TZ)) == "CL-2026-11-21-6E7FA7F2"


def test_daily_window_crosses_midnight() -> None:
    start, end = dtime(23, 0), dtime(5, 0)
    assert in_daily_window(dtime(23, 30), start, end)
    assert in_daily_window(dtime(2, 0), start, end)
    assert not in_daily_window(dtime(12, 0), start, end)
    assert in_daily_window(dtime(9, 0), dtime(8, 0), dtime(17, 0))


def test_env_refs_keep_secrets_out_of_yaml() -> None:
    cfg = {"cameras": [{"id": "cam-1", "rtsp_url_env": "CAM_1_RTSP"}]}
    out = resolve_env_refs(cfg, {"CAM_1_RTSP": "rtsp://user:pw@10.0.0.5/stream"})
    assert out["cameras"][0]["rtsp_url"] == "rtsp://user:pw@10.0.0.5/stream"
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}) == {"a": {"b": 1, "c": 3}}


class TestExplanations:
    cam = CameraNames(id="cam-gate-01", name="Gate camera 1", name_ur="گیٹ کیمرہ 1", name_roman="Gate-1")
    t = datetime(2026, 10, 23, 23, 41, tzinfo=PK_TZ)

    def test_loitering_in_three_languages(self) -> None:
        e = explain_alert(
            "loitering",
            {"passes": 4, "window_min": 15, "riders": 2, "slowdowns_near_ped": 2, "color": "black"},
            self.cam,
            self.t,
            p_value=0.004,
        )
        assert e.ur.startswith("گیٹ کیمرہ 1 پر 23:41 بجے: 2 افراد کالی موٹر سائیکل")
        assert "4 مرتبہ" in e.ur and "اعتماد: زیادہ" in e.ur
        assert "4 martaba" in e.roman and e.roman.isascii()
        assert "passed 4 times in 15 min" in e.en

    @pytest.mark.parametrize("kind", ["loitering", "snatch", "camera_tamper", "rule", "sos", "audio_event"])
    def test_language_is_neutral(self, kind: str) -> None:
        e = explain_alert(
            kind, {"check": "covered", "dwell_s": 400, "rule_name_ur": "رات کو گیٹ"}, self.cam, self.t, 0.01
        )
        for text in (e.ur, e.roman, e.en):
            assert is_neutral(text), text

    def test_pvalue_plain_language(self) -> None:
        texts = pvalue_text(0.004)
        assert texts is not None
        assert texts[1] == "Is jaisa pattern aam dinon mein 0.4% se kam hota hai"
        assert pvalue_text(None) is None
        assert "aksar" in (pvalue_text(0.5) or ("", "", ""))[1]


class TestHijri:
    @pytest.mark.parametrize(
        ("hijri", "pakistan", "max_days_off"),
        [
            ((1445, 9, 1), date(2024, 3, 12), 1),  # 1 Ramadan (moon sighting: a day later)
            ((1445, 10, 1), date(2024, 4, 10), 0),  # Eid ul Fitr
            ((1445, 12, 10), date(2024, 6, 17), 0),  # Eid ul Adha
            ((1446, 1, 10), date(2024, 7, 17), 0),  # Ashura
            ((1446, 9, 1), date(2025, 3, 2), 1),
            ((1446, 10, 1), date(2025, 3, 31), 0),
            ((1446, 12, 10), date(2025, 6, 7), 0),
        ],
    )
    def test_estimates_are_within_a_day_of_pakistani_dates(
        self, hijri: tuple[int, int, int], pakistan: date, max_days_off: int
    ) -> None:
        from jikimi_common.hijri import to_gregorian

        assert abs((to_gregorian(*hijri) - pakistan).days) <= max_days_off

    def test_roundtrip_over_three_years(self) -> None:
        from datetime import timedelta

        from jikimi_common.hijri import from_gregorian, to_gregorian

        d = date(2025, 1, 1)
        for _ in range(3 * 366):
            assert to_gregorian(*from_gregorian(d)) == d
            d += timedelta(days=1)
        assert from_gregorian(date(622, 7, 19)) == (1, 1, 1)


def test_pvalue_text_names_the_mode_it_was_calibrated_on() -> None:
    normal = pvalue_text(0.001)
    chand = pvalue_text(0.001, "chand_raat")
    assert normal is not None and chand is not None
    assert "aam dinon" in normal[1] and "Chand Raat ko" in chand[1] and "چاند رات" in chand[0]
    assert pvalue_text(0.001, "unknown-mode") == normal  # unknown modes fall back to the normal wording


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("haan main ne dekh liya", "ack"),
        ("ٹھیک ہے، میں دیکھ رہا ہوں", "ack"),
        ("हाँ जी, देख लिया", "ack"),
        ("Okay, I am coming.", "ack"),
        ("یہ غلط الارم ہے", "false_alarm"),
        ("ग़लत अलार्म है", "false_alarm"),
        ("dekh liya, sab khairiyat hai", "false_alarm"),  # checked: nothing there
        ("chor nahi tha, apna banda tha", "false_alarm"),
        ("nahi ji", "false_alarm"),
        ("jaldi aao madad chahiye", "need_help"),
        ("نہیں، مدد چاہیے", "need_help"),  # "no" belongs to another clause
        ("dekh liya, chor bhaag gaya", "need_help"),  # help beats seen
        ("جلدی آؤ پولیس کو بلاؤ", "need_help"),
        ("madad ki zaroorat nahi", "need_help"),  # a missed call for help is worse than an extra one
        ("madad nahi chahiye", None),
        ("ghalat alarm nahi hai", None),  # real, but seen or help? ask
        ("nahi dekha", None),
        ("kya hua ji?", None),
        ("", None),
    ],
)
def test_reply_intents_in_three_scripts(text: str, intent: str | None) -> None:
    assert reply_intent(text)[0] == intent


@pytest.mark.parametrize(
    ("kind", "features"),
    [
        (
            "loitering",
            {"passes": 4, "window_min": 15, "riders": 2, "slowdowns_near_ped": 1, "dwell_s": 130, "color": "black"},
        ),
        ("loitering", {"cross_camera": True, "passes": 4, "cameras": ["a", "b"], "window_min": 12, "color": "red"}),
        ("snatch", {"riders": 2, "color": "white"}),
        ("camera_tamper", {"check": "covered"}),
        ("camera_tamper", {"check": "view_accepted"}),
        ("sos", {}),
        ("network_match", {"riders": 1, "color": "blue", "distance_km": 1.2}),
        ("audio_event", {"sound": "scream"}),
    ],
)
def test_every_alert_can_be_read_by_a_hindi_voice(kind: str, features: dict[str, object]) -> None:
    import re

    from jikimi_common.translit import roman_to_devanagari

    cam = CameraNames(id="cam-gate-01", name="Gate camera 1", name_ur="گیٹ کیمرہ 1", name_roman="Gate-1")
    roman = explain_alert(kind, features, cam, datetime(2026, 10, 24, 23, 41, tzinfo=PK_TZ), 0.004, 0.9).roman
    deva = roman_to_devanagari(roman)
    assert not re.findall(r"[A-Za-z]", deva), deva  # nothing left for the voice to spell out
    assert "23:41" in deva and "बजे" in deva
