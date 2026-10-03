"""
Quantro OS invoicing adapter ("Facturación").

Flow never talks to a fiscal provider (Facturapi/etc.) directly and never
issues CFDI. Quantro OS is the fiscal source of truth; this adapter only
queries invoices OS has already processed (service-to-service) so Flow
can answer inbound email requests and prepare Gmail/Outlook reply payloads.

Env (server-side only — never exposed to the browser):
  QUANTRO_OS_API_URL      e.g. https://os.quantroflow.cloud
  QUANTRO_OS_SERVICE_TOKEN  bearer token for Flow → OS calls

Quantro OS contract (edge function ``service-invoices``)::

  GET {QUANTRO_OS_API_URL}/service-invoices
      ?organization_id=<OS org uuid>   required (400 organization_required)
      &invoice_id=<invoice uuid>       optional
      &q=<text>                        optional — invoice_number / client_name / client_email
      &limit=<n>
  → id, folio, total, currency, status, customer_name, customer_email,
    pdf_url, xml_url, date

OS knows nothing about Flow workspaces: a Flow workspace is translated to
its OS organization by the injected ``org_resolver`` (server.py passes
``workspace_to_org_id``). A workspace with no OS organization is never
sent to OS — it is reported as "not linked to a Quantro organization".
"""
from __future__ import annotations

import os
import uuid
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


# Flow workspace_id → Quantro OS organization id (or None when unlinked).
OrgResolver = Callable[[str], Awaitable[Optional[str]]]

NOT_LINKED_MESSAGE = "This workspace is not linked to a Quantro organization"
RECIPIENT_MISMATCH = "recipient_mismatch"


def _as_uuid(value: Any) -> Optional[str]:
    """Canonical UUID string, or None when ``value`` is not a UUID."""
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def _normalize_email(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


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

    def __init__(self, org_resolver: Optional[OrgResolver] = None):
        self._org_resolver = org_resolver

    async def organization_id(self, workspace_id: str) -> Optional[str]:
        """The workspace's Quantro OS organization id, or None if unlinked."""
        if self._org_resolver is None or not workspace_id:
            return None
        return _as_uuid(await self._org_resolver(workspace_id))

    async def _require_organization_id(self, workspace_id: str) -> str:
        org_id = await self.organization_id(workspace_id)
        if not org_id:
            raise QuantroError(
                "provider_not_connected",
                NOT_LINKED_MESSAGE,
                extra={"reason": "organization_not_linked"},
            )
        return org_id

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not is_os_invoicing_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                status=ConnectionStatus.CONFIGURATION_MISSING,
            )
        if not await self.organization_id(workspace_id):
            return ProviderStatus(
                provider_id=self.provider_id,
                status=ConnectionStatus.DISCONNECTED,
                error=NOT_LINKED_MESSAGE,
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
        if not await self.organization_id(workspace_id):
            return {"success": False, "message": NOT_LINKED_MESSAGE}
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

        Scoped to the workspace's OS organization; the Flow workspace id is
        never sent to OS. An unlinked workspace is refused before any call."""
        if not is_os_invoicing_configured():
            raise QuantroError(
                "configuration_missing",
                "Quantro OS invoicing is not configured on this deployment",
            )
        org_id = await self._require_organization_id(workspace_id)
        params: Dict[str, Any] = {
            "organization_id": org_id,
            "limit": max(1, min(int(limit or 10), 50)),
        }
        if q:
            params["q"] = q
        if invoice_id:
            canonical_invoice_id = _as_uuid(invoice_id)
            if not canonical_invoice_id:
                raise QuantroError(
                    "invalid_input",
                    "invoice_id must be a Quantro OS invoice id (UUID); use q to search by folio or customer",
                )
            params["invoice_id"] = canonical_invoice_id
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

        Never sends anything — it only builds the payload. Flow does not
        attach fiscal secrets — only public/safe metadata and document URLs
        OS already exposed.

        A reply is only prepared for an invoice whose ``customer_email``
        equals ``to`` (case-insensitive), so one customer's invoice can never
        be addressed to another person. Otherwise a structured refusal
        (``reason: "recipient_mismatch"``) is returned instead of a payload.
        """
        result = await self.query_invoices(
            workspace_id, q=q, limit=5, invoice_id=invoice_id,
        )
        invoices = result.get("invoices") or []
        if not invoices:
            raise QuantroError("invalid_input", "No matching invoice in Quantro OS")
        recipient = _normalize_email(to)
        inv = next(
            (i for i in invoices
             if isinstance(i, dict) and recipient and _normalize_email(i.get("customer_email")) == recipient),
            None,
        )
        if inv is None:
            return {
                "status": "refused",
                "reason": RECIPIENT_MISMATCH,
                "message": (
                    "No matching invoice belongs to this recipient: a reply is only prepared "
                    "when the recipient is the invoice's customer email"
                    if recipient else
                    "A recipient email is required: a reply is only prepared for the invoice's customer email"
                ),
                "to": to,
                "invoices_found": len(invoices),
            }
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
            "status": "ready",
            "channel": "outlook" if channel in ("outlook", "microsoft") else "gmail",
            "to": to.strip(),
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
