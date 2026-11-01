"""Public: anyone holding an evidence ID (or the file itself) can check it — no account needed."""

from __future__ import annotations

import hashlib

import streamlit as st

from jikimi_console import api, ui
from jikimi_console.views.evidence import report


def page() -> None:
    ui.head("Saboot ki tasdeeq", "ثبوت کی تصدیق", "Baghair login · koi bhi evidence ID ya file ki jaanch kar sakta hai")
    ev = st.text_input("Evidence ID", value=st.query_params.get("id", ""), placeholder="EV-2026-10-31-0001")
    if not ev:
        st.markdown(
            '<div class="chit">Saboot ke PDF par QR code hota hai — wahi ID yahan likhein.</div>',
            unsafe_allow_html=True,
        )
        return
    try:
        report(api.get(f"/v1/verify/{ev.strip()}"))
    except api.ApiError as e:
        st.error("Yeh ID nahi mili." if e.status == 404 else str(e))
        return
    st.markdown("**Aap ke paas file hai? (clip ya PDF)**")
    f = st.file_uploader("File yahin jaanchi jati hai — sirf uska hash server ko jata hai", type=None)
    if f is not None:
        digest = hashlib.sha256(f.getvalue()).hexdigest()
        m = api.get(f"/v1/verify/{ev.strip()}/match", sha256=digest)
        if m.get("matched"):
            st.success(f"Yeh file isi saboot ka hissa hai ({m.get('kind')}: {m.get('name')}). Ek bit bhi nahi badla.")
        else:
            st.error("Yeh file is saboot se mel nahi khati — ya badli gayi hai ya kisi aur ki hai.")
        st.caption(f"sha256 {digest}")
