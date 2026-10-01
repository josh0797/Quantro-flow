"""AI billing — USD-credit accounting for Quantro Flow.

Mirrors the front-end helper in /app/frontend/src/lib/billing.js so the
UI never advertises a different bag of credits than what the backend
actually charges. Keep both files in lock-step on every change.

Responsibilities:
  * Define per-plan monthly credit allowance (`PLAN_CREDITS`). Essential
    includes no Quantro AI credits; Pro and Enterprise include $10 / $20.
  * Compute the real USD cost of an OpenAI request from token usage.
  * Decrement profiles.ai_credits_used (and recompute remaining) after
    each successful request, persisting one row in `ai_credit_usage`.
  * Decide which OpenAI API key to use for a request:
        - user_api: the WORKSPACE saved its own OpenAI key in
                    Settings → Integrations (integrations_config row for
                    provider 'openai', status 'connected', encrypted
                    api_key). It always wins: the customer chose to pay
                    OpenAI directly, so Quantro credits are never debited.
        - quantro:  no own key, internal credits remaining > 0
        - blocked:  neither
  * Expose a single ``run_ai_request`` wrapper that every AI endpoint
    must call instead of touching OpenAI directly (Emergent LLM path removed in Phase 0).

Own key ("conectar su propia API"), decided 2026-09-30:
  * Source of truth is the workspace's ``integrations_config`` row (see
    connect_store.py; the key is Fernet ciphertext from
    integrations/secrets.py, never returned to a browser). The legacy
    ``profiles.user_openai_api_key_encrypted`` / ``has_user_api_key``
    columns were never written by any code path and are ignored.
  * When the own key fails (invalid/revoked, no quota, model not
    available) the request fails with a clear message pointing the leader
    to Settings → Integrations. There is NO silent fallback to Quantro's
    key: the product never defined one, and falling back would spend
    Quantro credits on a workspace that chose to be billed by OpenAI.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal, List, Dict, Any, Tuple
import asyncio
import logging
import os

import httpx
from fastapi import HTTPException

logger = logging.getLogger("quantro.ai_billing")

# ---------- Constants (lock-step with billing.js) ----------
# Quantro AI credits (USD) included in each plan per month. Essential
# includes none: an Essential user only runs on Quantro's key while a
# balance already stored on their profile lasts (balances granted before
# this change are never clawed back); after that they are blocked with
# reason "plan_no_credits" and must upgrade.
PLAN_CREDITS = {
    "essential": 0.0,    # no Quantro AI credits included
    "pro": 10.0,         # $10 USD / month
    "enterprise": 20.0,  # $20 USD / month
}
TEST_USER_CREDITS = 20.0
TEST_USERS = {
    "josias.martin@hotmail.com",
    "josias.martin90@hotmail.com",
}

QUANTRO_FORCED_MODEL = "gpt-4o-mini"
MODEL_PRICING = {
    "gpt-4o-mini":  {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4o":       {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
}

CreditSource = Literal["quantro", "user_api", "blocked"]

# ---------- Workspace's own OpenAI key --------------------------------
OPENAI_PROVIDER = "openai"
# Models a workspace may pick for its own key (Settings → Integrations).
# Lock-step with OPENAI_MODEL_OPTIONS in frontend/src/lib/billing.js (the
# card's <select>; pinned by tests/test_own_openai_key.py). Every entry has
# a price in MODEL_PRICING so the informational cost logged for 'user_api'
# is real.
OWN_KEY_ALLOWED_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini")
# A saved model outside the allowlist (e.g. a legacy "gpt-4-turbo") falls
# back to this default instead of failing every request.
OWN_KEY_DEFAULT_MODEL = QUANTRO_FORCED_MODEL
OWN_KEY_REQUEST_TIMEOUT_S = 60.0
OWN_KEY_TEST_TIMEOUT_S = 10.0
INTEGRATIONS_SETTINGS_PATH = "/settings/integrations"

# ---------- Supabase config (REST via PostgREST) ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


@dataclass
class CreditsState:
    total: float
    used: float
    remaining: float
    has_own_api_key: bool
    source: CreditSource
    blocked: bool
    reason: str


@dataclass
class UsageRecord:
    """Row written to public.ai_credit_usage after a successful request."""
    user_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    provider: str = "openai"
    source: CreditSource = "quantro"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- Pure helpers ----------------------------------------------
def calculate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost of one OpenAI request from token usage.

    Returns 0.0 for unknown models so the request never fails over a
    pricing mismatch — but logs a warning so we notice in prod.
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        logger.warning("ai_billing: pricing missing for model=%s", model)
        return 0.0
    return (
        (max(0, int(input_tokens or 0)) / 1_000_000) * pricing["input_per_1m"]
        + (max(0, int(output_tokens or 0)) / 1_000_000) * pricing["output_per_1m"]
    )


def resolve_credits_state(
    email: Optional[str] = None,
    profile: Optional[dict] = None,
    own_key_active: bool = False,
) -> CreditsState:
    """Read the user's credits state from a Supabase profiles row.

    ``own_key_active`` is True when the workspace the request runs in has
    its own OpenAI key connected (see ``get_user_api_key``).

    Decision:
        1. workspace own OpenAI key           → source = "user_api"
                                                (always wins: OpenAI bills
                                                the customer, no Quantro
                                                credits are debited)
        2. has_coupon=true                    → no Quantro credits, must
                                                supply own API key
        3. profiles.ai_credits_remaining > 0  → source = "quantro"
        4. otherwise                          → source = "blocked"
                                                (reason "plan_no_credits"
                                                when the plan includes no
                                                Quantro credits, e.g.
                                                Essential)

    The legacy profile columns ``user_openai_api_key_encrypted`` /
    ``has_user_api_key`` are ignored: nothing ever wrote them, and a stray
    flag used to route to a key that could not be read.
    """
    profile = profile or {}
    lc_email = (email or "").lower().strip()
    is_test_user = bool(lc_email) and lc_email in TEST_USERS
    plan_key = (profile.get("plan") or "").lower()
    has_coupon = bool(profile.get("has_coupon"))
    plan_includes_no_credits = (
        not is_test_user
        and plan_key in PLAN_CREDITS
        and PLAN_CREDITS[plan_key] <= 0
    )

    base_total = (
        TEST_USER_CREDITS if is_test_user
        else float(PLAN_CREDITS.get(plan_key, 0.0))
    )
    # A stored total of 0/NULL falls back to the plan's included amount.
    # Essential's is 0, so this never grants Essential anything; Pro and
    # Enterprise keep their existing behaviour.
    total = float(profile.get("ai_credits_total") or base_total or 0.0)
    used = max(0.0, float(profile.get("ai_credits_used") or 0.0))
    remaining_raw = profile.get("ai_credits_remaining")
    remaining = (
        float(remaining_raw)
        if remaining_raw is not None
        else max(0.0, total - used)
    )
    remaining = max(0.0, remaining)
    has_own_api_key = bool(own_key_active)

    if has_own_api_key:
        return CreditsState(
            total=0.0 if has_coupon else total,
            used=used,
            remaining=0.0 if has_coupon else remaining,
            has_own_api_key=True,
            source="user_api", blocked=False, reason="workspace_openai_key",
        )

    # Coupon / trial users don't get Quantro credits — they MUST bring
    # their own OpenAI key.
    if has_coupon:
        return CreditsState(
            total=0.0, used=used, remaining=0.0,
            has_own_api_key=False,
            source="blocked", blocked=True, reason="coupon_no_user_key",
        )

    if remaining > 0:
        return CreditsState(
            total=total, used=used, remaining=remaining,
            has_own_api_key=False,
            source="quantro", blocked=False, reason="using_quantro_credits",
        )
    return CreditsState(
        total=total, used=used, remaining=remaining,
        has_own_api_key=False,
        source="blocked", blocked=True,
        reason=(
            "plan_no_credits" if plan_includes_no_credits
            else "no_credits_no_user_key"
        ),
    )


def get_quantro_api_key() -> Optional[str]:
    """Return Quantro's default OpenAI key from env, never logged."""
    return os.environ.get("OPENAI_API_KEY") or None


# ---------- Workspace own key: lookup ---------------------------------
# server.py registers its IntegrationsConfigCollection facade here at
# import time (the same object the /api/integrations routes use), so the
# lookup follows whatever storage flags are live. Without a registration
# (scripts, unit tests) a Supabase-only facade is used.
_integrations_store: Any = None


def register_integrations_store(col: Any) -> None:
    global _integrations_store
    _integrations_store = col


def _integrations_col(explicit: Any = None) -> Any:
    if explicit is not None:
        return explicit
    if _integrations_store is not None:
        return _integrations_store
    import connect_store  # local: keeps this module importable on its own

    return connect_store.IntegrationsConfigCollection(None)


def resolve_own_key_model(configured: Optional[str]) -> str:
    """The saved model when it is in the allowlist, else the default."""
    model = (configured or "").strip() if isinstance(configured, str) else ""
    return model if model in OWN_KEY_ALLOWED_MODELS else OWN_KEY_DEFAULT_MODEL


@dataclass(frozen=True)
class WorkspaceOpenAIKey:
    """A workspace's connected OpenAI key. ``api_key`` is None when a key is
    saved but cannot be decrypted (encryption key rotated/missing) — the
    caller must then ask the leader to save it again, not fall back."""
    workspace_id: str
    model: str
    configured_model: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)


class OwnKeyStoreUnavailable(Exception):
    """integrations_config could not be read; the key's presence is unknown."""


async def get_user_api_key(
    workspace_id: Optional[str],
    *,
    integrations_col: Any = None,
) -> Optional[WorkspaceOpenAIKey]:
    """Return the OpenAI key the given workspace connected in Settings →
    Integrations, decrypted server-side. Never logs or returns it anywhere
    else.

    None means "this workspace has no own key" (no row, not connected, or
    no ciphertext) → the Quantro-credits path applies. Raises
    ``OwnKeyStoreUnavailable`` when the store read fails, so a transient
    error never silently moves a BYOK workspace onto Quantro's key.
    """
    if not workspace_id:
        return None
    import connect_store
    from integrations import secrets as integration_secrets

    try:
        doc = await connect_store.get_integrations_config(
            workspace_id=workspace_id,
            provider=OPENAI_PROVIDER,
            mongo_col=_integrations_col(integrations_col),
            projection={"_id": 0},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ai_billing.get_user_api_key: integrations_config read failed (%s)",
            type(exc).__name__,
        )
        raise OwnKeyStoreUnavailable() from None

    if not doc:
        return None
    # Defense in depth: the store filtered on workspace_id already.
    if doc.get("workspace_id") != workspace_id or doc.get("provider") != OPENAI_PROVIDER:
        logger.error("ai_billing.get_user_api_key: store returned a row for another workspace/provider")
        return None
    if (doc.get("status") or "") != "connected":
        return None
    config = doc.get("config") or {}
    ciphertext = config.get("api_key")
    if not isinstance(ciphertext, str) or not ciphertext:
        return None

    configured_model = config.get("model") if isinstance(config.get("model"), str) else None
    try:
        api_key = integration_secrets.decrypt_secret(ciphertext)
    except Exception as exc:  # noqa: BLE001 — e.g. no encryption key configured
        logger.warning("ai_billing.get_user_api_key: decrypt failed (%s)", type(exc).__name__)
        api_key = None
    if not api_key:
        logger.warning(
            "ai_billing.get_user_api_key: workspace=%s has a connected OpenAI key that "
            "cannot be decrypted", workspace_id,
        )
    return WorkspaceOpenAIKey(
        workspace_id=workspace_id,
        model=resolve_own_key_model(configured_model),
        configured_model=configured_model,
        api_key=api_key or None,
    )


# ---------- Workspace own key: errors + connection test ---------------
_OWN_KEY_MESSAGES: Dict[str, Dict[str, str]] = {
    "ok": {
        "es": "Conexión con OpenAI verificada: la clave es válida y tiene acceso al modelo {model}.",
        "en": "OpenAI connection verified: the key is valid and can use the {model} model.",
    },
    "not_connected": {
        "es": "OpenAI no está conectado en este espacio de trabajo. Guarda una clave en Configuración → Integraciones.",
        "en": "OpenAI isn’t connected in this workspace. Save a key in Settings → Integrations.",
    },
    "own_key_unreadable": {
        "es": "No pudimos leer la clave de OpenAI guardada en este espacio de trabajo. Un líder debe volver a guardarla en Configuración → Integraciones.",
        "en": "We couldn’t read this workspace’s saved OpenAI key. A leader needs to save it again in Settings → Integrations.",
    },
    "own_key_invalid": {
        "es": "OpenAI rechazó la clave de este espacio de trabajo (inválida o revocada). Un líder debe actualizarla en Configuración → Integraciones.",
        "en": "OpenAI rejected this workspace’s key (invalid or revoked). A leader needs to update it in Settings → Integrations.",
    },
    "own_key_quota_exhausted": {
        "es": "La cuenta de OpenAI de este espacio de trabajo se quedó sin saldo o cuota. Un líder debe revisar la facturación en OpenAI o cambiar la clave en Configuración → Integraciones.",
        "en": "This workspace’s OpenAI account is out of credit or quota. A leader needs to check billing at OpenAI or change the key in Settings → Integrations.",
    },
    "own_key_model_not_allowed": {
        "es": "La clave de OpenAI de este espacio de trabajo no tiene acceso al modelo {model}. Un líder debe elegir otro modelo o cambiar la clave en Configuración → Integraciones.",
        "en": "This workspace’s OpenAI key can’t use the {model} model. A leader needs to pick another model or change the key in Settings → Integrations.",
    },
    "own_key_forbidden": {
        "es": "OpenAI denegó el acceso con la clave de este espacio de trabajo (permisos del proyecto o región no soportada). Un líder debe revisarla en Configuración → Integraciones.",
        "en": "OpenAI denied access for this workspace’s key (project permissions or unsupported region). A leader needs to review it in Settings → Integrations.",
    },
    "own_key_rate_limited": {
        "es": "OpenAI está limitando temporalmente las solicitudes con la clave de este espacio de trabajo. Intenta de nuevo en unos minutos.",
        "en": "OpenAI is temporarily rate-limiting requests made with this workspace’s key. Try again in a few minutes.",
    },
    "own_key_unreachable": {
        "es": "No pudimos contactar a OpenAI a tiempo con la clave de este espacio de trabajo. Intenta de nuevo en unos minutos.",
        "en": "We couldn’t reach OpenAI in time with this workspace’s key. Try again in a few minutes.",
    },
    "own_key_provider_error": {
        "es": "OpenAI devolvió un error al usar la clave de este espacio de trabajo. Intenta de nuevo; si persiste, revisa la clave en Configuración → Integraciones.",
        "en": "OpenAI returned an error for this workspace’s key. Try again; if it persists, review the key in Settings → Integrations.",
    },
    "store_unavailable": {
        "es": "No pudimos leer la configuración de IA de este espacio de trabajo. Intenta de nuevo en unos minutos.",
        "en": "We couldn’t read this workspace’s AI configuration. Try again in a few minutes.",
    },
    "invalid_openai_key_format": {
        "es": "Eso no parece una clave de API de OpenAI (empiezan con \"sk-\"). Cópiala de platform.openai.com → API keys.",
        "en": "That doesn’t look like an OpenAI API key (they start with \"sk-\"). Copy it from platform.openai.com → API keys.",
    },
    "openai_key_required": {
        "es": "Pega la clave de API de OpenAI para conectar la integración.",
        "en": "Paste the OpenAI API key to connect the integration.",
    },
    "model_not_allowed": {
        "es": "Elige uno de los modelos disponibles: {models}.",
        "en": "Pick one of the available models: {models}.",
    },
}


def own_key_message(reason: str, language: str = "es", model: Optional[str] = None) -> str:
    lang = "en" if (language or "").lower().startswith("en") else "es"
    entry = _OWN_KEY_MESSAGES.get(reason) or _OWN_KEY_MESSAGES["own_key_provider_error"]
    return entry[lang].format(
        model=model or OWN_KEY_DEFAULT_MODEL,
        models=", ".join(OWN_KEY_ALLOWED_MODELS),
    )


def classify_openai_error(exc: BaseException) -> Tuple[str, int]:
    """Map an OpenAI SDK exception raised while using a workspace's own key
    to (reason, HTTP status for Flow's own response).

    Never 401: the frontend treats any 401 as an expired Quantro session
    and signs the user out (lib/authFetch.js, lib/api.js).
    """
    try:
        import openai
    except ImportError:  # pragma: no cover — requirements pin openai
        return "own_key_provider_error", 502
    code = getattr(exc, "code", None)
    err_type = getattr(exc, "type", None)
    if isinstance(exc, openai.AuthenticationError):
        return "own_key_invalid", 402
    if isinstance(exc, openai.RateLimitError):
        if "insufficient_quota" in (code, err_type):
            return "own_key_quota_exhausted", 402
        return "own_key_rate_limited", 429
    if isinstance(exc, openai.NotFoundError) or code == "model_not_found":
        return "own_key_model_not_allowed", 402
    if isinstance(exc, openai.PermissionDeniedError):
        return "own_key_forbidden", 402
    if isinstance(exc, openai.APITimeoutError) or isinstance(exc, asyncio.TimeoutError):
        return "own_key_unreachable", 504
    if isinstance(exc, openai.APIConnectionError):
        return "own_key_unreachable", 502
    return "own_key_provider_error", 502


def own_key_http_error(reason: str, status_code: int, language: str, model: Optional[str] = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": "ai_own_key_error",
            "reason": reason,
            "source": "user_api",
            "message": own_key_message(reason, language, model),
            "settings_path": INTEGRATIONS_SETTINGS_PATH,
        },
    )


def _make_openai_client(api_key: str, **kwargs: Any) -> Any:
    """Single construction point for the OpenAI client (lazy import keeps
    cold-start fast; tests replace this function to mock OpenAI)."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI SDK missing: {exc}")
    return AsyncOpenAI(api_key=api_key, **kwargs)


async def _close_client(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001
        pass


async def check_openai_key(
    api_key: str,
    model: str,
    *,
    timeout: float = OWN_KEY_TEST_TIMEOUT_S,
) -> Tuple[bool, Optional[str]]:
    """Real, cheap check of a workspace key: retrieve the chosen model.

    Proves the key is valid and can use that model without spending
    tokens. It cannot detect an exhausted quota (listing models is free);
    that surfaces as ``own_key_quota_exhausted`` on the first AI request.
    Returns (ok, reason) and never raises.
    """
    client = None
    try:
        client = _make_openai_client(api_key, timeout=timeout, max_retries=0)
        await asyncio.wait_for(client.models.retrieve(model), timeout=timeout + 2)
        return True, None
    except Exception as exc:  # noqa: BLE001
        reason, _status = classify_openai_error(exc)
        logger.info("ai_billing.check_openai_key failed reason=%s (%s)", reason, type(exc).__name__)
        return False, reason
    finally:
        if client is not None:
            await _close_client(client)


def format_block_message(language: str = "es", reason: str = "") -> str:
    """User-facing copy returned with HTTP 402 when AI is blocked."""
    if reason == "coupon_no_user_key":
        if language == "en":
            return (
                "Trial accounts don’t include Quantro AI credits. "
                "A leader can connect the workspace’s own OpenAI API key in "
                "Settings → Integrations to use AI features."
            )
        return (
            "Las cuentas de prueba no incluyen créditos de Quantro IA. "
            "Un líder puede conectar la clave de OpenAI del espacio de trabajo en "
            "Configuración → Integraciones para usar las funciones inteligentes."
        )
    if reason == "plan_no_credits":
        if language == "en":
            return (
                "Your plan doesn’t include Quantro AI credits. "
                "Upgrade to Pro, or have a leader connect the workspace’s own OpenAI key "
                "in Settings → Integrations, to use smart features."
            )
        return (
            "Tu plan no incluye créditos IA de Quantro. "
            "Actualiza a Pro, o pide a un líder que conecte la clave de OpenAI del espacio "
            "de trabajo en Configuración → Integraciones, para usar las funciones inteligentes."
        )
    if language == "en":
        return (
            "You’ve used up your Quantro AI credits for this cycle. "
            "A leader can connect the workspace’s own OpenAI key in "
            "Settings → Integrations to keep using smart features, or upgrade your plan."
        )
    return (
        "Se acabaron tus créditos IA de Quantro este ciclo. "
        "Un líder puede conectar la clave de OpenAI del espacio de trabajo en "
        "Configuración → Integraciones para seguir usando las funciones "
        "inteligentes, o actualiza tu plan."
    )


# ---------- Supabase REST helpers (httpx) ----------------------------
def _user_headers(access_token: str) -> Dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _service_headers() -> Dict[str, str]:
    if not SUPABASE_SERVICE_ROLE_KEY:
        return {}
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


async def fetch_profile(user_id: str, access_token: str) -> Dict[str, Any]:
    """Fetch the caller's row from public.profiles via PostgREST.

    Uses the user's own JWT (RLS policy: ``auth.uid() = id``). Returns
    an empty dict if Supabase is unreachable or the row doesn't exist
    yet; ``resolve_credits_state`` already handles the empty case.
    """
    if not SUPABASE_URL or not user_id or not access_token:
        return {}
    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=_user_headers(access_token))
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return data[0]
        else:
            logger.warning(
                "ai_billing.fetch_profile non-200 status=%s body=%s",
                r.status_code, r.text[:200],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_billing.fetch_profile failed: %s", exc)
    return {}


async def rpc_decrement_credits(
    user_id: str,
    amount: float,
    access_token: str,
) -> None:
    """Atomically deduct ``amount`` USD from profiles.ai_credits_used
    via the ``decrement_ai_credits`` Postgres function.

    The RPC is granted to ``authenticated`` so the user's own JWT is
    sufficient — no service-role key required. Best-effort: failures
    must never break the user's request.
    """
    cost = max(0.0, float(amount or 0.0))
    if cost == 0.0 or not SUPABASE_URL or not user_id or not access_token:
        return
    url = f"{SUPABASE_URL}/rest/v1/rpc/decrement_ai_credits"
    payload = {"p_user_id": user_id, "p_amount": cost}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, headers=_user_headers(access_token), json=payload)
        if r.status_code >= 400:
            logger.warning(
                "ai_billing.rpc_decrement_credits non-2xx status=%s body=%s",
                r.status_code, r.text[:200],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_billing.rpc_decrement_credits failed: %s", exc)


async def insert_credit_usage(
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    source: CreditSource,
    access_token: Optional[str] = None,
    provider: str = "openai",
) -> None:
    """Append a row to public.ai_credit_usage. RLS only allows
    service_role inserts, so we prefer the service key when present.
    Falls back to the user JWT (will fail RLS) — both paths are
    best-effort and never raise.
    """
    if not SUPABASE_URL or not user_id:
        return
    url = f"{SUPABASE_URL}/rest/v1/ai_credit_usage"
    payload = {
        "user_id": user_id,
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_usd": float(cost_usd or 0.0),
        "provider": provider,
        # Map our internal label to the DB constraint values.
        "source": "quantro_api" if source == "quantro" else "user_api",
    }

    headers_attempts: List[Dict[str, str]] = []
    svc = _service_headers()
    if svc:
        headers_attempts.append(svc)
    if access_token:
        headers_attempts.append(_user_headers(access_token))

    for headers in headers_attempts:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(url, headers=headers, json=payload)
            if r.status_code < 400:
                return
            logger.info(
                "ai_billing.insert_credit_usage status=%s body=%s",
                r.status_code, r.text[:200],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_billing.insert_credit_usage failed: %s", exc)
            continue


# ---------- Main wrapper ---------------------------------------------
async def run_ai_request(
    *,
    user_id: str,
    email: Optional[str],
    access_token: Optional[str],
    system_prompt: str,
    user_prompt: str,
    model_requested: Optional[str] = None,
    language: str = "es",
    response_format: Optional[Dict[str, Any]] = None,
    temperature: Optional[float] = None,
    workspace_id: Optional[str] = None,
    integrations_col: Any = None,
) -> Dict[str, Any]:
    """Single entry point for every AI endpoint in Quantro Flow.

    Enforces the AI Credits policy:
      * If the workspace (``workspace_id``, the active workspace of the
        request) connected its own OpenAI key, the request runs on that
        key with the model saved in Settings → Integrations (allowlisted,
        else the default). Quantro credits are NOT debited; usage is
        logged with source 'user_api'. Key errors surface as a clear
        ``ai_own_key_error`` — never a silent fallback to Quantro's key.
      * Otherwise reads the user's profile from Supabase (RLS-safe, user
        JWT). Trial / coupon users need the workspace's own key (0
        Quantro credits). On Quantro credits the model is FORCED to
        ``gpt-4o-mini`` and the real USD cost is deducted from the bag.

    Raises HTTPException(402) when the user is blocked (no credits and
    no own key) or when the workspace's own key is unusable.

    Returns a dict ``{"text": str, "model": str, "usage": {...},
    "source": "quantro" | "user_api"}`` so callers can pipe ``text``
    into their JSON-parsing logic just like before.
    """
    # 1. The workspace's own OpenAI key wins when connected.
    try:
        own_key = await get_user_api_key(workspace_id, integrations_col=integrations_col)
    except OwnKeyStoreUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "ai_unavailable",
                "reason": "ai_config_unavailable",
                "message": own_key_message("store_unavailable", language),
            },
        )
    if own_key is not None and not own_key.api_key:
        raise own_key_http_error("own_key_unreadable", 402, language, own_key.model)

    # 2. Resolve credits state (the profile only matters without an own key).
    profile: Dict[str, Any] = {}
    if own_key is None and access_token:
        profile = await fetch_profile(user_id, access_token)
    state = resolve_credits_state(email=email, profile=profile, own_key_active=own_key is not None)

    if state.blocked:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "ai_blocked",
                "reason": state.reason,
                "message": format_block_message(language, state.reason),
            },
        )

    # 3. Pick API key + model
    client_kwargs: Dict[str, Any] = {}
    if state.source == "user_api" and own_key is not None:
        api_key: Optional[str] = own_key.api_key
        model = own_key.model  # allowlisted in get_user_api_key; model_requested is ignored
        client_kwargs = {"timeout": OWN_KEY_REQUEST_TIMEOUT_S, "max_retries": 1}
    else:
        api_key = get_quantro_api_key()
        model = QUANTRO_FORCED_MODEL  # never let users escalate model on Quantro's dime

    if not api_key:
        # Quantro path but server has no env key configured.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "ai_unavailable",
                "message": "OpenAI API key is not configured on the server.",
            },
        )

    # 4. Call OpenAI
    client = _make_openai_client(api_key, **client_kwargs)
    openai_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if temperature is not None:
        openai_kwargs["temperature"] = temperature
    if response_format is not None:
        openai_kwargs["response_format"] = response_format

    try:
        response = await client.chat.completions.create(**openai_kwargs)
    except Exception as exc:  # noqa: BLE001
        if state.source == "user_api":
            from integrations.secrets import redact_error_text

            reason, status_code = classify_openai_error(exc)
            logger.warning(
                "ai_billing.run_ai_request own-key OpenAI call failed workspace=%s reason=%s err=%s",
                workspace_id, reason, redact_error_text(f"{type(exc).__name__}: {exc}"),
            )
            raise own_key_http_error(reason, status_code, language, model)
        logger.exception("ai_billing.run_ai_request OpenAI call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}")
    finally:
        await _close_client(client)

    text = ""
    try:
        text = response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        text = ""

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

    # 5. Accounting (best-effort — accounting failures never break the
    # user's request, but they are logged so we can detect them). On the
    # own-key path the cost is informational: OpenAI bills the customer.
    cost = calculate_openai_cost(model, input_tokens, output_tokens)

    if state.source == "quantro" and cost > 0 and access_token:
        await rpc_decrement_credits(user_id, cost, access_token)

    await insert_credit_usage(
        user_id=user_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        source=state.source,  # type: ignore[arg-type]
        access_token=access_token,
    )

    return {
        "text": text,
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
        },
        "source": state.source,
    }
