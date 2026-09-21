"""
Quantro OS invoicing adapter ("Facturación").

Flow never talks to a fiscal provider (Facturapi/etc.) directly and never
issues CFDI. Quantro OS is the fiscal source of truth; this adapter only
queries invoices OS has already processed (service-to-service) so Flow
can answer inbound email requests and prepare Gmail/Outlook reply payloads.

Env (server-side only — never exposed to the browser):
  QUANTRO_OS_API_URL      e.g. https://os.quantroflow.cloud
  QUANTRO_OS_SERVICE_TOKEN  bearer token for Flow → OS calls
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from errors import QuantroError
from ..base import (
    AuthType,
    ConnectionStatus,
    ProviderAccount,
    ProviderAdapter,
    ProviderStatus,
)


def is_os_invoicing_configured() -> bool:
    return bool(
        (os.environ.get("QUANTRO_OS_API_URL") or "").strip()
        and (os.environ.get("QUANTRO_OS_SERVICE_TOKEN") or "").strip()
    )


def _os_base() -> str:
    return (os.environ.get("QUANTRO_OS_API_URL") or "").strip().rstrip("/")


def _os_token() -> str:
    return (os.environ.get("QUANTRO_OS_SERVICE_TOKEN") or "").strip()


class QuantroInvoicingAdapter(ProviderAdapter):
    provider_id = "quantro_invoicing"
    name = "Facturación"
    category = "fiscal"
    description = (
        "Consulta facturas ya procesadas en Quantro OS y prepara respuestas "
        "por correo. Flow no emite CFDI ni conoce el proveedor fiscal."
    )
    auth_type = AuthType.API_KEY
    supports_sync = False
    supports_webhooks = False
    supports_test_mode = False
    configuration_schema = {}  # service-to-service; no browser secrets

    def __init__(
        self,
        resolve_org_id: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
    ):
        # Flow workspaces are Mongo ids; Quantro OS invoices belong to a
        # Supabase organization. OS refuses any lookup that does not name an
        # organization (the service token is not a tenant), so the resolver
        # (server.workspace_to_org_id) is mandatory for real calls.
        self._resolve_org_id = resolve_org_id

    async def _organization_id(self, workspace_id: str) -> str:
        org_id = await self._resolve_org_id(workspace_id) if self._resolve_org_id else None
        if not org_id:
            raise QuantroError(
                "configuration_missing",
                "This workspace is not linked to a Quantro OS organization, so invoices cannot be looked up.",
                extra={"workspace_id": workspace_id},
            )
        return str(org_id)

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not is_os_invoicing_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                status=ConnectionStatus.CONFIGURATION_MISSING,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            status=ConnectionStatus.CONNECTED,
            account=ProviderAccount(label="Quantro OS"),
            capabilities=["invoice.query", "invoice.reply_prep"],
            actions_available=self.get_actions(),
        )

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        raise QuantroError(
            "invalid_input",
            "Facturación is managed via Quantro OS service credentials — nothing to disconnect per workspace.",
        )

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        if not is_os_invoicing_configured():
            return {
                "success": False,
                "message": "QUANTRO_OS_API_URL / QUANTRO_OS_SERVICE_TOKEN not configured",
            }
        try:
            await self.query_invoices(workspace_id, q="", limit=1)
            return {"success": True, "message": "Quantro OS invoicing reachable"}
        except QuantroError as exc:
            return {"success": False, "message": exc.message}

    def get_actions(self) -> List[str]:
        return [
            "quantro_invoicing.invoice.query",
            "quantro_invoicing.invoice.prepare_reply",
        ]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not is_os_invoicing_configured():
            raise QuantroError(
                "configuration_missing",
                "Quantro OS invoicing is not configured on this deployment",
            )
        url = f"{_os_base()}{path}"
        headers = {
            "Authorization": f"Bearer {_os_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as cx:
                r = await cx.request(method, url, headers=headers, params=params, json=json)
        except httpx.HTTPError as exc:
            raise QuantroError(
                "provider_unavailable",
                "Could not reach Quantro OS invoicing",
                extra={"error": str(exc)[:200]},
            ) from exc
        if r.status_code in (401, 403):
            raise QuantroError("invalid_credentials", "Quantro OS rejected the service token")
        if r.status_code == 404:
            raise QuantroError("invalid_input", "Invoice not found in Quantro OS")
        if r.status_code >= 400:
            raise QuantroError(
                "provider_error",
                "Quantro OS invoicing error",
                extra={"status": r.status_code, "body": (r.text or "")[:300]},
            )
        if not r.content:
            return {}
        return r.json()

    async def query_invoices(
        self,
        workspace_id: str,
        *,
        q: str = "",
        limit: int = 10,
        invoice_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Locate invoices Quantro OS already processed — metadata/docs only.

        Always tenant-scoped: OS filters by ``organization_id`` and rejects
        the call otherwise, so an unlinked workspace fails here, closed.
        """
        params: Dict[str, Any] = {
            "organization_id": await self._organization_id(workspace_id),
            "workspace_id": workspace_id,  # informational only (OS logs); not a scope
            "limit": max(1, min(int(limit or 10), 50)),
        }
        if q:
            params["q"] = q
        if invoice_id:
            params["invoice_id"] = invoice_id
        data = await self._request("GET", "/service-invoices", params=params)
        if isinstance(data, list):
            return {"invoices": data}
        if isinstance(data, dict):
            if "invoices" not in data and "items" in data:
                return {"invoices": data.get("items") or []}
            data.setdefault("invoices", data.get("invoices") or [])
            return data
        return {"invoices": []}

    async def prepare_reply_payload(
        self,
        workspace_id: str,
        *,
        invoice_id: Optional[str] = None,
        q: str = "",
        to: Optional[str] = None,
        channel: str = "gmail",
    ) -> Dict[str, Any]:
        """Build a Gmail/Outlook-ready reply body from OS invoice metadata.

        Flow does not attach fiscal secrets — only public/safe metadata
        and document URLs OS already exposed.
        """
        result = await self.query_invoices(
            workspace_id, q=q, limit=5, invoice_id=invoice_id,
        )
        invoices = result.get("invoices") or []
        if not invoices:
            raise QuantroError("invalid_input", "No matching invoice in Quantro OS")
        inv = invoices[0]
        uuid_or_id = inv.get("id") or inv.get("invoice_id") or invoice_id or ""
        folio = inv.get("folio") or inv.get("number") or uuid_or_id
        total = inv.get("total") or inv.get("amount")
        currency = inv.get("currency") or "MXN"
        status = inv.get("status") or "unknown"
        pdf_url = inv.get("pdf_url") or inv.get("document_url") or inv.get("pdf")
        xml_url = inv.get("xml_url") or inv.get("xml")
        customer = inv.get("customer_name") or inv.get("legal_name") or inv.get("customer") or ""

        lines = [
            f"Hola{(' ' + customer) if isinstance(customer, str) and customer else ''},",
            "",
            f"Encontramos tu factura {folio} (estado: {status}).",
        ]
        if total is not None:
            lines.append(f"Total: {total} {currency}.")
        if pdf_url:
            lines.append(f"PDF: {pdf_url}")
        if xml_url:
            lines.append(f"XML: {xml_url}")
        lines.extend(["", "Saludos,", "Quantro Flow"])
        body = "\n".join(lines)
        subject = f"Factura {folio}"
        channel = (channel or "gmail").lower().strip()
        if channel not in ("gmail", "outlook", "microsoft"):
            channel = "gmail"
        return {
            "channel": "outlook" if channel in ("outlook", "microsoft") else "gmail",
            "to": to or inv.get("customer_email") or inv.get("email"),
            "subject": subject,
            "body": body,
            "invoice": {
                "id": uuid_or_id,
                "folio": folio,
                "status": status,
                "total": total,
                "currency": currency,
                "pdf_url": pdf_url,
                "xml_url": xml_url,
            },
            # Action ids the executor can use next — Flow mail transport only.
            "suggested_action_id": (
                "microsoft.mail.send" if channel in ("outlook", "microsoft") else "google.gmail.send"
            ),
        }
