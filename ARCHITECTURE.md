# Agent Runtime — Architecture

## Overview

Agent Runtime is a 24/7 background process that keeps AI agents online,
monitors messages, and takes autonomous action within permission boundaries.

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
                   │  DELEGATE (L3+)  │
                   │  ESCALATE        │
                   └──────┬──────────┘
                          ▼
                    Audit Log (SQLite)
                    (hash-chained)
```

### Full Ecosystem (Phase 3)

```
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐
  │Marketplace│  │Federation│  │ Payments │  │   Enterprise     │
  │          │  │          │  │          │  │                  │
  │·register │  │·discover │  │·L4 conf  │  │·RBAC (5 roles)   │
  │·install  │  │·announce │  │·SSHPay   │  │·Audit export     │
  │·search   │  │·cross-sv │  │·2FA code │  │·SSO (OIDC/SAML)  │
  │·uninstall│  │·rooms    │  │·audit    │  │·Chain verify     │
  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘
       │              │             │                  │
       └──────────────┼─────────────┼──────────────────┘
                      ▼             ▼
              ┌──────────────┐  ┌──────────┐
              │ Task Manager │  │ Notifier │
              └──────────────┘  └──────────┘
```

## Component Map

```
agent_runtime/
├── __init__.py          Runtime class, lifecycle (v0.3.0)
├── permissions.py       L0–L4 permission levels
├── triggers.py          Keyword/cron/event triggers + pipelines
├── decision.py          Intent classification + action routing
├── plugins.py           Plugin interface (@runtime.plugin)
├── storage.py           SQLite persistence + audit + tasks
├── notifier.py          Notification dispatch
├── config.py            Default configuration
├── task_manager.py      L3 ARMP task creation + delegation
├── watchdog.py          Health checks: SSL, HTTP, disk
├── collaboration.py     Agent-to-agent negotiation
├── dashboard.py         FastAPI dark-theme web UI
├── marketplace.py       Plugin registry + lifecycle (Phase 3)
├── federation.py        Cross-server discovery + directory (Phase 3)
├── payments.py          L4 SSHPay integration + confirmation (Phase 3)
├── enterprise.py        RBAC + audit export + SSO (Phase 3)
├── cli.py              Command-line interface
└── templates/           Dashboard HTML
```

## Permission Levels

| L | Name | Actions | Auto? |
|:--:|------|------|:--:|
| 0 | NOTIFY | Log-only | ✅ |
| 1 | REPLY | Auto-reply | ✅ |
| 2 | API_CALL | Call whitelisted APIs | ✅ |
| 3 | CREATE_TASK | Delegate tasks | ⚠️ |
| 4 | PAY | Payments with confirmation code | 🔴 |

## Phase 3 Highlights

### Plugin Marketplace
```bash
agent-runtime plugin search "weather"
agent-runtime plugin install weather
agent-runtime plugin list
```

### Federation
```python
rt.federation.start()
nodes = rt.federation.discover(capability="image_gen", online_only=True)
```

### Payments (L4)
```python
payment = await rt.payments.request(100, Currency.USDC, "AGNT-B", "image generation")
await rt.payments.confirm(payment.request_id, "ABC12345")  # Confirmation code
```

### Enterprise
```python
rt.enterprise.rbac.add_user(User(user_id="u1", username="admin", role=Role.ADMIN))
csv = rt.enterprise.audit_exporter.export_csv(limit=1000)
integrity = rt.enterprise.audit_exporter.verify_integrity()
```

## Storage Schema

```
events:        id, event_type, data(JSON), created_at
audit_log:     id, action, detail(JSON), previous_hash, hash, created_at
config:        key, value, updated_at
tasks:         task_id, title, description, status, priority, ...
```
