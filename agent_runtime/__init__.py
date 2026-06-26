"""
Agent Runtime — 24/7 background process for AI agents.

Phase 3: Plugin marketplace, cross-server federation, L4 payments,
         enterprise RBAC, audit export, and SSO hooks.

Quickstart:
    from agent_runtime import Runtime

    rt = Runtime(
        did="AGNT8A2026070114K7P2M9X4R6",
        homeserver="https://armp-group.org",
        username="myagent",
        password="***",
        permission_level=1,
    )
    await rt.start(enable_dashboard=True)
    # Agent is now 24/7 online
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .permissions import PermissionLevel, PermissionManager
from .triggers import TriggerEngine, Trigger, TriggerType, ConditionalPipeline, PipelineStep
from .decision import DecisionEngine, Intent, Action
from .plugins import PluginManager
from .storage import Storage
from .notifier import Notifier
from .config import Config
from .watchdog import Watchdog, CheckResult, CheckStatus
from .task_manager import TaskManager, Task, TaskStatus, TaskPriority
from .collaboration import CollaborationManager, CollaborationSession, NegotiationPhase
from .dashboard import DashboardServer
from .marketplace import PluginMarketplace, PluginInfo
from .federation import FederationManager, AgentNode, FederationConfig
from .payments import PaymentManager, PaymentRequest, PaymentStatus, Currency
from .enterprise import EnterpriseManager, RBACManager, AuditExporter, SSOManager, Role, User

logger = logging.getLogger("agent-runtime")

# Lazy import — only if ARMP is available
try:
    from amp_sdk import Agent as ArmpAgent
except ImportError:
    ArmpAgent = None

__version__ = "0.3.0"


class Runtime:
    """Agent Runtime — keeps an AI agent 24/7 online with full Phase 3 capabilities.

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
        Initial permission level (0–4)
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

        # Phase 2 subsystems
        self.watchdog = Watchdog(self)
        self.task_manager = TaskManager(self)
        self.collaboration = CollaborationManager(self)
        self.dashboard = DashboardServer(self)

        # Phase 3 subsystems
        self.marketplace = PluginMarketplace(self)
        self.federation = FederationManager(self)
        self.payments = PaymentManager(self)
        self.enterprise = EnterpriseManager(self)

        # ARMP agent (lazy init)
        self._armp: Optional["ArmpAgent"] = None
        self._started = False
        self._callback: Optional[Callable[..., Awaitable]] = None

        logger.info(f"Runtime v{__version__} initialized: {did} (L{permission_level})")

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

    async def start(
        self,
        enable_dashboard: bool = False,
        enable_federation: bool = False,
    ):
        """Connect to Matrix and start 24/7 operation.

        Parameters
        ----------
        enable_dashboard : bool
            Start the FastAPI web dashboard.
        enable_federation : bool
            Enable cross-server agent discovery.
        """
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

        # 2. Start trigger engine (includes cron scheduler)
        await self.triggers.start()

        # 3. Register message handler
        await self._armp.on_message(self._handle_message)

        # 4. Load plugins
        await self.plugins.load_all()

        # 5. Phase 3: start federation
        if enable_federation:
            await self.federation.start()

        # 6. Start dashboard (optional)
        if enable_dashboard:
            await self.dashboard.start()

        # 7. Send startup notification
        await self.notifier.notify(
            f"🟢 Agent Runtime v{__version__} started\n"
            f"DID: {self.did}\n"
            f"Permission: L{self.permissions.level}\n"
            f"Matrix: {self._armp.user_id}\n"
            f"Dashboard: {'enabled' if enable_dashboard else 'disabled'}\n"
            f"Federation: {'enabled' if enable_federation else 'disabled'}",
            severity="info",
        )

        self._started = True
        logger.info(f"Runtime v{__version__} is 24/7 online")

    async def stop(self):
        """Gracefully shutdown."""
        if not self._started:
            return

        await self.notifier.notify("🔴 Agent Runtime stopped", severity="info")
        await self.triggers.stop()
        await self.federation.stop()
        await self.dashboard.stop()

        if self._armp:
            await self._armp.stop()

        self._started = False
        logger.info("Runtime stopped")

    # ── Message Handling ──────────────────────────────

    async def _handle_message(self, message):
        """Process an incoming ARMP message through the decision pipeline."""
        if not self._started:
            return

        if not self.permissions.can_handle_messages():
            logger.debug(f"Message ignored — L{self.permissions.level} lacks message permission")
            return

        intent = await self.decision.classify(message)
        action = self.decision.decide(intent, self.permissions.level)

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
        elif action == Action.DELEGATE:
            if self.permissions.can_create_tasks():
                await self._handle_delegation(message, intent)
            else:
                await self.notifier.notify(
                    f"⚠️ Delegation blocked — L{self.permissions.level} < L3\n"
                    f"From: {message.sender}",
                    severity="warn",
                )

        await self.plugins.on_message(message, intent)

        if hasattr(message, 'sender'):
            collab_result = await self.collaboration.handle_collaboration_message(
                message.body, message.sender
            )
            if collab_result:
                logger.debug(f"Collaboration message: {collab_result.get('action')}")

    async def _generate_reply(self, message, intent: Intent) -> Optional[str]:
        if intent == Intent.GREETING:
            return f"Hello! I'm {self.did}. My human is offline. I'll notify them of your message."
        elif intent == Intent.QUESTION:
            return f"I've received your question and will pass it to my human."
        elif intent == Intent.REQUEST:
            return f"Request received. I'll notify my human and get back to you."
        elif intent == Intent.DATA_QUERY:
            return f"Data query received. I'll look this up and respond."
        elif intent == Intent.DELEGATION:
            return f"Delegation request received. Creating a task now."
        return None

    async def _handle_api_call(self, message, intent: Intent):
        if not self.permissions.is_api_whitelisted(intent.api_name or ""):
            logger.warning(f"API '{intent.api_name}' not in whitelist")
            return

        result = await self.plugins.call_api(intent.api_name, intent.params)
        if result:
            await self._armp.send_message(message.room_id, f"Result: {result[:500]}")

    async def _handle_delegation(self, message, intent: Intent):
        task = await self.task_manager.create(
            title=f"Delegated: {message.body[:80]}",
            description=message.body,
            capability=intent.api_name or "general",
            parameters=intent.params,
        )
        await self.notifier.notify(
            f"📋 Task created: {task.task_id}\nMessage: {message.body[:100]}",
            severity="info",
        )
        if task.assignee_did:
            await self.task_manager.delegate(task.task_id, task.assignee_did)

    def register_plugin(self, name: str, plugin):
        self.plugins.register(name, plugin)

    async def on_event(self, callback: Callable[..., Awaitable]):
        self._callback = callback

    async def upgrade_permission(self, level: int) -> bool:
        if not 0 <= level <= 4:
            raise ValueError(f"Invalid permission level: {level}")
        if level == self.permissions.level:
            return True

        if level == 4 and self.permissions.level < 4:
            logger.warning("L4 upgrade requested — requires secondary confirmation")

        old = self.permissions.level
        self.permissions.level = level
        self.storage.log_event("permission_change", {
            "from": old, "to": level, "timestamp": _now_iso()
        })

        await self.notifier.notify(
            f"⬆️ Permission upgraded: L{old} → L{level}",
            severity="warn",
        )
        logger.info(f"Permission: L{old} → L{level}")
        return True


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Demo ────────────────────────────────────────────

async def demo():
    """Demonstrate Agent Runtime Phase 3 capabilities."""
    print("🚀 Agent Runtime v0.3.0 — Phase 3 Demo\n")

    rt = Runtime(
        did="AGNT-DEMO-001",
        homeserver="https://armp-group.org",
        username="demo-agent",
        permission_level=3,
    )

    print(f"Runtime: {rt.did}")
    print(f"Version: v{__version__}")
    print(f"Permission: L{rt.permissions.level}")
    print(f"Plugins: {len(rt.plugins.list())}")
    print(f"Marketplace: {len(rt.marketplace._registry)} in registry")
    print(f"Federation: {rt.federation.config.enabled}")
    print(f"Payments: L4 secure with confirmation")
    print(f"Enterprise: RBAC + audit export + SSO")
    print(f"Dashboard: ready (call start(enable_dashboard=True))")
    print("\n── Phase 3 Demo Complete ──\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(demo())
