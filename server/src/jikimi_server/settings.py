"""Server settings from the environment (``.env`` in development)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from jikimi_common.config import env_bool


@dataclass
class ServerSettings:
    env: str = "dev"
    database_url: str = "sqlite:///data/server/jikimi.db"
    data_dir: Path = Path("data/server")
    jwt_secret: str = ""
    jwt_ttl_s: int = 12 * 3600
    public_base_url: str = "http://localhost:8000"
    dashboard_dir: Path = Path("apps/dashboard/out")
    workers_inprocess: bool = True
    verify_timeout_s: float = 20.0
    llm_base_url: str | None = None
    llm_model: str | None = None
    vlm_model: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_ids: list[str] = field(default_factory=list)
    escalation_scale: float = 1.0
    cookie_secure: bool = False
    demo_mode: bool = False
    whisper_model: Path | None = None  # guard voice replies (F12); None = off
    whisper_threads: int = 2
    vlm_local: Path | None = None  # local VLM verifier (F5); None = off
    vlm_mode: str = "advisory"  # "advisory": attach the verdict; "gate": a "normal" verdict logs a VERIFY alert
    vlm_frames: int = 2  # keyframes per verdict; each costs ~8 s on a laptop CPU

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"

    @classmethod
    def from_env(cls) -> ServerSettings:
        e = os.environ
        data_dir = Path(e.get("JIKIMI_DATA_DIR", "data/server"))
        return cls(
            env=e.get("JIKIMI_ENV", "dev"),
            database_url=e.get("JIKIMI_DATABASE_URL") or f"sqlite:///{data_dir / 'jikimi.db'}",
            data_dir=data_dir,
            jwt_secret=e.get("JIKIMI_JWT_SECRET", ""),
            public_base_url=e.get("JIKIMI_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            dashboard_dir=Path(e.get("JIKIMI_DASHBOARD_DIR", "apps/dashboard/out")),
            workers_inprocess=env_bool("JIKIMI_WORKERS_INPROCESS", True),
            verify_timeout_s=float(e.get("JIKIMI_VERIFY_TIMEOUT_S", "20")),
            llm_base_url=e.get("JIKIMI_LLM_BASE_URL") or None,
            llm_model=e.get("JIKIMI_LLM_MODEL") or None,
            vlm_model=e.get("JIKIMI_VLM_MODEL") or None,
            telegram_bot_token=e.get("JIKIMI_TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_ids=[c.strip() for c in e.get("JIKIMI_TELEGRAM_CHAT_IDS", "").split(",") if c.strip()],
            escalation_scale=float(e.get("JIKIMI_ESCALATION_SCALE", "1.0")),
            cookie_secure=env_bool("JIKIMI_COOKIE_SECURE", False),
            demo_mode=env_bool("JIKIMI_DEMO_MODE", False),
            whisper_model=Path(w) if (w := e.get("JIKIMI_WHISPER_MODEL", "models/faster-whisper-small")) else None,
            whisper_threads=int(e.get("JIKIMI_WHISPER_THREADS", "2")),
            vlm_local=Path(v) if (v := e.get("JIKIMI_VLM_LOCAL", "models/smolvlm-256m-instruct")) else None,
            vlm_mode=e.get("JIKIMI_VLM_MODE", "advisory"),
            vlm_frames=int(e.get("JIKIMI_VLM_FRAMES", "2")),
        )

    def validate(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JIKIMI_JWT_SECRET must be set (>= 32 chars). Run `make env`.")
