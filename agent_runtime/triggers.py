"""Trigger engine — keyword, cron, and Matrix event triggers with conditional chaining.

Phase 2: Adds cron scheduler, conditional pipeline chaining,
and integration with Watchdog for health checks.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.triggers")


class TriggerType(str, Enum):
    KEYWORD = "keyword"              # Message body matches keyword regex
    CRON = "cron"                    # Time-based trigger
    MATRIX_EVENT = "matrix_event"    # Specific Matrix event type
    CONDITION = "condition"          # Custom condition function
    PIPELINE = "pipeline"            # Chained: trigger A → action → trigger B


@dataclass
class Trigger:
    """A trigger that fires when its condition is met."""

    name: str
    trigger_type: TriggerType
    pattern: Optional[str] = None          # Regex for KEYWORD, cron expr for CRON
    handler: Optional[Callable] = None     # async fn(dict) -> None
    enabled: bool = True
    metadata: dict = field(default_factory=dict)
    # Phase 2: cron-specific
    cron_interval: int = 0                 # Seconds between firings (0 = pattern-based)
    last_fired: float = 0.0                # Unix timestamp of last fire
    max_fires: int = 0                     # Max total fires (0 = unlimited)
    fire_count: int = 0                    # Times fired so far


class CronScheduler:
    """Cron-style scheduler for time-based triggers.

    Runs a background loop that evaluates cron triggers on their
    configured intervals. Integrates with runtime's asyncio event loop.
    """

    def __init__(self, trigger_engine: "TriggerEngine"):
        self.engine = trigger_engine
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._tick_interval = 1.0  # Check every second

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Cron scheduler started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cron scheduler stopped")

    async def _loop(self):
        """Main scheduling loop."""
        while self._running:
            now = time.time()
            for trigger in self.engine.list_all():
                if not trigger.enabled:
                    continue
                if trigger.trigger_type != TriggerType.CRON:
                    continue
                if trigger.max_fires > 0 and trigger.fire_count >= trigger.max_fires:
                    continue

                interval = trigger.cron_interval
                if interval <= 0:
                    continue

                if now - trigger.last_fired >= interval:
                    trigger.last_fired = now
                    trigger.fire_count += 1
                    try:
                        if trigger.handler:
                            await trigger.handler({})
                        logger.debug(f"Cron trigger fired: {trigger.name}")
                    except Exception as e:
                        logger.error(f"Cron trigger '{trigger.name}' failed: {e}")

            await asyncio.sleep(self._tick_interval)


class ConditionalPipeline:
    """Chained trigger pipeline: if-A-then-B-then-C.

    Example:
        "If message contains 'data request' → query APITrad → send result"
    """

    def __init__(self, name: str):
        self.name = name
        self._steps: list[PipelineStep] = []

    def add_step(self, step: "PipelineStep"):
        self._steps.append(step)
        return self

    async def execute(self, context: dict) -> dict:
        """Execute pipeline steps sequentially. Stops on first failure."""
        for step in self._steps:
            try:
                result = await step.execute(context)
                if not result.get("success", False):
                    logger.warning(f"Pipeline '{self.name}' step '{step.name}' failed")
                    return {"success": False, "failed_at": step.name, "context": context}
                context = result.get("context", context)
            except Exception as e:
                logger.error(f"Pipeline '{self.name}' step '{step.name}' error: {e}")
                return {"success": False, "failed_at": step.name, "error": str(e)}
        return {"success": True, "context": context}


@dataclass
class PipelineStep:
    """A single step in a conditional pipeline."""
    name: str
    condition: Callable[[dict], bool]      # Should this step run?
    action: Callable[[dict], Awaitable]     # What to do
    on_failure: str = "stop"                # "stop" | "skip" | "continue"

    async def execute(self, context: dict) -> dict:
        try:
            if self.condition(context):
                result = await self.action(context)
                return {"success": True, "context": {**context, **result}}
            else:
                return {"success": True, "context": context}
        except Exception as e:
            if self.on_failure == "stop":
                return {"success": False, "error": str(e)}
            elif self.on_failure == "skip":
                logger.warning(f"Pipeline step '{self.name}' skipped: {e}")
                return {"success": True, "context": context}
            else:  # continue
                logger.error(f"Pipeline step '{self.name}' error (continuing): {e}")
                return {"success": True, "context": context}


class TriggerEngine:
    """Manages and evaluates triggers. Phase 2: adds cron + pipelines."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._triggers: list[Trigger] = []
        self._pipelines: dict[str, ConditionalPipeline] = {}
        self._running = False
        self._scheduler = CronScheduler(self)

        # Built-in triggers
        self.add(Trigger(
            name="greeting",
            trigger_type=TriggerType.KEYWORD,
            pattern=r"(?i)\b(hello|hi|hey|greetings)\b",
        ))
        self.add(Trigger(
            name="urgent",
            trigger_type=TriggerType.KEYWORD,
            pattern=r"(?i)\b(urgent|emergency|asap|critical)\b",
        ))
        self.add(Trigger(
            name="payment_request",
            trigger_type=TriggerType.KEYWORD,
            pattern=r"(?i)\b(pay|payment|invoice|bill)\b",
        ))
        # Phase 2: data request trigger
        self.add(Trigger(
            name="data_request",
            trigger_type=TriggerType.KEYWORD,
            pattern=r"(?i)\b(data|query|lookup|search|find)\b.*\b(price|rate|cost|status)\b",
        ))

    async def start(self):
        self._running = True
        await self._scheduler.start()
        logger.info(
            f"Trigger engine started "
            f"({len(self._triggers)} triggers, {len(self._pipelines)} pipelines)"
        )

    async def stop(self):
        self._running = False
        await self._scheduler.stop()

    def add(self, trigger: Trigger):
        self._triggers.append(trigger)
        logger.debug(f"Trigger added: {trigger.name} ({trigger.trigger_type})")

    def remove(self, name: str):
        self._triggers = [t for t in self._triggers if t.name != name]

    def list(self) -> list:
        return [
            {"name": t.name, "type": t.trigger_type, "enabled": t.enabled}
            for t in self._triggers
        ]

    def list_all(self) -> list[Trigger]:
        return self._triggers

    # ── Pipelines ───────────────────────────────────────

    def add_pipeline(self, pipeline: ConditionalPipeline):
        self._pipelines[pipeline.name] = pipeline
        logger.info(f"Pipeline added: {pipeline.name} ({len(pipeline._steps)} steps)")

    def get_pipeline(self, name: str) -> Optional[ConditionalPipeline]:
        return self._pipelines.get(name)

    async def run_pipeline(self, name: str, context: dict) -> dict:
        """Execute a named pipeline."""
        pipeline = self._pipelines.get(name)
        if not pipeline:
            return {"success": False, "error": f"Pipeline not found: {name}"}
        logger.info(f"Running pipeline: {name}")
        return await pipeline.execute(context)

    # ── Evaluation ──────────────────────────────────────

    async def evaluate(self, message_body: str = "", event_type: str = "") -> list:
        """Evaluate all triggers against a message or event. Returns fired triggers."""
        fired = []

        for trigger in self._triggers:
            if not trigger.enabled:
                continue

            match = False

            if trigger.trigger_type == TriggerType.KEYWORD and message_body:
                if trigger.pattern and re.search(trigger.pattern, message_body):
                    match = True

            elif trigger.trigger_type == TriggerType.MATRIX_EVENT and event_type:
                if trigger.pattern == event_type:
                    match = True

            elif trigger.trigger_type == TriggerType.CONDITION:
                if trigger.handler:
                    try:
                        result = await trigger.handler({"message": message_body})
                        match = bool(result)
                    except Exception as e:
                        logger.error(f"Condition trigger '{trigger.name}' failed: {e}")

            if match:
                fired.append(trigger)
                logger.debug(f"Trigger fired: {trigger.name}")

        # Phase 2: auto-run pipelines if their condition triggers fire
        for trigger in fired:
            pipeline_name = trigger.metadata.get("pipeline")
            if pipeline_name and pipeline_name in self._pipelines:
                result = await self.run_pipeline(pipeline_name, {"message": message_body})
                logger.info(f"Pipeline '{pipeline_name}' result: {result.get('success')}")

        return fired
