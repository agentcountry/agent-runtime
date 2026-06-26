"""Configuration management — defaults and persistent settings."""

import os
from pathlib import Path


class Config:
    """Runtime configuration with sensible defaults."""
    
    def __init__(self, config_path: str = ""):
        self.config_path = config_path or os.path.expanduser(
            "~/.agent-runtime/config.yaml"
        )
        self._data = self._load_defaults()
    
    def _load_defaults(self) -> dict:
        return {
            # Storage
            "db_path": os.path.expanduser("~/.agent-runtime/runtime.db"),
            
            # Permissions
            "default_permission_level": 0,
            "api_whitelist": [],
            
            # Triggers
            "keyword_triggers_enabled": True,
            "cron_triggers_enabled": False,
            
            # Decision
            "llm_enabled": False,
            "llm_provider": "deepseek",
            "llm_model": "deepseek-chat",
            
            # Notifications
            "notify_on_start": True,
            "notify_on_stop": True,
            "notify_on_message": True,
            "notify_on_error": True,
            
            # Limits
            "max_messages_per_hour": 100,
            "max_api_calls_per_hour": 50,
        }
    
    def get(self, key: str, default=None):
        return self._data.get(key, default)
    
    def set(self, key: str, value):
        self._data[key] = value
    
    # ── Convenience Properties ─────────────────────────
    
    @property
    def db_path(self) -> str:
        return self._data["db_path"]
    
    @property
    def default_permission_level(self) -> int:
        return self._data["default_permission_level"]
    
    @property
    def api_whitelist(self) -> list:
        return self._data["api_whitelist"]
