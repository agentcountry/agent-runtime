"""Storage layer — SQLite for state, config, audit logs, and tasks.

Phase 2: Adds tasks table for task_manager.py persistence.
"""

import hashlib
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
            # Phase 2: tasks table
            db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    requester_did TEXT DEFAULT '',
                    assignee_did TEXT DEFAULT '',
                    capability TEXT DEFAULT '',
                    parameters TEXT DEFAULT '{}',
                    result TEXT,
                    deadline TEXT,
                    tags TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
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
        detail_str = json.dumps(detail or {}, sort_keys=True)
        entry_hash = hashlib.sha256(
            (prev + detail_str).encode()
        ).hexdigest()

        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO audit_log (action, detail, previous_hash, hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (action, json.dumps(detail or {}), prev, entry_hash, self._now()),
            )
            db.commit()

    def _last_audit_hash(self) -> str:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else "0" * 64

    def get_audit_log(self, limit: int = 50) -> list:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

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

    # ── Tasks (Phase 2) ───────────────────────────────

    def save_task(self, task_data: dict):
        """Insert or update a task record."""
        with sqlite3.connect(self.db_path) as db:
            db.execute("""
                INSERT OR REPLACE INTO tasks
                (task_id, title, description, status, priority,
                 requester_did, assignee_did, capability, parameters,
                 result, deadline, tags, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_data["task_id"],
                task_data["title"],
                task_data.get("description", ""),
                task_data.get("status", "pending"),
                task_data.get("priority", "medium"),
                task_data.get("requester_did", ""),
                task_data.get("assignee_did", ""),
                task_data.get("capability", ""),
                json.dumps(task_data.get("parameters", {})),
                json.dumps(task_data.get("result")) if task_data.get("result") else None,
                task_data.get("deadline"),
                json.dumps(task_data.get("tags", [])),
                task_data.get("created_at", self._now()),
                task_data.get("updated_at", self._now()),
                task_data.get("completed_at"),
            ))
            db.commit()

    def get_tasks(self, status: str = "", limit: int = 50) -> list:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            if status:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    # ── Helpers ────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
