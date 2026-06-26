# Agent Runtime — Architecture

## Overview

Agent Runtime is a 24/7 background process that keeps AI agents online, monitors messages, and takes autonomous action within permission boundaries.

## Data Flow

```
Matrix Message → ARMP SDK → Runtime._handle_message()
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              Permission    Decision     Plugins
                Check       Engine     .on_message()
                    │           │
                    ▼           ▼
                Allowed?    Intent +
                    │       Action
                    └─────┬─────┘
                          ▼
                   ┌─────────────┐
                   │  Execute     │
                   │  IGNORE      │
                   │  NOTIFY      │
                   │  REPLY       │
                   │  API_CALL    │
                   │  ESCALATE    │
                   └──────┬──────┘
                          ▼
                    Audit Log (SQLite)
                    (hash-chained)
```

## Component Map

```
agent_runtime/
├── __init__.py      Runtime class, lifecycle
├── permissions.py   L0-L4 permission levels
├── triggers.py      Keyword/cron/event triggers
├── decision.py      Intent classification + action routing
├── plugins.py       Plugin interface (@runtime.plugin)
├── storage.py       SQLite persistence + audit
├── notifier.py      Notification dispatch
└── config.py        Default configuration
```

## Decision Pipeline

1. **Permission Check** — can the agent handle messages at its current level?
2. **Intent Classification** — regex patterns (Phase 1) → LLM (Phase 2)
3. **Action Decision** — map intent + permission level to action
4. **Action Execution** — IGNORE / NOTIFY / REPLY / API_CALL / ESCALATE
5. **Audit Logging** — all L1+ actions written to hash-chained SQLite log

## Permission Levels

| L | Name | Actions | Auto? |
|:--:|------|------|:--:|
| 0 | NOTIFY | Log-only, no action | ✅ |
| 1 | REPLY | Auto-reply to greetings/questions | ✅ |
| 2 | API_CALL | Call whitelisted APIs | ✅ |
| 3 | CREATE_TASK | Delegate to other agents | ⚠️ |
| 4 | PAY | Execute payments via SSHPay | 🔴 |

## Storage Schema

```
events:        id, event_type, data(JSON), created_at
audit_log:     id, action, detail(JSON), previous_hash, hash, created_at
config:        key, value, updated_at
```

Audit logs are hash-chained for tamper evidence: each entry's hash = SHA-256(previous_hash + data).

## Extension Points

- **Plugins**: Register via `runtime.register_plugin(name, plugin_obj)`
- **Triggers**: Add via `runtime.triggers.add(Trigger(...))`
- **Decision**: Override `runtime.decision.classify()` for custom logic
