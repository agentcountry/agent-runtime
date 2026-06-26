"""Tests for Agent Runtime Phase 1."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_runtime.permissions import PermissionManager, PermissionLevel
from agent_runtime.decision import DecisionEngine, Intent, Action, IntentResult
from agent_runtime.triggers import TriggerEngine, Trigger, TriggerType
from agent_runtime.plugins import PluginManager, plugin
from agent_runtime.storage import Storage
from agent_runtime.config import Config


# ── Permissions Tests ─────────────────────────────────

class TestPermissions:
    def test_default_level(self):
        pm = PermissionManager()
        assert pm.level == 0
        assert not pm.can_handle_messages()
        assert not pm.can_call_api()

    def test_level_1(self):
        pm = PermissionManager(level=1)
        assert pm.can_handle_messages()
        assert not pm.can_call_api()

    def test_level_2(self):
        pm = PermissionManager(level=2)
        assert pm.can_handle_messages()
        assert pm.can_call_api()
        assert not pm.can_create_tasks()

    def test_level_4(self):
        pm = PermissionManager(level=4)
        assert pm.can_pay()

    def test_whitelist(self):
        pm = PermissionManager(level=2)
        pm.add_whitelist("weather")
        assert pm.is_api_whitelisted("weather")
        assert not pm.is_api_whitelisted("payments")

    def test_anomaly_detection(self):
        pm = PermissionManager(level=2)
        # 11 high-level actions = anomaly
        actions = [{"level": 2} for _ in range(11)]
        assert pm.check_anomaly(actions)


# ── Decision Engine Tests ────────────────────────────

class TestDecision:
    def test_greeting_classification(self):
        engine = DecisionEngine(None)
        # Mock message
        class MockMsg:
            body = "Hello, are you there?"
        result = engine.classify_sync(MockMsg())
        assert result.intent == Intent.GREETING

    def test_question_classification(self):
        engine = DecisionEngine(None)
        class MockMsg:
            body = "What is the weather today?"
        result = engine.classify_sync(MockMsg())
        assert result.intent == Intent.QUESTION

    def test_spam_detection(self):
        engine = DecisionEngine(None)
        class MockMsg:
            body = "http://" * 10
        result = engine.classify_sync(MockMsg())
        assert result.intent == Intent.SPAM

    def test_action_routing_l0(self):
        engine = DecisionEngine(None)
        intent = IntentResult(intent=Intent.GREETING, confidence=0.9)
        action = engine.decide(intent, 0)
        assert action == Action.NOTIFY  # L0 can only notify

    def test_action_routing_l1(self):
        engine = DecisionEngine(None)
        intent = IntentResult(intent=Intent.GREETING, confidence=0.9)
        action = engine.decide(intent, 1)
        assert action == Action.REPLY  # L1 can reply


# Patch DecisionEngine with sync classify
def classify_sync(self, message):
    import asyncio
    return asyncio.run(self.classify(message))

DecisionEngine.classify_sync = classify_sync


# ── Trigger Tests ─────────────────────────────────────

class TestTriggers:
    def test_keyword_trigger(self):
        import asyncio
        rt = type('RT', (), {})()  # Dummy runtime
        engine = TriggerEngine(rt)
        asyncio.run(engine.start())

        fired = asyncio.run(engine.evaluate(message_body="Hello there!"))
        assert any(t.name == "greeting" for t in fired)

    def test_urgent_trigger(self):
        import asyncio
        rt = type('RT', (), {})()
        engine = TriggerEngine(rt)
        asyncio.run(engine.start())

        fired = asyncio.run(engine.evaluate(message_body="This is URGENT!"))
        assert any(t.name == "urgent" for t in fired)

    def test_no_match(self):
        import asyncio
        rt = type('RT', (), {})()
        engine = TriggerEngine(rt)
        asyncio.run(engine.start())

        fired = asyncio.run(engine.evaluate(message_body="Just a normal message"))
        assert len(fired) == 0


# ── Plugin Tests ──────────────────────────────────────

class TestPlugins:
    def test_register_and_list(self):
        pm = PluginManager()
        pm.register("test_plugin", object())
        assert "test_plugin" in pm.list()

    def test_unregister(self):
        pm = PluginManager()
        pm.register("temp", object())
        pm.unregister("temp")
        assert "temp" not in pm.list()

    def test_plugin_decorator(self):
        @plugin(name="hello", api_name="greet")
        async def greet(params):
            return f"Hello, {params.get('name', 'world')}!"

        assert greet.name == "hello"
        assert greet.api_name == "greet"


# ── Storage Tests ─────────────────────────────────────

class TestStorage:
    def test_init_and_log(self):
        import tempfile, os
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        s = Storage(db_path)

        s.log_event("test_event", {"key": "value"})
        events = s.get_events("test_event")
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"

        s.audit("test_action", {"detail": "test"})
        s.audit("test_action2", {"detail": "test2"})

    def test_config_persistence(self):
        import tempfile, os
        db_path = os.path.join(tempfile.mkdtemp(), "test2.db")
        s = Storage(db_path)

        s.set_config("greeting", "hello")
        assert s.get_config("greeting") == "hello"
        assert s.get_config("nonexistent", "default") == "default"


# ── Config Tests ──────────────────────────────────────

class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.default_permission_level == 0
        assert c.get("llm_enabled") is False
        assert "db_path" in c._data

    def test_set_and_get(self):
        c = Config()
        c.set("custom_key", 42)
        assert c.get("custom_key") == 42
