"""Roman Urdu search (F1). Lexicon first; LLM fallback only for low-coverage queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from jikimi_contracts.search import AgentReply, AgentTurn, SearchRequest, SearchResponse

from ...core import audit
from ...db.models import Camera, Site
from ...services import agent as agent_svc
from ..deps import DB, Ctx, Principal, check_site, require

router = APIRouter(prefix="/v1", tags=["search"])
CanSearch = Annotated[Principal, Depends(require("search"))]

EXAMPLES = [
    "kal raat kaali bike 2 sawar gate pe",
    "aaj subah laal gaari",
    "pichle 2 ghante mein bina helmet bike",
    "chheena jhapti wali clips",
    "raat 11 baje ke baad gate par chakkar",
    "کل رات کالی موٹر سائیکل",
    "double sawari neeli honda",
]


@router.get("/search/examples")
def examples(_: CanSearch) -> dict[str, list[str]]:
    return {"examples": EXAMPLES}


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, p: CanSearch, ctx: Ctx, db: DB) -> SearchResponse:
    check_site(p, body.site_id)
    site = db.get(Site, body.site_id)
    assert site is not None
    now = datetime.now(UTC).astimezone(ZoneInfo(site.timezone))
    vocab = ctx.search.site_vocab(db, site.id)
    parsed = ctx.search.parser.parse(body.query, now, vocab)
    if parsed.coverage < 0.6 and ctx.llm is not None:
        cams = [c.id for c in db.query(Camera).filter(Camera.site_id == site.id)]
        llm = ctx.llm.parse(body.query, cams)
        if llm:
            parsed = ctx.llm.merge(parsed, llm, cams)
    res = ctx.search.search(db, site.id, body.query, now, body.limit, parsed=parsed)
    audit.record(
        db,
        "search",
        p.name,
        site.id,
        {"query": body.query[:200], "results": len(res.results), "path": parsed.parser_path},
        p.user.tenant_id,
    )
    return res


@router.post("/agent", response_model=AgentReply)
def agent(body: AgentTurn, p: CanSearch, ctx: Ctx, db: DB) -> AgentReply:
    """F1 Tier 2: one turn of a multi-turn investigation (read-only tools, cited answers)."""
    check_site(p, body.site_id)
    site = db.get(Site, body.site_id)
    assert site is not None
    return agent_svc.turn(db, ctx.search, site, p.name, p.user.tenant_id, body.message, body.context, datetime.now(UTC))
