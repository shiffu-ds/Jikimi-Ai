"""``python -m jikimi_server <command>``: serve | workers | seed | merkle-close | audit-verify | retire-key | openapi."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path

from jikimi_common.config import load_dotenv
from jikimi_common.logging import setup_logging

log = logging.getLogger("jikimi_server")


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "jikimi_server.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
        proxy_headers=True,
    )
    return 0


def cmd_workers(args: argparse.Namespace) -> int:
    from .context import AppContext
    from .settings import ServerSettings
    from .workers import Workers

    settings = ServerSettings.from_env()
    settings.validate()
    ctx = AppContext.build(settings)
    stop = asyncio.Event()
    asyncio.run(Workers(ctx).run(stop))
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from jikimi_crypto import Signer

    from .db.session import Database
    from .seed import seed_site
    from .settings import ServerSettings

    settings = ServerSettings.from_env()
    password = os.environ.get("JIKIMI_DEMO_PASSWORD", "")
    if len(password) < 8:
        log.error("JIKIMI_DEMO_PASSWORD missing or too short: run `make env` first")
        return 2
    db = Database(settings.database_url)
    db.create_all()
    edge_dir = Path(os.environ.get("JIKIMI_EDGE_DATA_DIR", "data/edge"))
    signer = Signer.from_file(edge_dir / "keys" / "device.key", prefix="edge")  # lite profile: same machine
    res = seed_site(
        db, args.edge_config, password, signer.public_key, signer.key_id, edge_dir / "keys" / "device.token"
    )
    print(
        json.dumps(
            {
                "tenant": res.tenant_id,
                "site": res.site_id,
                "device": res.device_id,
                "device_key": signer.key_id,
                "users": res.users,
                "token_file": str(res.device_token_file),
            },
            indent=2,
        )
    )
    return 0


def cmd_merkle(args: argparse.Namespace) -> int:
    from .context import AppContext
    from .settings import ServerSettings

    ctx = AppContext.build(ServerSettings.from_env())
    with ctx.db.session() as db:
        batch = ctx.evidence.close_batch(db, date.today(), stamp=not args.no_stamp)
        print(
            json.dumps(
                {
                    "closed": batch is not None,
                    **(
                        {"batch": batch.id, "root": batch.root, "size": batch.tree_size, "ots": batch.ots_status}
                        if batch
                        else {}
                    ),
                }
            )
        )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .core.audit import verify_chain
    from .db.session import Database
    from .settings import ServerSettings

    db = Database(ServerSettings.from_env().database_url)
    with db.session() as s:
        ok, n, bad = verify_chain(s)
    print(json.dumps({"ok": ok, "rows": n, "first_bad_id": bad}))
    return 0 if ok else 1


def cmd_retire_key(args: argparse.Namespace) -> int:
    """Rotate the server key: keep its public key for verifying old evidence, take the private
    key out of service (move the printed file to offline storage), next start creates a new one."""
    from jikimi_crypto import Signer

    from .settings import ServerSettings

    keys = ServerSettings.from_env().keys_dir
    current = keys / "evidence.key"
    if not current.exists():
        print(json.dumps({"error": f"{current} not found"}))
        return 1
    signer = Signer.from_file(current, prefix="server", create=False)
    retired = keys / "retired"
    retired.mkdir(parents=True, exist_ok=True)
    (retired / f"{signer.key_id.replace(':', '_')}.pub").write_text(signer.public_key + "\n", encoding="utf-8")
    offline = keys / f"evidence.key.retired-{date.today():%Y%m%d}"
    current.rename(offline)
    print(json.dumps({"retired_key_id": signer.key_id, "move_offline": str(offline), "next": "restart the API"}))
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    from .main import create_app
    from .settings import ServerSettings

    settings = ServerSettings.from_env()
    settings.jwt_secret = settings.jwt_secret or "x" * 32
    settings.database_url = "sqlite:///:memory:"
    settings.workers_inprocess = False
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(create_app(settings).openapi(), indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="jikimi-server", description="Jikimi AI server")
    ap.add_argument("--log-level", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="run the API (+ in-process workers in the lite profile)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    sub.add_parser("workers", help="run background workers in their own process")
    sd = sub.add_parser("seed", help="provision tenant/site/cameras/users/device from the edge site YAML")
    sd.add_argument("--edge-config", default="edge/config/site.demo.yaml")
    mk = sub.add_parser("merkle-close", help="close the Merkle batch now and stamp it (OpenTimestamps)")
    mk.add_argument("--no-stamp", action="store_true")
    sub.add_parser("audit-verify", help="verify the hash-chained audit log")
    sub.add_parser("retire-key", help="rotate the server signing key (old evidence stays verifiable)")
    op = sub.add_parser("openapi", help="export the OpenAPI document")
    op.add_argument("--out", default="docs/api/openapi.json")
    args = ap.parse_args(argv)
    setup_logging(args.log_level)
    handlers = {
        "serve": cmd_serve,
        "workers": cmd_workers,
        "seed": cmd_seed,
        "merkle-close": cmd_merkle,
        "audit-verify": cmd_audit,
        "retire-key": cmd_retire_key,
        "openapi": cmd_openapi,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
