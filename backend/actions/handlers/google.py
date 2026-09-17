"""
Google action handlers. Both write scopes (gmail.send, calendar.events)
are requested incrementally — never at first connect (see
google_oauth.py's ACTION_SCOPES) — so every handler here checks the
workspace's stored scopes before calling Google, and returns a
structured `reauthorization_required` error (never a bare 500) when
the scope is missing, matching the task spec's error model exactly.
"""
from __future__ import annotations

from errors import QuantroError
from ..base import ActionContext, ActionResult


async def _load_creds_or_raise(ctx: ActionContext, action_id: str):
    goog = ctx.dep("goog_module")
    col = ctx.dep("google_integrations_col")
    doc = await col.find_one({"workspace_id": ctx.workspace_id})
    if not doc:
        raise QuantroError("provider_not_connected", "Google is not connected for this workspace")

    required_scope = goog.ACTION_SCOPES[action_id]
    stored_scopes = doc.get("scopes") or []
    if required_scope not in stored_scopes:
        raise QuantroError(
            "reauthorization_required",
            "Additional Google permission required for this action",
            extra={
                "provider": "google",
                "missing_scopes": [required_scope],
                "reauthorization_url": f"/api/connect/providers/google/request-permission?action_id={action_id}",
            },
        )

    load_credentials = ctx.dep("load_google_credentials")
    creds, doc = await load_credentials(ctx.workspace_id)
    if not creds:
        raise QuantroError("provider_not_connected", "Google is not connected for this workspace")
    return creds


async def gmail_send(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"to": input.get("to"), "subject": input.get("subject")}})
    creds = await _load_creds_or_raise(ctx, "google.gmail.send")
    goog = ctx.dep("goog_module")
    message_id = goog.send_gmail(creds, input["to"], input["subject"], input.get("body", ""))
    return ActionResult(status="succeeded", result_metadata={"message_id": message_id}, provider_request_id=message_id)


async def calendar_event_create(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"title": input.get("title"), "start_time": input.get("start_time")}})
    creds = await _load_creds_or_raise(ctx, "google.calendar.event.create")
    goog = ctx.dep("goog_module")
    event_id = goog.create_calendar_event(
        creds,
        title=input["title"],
        start_iso=input["start_time"],
        end_iso=input["end_time"],
        description=input.get("description", ""),
        location=input.get("location", ""),
        attendees=input.get("attendees"),
    )
    return ActionResult(status="succeeded", result_metadata={"event_id": event_id}, provider_request_id=event_id)
