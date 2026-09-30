"""AI credits policy: Essential includes no Quantro AI credits.

Pins the owner decision (2026-09-26):
  * Essential includes $0 of Quantro AI credits. Nothing in the backend may
    grant it a bag — neither PLAN_CREDITS nor the "stored total is 0/NULL"
    fallback in resolve_credits_state.
  * Balances already stored on an Essential profile are honoured until they
    run out (no claw-back).
  * Pro ($10) and Enterprise ($20) behave exactly as before.
  * decrement_ai_credits is still called with the user's own JWT (the
    Quantro OS migration keeps that call working).
  * backend, frontend billing.js and the reference stripe-webhook agree.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

import ai_billing
from ai_billing import (
    PLAN_CREDITS,
    format_block_message,
    resolve_credits_state,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_ID = "11111111-1111-1111-1111-111111111111"


def _profile(**cols: Any) -> Dict[str, Any]:
    return {"id": USER_ID, **cols}


# ---------- Constants -------------------------------------------------
def test_plan_credits_essential_is_zero_pro_enterprise_unchanged():
    assert PLAN_CREDITS == {"essential": 0.0, "pro": 10.0, "enterprise": 20.0}


# ---------- Essential: no new grant -----------------------------------
@pytest.mark.parametrize(
    "cols",
    [
        # DB defaults for a new profile (0/0/0).
        {"ai_credits_total": 0, "ai_credits_used": 0, "ai_credits_remaining": 0},
        # Stored total 0 and remaining NULL: used to fall back to $5.
        {"ai_credits_total": 0, "ai_credits_used": 0, "ai_credits_remaining": None},
        # NULL total and NULL remaining.
        {"ai_credits_total": None, "ai_credits_used": None, "ai_credits_remaining": None},
        # Credit columns missing from the row entirely.
        {},
    ],
    ids=["defaults_0_0_0", "total0_remaining_null", "all_null", "no_columns"],
)
def test_essential_without_stored_balance_is_blocked(cols):
    state = resolve_credits_state(email="owner@example.com", profile=_profile(plan="essential", **cols))
    assert state.blocked is True
    assert state.source == "blocked"
    assert state.reason == "plan_no_credits"
    assert state.total == 0.0
    assert state.remaining == 0.0


def test_essential_plan_key_is_case_insensitive():
    state = resolve_credits_state(profile=_profile(plan="Essential"))
    assert state.blocked is True
    assert state.reason == "plan_no_credits"
    assert state.total == 0.0


# ---------- Essential: no claw-back -----------------------------------
def test_essential_existing_balance_is_still_honoured():
    state = resolve_credits_state(
        profile=_profile(
            plan="essential",
            ai_credits_total=5,
            ai_credits_used=1.8,
            ai_credits_remaining=3.2,
        )
    )
    assert state.blocked is False
    assert state.source == "quantro"
    assert state.total == pytest.approx(5.0)
    assert state.remaining == pytest.approx(3.2)


def test_essential_existing_total_with_null_remaining_uses_stored_total():
    state = resolve_credits_state(
        profile=_profile(
            plan="essential",
            ai_credits_total=5,
            ai_credits_used=1,
            ai_credits_remaining=None,
        )
    )
    assert state.source == "quantro"
    assert state.total == pytest.approx(5.0)
    assert state.remaining == pytest.approx(4.0)


def test_essential_exhausted_legacy_balance_gets_plan_message():
    state = resolve_credits_state(
        profile=_profile(
            plan="essential",
            ai_credits_total=5,
            ai_credits_used=5,
            ai_credits_remaining=0,
        )
    )
    assert state.blocked is True
    assert state.reason == "plan_no_credits"


# ---------- Pro / Enterprise: unchanged -------------------------------
@pytest.mark.parametrize(
    "plan,cols,expected_total,expected_remaining,expected_source,expected_reason",
    [
        ("pro", {}, 10.0, 10.0, "quantro", "using_quantro_credits"),
        ("pro", {"ai_credits_total": 0, "ai_credits_remaining": None}, 10.0, 10.0, "quantro", "using_quantro_credits"),
        ("pro", {"ai_credits_total": 10, "ai_credits_used": 2.5, "ai_credits_remaining": 7.5}, 10.0, 7.5, "quantro", "using_quantro_credits"),
        ("pro", {"ai_credits_total": 0, "ai_credits_used": 0, "ai_credits_remaining": 0}, 10.0, 0.0, "blocked", "no_credits_no_user_key"),
        ("enterprise", {}, 20.0, 20.0, "quantro", "using_quantro_credits"),
        ("enterprise", {"ai_credits_total": 0, "ai_credits_remaining": None}, 20.0, 20.0, "quantro", "using_quantro_credits"),
        ("enterprise", {"ai_credits_total": 0, "ai_credits_used": 0, "ai_credits_remaining": 0}, 20.0, 0.0, "blocked", "no_credits_no_user_key"),
    ],
)
def test_pro_and_enterprise_behaviour_is_unchanged(
    plan, cols, expected_total, expected_remaining, expected_source, expected_reason,
):
    state = resolve_credits_state(profile=_profile(plan=plan, **cols))
    assert state.total == pytest.approx(expected_total)
    assert state.remaining == pytest.approx(expected_remaining)
    assert state.source == expected_source
    assert state.reason == expected_reason


@pytest.mark.parametrize("plan", [None, "", "legacy_plan"])
def test_unknown_or_missing_plan_keeps_generic_reason(plan):
    state = resolve_credits_state(profile=_profile(plan=plan))
    assert state.blocked is True
    assert state.reason == "no_credits_no_user_key"


def test_coupon_on_essential_keeps_coupon_reason():
    state = resolve_credits_state(profile=_profile(plan="essential", has_coupon=True))
    assert state.blocked is True
    assert state.reason == "coupon_no_user_key"


def test_essential_with_workspace_own_key_routes_to_user_api_not_quantro():
    # Before the change the $5 fallback made this "quantro" (Quantro-paid).
    # The own key is now the workspace's (integrations_config), not a
    # profile flag — see tests/test_own_openai_key.py.
    state = resolve_credits_state(profile=_profile(plan="essential"), own_key_active=True)
    assert state.blocked is False
    assert state.source == "user_api"


def test_internal_test_users_are_unaffected():
    email = next(iter(ai_billing.TEST_USERS))
    state = resolve_credits_state(email=email, profile=_profile(plan="essential"))
    assert state.source == "quantro"
    assert state.total == pytest.approx(ai_billing.TEST_USER_CREDITS)


# ---------- 402 copy --------------------------------------------------
@pytest.mark.parametrize("language", ["es", "en"])
def test_plan_no_credits_message_does_not_claim_used_up_or_amount(language):
    msg = format_block_message(language, "plan_no_credits")
    assert "Pro" in msg
    lowered = msg.lower()
    for forbidden in ("$5", "5 usd", "used up", "exhausted", "se acabaron"):
        assert forbidden not in lowered
    # The workspace's own OpenAI key works now (2026-09-30): point to it.
    assert "openai" in lowered
    assert ("Settings → Integrations" if language == "en" else "Configuración → Integraciones") in msg


def test_plan_no_credits_message_language():
    assert "plan" in format_block_message("en", "plan_no_credits").lower()
    assert "créditos" in format_block_message("es", "plan_no_credits")


async def test_run_ai_request_blocks_essential_with_plan_reason(monkeypatch):
    async def fake_fetch_profile(user_id, access_token):
        assert user_id == USER_ID
        return _profile(plan="essential", ai_credits_total=0, ai_credits_used=0, ai_credits_remaining=0)

    def must_not_be_called():
        raise AssertionError("Quantro's OpenAI key must not be used for Essential")

    monkeypatch.setattr(ai_billing, "fetch_profile", fake_fetch_profile)
    monkeypatch.setattr(ai_billing, "get_quantro_api_key", must_not_be_called)

    with pytest.raises(HTTPException) as exc:
        await ai_billing.run_ai_request(
            user_id=USER_ID,
            email="owner@example.com",
            access_token="user-jwt",
            system_prompt="s",
            user_prompt="u",
            language="en",
        )
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "ai_blocked"
    assert exc.value.detail["reason"] == "plan_no_credits"
    assert exc.value.detail["message"] == format_block_message("en", "plan_no_credits")


# ---------- decrement call is unchanged (user JWT) --------------------
class _FakeResponse:
    status_code = 204
    text = ""


class _FakeAsyncClient:
    calls: List[Dict[str, Any]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse()


async def test_rpc_decrement_credits_still_uses_the_users_jwt(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(ai_billing, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(ai_billing, "SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setattr(ai_billing, "SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
    monkeypatch.setattr(ai_billing.httpx, "AsyncClient", _FakeAsyncClient)

    await ai_billing.rpc_decrement_credits(USER_ID, 0.0123, "user-jwt")

    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"] == "https://example.supabase.co/rest/v1/rpc/decrement_ai_credits"
    assert call["json"] == {"p_user_id": USER_ID, "p_amount": 0.0123}
    assert call["headers"]["Authorization"] == "Bearer user-jwt"
    assert call["headers"]["apikey"] == "anon-key"
    assert "service-role-key" not in str(call["headers"])


# ---------- lock-step with frontend + reference webhook ---------------
def _parse_plan_credits(path: Path) -> Dict[str, float]:
    src = path.read_text(encoding="utf-8")
    block = re.search(r"PLAN_CREDITS[^=]*=\s*\{(.*?)\}", src, re.S)
    assert block, f"PLAN_CREDITS not found in {path}"
    pairs = re.findall(r"(essential|pro|enterprise)\s*:\s*([0-9.]+)", block.group(1))
    return {k: float(v) for k, v in pairs}


@pytest.mark.parametrize(
    "rel_path",
    ["frontend/src/lib/billing.js", "supabase/functions/stripe-webhook/index.ts"],
)
def test_plan_credits_lock_step(rel_path):
    assert _parse_plan_credits(REPO_ROOT / rel_path) == PLAN_CREDITS


def test_frontend_pricing_card_does_not_advertise_essential_credits():
    src = (REPO_ROOT / "frontend/src/lib/billing.js").read_text(encoding="utf-8")
    # The old bullet rendered "$5 USD en créditos IA / mes" on Essential and
    # would render "$0 USD ..." if only the constant changed.
    assert "${PLAN_CREDITS.essential}" not in src
    assert "planCreditsFeature('essential')" in src


# ---------- reference webhook: when a new bag of credits starts -------
WEBHOOK_DIR = REPO_ROOT / "supabase/functions/stripe-webhook"


def test_webhook_allocates_only_through_the_tested_gate():
    src = (WEBHOOK_DIR / "index.ts").read_text(encoding="utf-8")
    assert "from './credit_period.ts'" in src
    assert "if (startsNewCreditPeriod(event.type, sub.status, priceId, prev))" in src
    # The three credit columns are written in exactly one place, under the gate.
    assert src.count("update.ai_credits_total") == 1
    gate = src.index("if (startsNewCreditPeriod(")
    assert gate < src.index("update.ai_credits_total") < src.index("update.ai_credits_remaining")


def _node_strips_types() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    m = re.match(r"v(\d+)\.(\d+)", out.strip())
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (22, 18)


@pytest.mark.skipif(not _node_strips_types(), reason="needs Node >= 22.18 (TypeScript type stripping)")
def test_webhook_credit_period_gate_unit_tests():
    """Runs credit_period.test.ts: incomplete -> active starts a bag (first
    payment after SCA), renewal and plan change do, other updates do not."""
    result = subprocess.run(
        [shutil.which("node"), "--test", str(WEBHOOK_DIR / "credit_period.test.ts")],
        capture_output=True, text=True, check=False, cwd=REPO_ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
