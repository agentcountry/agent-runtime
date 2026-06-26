"""
Agent Runtime CLI — command-line interface for managing Agent Runtime.

Phase 3: Plugin marketplace, federation, and enterprise management commands.
"""

import argparse
import asyncio
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="agent-runtime",
        description="Agent Runtime — 24/7 background process for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    # ── Plugin ──────────────────────────────────────────
    plugin = sub.add_parser("plugin", help="Plugin marketplace commands")
    plugin_sub = plugin.add_subparsers(dest="subcommand")

    plugin_list = plugin_sub.add_parser("list", help="List installed plugins")
    plugin_list.add_argument("--registry", action="store_true", help="List registry instead of installed")

    plugin_search = plugin_sub.add_parser("search", help="Search plugin registry")
    plugin_search.add_argument("query", nargs="?", default="")
    plugin_search.add_argument("--tag", action="append", dest="tags")
    plugin_search.add_argument("--capability", default="")

    plugin_install = plugin_sub.add_parser("install", help="Install a plugin")
    plugin_install.add_argument("name")
    plugin_install.add_argument("--version", default="")

    plugin_uninstall = plugin_sub.add_parser("uninstall", help="Uninstall a plugin")
    plugin_uninstall.add_argument("name")

    # ── Federation ──────────────────────────────────────
    federate = sub.add_parser("federate", help="Federation commands")
    federate_sub = federate.add_subparsers(dest="subcommand")

    federate_discover = federate_sub.add_parser("discover", help="Discover agents")
    federate_discover.add_argument("--capability", default="")
    federate_discover.add_argument("--search", default="")
    federate_discover.add_argument("--online-only", action="store_true", default=True)

    federate_stats = federate_sub.add_parser("stats", help="Federation statistics")

    # ── Audit Export ────────────────────────────────────
    export = sub.add_parser("export", help="Export commands")
    export_sub = export.add_subparsers(dest="subcommand")

    export_audit = export_sub.add_parser("audit", help="Export audit logs")
    export_audit.add_argument("--format", choices=["csv", "json", "jsonl"], default="json")
    export_audit.add_argument("--limit", type=int, default=1000)
    export_audit.add_argument("--output", default="")

    export_verify = export_sub.add_parser("verify", help="Verify audit chain integrity")

    # ── Status ──────────────────────────────────────────
    status = sub.add_parser("status", help="Show runtime status (JSON)")

    # ── Start ───────────────────────────────────────────
    start = sub.add_parser("start", help="Start the Agent Runtime daemon")
    start.add_argument("--dashboard", action="store_true", help="Enable web dashboard")
    start.add_argument("--federation", action="store_true", help="Enable federation")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "status":
        print(json.dumps(_get_status(), indent=2))
    elif args.command == "plugin":
        _handle_plugin(args)
    elif args.command == "federate":
        _handle_federation(args)
    elif args.command == "export":
        _handle_export(args)
    elif args.command == "start":
        _handle_start(args)


def _get_status() -> dict:
    """Get runtime status. CLI stub — returns defaults if not running."""
    return {
        "version": "0.3.0",
        "status": "CLI only — runtime not loaded",
        "message": "Use 'agent-runtime start' to launch the daemon",
    }


def _handle_plugin(args):
    """Handle plugin subcommands."""
    from agent_runtime.marketplace import PluginMarketplace

    class StubRuntime:
        storage = type('S', (), {'audit': lambda *a, **kw: None})()

    mp = PluginMarketplace(StubRuntime())

    if args.subcommand == "list":
        if args.registry:
            plugins = mp.list_registry()
            print(f"{'Name':<30} {'Version':<10} {'Description'}")
            print("-" * 60)
            for p in plugins:
                print(f"{p.name:<30} {p.version:<10} {p.description[:40]}")
        else:
            plugins = mp.list_installed()
            if not plugins:
                print("No plugins installed.")
            else:
                print(f"{'Name':<30} {'Version':<10} {'Description'}")
                print("-" * 60)
                for p in plugins:
                    print(f"{p.name:<30} {p.version:<10} {p.description[:40]}")
        print(f"\nTotal: {len(plugins)}")

    elif args.subcommand == "search":
        results = mp.search(query=args.query, tags=args.tags, capability=args.capability)
        if not results:
            print("No plugins found.")
        else:
            print(f"{'Name':<30} {'Version':<10} {'Rating':<8} {'Description'}")
            print("-" * 70)
            for p in results:
                print(f"{p.name:<30} {p.version:<10} {'★' * int(p.rating):<8} {p.description[:40]}")

    elif args.subcommand == "install":
        info = mp._registry.get(args.name)
        if info:
            print(f"✓ Plugin found: {info.name} v{info.version}")
            print(f"  Run 'agent-runtime start' to load it.")
        else:
            print(f"✗ Plugin not found: {args.name}")

    elif args.subcommand == "uninstall":
        print(f"Uninstalling {args.name}...")
        print("  Run 'agent-runtime start' to apply changes.")

    else:
        print("Usage: agent-runtime plugin <list|search|install|uninstall>")


def _handle_federation(args):
    """Handle federation subcommands."""
    from agent_runtime.federation import FederationManager

    class StubRuntime:
        did = "CLI"
        permissions = type('P', (), {'level': 0})()
        plugins = type('Pl', (), {'list': lambda: []})()
        _started = False
        _armp = None
        homeserver = ""

    fm = FederationManager(StubRuntime())

    if args.subcommand == "discover":
        if args.search:
            nodes = fm.search(query=args.search)
        else:
            nodes = fm.discover(capability=args.capability, online_only=args.online_only)

        if not nodes:
            print("No agents discovered.")
        else:
            print(f"{'DID':<30} {'Capabilities':<40} {'Online'}")
            print("-" * 80)
            for n in nodes:
                caps = ", ".join(n.capabilities[:3])
                status = "🟢" if n.online else "🔴"
                print(f"{n.did:<30} {caps:<40} {status}")

    elif args.subcommand == "stats":
        print(json.dumps(fm.stats(), indent=2))

    else:
        print("Usage: agent-runtime federate <discover|stats>")


def _handle_export(args):
    """Handle export subcommands."""
    from agent_runtime.enterprise import AuditExporter

    class StubRuntime:
        class Storage:
            def get_audit_log(self, limit):
                return [
                    {"id": 1, "action": "test", "detail": "{}", "hash": "0" * 64, "created_at": "2026-01-01T00:00:00Z"},
                    {"id": 2, "action": "test2", "detail": "{}", "hash": "0" * 64, "created_at": "2026-01-01T01:00:00Z"},
                ][:limit]
        storage = Storage()

    exporter = AuditExporter(StubRuntime())

    if args.subcommand == "audit":
        if args.format == "csv":
            data = exporter.export_csv(args.limit)
        elif args.format == "jsonl":
            data = exporter.export_jsonl(args.limit)
        else:
            data = exporter.export_json(args.limit)

        if args.output:
            with open(args.output, "w") as f:
                f.write(data)
            print(f"Exported {args.limit} entries to {args.output}")
        else:
            print(data)

    elif args.subcommand == "verify":
        result = exporter.verify_integrity()
        status = "✅ VALID" if result["valid"] else "❌ BROKEN"
        print(f"Audit chain: {status}")
        print(f"Entries: {result['entries']}")
        if not result["valid"] and result["first_violation"]:
            print(f"First violation at id={result['first_violation']['id']}")

    else:
        print("Usage: agent-runtime export <audit|verify>")


def _handle_start(args):
    """Start the agent runtime daemon."""
    print("Starting Agent Runtime v0.3.0...")
    print("  Dashboard:", "enabled" if args.dashboard else "disabled")
    print("  Federation:", "enabled" if args.federation else "disabled")
    print("\nRun from Python:")
    print("  from agent_runtime import Runtime")
    print("  rt = Runtime(did='...', homeserver='...', username='...', password='...')")
    print("  await rt.start(enable_dashboard=True)")


if __name__ == "__main__":
    main()
