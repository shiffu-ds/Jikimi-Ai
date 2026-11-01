"""Jaiza: the first thing a supervisor reads when the shift starts."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from jikimi_console import api, store, ui
from jikimi_console.views import alert


def _mtta(s: float | None) -> str:
    if s is None:
        return "abhi naapa nahi"
    return f"{s:.0f} second" if s < 90 else f"{s / 60:.0f} minat"


def page() -> None:
    user = st.session_state["user"]
    site = st.session_state.get("site") or {}
    site_id = st.session_state.get("site_id")
    now = datetime.now(ui.PK)
    ui.head("Aaj ka jaiza", "آج کا جائزہ", f"{site.get('name', '')} · {now:%A, %d %B}")
    st.markdown(
        f'<div class="greet">Assalam-o-Alaikum, <b>{ui.esc(user["name"].split(" (")[0])}</b> — {ui.shift_name(now)}.</div>',
        unsafe_allow_html=True,
    )
    stats = api.get("/v1/stats", site_id=site_id, days=7) or {}
    cal = api.get(f"/v1/sites/{site_id}/calendar") if site_id else None
    sentence = (
        f"Aaj ab tak <b>{stats.get('alerts_today', 0)}</b> alert aaye, aur <b>{stats.get('open_alerts', 0)}</b> abhi khule hain. "
        f"Guard ka jawab ausatan <b>{_mtta(stats.get('mtta_median_s'))}</b> mein aata hai. "
        f"<b>{stats.get('cameras_online', 0)}</b> mein se {stats.get('cameras_total', 0)} camere chal rahe hain"
    )
    if stats.get("false_alarm_rate") is not None:
        sentence += f"; pichle hafte jaiza liye gaye alerts mein se {stats['false_alarm_rate'] * 100:.0f}% ghalat nikle"
    if stats.get("sms_fallbacks"):
        sentence += f", aur {stats['sms_fallbacks']} martaba internet ke baghair SMS gaya"
    st.markdown(f'<div class="sentence">{sentence}.</div>', unsafe_allow_html=True)
    if cal and cal.get("current_mode") not in (None, "normal"):
        st.warning(f"Aaj ka mausam: **{cal['current_mode']}** — alerts us din ke 'normal' se tole ja rahe hain.")

    main, side = st.columns([2.7, 1], gap="large")
    with main:
        ui.section("Taaza roznamcha")
        latest(site_id)
    with side:
        ui.section("Shift ka note")
        n = store.note(site_id or "")
        if n and n.get("text"):
            st.markdown(
                f'<div class="chit">{ui.esc(n["text"])}<div class="who">— {ui.esc(n["by"])}, {ui.ago(n["at"])}</div></div>',
                unsafe_allow_html=True,
            )
        with st.popover("Agli shift ke liye likhein", use_container_width=True):
            text = st.text_area(
                "Note",
                value=(n or {}).get("text", ""),
                placeholder="maslan: gate 2 ki light kharab hai, raat ko bazaar wale camere par nazar rakhein",
            )
            if st.button("Mehfooz karein"):
                store.save_note(site_id or "", text, user["name"])
                st.rerun()
        ui.section("Kahan nazar rakhein")
        try:
            hs = api.get(f"/v1/sites/{site_id}/hotspots", hours=4, budget_min=30)
            for z in (hs.get("zones") or [])[:3]:
                st.markdown(
                    f'<div class="spot"><div><b>{ui.esc(z.get("name"))}</b>'
                    f'<div class="naskh">{ui.esc(z.get("name_ur") or "")}</div></div>'
                    f'<div class="figure"><div class="n">{z.get("expected_events", 0):.1f}</div>'
                    '<div class="l">agle 4 ghante</div></div></div>',
                    unsafe_allow_html=True,
                )
            if hs.get("patrol"):
                route = " → ".join(p.get("name") or p["zone_key"] for p in hs["patrol"])
                st.caption(f"Gasht ka raasta (30 min): {route}. Yeh andaza hai, peshgoi nahi.")
        except api.ApiError:
            st.caption("Khatre ka andaza abhi dastyab nahi.")
        days = stats.get("by_day") or []
        if days:
            ui.section("Pichle 7 din")
            st.bar_chart({d["key"][5:]: d["count"] for d in days}, color="#0f5e4f", height=170)


@st.fragment(run_every="6s")
def latest(site_id: str | None) -> None:
    lang = st.session_state.get("lang", "ur")
    page = api.get("/v1/alerts", site_id=site_id, limit=8) or {}
    items = page.get("items", [])
    if not items:
        st.markdown('<div class="quiet">Abhi tak koi alert nahi. Khuda kare yun hi rahe.</div>', unsafe_allow_html=True)
        return
    for i, a in enumerate(items, 1):
        row, btn = st.columns([10, 1.7])
        row.markdown(f'<div class="register">{ui.register_row(i, a, lang)}</div>', unsafe_allow_html=True)
        if btn.button("Kholo", key=f"kholo-o{a['id']}", use_container_width=True):
            alert.show(a["id"])
