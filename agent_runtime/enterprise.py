"""
Enterprise — RBAC, audit export, and enterprise features.

Phase 3: Role-based access control, granular permissions,
audit log export (CSV/JSON/PDF), and SSO integration hooks.
"""

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.enterprise")


class Role(str, Enum):
    """Predefined roles for RBAC."""
    VIEWER = "viewer"                # Read-only dashboard access
    OPERATOR = "operator"            # Can manage triggers, plugins
    ADMIN = "admin"                  # Full control except billing
    OWNER = "owner"                  # Full control including billing
    SUPERADMIN = "superadmin"        # Cross-tenant admin (enterprise)


@dataclass
class User:
    """A user with RBAC permissions."""
    user_id: str
    username: str
    role: Role = Role.VIEWER
    email: str = ""
    sso_provider: str = ""           # "oidc", "saml", "github", ""
    permissions: list = field(default_factory=list)  # Explicit overrides
    created_at: str = ""
    last_login: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now_iso()

    def has_permission(self, action: str) -> bool:
        """Check if user has explicit permission."""
        return action in self.permissions


# Role → default permissions
ROLE_PERMISSIONS = {
    Role.VIEWER: [
        "dashboard.view",
        "status.read",
        "audit.read_own",
    ],
    Role.OPERATOR: [
        "dashboard.view", "status.read", "audit.read_own",
        "triggers.manage", "plugins.manage", "watchdog.manage",
        "tasks.create", "tasks.read",
    ],
    Role.ADMIN: [
        "dashboard.view", "status.read", "audit.read_all",
        "triggers.manage", "plugins.manage", "watchdog.manage",
        "tasks.create", "tasks.read", "tasks.manage",
        "permissions.manage", "users.manage", "config.manage",
        "collaboration.manage", "federation.manage",
    ],
    Role.OWNER: [
        "*",  # All permissions
    ],
    Role.SUPERADMIN: [
        "*", "cross_tenant.access", "cross_tenant.manage",
    ],
}


class RBACManager:
    """Role-based access control."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._users: dict[str, User] = {}

    def add_user(self, user: User):
        self._users[user.user_id] = user
        logger.info(f"User added: {user.username} ({user.role.value})")

    def remove_user(self, user_id: str):
        if user_id in self._users:
            del self._users[user_id]

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def can(self, user_id: str, action: str) -> bool:
        """Check if a user can perform an action."""
        user = self._users.get(user_id)
        if not user:
            return False

        # Explicit override
        if user.has_permission(action):
            return True

        # Role-based
        role_perms = ROLE_PERMISSIONS.get(user.role, [])
        if "*" in role_perms:
            return True
        return action in role_perms

    def list_users(self) -> list[dict]:
        return [
            {"user_id": u.user_id, "username": u.username, "role": u.role.value}
            for u in self._users.values()
        ]


class AuditExporter:
    """Export audit logs in various formats."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime

    def export_csv(self, limit: int = 1000) -> str:
        """Export audit log as CSV string."""
        logs = self.runtime.storage.get_audit_log(limit)
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["id", "action", "detail", "hash", "created_at"])
        for log in logs:
            writer.writerow([
                log.get("id", ""),
                log.get("action", ""),
                log.get("detail", ""),
                log.get("hash", "")[:16],
                log.get("created_at", ""),
            ])

        return output.getvalue()

    def export_json(self, limit: int = 1000) -> str:
        """Export audit log as JSON string."""
        logs = self.runtime.storage.get_audit_log(limit)
        export = {
            "exported_at": _now_iso(),
            "total": len(logs),
            "entries": logs,
        }
        return json.dumps(export, indent=2, default=str)

    def export_jsonl(self, limit: int = 1000) -> str:
        """Export audit log as JSONL (one JSON object per line)."""
        logs = self.runtime.storage.get_audit_log(limit)
        return "\n".join(json.dumps(log, default=str) for log in logs)

    def verify_integrity(self) -> dict:
        """Verify the hash-chain integrity of audit logs."""
        logs = self.runtime.storage.get_audit_log(10000)
        if not logs:
            return {"valid": True, "entries": 0}

        import hashlib

        prev_hash = "0" * 64
        results = []
        valid = True

        for log in reversed(logs):  # Oldest first
            expected_hash = hashlib.sha256(
                (prev_hash + (log.get("detail") or "{}")).encode()
            ).hexdigest()

            is_valid = (expected_hash == log.get("hash", ""))
            if not is_valid:
                valid = False
                logger.error(f"Hash chain broken at id={log.get('id')}")

            results.append({
                "id": log.get("id"),
                "valid": is_valid,
                "expected": expected_hash[:16],
                "actual": log.get("hash", "")[:16],
            })
            prev_hash = log.get("hash", "0" * 64)

        return {
            "valid": valid,
            "entries": len(logs),
            "first_violation": next((r for r in results if not r["valid"]), None),
        }


class SSOManager:
    """SSO integration hooks (OIDC/SAML)."""

    def __init__(self):
        self._providers: dict[str, dict] = {}

    def configure_oidc(
        self,
        provider_name: str,
        issuer: str,
        client_id: str,
        client_secret: str = "",
        redirect_uri: str = "",
    ):
        """Configure an OIDC identity provider."""
        self._providers[provider_name] = {
            "type": "oidc",
            "issuer": issuer,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "enabled": True,
        }
        logger.info(f"SSO provider configured: {provider_name} (OIDC)")

    def configure_saml(
        self,
        provider_name: str,
        idp_metadata_url: str,
        sp_entity_id: str,
    ):
        """Configure a SAML identity provider."""
        self._providers[provider_name] = {
            "type": "saml",
            "idp_metadata_url": idp_metadata_url,
            "sp_entity_id": sp_entity_id,
            "enabled": True,
        }
        logger.info(f"SSO provider configured: {provider_name} (SAML)")

    def list_providers(self) -> list[dict]:
        return [
            {"name": k, "type": v["type"], "enabled": v["enabled"]}
            for k, v in self._providers.items()
        ]


class EnterpriseManager:
    """Unified enterprise feature access."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self.rbac = RBACManager(runtime)
        self.audit_exporter = AuditExporter(runtime)
        self.sso = SSOManager()

    def stats(self) -> dict:
        return {
            "users": len(self.rbac._users),
            "sso_providers": len(self.sso._providers),
            "audit_entries": len(self.runtime.storage.get_audit_log(1)),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
