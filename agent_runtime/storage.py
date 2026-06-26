"""Storage layer — SQLite for state, config, audit logs."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agent-runtime.storage")


class Storage:
    """SQLite-backed persistence for Agent Runtime."""
    
    def __init__(self, db_path: str = ""):
        self.db_path = db_path or os.path.expanduser("~/.agent-runtime/runtime.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    detail TEXT DEFAULT '{}',
                    previous_hash TEXT DEFAULT '',
                    hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.commit()
    
    # ── Events ────────────────────────────────────────
    
    def log_event(self, event_type: str, data: dict = None):
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO events (event_type, data, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(data or {}), self._now()),
            )
            db.commit()
    
    def get_events(self, event_type: str = "", limit: int = 50) -> list:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            if event_type:
                rows = db.execute(
                    "SELECT * FROM events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    
    # ── Audit Log ─────────────────────────────────────
    
    def audit(self, action: str, detail: dict = None):
        """Write a tamper-evident audit entry."""
        prev = self._last_audit_hash()
        import hashlib
        detail_str = json.dumps(detail or {}, sort_keys=True)
        entry_hash = hashlib.sha256(
            (prev + detail_str).encode()
        ).hexdigest()
        
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO audit_log (action, detail, previous_hash, hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (action, json.dumps(detail or {}), prev, entry_hash, self._now()),
            )
            db.commit()
    
    def _last_audit_hash(self) -> str:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else "0" * 64
    
    # ── Config ────────────────────────────────────────
    
    def set_config(self, key: str, value: str):
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, self._now()),
            )
            db.commit()
    
    def get_config(self, key: str, default: str = "") -> str:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default
    
    # ── Helpers ────────────────────────────────────────
    
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
