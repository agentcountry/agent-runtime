"""Tests for Agent Runtime Phase 3."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_runtime.marketplace import PluginMarketplace, PluginInfo
from agent_runtime.federation import FederationManager, AgentNode, FederationConfig
from agent_runtime.payments import PaymentManager, PaymentRequest, PaymentStatus, Currency
from agent_runtime.enterprise import (
    EnterpriseManager, RBACManager, AuditExporter, SSOManager,
    Role, User, ROLE_PERMISSIONS,
)


# ── Helpers ────────────────────────────────────────────

async def _noop_notify(self, msg, severity=None):
    pass

def _noop_audit(self, *a, **kw):
    pass

def _make_stub_runtime(l4=False):
    """Create a minimal stub runtime for PaymentManager tests."""
    class StubPermissions:
        level = 4 if l4 else 0
        def can_pay(self):
            return l4

    class StubStorage:
        def audit(self, *a, **kw):
            pass

    class StubNotifier:
        async def notify(self, msg, severity=None):
            pass

    rt = type('RT', (), {})()
    rt.permissions = StubPermissions()
    rt.storage = StubStorage()
    rt.notifier = StubNotifier()
    return rt


# ── Marketplace Tests ─────────────────────────────────

class TestMarketplace:
    def test_register_plugin(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {'audit': lambda self, *a, **kw: None})()
        mp = PluginMarketplace(rt)

        # Reset registry to avoid cross-test pollution
        mp._registry.clear()

        info = PluginInfo(
            name="hello-world",
            version="1.0.0",
            description="A test plugin",
            author="test",
            capabilities=["greet"],
            tags=["demo"],
        )
        result = asyncio.run(mp.register(info))
        assert result is True
        assert "hello-world" in mp._registry

    def test_search_by_query(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {'audit': lambda self, *a, **kw: None})()
        mp = PluginMarketplace(rt)

        mp._registry["weather"] = PluginInfo(
            name="weather", version="1.0", description="Weather API",
            author="test", tags=["api", "weather"],
        )
        mp._registry["search"] = PluginInfo(
            name="search-engine", version="2.0", description="Search plugin",
            author="test", tags=["api", "search"],
        )

        results = mp.search(query="weather")
        assert len(results) == 1
        assert results[0].name == "weather"

    def test_search_by_tag(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {'audit': lambda self, *a, **kw: None})()
        mp = PluginMarketplace(rt)

        mp._registry["a"] = PluginInfo(name="a", version="1", description="", tags=["api"])
        mp._registry["b"] = PluginInfo(name="b", version="1", description="", tags=["tool"])

        results = mp.search(tags=["api"])
        assert len(results) == 1
        assert results[0].name == "a"

    def test_search_by_capability(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {'audit': lambda self, *a, **kw: None})()
        mp = PluginMarketplace(rt)

        mp._registry["img"] = PluginInfo(name="img", version="1", description="", capabilities=["image_gen"])

        results = mp.search(capability="image_gen")
        assert len(results) == 1

    def test_unregister(self):
        import asyncio
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {'audit': lambda self, *a, **kw: None})()
        mp = PluginMarketplace(rt)

        mp._registry["temp"] = PluginInfo(name="temp", version="1", description="")
        assert "temp" in mp._registry
        asyncio.run(mp.unregister("temp"))
        assert "temp" not in mp._registry


# ── Federation Tests ──────────────────────────────────

class TestFederation:
    def test_register_node(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        node = AgentNode(
            did="AGNT-A",
            capabilities=["image_gen", "text_gen"],
            online=True,
        )
        fm.register_node(node)
        assert "AGNT-A" in fm._directory
        assert "image_gen" in fm._by_capability
        assert "AGNT-A" in fm._by_capability["image_gen"]

    def test_discover_by_capability(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        fm.register_node(AgentNode(did="A", capabilities=["search"], online=True))
        fm.register_node(AgentNode(did="B", capabilities=["image_gen"], online=True))
        fm.register_node(AgentNode(did="C", capabilities=["search"], online=False))

        results = fm.discover(capability="search", online_only=True)
        assert len(results) == 1
        assert results[0].did == "A"

    def test_discover_all(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        fm.register_node(AgentNode(did="A", online=True))
        fm.register_node(AgentNode(did="B", online=True))

        results = fm.discover()
        assert len(results) == 2

    def test_unregister_node(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        fm.register_node(AgentNode(did="A", capabilities=["search"]))
        fm.unregister_node("A")
        assert "A" not in fm._directory
        assert "search" not in fm._by_capability or "A" not in fm._by_capability.get("search", set())

    def test_search(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        fm.register_node(AgentNode(did="AGNT-ALICE", display_name="Alice Agent", tags=["production"]))

        results = fm.search(query="alice")
        assert len(results) == 1
        assert results[0].did == "AGNT-ALICE"

    def test_stats(self):
        rt = type('RT', (), {})()
        rt.plugins = type('P', (), {'list': lambda: []})()
        fm = FederationManager(rt)

        fm.register_node(AgentNode(did="A", online=True))
        fm.register_node(AgentNode(did="B", online=False))

        stats = fm.stats()
        assert stats["total_nodes"] == 2
        assert stats["online_nodes"] == 1


# ── Payments Tests ────────────────────────────────────

class TestPayments:
    def test_request_requires_l4(self):
        import asyncio
        rt = _make_stub_runtime(l4=False)
        pm = PaymentManager(rt)

        try:
            asyncio.run(pm.request(100, Currency.USD, "recipient"))
            assert False, "Should raise PermissionError"
        except PermissionError:
            pass

    def test_request_and_confirm(self):
        import asyncio
        rt = _make_stub_runtime(l4=True)
        pm = PaymentManager(rt)
        # Don't actually execute — stub the execution
        async def stub_execute(request_id):
            pass
        pm._execute_payment = stub_execute

        payment = asyncio.run(pm.request(50, Currency.USDC, "AGNT-B", "test payment"))
        assert payment.status == PaymentStatus.PENDING
        assert payment.amount == 50.0
        assert payment.currency == Currency.USDC

        ok = asyncio.run(pm.confirm(payment.request_id, payment.confirmation_code))
        assert ok is True
        assert payment.status == PaymentStatus.CONFIRMED

    def test_reject_payment(self):
        import asyncio
        rt = _make_stub_runtime(l4=True)
        pm = PaymentManager(rt)

        payment = asyncio.run(pm.request(10, Currency.USD, "test"))
        ok = asyncio.run(pm.reject(payment.request_id, "not needed"))
        assert ok is True
        assert payment.status == PaymentStatus.REJECTED

    def test_wrong_code(self):
        import asyncio
        rt = _make_stub_runtime(l4=True)
        pm = PaymentManager(rt)

        payment = asyncio.run(pm.request(5, Currency.USD, "test"))
        ok = asyncio.run(pm.confirm(payment.request_id, "WRONG"))
        assert ok is False
        assert payment.status == PaymentStatus.PENDING

    def test_stats(self):
        import asyncio
        rt = _make_stub_runtime(l4=True)
        pm = PaymentManager(rt)

        asyncio.run(pm.request(100, Currency.USD, "a"))
        asyncio.run(pm.request(200, Currency.USDC, "b"))

        stats = pm.stats()
        assert stats["total"] == 2
        assert stats["pending"] == 2


# ── Enterprise Tests ──────────────────────────────────

class TestRBAC:
    def test_role_permissions(self):
        assert "dashboard.view" in ROLE_PERMISSIONS[Role.VIEWER]
        assert "triggers.manage" in ROLE_PERMISSIONS[Role.OPERATOR]
        assert "users.manage" in ROLE_PERMISSIONS[Role.ADMIN]
        assert "*" in ROLE_PERMISSIONS[Role.OWNER]
        assert "cross_tenant.access" in ROLE_PERMISSIONS[Role.SUPERADMIN]

    def test_rbac_can_check(self):
        rt = type('RT', (), {})()
        rbac = RBACManager(rt)
        rbac.add_user(User(user_id="u1", username="admin", role=Role.ADMIN))

        assert rbac.can("u1", "triggers.manage") is True
        assert rbac.can("u1", "payment.execute") is False

    def test_owner_has_all(self):
        rt = type('RT', (), {})()
        rbac = RBACManager(rt)
        rbac.add_user(User(user_id="u2", username="owner", role=Role.OWNER))

        assert rbac.can("u2", "payment.execute") is True
        assert rbac.can("u2", "any.random.permission") is True


class TestAuditExporter:
    def test_export_json(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {
            'get_audit_log': lambda self, limit: [
                {"id": 1, "action": "test", "detail": "{}", "hash": "abc123", "created_at": "2026-01-01T00:00:00Z"},
            ]
        })()
        exporter = AuditExporter(rt)
        data = exporter.export_json(10)
        assert "test" in data
        assert "abc123" in data

    def test_export_csv(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {
            'get_audit_log': lambda self, limit: [
                {"id": 1, "action": "test", "detail": "{}", "hash": "abc123", "created_at": "2026-01-01T00:00:00Z"},
            ]
        })()
        exporter = AuditExporter(rt)
        csv_data = exporter.export_csv(10)
        assert "test" in csv_data
        assert "abc123" in csv_data

    def test_verify_integrity_empty(self):
        rt = type('RT', (), {})()
        rt.storage = type('S', (), {
            'get_audit_log': lambda self, limit: []
        })()
        exporter = AuditExporter(rt)
        result = exporter.verify_integrity()
        assert result["valid"] is True
        assert result["entries"] == 0


class TestSSO:
    def test_configure_oidc(self):
        sso = SSOManager()
        sso.configure_oidc("google", "https://accounts.google.com", "client123")
        assert "google" in sso._providers
        assert sso._providers["google"]["type"] == "oidc"

    def test_list_providers(self):
        sso = SSOManager()
        sso.configure_oidc("okta", "https://okta.example.com", "client456")
        providers = sso.list_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "okta"
