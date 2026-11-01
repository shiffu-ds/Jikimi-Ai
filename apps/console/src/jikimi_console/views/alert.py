"""One alert, opened from the register: what was seen, why it was raised, what happened since."""

from __future__ import annotations

import streamlit as st

from jikimi_console import api, ui

EVENT_WORDS = {
    "ingested": "edge se pohancha",
    "created": "edge se pohancha",
    "acked": "dekh liya",
    "reviewed": "jaiza liya",
    "clip_ready": "clip aa gaya",
    "evidence": "saboot bana",
    "clip_received": "clip aa gaya",
    "sms_sent": "SMS bheja",
    "verified": "tasdeeq hui",
    "verify_requested": "tasdeeq ki darkhwast",
    "verify_skipped": "tasdeeq chhor di",
    "verify_timeout": "tasdeeq ka waqt guzar gaya",
    "need_help": "madad maangi",
    "superseded": "nayi upgrade ne jagah li",
    "network_shared": "padosiyon se share",
    "opened": "alert khula",
    "notified": "guard ko ittila",
    "sms": "SMS bheja",
    "escalated": "aage barhaya",
    "ack": "dekh liya",
    "review": "jaiza",
    "verify": "tasdeeq",
    "clip": "clip aa gaya",
    "sos": "SOS",
}


def actions(a: dict, key: str) -> None:
    perms = set((st.session_state.get("user") or {}).get("permissions") or [])
    c1, c2, c3, c4 = st.columns(4)
    if a["status"] in ("open", "escalated", "verifying") and c1.button(
        "Dekh liya", key=f"ack{key}", type="primary", use_container_width=True
    ):
        api.post(f"/v1/alerts/{a['id']}/ack", {"note": None})
        st.rerun()
    if "alerts:review" in perms or (st.session_state.get("user") or {}).get("role") in ("supervisor", "admin", "owner"):
        if c2.button("Sahi tha", key=f"t{key}", use_container_width=True):
            api.post(f"/v1/alerts/{a['id']}/review", {"verdict": "true", "notes": None})
            st.rerun()
        if c3.button("Ghalat alarm", key=f"f{key}", use_container_width=True):
            api.post(f"/v1/alerts/{a['id']}/review", {"verdict": "false", "notes": None})
            st.rerun()
        if c4.button("Saboot banayein", key=f"e{key}", use_container_width=True):
            ev = api.post("/v1/evidence", {"alert_ids": [a["id"]]})
            st.success(f"Saboot {ev['id']} ban gaya — 'Saboot' wale safhe par dekhein.")


@st.dialog("Alert ki tafseel", width="large")
def show(alert_id: str) -> None:
    a = api.get(f"/v1/alerts/{alert_id}", fresh=True)
    tok = api.token()
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem">'
        f'<div><b style="font-size:1.25rem">{ui.esc(ui.type_label(a["type"], a.get("features"), "en"))}</b>'
        f'<div class="quiet">{ui.esc(a.get("camera_name") or a["camera_id"])} · {ui.local(a["ts_end"]):%d %b, %H:%M:%S} · code {ui.esc(a["short_code"])}</div></div>'
        f"<div>{ui.stamp(a['status'])}</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ur" style="font-size:1.35rem;text-align:right;line-height:2.3;margin:.3rem 0 .9rem">{ui.esc(a.get("explanation_ur"))}</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.5, 1])
    with left:
        clip = api.media(a.get("clip_url") or "", tok) if a.get("has_clip") else None
        if clip:
            st.video(clip, format="video/mp4")
            st.caption(
                "Clip edge par hi dhundla kiya gaya (sar aur chehre) · "
                + ("dastakhat durust" if a.get("signature_valid") else "dastakhat ki jaanch baqi")
            )
        else:
            frames = [api.media(u, tok) for u in (a.get("keyframe_urls") or [])[:3]]
            frames = [f for f in frames if f]
            if frames:
                st.image(frames, use_container_width=True)
            else:
                st.info("Is alert ka clip abhi nahi aaya (edge 10 second ki post-roll ke baad bhejta hai).")
    with right:
        ui.section("Kyun?")
        if a.get("p_value_text_ur"):
            st.markdown(
                f'<div class="ur" style="text-align:right;color:#0f5e4f">{ui.esc(a["p_value_text_ur"])}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="quiet">score {a.get("raw_score") or 0:.3f} · p = {format(a["p_value"], ".4f") if a.get("p_value") is not None else "—"} · {ui.esc(a.get("route"))} · {ui.esc(a.get("severity"))}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"_{a.get('explanation_roman') or ''}_")
        st.caption(a.get("explanation_en") or "")
    actions(a, alert_id)
    with st.expander("Kya kya hua (timeline)", expanded=True):
        for ev in a.get("events") or []:
            t = ui.local(ev["at"])
            who = ev.get("actor") or ""
            st.markdown(
                f"`{t:%H:%M:%S}` &nbsp; {EVENT_WORDS.get(ev['kind'], ev['kind'])} &nbsp; <span class='quiet'>{ui.esc(who)} {ui.esc(ev.get('channel') or '')}</span>",
                unsafe_allow_html=True,
            )
        for r in a.get("reviews") or []:
            st.markdown(
                f"**Jaiza:** {r['verdict']} — {ui.esc(r.get('reviewer'))} {ui.esc(r.get('notes') or '')}",
                unsafe_allow_html=True,
            )
    with st.expander("Tafseelaat (jo edge ne naapa)"):
        feats = {
            k: v
            for k, v in (a.get("features") or {}).items()
            if not isinstance(v, dict | list) and k not in ("dedupe_key",)
        }
        st.dataframe(
            [{"cheez": k, "qeemat": str(v)} for k, v in feats.items()], hide_index=True, use_container_width=True
        )
        if a.get("clip_sha256"):
            st.code(f"clip sha256 {a['clip_sha256']}\nedge key   {a.get('device_key_id')}", language=None)
