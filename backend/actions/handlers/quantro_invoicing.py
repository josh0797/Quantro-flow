"""Quantro OS invoicing action handlers — query + reply prep only (no CFDI create)."""
from __future__ import annotations

from ..base import ActionContext, ActionResult


def _adapter(ctx: ActionContext):
    return ctx.dep("quantro_invoicing_adapter")


async def invoice_query(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(
            status="simulated",
            result_metadata={"predicted": {"q": input.get("q"), "invoice_id": input.get("invoice_id")}},
        )
    data = await _adapter(ctx).query_invoices(
        ctx.workspace_id,
        q=input.get("q") or "",
        limit=input.get("limit") or 10,
        invoice_id=input.get("invoice_id"),
    )
    return ActionResult(status="succeeded", result_metadata=data)


async def invoice_prepare_reply(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(
            status="simulated",
            result_metadata={
                "predicted": {
                    "channel": input.get("channel") or "gmail",
                    "to": input.get("to"),
                    "invoice_id": input.get("invoice_id"),
                }
            },
        )
    payload = await _adapter(ctx).prepare_reply_payload(
        ctx.workspace_id,
        invoice_id=input.get("invoice_id"),
        q=input.get("q") or "",
        to=input.get("to"),
        channel=input.get("channel") or "gmail",
    )
    return ActionResult(status="succeeded", result_metadata=payload)
