"""Tests for Agent Runtime Phase 2."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_runtime.permissions import PermissionManager, PermissionLevel
from agent_runtime.decision import DecisionEngine, Intent, Action, IntentResult
from agent_runtime.triggers import (
    TriggerEngine, Trigger, TriggerType,
    ConditionalPipeline, PipelineStep, CronScheduler,
)
from agent_runtime.plugins import PluginManager, plugin
from agent_runtime.storage import Storage
from agent_runtime.config import Config
from agent_runtime.task_manager import TaskManager, Task, TaskStatus, TaskPriority
from agent_runtime.watchdog import Watchdog, CheckResult, CheckStatus
from agent_runtime.collaboration import (
    CollaborationManager, CollaborationSession, NegotiationPhase,
)


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

    def test_level_3_can_create_tasks(self):
        pm = PermissionManager(level=3)
        assert pm.can_create_tasks()
        assert not pm.can_pay()

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
        actions = [{"level": 2} for _ in range(11)]
        assert pm.check_anomaly(actions)


# ── Decision Engine Tests ────────────────────────────

class TestDecision:
    def test_greeting_classification(self):
        engine = DecisionEngine(None)
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

    def test_data_query_classification(self):
        engine = DecisionEngine(None)
        class MockMsg:
            body = "Check the current rate"
        result = engine.classify_sync(MockMsg())
        assert result.intent == Intent.DATA_QUERY

    def test_delegation_classification(self):
        engine = DecisionEngine(None)
        class MockMsg:
            body = "Assign this to the image agent"
        result = engine.classify_sync(MockMsg())
        assert result.intent == Intent.DELEGATION

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
        assert action == Action.NOTIFY

    def test_action_routing_l1(self):
        engine = DecisionEngine(None)
        intent = IntentResult(intent=Intent.GREETING, confidence=0.9)
        action = engine.decide(intent, 1)
        assert action == Action.REPLY

    def test_delegation_l2_blocked(self):
        engine = DecisionEngine(None)
        intent = IntentResult(intent=Intent.DELEGATION, confidence=0.9)
        action = engine.decide(intent, 2)
        assert action == Action.ESCALATE  # L2 cannot delegate

    def test_delegation_l3_allowed(self):
        engine = DecisionEngine(None)
        intent = IntentResult(intent=Intent.DELEGATION, confidence=0.9)
        action = engine.decide(intent, 3)
        assert action == Action.DELEGATE


# Patch DecisionEngine with sync classify
def classify_sync(self, message):
    import asyncio
    return asyncio.run(self.classify(message))

DecisionEngine.classify_sync = classify_sync


# ── Trigger Tests ─────────────────────────────────────

class TestTriggers:
    def test_keyword_trigger(self):
        import asyncio
        rt = type('RT', (), {})()
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

    def test_data_request_trigger(self):
        import asyncio
        rt = type('RT', (), {})()
        engine = TriggerEngine(rt)
        asyncio.run(engine.start())
        fired = asyncio.run(engine.evaluate(message_body="Can you query the price for me?"))
        assert any(t.name == "data_request" for t in fired)

    def test_no_match(self):
        import asyncio
        rt = type('RT', (), {})()
        engine = TriggerEngine(rt)
        asyncio.run(engine.start())
        fired = asyncio.run(engine.evaluate(message_body="Just a normal message"))
        assert len(fired) == 0

    def test_cron_trigger_added(self):
        rt = type('RT', (), {})()
        engine = TriggerEngine(rt)
        engine.add(Trigger(
            name="hourly_check",
            trigger_type=TriggerType.CRON,
            cron_interval=3600,
        ))
        triggers = engine.list()
        assert any(t["name"] == "hourly_check" for t in triggers)


# ── Pipeline Tests ────────────────────────────────────

class TestPipelines:
    def test_pipeline_execution(self):
        import asyncio

        async def step_action(ctx):
            return {"step1_done": True}

        pipeline = ConditionalPipeline("test_pipeline")
        pipeline.add_step(PipelineStep(
            name="step1",
            condition=lambda ctx: True,
            action=step_action,
        ))

        result = asyncio.run(pipeline.execute({"initial": True}))
        assert result["success"]
        assert result["context"]["step1_done"]
        assert result["context"]["initial"]

    def test_pipeline_condition_false(self):
        import asyncio

        pipeline = ConditionalPipeline("skip_test")
        pipeline.add_step(PipelineStep(
            name="never_runs",
            condition=lambda ctx: False,
            action=lambda ctx: asyncio.sleep(0) or {"bad": True},
        ))

        result = asyncio.run(pipeline.execute({}))
        assert result["success"]
        assert "bad" not in result["context"]


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

    def test_task_persistence(self):
        import tempfile, os
        db_path = os.path.join(tempfile.mkdtemp(), "test3.db")
        s = Storage(db_path)

        task_data = {
            "task_id": "TASK-001",
            "title": "Test Task",
            "description": "A test",
            "status": "pending",
            "priority": "medium",
            "requester_did": "AGNT-TEST",
            "capability": "search",
            "parameters": {"q": "test"},
            "tags": ["test"],
        }
        s.save_task(task_data)
        tasks = s.get_tasks("pending")
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "TASK-001"

    def test_audit_log(self):
        import tempfile, os
        db_path = os.path.join(tempfile.mkdtemp(), "test4.db")
        s = Storage(db_path)
        s.audit("test", {"key": "val"})
        logs = s.get_audit_log()
        assert len(logs) == 1
        assert logs[0]["action"] == "test"


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


# ── Task Manager Tests ────────────────────────────────

class TestTaskManager:
    def test_create_task_requires_l3(self):
        rt = type('RT', (), {})()
        rt.permissions = PermissionManager(level=0)
        tm = TaskManager(rt)
        try:
            import asyncio
            asyncio.run(tm.create(title="Test"))
            assert False, "Should have raised PermissionError"
        except PermissionError:
            pass

    def test_create_task_l3_ok(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.permissions = PermissionManager(level=3)
        rt.storage = Storage()
        rt.notifier = type('N', (), {
            'notify': lambda self, msg, severity: None
        })()
        rt.did = "AGNT-TEST"
        tm = TaskManager(rt)
        task = asyncio.run(tm.create(
            title="Test Task",
            description="Testing",
            capability="search",
            priority=TaskPriority.HIGH,
        ))
        assert task.title == "Test Task"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.HIGH
        assert task.capability == "search"

    def test_task_stats(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.permissions = PermissionManager(level=3)
        rt.storage = Storage()
        rt.notifier = type('N', (), {
            'notify': lambda self, msg, severity: None
        })()
        rt.did = "AGNT-TEST"
        tm = TaskManager(rt)
        asyncio.run(tm.create(title="Task 1"))
        asyncio.run(tm.create(title="Task 2"))
        stats = tm.stats()
        assert stats["total"] == 2
        assert stats["pending"] == 2


# ── Watchdog Tests ─────────────────────────────────────

class TestWatchdog:
    def test_register_check(self):
        rt = type('RT', (), {})()
        wd = Watchdog(rt)
        wd.add_check("ssl:armp-group.org", interval_hours=24)
        wd.add_check("http:httpbin.org", interval_hours=12)
        assert len(wd._checks) == 2

    def test_summary_empty(self):
        rt = type('RT', (), {})()
        wd = Watchdog(rt)
        summary = wd.summary()
        assert summary["total_checks"] == 0

    def test_check_result(self):
        result = CheckResult(
            name="test",
            status=CheckStatus.OK,
            message="All good",
        )
        assert result.status == CheckStatus.OK
        assert result.name == "test"


# ── Collaboration Tests ───────────────────────────────

class TestCollaboration:
    def test_handle_query_message(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.storage = Storage()
        rt.permissions = PermissionManager(level=3)
        rt.did = "AGNT-TEST"
        rt._started = False  # No ARMP needed for message parsing
        cm = CollaborationManager(rt)

        msg = '{"type": "CAPABILITY_QUERY", "session_id": "S-001", "requester_did": "AGNT-A", "capability": "image_gen", "parameters": {}}'
        result = asyncio.run(
            cm.handle_collaboration_message(msg, "AGNT-A")
        )
        assert result is not None
        assert result["action"] == "query_received"
        assert result["capability"] == "image_gen"

    def test_handle_accept_message(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.storage = Storage()
        rt.permissions = PermissionManager(level=3)
        rt.did = "AGNT-TEST"
        rt._started = False
        cm = CollaborationManager(rt)

        msg = '{"type": "CAPABILITY_ACCEPT", "session_id": "S-002", "provider_did": "AGNT-B"}'
        result = asyncio.run(
            cm.handle_collaboration_message(msg, "AGNT-B")
        )
        assert result is not None
        assert result["action"] == "proposal_received"

    def test_collaboration_stats(self):
        rt = type('RT', (), {})()
        rt.storage = Storage()
        rt.permissions = PermissionManager(level=3)
        rt.did = "AGNT-TEST"
        rt._started = False
        cm = CollaborationManager(rt)
        stats = cm.stats()
        assert stats["total_sessions"] == 0
