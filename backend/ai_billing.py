"""AI billing — USD-credit accounting for Quantro Flow.

Mirrors the front-end helper in /app/frontend/src/lib/billing.js so the
UI never advertises a different bag of credits than what the backend
actually charges. Keep both files in lock-step on every change.

Responsibilities:
  * Define per-plan monthly credit allowance (`PLAN_CREDITS`).
  * Compute the real USD cost of an OpenAI request from token usage.
  * Decrement profiles.ai_credits_used (and recompute remaining) after
    each successful request, persisting one row in `ai_credit_usage`.
  * Decide which OpenAI API key to use for a given user:
        - quantro:  internal credits remaining > 0
        - user_api: user supplied their own key
        - blocked:  neither
  * Expose a single ``run_ai_request`` wrapper that every AI endpoint
    must call instead of touching OpenAI directly (Emergent LLM path removed in Phase 0).

The encryption / decryption of `profiles.user_openai_api_key_encrypted`
is intentionally NOT implemented here yet — it requires choosing a
key-management strategy (Supabase pgcrypto vs. KMS). The API surface
(`get_user_api_key`) is a stub returning None so callers don't crash;
when the migration lands, fill that single function in.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal, List, Dict, Any
import base64
import json
import logging
import os

import httpx
from fastapi import HTTPException

logger = logging.getLogger("quantro.ai_billing")

# ---------- Constants (lock-step with billing.js) ----------
PLAN_CREDITS = {
    "essential": 5.0,    # $5 USD / month
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
) -> CreditsState:
    """Read the user's credits state from a Supabase profiles row.

    Decision:
        1. has_coupon=true                    → no Quantro credits, must
                                                supply own API key
        2. profiles.ai_credits_remaining > 0  → source = "quantro"
        3. user supplied own OpenAI key       → source = "user_api"
        4. otherwise                          → source = "blocked"
    """
    profile = profile or {}
    lc_email = (email or "").lower().strip()
    is_test_user = bool(lc_email) and lc_email in TEST_USERS
    plan_key = (profile.get("plan") or "").lower()
    has_coupon = bool(profile.get("has_coupon"))

    base_total = (
        TEST_USER_CREDITS if is_test_user
        else float(PLAN_CREDITS.get(plan_key, 0.0))
    )
    total = float(profile.get("ai_credits_total") or base_total or 0.0)
    used = max(0.0, float(profile.get("ai_credits_used") or 0.0))
    remaining_raw = profile.get("ai_credits_remaining")
    remaining = (
        float(remaining_raw)
        if remaining_raw is not None
        else max(0.0, total - used)
    )
    remaining = max(0.0, remaining)
    has_own_api_key = (
        bool(profile.get("user_openai_api_key_encrypted"))
        or bool(profile.get("has_user_api_key"))
    )

    # Coupon / trial users don't get Quantro credits — they MUST bring
    # their own OpenAI key.
    if has_coupon:
        if has_own_api_key:
            return CreditsState(
                total=0.0, used=used, remaining=0.0,
                has_own_api_key=True,
                source="user_api", blocked=False, reason="coupon_user_api_key",
            )
        return CreditsState(
            total=0.0, used=used, remaining=0.0,
            has_own_api_key=False,
            source="blocked", blocked=True, reason="coupon_no_user_key",
        )

    if remaining > 0:
        return CreditsState(
            total=total, used=used, remaining=remaining,
            has_own_api_key=has_own_api_key,
            source="quantro", blocked=False, reason="using_quantro_credits",
        )
    if has_own_api_key:
        return CreditsState(
            total=total, used=used, remaining=remaining,
            has_own_api_key=True,
            source="user_api", blocked=False, reason="using_user_api_key",
        )
    return CreditsState(
        total=total, used=used, remaining=remaining,
        has_own_api_key=False,
        source="blocked", blocked=True, reason="no_credits_no_user_key",
    )


def get_quantro_api_key() -> Optional[str]:
    """Return Quantro's default OpenAI key from env, never logged."""
    return os.environ.get("OPENAI_API_KEY") or None


def get_user_api_key(profile: dict) -> Optional[str]:  # noqa: ARG001
    """Decrypt and return the user's own OpenAI API key.

    Stub for now: actual decryption depends on the chosen key-management
    strategy (pgcrypto, Supabase Vault, KMS). Wire it up as soon as the
    schema migration lands. Return None means "not available".
    """
    return None


def format_block_message(language: str = "es", reason: str = "") -> str:
    """User-facing copy returned with HTTP 402 when AI is blocked."""
    if reason == "coupon_no_user_key":
        if language == "en":
            return (
                "Trial accounts don\u2019t include Quantro AI credits. "
                "Add your own OpenAI API key in Settings to use AI features."
            )
        return (
            "Las cuentas de prueba no incluyen cr\u00e9ditos de Quantro IA. "
            "Agrega tu propia API key de OpenAI en Configuraci\u00f3n para "
            "usar las funciones inteligentes."
        )
    if language == "en":
        return (
            "You\u2019ve used up your Quantro AI credits for this cycle. "
            "Add your own OpenAI API key in Settings to keep using smart features, "
            "or upgrade your plan."
        )
    return (
        "Se acabaron tus cr\u00e9ditos IA de Quantro este ciclo. "
        "Agrega tu propia API key de OpenAI en Configuraci\u00f3n para seguir usando "
        "las funciones inteligentes, o actualiza tu plan."
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


def _jwt_subject(access_token: str) -> Optional[str]:
    """Return the ``sub`` claim of a JWT **without** verifying it.

    Only used as a defense-in-depth consistency check inside
    ``rpc_decrement_credits``: the token was already signature-verified
    by ``server.get_current_user`` (which also derives ``user.user_id``
    from this same ``sub``). Returns None for anything that isn't a
    well-formed JWT.
    """
    try:
        parts = (access_token or "").split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        sub = claims.get("sub") if isinstance(claims, dict) else None
        return str(sub) if sub else None
    except Exception:  # noqa: BLE001
        return None


async def rpc_decrement_credits(
    user_id: str,
    amount: float,
    access_token: str,
) -> None:
    """Atomically deduct ``amount`` USD from profiles.ai_credits_used
    via the ``decrement_ai_credits`` Postgres function.

    The RPC is called with the **service-role** key (``_service_headers``),
    never with the end user's JWT: ``decrement_ai_credits(uuid, numeric)``
    is SECURITY DEFINER and charges whatever ``p_user_id`` it receives
    (it does not use ``auth.uid()``), so EXECUTE is being revoked from
    ``authenticated`` and only ``service_role`` may call it.

    Authorization therefore lives here, in the backend: ``access_token``
    is still required (proof the request comes from a verified caller)
    and its ``sub`` must match ``user_id`` — a user can only ever be
    charged on their own profile. Best-effort: failures must never break
    the user's request.
    """
    cost = max(0.0, float(amount or 0.0))
    if cost == 0.0 or not SUPABASE_URL or not user_id or not access_token:
        return
    token_sub = _jwt_subject(access_token)
    if token_sub != str(user_id):
        logger.warning(
            "ai_billing.rpc_decrement_credits skipped: token subject does not match user_id",
        )
        return
    headers = _service_headers()
    if not headers:
        logger.warning(
            "ai_billing.rpc_decrement_credits skipped: SUPABASE_SERVICE_ROLE_KEY not configured",
        )
        return
    url = f"{SUPABASE_URL}/rest/v1/rpc/decrement_ai_credits"
    payload = {"p_user_id": user_id, "p_amount": cost}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, headers=headers, json=payload)
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
) -> Dict[str, Any]:
    """Single entry point for every AI endpoint in Quantro Flow.

    Enforces the AI Credits policy:
      * Reads the user's profile from Supabase (RLS-safe, user JWT).
      * Trial / coupon users must use their own OpenAI key (0 Quantro
        credits).
      * When using Quantro credits, model is FORCED to ``gpt-4o-mini``.
      * After the request, USD cost is calculated from token usage and
        either deducted from the bag (Quantro) or just logged (user
        API key).

    Raises HTTPException(402) when the user is blocked (no credits and
    no own API key) or when their own key is configured but missing.

    Returns a dict ``{"text": str, "model": str, "usage": {...},
    "source": "quantro" | "user_api"}`` so callers can pipe ``text``
    into their JSON-parsing logic just like before.
    """
    # 1. Resolve credits state
    profile: Dict[str, Any] = {}
    if access_token:
        profile = await fetch_profile(user_id, access_token)
    state = resolve_credits_state(email=email, profile=profile)

    if state.blocked:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "ai_blocked",
                "reason": state.reason,
                "message": format_block_message(language, state.reason),
            },
        )

    # 2. Pick API key + model
    if state.source == "quantro":
        api_key = get_quantro_api_key()
        model = QUANTRO_FORCED_MODEL  # never let users escalate model on Quantro's dime
    else:  # user_api
        api_key = get_user_api_key(profile)
        if not api_key:
            # Profile flagged as having a key but we couldn't read it.
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "ai_blocked",
                    "reason": "user_api_key_unavailable",
                    "message": format_block_message(language, "coupon_no_user_key"),
                },
            )
        model = (model_requested or QUANTRO_FORCED_MODEL).strip()

    if not api_key:
        # Quantro path but server has no env key configured.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "ai_unavailable",
                "message": "OpenAI API key is not configured on the server.",
            },
        )

    # 3. Call OpenAI (lazy import keeps cold-start fast and avoids hard
    # dependency at module import time)
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI SDK missing: {exc}")

    client = AsyncOpenAI(api_key=api_key)
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
        logger.exception("ai_billing.run_ai_request OpenAI call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}")

    text = ""
    try:
        text = response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        text = ""

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

    # 4. Accounting (best-effort — accounting failures never break the
    # user's request, but they are logged so we can detect them).
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
