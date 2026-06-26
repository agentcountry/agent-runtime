"""
Federation — cross-server agent discovery and multi-Runtime coordination.

Phase 3: Enables Runtime instances on different Matrix homeservers
to discover each other, register capabilities, and collaborate
across server boundaries through a federated directory.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.federation")


@dataclass
class AgentNode:
    """A registered agent node in the federation directory."""
    did: str
    matrix_id: str = ""
    homeserver: str = ""
    display_name: str = ""
    capabilities: list = field(default_factory=list)
    permission_level: int = 0
    online: bool = False
    last_seen: str = ""
    version: str = ""
    tags: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "did": self.did,
            "matrix_id": self.matrix_id,
            "homeserver": self.homeserver,
            "display_name": self.display_name,
            "capabilities": self.capabilities,
            "permission_level": self.permission_level,
            "online": self.online,
            "last_seen": self.last_seen,
            "version": self.version,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentNode":
        return cls(**{
            k: data.get(k, "" if v.default == "" else ([] if v.default == field(default_factory=list) else v.default))
            for k, v in cls.__dataclass_fields__.items()
            if k != "metadata"
        })


@dataclass
class FederationConfig:
    """Configuration for federation."""
    enabled: bool = True
    announce_interval: int = 300          # Seconds between announcements
    discovery_interval: int = 600         # Seconds between discovery scans
    trusted_homeservers: list = field(default_factory=list)
    max_nodes: int = 1000
    auto_join_rooms: bool = True


class FederationManager:
    """Cross-server agent discovery and coordination."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self.config = FederationConfig()
        self._directory: dict[str, AgentNode] = {}  # did → AgentNode
        self._by_capability: dict[str, set[str]] = {}  # capability → set of DIDs
        self._rooms: dict[str, str] = {}  # did → room_id
        self._running = False
        self._announce_task: Optional[asyncio.Task] = None
        self._discovery_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start federation background tasks."""
        if not self.config.enabled:
            return

        self._running = True
        self._announce_task = asyncio.create_task(self._announce_loop())
        self._discovery_task = asyncio.create_task(self._discovery_loop())
        logger.info("Federation started")

    async def stop(self):
        self._running = False
        for task in [self._announce_task, self._discovery_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # ── Directory Operations ────────────────────────────

    def register_node(self, node: AgentNode):
        """Register an agent in the federation directory."""
        self._directory[node.did] = node

        # Index capabilities
        for cap in node.capabilities:
            if cap not in self._by_capability:
                self._by_capability[cap] = set()
            self._by_capability[cap].add(node.did)

        logger.debug(f"Federation: registered {node.did} ({len(node.capabilities)} capabilities)")

    def unregister_node(self, did: str):
        """Remove an agent from the directory."""
        if did in self._directory:
            node = self._directory[did]
            for cap in node.capabilities:
                if cap in self._by_capability:
                    self._by_capability[cap].discard(did)

            del self._directory[did]
            logger.debug(f"Federation: unregistered {did}")

    # ── Discovery ───────────────────────────────────────

    def discover(self, capability: str = "", online_only: bool = True) -> list[AgentNode]:
        """Find agents by capability."""
        if capability:
            dids = self._by_capability.get(capability, set())
            nodes = [self._directory[d] for d in dids if d in self._directory]
        else:
            nodes = list(self._directory.values())

        if online_only:
            nodes = [n for n in nodes if n.online]

        return sorted(nodes, key=lambda n: n.last_seen, reverse=True)

    def find_by_did(self, did: str) -> Optional[AgentNode]:
        return self._directory.get(did)

    def search(self, query: str = "", tags: list = None) -> list[AgentNode]:
        """Text search across the directory."""
        results = list(self._directory.values())

        if query:
            q = query.lower()
            results = [
                n for n in results
                if q in n.did.lower()
                or q in n.display_name.lower()
                or any(q in cap.lower() for cap in n.capabilities)
            ]

        if tags:
            results = [n for n in results if all(t in n.tags for t in tags)]

        return results

    # ── Room Management ─────────────────────────────────

    def get_room(self, did: str) -> str:
        """Get Matrix room ID for an agent."""
        return self._rooms.get(did, "")

    async def join_room(self, did: str, room_id: str):
        """Join a Matrix room with another agent."""
        self._rooms[did] = room_id
        if self.runtime._started and self.runtime._armp:
            try:
                await self.runtime._armp.join_room(room_id)
                logger.info(f"Federation: joined room {room_id} with {did}")
            except Exception as e:
                logger.error(f"Failed to join room {room_id}: {e}")

    # ── Background Loops ────────────────────────────────

    async def _announce_loop(self):
        """Periodically announce this agent's presence."""
        self_node = AgentNode(
            did=self.runtime.did,
            matrix_id=self.runtime._armp.user_id if self.runtime._armp else "",
            homeserver=self.runtime.homeserver,
            display_name=self.runtime.did,
            capabilities=self.runtime.plugins.list(),
            permission_level=self.runtime.permissions.level,
            online=True,
            last_seen=_now_iso(),
            version=self.runtime.__class__.__module__.split(".")[0],
        )
        self.register_node(self_node)

        while self._running:
            try:
                self_node.last_seen = _now_iso()
                self_node.online = self.runtime.is_running
                self.register_node(self_node)
            except Exception as e:
                logger.error(f"Announce error: {e}")
            await asyncio.sleep(self.config.announce_interval)

    async def _discovery_loop(self):
        """Periodically scan for new agents."""
        while self._running:
            try:
                # Phase 3: Query ARMP directory for new agents
                # Stub: federation via Matrix room discovery
                pass
            except Exception as e:
                logger.error(f"Discovery error: {e}")
            await asyncio.sleep(self.config.discovery_interval)

    # ── Stats ───────────────────────────────────────────

    def stats(self) -> dict:
        online = [n for n in self._directory.values() if n.online]
        return {
            "total_nodes": len(self._directory),
            "online_nodes": len(online),
            "capabilities_indexed": len(self._by_capability),
            "rooms_joined": len(self._rooms),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
