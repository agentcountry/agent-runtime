"""Trigger engine — keyword, cron, and Matrix event triggers."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.triggers")


class TriggerType(str, Enum):
    KEYWORD = "keyword"          # Message body matches keyword regex
    CRON = "cron"                # Time-based trigger
    MATRIX_EVENT = "matrix_event"  # Specific Matrix event type
    CONDITION = "condition"      # Custom condition function


@dataclass
class Trigger:
    """A trigger that fires when its condition is met."""
    name: str
    trigger_type: TriggerType
    pattern: Optional[str] = None       # Regex for KEYWORD, cron expr for CRON
    handler: Optional[Callable] = None  # async fn(dict) -> None
    enabled: bool = True
    metadata: dict = field(default_factory=dict)


class TriggerEngine:
    """Manages and evaluates triggers."""
    
    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._triggers: list[Trigger] = []
        self._running = False
        
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
    
    async def start(self):
        self._running = True
        logger.info(f"Trigger engine started ({len(self._triggers)} triggers)")
    
    async def stop(self):
        self._running = False
    
    def add(self, trigger: Trigger):
        self._triggers.append(trigger)
        logger.debug(f"Trigger added: {trigger.name} ({trigger.trigger_type})")
    
    def remove(self, name: str):
        self._triggers = [t for t in self._triggers if t.name != name]
    
    def list(self) -> list:
        return [{"name": t.name, "type": t.trigger_type, "enabled": t.enabled}
                for t in self._triggers]
    
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
        
        return fired
