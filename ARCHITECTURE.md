# Agent Runtime — Architecture

## Overview

Agent Runtime is a 24/7 background process that keeps AI agents online,
monitors messages, and takes autonomous action within permission boundaries.

Phase 2 adds: L3 task delegation, health watchdog, agent collaboration,
conditional pipelines, cron scheduling, and a web dashboard.

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
                   ┌─────────────────┐
                   │  Execute         │
                   │  IGNORE          │
                   │  NOTIFY          │
                   │  REPLY           │
                   │  API_CALL        │
                   │  DELEGATE (L3+)  │  ← Phase 2
                   │  ESCALATE        │
                   └──────┬──────────┘
                          ▼
                    Audit Log (SQLite)
                    (hash-chained)
```

### Phase 2: Extended Flow

```
  C R O N            T R I G G E R S            W A T C H D O G
  ─────────         ─────────────────         ─────────────────
  CronScheduler  →  ConditionalPipeline   →  Health Checks
  (time-based)      (if-A-then-B-then-C)     (SSL, HTTP, Disk)
        │                    │                      │
        └────────────────────┼──────────────────────┘
                             ▼
                      Decision Engine
                             │
                    ┌────────┼────────┐
                    ▼        ▼        ▼
               Task Manager  Notifier  Collaboration
               (L3+ tasks)            (Agent ↔ Agent)
```

## Component Map

```
agent_runtime/
├── __init__.py          Runtime class, lifecycle (Phase 1+2)
├── permissions.py       L0–L4 permission levels
├── triggers.py          Keyword/cron/event triggers + conditional pipelines
├── decision.py          Intent classification + action routing (incl. DELEGATE)
├── plugins.py           Plugin interface (@runtime.plugin)
├── storage.py           SQLite persistence + audit + tasks table
├── notifier.py          Notification dispatch
├── config.py            Default configuration
├── task_manager.py      L3 ARMP task creation + delegation (Phase 2)
├── watchdog.py          Health checks: SSL, HTTP, disk (Phase 2)
├── collaboration.py     Agent-to-Agent negotiation (Phase 2)
├── dashboard.py         FastAPI web dashboard with dark theme (Phase 2)
└── templates/           Dashboard HTML templates
```

## Decision Pipeline

1. **Permission Check** — can the agent handle messages at its current level?
2. **Intent Classification** — regex patterns (Phase 1) → LLM (Phase 3)
3. **Action Decision** — map intent + permission level to action
4. **Action Execution** — IGNORE / NOTIFY / REPLY / API_CALL / DELEGATE / ESCALATE
5. **Audit Logging** — all L1+ actions written to hash-chained SQLite log

## Intents (Phase 2)

| Intent | Patterns | Phase |
|--------|----------|:--:|
| GREETING | hello, hi, hey | 1 |
| QUESTION | what, how, why, when | 1 |
| REQUEST | can you, please, help | 1 |
| COMMAND | do, run, execute | 1 |
| DATA_QUERY | price, cost, rate, status | 2 |
| DELEGATION | assign, delegate, hand off | 2 |
| SPAM | too many links, too long | 1 |
| UNKNOWN | fallback | 1 |

## Permission Levels

| L | Name | Actions | Auto? |
|:--:|------|------|:--:|
| 0 | NOTIFY | Log-only, no action | ✅ |
| 1 | REPLY | Auto-reply to greetings/questions | ✅ |
| 2 | API_CALL | Call whitelisted APIs | ✅ |
| 3 | CREATE_TASK | Create ARMP tasks, delegate | ⚠️ |
| 4 | PAY | Execute payments via SSHPay | 🔴 |

## Conditional Pipelines

```python
pipeline = ConditionalPipeline("auto_quote")
pipeline.add_step(PipelineStep(
    name="check_price",
    condition=lambda ctx: "price" in ctx.get("message", ""),
    action=query_apitrad_price,
))
pipeline.add_step(PipelineStep(
    name="send_result",
    condition=lambda ctx: ctx.get("price"),
    action=send_price_to_requester,
))
```

## Cron Scheduler

Background loop evaluates `TriggerType.CRON` triggers on configured intervals:

```python
rt.triggers.add(Trigger(
    name="hourly_health",
    trigger_type=TriggerType.CRON,
    cron_interval=3600,  # seconds
    handler=run_watchdog_checks,
))
```

## Watchdog Checks

| Check Type | What | Config |
|------------|------|--------|
| ssl:* | SSL cert expiry | domain, port |
| http:* | HTTP endpoint reachable | url, expected_status |
| disk:* | Disk usage | path, warn_pct, critical_pct |
| cert_files | Local cert file expiry | paths list |

## Collaboration Protocol

```
Initiator Agent                  Partner Agent
      │                               │
      │── CAPABILITY_QUERY ──────────→│  "Can you do X?"
      │←─ CAPABILITY_ACCEPT ─────────│  "Yes, I can"
      │── Task Delegation ───────────→│  ARMP Task
      │←─ TASK_COMPLETE ─────────────│  Done with result
```

## Dashboard

FastAPI server on port 8080 (default). Dark theme with:
- Agent status (online/offline, DID, permission level)
- Trigger and watchdog summaries
- Task stats with recent task table
- Collaboration session counts
- JSON API endpoints at `/api/status`, `/api/tasks`, `/api/watchdog`
- Auto-refresh every 30 seconds

## Storage Schema

```
events:        id, event_type, data(JSON), created_at
audit_log:     id, action, detail(JSON), previous_hash, hash, created_at
config:        key, value, updated_at
tasks:         task_id, title, description, status, priority,            ← Phase 2
               requester_did, assignee_did, capability, parameters,
               result, deadline, tags, created_at, updated_at, completed_at
```

Audit logs are hash-chained for tamper evidence: each entry's hash = SHA-256(previous_hash + data).

## Extension Points

- **Plugins**: Register via `runtime.register_plugin(name, plugin_obj)`
- **Triggers**: Add via `runtime.triggers.add(Trigger(...))`
- **Pipelines**: Create `ConditionalPipeline` and add to runtime
- **Watchdog**: Register checks with `runtime.watchdog.add_check(...)`
- **Decision**: Override `runtime.decision.classify()` for custom logic
