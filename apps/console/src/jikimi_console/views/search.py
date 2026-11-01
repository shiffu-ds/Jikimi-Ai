"""Talash aur sawal: search footage in Roman Urdu, then ask the investigation agent about it."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from jikimi_console import api, ui

MARK = str(Path(__file__).resolve().parents[1] / "static" / "mark.png")


def thumbs(clips: list[dict], key: str, per_row: int = 5, most: int = 15) -> None:
    cols = st.columns(per_row)
    for i, c in enumerate(clips[:most]):
        with cols[i % per_row]:
            img = api.media(c.get("thumbnail_url") or "", api.token())
            if img:
                st.image(img, use_container_width=True)
            else:
                st.markdown('<div class="chit" style="text-align:center">tasveer nahi</div>', unsafe_allow_html=True)
            t = ui.local(c.get("ts_start"))
            objs = ", ".join(f"{o.get('color') or ''} {o.get('type')}".strip() for o in (c.get("objects") or [])[:2])
            st.caption(
                f"{c.get('camera_name') or c.get('camera_id')} · {t:%d %b %H:%M}" + (f" · {objs}" if objs else "")
            )


def page() -> None:
    site_id = st.session_state.get("site_id")
    ui.head("Talash aur sawal", "تلاش اور سوال", "Jaise aap bolte hain waise likhein — Roman Urdu, Urdu ya English")
    tab1, tab2 = st.tabs(["Talash", "Tafteesh se baat"])
    with tab1:
        try:
            examples = (api.get("/v1/search/examples") or {}).get("examples", [])
        except api.ApiError:
            examples = []
        q = st.text_input("Kya dhoondna hai?", placeholder="kal raat kaali bike 2 sawar gate pe", key="q")
        if examples:
            pick = st.pills("Misalen", examples[:6], key="qpick")
            q = pick or q
        if q:
            res = api.post("/v1/search", {"site_id": site_id, "query": q, "limit": 24})
            p = res.get("parsed") or {}
            st.markdown(
                f'<div class="sentence">Samjha: <b>{ui.esc(p.get("text_en") or q)}</b>'
                f' <span class="quiet">· {len(res.get("results") or [])} nateeje, {res.get("took_ms", 0):.0f} ms</span></div>',
                unsafe_allow_html=True,
            )
            if p.get("unknown_tokens"):
                st.caption("Yeh alfaaz samajh nahi aaye: " + ", ".join(p["unknown_tokens"]))
            thumbs(res.get("results") or [], "s")
    with tab2:
        st.caption("Tafteesh sirf parhti hai, kuch badalti nahi; har jawab ke saath uske clips ka hawala hota hai.")
        hist = st.session_state.setdefault("agent_hist", [])
        for who, msg, clips in hist:
            with st.chat_message("user" if who == "you" else "assistant", avatar=None if who == "you" else MARK):
                st.markdown(msg, unsafe_allow_html=True)
                if clips:
                    thumbs(clips, f"a{len(msg)}", per_row=7, most=7)
        ask = st.chat_input("Poochein — maslan: ye bike aur kahan dekhi gayi?")
        if ask:
            reply = api.post(
                "/v1/agent", {"site_id": site_id, "message": ask, "context": st.session_state.get("agent_ctx")}
            )
            st.session_state["agent_ctx"] = reply.get("context")
            hist.append(("you", ask, []))
            text = reply.get("answer_roman") or reply.get("answer_en")
            if reply.get("answer_ur"):
                text = f'{text}\n\n<div class="ur" style="text-align:right">{ui.esc(reply["answer_ur"])}</div>'
            if reply.get("draft_report"):
                text += f"\n\n```\n{reply['draft_report']}\n```"
            hist.append(("agent", text, reply.get("citations") or []))
            st.rerun()
        if hist and st.button("Nayi baat shuru karein"):
            st.session_state["agent_hist"] = []
            st.session_state.pop("agent_ctx", None)
            st.rerun()
