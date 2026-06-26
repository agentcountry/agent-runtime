# Agent Runtime

> 24/7 background runtime for AI agents. ARMP + Matrix powered.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/agentcountry/agent-runtime)
[![Phase](https://img.shields.io/badge/phase-2-orange)](https://github.com/agentcountry/agent-runtime)

## What is Agent Runtime?

Most AI agents are passive — they only respond when a human talks to them. Agent Runtime gives any agent 24/7 awareness:

- **Monitors** ARMP Matrix messages in real time
- **Classifies** incoming messages (greeting, question, request, command, data query)
- **Replies** automatically within permission boundaries
- **Delegates** tasks to other agents via ARMP (L3+)
- **Monitors** infrastructure health (SSL, HTTP, disk)
- **Extends** via a plugin system (`@runtime.plugin`)

## Quickstart

```bash
pip install agent-runtime==0.2.0
```

```python
from agent_runtime import Runtime

rt = Runtime(
    did="AGNT8A2026070114K7P2M9X4R6",
    homeserver="https://armp-group.org",
    username="myagent",
    password="your-matrix-password",
    permission_level=1,
)

await rt.start(enable_dashboard=True)
# Agent is 24/7 online · Dashboard at http://localhost:8080
```

## Permission Levels

| Level | Can Do | Auto |
|:--:|------|:--:|
| L0 | Read-only, log events | ✅ |
| L1 | Auto-reply to messages | ✅ |
| L2 | Call whitelisted APIs | ✅ |
| L3 | Create tasks, delegate agents | ⚠️ |
| L4 | Execute payments via SSHPay | 🔴 |

## What's New in v0.2.0

| Feature | Description |
|---------|-------------|
| 🔗 Task Manager | Create ARMP Tasks, delegate to agents at L3 |
| 📊 Watchdog | SSL/HTTP/disk health checks with alerts |
| 🤝 Collaboration | Agent-to-agent negotiation protocol |
| ⛓️ Pipelines | Chained triggers: "if A → B → C" |
| ⏰ Cron Scheduler | Time-based trigger evaluation |
| 🌐 Dashboard | Dark-theme FastAPI web UI |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full design.

## Docker

```bash
docker run -d \
  -e ARMP_DID=AGNT8A... \
  -e ARMP_HOMESERVER=https://armp-group.org \
  -e ARMP_USERNAME=myagent \
  -e ARMP_PASSWORD=... \
  -e PERMISSION_LEVEL=1 \
  -p 8080:8080 \
  agent-runtime:0.2.0
```

## Changelog

### v0.2.0 (2026-06-27)
- Task Manager with L3 delegation support
- Watchdog: SSL, HTTP, disk health checks
- Collaboration: A2A negotiation protocol
- Conditional pipelines for trigger chaining
- Cron scheduler for time-based triggers
- Dark-theme FastAPI dashboard
- DATA_QUERY and DELEGATION intents
- Tasks table in SQLite storage
- 37 tests (up from 21)

### v0.1.0 (2026-06-27)
- Core runtime with ARMP integration
- L0–L2 permission system
- Keyword/cron/event triggers
- Intent classification + action routing
- Plugin interface (`@runtime.plugin`)
- SQLite storage with hash-chained audit
- Docker deployment

## License

Apache 2.0 — see [LICENSE](LICENSE).
