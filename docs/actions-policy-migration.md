# Quantro Actions — Policy unification & indexes

## Unified Policy Engine

Standalone Actions no longer use a second independent rule brain. `PolicyGate`
delegates to `actions.policy_engine.PolicyEngine`, which:

1. Always prefers **Simulation Mode** (`simulate`).
2. Enforces **RBAC** via `ActionDefinition.minimum_role` (+ defaults by provider/risk).
3. Reads **`automation_policies`** with `scope: "action"` as the preferred SoT.
4. Falls back to legacy **`action_policies`** (`auto_approve`, `daily_limit`) for
   high/critical Actions during migration.
5. Exposes `evaluate_inbox_action()` so Inbox outcomes share the same vocabulary
   (`execute | pending_approval | block | simulate | escalate`).

Inbox intent evaluation (`evaluate_policy_for_item` / `evaluate_advanced_escalation`)
remains intact for backward compatibility.

### Recommended `automation_policies` shape for Actions

```json
{
  "policy_id": "...",
  "workspace_id": "...",
  "enabled": true,
  "scope": "action",
  "action_id": "facturapi.invoice.create",
  "mode": "require_approval",
  "minimum_role": "leader",
  "daily_limit": 20
}
```

`mode` values: `auto_run` | `require_approval` | `block` | `simulate` | `escalate`.

Legacy `action_policies` rows continue to work until migrated.

## Mongo index — atomic idempotency

Collection: `action_executions`  
Name: `uniq_workspace_action_idempotency_key`  
Keys: `(workspace_id, action_id, idempotency_key)` unique  
Partial filter: `idempotency_key` exists and is a string  

Created idempotently at startup via `ensure_action_indexes()`.

If historical duplicates block index creation, **do not auto-delete**. Resolve
manually (keep earliest execution per key) then restart.

## Approval lifecycle

`pending_approval → approved → running → succeeded|failed|simulated` on the
**same** `execution_id`. Simulation Mode still wins if enabled between pending
and approve.
