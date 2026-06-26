"""
Task Manager — L3 ARMP task creation, delegation, and lifecycle management.

Phase 2: Agents at L3+ can create ARMP Tasks and delegate work to other agents.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.tasks")


class TaskStatus(str, Enum):
    """ARMP Task lifecycle states."""
    PENDING = "pending"          # Created, not yet assigned
    ASSIGNED = "assigned"        # Assigned to an agent
    IN_PROGRESS = "in_progress"  # Agent is working on it
    COMPLETED = "completed"      # Done successfully
    FAILED = "failed"            # Failed or timed out
    CANCELLED = "cancelled"      # Cancelled by requester
    EXPIRED = "expired"          # Deadline passed


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Task:
    """A single ARMP Task that can be delegated to other agents."""

    task_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    requester_did: str = ""
    assignee_did: str = ""
    capability: str = ""         # Required capability (e.g. "image_generation")
    parameters: dict = field(default_factory=dict)
    result: Optional[dict] = None
    deadline: Optional[str] = None  # ISO 8601
    tags: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "requester_did": self.requester_did,
            "assignee_did": self.assignee_did,
            "capability": self.capability,
            "parameters": self.parameters,
            "result": self.result,
            "deadline": self.deadline,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class TaskManager:
    """Creates, delegates, and tracks ARMP Tasks."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._tasks: dict[str, Task] = {}
        self._task_history: dict[str, list[Task]] = {}  # agent_did → completed tasks

    # ── Task Lifecycle ─────────────────────────────────

    async def create(
        self,
        title: str,
        description: str = "",
        capability: str = "",
        parameters: dict = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        deadline: str = "",
    ) -> Task:
        """Create a new task. Requires L3 permission."""
        if not self.runtime.permissions.can_create_tasks():
            raise PermissionError(
                f"Task creation requires L3+. Current: L{self.runtime.permissions.level}"
            )

        task = Task(
            task_id=f"TASK-{uuid.uuid4().hex[:8].upper()}",
            title=title,
            description=description,
            requester_did=self.runtime.did,
            capability=capability,
            parameters=parameters or {},
            priority=priority,
            deadline=deadline or None,
        )

        self._tasks[task.task_id] = task

        self.runtime.storage.audit("task_created", task.to_dict())
        logger.info(
            f"Task created: {task.task_id} — {title} "
            f"(capability={capability}, priority={priority.value})"
        )
        return task

    async def delegate(self, task_id: str, assignee_did: str) -> bool:
        """Delegate a task to another agent via ARMP."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if task.status != TaskStatus.PENDING:
            raise ValueError(f"Task {task_id} is not PENDING (current: {task.status.value})")

        if not self.runtime._started or not self.runtime._armp:
            raise RuntimeError("Runtime not started. Cannot send delegation message.")

        # Send ARMP message to assignee
        delegation_msg = {
            "type": "armp.task.delegation",
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "capability": task.capability,
            "parameters": task.parameters,
            "priority": task.priority.value,
            "requester_did": task.requester_did,
            "deadline": task.deadline,
        }

        try:
            # Send via Matrix DM to the assignee
            assignee_room = self._resolve_agent_room(assignee_did)
            if assignee_room:
                await self.runtime._armp.send_message(
                    assignee_room,
                    f"📋 Task Delegation\n\n"
                    f"Task: {task.title}\n"
                    f"Description: {task.description}\n"
                    f"Capability: {task.capability}\n"
                    f"Priority: {task.priority.value}\n"
                    f"Parameters: {task.parameters}\n",
                )

            task.status = TaskStatus.ASSIGNED
            task.assignee_did = assignee_did
            task.updated_at = _now_iso()

            self.runtime.storage.audit("task_delegated", {
                "task_id": task.task_id,
                "to": assignee_did,
            })

            await self.runtime.notifier.notify(
                f"📤 Task {task.task_id} delegated to {assignee_did}",
                severity="info",
            )
            return True
        except Exception as e:
            logger.error(f"Delegation failed: {e}")
            return False

    async def update_status(self, task_id: str, status: TaskStatus, result: dict = None) -> bool:
        """Update task status (completion, failure, cancellation)."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        old_status = task.status
        task.status = status
        task.updated_at = _now_iso()

        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = _now_iso()
            task.result = result

            # Move to history
            agent_key = task.assignee_did or task.requester_did
            if agent_key not in self._task_history:
                self._task_history[agent_key] = []
            self._task_history[agent_key].append(task)

        self.runtime.storage.audit("task_status_change", {
            "task_id": task.task_id,
            "from": old_status.value,
            "to": status.value,
        })

        logger.info(f"Task {task_id}: {old_status.value} → {status.value}")
        return True

    # ── Task Queries ────────────────────────────────────

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_by_status(self, status: TaskStatus = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def list_by_capability(self, capability: str) -> list[Task]:
        return [
            t for t in self._tasks.values()
            if t.capability == capability and t.status == TaskStatus.PENDING
        ]

    def history(self, agent_did: str = "", limit: int = 20) -> list[dict]:
        """Get completed task history for an agent."""
        if agent_did and agent_did in self._task_history:
            tasks = self._task_history[agent_did][-limit:]
        else:
            tasks = []
            for agent_tasks in self._task_history.values():
                tasks.extend(agent_tasks)
            tasks = tasks[-limit:]
        return [t.to_dict() for t in tasks]

    def stats(self) -> dict:
        """Task statistics."""
        all_tasks = list(self._tasks.values())
        return {
            "total": len(all_tasks),
            "pending": sum(1 for t in all_tasks if t.status == TaskStatus.PENDING),
            "assigned": sum(1 for t in all_tasks if t.status == TaskStatus.ASSIGNED),
            "in_progress": sum(1 for t in all_tasks if t.status == TaskStatus.IN_PROGRESS),
            "completed": sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in all_tasks if t.status == TaskStatus.FAILED),
        }

    # ── Internal ────────────────────────────────────────

    def _resolve_agent_room(self, agent_did: str) -> str:
        """Resolve an agent DID to a Matrix room ID.
        
        In production, this queries the ARMP directory or maintains
        a DID → room_id cache. For now, uses a convention.
        """
        # Convention: DM rooms are addressed by Matrix user ID
        # DID format: AGNT8A... → resolve via OurDID or directory
        # Stub: return placeholder (real implementation in Phase 3)
        return ""  # TODO: DID → Matrix room resolution


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
