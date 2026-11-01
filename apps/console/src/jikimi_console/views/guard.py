"""Meri duty: the guard's phone view — one big card, three buttons, a voice reply and SOS."""

from __future__ import annotations

import io
import math
import struct
import wave

import streamlit as st

from jikimi_console import api, ui

INTENT_WORDS = {"ack": "dekh liya", "false_alarm": "ghalat alarm", "need_help": "madad chahiye"}


@st.cache_data
def beep() -> bytes:
    """Two short tones, generated here (no sound files to ship)."""
    buf, rate = io.BytesIO(), 16000
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b""
        for f, dur in ((880, 0.18), (0, 0.06), (1320, 0.3)):
            for i in range(int(rate * dur)):
                frames += struct.pack("<h", int(9000 * math.sin(2 * math.pi * f * i / rate) * math.exp(-3 * i / rate)))
        w.writeframes(frames)
    return buf.getvalue()


def respond(a: dict, intent: str) -> None:
    if intent == "ack":
        api.post(f"/v1/alerts/{a['id']}/ack", {"note": None})
        st.toast("Shukriya — supervisor ko pata chal gaya ke aap ne dekh liya.")
    elif intent == "false_alarm":
        api.post(f"/v1/alerts/{a['id']}/ack", {"note": "guard: ghalat alarm"})
        st.toast("Note kar liya: ghalat alarm. Is se system behtar hota hai.")
    elif intent == "need_help":
        api.post(
            "/v1/sos",
            {"site_id": a["site_id"], "camera_id": a["camera_id"], "note": f"madad chahiye · alert {a['short_code']}"},
        )
        st.toast("Madad ki darkhwast supervisor tak bhej di gayi.")


def page() -> None:
    _, phone, _ = st.columns([1, 1.6, 1])  # a phone's width, also on a desktop screen
    with phone:
        body()


def body() -> None:
    user = st.session_state["user"]
    site_id = st.session_state.get("site_id")
    first = user["name"].split(" (")[0]
    st.markdown(
        f'<div class="greet">Assalam-o-Alaikum {ui.esc(first)} — {ui.shift_name()}. '
        f'<div class="quiet" style="margin-bottom:.8rem">Kuch ho to yahin dikhega, awaaz ke saath.</div></div>',
        unsafe_allow_html=True,
    )
    duty(site_id)
    st.divider()
    with st.expander("SOS — foran madad", expanded=False):
        st.caption("Sirf asal khatre mein. Supervisor aur malik dono ko foran ittila jati hai.")
        if st.toggle("Haan, mujhe madad chahiye", key="sos_arm") and st.button(
            "SOS bhejein", type="primary", use_container_width=True
        ):
            api.post("/v1/sos", {"site_id": site_id, "camera_id": None, "note": "guard SOS"})
            st.error("SOS bhej diya gaya. Madad aa rahi hai.")


@st.fragment(run_every="5s")
def duty(site_id: str | None) -> None:
    page = api.get("/v1/alerts", site_id=site_id, status=["open", "escalated"], limit=5) or {}
    items = page.get("items", [])
    if not items:
        st.markdown(
            '<div class="sentence">Sab khairiyat hai. Koi khula alert nahi.<div class="ur" style="text-align:right">سب خیریت ہے</div></div>',
            unsafe_allow_html=True,
        )
        return
    a = items[0]
    if st.session_state.get("last_rung") != a["id"]:
        st.session_state["last_rung"] = a["id"]
        with st.container(key="beep"):  # heard, not shown
            st.audio(beep(), format="audio/wav", autoplay=True)
    st.markdown(
        f'<div class="bigcard"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:.6rem;flex-wrap:wrap"><b>{ui.esc(ui.type_label(a["type"], None, "en"))}</b>'
        f'<span class="quiet">#{ui.esc(a["short_code"])} · {ui.local(a["ts_end"]):%H:%M} · {ui.ago(a["ts_end"])}</span></div>'
        f'<div class="ur">{ui.esc(a.get("explanation_ur"))}</div></div>',
        unsafe_allow_html=True,
    )
    img = api.media(a.get("thumbnail_url") or "", api.token())
    if img:
        st.image(img, use_container_width=True)
    if st.button("Dekh liya", key=f"g1{a['id']}", type="primary", use_container_width=True):
        respond(a, "ack")
    c2, c3 = st.columns(2)
    if c2.button("Ghalat alarm", key=f"g2{a['id']}", use_container_width=True):
        respond(a, "false_alarm")
    if c3.button("Madad chahiye", key=f"g3{a['id']}", use_container_width=True):
        respond(a, "need_help")
    voice = st.audio_input(
        "Ya bol kar jawab dein — 'haan dekh liya', 'ghalat alarm', 'madad chahiye'", key=f"v{a['id']}"
    )
    if voice is not None:
        try:
            r = api.post("/v1/voice/reply", raw=voice.getvalue(), content_type="audio/wav", lang="ur")
            intent = r.get("intent")
            st.markdown(f"Suna: _{ui.esc(r.get('text'))}_", unsafe_allow_html=True)
            if intent in INTENT_WORDS and st.button(f"Haan, bhejein: {INTENT_WORDS[intent]}", key=f"vc{a['id']}"):
                respond(a, intent)
            elif intent not in INTENT_WORDS:
                st.caption("Samajh nahi aaya — dobara bolein ya button dabayein.")
        except api.ApiError as e:
            st.caption(f"Awaaz wala jawab is server par band hai ({e.title}). Button istemal karein.")
    if len(items) > 1:
        st.caption(f"Aur {len(items) - 1} khule alert pichhe hain.")
