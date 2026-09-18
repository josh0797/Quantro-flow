"""
Microsoft action handlers — same reauthorization_required contract as
handlers/google.py. See microsoft_oauth.py's ACTION_SCOPES docstring
for why the actual incremental-consent UX is a documented follow-up
(Graph/MSAL don't support Google-style scope deltas) — the important
part for correctness today is that these handlers never call Graph
with a scope the stored token doesn't have; they fail structured
instead.
"""
from __future__ import annotations

from errors import QuantroError
from ..base import ActionContext, ActionResult


async def _access_token_or_raise(ctx: ActionContext, action_id: str) -> str:
    msoa = ctx.dep("msoa_module")
    col = ctx.dep("microsoft_integrations_col")
    doc = await col.find_one({"workspace_id": ctx.workspace_id})
    if not doc:
        raise QuantroError("provider_not_connected", "Microsoft is not connected for this workspace")

    required_scope = msoa.ACTION_SCOPES[action_id]
    stored_scopes = doc.get("scopes") or []
    if required_scope not in stored_scopes:
        raise QuantroError(
            "reauthorization_required",
            "Additional Microsoft permission required for this action",
            extra={"provider": "microsoft", "missing_scopes": [required_scope]},
        )

    load_credentials = ctx.dep("load_microsoft_credentials")
    access_token, doc = await load_credentials(ctx.workspace_id)
    if not access_token:
        raise QuantroError("provider_not_connected", "Microsoft is not connected for this workspace")
    return access_token


async def mail_send(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"to": input.get("to"), "subject": input.get("subject")}})
    access_token = await _access_token_or_raise(ctx, "microsoft.mail.send")
    msoa = ctx.dep("msoa_module")
    msoa.send_mail(access_token, input["to"], input["subject"], input.get("body", ""))
    return ActionResult(status="succeeded", result_metadata={"sent": True})


async def calendar_event_create(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"subject": input.get("title"), "start_time": input.get("start_time")}})
    access_token = await _access_token_or_raise(ctx, "microsoft.calendar.event.create")
    msoa = ctx.dep("msoa_module")
    event_id = msoa.create_calendar_event(
        access_token,
        subject=input["title"],
        start_iso=input["start_time"],
        end_iso=input["end_time"],
        description=input.get("description", ""),
        location=input.get("location", ""),
        attendees=input.get("attendees"),
    )
    return ActionResult(status="succeeded", result_metadata={"event_id": event_id}, provider_request_id=event_id)
