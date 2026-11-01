"""Qawaid aur mausam: rules written in Roman Urdu, and the event calendar (Ramzan, Eid, ...)."""

from __future__ import annotations

from datetime import date

import streamlit as st

from jikimi_console import api, ui

MODES = {
    "ramadan": "Ramzan",
    "chand_raat": "Chand Raat",
    "eid": "Eid",
    "muharram": "Muharram",
    "independence_day": "14 August",
    "bazaar_day": "Bazaar ka din",
    "normal": "Aam din",
}


def _plain(v: object) -> str:
    """A rule part as a few words ("23:00-05:00", "gate-2"), not a JSON blob."""
    if isinstance(v, dict):
        if "start" in v and "end" in v:
            return f"{v['start']}–{v['end']}"
        return " ".join(_plain(x) for x in v.values() if x not in (None, [], {}))[:60]
    if isinstance(v, list):
        return ", ".join(_plain(x) for x in v)[:60]
    return "" if v is None else str(v)


def page() -> None:
    site_id = st.session_state.get("site_id")
    role = st.session_state["user"]["role"]
    ui.head(
        "Qawaid aur mausam",
        "قواعد اور موسم",
        "Apni zubaan mein qaida likhein; admin ki manzoori ke baad hi camere par chalta hai",
    )
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        text = st.text_input("Naya qaida", placeholder="raat 11 ke baad gate 2 par koi 5 min se zyada ruke to batao")
        if text:
            d = api.post("/v1/rules/draft", {"site_id": site_id, "text": text})
            if d.get("questions"):
                st.warning("Pehle yeh batayein: " + " · ".join(d["questions"]))
            for e in d.get("errors") or []:
                st.error(e)
            if d.get("valid") and d.get("rule"):
                r = d["rule"]
                st.markdown(
                    f'<div class="sentence"><div class="ur" style="text-align:right;font-size:1.3rem">{ui.esc(r.get("name_ur"))}</div>'
                    f"{ui.esc(r.get('name_en'))}</div>",
                    unsafe_allow_html=True,
                )
                und = {k: _plain(v) for k, v in (d.get("understood") or {}).items()}
                und = {k: v for k, v in und.items() if v}
                if und:
                    st.markdown(
                        " ".join(f'<span class="tag">{ui.esc(k)}: {ui.esc(v)}</span>' for k, v in und.items()),
                        unsafe_allow_html=True,
                    )
                bt = d.get("backtest") or {}
                if bt:
                    st.markdown(
                        f"Pichle **{bt.get('days', 7)} din** ki footage par yeh qaida **{bt.get('matches', 0)}** martaba chalta "
                        f"({bt.get('tracks_checked', 0)} tracks dekhe)."
                    )
                if st.button("Manzoori ke liye bhejein", type="primary"):
                    api.post("/v1/rules", {"rule": r})
                    st.success("Bhej diya — admin ki manzoori ke baad dastakhat ke saath edge tak jayega.")
        ui.section("Is site ke qawaid")
        rules = api.get("/v1/rules", site_id=site_id) or []
        if not rules:
            st.caption("Abhi koi qaida nahi.")
        for r in rules:
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            on_edge = " · edge par maujood" if r.get("on_edge") else ""
            c1.markdown(
                f"**{ui.esc(r['rule'].get('name_en'))}** <span class='quiet'>· {r['status']} · v{r['version']}{on_edge}</span>",
                unsafe_allow_html=True,
            )
            if (
                role in ("admin", "owner")
                and r["status"] == "pending"
                and c2.button("Manzoor", key=f"ap{r['rule_id']}")
            ):
                api.post(f"/v1/rules/{r['rule_id']}/approve")
                st.rerun()
            if r["status"] == "active" and c2.button("Band karein", key=f"ds{r['rule_id']}"):
                api.post(f"/v1/rules/{r['rule_id']}/disable")
                st.rerun()
    with right:
        ui.section("Mausam (event modes)")
        cal = api.get(f"/v1/sites/{site_id}/calendar") or {}
        st.markdown(
            f"Aaj: **{MODES.get(cal.get('current_mode'), cal.get('current_mode'))}**"
            + (f" · rush {cal['rush_ratio']:.1f}× aam din se" if cal.get("rush_ratio") else "")
        )
        st.caption(
            "Ramzan ya Chand Raat par rush aam baat hai; har mausam ka apna 'normal' hota hai taake ghalat alarm na barhein."
        )
        for w in cal.get("windows") or []:
            c1, c2 = st.columns([2.4, 1], vertical_alignment="center")
            c1.markdown(
                f"✓ **{ui.esc(w['name'])}**<br><span class='quiet'>{w['starts']} → {w['ends']}"
                f" · {ui.esc(w.get('confirmed_by') or '')}</span>",
                unsafe_allow_html=True,
            )
            if c2.button("Hatao", key=f"rm{w.get('id')}", use_container_width=True):
                api.post(f"/v1/sites/{site_id}/calendar/{w['id']}", method="DELETE")
                st.rerun()
        ui.section("Aane wale andaze")
        st.caption("Chaand dekhne ke baad tasdeeq karein.")
        for i, w in enumerate((cal.get("estimates") or [])[:6]):
            c1, c2 = st.columns([2.4, 1], vertical_alignment="center")
            c1.markdown(
                f"**{ui.esc(w['name'])}**<br><span class='quiet'>{w['starts']} → {w['ends']}</span>",
                unsafe_allow_html=True,
            )
            if c2.button("Tasdeeq", key=f"cf{i}", use_container_width=True):
                api.post(
                    f"/v1/sites/{site_id}/calendar",
                    {"name": w["name"], "mode": w["mode"], "starts": w["starts"], "ends": w["ends"]},
                )
                st.rerun()
        with st.expander("Apna mausam shamil karein (maslan Itwar bazaar)"):
            name = st.text_input("Naam")
            mode = st.selectbox("Qism", list(MODES), format_func=MODES.get)
            span = st.date_input("Kab se kab tak", value=(date.today(), date.today()))
            if st.button("Shamil karein") and name and isinstance(span, tuple) and len(span) == 2:
                api.post(
                    f"/v1/sites/{site_id}/calendar",
                    {"name": name, "mode": mode, "starts": str(span[0]), "ends": str(span[1])},
                )
                st.rerun()
