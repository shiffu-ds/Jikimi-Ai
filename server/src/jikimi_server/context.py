"""Application context: everything the routers and workers share."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from jikimi_crypto import Signer

from .core.ratelimit import RateLimiter
from .db.session import Database
from .evidence.service import EvidenceService, load_retired_keys
from .search.engine import SearchEngine
from .search.llm_fallback import LlmFallback
from .services.alerts import AlertService
from .services.edge_ingest import EdgeIngest
from .services.effects import Effects
from .services.hub import Hub
from .services.notifier import Notifier
from .services.vlm import VlmVerifier
from .services.voice import Transcriber
from .settings import ServerSettings
from .storage import LocalStore


@dataclass
class AppContext:
    settings: ServerSettings
    db: Database
    store: LocalStore
    hub: Hub
    notifier: Notifier
    alerts: AlertService
    ingest: EdgeIngest
    evidence: EvidenceService
    search: SearchEngine
    llm: LlmFallback | None
    executor: ThreadPoolExecutor
    voice: Transcriber
    verifier: VlmVerifier
    verify_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(rate_per_min=60, burst=30))
    login_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(rate_per_min=10, burst=10))
    voice_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(rate_per_min=12, burst=6))

    def dispatch(self, effects: Effects) -> None:
        effects.dispatch(self.hub, self.executor)

    @classmethod
    def build(cls, settings: ServerSettings) -> AppContext:
        db = Database(settings.database_url)
        store = LocalStore(settings.storage_dir)
        hub = Hub()
        notifier = Notifier(settings)
        verifier = VlmVerifier(settings.vlm_local)
        local = bool(verifier.types()) and verifier.available  # a VLM that passed nothing costs nothing
        gate = local and settings.vlm_mode == "gate"
        alerts = AlertService(
            notifier,
            max(settings.verify_timeout_s, 60.0)
            if gate
            else settings.verify_timeout_s,  # ~20 s per alert on a laptop CPU
            vlm_enabled=bool(settings.llm_base_url and settings.vlm_model) or gate,
            vlm_advisory=local and not gate,
        )
        signer = Signer.from_file(settings.keys_dir / "evidence.key", prefix="server")
        llm = (
            LlmFallback(settings.llm_base_url, settings.llm_model)
            if settings.llm_base_url and settings.llm_model
            else None
        )
        return cls(
            settings=settings,
            db=db,
            store=store,
            hub=hub,
            notifier=notifier,
            alerts=alerts,
            ingest=EdgeIngest(alerts, store),
            evidence=EvidenceService(
                store, signer, settings.public_base_url, load_retired_keys(settings.keys_dir / "retired")
            ),
            search=SearchEngine(),
            llm=llm,
            executor=ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg"),
            voice=Transcriber(settings.whisper_model, settings.whisper_threads),
            verifier=verifier,
        )
