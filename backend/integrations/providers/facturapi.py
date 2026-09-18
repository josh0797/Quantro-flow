"""
Facturapi adapter — real integration with https://www.facturapi.io/v2
(CFDI México). Endpoints/fields/webhook events below were verified
directly against Facturapi's published OpenAPI spec
(docs.facturapi.io/redocusaurus/api-es.yaml) on the day this was
written — nothing here is guessed.

Key facts that shaped this file:
  * Auth is `Authorization: Bearer <secret_key>` (NOT Basic auth).
    Key prefix tells you the environment: `sk_test_...` / `sk_live_...`
    — there is no separate "environment" field anywhere in the API to
    check instead, so the prefix IS the source of truth.
  * `GET /organizations/me` returns the org profile — `is_production_ready`,
    `timezone`, `legal.legal_name` are the fields we persist.
  * `POST /webhooks` returns a `secret` (format `wh_sec_...`) used to
    verify the `Facturapi-Signature` header via
    `POST /webhooks/validate-signature`. That Facturapi-side secret is
    defense in depth; our PRIMARY defense (per the task spec) is the
    random high-entropy `webhook_token` embedded in the URL path we
    register, which Facturapi's docs don't know anything about.
  * The 7 webhook events in `enabled_events` below are exactly the enum
    Facturapi's spec accepts — do not add events that aren't in that
    enum, `POST /webhooks` will reject the request.
"""
from __future__ import annotations

import secrets as _secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from errors import QuantroError
from ..base import (
    AuthType,
    ConnectionStatus,
    ProviderAccount,
    ProviderAdapter,
    ProviderStatus,
)
from ..secrets import decrypt_secret, encrypt_secret, redact_error_text

try:
    import connect_store
except ImportError:  # pragma: no cover — script / partial path
    connect_store = None  # type: ignore

FACTURAPI_BASE = "https://www.facturapi.io/v2"

# Verbatim from Facturapi's WebhookCreateInput.enabled_events enum.
FACTURAPI_WEBHOOK_EVENTS: List[str] = [
    "invoice.global_invoice_created",
    "invoice.status_updated",
    "invoice.created_from_dashboard",
    "invoice.cancellation_status_updated",
    "receipt.self_invoice_complete",
    "receipt.status_updated",
    "receipt.cancellation_status_updated",
]

BackendPublicUrlFn = Callable[[], Optional[str]]


def infer_environment(secret_key: str) -> str:
    if secret_key.startswith("sk_live_"):
        return "live"
    if secret_key.startswith("sk_test_"):
        return "test"
    raise QuantroError(
        "invalid_credentials",
        "A Facturapi secret key must start with sk_test_ or sk_live_",
    )


class FacturapiAdapter(ProviderAdapter):
    provider_id = "facturapi"
    name = "Facturapi — CFDI México"
    category = "fiscal"
    description = "Fiscal invoicing (CFDI) for Mexico — customers, products, invoices."
    auth_type = AuthType.API_KEY
    supports_sync = False
    supports_webhooks = True
    supports_test_mode = True
    configuration_schema = {
        "secret_key": {
            "type": "string", "secret": True, "required": True,
            "help": "Test or Live secret key from your Facturapi dashboard",
        },
    }

    def __init__(self, col, webhook_events_col, backend_public_url_fn: BackendPublicUrlFn, log_audit_fn=None):
        self.col = col
        self.webhook_events_col = webhook_events_col
        self._backend_public_url_fn = backend_public_url_fn
        self._log_audit = log_audit_fn  # optional async fn(event_type, description, **kw)

    # ── internal HTTP helpers ────────────────────────────────────────
    def _client(self, secret_key: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=FACTURAPI_BASE,
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=15.0,
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise QuantroError("invalid_credentials", "Facturapi rejected this secret key")
        if resp.status_code == 429:
            raise QuantroError("rate_limited", "Facturapi rate limit reached — try again shortly")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message") or resp.text
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise QuantroError(
                "provider_error",
                "Facturapi returned an error",
                extra={"status": resp.status_code, "detail": redact_error_text(detail)},
            )

    async def _get_secret_key(self, workspace_id: str) -> Optional[str]:
        doc = await self._load_connection(workspace_id=workspace_id)
        if not doc:
            return None
        return decrypt_secret(doc.get("secret_key_encrypted"))

    async def _load_connection(
        self,
        *,
        workspace_id: Optional[str] = None,
        connection_id: Optional[str] = None,
        projection: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if connect_store is None:
            if connection_id:
                return await self.col.find_one({"connection_id": connection_id}, projection)
            return await self.col.find_one({"workspace_id": workspace_id}, projection)
        return await connect_store.get_facturapi_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
            mongo_col=self.col,
            projection=projection,
        )

    async def _persist_connection(self, workspace_id: str, fields: Dict[str, Any], *, upsert: bool = True) -> None:
        if connect_store is None:
            if upsert:
                await self.col.update_one({"workspace_id": workspace_id}, {"$set": fields}, upsert=True)
            else:
                await self.col.update_one({"workspace_id": workspace_id}, {"$set": fields})
            return
        if upsert:
            await connect_store.upsert_facturapi_connection(
                workspace_id=workspace_id, mongo_col=self.col, fields=fields,
            )
        else:
            await connect_store.patch_facturapi_connection(
                workspace_id=workspace_id, mongo_col=self.col, fields=fields,
            )

    async def request(
        self, workspace_id: str, method: str, path: str,
        json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Public entry point for Action handlers (facturapi.customer.*,
        facturapi.product.*, facturapi.invoice.*) — resolves the
        workspace's stored secret key, makes the call, raises a
        QuantroError with a normalized code on any non-2xx response, and
        returns the parsed JSON body on success. GET requests get one
        controlled retry on 429/5xx per the task spec's rate-limit
        section; POST/DELETE do not (idempotency is the caller's job)."""
        secret_key = await self._get_secret_key(workspace_id)
        if not secret_key:
            raise QuantroError("provider_not_connected", "Facturapi is not connected for this workspace")

        attempts = 2 if method.upper() == "GET" else 1
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                async with self._client(secret_key) as client:
                    resp = await client.request(method, path, json=json, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                continue
            self._raise_for_status(resp)
            return resp.json() if resp.content else {}
        raise QuantroError(
            "provider_unavailable", "Could not reach Facturapi",
            extra={"detail": redact_error_text(str(last_exc)) if last_exc else "unknown"},
        )

    # ── ProviderAdapter interface ────────────────────────────────────
    async def get_status(self, workspace_id: str) -> ProviderStatus:
        doc = await self._load_connection(
            workspace_id=workspace_id,
            projection={"_id": 0, "secret_key_encrypted": 0},
        )
        if not doc:
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.DISCONNECTED)
        status = ConnectionStatus.ERROR if doc.get("status") == "error" else ConnectionStatus.CONNECTED
        return ProviderStatus(
            provider_id=self.provider_id,
            status=status,
            account=ProviderAccount(
                id=doc.get("organization_id"),
                label=doc.get("legal_name"),
                extra={
                    "environment": doc.get("environment"),
                    "is_production_ready": doc.get("is_production_ready"),
                    "timezone": doc.get("timezone"),
                },
            ),
            capabilities=["fiscal.invoicing"],
            actions_available=self.get_actions(),
            error=doc.get("last_error"),
        )

    async def connect(self, workspace_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        secret_key = ((payload or {}).get("secret_key") or "").strip()
        if not secret_key:
            raise QuantroError("invalid_input", "secret_key is required")
        environment = infer_environment(secret_key)

        async with self._client(secret_key) as client:
            try:
                resp = await client.get("/organizations/me")
            except httpx.HTTPError as exc:
                raise QuantroError(
                    "provider_unavailable", "Could not reach Facturapi",
                    extra={"detail": redact_error_text(str(exc))},
                ) from exc
        self._raise_for_status(resp)
        org = resp.json()
        legal = org.get("legal") or {}

        now = datetime.now(timezone.utc)
        existing = await self._load_connection(
            workspace_id=workspace_id, projection={"connection_id": 1},
        )
        connection_id = (existing or {}).get("connection_id") or str(uuid.uuid4())

        doc: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "connection_id": connection_id,
            "environment": environment,
            "secret_key_encrypted": encrypt_secret(secret_key),
            "organization_id": org.get("id"),
            "legal_name": legal.get("legal_name") or legal.get("name"),
            "is_production_ready": bool(org.get("is_production_ready")),
            "timezone": org.get("timezone"),
            "status": "connected",
            "last_error": None,
            "updated_at": now,
        }
        if not existing:
            # Full doc check for connected_at (projection may omit fields).
            full_existing = await self._load_connection(workspace_id=workspace_id)
            if not full_existing:
                doc["connected_at"] = now
            elif not full_existing.get("connected_at"):
                doc["connected_at"] = now
        await self._persist_connection(workspace_id, doc, upsert=True)

        webhook_result = await self._register_webhook(workspace_id, connection_id, secret_key)

        if self._log_audit:
            await self._log_audit(
                "integration.connected",
                f"Facturapi connected ({environment})",
                workspace_id=workspace_id,
                metadata={"provider": "facturapi", "environment": environment},
            )

        return {
            "success": True,
            "environment": environment,
            "organization_id": org.get("id"),
            "legal_name": doc["legal_name"],
            "is_production_ready": doc["is_production_ready"],
            "webhook_registered": webhook_result.get("registered", False),
        }

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        doc = await self._load_connection(workspace_id=workspace_id)
        if not doc:
            return {"success": True, "already": "disconnected"}

        secret_key = decrypt_secret(doc.get("secret_key_encrypted"))
        webhook_id = doc.get("webhook_id")
        if secret_key and webhook_id:
            try:
                async with self._client(secret_key) as client:
                    await client.delete(f"/webhooks/{webhook_id}")
            except httpx.HTTPError:
                pass  # best-effort — local delete still proceeds

        if connect_store is None:
            await self.col.delete_one({"workspace_id": workspace_id})
        else:
            await connect_store.delete_facturapi_connection(
                workspace_id=workspace_id, mongo_col=self.col,
            )
        if self._log_audit:
            await self._log_audit(
                "integration.disconnected", "Facturapi disconnected",
                workspace_id=workspace_id, metadata={"provider": "facturapi"},
            )
        return {"success": True}

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        secret_key = await self._get_secret_key(workspace_id)
        if not secret_key:
            raise QuantroError("provider_not_connected", "Facturapi is not connected for this workspace")
        async with self._client(secret_key) as client:
            try:
                resp = await client.get("/organizations/me")
            except httpx.HTTPError as exc:
                await self._persist_connection(
                    workspace_id,
                    {"status": "error", "last_error": redact_error_text(str(exc))},
                    upsert=False,
                )
                return {"success": False, "message": "Could not reach Facturapi"}
        if resp.status_code == 401:
            await self._persist_connection(
                workspace_id,
                {"status": "error", "last_error": "Invalid credentials"},
                upsert=False,
            )
            return {"success": False, "message": "Facturapi rejected the stored secret key"}
        if resp.status_code >= 400:
            return {"success": False, "message": f"Facturapi returned HTTP {resp.status_code}"}
        org = resp.json()
        await self._persist_connection(
            workspace_id,
            {"status": "connected", "last_error": None},
            upsert=False,
        )
        legal = org.get("legal") or {}
        return {"success": True, "message": f"Connected to {legal.get('legal_name') or legal.get('name') or org.get('id')}"}

    def get_actions(self) -> List[str]:
        return [
            "facturapi.customer.create",
            "facturapi.customer.get",
            "facturapi.customer.list",
            "facturapi.product.create",
            "facturapi.product.get",
            "facturapi.product.list",
            "facturapi.invoice.create",
            "facturapi.invoice.get",
            "facturapi.invoice.list",
            "facturapi.invoice.cancel",
        ]

    # ── Webhooks ──────────────────────────────────────────────────────
    async def _register_webhook(self, workspace_id: str, connection_id: str, secret_key: str) -> Dict[str, Any]:
        backend_url = self._backend_public_url_fn()
        if not backend_url:
            return {"registered": False, "reason": "BACKEND_PUBLIC_URL not configured"}

        webhook_token = _secrets.token_urlsafe(32)
        callback_url = f"{backend_url.rstrip('/')}/api/webhooks/facturapi/{connection_id}/{webhook_token}"

        async with self._client(secret_key) as client:
            try:
                resp = await client.post(
                    "/webhooks",
                    json={"enabled_events": FACTURAPI_WEBHOOK_EVENTS, "url": callback_url},
                )
            except httpx.HTTPError as exc:
                return {"registered": False, "reason": redact_error_text(str(exc))}
        if resp.status_code >= 400:
            return {"registered": False, "reason": f"HTTP {resp.status_code}"}

        body = resp.json()
        await self._persist_connection(
            workspace_id,
            {
                "webhook_id": body.get("id"),
                "webhook_token_encrypted": encrypt_secret(webhook_token),
                # Facturapi-issued signing secret (may be absent depending on
                # API version) — used for defense-in-depth signature checks
                # in handle_webhook(); our own webhook_token above is the
                # primary defense regardless of whether this is present.
                "webhook_signing_secret_encrypted": (
                    encrypt_secret(body.get("secret")) if body.get("secret") else None
                ),
            },
            upsert=False,
        )
        return {"registered": True, "webhook_id": body.get("id")}

    async def handle_webhook(
        self, connection_id: str, webhook_token: str, raw_body: bytes, signature_header: Optional[str],
    ) -> Dict[str, Any]:
        """Process one inbound Facturapi webhook POST. Returns a dict the
        caller (the FastAPI route) turns straight into the HTTP response.
        Never raises for "this looked like an attack" cases — those are
        just reported as {"accepted": False, ...} with a 2xx-safe shape
        so Facturapi doesn't retry-storm us; genuine infra errors bubble
        as QuantroError.
        """
        doc = await self._load_connection(connection_id=connection_id)
        if not doc:
            return {"accepted": False, "reason": "unknown_connection"}

        stored_token = decrypt_secret(doc.get("webhook_token_encrypted"))
        if not stored_token or not _secrets.compare_digest(stored_token, webhook_token):
            return {"accepted": False, "reason": "invalid_token"}

        import json as _json
        try:
            payload = _json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"accepted": False, "reason": "invalid_json"}

        event_id = payload.get("id")
        event_type = payload.get("type")
        if not event_id or not event_type:
            return {"accepted": False, "reason": "malformed_event"}

        # Defense in depth: verify the Facturapi-Signature header via
        # their own validate-signature endpoint, when we have a signing
        # secret to check it against. Failure here does NOT block
        # processing — our webhook_token already proved the request came
        # through the URL only we and Facturapi know — but it's recorded
        # for audit visibility.
        signature_valid: Optional[bool] = None
        signing_secret = decrypt_secret(doc.get("webhook_signing_secret_encrypted"))
        secret_key = decrypt_secret(doc.get("secret_key_encrypted"))
        if signing_secret and signature_header and secret_key:
            try:
                async with self._client(secret_key) as client:
                    vr = await client.post(
                        "/webhooks/validate-signature",
                        json={"secret": signing_secret, "payload": payload, "signature": signature_header},
                    )
                signature_valid = vr.status_code < 400
            except httpx.HTTPError:
                signature_valid = None

        # Idempotent dedup on Facturapi's own event id.
        workspace_id = doc["workspace_id"]
        if connect_store is None:
            existing = await self.webhook_events_col.find_one({"event_id": event_id})
        else:
            existing = await connect_store.find_webhook_event(
                provider="facturapi",
                event_id=event_id,
                mongo_col=self.webhook_events_col,
            )
        if existing:
            if self._log_audit:
                await self._log_audit(
                    "facturapi.webhook.duplicate", f"Duplicate Facturapi event {event_type}",
                    workspace_id=workspace_id, metadata={"event_id": event_id, "event_type": event_type},
                )
            return {"accepted": True, "duplicate": True}

        event_doc = {
            "event_id": event_id,
            "workspace_id": workspace_id,
            "connection_id": connection_id,
            "event_type": event_type,
            "livemode": bool(payload.get("livemode")),
            "signature_valid": signature_valid,
            "received_at": datetime.now(timezone.utc),
            "payload_summary": _summarize_event(payload),
        }
        if connect_store is None:
            await self.webhook_events_col.insert_one(event_doc)
        else:
            await connect_store.insert_webhook_event(
                provider="facturapi",
                mongo_col=self.webhook_events_col,
                doc=event_doc,
            )

        if self._log_audit:
            await self._log_audit(
                "facturapi.webhook.received", f"Facturapi event {event_type}",
                workspace_id=workspace_id,
                metadata={"event_id": event_id, "event_type": event_type, "signature_valid": signature_valid},
            )
            await self._log_audit(
                "facturapi.webhook.processed", f"Facturapi event {event_type} processed",
                workspace_id=workspace_id, metadata={"event_id": event_id, "event_type": event_type},
            )

        return {"accepted": True, "duplicate": False}


def _summarize_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only non-sensitive, small identifiers from the event body for
    the audit trail — never the full payload (could contain customer PII
    like tax_id/email on an invoice.* event)."""
    data = payload.get("data") or {}
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "cancellation_status": data.get("cancellation_status"),
    }
