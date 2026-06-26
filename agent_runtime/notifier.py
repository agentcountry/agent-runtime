"""Notifier — sends notifications to the human owner."""

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.notifier")


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


class Notifier:
    """Notification dispatcher."""
    
    ICONS = {
        Severity.INFO: "ℹ️",
        Severity.WARN: "⚠️",
        Severity.ERROR: "❌",
        Severity.CRITICAL: "🚨",
        Severity.DEBUG: "🔍",
    }
    
    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._history: list[dict] = []
    
    async def notify(self, message: str, severity: Severity = Severity.INFO):
        """Send a notification. Primary channel: Matrix DM to owner."""
        icon = self.ICONS.get(severity, "")
        formatted = f"{icon} {message}" if icon else message
        
        # Store in history
        self._history.append({
            "message": message,
            "severity": severity,
            "timestamp": self._now_iso(),
        })
        
        # Trim history
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        # Log
        log_fn = {
            Severity.DEBUG: logger.debug,
            Severity.INFO: logger.info,
            Severity.WARN: logger.warning,
            Severity.ERROR: logger.error,
            Severity.CRITICAL: logger.critical,
        }.get(severity, logger.info)
        log_fn(formatted)
        
        # Send via ARMP Matrix if connected
        if self.runtime._started and self.runtime._armp:
            try:
                # In production: send to owner's DM room
                # For now, log the notification
                pass
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
    
    def history(self, limit: int = 20) -> list:
        """Get recent notification history."""
        return self._history[-limit:]
    
    def _now_iso(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
