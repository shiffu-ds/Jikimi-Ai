"""Jikimi AI console (Streamlit).

    make ui            # or: cd apps/console && uv run streamlit run src/jikimi_console/app.py

Reads the API at ``JIKIMI_API_URL`` (default http://127.0.0.1:8000). Every person signs in with
their own account; what they see follows their role (guard, supervisor, admin, police viewer).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # `streamlit run` on this file

from jikimi_console import api, ui
from jikimi_console.views import (
    evidence,
    guard,
    health,
    live,
    login,
    overview,
    register,
    rules,
    search,
    verify,
)

st.set_page_config(
    page_title="Jikimi · pehra register", page_icon=str(Path(__file__).parent / "static/mark.png"), layout="wide"
)
ui.setup()

user = st.session_state.get("user")
public = [st.Page(verify.page, title="Saboot ki tasdeeq", url_path="verify")]

if not api.token() or not user:
    nav = st.navigation(
        [st.Page(login.page, title="Sign in", url_path="login", default=True), *public], position="hidden"
    )
    nav.run()
    st.stop()

role = user["role"]
pages: dict[str, list[st.Page]] = {}
if role == "guard":
    pages["Duty"] = [st.Page(guard.page, title="Meri duty", url_path="guard", default=True)]
    pages["More"] = [st.Page(register.page, title="Roznamcha", url_path="register"), *public]
else:
    pages["Aaj"] = [
        st.Page(overview.page, title="Jaiza", url_path="overview", default=True),
        st.Page(register.page, title="Roznamcha", url_path="register"),
        st.Page(live.page, title="Live cameras", url_path="live"),
    ]
    pages["Tafteesh"] = [
        st.Page(search.page, title="Talash aur sawal", url_path="search"),
        st.Page(evidence.page, title="Saboot", url_path="evidence"),
    ]
    if role != "police_viewer":
        pages["Intezam"] = [
            st.Page(rules.page, title="Qawaid aur mausam", url_path="rules"),
            st.Page(health.page, title="Cameron ki sehat", url_path="health"),
        ]
    pages["Duty"] = [st.Page(guard.page, title="Guard ka phone", url_path="guard")]
    pages["Public"] = public
nav = st.navigation(pages)

with st.sidebar:
    sites = api.get("/v1/sites") or []
    if sites:
        names = {s["id"]: s.get("name_ur") or s["name"] for s in sites}
        current = st.session_state.get("site_id") or sites[0]["id"]
        st.session_state["site_id"] = st.selectbox(
            "Site", list(names), index=list(names).index(current) if current in names else 0, format_func=names.get
        )
        st.session_state["site"] = next(s for s in sites if s["id"] == st.session_state["site_id"])
    st.markdown(
        f'<div class="quiet">{ui.esc(user["name"])} · {ui.esc(role)}<br>{ui.shift_name()}</div>', unsafe_allow_html=True
    )
    if st.button("Log out", use_container_width=True):
        api.logout()
        st.rerun()

nav.run()
