"""Mohalla alert network (F21, plan Section 8.21): opt-in sharing of confirmed incidents.

Guardrails, each enforced here: only sites that opted in with a written agreement take part,
both ways; a share needs a *confirmed* (reviewed true), high-severity snatch / loitering / SOS;
it carries an appearance embedding, rider count and colour - never an image; it reaches only
opted-in sites within *both* sites' radius; it expires after 2 h and embeddings after 24 h
(deleted, not hidden); every share is audited; opting out stops sharing at once and withdraws
what this site shared. Neighbours match on their own edge and only tell their own guard.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

from jikimi_contracts.network import (
    EMBEDDING_HOURS,
    SHARE_HOURS,
    BikeEmbedding,
    NetworkBundle,
    NetworkSettings,
    NetworkShare,
    NetworkStatus,
)
from jikimi_crypto import Signer, canonicalize
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core import audit
from ..db.models import Alert, AlertEmbedding, NetworkShareRow, Site

SHARED_TYPES = ("snatch", "loitering", "sos")


def settings_of(site: Site) -> NetworkSettings:
    raw = dict((site.config or {}).get("network") or {})
    raw.setdefault("lat", site.lat)
    raw.setdefault("lon", site.lon)
    return NetworkSettings.model_validate(raw)


def km(a: NetworkSettings, b: NetworkSettings) -> float | None:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return None
    p1, p2 = math.radians(a.lat or 0), math.radians(b.lat or 0)
    dp, dl = p2 - p1, math.radians((b.lon or 0) - (a.lon or 0))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def neighbors(db: Session, site: Site) -> list[tuple[Site, float]]:
    me = settings_of(site)
    if not me.opted_in:
        return []
    out = []
    for other in db.scalars(select(Site).where(Site.id != site.id)).all():
        them = settings_of(other)
        d = km(me, them)
        if them.opted_in and d is not None and d <= min(me.radius_km, them.radius_km):
            out.append((other, round(d, 2)))
    return out


def update_settings(db: Session, site: Site, new: NetworkSettings, actor: str, now: datetime) -> NetworkSettings:
    if new.opted_in and (not new.agreement or new.lat is None or new.lon is None):
        raise ValueError("opting in needs the signed agreement and the site's location")
    was = settings_of(site).opted_in
    site.config = {**(site.config or {}), "network": new.model_dump(mode="json")}
    site.lat, site.lon = new.lat, new.lon
    if was and not new.opted_in:  # leaving: withdraw what this site shared, forget kept embeddings
        db.execute(delete(NetworkShareRow).where(NetworkShareRow.from_site == site.id))
        db.execute(delete(AlertEmbedding).where(AlertEmbedding.site_id == site.id))
    audit.record(
        db, "network.settings", actor, site.id, {"opted_in": new.opted_in, "radius_km": new.radius_km}, site.tenant_id
    )
    return new


def keep_embedding(db: Session, site: Site, e: BikeEmbedding, now: datetime) -> bool:
    """Store a bike alert's embedding for 24 h, only if the site takes part."""
    if not settings_of(site).opted_in or e.site_id != site.id:
        return False
    row = db.get(AlertEmbedding, e.alert_id) or AlertEmbedding(alert_id=e.alert_id, site_id=site.id, descriptor_b64="")
    row.descriptor_b64, row.riders, row.color = e.descriptor_b64, e.riders, e.color
    row.expires_at = now + timedelta(hours=EMBEDDING_HOURS)
    db.add(row)
    return True


def on_confirmed(db: Session, a: Alert, actor: str, now: datetime) -> int:
    """A reviewer marked ``a`` true: share it with the neighbours if every rule allows it."""
    if a.type not in SHARED_TYPES or a.severity != "high":
        return 0
    site = db.get(Site, a.site_id)
    emb = db.get(AlertEmbedding, a.id)
    if site is None or emb is None or emb.expires_at < now:
        return 0
    sent = 0
    for other, d in neighbors(db, site):
        sid = hashlib.sha256(f"{a.id}:{other.id}".encode()).hexdigest()[:24]
        if db.get(NetworkShareRow, sid) is not None:
            continue
        db.add(
            NetworkShareRow(
                id=sid,
                from_site=site.id,
                to_site=other.id,
                alert_id=a.id,
                alert_type=a.type,
                riders=emb.riders,
                color=emb.color,
                descriptor_b64=emb.descriptor_b64,
                distance_km=d,
                seen_at=a.ts_end,
                created_at=now,
                expires_at=now + timedelta(hours=SHARE_HOURS),
            )
        )
        sent += 1
    if sent:
        audit.record(db, "network.share", actor, str(a.id), {"sites": sent, "type": a.type}, site.tenant_id)
    return sent


def bundle(db: Session, site_id: str, signer: Signer, now: datetime) -> NetworkBundle:
    site = db.get(Site, site_id)
    opted = site is not None and settings_of(site).opted_in
    rows = (
        db.scalars(
            select(NetworkShareRow)
            .where(NetworkShareRow.to_site == site_id, NetworkShareRow.expires_at > now)
            .order_by(NetworkShareRow.created_at)
        ).all()
        if opted
        else []
    )
    shares = [
        NetworkShare(
            id=r.id,
            alert_type=r.alert_type,
            riders=r.riders,
            color=r.color,
            descriptor_b64=r.descriptor_b64,
            seen_at=r.seen_at,
            expires_at=r.expires_at,
            distance_km=r.distance_km,
        )
        for r in rows
    ]
    version = hashlib.sha256(canonicalize([opted, *[s.id for s in shares]])).hexdigest()[:16]
    unsigned = NetworkBundle(
        site_id=site_id,
        version=version,
        opted_in=opted,
        shares=shares,
        key_id=signer.key_id,
        public_key=signer.public_key,
        signed_at=now,
        signature="",
    )
    return unsigned.model_copy(update={"signature": signer.sign(unsigned.signing_payload())})


def status(db: Session, site: Site, now: datetime) -> NetworkStatus:
    since = now - timedelta(hours=24)
    sent = db.scalar(
        select(func.count())
        .select_from(NetworkShareRow)
        .where(NetworkShareRow.from_site == site.id, NetworkShareRow.created_at >= since)
    )
    received = db.scalar(
        select(func.count())
        .select_from(NetworkShareRow)
        .where(NetworkShareRow.to_site == site.id, NetworkShareRow.expires_at > now)
    )
    return NetworkStatus(
        settings=settings_of(site),
        neighbors=len(neighbors(db, site)),
        shares_sent_24h=sent or 0,
        shares_received_active=received or 0,
    )


def purge(db: Session, now: datetime) -> int:
    """Expired shares and embeddings are deleted, not hidden."""
    a = db.execute(delete(NetworkShareRow).where(NetworkShareRow.expires_at <= now)).rowcount or 0
    b = db.execute(delete(AlertEmbedding).where(AlertEmbedding.expires_at <= now)).rowcount or 0
    return int(a + b)
