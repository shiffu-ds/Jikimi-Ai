"""Jikimi Analyst agent (F1 Tier 2, plan Section 8.6): multi-turn investigation in Roman Urdu,
Urdu or English, over read-only tools.

The planner is deterministic (no LLM is needed, so it runs on the laptop): the search parser
reads each turn, and follow-ups refer to the previous answer - "ye bike aur kahan dekhi gayi",
"pehla clip dikhao", "report banao". Tools: ``search_clips``, ``get_trajectory``, ``get_clip``,
``camera_map``, ``draft_evidence_report``. Guardrails from the plan: tools only read (the report is
a draft; exporting or sharing stays a human's button on the Evidence page); at most 8 tool calls
per turn; every claim cites clip ids of this site (an answer without citations becomes "nothing
found"); the client's context is re-checked against the user's sites; every turn is audited.

``get_trajectory`` is honest about what it knows: "the same bike" only for the same anonymous
entity on one camera; on other cameras it reports bikes of the same colour and rider count within
30 minutes as *similar*, because the server never stores appearance embeddings.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jikimi_common.explain import object_names
from jikimi_contracts.search import AgentContext, AgentReply, ClipRef, ToolCall
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core import audit
from ..db.models import Alert, Camera, ClipIndex, Site

MAX_TOOL_CALLS = 8
FOLLOW = (
    "aur kahan", "aage kahan", "kahan gay", "kahan gai", "kis taraf", "isi bike", "yahi bike", "same bike",
    "where else", "where did", "اور کہاں", "کہاں گئی", "کہاں گیا", "کس طرف",
)  # fmt: skip
CLIP = ("clip", "video", "dikhao", "dikha", "show", "کلپ", "ویڈیو", "دکھاؤ", "دکھائیں")
REPORT = ("report", "fir", "rapat", "evidence", "رپورٹ", "ثبوت")
CAMERAS = ("camera kaun", "kaun se camera", "cameras", "naqsha", "map", "کون سے کیمرے", "نقشہ")
ORDINAL = {
    "pehla": 0, "pehli": 0, "first": 0, "پہلا": 0, "پہلی": 0, "doosra": 1, "dusra": 1, "second": 1, "دوسرا": 1,
    "teesra": 2, "tesra": 2, "third": 2, "تیسرا": 2, "aakhri": -1, "last": -1, "آخری": -1,
}  # fmt: skip


class Agent:
    def __init__(self, db: Session, search: Any, site: Site, actor: str, tenant_id: Any) -> None:
        self.db, self.search, self.site, self.actor, self.tenant_id = db, search, site, actor, tenant_id
        self.tz = ZoneInfo(site.timezone or "Asia/Karachi")
        self.tools: list[ToolCall] = []
        self.parsed: Any = None
        self.cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.site_id == site.id))}

    # ---------------------------------------------------------------------------- tools
    def _call(self, name: str, args: dict[str, object], fn: Any) -> Any:
        if len(self.tools) >= MAX_TOOL_CALLS:
            raise RuntimeError("tool budget used up")
        t0 = time.perf_counter()
        out = fn()
        n = len(out) if isinstance(out, list) else int(out is not None)
        self.tools.append(ToolCall(name=name, args=args, results=n, ms=round((time.perf_counter() - t0) * 1000, 1)))
        return out

    def ref(self, row: ClipIndex) -> ClipRef:
        alert = self.db.get(Alert, row.alert_id) if row.alert_id else None
        cam = self.cams.get(row.camera_id)
        return ClipRef(
            clip_id=row.ref,
            kind="alert" if row.kind == "alert" else "track",
            alert_id=row.alert_id,
            alert_type=row.alert_type,
            camera_id=row.camera_id,
            camera_name=cam.name if cam else None,
            ts_start=row.ts_start,
            ts_end=row.ts_end,
            score=1.0,
            thumbnail_url=f"/v1/media/thumbs/{row.id}.jpg" if row.thumbnail_uri else None,
            clip_url=f"/v1/media/clips/{alert.id}.mp4" if alert is not None and alert.clip_uri else None,
            objects=row.objects or [],
        )

    def search_clips(self, query: str, now: datetime, limit: int = 10) -> list[ClipRef]:
        def run() -> list[ClipRef]:
            res = self.search.search(self.db, self.site.id, query, now, limit)
            self.parsed = res.parsed
            return list(res.results)

        return self._call("search_clips", {"query": query, "limit": limit}, run)

    def get_trajectory(self, row: ClipIndex, window_min: int = 30) -> list[tuple[ClipIndex, bool]]:
        def run() -> list[tuple[ClipIndex, bool]]:
            obj = (row.objects or [{}])[0]
            lo, hi = row.ts_start - timedelta(minutes=window_min), row.ts_end + timedelta(minutes=window_min)
            cands = self.db.scalars(
                select(ClipIndex)
                .where(
                    ClipIndex.site_id == self.site.id,
                    or_(ClipIndex.entity_id == row.entity_id, (ClipIndex.ts_start <= hi) & (ClipIndex.ts_end >= lo)),
                )
                .order_by(ClipIndex.ts_start)
                .limit(400)
            ).all()
            out = []
            for c in cands:
                if c.id == row.id:
                    continue
                if row.entity_id and c.entity_id == row.entity_id:
                    out.append((c, True))
                    continue
                o = (c.objects or [{}])[0]
                same_look = o.get("type") == obj.get("type") and o.get("color") == obj.get("color") and obj.get("color")
                if c.camera_id != row.camera_id and same_look and o.get("riders") == obj.get("riders"):
                    out.append((c, False))
            return out[:10]

        return self._call("get_trajectory", {"clip_id": row.ref, "window_min": window_min}, run)

    def get_clip(self, clip_id: str) -> ClipIndex | None:
        return self._call(
            "get_clip",
            {"clip_id": clip_id},
            lambda: self.db.scalar(
                select(ClipIndex).where(ClipIndex.site_id == self.site.id, ClipIndex.ref == clip_id)
            ),
        )

    def camera_map(self) -> list[Camera]:
        return self._call("camera_map", {"site_id": self.site.id}, lambda: list(self.cams.values()))

    def draft_evidence_report(self, alert_ids: list[Any]) -> list[Alert]:
        return self._call(
            "draft_evidence_report",
            {"alerts": len(alert_ids)},
            lambda: [a for i in alert_ids if (a := self.db.get(Alert, i)) is not None and a.site_id == self.site.id],
        )

    # ---------------------------------------------------------------------------- helpers
    def when(self, dt: datetime) -> str:
        return dt.astimezone(self.tz).strftime("%d %b %H:%M")

    def cam_names(self, camera_id: str) -> tuple[str, str]:
        c = self.cams.get(camera_id)
        return ((c.name_ur or c.name) if c else camera_id, (c.name_roman or c.name) if c else camera_id)

    def describe(self, r: ClipRef | ClipIndex) -> tuple[str, str, str]:
        o = (r.objects or [{}])[0]
        ur, ro, en = object_names(str(o.get("type", "motorcycle")), o.get("color"))
        n = o.get("riders")
        if n:
            ur, ro, en = f"{ur} ({n} سوار)", f"{ro} ({n} sawar)", f"{en} ({n} riders)"
        return ur, ro, en

    def known(self, context: AgentContext | None) -> list[ClipIndex]:
        """The previous turn's clips, re-checked: only this site's, in the client's order."""
        if not context or not context.clip_ids:
            return []
        rows = self.db.scalars(
            select(ClipIndex).where(ClipIndex.site_id == self.site.id, ClipIndex.ref.in_(context.clip_ids))
        ).all()
        by_ref = {r.ref: r for r in rows}
        return [by_ref[c] for c in context.clip_ids if c in by_ref]


def _exact(r: ClipRef, parsed: Any) -> bool:
    """Every attribute the question asked for matches exactly (not "~similar")."""
    if parsed is None:
        return True
    if parsed.zones and not any(f"zone:{z}" in r.matched for z in parsed.zones):
        return False
    for q in parsed.objects:
        for name in ("color", "riders"):
            want = getattr(q, name, None)
            if want and f"{name}:{want}" not in r.matched:
                return False
    return True


def _pick(msg: str, rows: list[ClipIndex]) -> ClipIndex | None:
    if not rows:
        return None
    for word, i in ORDINAL.items():
        if word in msg:
            return rows[i] if -len(rows) <= i < len(rows) else None
    return rows[0]


def turn(
    db: Session,
    search: Any,
    site: Site,
    actor: str,
    tenant_id: Any,
    message: str,
    context: AgentContext | None,
    now: datetime,
) -> AgentReply:
    ag = Agent(db, search, site, actor, tenant_id)
    msg = message.lower().strip()
    prev = ag.known(context)
    local_now = now.astimezone(ag.tz)
    citations: list[ClipRef] = []
    report: str | None = None
    count: int | None = None
    if any(k in msg for k in CAMERAS):
        intent = "camera_map"
        cams = ag.camera_map()
        zones = [f"{c.name} ({', '.join(z.get('name') or z['id'] for z in c.zones or []) or '-'})" for c in cams]
        ur = "اس سائٹ کے کیمرے: " + "؛ ".join(f"{c.name_ur or c.name}" for c in cams)
        ro = en = "Cameras: " + "; ".join(zones)
    elif any(k in msg for k in REPORT):
        intent = "report"
        rows = prev or [
            r for r in (ag.get_clip(c.clip_id) for c in ag.search_clips(message, local_now)) if r is not None
        ]
        alerts = ag.draft_evidence_report([r.alert_id for r in rows if r.alert_id])
        citations = [ag.ref(r) for r in rows if r.alert_id in {a.id for a in alerts}]
        lines = [
            f"- {ag.when(a.ts_end)} | {a.camera_id} | {a.type} | {a.explanation_en or ''} | alert sha256 {a.alert_sha256 or '-'}"
            + (f" | clip sha256 {a.clip_sha256}" if a.clip_sha256 else "")
            for a in alerts
        ]
        report = "DRAFT - not exported or shared. Export the evidence pack from the Evidence page.\n" + "\n".join(lines)
        ur = f"{len(alerts)} الرٹس کی رپورٹ کا مسودہ تیار ہے؛ برآمد یا شیئر صرف ثبوت (Evidence) کے صفحے سے۔"
        ro = f"{len(alerts)} alerts ki report ka masauda tayyar hai; export ya share sirf Evidence page se."
        en = f"Drafted a report of {len(alerts)} alert(s); export or share it only from the Evidence page."
    elif prev and any(k in msg for k in FOLLOW):
        intent = "trajectory"
        row = _pick(msg, prev)
        assert row is not None
        seen = ag.get_trajectory(row)
        citations = [ag.ref(row)] + [ag.ref(c) for c, _ in seen]
        same = [c for c, s in seen if s]
        similar = [c for c, s in seen if not s]
        d_ur, d_ro, d_en = ag.describe(row)
        ur = (
            f"{d_ur}: اسی کیمرے پر یہی بائیک {len(same)} بار اور دوسرے کیمروں پر ملتی جلتی بائیک {len(similar)} بار ("
            + "، ".join(f"{ag.cam_names(c.camera_id)[0]} {ag.when(c.ts_start)}" for c in similar[:3])
            + ")۔"
        )
        ro = (
            f"{d_ro}: isi camera par yahi bike {len(same)} baar, doosre cameras par milti julti bike {len(similar)} baar ("
            + ", ".join(f"{ag.cam_names(c.camera_id)[1]} {ag.when(c.ts_start)}" for c in similar[:3])
            + ")."
        )
        en = f"{d_en}: the same bike {len(same)} more time(s) on this camera; a similar bike {len(similar)} time(s) on other cameras."
    elif prev and any(k in msg for k in CLIP):
        intent = "clip"
        row = _pick(msg, prev)
        got = ag.get_clip(row.ref) if row is not None else None
        citations = [ag.ref(got)] if got is not None else []
        name_ur, name_ro = ag.cam_names(got.camera_id) if got is not None else ("", "")
        when = ag.when(got.ts_start) if got is not None else ""
        ur, ro, en = (
            f"یہ رہا کلپ: {name_ur}، {when}۔",
            f"Ye raha clip: {name_ro}, {when}.",
            f"Here is the clip: {name_ro}, {when}.",
        )
    else:
        counting = any(k in msg for k in ("kitni", "kitne", "how many", "کتنی", "کتنے"))
        intent = "count" if counting else "find"
        res = ag.search_clips(message, local_now, limit=50 if counting else 10)
        citations = res
        if res and counting:
            exact = [r for r in res if _exact(r, ag.parsed)]  # partial matches rank, they do not count
            refs = {r.clip_id for r in exact}
            ents = dict(db.execute(select(ClipIndex.ref, ClipIndex.entity_id).where(ClipIndex.ref.in_(refs))).all())
            things = {ents.get(r.clip_id) or r.clip_id for r in exact}
            per: dict[str, int] = {}
            for r in exact:
                per[ag.cam_names(r.camera_id)[1]] = per.get(ag.cam_names(r.camera_id)[1], 0) + 1
            count = len(things)
            citations = exact
            where = ", ".join(f"{k}: {v}" for k, v in per.items())
            ur = f"{count} مختلف ({len(exact)} بار دیکھی گئیں: {where})۔"
            ro = f"{count} alag alag ({len(exact)} baar dekhi gayin: {where})."
            en = f"{count} different one(s), seen {len(exact)} time(s) ({where})."
        elif res:
            top = res[0]
            d_ur, d_ro, d_en = ag.describe(top)
            n_ur, n_ro = ag.cam_names(top.camera_id)
            ur = f"{len(res)} کلپ ملے۔ سب سے قریب: {n_ur} پر {ag.when(top.ts_start)}، {d_ur}۔"
            ro = f"{len(res)} clip mile. Sab se qareeb: {n_ro} par {ag.when(top.ts_start)}, {d_ro}."
            en = f"Found {len(res)} clip(s). Best match: {n_ro} at {ag.when(top.ts_start)}, {d_en}."
        else:
            ur = ro = en = ""
    if not citations and intent != "camera_map":  # guardrail: no claim without a clip
        ur = "کچھ نہیں ملا۔ وقت بڑھا کر دیکھیں (مثلاً 'پچھلے ہفتے') یا رنگ / کیمرہ بدلیں۔"
        ro = "Kuch nahi mila. Waqt barha kar dekhein (maslan 'pichle hafte') ya rang / camera badlein."
        en = "Nothing found. Try a longer time ('last week') or another colour / camera."
        report = None if intent == "report" else report
    reply = AgentReply(
        intent=intent,
        answer_ur=ur,
        answer_roman=ro,
        answer_en=en,
        citations=citations[:10],
        tools=ag.tools,
        context=AgentContext(clip_ids=[c.clip_id for c in citations[:20]], last_query=message[:300]),
        draft_report=report,
        count=count if intent == "count" else None,
    )
    audit.record(
        db,
        "agent.turn",
        actor,
        site.id,
        {
            "message": message[:200],
            "intent": intent,
            "tools": [t.name for t in ag.tools],
            "citations": len(reply.citations),
        },
        tenant_id,
    )
    return reply
