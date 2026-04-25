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

The encryption / decryption of `profiles.user_openai_api_key_encrypted`
is intentionally NOT implemented here yet — it requires choosing a
key-management strategy (Supabase pgcrypto vs. KMS). The API surface
(`get_user_api_key`) is a stub returning None so callers don't crash;
when the migration lands, fill that single function in.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal
import os

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


def calculate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost of one OpenAI request from token usage.

    Raises ValueError on unknown models so we never silently undercharge.
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        raise ValueError(f"Modelo no soportado para billing: {model}")
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
        1. profiles.ai_credits_remaining > 0  → source = "quantro"
        2. user supplied own OpenAI key      → source = "user_api"
        3. otherwise                         → source = "blocked"
    """
    profile = profile or {}
    lc_email = (email or "").lower().strip()
    is_test_user = bool(lc_email) and lc_email in TEST_USERS
    plan_key = (profile.get("plan") or "").lower()

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
    has_own_api_key = bool(profile.get("user_openai_api_key_encrypted")) or bool(profile.get("has_user_api_key"))

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


async def decrement_credits(
    *,
    supabase_client,
    user_id: str,
    cost_usd: float,
) -> None:
    """Atomically deduct `cost_usd` from profiles.ai_credits_used and
    recompute remaining. Uses the Postgres RPC `decrement_ai_credits` if
    present (recommended) or falls back to a plain UPDATE.

    Caller must pass an admin/service-role Supabase client because this
    bypasses RLS.
    """
    cost = max(0.0, float(cost_usd or 0.0))
    if cost == 0.0:
        return
    try:
        # Preferred path: Postgres RPC keeps the math atomic + handles
        # negative remaining → 0 clamping in one round-trip.
        await supabase_client.rpc("decrement_ai_credits", {
            "p_user_id": user_id,
            "p_amount": cost,
        }).execute()
    except Exception:  # noqa: BLE001 — fall through to manual update
        # Read current values then write back. Not strictly atomic but
        # acceptable while we don't have the RPC in place.
        try:
            row = await supabase_client.table("profiles").select(
                "ai_credits_total, ai_credits_used"
            ).eq("id", user_id).maybe_single().execute()
            data = (row.data or {}) if hasattr(row, "data") else (row or {})
            total = float(data.get("ai_credits_total") or 0.0)
            used = float(data.get("ai_credits_used") or 0.0) + cost
            remaining = max(0.0, total - used)
            await supabase_client.table("profiles").update({
                "ai_credits_used": used,
                "ai_credits_remaining": remaining,
            }).eq("id", user_id).execute()
        except Exception:  # noqa: BLE001
            # Never let billing accounting crash the request.
            pass


async def log_usage(
    *,
    supabase_client,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    source: CreditSource = "quantro",
    provider: str = "openai",
) -> None:
    """Persist one row in public.ai_credit_usage. Best-effort — logging
    failures should never break the user's request."""
    try:
        await supabase_client.table("ai_credit_usage").insert({
            "user_id": user_id,
            "model": model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cost_usd": float(cost_usd or 0.0),
            "provider": provider,
            "source": source,
        }).execute()
    except Exception:  # noqa: BLE001
        pass


def format_block_message(language: str = "es") -> str:
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
