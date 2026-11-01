"""Cameron ki sehat: edge boxes and cameras — covered, blurred, moved, frozen, offline, power."""

from __future__ import annotations

import streamlit as st

from jikimi_console import api, ui

CHECKS = {
    "covered": "dhaka hua",
    "blur": "dhundla",
    "moved": "rukh badla",
    "frozen": "ruka hua",
    "offline": "band",
    "moving": "hil raha",
}


def page() -> None:
    site_id = st.session_state.get("site_id")
    ui.head("Cameron ki sehat", "سسٹم کی صحت", "Har camera aur edge box ka haal")
    h = api.get("/v1/health/overview", fresh=True) or {}
    for d in h.get("devices") or []:
        if d.get("site_id") != site_id:
            continue
        status = "online" if d.get("online") else "offline"
        st.markdown(
            f'<div class="sentence"><b>{ui.esc(d.get("name") or d["id"])}</b> — {status}, aakhri baar {ui.ago(d.get("last_seen"))}. '
            f"Outbox mein {d.get('outbox_backlog', 0)} cheezen ruki hain"
            + (f", battery {d['battery_pct']}%" if d.get("battery_pct") is not None else "")
            + f" ({ui.esc(d.get('power_source') or 'bijli')}), SMS: {ui.esc(d.get('sms_gateway') or '—')}.</div>",
            unsafe_allow_html=True,
        )
        if d.get("drift"):
            st.caption(
                "Calibration drift: " + ", ".join(f"{k}: {'haan' if v else 'nahi'}" for k, v in d["drift"].items())
            )
    rows = []
    for c in h.get("cameras") or []:
        if c.get("site_id") != site_id:
            continue
        checks = (c.get("health") or {}).get("checks") or c.get("health") or {}
        bad = [CHECKS.get(k, k) for k, v in checks.items() if isinstance(v, str) and v not in ("ok", "pass")]
        rows.append(
            {
                "camera": c.get("name"),
                "haal": c.get("status"),
                "fps": round(c.get("fps") or 0, 1),
                "masle": ", ".join(bad) or "theek",
                "aakhri frame": ui.ago(c.get("last_seen")),
            }
        )
        admin = st.session_state["user"]["role"] in ("admin", "owner")
        if "rukh badla" in bad and admin and st.button(f"{c.get('name')}: naya rukh qabool karein", key=f"av{c['id']}"):
            api.post(f"/v1/sites/{site_id}/cameras/{c['id']}/accept-view")
            st.success("Hukm dastakhat ke saath edge ko bhej diya.")
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption(f"Server ka waqt: {ui.local(h.get('server_time')):%H:%M:%S}" if h.get("server_time") else "")
