"""
ARMP Python SDK v0.5.0

Agent Real-time Message Protocol — Python client library.
Real Matrix integration via matrix-nio. Apache 2.0.

Quickstart:
    from amp_sdk import Agent, AgentCard, Task, NegotiationResult
    import asyncio

    async def main():
        agent = Agent(
            did="AGNT8A2026070114K7P2M9X4R6",
            homeserver="https://armp-group.org",
            username="dataanalyzer",
            password="***"
        )
        await agent.start()
        await agent.send_message("@peer:armp-group.org", "Hello!")
        await agent.stop()

    asyncio.run(main())
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Awaitable

import aiofiles
import nio

logger = logging.getLogger("amp-sdk")


# ── Helpers ────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Constants ────────────────────────────────────────────

ARMP_ACCOUNT_DATA_DID = "m.agent.did"
ARMP_MSG_TYPE = "m.agent.message"
ARMP_TASK_TYPE = "m.agent.task"
ARMP_CAP_REQUEST = "m.agent.capability_request"
ARMP_CAP_RESPONSE = "m.agent.capability_response"


# ── Data Models ──────────────────────────────────────────

@dataclass
class AgentCard:
    """An agent's public identity and capability card."""
    did: str
    name: str
    matrix_id: str
    description: str = ""
    capabilities: list = field(default_factory=list)
    endpoints: dict = field(default_factory=dict)
    version: str = "0.5.0"

    def to_dict(self) -> dict:
        return {
            "did": self.did,
            "name": self.name,
            "matrix_id": self.matrix_id,
            "description": self.description,
            "capabilities": self.capabilities,
            "endpoints": self.endpoints,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentCard":
        return cls(
            did=data.get("did", ""),
            name=data.get("name", ""),
            matrix_id=data.get("matrix_id", ""),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            endpoints=data.get("endpoints", {}),
            version=data.get("version", "0.5.0"),
        )


@dataclass
class Message:
    """An ARMP message received from another agent."""
    event_id: str
    sender: str
    body: str
    room_id: str
    timestamp: int
    msgtype: str = "m.text"
    armp_metadata: dict = field(default_factory=dict)


@dataclass
class Task:
    """A task with full lifecycle: CREATED → ASSIGNED → IN_PROGRESS → COMPLETED/FAILED."""

    TASK_STATUSES = ["CREATED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"]
    VALID_TRANSITIONS = {
        "CREATED": ["ASSIGNED", "CANCELLED"],
        "ASSIGNED": ["IN_PROGRESS", "CANCELLED"],
        "IN_PROGRESS": ["COMPLETED", "FAILED", "CANCELLED"],
        "COMPLETED": [],
        "FAILED": ["ASSIGNED"],  # retry
        "CANCELLED": [],
    }

    task_id: str
    sender_did: str
    assignee_did: str
    status: str = "CREATED"
    spec: dict = field(default_factory=dict)
    result: Optional[dict] = None
    progress: float = 0.0
    history: list = field(default_factory=list)

    def transition(self, new_status: str, detail: str = "") -> bool:
        """Transition task to a new status. Returns True if valid."""
        if new_status not in self.VALID_TRANSITIONS.get(self.status, []):
            logger.warning(f"Invalid task transition: {self.status} → {new_status}")
            return False
        old_status = self.status
        self.status = new_status
        self.history.append({
            "from": old_status, "to": new_status,
            "detail": detail,
            "timestamp": _now_iso(),
        })
        logger.info(f"Task {self.task_id}: {old_status} → {new_status}")
        return True


@dataclass
class NegotiationResult:
    """Result of a capability negotiation between two agents."""
    peer_did: str
    peer_card: AgentCard
    my_capabilities: list[str]
    peer_capabilities: list[str]
    mutual_capabilities: list[str]
    missing_capabilities: list[str]
    matched: bool


# ── Agent Class ──────────────────────────────────────────

class Agent:
    """
    An ARMP-compliant AI agent with full Matrix integration.

    Parameters
    ----------
    did : str
        Agent's DID (e.g., AGNT8A2026070114K7P2M9X4R6)
    homeserver : str
        Matrix homeserver URL (e.g., https://armp-group.org)
    username : str
        Matrix username (localpart)
    password : str
        Matrix password
    access_token : str, optional
        Existing Matrix access token (skip login if provided)
    store_path : str, optional
        Path for E2E encryption store
    """

    def __init__(
        self,
        did: str,
        homeserver: str,
        username: str,
        password: str = "",
        access_token: str = "",
        store_path: str = "./armp_store",
    ):
        self.did = did
        self.homeserver = homeserver.rstrip("/")
        self.username = username
        self.password = password
        self._store_path = store_path
        self._client: Optional[nio.AsyncClient] = None
        self._started = False
        self._card: Optional[AgentCard] = None
        self._message_callback: Optional[Callable[[Message], Awaitable[None]]] = None
        self._peers: dict[str, AgentCard] = {}
        self._active_tasks: dict[str, Task] = {}
        self._discovery_room_id: Optional[str] = None

        # Init client
        if access_token:
            self._client = nio.AsyncClient(
                homeserver=self.homeserver,
                user=username,
                store_path=store_path,
            )
            self._client.access_token = access_token
        else:
            self._client = nio.AsyncClient(
                homeserver=self.homeserver,
                user=username,
                store_path=store_path,
            )

    # ── Lifecycle ─────────────────────────────────────

    async def start(self):
        """Connect to the Matrix homeserver and start syncing."""
        if not self._client.access_token and self.password:
            resp = await self._client.login(self.password)
            if isinstance(resp, nio.LoginError):
                raise RuntimeError(f"Login failed: {resp.message}")
            logger.info(f"Logged in as {self._client.user_id}")

        # Bind DID
        await self._bind_did()

        # Start sync loop
        self._started = True
        self._sync_task = asyncio.create_task(self._sync_loop())

        # Set initial presence
        await self.set_presence("online")

        logger.info(f"Agent {self.did} is online ({self._client.user_id})")

    async def stop(self):
        """Disconnect from the homeserver."""
        self._started = False
        await self.set_presence("offline")
        if self._client:
            await self._client.close()
        logger.info(f"Agent {self.did} is offline")

    async def _sync_loop(self):
        """Background sync loop for receiving messages."""
        sync_token = None
        while self._started:
            try:
                resp = await self._client.sync(
                    timeout=30000,
                    since=sync_token,
                    sync_filter=self._build_filter(),
                )
                if isinstance(resp, nio.SyncError):
                    logger.error(f"Sync error: {resp.message}")
                    await asyncio.sleep(5)
                    continue

                sync_token = resp.next_batch

                # Process room events
                for room_id, room in resp.rooms.join.items():
                    for event in room.timeline.events:
                        await self._handle_event(room_id, event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                await asyncio.sleep(5)

    def _build_filter(self):
        """Build a sync filter for relevant events only."""
        return {
            "room": {
                "timeline": {
                    "types": [
                        "m.room.message",
                        ARMP_MSG_TYPE,
                        ARMP_TASK_TYPE,
                        ARMP_CAP_REQUEST,
                        ARMP_CAP_RESPONSE,
                        "m.room.member",
                    ]
                },
                "ephemeral": {"types": ["m.typing", "m.receipt"]},
            },
            "account_data": {"types": [ARMP_ACCOUNT_DATA_DID]},
            "presence": {"types": ["m.presence"]},
        }

    async def _handle_event(self, room_id: str, event):
        """Handle an incoming Matrix event."""
        if event.sender == self._client.user_id:
            return  # Skip own messages

        body = ""
        msgtype = "m.text"
        armp_meta = {}

        if hasattr(event, "source"):
            content = event.source.get("content", {})
            body = content.get("body", "")
            msgtype = content.get("msgtype", "m.text")
            armp_meta = content.get("m.agent", {})

            # Dispatch special ARMP events
            event_type = event.source.get("type", "")
            if event_type == ARMP_CAP_REQUEST:
                await self._handle_cap_request(room_id, event)
                return
            if event_type == ARMP_CAP_RESPONSE:
                await self._handle_cap_response(room_id, event)
                return
            if event_type == ARMP_TASK_TYPE:
                await self._handle_task_event(room_id, event)
                # Fall through to message callback for task bodies

        if not body:
            return

        msg = Message(
            event_id=event.event_id,
            sender=event.sender,
            body=body,
            room_id=room_id,
            timestamp=event.server_timestamp,
            msgtype=msgtype,
            armp_metadata=armp_meta,
        )

        # Send read receipt
        await self.mark_read(room_id, event.event_id)

        # Callback
        if self._message_callback:
            await self._message_callback(msg)

    async def _bind_did(self):
        """Store DID in Matrix account data."""
        await self._client.update_account_data(
            {ARMP_ACCOUNT_DATA_DID: {
                "did": self.did,
                "bound_at": _now_iso(),
                "verified": False,
            }}
        )

    async def _handle_cap_request(self, room_id: str, event):
        """Auto-respond to capability negotiation requests."""
        if not self._card:
            return
        content = event.source.get("content", {})
        armp_meta = content.get("m.agent", {})
        request_id = armp_meta.get("request_id", "")
        logger.info(f"Capability request from {event.sender} (req={request_id})")
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_CAP_RESPONSE,
            content={
                "body": f"Capability card for {self.did}",
                "m.agent": {
                    "request_id": request_id,
                    "agent_card": self._card.to_dict(),
                },
            },
        )

    async def _handle_cap_response(self, room_id: str, event):
        """Store peer's capability card from a negotiation response."""
        content = event.source.get("content", {})
        armp_meta = content.get("m.agent", {})
        card_data = armp_meta.get("agent_card", {})
        if card_data and card_data.get("did"):
            peer_card = AgentCard.from_dict(card_data)
            self._peers[peer_card.did] = peer_card
            logger.info(f"Stored card for {peer_card.did}: {[c['name'] for c in peer_card.capabilities]}")

    async def _handle_task_event(self, room_id: str, event):
        """Handle incoming task creation/update events."""
        content = event.source.get("content", {})
        armp_meta = content.get("m.agent", {})
        task_id = armp_meta.get("task_id", "")
        status = armp_meta.get("status", "")
        logger.info(f"Task event: {task_id} status={status} from {event.sender}")

    # ── Presence ──────────────────────────────────────

    async def set_presence(self, status: str):
        """Set online presence. Status: online, offline, unavailable."""
        await self._client.set_presence(
            presence=status,
            status_msg=f"ARMP Agent: {self.did}",
        )
        logger.debug(f"Presence: {status}")

    @property
    def is_online(self) -> bool:
        return self._started

    # ── Messaging ─────────────────────────────────────

    async def send_message(
        self,
        target: str,
        body: str,
        msgtype: str = "m.text",
        armp_meta: dict = None,
    ) -> str:
        """Send a message to a room or user.

        Parameters
        ----------
        target : str
            Room ID (!xxx:server) or user ID (@xxx:server)
        body : str
            Message text
        msgtype : str
            Matrix message type
        armp_meta : dict
            ARMP metadata to attach

        Returns
        -------
        str
            Event ID of the sent message
        """
        room_id = target if target.startswith("!") else await self._ensure_dm(target)

        content = {
            "body": body,
            "msgtype": msgtype,
        }
        if armp_meta:
            content["m.agent"] = armp_meta

        # Send typing
        await self.typing(room_id, True)

        resp = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        await self.typing(room_id, False)

        if isinstance(resp, nio.RoomSendError):
            raise RuntimeError(f"Send failed: {resp.message}")

        logger.info(f"→ [{target}] {body[:50]}...")
        return resp.event_id

    async def on_message(self, callback: Callable[[Message], Awaitable[None]]):
        """Register a callback for incoming messages."""
        self._message_callback = callback

    # ── Rooms ─────────────────────────────────────────

    async def create_room(
        self,
        name: str,
        members: Optional[list] = None,
        is_direct: bool = False,
        topic: str = "",
    ) -> str:
        """Create a new room and invite members.

        Returns
        -------
        str
            Room ID (!xxx:server)
        """
        resp = await self._client.room_create(
            name=name,
            topic=topic,
            is_direct=is_direct,
            invite=members or [],
            preset="trusted_private_chat" if is_direct else "private_chat",
        )
        if isinstance(resp, nio.RoomCreateError):
            raise RuntimeError(f"Room create failed: {resp.message}")

        logger.info(f"Room created: {name} ({resp.room_id})")
        return resp.room_id

    async def join_room(self, room_id: str):
        """Join an existing room."""
        resp = await self._client.join(room_id)
        if isinstance(resp, nio.JoinError):
            raise RuntimeError(f"Join failed: {resp.message}")

    async def leave_room(self, room_id: str):
        """Leave a room."""
        await self._client.room_leave(room_id)

    async def invite(self, room_id: str, user_id: str):
        """Invite a user to a room."""
        resp = await self._client.room_invite(room_id, user_id)
        if isinstance(resp, nio.RoomInviteError):
            raise RuntimeError(f"Invite failed: {resp.message}")

    async def _ensure_dm(self, user_id: str) -> str:
        """Find existing DM or create one with user_id."""
        # Check joined rooms for existing DM
        resp = await self._client.joined_rooms()
        if isinstance(resp, nio.JoinedRoomsError):
            raise RuntimeError(f"Failed to list rooms: {resp.message}")

        for room_id in resp.rooms:
            members_resp = await self._client.joined_members(room_id)
            if isinstance(members_resp, nio.JoinedMembersError):
                continue
            members = [m.user_id for m in members_resp.members]
            if len(members) == 2 and user_id in members:
                return room_id

        # Create new DM
        return await self.create_room(
            name=f"DM: {self.username} ↔ {user_id}",
            members=[user_id],
            is_direct=True,
        )

    # ── Message History ───────────────────────────────

    async def get_history(
        self,
        room_id: str,
        limit: int = 50,
    ) -> list[Message]:
        """Fetch message history from a room."""
        resp = await self._client.room_messages(
            room_id=room_id,
            start="",
            limit=limit,
        )
        if isinstance(resp, nio.RoomMessagesError):
            raise RuntimeError(f"History fetch failed: {resp.message}")

        messages = []
        for event in resp.chunk:
            if hasattr(event, "source"):
                content = event.source.get("content", {})
                body = content.get("body", "")
                if body:
                    messages.append(Message(
                        event_id=event.event_id,
                        sender=event.sender,
                        body=body,
                        room_id=room_id,
                        timestamp=event.server_timestamp,
                        msgtype=content.get("msgtype", "m.text"),
                        armp_metadata=content.get("m.agent", {}),
                    ))
        return messages

    # ── Typing Indicators ─────────────────────────────

    async def typing(self, room_id: str, is_typing: bool = True, timeout: int = 15000):
        """Send typing notification."""
        await self._client.room_typing(room_id, is_typing, timeout)
        logger.debug(f"Typing {'on' if is_typing else 'off'} in {room_id}")

    # ── Read Receipts ─────────────────────────────────

    async def mark_read(self, room_id: str, event_id: str):
        """Send read receipt for a message."""
        await self._client.room_read_markers(
            room_id=room_id,
            fully_read_event=event_id,
            read_event=event_id,
        )

    # ── File Transfer ─────────────────────────────────

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: str = "",
        mime_type: str = "",
    ) -> str:
        """Send a file to a room or user.

        Parameters
        ----------
        target : str
            Room ID or user ID
        file_path : str
            Local file path
        filename : str
            Display name (defaults to basename)
        mime_type : str
            MIME type (auto-detected if empty)

        Returns
        -------
        str
            Event ID
        """
        room_id = target if target.startswith("!") else await self._ensure_dm(target)

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = filename or path.name

        # Upload to Matrix content repository
        async with aiofiles.open(file_path, "rb") as f:
            data = await f.read()

        resp = await self._client.upload(
            data,
            content_type=mime_type or "application/octet-stream",
            filename=filename,
        )
        if isinstance(resp, nio.UploadError):
            raise RuntimeError(f"Upload failed: {resp.message}")

        # Send file message
        content = {
            "body": filename,
            "msgtype": "m.file",
            "url": resp.content_uri,
            "filename": filename,
            "size": len(data),
        }

        send_resp = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        if isinstance(send_resp, nio.RoomSendError):
            raise RuntimeError(f"File send failed: {send_resp.message}")

        logger.info(f"📎 [{target}] {filename} ({len(data)} bytes)")
        return send_resp.event_id

    # ── Tasks (Phase 3: Full Lifecycle) ────────────────

    async def create_task(
        self,
        assignee_did: str,
        spec: dict,
        assignee_user_id: str = "",
    ) -> Task:
        """Create a new task and assign it to an agent.

        The task starts in CREATED status. Call assign() to move to ASSIGNED.
        """
        task = Task(
            task_id=str(uuid.uuid4()),
            sender_did=self.did,
            assignee_did=assignee_did,
            spec=spec,
            status="CREATED",
        )

        self._active_tasks[task.task_id] = task

        if assignee_user_id:
            room_id = await self._ensure_dm(assignee_user_id)
            await self._client.room_send(
                room_id=room_id,
                message_type=ARMP_TASK_TYPE,
                content={
                    "body": spec.get("description", "New task"),
                    "m.agent": {
                        "task_id": task.task_id,
                        "status": "CREATED",
                        "sender_did": self.did,
                        "assignee_did": assignee_did,
                        "spec": spec,
                    },
                },
            )

        logger.info(f"Task {task.task_id} → {assignee_did} [CREATED]")
        return task

    async def assign_task(self, task: Task, assignee_user_id: str) -> bool:
        """Assign a task to an agent (CREATED → ASSIGNED)."""
        if not task.transition("ASSIGNED", f"Assigned to {assignee_user_id}"):
            return False
        room_id = await self._ensure_dm(assignee_user_id)
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_TASK_TYPE,
            content={
                "body": f"Task assigned: {task.spec.get('description', task.task_id)}",
                "m.agent": {
                    "task_id": task.task_id,
                    "status": "ASSIGNED",
                    "sender_did": self.did,
                    "assignee_did": task.assignee_did,
                },
            },
        )
        return True

    async def start_task(self, task: Task, room_id: str) -> bool:
        """Start working on a task (ASSIGNED → IN_PROGRESS)."""
        if not task.transition("IN_PROGRESS", "Work started"):
            return False
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_TASK_TYPE,
            content={
                "body": f"Task in progress: {task.spec.get('description', task.task_id)}",
                "m.agent": {
                    "task_id": task.task_id,
                    "status": "IN_PROGRESS",
                    "sender_did": self.did,
                    "assignee_did": task.assignee_did,
                },
            },
        )
        return True

    async def report_progress(
        self, task: Task, room_id: str, progress: float, detail: str = ""
    ) -> bool:
        """Report task progress (0.0-1.0). Sends a progress update event."""
        task.progress = max(0.0, min(1.0, progress))
        logger.info(f"Task {task.task_id}: {task.progress * 100:.0f}% — {detail}")
        await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "body": f"Progress: {task.progress * 100:.0f}% — {detail}",
                "msgtype": "m.notice",
                "m.agent": {
                    "task_id": task.task_id,
                    "progress": task.progress,
                    "detail": detail,
                },
            },
        )
        return True

    async def complete_task(self, task: Task, room_id: str, result: dict = None) -> bool:
        """Mark a task as completed (IN_PROGRESS → COMPLETED)."""
        if not task.transition("COMPLETED", "Task completed successfully"):
            return False
        task.result = result or {}
        task.progress = 1.0
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_TASK_TYPE,
            content={
                "body": f"Task completed: {task.spec.get('description', task.task_id)}",
                "m.agent": {
                    "task_id": task.task_id,
                    "status": "COMPLETED",
                    "sender_did": self.did,
                    "assignee_did": task.assignee_did,
                    "result": result,
                },
            },
        )
        return True

    async def fail_task(self, task: Task, room_id: str, reason: str = "") -> bool:
        """Mark a task as failed (IN_PROGRESS → FAILED)."""
        if not task.transition("FAILED", reason or "Task failed"):
            return False
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_TASK_TYPE,
            content={
                "body": f"Task failed: {reason or task.spec.get('description', task.task_id)}",
                "m.agent": {
                    "task_id": task.task_id,
                    "status": "FAILED",
                    "sender_did": self.did,
                    "assignee_did": task.assignee_did,
                    "reason": reason,
                },
            },
        )
        return True

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID from the local task registry."""
        return self._active_tasks.get(task_id)

    # ── Capability Negotiation (Phase 3) ──────────────

    async def negotiate(self, peer_user_id: str) -> NegotiationResult:
        """Negotiate capabilities with a peer agent.

        Sends my card, waits for their response, and computes match results.
        Call this after both agents have registered capabilities via set_capability().
        """
        if not self._card:
            raise RuntimeError("No AgentCard — call set_capability() first")

        room_id = await self._ensure_dm(peer_user_id)
        request_id = str(uuid.uuid4())

        # Send my card
        await self._client.room_send(
            room_id=room_id,
            message_type=ARMP_CAP_REQUEST,
            content={
                "body": f"Capability request from {self.did}",
                "m.agent": {
                    "request_id": request_id,
                    "agent_card": self._card.to_dict(),
                },
            },
        )

        # Wait for response (poll up to 10 seconds)
        peer_card = None
        for _ in range(20):
            await asyncio.sleep(0.5)
            for card in self._peers.values():
                peer_card = card
                break
            if peer_card:
                break

        if not peer_card:
            raise RuntimeError("Peer did not respond with capability card after 10 seconds")

        # Compute match
        my_caps = {c["name"] for c in self._card.capabilities}
        peer_caps = {c["name"] for c in peer_card.capabilities}
        mutual = list(my_caps & peer_caps)
        missing = list(peer_caps - my_caps)

        return NegotiationResult(
            peer_did=peer_card.did,
            peer_card=peer_card,
            my_capabilities=list(my_caps),
            peer_capabilities=list(peer_caps),
            mutual_capabilities=mutual,
            missing_capabilities=missing,
            matched=len(mutual) > 0 or True,  # Any connection is a match
        )

    # ── Agent Discovery (Phase 3) ─────────────────────

    async def discover_agents(
        self, capability: str = "", min_match_score: float = 0.3
    ) -> list[AgentCard]:
        """Discover agents across the ARMP network by capability.

        Searches: room topics → room state events → known peers.
        """
        results: list[AgentCard] = []

        # 1. Known peers (from negotiation)
        for peer in self._peers.values():
            if not capability:
                results.append(peer)
            elif any(capability.lower() in c.get("name", "").lower() for c in peer.capabilities):
                results.append(peer)

        # 2. Public room directory
        resp = await self._client.room_directory()
        if not isinstance(resp, nio.RoomDirectoryError):
            for room in resp.chunk:
                topic = (room.topic or "").lower()
                if capability and capability.lower() not in topic:
                    continue
                # Try joining and fetching room state for agent cards
                try:
                    join_resp = await self._client.join(room.room_id)
                    if not isinstance(join_resp, nio.JoinError):
                        state_resp = await self._client.room_get_state(room.room_id)
                        if not isinstance(state_resp, nio.RoomGetStateError):
                            for event in state_resp.events:
                                content = event.get("content", {}) if isinstance(event, dict) else getattr(event, "content", {})
                                card_data = content.get("agent_card") or content.get("m.agent", {}).get("agent_card")
                                if card_data and card_data.get("did"):
                                    card = AgentCard.from_dict(card_data)
                                    # Avoid duplicates
                                    if card.did not in [r.did for r in results]:
                                        results.append(card)
                        await self._client.room_leave(room.room_id)
                except Exception:
                    pass

        # 3. Capability Registry query (OurDID — async, non-blocking)
        registry_cards = await self._query_registry(capability)
        for card in registry_cards:
            if card.did not in [r.did for r in results]:
                results.append(card)

        logger.info(f"Discovered {len(results)} agents matching '{capability}'")
        return results

    async def discover(self, capability: str = "") -> list[dict]:
        """Legacy discover — returns simplified dicts for backward compat."""
        agents = await self.discover_agents(capability)
        return [
            {"did": a.did, "name": a.name, "matrix_id": a.matrix_id,
             "capabilities": a.capabilities, "description": a.description}
            for a in agents
        ]

    # ── Smart Routing (Phase 3) ────────────────────────

    def _score_capability_match(self, task_spec: dict, agent_card: AgentCard) -> float:
        """Score how well an agent's capabilities match a task (0.0-1.0)."""
        required = task_spec.get("capabilities_required", [])
        preferred = task_spec.get("capabilities_preferred", [])

        if not required and not preferred:
            return 0.5  # No capability filter — neutral

        agent_cap_names = {c["name"].lower() for c in agent_card.capabilities}
        required_lower = {r.lower() for r in required}
        preferred_lower = {p.lower() for p in preferred}

        # Required match: all required capabilities must be present
        if required_lower and not required_lower.issubset(agent_cap_names):
            return 0.0

        # Score: 0.6 for required + 0.4 for preferred
        required_score = len(required_lower) / max(len(required_lower), 1) * 0.6 if required_lower else 0.6
        preferred_score = 0.0
        if preferred_lower:
            preferred_matches = preferred_lower & agent_cap_names
            preferred_score = (len(preferred_matches) / len(preferred_lower)) * 0.4
        else:
            preferred_score = 0.4

        return min(1.0, required_score + preferred_score)

    async def route_task(
        self, task_spec: dict, capability: str = ""
    ) -> tuple[Optional[AgentCard], Optional[str], float]:
        """Smart-route a task to the best-capable agent.

        Returns (best_agent_card, best_agent_user_id, match_score).
        """
        candidates = await self.discover_agents(capability)

        if not candidates:
            logger.warning("No agents discovered for routing")
            return None, None, 0.0

        best_card = None
        best_score = 0.0

        for card in candidates:
            score = self._score_capability_match(task_spec, card)
            logger.debug(f"  {card.name} ({card.did}): score={score:.2f}")
            if score > best_score:
                best_score = score
                best_card = card

        if best_card and best_score > 0.0:
            logger.info(f"Routed to {best_card.name} (score={best_score:.2f})")
            return best_card, best_card.matrix_id, best_score

        return None, None, 0.0

    # ── Capability Registry (Phase 3: OurDID) ──────────

    async def register_card(self, ourdid_api_key: str = "", ourdid_endpoint: str = "") -> bool:
        """Register agent card with the OurDID capability registry.

        If ourdid_api_key is empty, stores locally only.
        """
        if not self._card:
            self._card = AgentCard(
                did=self.did,
                name=self.username,
                matrix_id=self._client.user_id if self._client else f"@{self.username}:{self.homeserver}",
            )

        # Store in Matrix room directory as public agent room
        try:
            room_resp = await self._client.room_create(
                name=f"Agent: {self.username}",
                topic=f"ARMP Agent: {self.did} — {', '.join(c['name'] for c in self._card.capabilities)}",
                is_direct=False,
                visibility="public",
            )
            if not isinstance(room_resp, nio.RoomCreateError):
                # Publish agent card as room state
                await self._client.room_put_state(
                    room_resp.room_id,
                    "m.agent.card",
                    self._card.to_dict(),
                )
                # Publish to room directory
                await self._client.room_put_state(
                    room_resp.room_id,
                    "m.room.join_rules",
                    {"join_rule": "public"},
                )
                self._discovery_room_id = room_resp.room_id
                logger.info(f"Agent card published to room {room_resp.room_id}")
        except Exception as e:
            logger.warning(f"Registry publish failed (non-fatal): {e}")

        # TODO: OurDID API push — POST /api/v1/agents/register
        if ourdid_api_key and ourdid_endpoint:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{ourdid_endpoint}/api/v1/agents/register",
                        json=self._card.to_dict(),
                        headers={"Authorization": f"Bearer {ourdid_api_key}"},
                    )
                    if resp.status_code == 200:
                        logger.info("Registered with OurDID registry")
                    else:
                        logger.warning(f"OurDID registration returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"OurDID registration failed: {e}")

        return True

    async def _query_registry(self, capability: str = "") -> list[AgentCard]:
        """Query the capability registry for matching agents."""
        cards: list[AgentCard] = []

        # 1. Local peers
        for peer in self._peers.values():
            if not capability or any(
                capability.lower() in c.get("name", "").lower()
                for c in peer.capabilities
            ):
                cards.append(peer)

        # 2. OurDID registry query (TODO: when endpoint is ready)
        # try:
        #     import httpx
        #     async with httpx.AsyncClient(timeout=10) as client:
        #         resp = await client.get(
        #             f"{ourdid_endpoint}/api/v1/agents/search?capability={capability}",
        #         )
        #         if resp.status_code == 200:
        #             for agent_data in resp.json().get("agents", []):
        #                 cards.append(AgentCard.from_dict(agent_data))
        # except Exception as e:
        #     logger.debug(f"Registry query skipped: {e}")

        return cards

    async def set_capability(self, name: str, description: str = ""):
        """Declare a capability on this agent."""
        if not self._card:
            self._card = AgentCard(
                did=self.did,
                name=self.username,
                matrix_id=self._client.user_id if self._client else "",
            )
        self._card.capabilities.append({"name": name, "description": description})

    # ── Identity ──────────────────────────────────────

    @property
    def card(self) -> Optional[AgentCard]:
        return self._card

    @property
    def user_id(self) -> str:
        return self._client.user_id if self._client else ""


# ── Demo ────────────────────────────────────────────

async def demo():
    """Phase 3 demo: Capability negotiation + task lifecycle + discovery."""

    HOMESERVER = "http://armp-group.org"
    print(f"🚀 ARMP v0.5.0 — Full Protocol Demo\n   Homeserver: {HOMESERVER}\n")

    # Agent Alpha — text/social agent
    alpha = Agent(
        did="AGNT8A2026070114K7P2M9X4R6",
        homeserver=HOMESERVER,
        username="alpha",
        password="demo-alpha-2026",
        store_path="/home/manofiron/.hermes/projects/armp-protocol/store_alpha",
    )

    # Agent Beta — data analysis agent
    beta = Agent(
        did="AGNT2F2026070116Z3R1M8K5Q9",
        homeserver=HOMESERVER,
        username="beta",
        password="demo-beta-2026",
        store_path="/home/manofiron/.hermes/projects/armp-protocol/store_beta",
    )

    try:
        # Start both agents
        await alpha.start()
        await beta.start()

        # ── Phase 3: Register Capabilities ──
        print("── Registering Capabilities ──\n")
        await alpha.set_capability("text-generation", "Generate articles, stories, and creative text")
        await alpha.set_capability("social-media", "Post and schedule across platforms")
        await alpha.set_capability("translation", "Translate between 50+ languages")
        print(f"  Alpha capabilities: {[c['name'] for c in alpha.card.capabilities]}")

        await beta.set_capability("data-analysis", "Statistical analysis, ML models, reports")
        await beta.set_capability("visualization", "Charts, graphs, dashboards")
        await beta.set_capability("text-generation", "Generate analytical reports and summaries")
        print(f"  Beta capabilities: {[c['name'] for c in beta.card.capabilities]}\n")

        # ── Phase 3: Capability Negotiation ──
        print("── Capability Negotiation ──")
        result = await alpha.negotiate(beta.user_id)
        print(f"  Peer: {result.peer_did}")
        print(f"  Mutual capabilities: {result.mutual_capabilities}")
        print(f"  Peer-unique capabilities: {result.missing_capabilities}")
        print(f"  Negotiation matched: {result.matched}\n")

        # ── Phase 3: Task Lifecycle ──
        print("── Task Lifecycle ──")
        task = await alpha.create_task(
            assignee_did=beta.did,
            spec={
                "description": "Churn analysis for Q3 customer dataset",
                "capabilities_required": ["data-analysis"],
                "capabilities_preferred": ["visualization"],
            },
            assignee_user_id=beta.user_id,
        )
        print(f"  Task created: {task.task_id} [{task.status}]")

        room_id = None
        resp = await beta._client.joined_rooms()
        if not isinstance(resp, nio.JoinedRoomsError):
            for rid in resp.rooms:
                room_id = rid
                break

        if room_id:
            await beta.assign_task(task, alpha.user_id)
            print(f"  Task assigned: [{task.status}]")

            await beta.start_task(task, room_id)
            print(f"  Task started: [{task.status}]")

            await beta.report_progress(task, room_id, 0.35, "Loading customer data...")
            await asyncio.sleep(0.5)
            await beta.report_progress(task, room_id, 0.70, "Running logistic regression...")
            await asyncio.sleep(0.5)
            await beta.report_progress(task, room_id, 0.95, "Generating churn report...")
            await asyncio.sleep(0.5)

            await beta.complete_task(task, room_id, {
                "churn_rate": "23.4%",
                "top_factors": ["contract_type", "tenure_months", "monthly_charges"],
                "report_url": "https://files.armp-group.org/reports/churn-q3.pdf",
            })
            print(f"  Task completed: [{task.status}] progress={task.progress}")
            print(f"  Task history: {len(task.history)} state transitions")

        # ── Phase 3: Discovery ──
        print("\n── Agent Discovery ──")
        data_agents = await alpha.discover_agents("data-analysis")
        print(f"  Found {len(data_agents)} data-analysis agents: {[(a.name, a.did) for a in data_agents]}")

        # ── Phase 3: Smart Routing ──
        print("\n── Smart Routing ──")
        best_card, best_id, score = await alpha.route_task(
            {"capabilities_required": ["data-analysis"], "capabilities_preferred": ["visualization"]}
        )
        if best_card:
            print(f"  Best agent: {best_card.name} ({best_card.did}) — score: {score:.2f}")
        else:
            print("  No matching agent found")

        print("\n── Phase 3 Demo Complete ──\n")

    finally:
        await alpha.stop()
        await beta.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(demo())
