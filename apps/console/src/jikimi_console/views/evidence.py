"""Saboot: evidence packs for the police, and how each one checks out."""

from __future__ import annotations

import streamlit as st

from jikimi_console import api, ui

CHECK = {"pass": ("✓", "#0f5e4f"), "fail": ("✗", "#a3281f"), "pending": ("…", "#9a6a10"), "skipped": ("–", "#7d7566")}


def report(rep: dict) -> None:
    ok = rep.get("verified")
    st.markdown(
        f'<div class="sentence" style="border-color:{"#0f5e4f" if ok else "#a3281f"}">'
        f'<b>{ui.esc(rep.get("summary_en"))}</b><div class="ur" style="text-align:right">{ui.esc(rep.get("summary_ur"))}</div></div>',
        unsafe_allow_html=True,
    )
    for c in rep.get("checks") or []:
        mark, color = CHECK.get(c.get("status"), ("?", "#555"))
        st.markdown(
            f'<div class="row" style="grid-template-columns:2rem 1fr 1fr"><div style="color:{color};font-weight:700;font-size:1.2rem">{mark}</div>'
            f'<div>{ui.esc(c.get("detail_en"))}<div class="quiet">{ui.esc(c.get("name"))}</div></div>'
            f'<div class="naskh" style="text-align:right">{ui.esc(c.get("detail_ur"))}</div></div>',
            unsafe_allow_html=True,
        )


def page() -> None:
    site_id = st.session_state.get("site_id")
    ui.head(
        "Saboot", "ثبوت", "Dastakhat shuda clip + PDF · Merkle · OpenTimestamps · police khud tasdeeq kar sakti hai"
    )
    items = api.get("/v1/evidence", site_id=site_id, limit=30) or []
    items = items if isinstance(items, list) else items.get("items", [])
    if not items:
        st.markdown(
            '<div class="chit">Abhi koi saboot nahi bana. Roznamcha mein kisi alert ko khol kar "Saboot banayein" dabayein.</div>',
            unsafe_allow_html=True,
        )
        return
    names = {
        e["id"]: f"{e['id']} · {e['alert_count']} alert · {ui.local(e['created_at']):%d %b %H:%M} · {e['created_by']}"
        for e in items
    }
    pick = st.selectbox("Kaun sa saboot", list(names), format_func=names.get)
    ev = api.get(f"/v1/evidence/{pick}")
    a, b = st.columns([1.3, 1])
    with a:
        report(api.get(f"/v1/verify/{pick}"))
    with b:
        st.markdown("**Hawale ki zanjeer (chain of custody)**")
        for c in ev.get("custody") or []:
            st.markdown(
                f"`{ui.local(c['at']):%d %b %H:%M}` {ui.esc(c['action'])} — {ui.esc(c['actor'])}",
                unsafe_allow_html=True,
            )
        st.code(
            f"manifest {ev['manifest_sha256']}\npdf      {ev.get('pdf_sha256') or '—'}\nmerkle   {ev['merkle_status']}\nOTS      {ev['ots_status']}",
            language=None,
        )
        pdf = api.media(ev.get("pdf_url") or "", api.token())
        if pdf:
            st.download_button(
                "PDF download (Urdu + English)",
                pdf,
                file_name=f"{pick}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        st.caption(f"Police ke liye link: {ev.get('verify_url')}")
