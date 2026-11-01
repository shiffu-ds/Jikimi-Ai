from __future__ import annotations

import streamlit as st

from jikimi_console import api


def page() -> None:
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown(
            '<div style="text-align:center;margin-top:2.5rem">'
            '<img src="app/static/mark.png" width="74">'
            '<div class="ur" style="font-size:2.6rem;color:#0f5e4f;direction:rtl;line-height:2.6;margin:.2rem 0 .1rem">جکیمی — پہرہ رجسٹر</div>'
            '<div class="quiet">Har raat, aap ka pehra. Apne account se andar aayein.</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("login", border=True):
            username = st.text_input("Username", placeholder="maslan: sana")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Andar aayein", use_container_width=True, type="primary")
        if ok:
            try:
                api.login(username.strip(), password)
                st.rerun()
            except api.ApiError as e:
                st.error("Username ya password durust nahi." if e.status in (400, 401) else f"Server: {e}")
            except Exception:
                st.error(f"Server tak nahi pohanch sake ({api.BASE}). Kya `make server` chal raha hai?")
        st.markdown(
            '<div class="quiet" style="text-align:center;margin-top:.8rem">'
            "Chehra shanasi nahi · har dekhne ka record audit mein · police ke liye "
            '<a href="verify" target="_self">saboot ki tasdeeq</a> baghair login</div>',
            unsafe_allow_html=True,
        )
