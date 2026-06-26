# Agent Runtime

> 24/7 background runtime for AI agents. ARMP + Matrix powered.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange)](https://github.com/agentcountry/agent-runtime)

## What is Agent Runtime?

Most AI agents are passive — they only respond when a human talks to them. Agent Runtime gives any agent 24/7 awareness:

- **Monitors** ARMP Matrix messages in real time
- **Classifies** incoming messages (greeting, question, request, command)
- **Replies** automatically within permission boundaries
- **Escalates** important messages to the human owner
- **Extends** via a plugin system (`@runtime.plugin`)

## Quickstart

```bash
pip install agent-runtime
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

await rt.start()
# Agent is now 24/7 online
```

## Permission Levels

| Level | Can Do | Auto |
|:--:|------|:--:|
| L0 | Read-only, log events | ✅ |
| L1 | Auto-reply to messages | ✅ |
| L2 | Call whitelisted APIs | ✅ |
| L3 | Create tasks, delegate agents | ⚠️ |
| L4 | Execute payments via SSHPay | 🔴 |

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
  agent-runtime:latest
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
