"""
Quantro Internal action handlers.

These bodies are lifted directly from the pre-migration
execute_action_for_item() in server.py (see git history) — not
reimplemented. server.py's execute_action_for_item() is now a thin
compatibility shim that builds this module's `input` shape from an
inbox item and calls ActionExecutor.execute(), so there is exactly one
copy of "how do we create a calendar event / contact / onboarding
agent" in the codebase.

Deps expected in ActionContext.deps:
    calendar_col, contacts_col, agents_col, onboarding_col — Mongo collections
    log_activity — async fn(event_type, title, description, related_id=None, related_type=None, workspace_id=None)
    is_simulation_mode — async fn(workspace_id) -> bool

Simulation Mode note: internal Mongo writes are allowed during
Simulation Mode (sandbox data), but MUST always be tagged
`is_simulation=true` when effective_simulation is true.

Canonical rule:
    effective_simulation = ctx.dry_run OR bool(input.get("is_simulation"))

Never write Live rows (is_simulation=false) while Simulation Mode /
dry_run is active.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from ..base import ActionContext, ActionResult


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _effective_simulation(ctx: ActionContext, input: Dict[str, Any]) -> bool:
    """True when this write must be sandbox-tagged."""
    return bool(ctx.dry_run) or bool(input.get("is_simulation"))


async def calendar_event_create(ctx: ActionContext, input: dict) -> ActionResult:
    calendar_col = ctx.dep("calendar_col")
    log_activity = ctx.dep("log_activity")

    now = datetime.utcnow()
    event = {
        "event_id": str(uuid.uuid4()),
        "title": input.get("title") or "Meeting",
        "description": input.get("description", ""),
        "start_time": input.get("start_time") or (now + timedelta(days=1, hours=2)).isoformat(),
        "end_time": input.get("end_time") or (now + timedelta(days=1, hours=3)).isoformat(),
        "location": input.get("location") or "TBD",
        "attendees": input.get("attendees") or [],
        "status": "pending",
        "source": f"ai_{ctx.source}",
        "created_at": _now_iso(),
        "contact_id": input.get("contact_id"),
        "is_simulation": _effective_simulation(ctx, input),
        "workspace_id": ctx.workspace_id,
    }
    await calendar_col.insert_one(event)
    await log_activity(
        "calendar", f"Meeting auto-scheduled ({ctx.source})",
        f"Meeting '{event['title']}' created automatically", event["event_id"], "calendar",
        workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"event_id": event["event_id"]})


async def crm_contact_create(ctx: ActionContext, input: dict) -> ActionResult:
    contacts_col = ctx.dep("contacts_col")
    log_activity = ctx.dep("log_activity")

    now_iso = _now_iso()
    contact = {
        "contact_id": str(uuid.uuid4()),
        "name": input.get("name") or "Unknown",
        "email": input.get("email") or "",
        "phone": input.get("phone", ""),
        "type": "lead",
        "lifecycle_stage": "new",
        "source": f"inbox_{ctx.source}",
        "ghl_sync_status": "pending",
        "ghl_last_sync": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "notes": input.get("notes", ""),
        "is_simulation": _effective_simulation(ctx, input),
        "workspace_id": ctx.workspace_id,
    }
    await contacts_col.insert_one(contact)
    await log_activity(
        "crm", f"Contact auto-created ({ctx.source})",
        f"New contact {contact['name']} created automatically", contact["contact_id"], "contact",
        workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"contact_id": contact["contact_id"]})


async def onboarding_start(ctx: ActionContext, input: dict) -> ActionResult:
    agents_col = ctx.dep("agents_col")
    onboarding_col = ctx.dep("onboarding_col")
    log_activity = ctx.dep("log_activity")

    is_simulation = _effective_simulation(ctx, input)
    agent = {
        "agent_id": str(uuid.uuid4()),
        "name": input.get("name") or "New Agent",
        "email": input.get("email") or "",
        "phone": input.get("phone", ""),
        "role": "agent",
        "status": "onboarding",
        "start_date": datetime.utcnow().isoformat(),
        "photo_url": None,
        "created_at": _now_iso(),
        "is_simulation": is_simulation,
        "workspace_id": ctx.workspace_id,
    }
    await agents_col.insert_one(agent)
    default_steps = [
        "Complete compliance training",
        "Set up CRM profile",
        "Configure email signature",
        "Schedule orientation with team lead",
        "Access granted to listing portal",
    ]
    for idx, title in enumerate(default_steps):
        await onboarding_col.insert_one({
            "workspace_id": ctx.workspace_id, "task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"],
            "title": title, "description": f"Auto-generated step {idx + 1}", "status": "pending",
            "order": idx + 1, "completed_at": None, "auto_generated": True, "is_simulation": is_simulation,
        })
    await log_activity(
        "onboarding", f"Onboarding auto-started ({ctx.source})",
        f"Agent {agent['name']} onboarding initiated automatically", agent["agent_id"], "agent",
        workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"agent_id": agent["agent_id"]})


async def followup_send(ctx: ActionContext, input: dict) -> ActionResult:
    log_activity = ctx.dep("log_activity")
    await log_activity(
        "inbox", f"Follow-up auto-queued ({ctx.source})",
        f"Follow-up for {input.get('recipient_name', 'contact')} queued automatically",
        input.get("related_id"), "inbox", workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"queued": True})


async def review_flag(ctx: ActionContext, input: dict) -> ActionResult:
    log_activity = ctx.dep("log_activity")
    await log_activity(
        "inbox", f"Flagged for review ({ctx.source})",
        input.get("reason") or "Flagged for manual review",
        input.get("related_id"), "inbox", workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"flagged": True})


async def inbox_ignore(ctx: ActionContext, input: dict) -> ActionResult:
    log_activity = ctx.dep("log_activity")
    await log_activity(
        "inbox", f"Auto-ignored ({ctx.source})",
        f"Message from {input.get('from_name', 'unknown')} auto-ignored (spam/irrelevant)",
        input.get("related_id"), "inbox", workspace_id=ctx.workspace_id,
    )
    status = "simulated" if ctx.dry_run else "succeeded"
    return ActionResult(status=status, result_metadata={"ignored": True})
