"""The look of the console: a guard-room register (roznamcha) rather than a dashboard of tiles.

Warm paper, ink, ruled rows, rubber stamps for status, Urdu headings in Nastaliq. Kept in one
place so every page reads the same way.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import streamlit as st

PK = ZoneInfo("Asia/Karachi")

TYPES = {  # type -> (Urdu, English)
    "snatch": ("چھینا جھپٹی کا شبہ", "Suspected snatching"),
    "loitering": ("مشکوک چکر", "Suspicious loitering"),
    "person_in_danger": ("کسی کو خطرہ", "Person in danger"),
    "vehicle_theft": ("بائیک چوری کا شبہ", "Suspected bike theft"),
    "crowd_panic": ("بھگدڑ", "Crowd panic"),
    "camera_tamper": ("کیمرے سے چھیڑ چھاڑ", "Camera tampering"),
    "rule": ("قاعدہ", "Rule"),
    "sos": ("ایس او ایس", "SOS"),
    "audio_event": ("آواز", "Audio event"),
    "network_match": ("پڑوس سے ملتی بائیک", "Bike seen at a neighbour"),
}
PATTERNS = {
    "following": ("پیچھا", "followed"),
    "surrounded": ("گھیراؤ", "surrounded"),
    "struggle": ("ہاتھا پائی", "struggle"),
    "dragged": ("زبردستی کھینچنا", "dragged"),
    "forced_into_vehicle": ("زبردستی گاڑی میں", "forced into a vehicle"),
    "fall": ("گر گیا", "fell down"),
}
STATUS = {  # status -> (Urdu stamp, English, css class)
    "open": ("کھلا", "open", "red"),
    "escalated": ("آگے بڑھایا", "escalated", "red"),
    "verifying": ("تصدیق جاری", "verifying", "amber"),
    "acked": ("دیکھ لیا", "seen", "green"),
    "resolved": ("حل", "resolved", "green"),
    "false_alarm": ("غلط الارم", "false alarm", "grey"),
    "unclear": ("غیر واضح", "unclear", "grey"),
    "logged_only": ("صرف ریکارڈ", "logged", "grey"),
}

CSS = """
<style>
@font-face { font-family: "Nastaliq"; src: url("app/static/NotoNastaliqUrdu-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Nastaliq"; src: url("app/static/NotoNastaliqUrdu-Bold.ttf"); font-weight: 700; }
@font-face { font-family: "Naskh"; src: url("app/static/NotoNaskhArabic-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Naskh"; src: url("app/static/NotoNaskhArabic-SemiBold.ttf"); font-weight: 600; }
:root { --ink: #1f2a33; --paper: #f7f3ea; --rule: #e3d9c4; --green: #0f5e4f; --red: #a3281f; --amber: #9a6a10; --muted: #6b6457; }
.block-container { padding-top: 3rem; max-width: 1240px; }
h1, h2, h3 { letter-spacing: -0.01em; }
.ur { font-family: "Nastaliq", "Naskh", serif; direction: rtl; line-height: 2.1; }
.naskh { font-family: "Naskh", serif; direction: rtl; line-height: 1.9; }
.ur-in { font-family: "Nastaliq", "Naskh", serif; direction: rtl; unicode-bidi: isolate; line-height: 1; margin-left: .35rem; }
.sec { font-family: "Noto Serif", serif; font-size: 1.2rem; font-weight: 700; color: var(--ink);
  margin: 1.3rem 0 .55rem; padding-bottom: .25rem; border-bottom: 1px solid var(--rule); }
.sec:first-child { margin-top: .2rem; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem;
  border-bottom: 2px solid var(--ink); padding-bottom: .35rem; margin-bottom: 1.1rem; }
.page-head .t { font-family: "Noto Serif", serif; font-size: 2.05rem; font-weight: 700; color: var(--ink); line-height: 1.1; }
.page-head .s { color: var(--muted); font-size: .95rem; margin-top: .2rem; }
.page-head .u { font-family: "Nastaliq", serif; font-size: 1.85rem; color: var(--green); direction: rtl; line-height: 2.5;
  white-space: nowrap; }
.greet { font-family: "Noto Serif", serif; font-size: 1.15rem; color: var(--ink); }
.greet b { font-weight: 700; }
.sentence { font-size: 1.05rem; color: var(--ink); background: #fffdf7; border-left: 4px solid var(--green);
  padding: .8rem 1rem; border-radius: 2px; margin: .6rem 0 1.2rem; }
.register { border-top: 1px solid var(--rule); }
.row { display: grid; grid-template-columns: 2.4rem 6.2rem 1fr; gap: .9rem; align-items: start;
  padding: .75rem .25rem; border-bottom: 1px solid var(--rule); }
.row .sn { font-family: "Noto Serif", serif; color: var(--muted); font-size: .9rem; padding-top: .15rem; }
.row .tm { font-family: "Noto Serif", serif; font-size: 1.05rem; color: var(--ink); }
.row .tm small { display: block; color: var(--muted); font-size: .78rem; white-space: nowrap; }
.row .what .k { display: flex; align-items: center; flex-wrap: wrap; gap: .45rem; margin-bottom: .3rem; font-weight: 650; color: var(--ink); }
.row .what .k .stamp { margin-left: auto; }
.row .what .k em { font-style: normal; color: var(--muted); font-weight: 400; }
.row .what .r { font-family: "Nastaliq", "Naskh", serif; direction: rtl; text-align: right; font-size: 1.12rem; line-height: 2.05; color: #2c3a44; }
.row .what .r.lat { font-family: inherit; direction: ltr; text-align: left; font-size: .95rem; line-height: 1.5; }
.row .what .m { font-size: .8rem; color: var(--muted); }
div[class*="st-key-kholo"] { padding-top: .8rem; }
.st-key-beep { display: none; }
.spot { display: grid; grid-template-columns: 1fr auto; gap: .8rem; align-items: center; padding: .55rem .1rem; border-bottom: 1px solid var(--rule); }
.spot b { font-weight: 600; color: var(--ink); }
.spot .naskh { font-size: .95rem; color: var(--muted); text-align: left; direction: rtl; unicode-bidi: plaintext; line-height: 1.6; }
.spot .figure { text-align: right; }
.spot .figure .n { font-size: 1.45rem; }
.spot .figure .l { font-size: .72rem; white-space: nowrap; }
.stamp { display: inline-block; transform: rotate(-4deg); border: 2px solid currentColor; border-radius: 4px;
  padding: .05rem .55rem; font-family: "Nastaliq", "Naskh", serif; font-size: 1.05rem; line-height: 1.9; opacity: .85; white-space: nowrap; }
.stamp small { font-family: "Noto Sans", sans-serif; font-size: .62rem; letter-spacing: .08em; text-transform: uppercase; margin-left: .35rem; }
.stamp.red { color: var(--red); } .stamp.green { color: var(--green); } .stamp.amber { color: var(--amber); } .stamp.grey { color: #7d7566; }
.chit { background: #fff8d9; border: 1px dashed #c9b56a; padding: .8rem 1rem; border-radius: 2px; transform: rotate(-.4deg);
  box-shadow: 2px 3px 0 rgba(0,0,0,.05); color: #3d3522; }
.chit .who { font-size: .78rem; color: #8a7a45; margin-top: .3rem; }
.figure { font-family: "Noto Serif", serif; }
.figure .n { font-size: 2.1rem; font-weight: 700; color: var(--ink); line-height: 1; }
.figure .l { color: var(--muted); font-size: .85rem; }
.tag { display: inline-block; font-size: .78rem; font-weight: 400; padding: .05rem .5rem; border: 1px solid var(--rule); border-radius: 3px; color: var(--muted); }
.tag.hot { border-color: #d9a49f; color: var(--red); }
.bigcard { border: 2px solid var(--red); background: #fff6f3; padding: 1rem 1.1rem; border-radius: 6px; margin-bottom: .8rem; }
.bigcard .ur { font-size: 1.45rem; color: var(--ink); text-align: right; }
.quiet { color: var(--muted); font-size: .9rem; }
section[data-testid="stSidebar"] .ur { font-size: 1.25rem; }
</style>
"""


def setup() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def head(title: str, urdu: str, sub: str = "") -> None:
    st.markdown(
        f'<div class="page-head"><div><div class="t">{esc(title)}</div><div class="s">{esc(sub)}</div></div>'
        f'<div class="u">{esc(urdu)}</div></div>',
        unsafe_allow_html=True,
    )


def section(title: str) -> None:
    st.markdown(f'<div class="sec">{esc(title)}</div>', unsafe_allow_html=True)


def local(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PK)


def ago(ts: str | None) -> str:
    """Roman Urdu, the way a guard says it: '3 minat pehle'."""
    t = local(ts)
    if t is None:
        return ""
    s = (datetime.now(UTC) - t.astimezone(UTC)).total_seconds()
    if s < 60:
        return "abhi abhi"
    if s < 3600:
        return f"{int(s // 60)} minat pehle"
    if s < 86400:
        return f"{int(s // 3600)} ghante pehle"
    days = int(s // 86400)
    return "kal" if days == 1 else f"{days} din pehle"


def shift_name(now: datetime | None = None) -> str:
    h = (now or datetime.now(PK)).hour
    if 5 <= h < 12:
        return "subah ki duty"
    if 12 <= h < 17:
        return "dopahar ki duty"
    if 17 <= h < 21:
        return "shaam ki duty"
    return "raat ki duty"


def type_label(t: str, features: dict | None = None, lang: str = "ur") -> str:
    ur, en = TYPES.get(t, (t, t))
    pat = (features or {}).get("pattern")
    if pat in PATTERNS:
        ur, en = f"{ur} · {PATTERNS[pat][0]}", f"{en} · {PATTERNS[pat][1]}"
    if (features or {}).get("on_foot"):
        ur, en = f"{ur} · پیدل", f"{en} · on foot"
    return ur if lang == "ur" else en


def stamp(status: str) -> str:
    ur, en, cls = STATUS.get(status, (status, status, "grey"))
    return f'<span class="stamp {cls}">{esc(ur)}<small>{esc(en)}</small></span>'


def reason(a: dict, lang: str) -> tuple[str, bool]:
    """The alert's own explanation in the chosen script; ``True`` when it is Urdu script."""
    if lang == "ur" and a.get("explanation_ur"):
        return a["explanation_ur"], True
    if lang == "roman" and a.get("explanation_roman"):
        return a["explanation_roman"], False
    return a.get("explanation_en") or a.get("explanation_roman") or "", False


def register_row(n: int, a: dict, lang: str) -> str:
    t = local(a.get("ts_end"))
    text, urdu = reason(a, lang)
    meta = " · ".join(
        x
        for x in (
            a.get("camera_name") or a.get("camera_id"),
            f"code {a.get('short_code')}" if a.get("short_code") else "",
            f"p = {a['p_value']:.4f}" if a.get("p_value") is not None else "",
            "SMS bheja gaya" if a.get("sms_sent") else "",
        )
        if x
    )
    hot = ' class="tag hot"' if a.get("severity") == "high" else ' class="tag"'
    return (
        f'<div class="row"><div class="sn">{n:03d}</div>'
        f'<div class="tm">{t:%H:%M}<small>{esc(ago(a.get("ts_end")))}</small></div>'
        f'<div class="what"><div class="k">{esc(type_label(a["type"], a.get("features"), "en"))} '
        f"<span{hot}>{esc(a.get('severity', ''))}</span> <em>{esc(a.get('route', ''))}</em>{stamp(a.get('status', ''))}</div>"
        f'<div class="r{"" if urdu else " lat"}">{esc(text)}</div><div class="m">{esc(meta)}</div></div></div>'
        if t
        else ""
    )


def lang_picker(key: str = "lang") -> str:
    labels = {"ur": "اردو", "roman": "Roman Urdu", "en": "English"}
    return (
        st.segmented_control(
            "Wajah kis zubaan mein?",
            list(labels),
            format_func=labels.get,
            default=st.session_state.get(key, "ur"),
            key=key,
        )
        or "ur"
    )
