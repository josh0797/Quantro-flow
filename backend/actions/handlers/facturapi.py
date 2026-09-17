"""
Facturapi action handlers — thin wrappers around
FacturapiAdapter.request(), which does auth/retry/error-normalization.
Field names match Facturapi's v2 OpenAPI spec exactly (verified live
against docs.facturapi.io while building this) — see
integrations/providers/facturapi.py's module docstring for the
specific facts checked.

dry_run (Simulation Mode or an explicit preview) NEVER calls Facturapi
— that would create a real customer/product/invoice, which for
`facturapi.invoice.create` means emitting a real CFDI. Each handler
below short-circuits into a predicted result_metadata instead.
"""
from __future__ import annotations

from ..base import ActionContext, ActionResult


def _adapter(ctx: ActionContext):
    return ctx.dep("facturapi_adapter")


# ── Customers ────────────────────────────────────────────────────────

async def customer_create(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"legal_name": input.get("legal_name")}})
    body = {
        "legal_name": input["legal_name"],
        "tax_id": input["tax_id"],
        "tax_system": input["tax_system"],
        "address": input["address"],
    }
    if input.get("email"):
        body["email"] = input["email"]
    if input.get("phone"):
        body["phone"] = input["phone"]
    resp = await _adapter(ctx).request(ctx.workspace_id, "POST", "/customers", json=body)
    return ActionResult(status="succeeded", result_metadata={"customer_id": resp.get("id"), "legal_name": resp.get("legal_name")}, provider_request_id=resp.get("id"))


async def customer_get(ctx: ActionContext, input: dict) -> ActionResult:
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", f"/customers/{input['customer_id']}")
    return ActionResult(status="succeeded", result_metadata=resp)


async def customer_list(ctx: ActionContext, input: dict) -> ActionResult:
    params = {k: v for k, v in {"q": input.get("q"), "page": input.get("page")}.items() if v is not None}
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", "/customers", params=params)
    return ActionResult(status="succeeded", result_metadata=resp)


# ── Products ─────────────────────────────────────────────────────────

async def product_create(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"description": input.get("description")}})
    body = {
        "description": input["description"],
        "product_key": input["product_key"],
        "unit_key": input["unit_key"],
        "price": input["price"],
    }
    for optional in ("tax_included", "taxability", "sku"):
        if optional in input:
            body[optional] = input[optional]
    resp = await _adapter(ctx).request(ctx.workspace_id, "POST", "/products", json=body)
    return ActionResult(status="succeeded", result_metadata={"product_id": resp.get("id"), "description": resp.get("description")}, provider_request_id=resp.get("id"))


async def product_get(ctx: ActionContext, input: dict) -> ActionResult:
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", f"/products/{input['product_id']}")
    return ActionResult(status="succeeded", result_metadata=resp)


async def product_list(ctx: ActionContext, input: dict) -> ActionResult:
    params = {k: v for k, v in {"q": input.get("q"), "page": input.get("page")}.items() if v is not None}
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", "/products", params=params)
    return ActionResult(status="succeeded", result_metadata=resp)


# ── Invoices ─────────────────────────────────────────────────────────
# facturapi.invoice.create is HIGH risk (emits a real CFDI in Live) —
# see actions/bootstrap.py's risk_level for this action and
# server.py's action_policies default (no auto-approve override).

async def invoice_create(ctx: ActionContext, input: dict) -> ActionResult:
    if ctx.dry_run:
        return ActionResult(
            status="simulated",
            result_metadata={"predicted": {"customer": input.get("customer"), "items": input.get("items")}},
        )
    body = {
        "customer": input["customer"],
        "items": input["items"],
        "payment_form": input["payment_form"],
        "use": input["use"],
    }
    for optional in ("payment_method", "currency", "exchange", "status", "series", "folio_number"):
        if optional in input:
            body[optional] = input[optional]
    resp = await _adapter(ctx).request(ctx.workspace_id, "POST", "/invoices", json=body)
    return ActionResult(
        status="succeeded",
        result_metadata={"invoice_id": resp.get("id"), "uuid": resp.get("uuid"), "total": resp.get("total"), "status": resp.get("status")},
        provider_request_id=resp.get("id"),
    )


async def invoice_get(ctx: ActionContext, input: dict) -> ActionResult:
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", f"/invoices/{input['invoice_id']}")
    return ActionResult(status="succeeded", result_metadata=resp)


async def invoice_list(ctx: ActionContext, input: dict) -> ActionResult:
    params = {k: v for k, v in {"q": input.get("q"), "page": input.get("page")}.items() if v is not None}
    resp = await _adapter(ctx).request(ctx.workspace_id, "GET", "/invoices", params=params)
    return ActionResult(status="succeeded", result_metadata=resp)


async def invoice_cancel(ctx: ActionContext, input: dict) -> ActionResult:
    # CRITICAL risk (see bootstrap.py) — cancelling a CFDI has fiscal
    # consequences and, per Facturapi's docs, may require the receiving
    # customer's confirmation (cancellation_status: "pending").
    if ctx.dry_run:
        return ActionResult(status="simulated", result_metadata={"predicted": {"invoice_id": input.get("invoice_id"), "motive": input.get("motive")}})
    params = {"motive": input["motive"]}
    if input.get("substitution"):
        params["substitution"] = input["substitution"]
    resp = await _adapter(ctx).request(ctx.workspace_id, "DELETE", f"/invoices/{input['invoice_id']}", params=params)
    return ActionResult(
        status="succeeded",
        result_metadata={"invoice_id": resp.get("id"), "status": resp.get("status"), "cancellation_status": resp.get("cancellation_status")},
    )
