"""Durable edge outbox on SQLite (F4, plan Section 8.8; ADR-008).

Everything that must reach the server goes through here first (alerts, clips, heartbeats,
track summaries, SMS acks). ``journal_mode=WAL`` + ``synchronous=FULL`` means a committed alert
survives a power cut. Enqueue is idempotent on ``dedupe_key`` (the alert id), so a restart or a
retry can never duplicate an alert.
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                 -- alert | clip | heartbeat | snapshot | track | ack
  dedupe_key TEXT UNIQUE,
  payload TEXT NOT NULL,              -- JSON
  file_path TEXT,                     -- JSON list of local files to upload (clips, keyframes)
  severity TEXT NOT NULL DEFAULT 'medium',
  priority INTEGER NOT NULL DEFAULT 5,
  created_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_try_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | sms_sent | sent | dead
  last_error TEXT,
  sms_sent_at REAL,
  sms_recipients INTEGER NOT NULL DEFAULT 0,
  sent_at REAL
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status, next_try_at, priority);
CREATE TABLE IF NOT EXISTS sms_log (
  id INTEGER PRIMARY KEY,
  direction TEXT NOT NULL,            -- out | in
  number TEXT NOT NULL,
  text TEXT NOT NULL,
  alert_id TEXT,
  code TEXT,
  status TEXT NOT NULL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sms_code ON sms_log(code);
CREATE TABLE IF NOT EXISTS local_acks (
  id INTEGER PRIMARY KEY,
  alert_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  channel TEXT NOT NULL,
  at REAL NOT NULL,
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plugin_state (
  plugin TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  state TEXT NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (plugin, camera_id)
);
"""


@dataclass
class OutboxItem:
    id: int
    kind: str
    dedupe_key: str | None
    payload: dict[str, Any]
    files: list[str]
    severity: str
    priority: int
    created_at: float
    attempts: int
    status: str
    sms_sent_at: float | None
    sms_recipients: int

    def age_s(self, now: float) -> float:
        return now - self.created_at


class Outbox:
    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ queue
    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        severity: str = "medium",
        priority: int = 5,
        dedupe_key: str | None = None,
        files: list[str] | None = None,
        replace: bool = False,
        now: float | None = None,
    ) -> bool:
        """Insert (or, with ``replace``, upsert) an item. Returns True if a row was written."""
        now = time.time() if now is None else now
        args = (
            kind,
            dedupe_key,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(files or []),
            severity,
            priority,
            now,
            now,
        )
        sql = (
            "INSERT INTO outbox(kind, dedupe_key, payload, file_path, severity, priority, created_at, next_try_at) "
            "VALUES (?,?,?,?,?,?,?,?)"
        )
        if replace:
            sql += (
                " ON CONFLICT(dedupe_key) DO UPDATE SET payload=excluded.payload, file_path=excluded.file_path,"
                " status='pending', attempts=0, next_try_at=excluded.next_try_at, created_at=excluded.created_at,"
                " last_error=NULL"
            )
        else:
            sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.rowcount > 0

    def due(self, now: float | None = None, limit: int = 50) -> list[OutboxItem]:
        now = time.time() if now is None else now
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outbox WHERE status IN ('pending','sms_sent') AND next_try_at <= ? "
                "ORDER BY priority, id LIMIT ?",
                (now, limit),
            ).fetchall()
        return [self._item(r) for r in rows]

    def pending_alerts(self) -> list[OutboxItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outbox WHERE kind='alert' AND status IN ('pending','sms_sent') ORDER BY id"
            ).fetchall()
        return [self._item(r) for r in rows]

    @staticmethod
    def _item(r: sqlite3.Row) -> OutboxItem:
        return OutboxItem(
            id=r["id"],
            kind=r["kind"],
            dedupe_key=r["dedupe_key"],
            payload=json.loads(r["payload"]),
            files=json.loads(r["file_path"] or "[]"),
            severity=r["severity"],
            priority=r["priority"],
            created_at=r["created_at"],
            attempts=r["attempts"],
            status=r["status"],
            sms_sent_at=r["sms_sent_at"],
            sms_recipients=r["sms_recipients"],
        )

    def mark_sent(self, item_id: int, now: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
                (time.time() if now is None else now, item_id),
            )

    def mark_sms(self, item_id: int, recipients: int, now: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET status='sms_sent', sms_sent_at=?, sms_recipients=? WHERE id=?",
                (time.time() if now is None else now, recipients, item_id),
            )

    def backoff(self, item_id: int, attempts: int, error: str, now: float | None = None) -> float:
        now = time.time() if now is None else now
        delay = min(2.0 ** min(attempts, 9), 300.0) * random.uniform(0.8, 1.2)
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET attempts=?, next_try_at=?, last_error=? WHERE id=?",
                (attempts + 1, now + delay, error[:500], item_id),
            )
        return delay

    def mark_dead(self, item_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE outbox SET status='dead', last_error=? WHERE id=?", (error[:500], item_id))

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()
        out = {"pending": 0, "sms_sent": 0, "sent": 0, "dead": 0}
        out.update({r["status"]: r["n"] for r in rows})
        return out

    def backlog(self) -> int:
        c = self.counts()
        return c["pending"] + c["sms_sent"]

    def purge_sent(self, older_than_s: float = 7 * 86400, now: float | None = None) -> int:
        cutoff = (time.time() if now is None else now) - older_than_s
        with self._lock:
            return self._conn.execute("DELETE FROM outbox WHERE status='sent' AND sent_at < ?", (cutoff,)).rowcount

    # ------------------------------------------------------------------ SMS + acks
    def log_sms(
        self, direction: str, number: str, text: str, status: str, alert_id: str | None = None, code: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sms_log(direction, number, text, alert_id, code, status, at) VALUES (?,?,?,?,?,?,?)",
                (direction, number, text, alert_id, code, status, time.time()),
            )

    def alert_for_code(self, code: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT alert_id FROM sms_log WHERE direction='out' AND code=? ORDER BY id DESC LIMIT 1",
                (code.upper(),),
            ).fetchone()
        return row["alert_id"] if row else None

    def latest_sms_alert(self, number: str | None = None) -> str | None:
        q = "SELECT alert_id FROM sms_log WHERE direction='out' AND alert_id IS NOT NULL"
        args: tuple[Any, ...] = ()
        if number:
            q += " AND number=?"
            args = (number,)
        with self._lock:
            row = self._conn.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()
        return row["alert_id"] if row else None

    def add_local_ack(
        self, alert_id: str, action: str, actor: str, channel: str = "sms", at: float | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO local_acks(alert_id, action, actor, channel, at) VALUES (?,?,?,?,?)",
                (alert_id, action, actor, channel, time.time() if at is None else at),
            )

    def pending_acks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM local_acks WHERE synced=0 ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def mark_acks_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany("UPDATE local_acks SET synced=1 WHERE id=?", [(i,) for i in ids])

    # ------------------------------------------------------------------ plugin state
    def save_state(self, plugin: str, camera_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO plugin_state(plugin, camera_id, state, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(plugin, camera_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
                (plugin, camera_id, json.dumps(state), time.time()),
            )

    def load_state(self, plugin: str, camera_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM plugin_state WHERE plugin=? AND camera_id=?", (plugin, camera_id)
            ).fetchone()
        return json.loads(row["state"]) if row else None
