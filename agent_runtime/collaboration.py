"""
Collaboration — Agent-to-Agent negotiation and task coordination via ARMP.

Phase 2: Enables two Runtime agents to discover each other's capabilities,
negotiate task assignments, and hand off work through ARMP Matrix rooms.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.collaboration")


class NegotiationPhase(str, Enum):
    """Phases of an agent negotiation."""
    DISCOVERY = "discovery"        # "What can you do?"
    CAPABILITY_MATCH = "cap_match" # "I need X, you have X — interested?"
    PROPOSAL = "proposal"          # "Here are the terms"
    ACCEPTANCE = "acceptance"      # "Deal!"
    EXECUTION = "execution"        # Task in progress
    COMPLETION = "completion"      # Done


@dataclass
class CollaborationSession:
    """A single collaboration session between two agents."""
    session_id: str
    initiator_did: str
    partner_did: str
    phase: NegotiationPhase = NegotiationPhase.DISCOVERY
    room_id: str = ""
    capability_requested: str = ""
    parameters: dict = field(default_factory=dict)
    result: Optional[dict] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now


class CollaborationManager:
    """Manages agent-to-agent collaboration sessions."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._sessions: dict[str, CollaborationSession] = {}
        self._negotiation_handlers: dict[str, Callable] = {}

    # ── Session Management ──────────────────────────────

    async def initiate(
        self,
        partner_did: str,
        capability: str,
        parameters: dict = None,
    ) -> CollaborationSession:
        """Initiate a collaboration with another agent."""
        import uuid

        session = CollaborationSession(
            session_id=f"COLLAB-{uuid.uuid4().hex[:8].upper()}",
            initiator_did=self.runtime.did,
            partner_did=partner_did,
            capability_requested=capability,
            parameters=parameters or {},
        )
        self._sessions[session.session_id] = session

        logger.info(
            f"Collaboration initiated: {session.session_id} "
            f"({self.runtime.did} requesting '{capability}' from {partner_did})"
        )

        # Send capability query via ARMP
        if self.runtime._started and self.runtime._armp:
            room = self._resolve_room(partner_did)
            if room:
                await self.runtime._armp.send_message(
                    room,
                    _format_negotiation_message("CAPABILITY_QUERY", {
                        "session_id": session.session_id,
                        "requester_did": self.runtime.did,
                        "capability": capability,
                        "parameters": parameters or {},
                    }),
                )
                session.room_id = room

        self.runtime.storage.audit("collaboration_initiated", {
            "session_id": session.session_id,
            "partner": partner_did,
            "capability": capability,
        })

        return session

    async def respond_to_query(
        self,
        session_id: str,
        accept: bool,
        message: str = "",
    ) -> bool:
        """Respond to an incoming capability query."""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Unknown collaboration session: {session_id}")
            return False

        if accept:
            session.phase = NegotiationPhase.CAPABILITY_MATCH
            session.updated_at = _now_iso()

            # Propose terms
            if self.runtime._started and self.runtime._armp and session.room_id:
                await self.runtime._armp.send_message(
                    session.room_id,
                    _format_negotiation_message("CAPABILITY_ACCEPT", {
                        "session_id": session.session_id,
                        "provider_did": self.runtime.did,
                        "message": message or "I can handle this task.",
                    }),
                )

            await self.runtime.notifier.notify(
                f"🤝 Accepted collaboration: {session.session_id} — {session.capability_requested}",
                severity="info",
            )
        else:
            session.phase = NegotiationPhase.COMPLETION
            if self.runtime._started and self.runtime._armp and session.room_id:
                await self.runtime._armp.send_message(
                    session.room_id,
                    _format_negotiation_message("CAPABILITY_REJECT", {
                        "session_id": session.session_id,
                        "provider_did": self.runtime.did,
                        "reason": message or "Capability not available.",
                    }),
                )

        return True

    async def complete(self, session_id: str, result: dict = None) -> bool:
        """Mark a collaboration session as completed."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.phase = NegotiationPhase.COMPLETION
        session.result = result
        session.updated_at = _now_iso()

        if self.runtime._started and self.runtime._armp and session.room_id:
            await self.runtime._armp.send_message(
                session.room_id,
                _format_negotiation_message("TASK_COMPLETE", {
                    "session_id": session.session_id,
                    "provider_did": self.runtime.did,
                    "result": result or {},
                }),
            )

        self.runtime.storage.audit("collaboration_completed", {
            "session_id": session.session_id,
            "result": result,
        })

        logger.info(f"Collaboration {session.session_id} completed")
        return True

    # ── Incoming Message Handler ────────────────────────

    async def handle_collaboration_message(self, message_body: str, sender_did: str) -> Optional[dict]:
        """Process an ARMP message that may be a collaboration negotiation."""
        try:
            data = json.loads(message_body)
        except json.JSONDecodeError:
            return None  # Not a collaboration message

        msg_type = data.get("type", "")

        if msg_type == "CAPABILITY_QUERY":
            return {
                "action": "query_received",
                "session_id": data.get("session_id"),
                "requester": data.get("requester_did"),
                "capability": data.get("capability"),
                "parameters": data.get("parameters", {}),
            }

        elif msg_type == "CAPABILITY_ACCEPT":
            return {
                "action": "proposal_received",
                "session_id": data.get("session_id"),
                "provider": data.get("provider_did"),
            }

        elif msg_type == "CAPABILITY_REJECT":
            return {
                "action": "rejected",
                "session_id": data.get("session_id"),
                "reason": data.get("reason", ""),
            }

        elif msg_type == "TASK_COMPLETE":
            return {
                "action": "result_received",
                "session_id": data.get("session_id"),
                "result": data.get("result", {}),
            }

        return None

    # ── Session Queries ─────────────────────────────────

    def get(self, session_id: str) -> Optional[CollaborationSession]:
        return self._sessions.get(session_id)

    def list_active(self) -> list[CollaborationSession]:
        return [
            s for s in self._sessions.values()
            if s.phase != NegotiationPhase.COMPLETION
        ]

    def stats(self) -> dict:
        sessions = list(self._sessions.values())
        return {
            "total_sessions": len(sessions),
            "active": sum(1 for s in sessions if s.phase != NegotiationPhase.COMPLETION),
            "completed": sum(1 for s in sessions if s.phase == NegotiationPhase.COMPLETION),
        }

    # ── Internal ────────────────────────────────────────

    def _resolve_room(self, agent_did: str) -> str:
        """Resolve an agent DID to a Matrix room ID."""
        # TODO: Phase 3 — query ARMP directory
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_negotiation_message(msg_type: str, data: dict) -> str:
    """Format a collaboration message as ARMP-compatible JSON."""
    return json.dumps({"type": msg_type, **data}, indent=2)
