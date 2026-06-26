"""
Dashboard — FastAPI web UI with dark theme for monitoring Agent Runtime.

Phase 2: Provides a real-time dashboard showing agent status,
permissions, triggers, watchdogs, tasks, and collaboration sessions.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.dashboard")

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Inline dark-theme dashboard HTML (no external deps)
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Runtime — Dashboard</title>
    <style>
        :root {
            --bg: #0d1117;
            --bg-card: #161b22;
            --bg-hover: #21262d;
            --border: #30363d;
            --text: #c9d1d9;
            --text-dim: #8b949e;
            --accent: #3559f0;
            --green: #3fb950;
            --yellow: #d2991d;
            --red: #f85149;
            --purple: #a371f7;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', sans-serif;
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);
        }
        header h1 { font-size: 1.5rem; font-weight: 600; }
        .badge {
            display: inline-block; padding: 0.2em 0.6em; border-radius: 2em;
            font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
        }
        .badge-online { background: var(--green); color: #000; }
        .badge-offline { background: var(--red); color: #fff; }
        .badge-l0 { background: var(--border); color: var(--text-dim); }
        .badge-l1 { background: #1f6feb; color: #fff; }
        .badge-l2 { background: #1f6feb; color: #fff; }
        .badge-l3 { background: var(--yellow); color: #000; }
        .badge-l4 { background: var(--red); color: #fff; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; }
        .card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 8px; padding: 1.25rem;
        }
        .card h3 { font-size: 0.875rem; color: var(--text-dim); margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
        .stat-row { display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
        .stat-row:last-child { border-bottom: none; }
        .stat-value { font-weight: 600; }
        .stat-value.ok { color: var(--green); }
        .stat-value.warn { color: var(--yellow); }
        .stat-value.error { color: var(--red); }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
        th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
        th { color: var(--text-dim); font-weight: 600; }
        .fade { color: var(--text-dim); font-size: 0.8rem; }
        .section { margin-top: 2rem; }
        pre {
            background: var(--bg); border: 1px solid var(--border);
            border-radius: 6px; padding: 1rem; overflow-x: auto;
            font-size: 0.8rem; font-family: 'SF Mono', 'Fira Code', monospace;
        }
        .auto-refresh { font-size: 0.75rem; color: var(--text-dim); }
        @media (max-width: 600px) {
            .container { padding: 1rem; }
            header { flex-direction: column; gap: 0.5rem; }
        }
    </style>
</head>
<body>
<div class="container">
    <header>
        <div>
            <h1>🤖 Agent Runtime</h1>
            <span class="fade">{{did}}</span>
        </div>
        <span class="badge {{status_class}}">{{status}}</span>
    </header>

    <!-- Permissions -->
    <div class="grid">
        <div class="card">
            <h3>Permissions</h3>
            <div class="stat-row">
                <span>Level</span>
                <span class="badge badge-l{{permission_level}}">L{{permission_level}}</span>
            </div>
            <div class="stat-row">
                <span>Handle Messages</span>
                <span class="stat-value {{can_msg_class}}">{{can_handle_messages}}</span>
            </div>
            <div class="stat-row">
                <span>API Calls</span>
                <span class="stat-value {{can_api_class}}">{{can_call_api}}</span>
            </div>
            <div class="stat-row">
                <span>Create Tasks</span>
                <span class="stat-value {{can_task_class}}">{{can_create_tasks}}</span>
            </div>
            <div class="stat-row">
                <span>Payments</span>
                <span class="stat-value {{can_pay_class}}">{{can_pay}}</span>
            </div>
            <div class="stat-row">
                <span>API Whitelist</span>
                <span>{{api_whitelist_count}} APIs</span>
            </div>
        </div>

        <!-- Triggers -->
        <div class="card">
            <h3>Triggers</h3>
            {{trigger_rows}}
        </div>

        <!-- Watchdog -->
        <div class="card">
            <h3>Watchdog</h3>
            {{watchdog_rows}}
        </div>
    </div>

    <!-- Tasks -->
    <div class="section">
        <h2>📋 Tasks</h2>
        <div class="grid">
            <div class="card">
                <h3>Task Stats</h3>
                <div class="stat-row"><span>Total</span><span class="stat-value">{{task_total}}</span></div>
                <div class="stat-row"><span>Pending</span><span class="stat-value">{{task_pending}}</span></div>
                <div class="stat-row"><span>In Progress</span><span class="stat-value">{{task_in_progress}}</span></div>
                <div class="stat-row"><span>Completed</span><span class="stat-value ok">{{task_completed}}</span></div>
                <div class="stat-row"><span>Failed</span><span class="stat-value error">{{task_failed}}</span></div>
            </div>
            <div class="card">
                <h3>Recent Tasks</h3>
                <div class="table-wrap">
                    <table>
                        <tr><th>ID</th><th>Title</th><th>Status</th></tr>
                        {{task_rows}}
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- Collaboration -->
    <div class="section">
        <h2>🤝 Collaboration</h2>
        <div class="grid">
            <div class="card">
                <h3>Sessions</h3>
                <div class="stat-row"><span>Active</span><span class="stat-value">{{collab_active}}</span></div>
                <div class="stat-row"><span>Completed</span><span class="stat-value ok">{{collab_completed}}</span></div>
            </div>
        </div>
    </div>

    <p class="auto-refresh" style="text-align:center; margin-top:2rem;">
        Agent Runtime v{{version}} · Apache 2.0 · Auto-refresh every 30s
    </p>
</div>
<script>
    setTimeout(() => location.reload(), 30000);
</script>
</body>
</html>"""


class DashboardServer:
    """FastAPI-based dashboard server with dark theme."""

    def __init__(self, runtime: "Runtime", host: str = "0.0.0.0", port: int = 8080):
        self.runtime = runtime
        self.host = host
        self.port = port
        self._app = None
        self._server = None

    def _build_app(self):
        """Build the FastAPI application."""
        try:
            from fastapi import FastAPI
            from fastapi.responses import HTMLResponse, JSONResponse
        except ImportError:
            raise ImportError(
                "fastapi required for dashboard. Install: pip install fastapi uvicorn"
            )

        app = FastAPI(
            title="Agent Runtime Dashboard",
            version="0.2.0",
            docs_url=None,
            redoc_url=None,
        )

        runtime_ref = self.runtime

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return self._render_html()

        @app.get("/api/status")
        async def api_status():
            return JSONResponse(content=self._collect_status())

        @app.get("/api/tasks")
        async def api_tasks():
            tasks = runtime_ref.task_manager.list_by_status() if hasattr(runtime_ref, 'task_manager') else []
            return JSONResponse(content=[t.to_dict() for t in tasks[:50]])

        @app.get("/api/watchdog")
        async def api_watchdog():
            if hasattr(runtime_ref, 'watchdog'):
                return JSONResponse(content=runtime_ref.watchdog.summary())
            return JSONResponse(content={"error": "watchdog not initialized"})

        @app.get("/health")
        async def health():
            return {"status": "ok" if runtime_ref.is_running else "stopped"}

        return app

    def _render_html(self) -> str:
        rt = self.runtime
        html = DASHBOARD_HTML

        # Status
        html = html.replace("{{did}}", rt.did)
        html = html.replace("{{status}}", "ONLINE" if rt.is_running else "OFFLINE")
        html = html.replace("{{status_class}}", "badge-online" if rt.is_running else "badge-offline")

        # Permissions
        pm = rt.permissions
        html = html.replace("{{permission_level}}", str(pm.level))
        html = html.replace("{{can_handle_messages}}", "✅" if pm.can_handle_messages() else "❌")
        html = html.replace("{{can_msg_class}}", "ok" if pm.can_handle_messages() else "error")
        html = html.replace("{{can_call_api}}", "✅" if pm.can_call_api() else "❌")
        html = html.replace("{{can_api_class}}", "ok" if pm.can_call_api() else "error")
        html = html.replace("{{can_create_tasks}}", "✅" if pm.can_create_tasks() else "❌")
        html = html.replace("{{can_task_class}}", "ok" if pm.can_create_tasks() else "error")
        html = html.replace("{{can_pay}}", "✅" if pm.can_pay() else "❌")
        html = html.replace("{{can_pay_class}}", "ok" if pm.can_pay() else "error")
        html = html.replace("{{api_whitelist_count}}", str(len(pm.api_whitelist)))

        # Triggers
        triggers = rt.triggers.list()
        trigger_rows = []
        for t in triggers:
            trigger_rows.append(
                f'<div class="stat-row"><span>{t["name"]}</span>'
                f'<span class="stat-value ok">{t["type"]}</span></div>'
            )
        html = html.replace("{{trigger_rows}}", "\n".join(trigger_rows) if trigger_rows else '<div class="stat-row"><span>No triggers</span></div>')

        # Watchdog
        if hasattr(rt, 'watchdog'):
            s = rt.watchdog.summary()
            watchdog_rows = f"""<div class="stat-row"><span>Total Checks</span><span class="stat-value">{s["total_checks"]}</span></div>
<div class="stat-row"><span>OK</span><span class="stat-value ok">{s["ok"]}</span></div>
<div class="stat-row"><span>Warnings</span><span class="stat-value warn">{s["warn"]}</span></div>
<div class="stat-row"><span>Critical</span><span class="stat-value error">{s["critical"]}</span></div>
<div class="stat-row"><span>Errors</span><span class="stat-value error">{s["error"]}</span></div>
<div class="stat-row"><span>Last Run</span><span class="fade">{s["last_run"][:19]}</span></div>"""
        else:
            watchdog_rows = '<div class="stat-row"><span>Not initialized</span></div>'
        html = html.replace("{{watchdog_rows}}", watchdog_rows)

        # Tasks
        if hasattr(rt, 'task_manager'):
            ts = rt.task_manager.stats()
            html = html.replace("{{task_total}}", str(ts["total"]))
            html = html.replace("{{task_pending}}", str(ts["pending"]))
            html = html.replace("{{task_assigned}}", str(ts["assigned"]))
            html = html.replace("{{task_in_progress}}", str(ts["in_progress"]))
            html = html.replace("{{task_completed}}", str(ts["completed"]))
            html = html.replace("{{task_failed}}", str(ts["failed"]))
            recent = rt.task_manager.list_by_status()[:10]
            task_rows = "".join(
                f'<tr><td>{t.task_id}</td><td>{t.title[:40]}</td><td>{t.status.value}</td></tr>'
                for t in recent
            )
            html = html.replace("{{task_rows}}", task_rows or '<tr><td colspan="3" class="fade">No tasks</td></tr>')
        else:
            for k in ["task_total", "task_pending", "task_assigned", "task_in_progress",
                       "task_completed", "task_failed"]:
                html = html.replace("{{" + k + "}}", "—")
            html = html.replace("{{task_rows}}", '<tr><td colspan="3" class="fade">Not initialized</td></tr>')

        # Collaboration
        if hasattr(rt, 'collaboration'):
            cs = rt.collaboration.stats()
            html = html.replace("{{collab_active}}", str(cs["active"]))
            html = html.replace("{{collab_completed}}", str(cs["completed"]))
        else:
            html = html.replace("{{collab_active}}", "—")
            html = html.replace("{{collab_completed}}", "—")

        html = html.replace("{{version}}", "0.2.0")
        return html

    def _collect_status(self) -> dict:
        rt = self.runtime
        status = {
            "did": rt.did,
            "running": rt.is_running,
            "permission_level": rt.permissions.level,
            "plugins": rt.plugins.list(),
            "triggers": rt.triggers.list(),
        }
        if hasattr(rt, 'watchdog'):
            status["watchdog"] = rt.watchdog.summary()
        if hasattr(rt, 'task_manager'):
            status["tasks"] = rt.task_manager.stats()
        if hasattr(rt, 'collaboration'):
            status["collaboration"] = rt.collaboration.stats()
        return status

    async def start(self):
        """Start the dashboard server."""
        try:
            import uvicorn
        except ImportError:
            raise ImportError("uvicorn required. Install: pip install uvicorn")

        self._app = self._build_app()
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        logger.info(f"Dashboard started at http://{self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.should_exit = True
