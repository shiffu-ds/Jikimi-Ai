"""The console renders without a server and its register reads the way a guard speaks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from jikimi_console import ui
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "src" / "jikimi_console" / "app.py"


def test_signed_out_visitor_sees_the_sign_in_form() -> None:
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Username", "Password"]


def test_times_are_said_in_roman_urdu() -> None:
    now = datetime.now(UTC)
    assert ui.ago(now.isoformat()) == "abhi abhi"
    assert ui.ago((now - timedelta(minutes=5)).isoformat()) == "5 minat pehle"
    assert ui.ago((now - timedelta(days=1, hours=1)).isoformat()) == "kal"


def test_register_row_shows_reason_stamp_and_code() -> None:
    a = {
        "type": "snatch",
        "severity": "high",
        "route": "ALERT_NOW",
        "status": "acked",
        "ts_end": datetime.now(UTC).isoformat(),
        "explanation_ur": "بازار کیمرہ 2 پر",
        "explanation_roman": "Bazaar-2 par",
        "camera_name": "Market street camera 2",
        "short_code": "9A40",
        "p_value": 0.0005,
    }
    row = ui.register_row(7, a, "ur")
    assert "007" in row and "دیکھ لیا" in row and "code 9A40" in row and "بازار" in row
    assert "Bazaar-2 par" in ui.register_row(7, a, "roman")


def test_labels_never_name_a_person() -> None:
    """Behaviour only: no gender words in any label the console prints."""
    words = " ".join(v[1] for v in ui.TYPES.values()) + " " + " ".join(v[1] for v in ui.PATTERNS.values())
    assert not {"woman", "man", "girl", "boy", "female", "male", "thief"} & set(words.lower().split())
    assert ui.type_label("person_in_danger", {"pattern": "following"}, "en") == "Person in danger · followed"
