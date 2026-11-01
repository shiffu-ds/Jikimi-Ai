"""Live cameras: the latest blurred snapshot of every camera, refreshed every few seconds."""

from __future__ import annotations

import streamlit as st

from jikimi_console import api, ui


def page() -> None:
    ui.head("Live camere", "لائیو کیمرے", "Tasveeren edge par hi dhundli hoti hain, phir yahan aati hain")
    feed()


@st.fragment(run_every="3s")
def feed() -> None:
    site = api.get("/v1/sites") or []
    site = next((s for s in site if s["id"] == st.session_state.get("site_id")), site[0] if site else None)
    if not site:
        st.info("Koi site nahi mili.")
        return
    cams = site.get("cameras") or []
    cols = st.columns(2)
    for i, cam in enumerate(cams):
        with cols[i % 2]:
            img = api.media(cam.get("snapshot_url") or f"/v1/media/snapshots/{cam['id']}.jpg", api.token())
            state = "chal raha hai" if cam.get("status") == "online" else cam.get("status", "?")
            st.markdown(
                f"**{ui.esc(cam.get('name'))}** <span class='ur-in'>{ui.esc(cam.get('name_ur') or '')}</span>"
                f"<br><span class='quiet'>{state} · {cam.get('fps', 0):.1f} fps · {ui.ago(cam.get('last_seen'))}</span>",
                unsafe_allow_html=True,
            )
            if img:
                st.image(img, use_container_width=True)
            else:
                st.markdown('<div class="chit">Is camere ki tasveer abhi nahi aayi.</div>', unsafe_allow_html=True)
            checks = (cam.get("health") or {}).get("checks") or cam.get("health") or {}
            bad = [k for k, v in checks.items() if isinstance(v, str) and v not in ("ok", "pass")]
            if bad:
                st.caption("Tawajjo: " + ", ".join(bad))
