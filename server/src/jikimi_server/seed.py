"""Provision a site from the edge site YAML: tenant, site, cameras, users, edge device.

The device's public key is read from the edge key (same machine in the lite profile) or given
explicitly; the device API token is written to ``data/edge/keys/device.token`` (mode 0600).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jikimi_common.config import load_config
from sqlalchemy import select

from .core.security import hash_password, new_device_token, token_hash
from .db.models import Camera, Device, Site, Tenant, User
from .db.session import Database

log = logging.getLogger(__name__)

DEMO_USERS: list[dict[str, Any]] = [
    {"username": "owner", "name": "Qureshi Sahab (owner)", "role": "owner", "sites": None},
    {"username": "admin", "name": "Site admin", "role": "admin", "sites": None},
    {"username": "sana", "name": "Sana (supervisor)", "role": "supervisor", "sites": None},
    {"username": "akram", "name": "Akram (guard, gate)", "role": "guard", "sites": "site"},
    {"username": "police", "name": "Investigating officer", "role": "police_viewer", "sites": "site"},
]


@dataclass
class SeedResult:
    tenant_id: str
    site_id: str
    device_id: str
    device_token_file: Path
    users: list[str]


def write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value)


def seed_site(
    db: Database,
    edge_config: str | Path,
    password: str,
    device_public_key: str,
    device_key_id: str,
    token_file: Path,
    tenant_name: str = "Jikimi Homes Society",
) -> SeedResult:
    cfg = load_config(edge_config)
    with db.session() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == tenant_name)) or Tenant(name=tenant_name)
        s.add(tenant)
        s.flush()
        site = s.get(Site, cfg["site_id"]) or Site(
            id=cfg["site_id"], tenant_id=tenant.id, name=cfg.get("site_name", cfg["site_id"])
        )
        site.name = cfg.get("site_name", site.name)
        site.name_ur = cfg.get("site_name_ur") or "جکیمی ہومز - شمالی گیٹ"
        site.timezone = cfg.get("timezone", "Asia/Karachi")
        site.config = {k: cfg[k] for k in ("escalation", "camera_graph") if cfg.get(k)}
        s.add(site)
        s.flush()
        for c in cfg.get("cameras", []):
            cam = s.get(Camera, c["id"]) or Camera(
                id=c["id"], site_id=site.id, tenant_id=tenant.id, name=c.get("name", c["id"])
            )
            cam.name = c.get("name", c["id"])
            cam.name_ur = c.get("name_ur")
            cam.name_roman = c.get("name_roman")
            cam.zones = [
                {"id": z["id"], "name": z.get("name"), "name_ur": z.get("name_ur"), "polygon": z.get("polygon", [])}
                for z in c.get("zones") or []
            ]
            s.add(cam)
        users = []
        for u in DEMO_USERS:
            row = s.scalar(select(User).where(User.username == u["username"]))
            if row is None:
                row = User(
                    username=u["username"],
                    tenant_id=tenant.id,
                    name=u["name"],
                    role=u["role"],
                    password_hash=hash_password(password),
                )
            row.site_ids = [site.id] if u["sites"] == "site" else None
            row.role = u["role"]
            row.name = u["name"]
            s.add(row)
            users.append(u["username"])
        device_id = cfg.get("device_id") or f"edge-{site.id}"
        dev = s.get(Device, device_id)
        token = new_device_token()
        if dev is None:
            dev = Device(
                id=device_id,
                tenant_id=tenant.id,
                site_id=site.id,
                name=f"Edge {site.id}",
                public_key=device_public_key,
                key_id=device_key_id,
                token_hash=token_hash(token),
            )
        else:
            dev.public_key, dev.key_id, dev.token_hash, dev.status = (
                device_public_key,
                device_key_id,
                token_hash(token),
                "active",
            )
        s.add(dev)
        write_secret(token_file, token)
        return SeedResult(str(tenant.id), site.id, device_id, token_file, users)
