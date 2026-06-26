# Agent Runtime

> 24/7 background runtime for AI agents. ARMP + Matrix powered.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.3.0-blue)](https://github.com/agentcountry/agent-runtime)
[![Phase](https://img.shields.io/badge/phase-3-green)](https://github.com/agentcountry/agent-runtime)

## What is Agent Runtime?

Most AI agents are passive. Agent Runtime gives any agent 24/7 awareness:
monitor messages, auto-reply, delegate tasks, discover peers,
process payments, and run health checks — all with permission boundaries.

## Quickstart

```bash
pip install agent-runtime==0.3.0
```

```python
from agent_runtime import Runtime

rt = Runtime(
    did="AGNT8A...",
    homeserver="https://armp-group.org",
    username="myagent",
    password="***",
    permission_level=2,
)

await rt.start(enable_dashboard=True, enable_federation=True)
```

## Permission Levels

| Level | Can Do | Auto |
|:--:|------|:--:|
| L0 | Read-only, log events | ✅ |
| L1 | Auto-reply to messages | ✅ |
| L2 | Call whitelisted APIs | ✅ |
| L3 | Create tasks, delegate agents | ⚠️ |
| L4 | Payments with confirmation code | 🔴 |

## CLI

```bash
agent-runtime plugin search weather
agent-runtime plugin install weather
agent-runtime federate discover --capability image_gen
agent-runtime export audit --format csv
agent-runtime export verify
```

## Features

| Feature | Since | Description |
|---------|:--:|------|
| Core Runtime | v0.1 | ARMP Matrix integration, L0–L2 |
| Tasks & Watchdog | v0.2 | L3 delegation, health checks |
| Marketplace | v0.3 | Plugin registry, install/search |
| Federation | v0.3 | Cross-server agent discovery |
| Payments | v0.3 | L4 SSHPay with confirmation |
| Enterprise | v0.3 | RBAC, audit export, SSO |
| Dashboard | v0.2 | Dark-theme FastAPI web UI |
| Pipelines | v0.2 | Chained conditional triggers |
| Collaboration | v0.2 | A2A negotiation protocol |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full design.

## Docker

```bash
docker run -d \
  -e ARMP_DID=AGNT8A... \
  -e ARMP_HOMESERVER=https://armp-group.org \
  -e ARMP_USERNAME=myagent \
  -e ARMP_PASSWORD=*** \
  -e PERMISSION_LEVEL=2 \
  -p 8080:8080 \
  agent-runtime:0.3.0
```

## Changelog

### v0.3.0 (2026-06-28)
- Plugin Marketplace: registry, install, search, uninstall
- Federation Manager: cross-server agent discovery + directory
- Payment Manager: L4 SSHPay with confirmation code verification
- Enterprise: RBAC (5 roles), audit export (CSV/JSON/JSONL), hash-chain verification, SSO hooks
- CLI: `agent-runtime plugin|federate|export` commands

### v0.2.0 (2026-06-27)
- Task Manager, Watchdog, Collaboration, Pipelines, Cron, Dashboard

### v0.1.0 (2026-06-27)
- Core runtime, permissions, triggers, plugins, storage

## License

Apache 2.0 — see [LICENSE](LICENSE).
