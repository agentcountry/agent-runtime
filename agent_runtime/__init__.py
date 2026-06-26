"""
Agent Runtime — 7×24 background process for AI agents.

Phase 1: Core runtime with ARMP integration, L0-L2 permissions,
         trigger engine, decision engine, and plugin interface.

Quickstart:
    from agent_runtime import Runtime
    
    rt = Runtime(
        did="AGNT8A2026070114K7P2M9X4R6",
        homeserver="https://armp-group.org",
        username="myagent",
        password="***",
        permission_level=1,  # L1
    )
    await rt.start()
    # Agent is now 24/7 online
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .permissions import PermissionLevel, PermissionManager
from .triggers import TriggerEngine, Trigger, TriggerType
from .decision import DecisionEngine, Intent, Action
from .plugins import PluginManager
from .storage import Storage
from .notifier import Notifier
from .config import Config

logger = logging.getLogger("agent-runtime")

# Lazy import — only if ARMP is available
try:
    from amp_sdk import Agent as ArmpAgent
except ImportError:
    ArmpAgent = None


class Runtime:
    """
    Agent Runtime — keeps an AI agent 24/7 online.
    
    Parameters
    ----------
    did : str
        Agent DID (from OurDID)
    homeserver : str
        Matrix homeserver URL
    username : str
        Matrix username
    password : str
        Matrix password
    permission_level : int
        Initial permission level (0-4)
    config_path : str
        Path to config file (default: ~/.agent-runtime/config.yaml)
    """
    
    def __init__(
        self,
        did: str,
        homeserver: str,
        username: str,
        password: str = "",
        permission_level: int = 0,
        config_path: str = "",
    ):
        self.did = did
        self.homeserver = homeserver
        self.username = username
        self.password = password
        
        # Subsystems
        self.config = Config(config_path)
        self.permissions = PermissionManager(permission_level)
        self.storage = Storage(self.config.db_path)
        self.plugins = PluginManager()
        self.notifier = Notifier(self)
        self.triggers = TriggerEngine(self)
        self.decision = DecisionEngine(self)
        
        # ARMP agent (lazy init)
        self._armp: Optional["ArmpAgent"] = None
        self._started = False
        self._callback: Optional[Callable[..., Awaitable]] = None
        
        logger.info(f"Runtime initialized: {did} (L{permission_level})")
    
    @property
    def is_running(self) -> bool:
        return self._started
    
    @property
    def armp(self):
        """Get the underlying ARMP agent. Requires start()."""
        if not self._armp:
            raise RuntimeError("Runtime not started. Call start() first.")
        return self._armp
    
    # ── Lifecycle ─────────────────────────────────────
    
    async def start(self):
        """Connect to Matrix and start 24/7 operation."""
        if self._started:
            logger.warning("Runtime already started")
            return
        
        if ArmpAgent is None:
            raise ImportError(
                "amp_sdk not found. Install ARMP SDK:\n"
                "  pip install armp-sdk"
            )
        
        # 1. Connect ARMP agent
        self._armp = ArmpAgent(
            did=self.did,
            homeserver=self.homeserver,
            username=self.username,
            password=self.password,
        )
        await self._armp.start()
        logger.info(f"ARMP agent online: {self._armp.user_id}")
        
        # 2. Start trigger engine
        await self.triggers.start()
        
        # 3. Register message handler
        await self._armp.on_message(self._handle_message)
        
        # 4. Load plugins
        await self.plugins.load_all()
        
        # 5. Send startup notification
        await self.notifier.notify(
            f"🟢 Agent Runtime started\n"
            f"DID: {self.did}\n"
            f"Permission: L{self.permissions.level}\n"
            f"Matrix: {self._armp.user_id}",
            severity="info",
        )
        
        self._started = True
        logger.info("Runtime is 24/7 online")
    
    async def stop(self):
        """Gracefully shutdown."""
        if not self._started:
            return
        
        await self.notifier.notify("🔴 Agent Runtime stopped", severity="info")
        await self.triggers.stop()
        
        if self._armp:
            await self._armp.stop()
        
        self._started = False
        logger.info("Runtime stopped")
    
    # ── Message Handling ──────────────────────────────
    
    async def _handle_message(self, message):
        """Process an incoming ARMP message through the decision pipeline."""
        if not self._started:
            return
        
        # 1. Permission check
        if not self.permissions.can_handle_messages():
            logger.debug(f"Message ignored — L{self.permissions.level} lacks message permission")
            return
        
        # 2. Decision engine
        intent = await self.decision.classify(message)
        action = self.decision.decide(intent, self.permissions.level)
        
        # 3. Execute action
        if action == Action.IGNORE:
            return
        elif action == Action.NOTIFY:
            await self.notifier.notify(
                f"📩 Message from {message.sender}:\n{message.body[:200]}",
                severity="info",
            )
        elif action == Action.REPLY:
            reply = await self._generate_reply(message, intent)
            if reply:
                await self._armp.send_message(message.room_id, reply)
        elif action == Action.API_CALL:
            if self.permissions.can_call_api():
                await self._handle_api_call(message, intent)
            else:
                await self.notifier.notify(
                    f"⚠️ API call blocked — L{self.permissions.level} insufficient\n"
                    f"From: {message.sender}",
                    severity="warn",
                )
        
        # 4. Invoke plugins
        await self.plugins.on_message(message, intent)
    
    async def _generate_reply(self, message, intent: Intent) -> Optional[str]:
        """Generate an automatic reply."""
        if intent == Intent.GREETING:
            return f"Hello! I'm {self.did}. My human is offline. I'll notify them of your message."
        elif intent == Intent.QUESTION:
            return f"I've received your question and will pass it to my human."
        elif intent == Intent.REQUEST:
            return f"Request received. I'll notify my human and get back to you."
        return None
    
    async def _handle_api_call(self, message, intent: Intent):
        """Handle an API-level request."""
        # Check against whitelist
        if not self.permissions.is_api_whitelisted(intent.api_name or ""):
            logger.warning(f"API '{intent.api_name}' not in whitelist")
            return
        
        # Execute via plugins
        result = await self.plugins.call_api(intent.api_name, intent.params)
        if result:
            await self._armp.send_message(
                message.room_id,
                f"Result: {result[:500]}",
            )
    
    # ── Plugin Registration ───────────────────────────
    
    def register_plugin(self, name: str, plugin):
        """Register a plugin."""
        self.plugins.register(name, plugin)
    
    # ── User API ─────────────────────────────────────
    
    async def on_event(self, callback: Callable[..., Awaitable]):
        """Register a callback for runtime events.
        
        Events: message_received, trigger_fired, permission_denied, error
        """
        self._callback = callback
    
    async def upgrade_permission(self, level: int) -> bool:
        """Request permission level upgrade."""
        if not 0 <= level <= 4:
            raise ValueError(f"Invalid permission level: {level}")
        if level == self.permissions.level:
            return True
        
        old = self.permissions.level
        self.permissions.level = level
        self.storage.log_event("permission_change", {
            "from": old, "to": level, "timestamp": self._now_iso()
        })
        
        await self.notifier.notify(
            f"⬆️ Permission upgraded: L{old} → L{level}",
            severity="warn",
        )
        logger.info(f"Permission: L{old} → L{level}")
        return True
    
    def _now_iso(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()


# ── Demo ────────────────────────────────────────────

async def demo():
    """Demonstrate Agent Runtime with a simple agent."""
    print("🚀 Agent Runtime v0.1.0 — Demo\n")
    
    rt = Runtime(
        did="AGNT-DEMO-001",
        homeserver="https://armp-group.org",
        username="demo-agent",
        password="demo",
        permission_level=0,
    )
    
    print(f"Runtime: {rt.did}")
    print(f"Permission: L{rt.permissions.level}")
    print(f"Storage: {rt.storage.db_path}")
    print(f"Plugins loaded: {len(rt.plugins.list())}")
    print("\n── Demo Complete ──\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(demo())
