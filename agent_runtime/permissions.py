"""Permission system — L0 through L4 security levels."""

from dataclasses import dataclass
import logging

logger = logging.getLogger("agent-runtime.permissions")


class PermissionLevel:
    """Five-level permission model."""
    
    NOTIFY = 0       # Read-only notifications
    REPLY = 1        # Auto-reply to messages
    API_CALL = 2     # Call whitelisted APIs
    CREATE_TASK = 3  # Create ARMP tasks, delegate
    PAY = 4          # Execute payments via SSHPay
    
    @classmethod
    def name(cls, level: int) -> str:
        names = {
            0: "NOTIFY — Read-only notifications",
            1: "REPLY — Auto-reply to messages",
            2: "API_CALL — Call whitelisted APIs",
            3: "CREATE_TASK — Create tasks and delegate",
            4: "PAY — Execute payments",
        }
        return names.get(level, f"UNKNOWN ({level})")


@dataclass
class PermissionManager:
    """Manages agent permission level and whitelists."""
    
    level: int = 0  # L0-L4
    api_whitelist: list = None
    auto_upgrade_enabled: bool = False
    anomaly_detection: bool = True
    
    def __post_init__(self):
        if self.api_whitelist is None:
            self.api_whitelist = []
    
    # ── Capability Checks ────────────────────────────
    
    def can_handle_messages(self) -> bool:
        return self.level >= PermissionLevel.REPLY
    
    def can_call_api(self) -> bool:
        return self.level >= PermissionLevel.API_CALL
    
    def can_create_tasks(self) -> bool:
        return self.level >= PermissionLevel.CREATE_TASK
    
    def can_pay(self) -> bool:
        return self.level >= PermissionLevel.PAY
    
    # ── Whitelist Management ──────────────────────────
    
    def is_api_whitelisted(self, api_name: str) -> bool:
        if not api_name:
            return False
        return api_name in self.api_whitelist
    
    def add_whitelist(self, api_name: str):
        if api_name not in self.api_whitelist:
            self.api_whitelist.append(api_name)
            logger.info(f"API whitelisted: {api_name}")
    
    def remove_whitelist(self, api_name: str):
        if api_name in self.api_whitelist:
            self.api_whitelist.remove(api_name)
            logger.info(f"API removed from whitelist: {api_name}")
    
    # ── Safety ────────────────────────────────────────
    
    def check_anomaly(self, recent_actions: list) -> bool:
        """Check for anomalous activity patterns."""
        if not self.anomaly_detection:
            return False
        
        # High-frequency L2+ actions in short window
        high_level = [a for a in recent_actions if a.get("level", 0) >= 2]
        if len(high_level) > 10:
            logger.warning("ANOMALY: High-frequency L2+ actions detected")
            return True
        
        return False
