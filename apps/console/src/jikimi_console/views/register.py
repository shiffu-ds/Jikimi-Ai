"""Roznamcha: every alert of the site, newest first, the way a duty register is kept."""

from __future__ import annotations

import streamlit as st

from jikimi_console import api, ui
from jikimi_console.views import alert

TABS = {"Khule": ["open", "escalated", "verifying", "acked"], "Sab": [], "Sirf record": ["logged_only"]}


def page() -> None:
    site_id = st.session_state.get("site_id")
    ui.head("Roznamcha", "روزنامچہ", "Har alert, uski wajah aur uska anjaam")
    c1, c2, c3 = st.columns([1.6, 2.2, 1.6], vertical_alignment="bottom")
    tab = c1.segmented_control("Kaun se", list(TABS), default="Khule", key="reg_tab") or "Khule"
    types = c2.multiselect("Qism", list(ui.TYPES), format_func=lambda t: ui.TYPES[t][1], placeholder="Har qism")
    with c3:
        lang = ui.lang_picker()
    entries(site_id, tab, types, lang)


@st.fragment(run_every="8s")
def entries(site_id: str | None, tab: str, types: list[str], lang: str) -> None:
    params = {"site_id": site_id, "status": TABS[tab], "type": types, "limit": 40}
    if tab == "Sirf record":
        params["include_logged"] = True
    page = api.get("/v1/alerts", **params) or {}
    items = page.get("items", [])
    st.caption(f"{len(items)} indraaj" + (" (aur bhi hain — filter tang karein)" if page.get("next_cursor") else ""))
    if not items:
        st.markdown('<div class="quiet">Is filter mein koi indraaj nahi.</div>', unsafe_allow_html=True)
    for i, a in enumerate(items, 1):
        row, btn = st.columns([10, 1.7])
        row.markdown(f'<div class="register">{ui.register_row(i, a, lang)}</div>', unsafe_allow_html=True)
        if btn.button("Kholo", key=f"kholo-r{a['id']}", use_container_width=True):
            alert.show(a["id"])
