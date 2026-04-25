"""Centralized billing limits for Quantro Flow.

This module is the **single source of truth on the backend** for how many
AI calls a user can make per month. It MIRRORS the values declared in
`/app/frontend/src/lib/billing.js` so the UI advertises exactly the same
cap the API enforces.

Resolution order (top wins):
    1. Email in TEST_USERS                                  -> TEST_USER_LIMIT
    2. subscription_status not in {active, trialing}        -> 0 (BLOCKED)
    3. profiles.has_coupon == True                          -> COUPON_LIMIT
    4. PLAN_LIMITS[profiles.plan]                           -> plan default

Use from any FastAPI handler that gates AI features:

    from billing_limits import resolve_openai_limit

    limit_info = resolve_openai_limit(email=user.email, profile=profile_row)
    if limit_info.blocked:
        raise HTTPException(403, detail="Activa un plan para usar Inbox AI")
    if used_calls_this_month >= limit_info.limit:
        raise HTTPException(429, detail="Límite mensual alcanzado")
"""

from dataclasses import dataclass
from typing import Optional

PLAN_LIMITS = {
    "essential": 1000,
    "pro": 3000,
    "enterprise": 15000,
}

INACTIVE_LIMIT = 0
COUPON_LIMIT = 500
TEST_USER_LIMIT = 15000

TEST_USERS = {
    "josias.martin@hotmail.com",
    "josias.martin90@hotmail.com",
}


@dataclass
class UsageLimit:
    limit: int
    reason: str
    blocked: bool


def resolve_openai_limit(
    email: Optional[str] = None,
    profile: Optional[dict] = None,
) -> UsageLimit:
    """Resolve the AI usage limit for a given user based on Supabase profile.

    Args:
        email: User's email (case-insensitive matching against TEST_USERS).
        profile: Row from public.profiles. Expected keys:
            - plan: "essential" | "pro" | "enterprise" | None
            - subscription_status: Stripe sub status
            - has_coupon: bool
            - stripe_customer_id: str | None

    Returns:
        UsageLimit dataclass with the resolved limit, reason and whether
        the user should be blocked from AI calls entirely.
    """
    profile = profile or {}
    lc_email = (email or "").lower().strip()

    # 1. Internal QA accounts always get the top tier.
    if lc_email and lc_email in TEST_USERS:
        return UsageLimit(limit=TEST_USER_LIMIT, reason="test_user", blocked=False)

    status = (profile.get("subscription_status") or "").lower()
    has_active_status = status in ("active", "trialing")
    plan_key = (profile.get("plan") or "").lower()
    # Treat "plan present + no status yet" as trial-like so we don't
    # accidentally lock out users while the Stripe webhook is in flight.
    plan_looks_active = bool(plan_key) and (
        has_active_status or (not status and bool(profile.get("stripe_customer_id")))
    )

    # 2. No active subscription -> blocked.
    if not plan_looks_active and not has_active_status:
        return UsageLimit(limit=INACTIVE_LIMIT, reason="no_active_subscription", blocked=True)

    # 3. Coupon override.
    if profile.get("has_coupon"):
        return UsageLimit(limit=COUPON_LIMIT, reason="coupon_applied", blocked=False)

    # 4. Plan-based limit.
    if plan_key in PLAN_LIMITS:
        return UsageLimit(limit=PLAN_LIMITS[plan_key], reason=f"plan:{plan_key}", blocked=False)

    # Fallback (should rarely hit): essential.
    return UsageLimit(limit=PLAN_LIMITS["essential"], reason="fallback_essential", blocked=False)


def format_block_message(language: str = "es") -> str:
    """Friendly message shown when a user without an active plan tries to
    consume AI features. Kept here so it can be reused across endpoints."""
    if language == "en":
        return "You need an active plan to use Quantro Flow's smart features."
    return "Necesitas un plan activo para usar las funciones inteligentes de Quantro Flow."
