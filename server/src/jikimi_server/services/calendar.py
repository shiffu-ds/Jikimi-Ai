"""Event-mode calendar (F16): Pakistani event estimates, confirmed windows, the signed edge bundle."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

from jikimi_common import hijri
from jikimi_contracts.modes import CalendarBundle, CalendarOut, ModeWindow, mode_on
from jikimi_crypto import Signer, canonicalize
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ModeWindowRow
from .devices import edge_reports, rush_ratio

HISTORY_DAYS = 30
ESTIMATE_DAYS = 365
SIGHTING_DAYS = 2


def estimates(start: date, end: date) -> list[ModeWindow]:
    """National and religious events overlapping ``start..end`` (tabular Hijri, +-1 day)."""
    out: list[ModeWindow] = []
    first = hijri.from_gregorian(start)[0]
    for hy in range(first - 1, first + 3):
        eid_fitr = hijri.to_gregorian(hy, 10, 1)
        eid_adha = hijri.to_gregorian(hy, 12, 10)
        for name, mode, starts, ends in (
            (f"Ramadan {hy}", "ramadan", hijri.to_gregorian(hy, 9, 1), eid_fitr - timedelta(days=1)),
            (f"Chand Raat {hy}", "chand_raat", eid_fitr - timedelta(days=1), eid_fitr - timedelta(days=1)),
            (f"Eid ul Fitr {hy}", "eid", eid_fitr, eid_fitr + timedelta(days=2)),
            (f"Eid ul Adha {hy}", "eid", eid_adha, eid_adha + timedelta(days=2)),
            (
                f"Muharram 9-10, {hy + 1}",
                "muharram",
                hijri.to_gregorian(hy + 1, 1, 9),
                hijri.to_gregorian(hy + 1, 1, 10),
            ),
        ):
            out.append(ModeWindow(name=name, mode=mode, starts=starts, ends=ends, source="estimate"))  # type: ignore[arg-type]
    for year in range(start.year, end.year + 1):
        day = date(year, 8, 14)
        out.append(
            ModeWindow(name=f"14 August {year}", mode="independence_day", starts=day, ends=day, source="estimate")
        )
    return sorted((w for w in out if w.ends >= start and w.starts <= end), key=lambda w: (w.starts, w.ends))


def to_out(row: ModeWindowRow) -> ModeWindow:
    return ModeWindow(
        id=row.id,
        name=row.name,
        mode=row.mode,  # type: ignore[arg-type]
        starts=row.starts,
        ends=row.ends,
        source="admin",
        confirmed_by=row.confirmed_by,
    )


def confirmed(db: Session, site_id: str, since: date) -> list[ModeWindow]:
    rows = db.scalars(
        select(ModeWindowRow)
        .where(ModeWindowRow.site_id == site_id, ModeWindowRow.ends >= since)
        .order_by(ModeWindowRow.starts, ModeWindowRow.id)
    ).all()
    return [to_out(r) for r in rows]


def calendar_version(windows: list[ModeWindow]) -> str:
    return hashlib.sha256(canonicalize([w.model_dump(mode="json") for w in windows])).hexdigest()[:16]


def calendar(db: Session, site_id: str, today: date, now: datetime | None = None) -> CalendarOut:
    windows = confirmed(db, site_id, today - timedelta(days=HISTORY_DAYS))
    reported = edge_reports(db, site_id, "calendar_bundle", now or datetime.now(UTC))
    # an estimate is settled once a confirmed window of the same mode overlaps it or starts within
    # SIGHTING_DAYS of it (the moon was seen a day early or late)
    pending = [
        e
        for e in estimates(today, today + timedelta(days=ESTIMATE_DAYS))
        if not any(
            w.mode == e.mode
            and ((w.starts <= e.ends and e.starts <= w.ends) or abs((w.starts - e.starts).days) <= SIGHTING_DAYS)
            for w in windows
        )
    ]
    return CalendarOut(
        site_id=site_id,
        today=today,
        current_mode=mode_on(windows, today),  # type: ignore[arg-type]
        windows=windows,
        estimates=pending,
        edge_synced=None if reported is None else calendar_version(windows) in reported,
        rush_ratio=rush_ratio(db, site_id, now or datetime.now(UTC)),
    )


def bundle(db: Session, site_id: str, today: date, signer: Signer, now: datetime) -> CalendarBundle:
    windows = confirmed(db, site_id, today - timedelta(days=HISTORY_DAYS))
    version = calendar_version(windows)
    unsigned = CalendarBundle(
        site_id=site_id,
        version=version,
        windows=windows,
        key_id=signer.key_id,
        public_key=signer.public_key,
        signed_at=now,
        signature="",
    )
    return unsigned.model_copy(update={"signature": signer.sign(unsigned.signing_payload())})
