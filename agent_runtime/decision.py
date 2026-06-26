"""Decision engine — intent classification and action routing."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from amp_sdk import Message
    from . import Runtime

logger = logging.getLogger("agent-runtime.decision")


class Intent(str, Enum):
    """Classified intent of an incoming message."""
    GREETING = "greeting"       # Hello, hi, hey
    QUESTION = "question"       # What is..., how do I...
    REQUEST = "request"         # Can you..., please...
    COMMAND = "command"         # Do this, run that
    SPAM = "spam"              # Likely spam/irrelevant
    UNKNOWN = "unknown"         # Could not classify


class Action(str, Enum):
    """Action to take based on intent and permission level."""
    IGNORE = "ignore"
    NOTIFY = "notify"           # Tell the human
    REPLY = "reply"            # Auto-reply
    API_CALL = "api_call"      # Call a whitelisted API
    ESCALATE = "escalate"      # Needs higher permission


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: Intent
    confidence: float = 0.0
    api_name: Optional[str] = None
    params: dict = field(default_factory=dict)
    explanation: str = ""


class DecisionEngine:
    """Classifies messages and decides what action to take."""
    
    # Local keyword patterns — no LLM needed for these
    PATTERNS = {
        Intent.GREETING: [
            r"\b(hello|hi|hey|greetings|good morning|good evening)\b",
        ],
        Intent.QUESTION: [
            r"\b(what|how|why|when|where|who|which)\b",
            r"\?$",
        ],
        Intent.REQUEST: [
            r"\b(can you|could you|please|would you|help)\b",
        ],
        Intent.COMMAND: [
            r"\b(do|run|execute|start|stop|create|delete)\b",
        ],
    }
    
    # API name extraction patterns
    API_PATTERNS = {
        "weather": [r"\b(weather|temperature|forecast)\b"],
        "search": [r"\b(search|find|look up|google)\b"],
        "price": [r"\b(price|cost|how much|rate)\b"],
    }
    
    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._use_llm = False  # Phase 1: keyword-only. Phase 2: add LLM
    
    async def classify(self, message: "Message") -> IntentResult:
        """Classify a message's intent."""
        body = message.body.lower() if hasattr(message, 'body') else ""
        
        if not body:
            return IntentResult(intent=Intent.UNKNOWN, confidence=0.0)
        
        # Spam detection
        if len(body) > 5000 or body.count("http") > 5:
            return IntentResult(intent=Intent.SPAM, confidence=0.9,
                              explanation="Message too long or too many links")
        
        # Pattern matching
        import re
        best_intent = Intent.UNKNOWN
        best_confidence = 0.0
        
        for intent, patterns in self.PATTERNS.items():
            matches = sum(1 for p in patterns if re.search(p, body))
            if matches > 0:
                confidence = matches / len(patterns)
                if confidence > best_confidence:
                    best_intent = intent
                    best_confidence = confidence
        
        # API name extraction
        api_name = None
        for name, patterns in self.API_PATTERNS.items():
            if any(re.search(p, body) for p in patterns):
                api_name = name
                break
        
        logger.debug(f"Intent: {best_intent} (confidence={best_confidence:.2f})")
        return IntentResult(
            intent=best_intent,
            confidence=best_confidence,
            api_name=api_name,
        )
    
    def decide(self, intent_result: IntentResult, permission_level: int) -> Action:
        """Decide what action to take based on intent and permissions."""
        
        if intent_result.intent == Intent.SPAM:
            return Action.IGNORE
        
        if intent_result.intent == Intent.UNKNOWN:
            if permission_level >= 1:
                return Action.NOTIFY
            return Action.IGNORE
        
        if intent_result.intent in (Intent.GREETING, Intent.QUESTION):
            if permission_level >= 1:
                return Action.REPLY
            return Action.NOTIFY
        
        if intent_result.intent == Intent.REQUEST:
            if intent_result.api_name and permission_level >= 2:
                return Action.API_CALL
            return Action.NOTIFY
        
        if intent_result.intent == Intent.COMMAND:
            if permission_level >= 3:
                return Action.API_CALL
            return Action.ESCALATE
        
        return Action.NOTIFY
