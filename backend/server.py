import os
import uuid
import json
import time
import asyncio
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

import httpx
import jwt as pyjwt
from jwt import PyJWKClient, InvalidTokenError, ExpiredSignatureError
from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from fastapi.responses import StreamingResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
from ai_billing import run_ai_request
import supabase_admin

# ─── Quantro Connect + Quantro Actions ─────────────────────────────────
# New platform-layer modules (see integrations/ and actions/ packages).
# server.py stays the single FastAPI app; these packages hold all the
# provider/action-specific logic so server.py doesn't grow further.
from errors import QuantroError
from integrations.base import ConnectionStatus
from integrations import secrets as integration_secrets
from integrations.registry import register_provider, get_provider as get_connect_provider, list_providers as list_connect_providers
from integrations.service import ConnectService
from integrations.providers.google import GoogleAdapter
from integrations.providers.microsoft import MicrosoftAdapter
from integrations.providers.facturapi import FacturapiAdapter
from integrations.providers.quantro_internal import QuantroInternalAdapter
from actions.executor import ActionExecutor
from actions.policy_gate import PolicyGate
from actions.registry import get_action, list_actions
from actions.bootstrap import register_all_actions

# ─── Config ────────────────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "quantro_os")
# AI Billing — every AI request now flows through ai_billing.run_ai_request.
# EMERGENT_LLM_KEY is intentionally NOT loaded here: Quantro uses
# OPENAI_API_KEY directly (Quantro credits) or the user's own key
# (coupon / depleted-credit users). See /app/backend/ai_billing.py.

# ─── Supabase Auth (shared project with the Quantro landing) ──────────
# The frontend signs users in through Supabase Auth; we simply verify the
# JWT here. We support BOTH signing methods Supabase is currently using
# for this project:
#   • Current key  → ECC (P-256) via JWKS (ES256)
#   • Previous key → Legacy HS256 shared secret
# This dual verification means tokens issued before or after a key rotation
# keep working without user impact.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else ""

# Lazy JWKS client (PyJWT caches keys in memory for us).
_jwks_client: Optional[PyJWKClient] = None

def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    if not SUPABASE_JWKS_URL:
        return None
    if _jwks_client is None:
        try:
            _jwks_client = PyJWKClient(SUPABASE_JWKS_URL, cache_keys=True, lifespan=3600)
        except Exception:
            _jwks_client = None
    return _jwks_client

# ─── MongoDB ───────────────────────────────────────────────────────────
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Collections
inbox_col = db["inbox_items"]
calendar_col = db["calendar_events"]
contacts_col = db["contacts"]
agents_col = db["agents"]
onboarding_col = db["onboarding_tasks"]
content_col = db["content_items"]
activity_col = db["activity_events"]
policies_col = db["automation_policies"]
escalation_col = db["escalation_rules"]
templates_col = db["content_templates"]
business_profile_col = db["business_profile"]
integrations_config_col = db["integrations_config"]
system_health_col = db["system_health_events"]
# Phase 7a — Auth + multi-tenant
users_col = db["users"]
user_sessions_col = db["user_sessions"]
workspaces_col = db["workspaces"]
workspace_members_col = db["workspace_members"]
workspace_invites_col = db["workspace_invites"]
audit_log_col = db["audit_log"]
# Phase 7e — Google OAuth (Gmail + Calendar)
google_integrations_col = db["google_integrations"]
google_oauth_state_col = db["google_oauth_state"]
# Phase 7e.2 — Microsoft Outlook OAuth (Mail + Calendar)
microsoft_integrations_col = db["microsoft_integrations"]
microsoft_oauth_state_col = db["microsoft_oauth_state"]
# Quantro Connect — Facturapi (CFDI México)
facturapi_connections_col = db["facturapi_connections"]
facturapi_webhook_events_col = db["facturapi_webhook_events"]
# Quantro Actions
action_executions_col = db["action_executions"]
action_policies_col = db["action_policies"]  # workspace-level auto-approve overrides for high/critical-risk actions

# The workspace_id used by pre-auth seed + backfill. The first user to
# log in claims this workspace (rename + become Owner). Subsequent users
# get fresh personal workspaces.
DEFAULT_WORKSPACE_ID = "default"

# ─── Helpers ───────────────────────────────────────────────────────────
def serialize_doc(doc):
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == "_id":
            result["id"] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [serialize_doc(v) if isinstance(v, dict) else (v.isoformat() if isinstance(v, datetime) else v) for v in value]
        elif isinstance(value, dict):
            result[key] = serialize_doc(value)
        else:
            result[key] = value
    return result

def now_iso():
    return datetime.utcnow()


# ─── Auth & Workspace (Supabase-backed) ───────────────────────────────
class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    current_workspace_id: Optional[str] = None
    # Supabase access_token forwarded from the request — needed by the
    # AI billing wrapper to read profiles/usage under RLS without
    # requiring a service-role key.
    access_token: Optional[str] = None


def _extract_bearer_token(request: Request) -> Optional[str]:
    """Pull a Bearer token from the Authorization header (Supabase access token).

    Frontend also attaches the Supabase session via authFetch/axios. We no longer
    accept cookies because the entire ecosystem standardised on Supabase Bearer
    tokens (shared with the landing page)."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase JWT and return its claims dict.

    Strategy (in order):
      1. Inspect the unverified header. If ``alg`` is an asymmetric algorithm
         (ES256/RS256/EdDSA), fetch the matching public key from the project's
         JWKS endpoint and verify with it.
      2. If ``alg`` is HS256 (legacy shared-secret tokens) verify with the
         project's SUPABASE_JWT_SECRET.
      3. Otherwise, fall back to trying both paths in sequence so we never
         lock out a user during a Supabase signing-key rotation.

    Raises HTTPException(401) if the token is invalid/expired.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        header = pyjwt.get_unverified_header(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Malformed token")

    alg = (header.get("alg") or "").upper()
    # Decode options: Supabase issues `aud: "authenticated"` for signed-in users.
    decode_kwargs = dict(
        audience="authenticated",
        options={"verify_aud": True, "require": ["exp", "sub"]},
        leeway=5,
    )

    last_err: Optional[Exception] = None

    def _try_jwks():
        client = _get_jwks_client()
        if not client:
            raise RuntimeError("JWKS client unavailable")
        signing_key = client.get_signing_key_from_jwt(token).key
        return pyjwt.decode(token, signing_key, algorithms=[alg or "ES256", "RS256", "EdDSA"], **decode_kwargs)

    def _try_hs256():
        if not SUPABASE_JWT_SECRET:
            raise RuntimeError("JWT secret unavailable")
        return pyjwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], **decode_kwargs)

    # Primary path based on header alg.
    try:
        if alg == "HS256":
            return _try_hs256()
        # Everything else → JWKS first.
        return _try_jwks()
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except Exception as e:
        last_err = e

    # Fallback path (rotation safety net).
    for attempt in (_try_hs256, _try_jwks):
        try:
            return attempt()
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Session expired")
        except Exception as e:
            last_err = e
            continue

    # All paths failed.
    raise HTTPException(status_code=401, detail=f"Invalid token: {last_err}")


async def _upsert_user_from_claims(claims: dict) -> dict:
    """Ensure a Mongo users_col row exists for this Supabase identity.

    Key behaviour:
      • user_id is ALWAYS the Supabase UUID (``sub`` claim).
      • If a legacy Emergent-era user with the same email exists, we migrate
        its workspace memberships and config to the new user_id so no data
        is lost when switching auth providers.
      • Updates name/picture/last_login_at on every call (cheap).
    """
    user_id = claims.get("sub")
    email = claims.get("email") or (claims.get("user_metadata") or {}).get("email")
    if not user_id or not email:
        raise HTTPException(status_code=401, detail="Token missing sub/email")

    meta = claims.get("user_metadata") or {}
    name = meta.get("full_name") or meta.get("name") or email.split("@")[0]
    picture = meta.get("avatar_url") or meta.get("picture")

    existing = await users_col.find_one({"user_id": user_id}, {"_id": 0})
    if not existing:
        # Migrate legacy user (matched by email) if any → reuse its workspace.
        legacy = await users_col.find_one({"email": email, "user_id": {"$ne": user_id}}, {"_id": 0})
        if legacy:
            legacy_id = legacy["user_id"]
            await workspace_members_col.update_many(
                {"user_id": legacy_id}, {"$set": {"user_id": user_id}}
            )
            await workspaces_col.update_many(
                {"owner_user_id": legacy_id}, {"$set": {"owner_user_id": user_id}}
            )
            # Keep legacy row for audit history but rename its id to prevent
            # future matches.
            await users_col.update_one(
                {"user_id": legacy_id},
                {"$set": {"user_id": f"legacy_{legacy_id}", "migrated_to": user_id}},
            )

        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "created_at": datetime.now(timezone.utc),
            "last_login_at": datetime.now(timezone.utc),
            "auth_provider": "supabase",
        }
        await users_col.insert_one(user_doc)
        existing = user_doc
    else:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "email": email,
                "name": name,
                "picture": picture,
                "last_login_at": datetime.now(timezone.utc),
                "auth_provider": "supabase",
            }},
        )
        existing.update({"email": email, "name": name, "picture": picture})

    # Ensure the user has an active workspace.
    # Phase 7c: reconcile Supabase org memberships first — if this user is
    # already a member of one or more orgs in Supabase, those memberships
    # are the source of truth, so mirror them into Mongo *before* we fall
    # back to creating a personal workspace. This prevents the "everyone
    # gets their own private workspace on first login" bug that affected
    # users whose legacy Mongo identity was remapped during auth migration.
    reconciled_ws = await reconcile_supabase_memberships_to_mongo(existing)
    if not existing.get("current_workspace_id"):
        ws_id = reconciled_ws or await claim_or_create_workspace_for_user(existing)
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"current_workspace_id": ws_id}},
        )
        existing["current_workspace_id"] = ws_id

    return existing


async def get_current_user(request: Request) -> User:
    """FastAPI dependency: resolve the authenticated user from the Supabase
    access token (Bearer). All workspace-scoped endpoints depend on this."""
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = _verify_supabase_jwt(token)
    user_doc = await _upsert_user_from_claims(claims)
    user = User(**{k: user_doc.get(k) for k in ["user_id", "email", "name", "picture", "current_workspace_id"]})
    # Forward the raw access_token so AI billing can read Supabase under
    # the user's own RLS context (no service-role key needed for reads
    # or for the decrement_ai_credits RPC).
    user.access_token = token
    return user


async def _active_workspace_id(request: Request, user: User) -> str:
    """Resolve the active workspace id for this request.

    Priority:
      1. `X-Workspace-Id` header (explicit switcher intent)
      2. user.current_workspace_id (last-used)
      3. first membership (deterministic fallback)
    The chosen id is validated against membership to prevent cross-workspace access."""
    header_ws = request.headers.get("x-workspace-id") or request.headers.get("X-Workspace-Id")
    candidate_ids = []
    if header_ws:
        candidate_ids.append(header_ws)
    if user.current_workspace_id:
        candidate_ids.append(user.current_workspace_id)

    memberships = await workspace_members_col.find({"user_id": user.user_id}, {"_id": 0}).to_list(50)
    member_ids = {m["workspace_id"] for m in memberships}
    if not member_ids:
        raise HTTPException(status_code=403, detail="No workspace access")

    for cid in candidate_ids:
        if cid in member_ids:
            return cid
    return sorted(member_ids)[0]


async def get_current_workspace_id(request: Request, user: User = Depends(get_current_user)) -> str:
    return await _active_workspace_id(request, user)


async def log_audit(
    event_type: str,
    description: str,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    target_member_id: Optional[str] = None,
):
    """Append an audit log event. Non-fatal on error.

    Phase 7c: every event is also shadow-written to the Supabase
    ``org_audit_logs`` table whenever a workspace→org mapping exists.
    The Supabase action vocabulary is constrained (see migration), so
    we map our internal event types onto its CHECK constraint values
    and drop events that don't fit (auth + workspace lifecycle which
    aren't in the Supabase schema yet).

    The audit row mirrors the shape we'll eventually use in Supabase
    (`org_audit_logs`): actor (`user_id`), target (`target_user_id`),
    workspace context (`workspace_id`), action (`event_type`), and a
    free-form `metadata` jsonb-like dict.
    """
    try:
        await audit_log_col.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "description": description,
            "user_id": user_id,
            "target_member_id": target_member_id,
            "workspace_id": workspace_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception:
        pass

    # Shadow-write to Supabase (best-effort).
    try:
        if not workspace_id or not target_member_id:
            return
        if not supabase_admin.is_dual_write_enabled():
            return
        org_id = await workspace_to_org_id(workspace_id)
        if not org_id:
            return
        action = _map_audit_event_to_supabase(event_type)
        if not action:
            return
        meta = dict(metadata or {})
        meta.setdefault("event_type", event_type)
        meta.setdefault("description", description)
        await supabase_admin.insert_audit_log(
            org_id=org_id,
            action=action,
            target_user_id=target_member_id,
            actor_user_id=user_id,
            access_token=None,  # service-role only in this path; user JWT not always available here
            old_role=meta.get("previous_role") or meta.get("old_role"),
            new_role=meta.get("new_role"),
            metadata=meta,
        )
    except Exception:  # noqa: BLE001
        pass


# Mapping from internal event_type → Supabase org_audit_logs.action
# (constrained by CHECK). Anything not in this map skips the shadow.
_AUDIT_EVENT_MAP: Dict[str, str] = {
    "members.role_changed": "role_changed",
    "members.removed": "access_revoked",
    "invites.created": "invitation_created",
    "invites.revoked": "access_revoked",
    "invites.accepted": "invitation_accepted",
    "onboarding.completed": "onboarding_completed",
    "onboarding.step_updated": "permissions_modified",
}


def _map_audit_event_to_supabase(event_type: str) -> Optional[str]:
    return _AUDIT_EVENT_MAP.get(event_type)


# ─── Simulation Mode Helpers (Strict Data Isolation) ──────────────────
# These helpers are the single source of truth for deciding whether a
# request should operate in the simulation sandbox or against the real
# workspace. All list / detail / metrics endpoints MUST use
# `get_mode_filter()` when querying operational collections to guarantee
# zero data leakage between modes. All write endpoints MUST tag new
# records with `is_simulation = await is_simulation_mode(workspace_id)` so
# they stay in the correct dataset.
async def is_simulation_mode(workspace_id: str = DEFAULT_WORKSPACE_ID) -> bool:
    """Return True if the given workspace is currently in Simulation Mode."""
    profile = await business_profile_col.find_one(
        {"workspace_id": workspace_id},
        {"_id": 0, "simulation_mode": 1},
    )
    if not profile:
        # Legacy fallback for pre-migration instances
        profile = await business_profile_col.find_one(
            {"profile_id": "default"},
            {"_id": 0, "simulation_mode": 1},
        )
    return bool((profile or {}).get("simulation_mode", False))


async def get_mode_filter(workspace_id: str = DEFAULT_WORKSPACE_ID) -> dict:
    """Return the Mongo filter that isolates the current mode + workspace.

    Combines:
      - workspace_id (strict tenant isolation)
      - is_simulation (strict sandbox/live isolation)
    """
    base = {"workspace_id": workspace_id}
    if await is_simulation_mode(workspace_id):
        base["is_simulation"] = True
    else:
        base["is_simulation"] = {"$ne": True}
    return base


def merge_query(base: dict, mode: dict) -> dict:
    """Merge a caller-provided base query with a mode filter safely."""
    if not base:
        return dict(mode)
    out = dict(base)
    out.update(mode)
    return out


# ─── AI Prompts ────────────────────────────────────────────────────────
LANGUAGE_NAMES = {"es": "Spanish", "en": "English"}

def _lang_directive(language_code):
    """Return a single-line language directive to inject into LLM prompts.
    Spec: 'Respond in ${lang === "es" ? "Spanish" : "English"}'."""
    name = LANGUAGE_NAMES.get((language_code or "en").lower(), "English")
    return f"Respond in {name}. All textual fields (summary, description, generated copy) must be written in {name}."


async def _workspace_language(workspace_id: str = DEFAULT_WORKSPACE_ID) -> str:
    """Return the active business-profile language ('es' | 'en') for a workspace."""
    try:
        profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        return ((profile or {}).get("language") or "es").lower()
    except Exception:
        return "es"

async def build_intent_prompt(business_profile=None, workspace_id: str = DEFAULT_WORKSPACE_ID):
    """Build intent detection prompt with business profile context."""
    if not business_profile:
        profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        business_profile = profile if profile else {"industry": "other", "entity_labels": {}}
    
    industry = business_profile.get("industry", "other")
    labels = business_profile.get("entity_labels", {})
    language = business_profile.get("language", "es")
    
    industry_context = {
        "real_estate": "real estate operations",
        "healthcare": "healthcare and patient management",
        "consulting": "consulting and client services",
        "ecommerce": "e-commerce and customer operations",
        "other": "business operations"
    }.get(industry, "business operations")
    
    entity_name = labels.get("services", "property")
    
    return f"""You are an AI assistant for Quantro Flow, a Business Operating System.
The business operates in: {industry_context}.
{_lang_directive(language)}

Analyze incoming messages and detect intent.

Respond with ONLY valid JSON (no markdown fences):
{{
  "intent": "<booking|onboarding|follow_up|inquiry|escalation|spam|needs_review>",
  "confidence": <float 0.0-1.0>,
  "summary": "<1-sentence summary>",
  "entities": {{
    "person_name": "<name or null>",
    "email": "<email or null>",
    "phone": "<phone or null>",
    "date_time": "<date/time or null>",
    "asset": "<{entity_name} or null>"
  }},
  "suggested_action": {{
    "type": "<schedule_meeting|create_contact|send_follow_up|start_onboarding|flag_review|ignore|none>",
    "description": "<what to do>"
  }}
}}"""

async def build_content_prompt(business_profile=None, workspace_id: str = DEFAULT_WORKSPACE_ID):
    """Build content generation prompt with business profile context."""
    if not business_profile:
        profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        business_profile = profile if profile else {"industry": "other"}
    
    industry = business_profile.get("industry", "other")
    language = business_profile.get("language", "es")
    
    industry_context = {
        "real_estate": "a real estate team",
        "healthcare": "a healthcare organization",
        "consulting": "a consulting firm",
        "ecommerce": "an e-commerce business",
        "other": "a professional business"
    }.get(industry, "a professional business")
    
    return f"""You are a premium content writer for {industry_context}.
Generate professional, engaging content.
{_lang_directive(language)}

Respond with ONLY valid JSON (no markdown fences):
{{
  "social_post": {{
    "text": "<social media post, 1-3 sentences>",
    "hashtags": ["<hashtags>"],
    "platform": "instagram"
  }},
  "email_draft": {{
    "subject": "<subject line>",
    "body": "<2-4 paragraphs>",
    "call_to_action": "<CTA>"
  }}
}}

Style: Professional, warm, trustworthy."""

async def parse_ai_json(response_text):
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None

async def log_activity(event_type, title, description, related_id=None, related_type=None, workspace_id: Optional[str] = None):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "title": title,
        "description": description,
        "related_id": related_id,
        "related_type": related_type,
        "timestamp": now_iso(),
        "is_simulation": await is_simulation_mode(workspace_id or DEFAULT_WORKSPACE_ID),
        "workspace_id": workspace_id or DEFAULT_WORKSPACE_ID,
    }
    await activity_col.insert_one(event)
    return event

# ─── Auto-Execution Engine ─────────────────────────────────────────────
URGENCY_KEYWORDS = ["urgent", "asap", "immediately", "emergency", "critical", "right away", "time-sensitive", "rush"]

async def execute_action_for_item(item, source="auto"):
    """Execute the suggested action for an inbox item.

    Thin compatibility shim over ActionExecutor.execute() — Quantro
    Actions migration. The actual DB-write logic for each action_type
    now lives in actions/handlers/quantro_internal.py (moved, not
    copied); this function's only job is: map the legacy action_type
    name to its Action id, build the `input` shape a handler expects
    from an inbox item, and translate the resulting execution record
    back into the {"executed", "action_type", "results"} shape every
    existing caller (analyze/batch-analyze/approve endpoints) expects,
    so nothing downstream of this function had to change.

    skip_policy_gate=True: callers only ever reach this function AFTER
    their own intent-based policy evaluation (see
    evaluate_policy_for_item / the confidence-threshold checks in
    analyze/batch-analyze above) already decided to auto-run — this
    function must never re-decide that via the Actions Policy Gate.
    """
    action = item.get("ai_suggested_action")
    if not action:
        return {"executed": False, "reason": "No action available"}

    action_type = action["type"]
    entities = item.get("ai_intent", {}).get("entities", {})
    # Downstream artifacts inherit the mode of the triggering inbox item
    # so everything remains in the correct sandbox/workspace.
    sim_flag = bool(item.get("is_simulation", False))
    ws_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)

    async def run(action_id: str, input_payload: dict):
        return await action_executor.execute(
            workspace_id=ws_id, action_id=action_id, input=input_payload,
            source=source, skip_policy_gate=True,
        )

    if action_type == "schedule_meeting":
        execution = await run("quantro.calendar.event.create", {
            "title": f"Meeting - {item['from_name']}",
            "description": action.get("description", ""),
            "start_time": (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat(),
            "location": entities.get("property", "TBD"),
            "attendees": [item["from_name"]],
            "contact_id": item.get("contact_id"),
            "is_simulation": sim_flag,
        })
        results = [{"type": "event_created", "event_id": (execution.get("result_metadata") or {}).get("event_id")}]

    elif action_type == "create_contact":
        execution = await run("quantro.crm.contact.create", {
            "name": entities.get("person_name", item["from_name"]),
            "email": entities.get("email", item["from_email"]),
            "phone": entities.get("phone", ""),
            "notes": item.get("ai_intent", {}).get("summary", ""),
            "is_simulation": sim_flag,
        })
        contact_id = (execution.get("result_metadata") or {}).get("contact_id")
        if contact_id:
            await inbox_col.update_one({"inbox_id": item["inbox_id"]}, {"$set": {"contact_id": contact_id}})
        results = [{"type": "contact_created", "contact_id": contact_id}]

    elif action_type == "start_onboarding":
        execution = await run("quantro.onboarding.start", {
            "name": entities.get("person_name", item["from_name"]),
            "email": entities.get("email", item["from_email"]),
            "phone": entities.get("phone", ""),
            "is_simulation": sim_flag,
        })
        results = [{"type": "agent_created", "agent_id": (execution.get("result_metadata") or {}).get("agent_id")}]

    elif action_type == "send_follow_up":
        execution = await run("quantro.followup.send", {"recipient_name": item["from_name"], "related_id": item["inbox_id"]})
        results = [{"type": "follow_up_queued"}]

    elif action_type == "ignore":
        execution = await run("quantro.inbox.ignore", {"from_name": item["from_name"], "related_id": item["inbox_id"]})
        results = [{"type": "ignored"}]

    else:
        execution = await run("quantro.review.flag", {"reason": f"Action '{action_type}' for {item['from_name']}", "related_id": item["inbox_id"]})
        results = [{"type": action_type}]

    executed = execution["status"] in ("succeeded", "simulated")

    # Mark as auto-actioned
    await inbox_col.update_one(
        {"inbox_id": item["inbox_id"]},
        {"$set": {"status": "auto_actioned", "auto_executed": executed, "auto_executed_at": now_iso(), "execution_source": source, "execution_results": results}}
    )

    return {"executed": executed, "action_type": action_type, "results": results}


async def evaluate_advanced_escalation(item, intent, confidence, policy_action):
    """Evaluate advanced escalation conditions beyond simple intent/keyword matching."""
    escalation_info = None
    escalation_reasons = []
    workspace_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)
    
    rules = await escalation_col.find({"workspace_id": workspace_id, "enabled": True}).to_list(100)
    entities = item.get("ai_intent", {}).get("entities", {})
    text = f"{item.get('subject', '')} {item.get('body', '')}".lower()
    
    for rule in rules:
        matched = False
        
        if rule["condition_type"] == "intent" and rule["condition_value"] == intent:
            matched = True
        
        elif rule["condition_type"] == "keyword":
            keywords = [k.strip().lower() for k in rule["condition_value"].split(",")]
            if any(kw in text for kw in keywords):
                matched = True
        
        elif rule["condition_type"] == "calendar_conflict":
            # Check if a meeting is proposed and conflicts with existing events
            if item.get("ai_suggested_action", {}).get("type") == "schedule_meeting":
                proposed_dt = entities.get("date_time")
                if proposed_dt:
                    # Check for any events on the same day (simplified conflict check)
                    existing_events = await calendar_col.find({"workspace_id": workspace_id}).to_list(100)
                    for ev in existing_events:
                        try:
                            ev_start = ev.get("start_time", "")
                            if proposed_dt.lower() in ev_start.lower() or ev_start[:10] == proposed_dt[:10]:
                                matched = True
                                escalation_reasons.append(f"Potential calendar conflict with '{ev.get('title', 'existing event')}'")
                                break
                        except Exception:
                            pass
                # Also trigger if there are many events that day
                if not matched:
                    from datetime import date
                    today_str = date.today().isoformat()
                    today_events = [e for e in await calendar_col.find({"workspace_id": workspace_id}).to_list(100) if today_str in e.get("start_time", "")]
                    if len(today_events) >= 4:
                        matched = True
                        escalation_reasons.append(f"Calendar is busy ({len(today_events)} events today)")
        
        elif rule["condition_type"] == "incomplete_entities":
            # Check if critical entities are missing
            required_fields = [f.strip() for f in rule["condition_value"].split(",")]
            missing = [f for f in required_fields if not entities.get(f)]
            if missing:
                matched = True
                escalation_reasons.append(f"Missing information: {', '.join(missing)}")
        
        elif rule["condition_type"] == "urgency":
            # Check for urgency indicators in the message
            urgency_level = rule["condition_value"].lower()
            found_keywords = [kw for kw in URGENCY_KEYWORDS if kw in text]
            if urgency_level == "any" and found_keywords:
                matched = True
                escalation_reasons.append(f"Urgency detected: {', '.join(found_keywords)}")
            elif urgency_level == "high" and len(found_keywords) >= 2:
                matched = True
                escalation_reasons.append(f"High urgency: {', '.join(found_keywords)}")
        
        elif rule["condition_type"] == "contact_type":
            # Check contact type if linked
            if item.get("contact_id"):
                contact = await contacts_col.find_one({"contact_id": item["contact_id"]})
                if contact and contact.get("type") == rule["condition_value"]:
                    matched = True
                    escalation_reasons.append(f"Contact type match: {rule['condition_value']}")
                elif contact and contact.get("lifecycle_stage") == rule["condition_value"]:
                    matched = True
                    escalation_reasons.append(f"Lifecycle stage match: {rule['condition_value']}")
        
        if matched:
            escalation_info = {
                "rule": rule["name"],
                "route_to": rule["route_to"],
                "priority": rule["priority"],
                "reasons": escalation_reasons if escalation_reasons else [f"Matched {rule['condition_type']}: {rule['condition_value']}"],
            }
            break
    
    return escalation_info

# ─── Seed Data ─────────────────────────────────────────────────────────
async def seed_database():
    count = await inbox_col.count_documents({})
    if count > 0:
        return

    now = datetime.utcnow()

    # Contacts
    contacts = [
        {"contact_id": str(uuid.uuid4()), "name": "Sarah Chen", "email": "sarah.chen@gmail.com", "phone": "555-0101", "type": "client", "lifecycle_stage": "active", "source": "referral", "ghl_sync_status": "synced", "ghl_last_sync": now - timedelta(minutes=12), "created_at": now - timedelta(days=30), "updated_at": now - timedelta(hours=2), "notes": "Looking for waterfront properties. Budget $1.5-2.5M."},
        {"contact_id": str(uuid.uuid4()), "name": "David Park", "email": "david.park@mail.com", "phone": "555-0102", "type": "lead", "lifecycle_stage": "new", "source": "website", "ghl_sync_status": "synced", "ghl_last_sync": now - timedelta(minutes=5), "created_at": now - timedelta(days=2), "updated_at": now - timedelta(hours=1), "notes": "Interested in downtown condos under $500K."},
        {"contact_id": str(uuid.uuid4()), "name": "Linda Vasquez", "email": "linda.v@outlook.com", "phone": "555-0234", "type": "client", "lifecycle_stage": "at_risk", "source": "cold_call", "ghl_sync_status": "pending", "ghl_last_sync": now - timedelta(hours=3), "created_at": now - timedelta(days=60), "updated_at": now - timedelta(minutes=30), "notes": "Frustrated about delayed inspection report. Needs escalation."},
        {"contact_id": str(uuid.uuid4()), "name": "Mark Thompson", "email": "mark.t@realty.co", "phone": "555-0188", "type": "client", "lifecycle_stage": "active", "source": "referral", "ghl_sync_status": "synced", "ghl_last_sync": now - timedelta(minutes=20), "created_at": now - timedelta(days=45), "updated_at": now - timedelta(hours=4), "notes": "Submitted offer for 456 Pine Ave. Awaiting response."},
        {"contact_id": str(uuid.uuid4()), "name": "Emily Rodriguez", "email": "emily.r@homes.com", "phone": "555-0199", "type": "lead", "lifecycle_stage": "nurturing", "source": "open_house", "ghl_sync_status": "synced", "ghl_last_sync": now - timedelta(minutes=45), "created_at": now - timedelta(days=14), "updated_at": now - timedelta(hours=6), "notes": "Attended open house at Maple Ridge. Interested in similar properties."},
        {"contact_id": str(uuid.uuid4()), "name": "Robert Kim", "email": "r.kim@business.net", "phone": "555-0177", "type": "investor", "lifecycle_stage": "active", "source": "network", "ghl_sync_status": "synced", "ghl_last_sync": now - timedelta(minutes=8), "created_at": now - timedelta(days=90), "updated_at": now - timedelta(hours=1), "notes": "Looking for multi-family investment properties. Budget $3-5M."},
    ]
    await contacts_col.insert_many(contacts)

    # Agents
    agents = [
        {"agent_id": str(uuid.uuid4()), "name": "James Rivera", "email": "jrivera@realtyfirm.com", "phone": "555-0192", "role": "agent", "status": "onboarding", "start_date": (now - timedelta(days=3)).isoformat(), "photo_url": None, "created_at": now - timedelta(days=3)},
        {"agent_id": str(uuid.uuid4()), "name": "Aisha Patel", "email": "aisha.p@realtyfirm.com", "phone": "555-0211", "role": "senior_agent", "status": "active", "start_date": (now - timedelta(days=180)).isoformat(), "photo_url": None, "created_at": now - timedelta(days=180)},
        {"agent_id": str(uuid.uuid4()), "name": "Carlos Mendez", "email": "carlos.m@realtyfirm.com", "phone": "555-0223", "role": "agent", "status": "active", "start_date": (now - timedelta(days=90)).isoformat(), "photo_url": None, "created_at": now - timedelta(days=90)},
        {"agent_id": str(uuid.uuid4()), "name": "Sophia Turner", "email": "sophia.t@realtyfirm.com", "phone": "555-0245", "role": "team_lead", "status": "active", "start_date": (now - timedelta(days=365)).isoformat(), "photo_url": None, "created_at": now - timedelta(days=365)},
    ]
    await agents_col.insert_many(agents)

    # Onboarding tasks for James Rivera
    james_id = agents[0]["agent_id"]
    onboarding_tasks = [
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Complete compliance training", "description": "Review and sign all compliance documents", "status": "completed", "order": 1, "completed_at": (now - timedelta(days=1)).isoformat(), "auto_generated": True, "workspace_id": DEFAULT_WORKSPACE_ID},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Set up CRM profile", "description": "Configure GoHighLevel profile and sync", "status": "completed", "order": 2, "completed_at": (now - timedelta(hours=12)).isoformat(), "auto_generated": True, "workspace_id": DEFAULT_WORKSPACE_ID},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Configure email signature", "description": "Set up branded email signature template", "status": "in_progress", "order": 3, "completed_at": None, "auto_generated": True, "workspace_id": DEFAULT_WORKSPACE_ID},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Schedule orientation with team lead", "description": "Book 1:1 orientation meeting with Sophia Turner", "status": "pending", "order": 4, "completed_at": None, "auto_generated": True, "workspace_id": DEFAULT_WORKSPACE_ID},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Access granted to listing portal", "description": "Get login credentials for MLS and listing tools", "status": "pending", "order": 5, "completed_at": None, "auto_generated": True, "workspace_id": DEFAULT_WORKSPACE_ID},
    ]
    await onboarding_col.insert_many(onboarding_tasks)

    # Inbox items (connected to contacts)
    inbox_items = [
        {"inbox_id": str(uuid.uuid4()), "from_name": "Sarah Chen", "from_email": "sarah.chen@gmail.com", "subject": "Property viewing request - 789 Lakeshore Dr", "body": "Hi, I'd like to schedule a viewing for the waterfront estate at 789 Lakeshore Drive this Saturday at 2pm. I've been looking at properties in this range and this one really caught my eye. Thanks!", "received_at": now - timedelta(hours=1), "read": False, "status": "new", "ai_intent": None, "ai_suggested_action": None, "contact_id": contacts[0]["contact_id"], "source": "gmail"},
        {"inbox_id": str(uuid.uuid4()), "from_name": "David Park", "from_email": "david.park@mail.com", "subject": "Downtown condo listings", "body": "Hello, I'm interested in learning more about available listings in the downtown area, preferably 2-bedroom condos under $500K. Could someone from your team get back to me?", "received_at": now - timedelta(hours=3), "read": False, "status": "new", "ai_intent": None, "ai_suggested_action": None, "contact_id": contacts[1]["contact_id"], "source": "gmail"},
        {"inbox_id": str(uuid.uuid4()), "from_name": "Linda Vasquez", "from_email": "linda.v@outlook.com", "subject": "RE: Inspection Report - URGENT", "body": "This is unacceptable. I've been waiting 3 weeks for the inspection report and nobody has gotten back to me. I want to speak to a manager immediately.", "received_at": now - timedelta(hours=2), "read": True, "status": "new", "ai_intent": None, "ai_suggested_action": None, "contact_id": contacts[2]["contact_id"], "source": "gmail"},
        {"inbox_id": str(uuid.uuid4()), "from_name": "Mark Thompson", "from_email": "mark.t@realty.co", "subject": "Offer update - 456 Pine Ave", "body": "Hey, just checking in on the offer we submitted last week for the property at 456 Pine Ave. The buyers are getting anxious. Can we get an update on the seller's response?", "received_at": now - timedelta(hours=5), "read": True, "status": "processed", "ai_intent": {"intent": "follow_up", "confidence": 0.92, "summary": "Requesting update on submitted offer for 456 Pine Ave"}, "ai_suggested_action": {"type": "send_follow_up", "description": "Send follow-up to seller's agent regarding offer status"}, "contact_id": contacts[3]["contact_id"], "source": "gmail"},
        {"inbox_id": str(uuid.uuid4()), "from_name": "James Rivera", "from_email": "jrivera@realtyfirm.com", "subject": "New agent setup request", "body": "Hi, I just joined the team as a new agent. My manager said I should reach out to get my systems set up. Looking forward to getting started!", "received_at": now - timedelta(hours=8), "read": True, "status": "actioned", "ai_intent": {"intent": "onboarding", "confidence": 0.95, "summary": "New agent requesting system setup"}, "ai_suggested_action": {"type": "start_onboarding", "description": "Initiate onboarding workflow for new agent"}, "contact_id": None, "source": "gmail"},
        {"inbox_id": str(uuid.uuid4()), "from_name": "Emily Rodriguez", "from_email": "emily.r@homes.com", "subject": "Similar properties to Maple Ridge?", "body": "Hi there, I attended the open house at Maple Ridge last weekend and loved it. Are there any similar properties available? I'm flexible on timing for a viewing.", "received_at": now - timedelta(hours=4), "read": False, "status": "new", "ai_intent": None, "ai_suggested_action": None, "contact_id": contacts[4]["contact_id"], "source": "gmail"},
    ]
    await inbox_col.insert_many(inbox_items)

    # Calendar events
    calendar_events = [
        {"event_id": str(uuid.uuid4()), "title": "Property viewing - 456 Pine Ave", "description": "Showing with Mark Thompson's clients", "start_time": (now + timedelta(hours=2)).isoformat(), "end_time": (now + timedelta(hours=3)).isoformat(), "location": "456 Pine Ave", "attendees": ["Mark Thompson", "Aisha Patel"], "status": "confirmed", "source": "google_calendar", "created_at": now - timedelta(days=2), "contact_id": contacts[3]["contact_id"]},
        {"event_id": str(uuid.uuid4()), "title": "Team standup", "description": "Weekly team sync", "start_time": (now + timedelta(hours=4)).isoformat(), "end_time": (now + timedelta(hours=4, minutes=30)).isoformat(), "location": "Virtual - Zoom", "attendees": ["Sophia Turner", "Aisha Patel", "Carlos Mendez"], "status": "confirmed", "source": "google_calendar", "created_at": now - timedelta(days=7), "contact_id": None},
        {"event_id": str(uuid.uuid4()), "title": "Client consultation - Robert Kim", "description": "Investment property discussion", "start_time": (now + timedelta(days=1, hours=2)).isoformat(), "end_time": (now + timedelta(days=1, hours=3)).isoformat(), "location": "Office - Conference Room A", "attendees": ["Robert Kim", "Sophia Turner"], "status": "confirmed", "source": "google_calendar", "created_at": now - timedelta(days=1), "contact_id": contacts[5]["contact_id"]},
        {"event_id": str(uuid.uuid4()), "title": "Open house - Maple Ridge", "description": "Weekend open house event", "start_time": (now + timedelta(days=3, hours=5)).isoformat(), "end_time": (now + timedelta(days=3, hours=8)).isoformat(), "location": "Maple Ridge Estate", "attendees": ["Carlos Mendez", "Aisha Patel"], "status": "confirmed", "source": "google_calendar", "created_at": now - timedelta(days=5), "contact_id": None},
        {"event_id": str(uuid.uuid4()), "title": "Onboarding - James Rivera", "description": "New agent orientation session", "start_time": (now + timedelta(days=1, hours=5)).isoformat(), "end_time": (now + timedelta(days=1, hours=6)).isoformat(), "location": "Office - Training Room", "attendees": ["James Rivera", "Sophia Turner"], "status": "pending", "source": "system", "created_at": now - timedelta(hours=6), "contact_id": None},
    ]
    await calendar_col.insert_many(calendar_events)

    # Content items
    content_items = [
        {"content_id": str(uuid.uuid4()), "type": "social_post", "title": "New Listing - 789 Lakeshore Dr", "content": {"text": "Discover luxury waterfront living at 789 Lakeshore Drive. This stunning 5-bedroom estate features an infinity pool and smart home system.", "hashtags": ["#LuxuryLiving", "#WaterfrontEstate", "#DreamHome"], "platform": "instagram"}, "status": "draft", "created_at": now - timedelta(hours=6), "created_by": "ai", "workspace_id": DEFAULT_WORKSPACE_ID},
        {"content_id": str(uuid.uuid4()), "type": "email_draft", "title": "Q4 Market Update", "content": {"subject": "Your Q4 Real Estate Market Update", "body": "Dear valued clients,\n\nAs we close out Q4, the market continues to show strong momentum. Prices are up 3% in our metro area, and inventory remains tight.\n\nThis presents an excellent opportunity for sellers looking to capitalize on current demand. For buyers, acting quickly on well-priced properties is key.\n\nLet's schedule a call to discuss how these trends affect your real estate goals.", "call_to_action": "Schedule a consultation"}, "status": "published", "created_at": now - timedelta(days=2), "created_by": "ai", "workspace_id": DEFAULT_WORKSPACE_ID},
        {"content_id": str(uuid.uuid4()), "type": "social_post", "title": "Team Spotlight - Aisha Patel", "content": {"text": "Meet Aisha Patel, one of our senior agents with 5+ years of experience. She specializes in helping first-time homebuyers navigate the market with confidence.", "hashtags": ["#MeetTheTeam", "#RealEstateAgent", "#FirstTimeHomeBuyer"], "platform": "linkedin"}, "status": "draft", "created_at": now - timedelta(hours=12), "created_by": "ai", "workspace_id": DEFAULT_WORKSPACE_ID},
    ]
    await content_col.insert_many(content_items)

    # Activity events
    activity_events = [
        {"event_id": str(uuid.uuid4()), "event_type": "system", "title": "System initialized", "description": "Quantro Flow OS started successfully. All services running.", "related_id": None, "related_type": None, "timestamp": now - timedelta(hours=12)},
        {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New message received", "description": "Email from Sarah Chen: Property viewing request", "related_id": inbox_items[0]["inbox_id"], "related_type": "inbox", "timestamp": now - timedelta(hours=1)},
        {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New message received", "description": "Email from Linda Vasquez: Urgent escalation", "related_id": inbox_items[2]["inbox_id"], "related_type": "inbox", "timestamp": now - timedelta(hours=2)},
        {"event_id": str(uuid.uuid4()), "event_type": "ai", "title": "AI processed inbox", "description": "Intent detected: follow_up for Mark Thompson's message", "related_id": inbox_items[3]["inbox_id"], "related_type": "inbox", "timestamp": now - timedelta(hours=4, minutes=50)},
        {"event_id": str(uuid.uuid4()), "event_type": "ai", "title": "AI processed inbox", "description": "Intent detected: onboarding for James Rivera's request", "related_id": inbox_items[4]["inbox_id"], "related_type": "inbox", "timestamp": now - timedelta(hours=7, minutes=45)},
        {"event_id": str(uuid.uuid4()), "event_type": "onboarding", "title": "Onboarding started", "description": "New agent James Rivera - onboarding workflow initiated", "related_id": james_id, "related_type": "agent", "timestamp": now - timedelta(hours=7, minutes=30)},
        {"event_id": str(uuid.uuid4()), "event_type": "crm", "title": "CRM synced", "description": "6 contacts synced with GoHighLevel. 0 conflicts.", "related_id": None, "related_type": "crm", "timestamp": now - timedelta(minutes=12)},
        {"event_id": str(uuid.uuid4()), "event_type": "content", "title": "Content generated", "description": "AI created social post for 789 Lakeshore Dr listing", "related_id": content_items[0]["content_id"], "related_type": "content", "timestamp": now - timedelta(hours=6)},
        {"event_id": str(uuid.uuid4()), "event_type": "calendar", "title": "Event scheduled", "description": "Property viewing at 456 Pine Ave confirmed for today", "related_id": calendar_events[0]["event_id"], "related_type": "calendar", "timestamp": now - timedelta(days=2)},
        {"event_id": str(uuid.uuid4()), "event_type": "system", "title": "All systems running", "description": "Gmail sync active. Calendar sync active. CRM sync healthy.", "related_id": None, "related_type": None, "timestamp": now - timedelta(minutes=1)},
    ]
    await activity_col.insert_many(activity_events)

    # Automation Policies (per-intent rules)
    policies = [
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "booking", "action": "auto_run", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "auto_run", "medium_action": "require_approval", "low_action": "escalate", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "follow_up", "action": "require_approval", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "require_approval", "medium_action": "require_approval", "low_action": "escalate", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "onboarding", "action": "require_approval", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "require_approval", "medium_action": "require_approval", "low_action": "escalate", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "inquiry", "action": "manual_review", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "manual_review", "medium_action": "manual_review", "low_action": "escalate", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "escalation", "action": "escalate", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "escalate", "medium_action": "escalate", "low_action": "escalate", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "spam", "action": "auto_run", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "auto_run", "medium_action": "manual_review", "low_action": "manual_review", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "policy_id": str(uuid.uuid4()), "intent": "needs_review", "action": "manual_review", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "manual_review", "medium_action": "manual_review", "low_action": "escalate", "enabled": True, "created_at": now},
    ]
    await policies_col.insert_many(policies)

    # Escalation Rules
    escalation_rules = [
        {"workspace_id": DEFAULT_WORKSPACE_ID, "rule_id": str(uuid.uuid4()), "name": "Urgent recruiting leads", "condition_type": "intent", "condition_value": "onboarding", "route_to": "Larry", "priority": "high", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "rule_id": str(uuid.uuid4()), "name": "Incomplete onboarding data", "condition_type": "keyword", "condition_value": "incomplete,missing,setup", "route_to": "Ops/Admin", "priority": "normal", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "rule_id": str(uuid.uuid4()), "name": "Calendar conflicts", "condition_type": "keyword", "condition_value": "conflict,reschedule,cancel", "route_to": "Manual Review", "priority": "normal", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "rule_id": str(uuid.uuid4()), "name": "Escalation requests", "condition_type": "intent", "condition_value": "escalation", "route_to": "Sophia Turner", "priority": "critical", "enabled": True, "created_at": now},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "rule_id": str(uuid.uuid4()), "name": "High-value investor inquiries", "condition_type": "keyword", "condition_value": "investor,investment,portfolio", "route_to": "Sophia Turner", "priority": "high", "enabled": True, "created_at": now},
    ]
    await escalation_col.insert_many(escalation_rules)

    # Content Templates
    templates = [
        {"workspace_id": DEFAULT_WORKSPACE_ID, "template_id": str(uuid.uuid4()), "name": "Welcome Email", "category": "welcome", "template_type": "email", "subject_template": "Welcome to our team, {{contact_name}}!", "body_template": "Dear {{contact_name}},\n\nWelcome to the team! We're thrilled to have you on board.\n\n{{situation}}\n\nPlease don't hesitate to reach out if you need anything during your transition. We're here to help you succeed.\n\nBest regards,\nThe Quantro Team", "variables": ["contact_name", "situation"], "tags": ["onboarding", "welcome"], "status": "active", "created_at": now, "created_by": "system"},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "template_id": str(uuid.uuid4()), "name": "Follow-up Message", "category": "follow_up", "template_type": "email", "subject_template": "Following up: {{subject}}", "body_template": "Hi {{contact_name}},\n\nI wanted to follow up on {{subject}}. {{situation}}\n\nPlease let me know if you have any questions or if there's anything else I can help with.\n\nBest,\nThe Quantro Team", "variables": ["contact_name", "subject", "situation"], "tags": ["follow-up", "client"], "status": "active", "created_at": now, "created_by": "system"},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "template_id": str(uuid.uuid4()), "name": "Recruiting Message", "category": "recruiting", "template_type": "email", "subject_template": "Exciting opportunity at our firm", "body_template": "Hi {{contact_name}},\n\nWe're expanding our team and your profile caught our attention. {{situation}}\n\nWe'd love to discuss how you could be a great fit for our growing real estate team. Would you be available for a brief call this week?\n\nLooking forward to connecting,\nThe Quantro Team", "variables": ["contact_name", "situation"], "tags": ["recruiting", "agent"], "status": "active", "created_at": now, "created_by": "system"},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "template_id": str(uuid.uuid4()), "name": "New Listing Social Post", "category": "social", "template_type": "social_post", "subject_template": None, "body_template": "Just listed! {{property_details}}. {{highlight}}. Contact us today for a private showing. #NewListing #RealEstate #{{location}}", "variables": ["property_details", "highlight", "location"], "tags": ["listing", "social"], "status": "active", "created_at": now, "created_by": "system"},
        {"workspace_id": DEFAULT_WORKSPACE_ID, "template_id": str(uuid.uuid4()), "name": "Market Update Post", "category": "market_update", "template_type": "social_post", "subject_template": None, "body_template": "Market Update: {{market_data}}. {{insight}}. Whether you're buying or selling, now is the time to strategize. #MarketUpdate #RealEstate", "variables": ["market_data", "insight"], "tags": ["market", "social", "update"], "status": "active", "created_at": now, "created_by": "system"},
    ]
    await templates_col.insert_many(templates)

    # Business Profile (default - industry agnostic)
    business_profile = {
        "profile_id": "default",
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "industry": "other",
        "use_case": "General business operations and workflow management",
        "entity_labels": {
            "contacts": "Contacts",
            "team_members": "Team Members",
            "meetings": "Meetings",
            "events": "Events",
            "services": "Services"
        },
        "simulation_mode": False,
        "language": "es",
        "created_at": now,
        "updated_at": now
    }
    await business_profile_col.insert_one(business_profile)

    # Integrations Config (default - all disconnected, workspace-scoped)
    integrations = [
        {"integration_id": str(uuid.uuid4()), "workspace_id": DEFAULT_WORKSPACE_ID, "provider": "gmail", "status": "disconnected", "last_sync_at": None, "config": {}, "created_at": now, "updated_at": now},
        {"integration_id": str(uuid.uuid4()), "workspace_id": DEFAULT_WORKSPACE_ID, "provider": "crm", "status": "disconnected", "last_sync_at": None, "config": {}, "created_at": now, "updated_at": now},
    ]
    await integrations_config_col.insert_many(integrations)

    print("Seeded database with connected mock data")

# ─── Pydantic Models ───────────────────────────────────────────────────
class CreateEventRequest(BaseModel):
    title: str
    description: str = ""
    start_time: str
    end_time: str
    location: str = ""
    attendees: List[str] = []
    contact_id: Optional[str] = None

class CreateAgentRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    role: str = "agent"

class UpdateOnboardingTaskRequest(BaseModel):
    status: str

class ContentGenerateRequest(BaseModel):
    prompt: str
    type: str = "both"  # social_post, email_draft, or both

class CreateContactRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    type: str = "lead"
    source: str = "manual"
    notes: str = ""

class BatchAnalyzeRequest(BaseModel):
    inbox_ids: List[str]

class UpdateInboxDetailsRequest(BaseModel):
    """Manual override for AI-extracted entities and suggested action"""
    entities: Optional[dict] = None
    suggested_action_type: Optional[str] = None
    suggested_action_description: Optional[str] = None
    summary: Optional[str] = None

class ApproveWithOverridesRequest(BaseModel):
    """Approve with optional manual overrides"""
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

# Legacy → canonical policy-action aliases. AutomationPolicies.js (frontend)
# sends 'auto_execute' as its "auto" mode value; the auto-execute checks
# throughout this file compare against 'auto_run'. Before this alias map,
# a policy saved with mode "Auto-execute" from the UI silently never
# auto-executed — found during the Quantro Connect/Actions Phase 0 audit.
# _normalize_policy_action() is the single place that reconciles the two,
# applied on both read (evaluate_policy_for_item, analyze/batch-analyze)
# and write (create_policy/update_policy) so stored data converges on
# the canonical value without a data migration.
POLICY_ACTION_ALIASES = {
    "auto_execute": "auto_run",
    "auto_run": "auto_run",
    "require_approval": "require_approval",
    "manual_review": "manual_review",
    "suggest_only": "manual_review",
    "escalate": "escalate",
}


def _normalize_policy_action(action: Optional[str]) -> str:
    return POLICY_ACTION_ALIASES.get((action or "").lower().strip(), action or "manual_review")


class AutomationPolicyRequest(BaseModel):
    intent: str
    action: str  # auto_run, require_approval, manual_review, escalate
    confidence_threshold_high: float = 0.85
    confidence_threshold_medium: float = 0.6
    high_action: str = "auto_run"
    medium_action: str = "require_approval"
    low_action: str = "escalate"
    enabled: bool = True

class EscalationRuleRequest(BaseModel):
    name: str
    condition_type: str  # intent, keyword, confidence, contact_type
    condition_value: str
    route_to: str  # person name or team
    priority: str = "normal"  # normal, high, critical
    enabled: bool = True

class ContentTemplateRequest(BaseModel):
    name: str
    category: str  # welcome, follow_up, recruiting, social, market_update
    template_type: str  # email, social_post
    subject_template: Optional[str] = None
    body_template: str
    variables: List[str] = []
    tags: List[str] = []

class GenerateFromTemplateRequest(BaseModel):
    template_id: str
    context: dict = {}  # e.g. {"contact_name": "Sarah", "situation": "new lead"}

# ─── Integrations Catalog (self-healing) ───────────────────────────────
DEFAULT_INTEGRATIONS_CATALOG = [
    {"provider": "gmail",            "category": "email",        "display_name": "Gmail"},
    {"provider": "google_calendar",  "category": "calendar",     "display_name": "Google Calendar"},
    {"provider": "crm",              "category": "crm",          "display_name": "CRM (HubSpot / GoHighLevel)"},
    {"provider": "openai",           "category": "ai",           "display_name": "OpenAI / LLM Provider"},
    {"provider": "webhook",          "category": "automation",   "display_name": "Webhooks & Endpoints"},
]

# ─── Default Automation Policies / Escalation Rules / Templates ───────
# Seeded into every new workspace (and back-filled into existing ones with
# zero policies) so onboarding never leaves a client with an empty
# automation setup. Mirrors the shape used by the legacy seed_database().
DEFAULT_AUTOMATION_POLICIES = [
    {"intent": "booking", "action": "auto_run", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "auto_run", "medium_action": "require_approval", "low_action": "escalate"},
    {"intent": "follow_up", "action": "require_approval", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "require_approval", "medium_action": "require_approval", "low_action": "escalate"},
    {"intent": "onboarding", "action": "require_approval", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "require_approval", "medium_action": "require_approval", "low_action": "escalate"},
    {"intent": "inquiry", "action": "manual_review", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "manual_review", "medium_action": "manual_review", "low_action": "escalate"},
    {"intent": "escalation", "action": "escalate", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "escalate", "medium_action": "escalate", "low_action": "escalate"},
    {"intent": "spam", "action": "auto_run", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "auto_run", "medium_action": "manual_review", "low_action": "manual_review"},
    {"intent": "needs_review", "action": "manual_review", "confidence_threshold_high": 0.85, "confidence_threshold_medium": 0.6, "high_action": "manual_review", "medium_action": "manual_review", "low_action": "escalate"},
]

DEFAULT_ESCALATION_RULES = [
    {"name": "Urgent recruiting leads", "condition_type": "intent", "condition_value": "onboarding", "route_to": "Team Lead", "priority": "high"},
    {"name": "Incomplete onboarding data", "condition_type": "keyword", "condition_value": "incomplete,missing,setup", "route_to": "Ops/Admin", "priority": "normal"},
    {"name": "Calendar conflicts", "condition_type": "keyword", "condition_value": "conflict,reschedule,cancel", "route_to": "Manual Review", "priority": "normal"},
    {"name": "Escalation requests", "condition_type": "intent", "condition_value": "escalation", "route_to": "Team Lead", "priority": "critical"},
    {"name": "High-value investor inquiries", "condition_type": "keyword", "condition_value": "investor,investment,portfolio", "route_to": "Team Lead", "priority": "high"},
]

DEFAULT_CONTENT_TEMPLATES = [
    {"name": "Welcome Email", "category": "welcome", "template_type": "email", "subject_template": "Welcome to our team, {{contact_name}}!", "body_template": "Dear {{contact_name}},\n\nWelcome to the team! We're thrilled to have you on board.\n\n{{situation}}\n\nPlease don't hesitate to reach out if you need anything during your transition. We're here to help you succeed.\n\nBest regards,\nThe Team", "variables": ["contact_name", "situation"], "tags": ["onboarding", "welcome"]},
    {"name": "Follow-up Message", "category": "follow_up", "template_type": "email", "subject_template": "Following up: {{subject}}", "body_template": "Hi {{contact_name}},\n\nI wanted to follow up on {{subject}}. {{situation}}\n\nPlease let me know if you have any questions or if there's anything else I can help with.\n\nBest,\nThe Team", "variables": ["contact_name", "subject", "situation"], "tags": ["follow-up", "client"]},
    {"name": "Recruiting Message", "category": "recruiting", "template_type": "email", "subject_template": "Exciting opportunity at our firm", "body_template": "Hi {{contact_name}},\n\nWe're expanding our team and your profile caught our attention. {{situation}}\n\nWe'd love to discuss how you could be a great fit for our growing team. Would you be available for a brief call this week?\n\nLooking forward to connecting", "variables": ["contact_name", "situation"], "tags": ["recruiting"]},
    {"name": "New Listing Social Post", "category": "social", "template_type": "social_post", "subject_template": None, "body_template": "Just listed! {{property_details}}. {{highlight}}. Contact us today for a private showing. #NewListing #{{location}}", "variables": ["property_details", "highlight", "location"], "tags": ["listing", "social"]},
    {"name": "Market Update Post", "category": "market_update", "template_type": "social_post", "subject_template": None, "body_template": "Market Update: {{market_data}}. {{insight}}. Whether you're buying or selling, now is the time to strategize. #MarketUpdate", "variables": ["market_data", "insight"], "tags": ["market", "social", "update"]},
]

async def ensure_integrations_seeded():
    """Idempotently ensure every provider in the catalog has a row.
    Self-healing: this runs on every startup so missing rows are created even
    if the main seed_database() was skipped because inbox already had data.
    Every repair is logged to `system_health_events` so the UI can surface
    the 'Quantro OS detects and fixes issues before you notice them' trust signal."""
    now = datetime.utcnow()
    repairs = []  # Events: [{type, provider, detail}]

    for item in DEFAULT_INTEGRATIONS_CATALOG:
        existing = await integrations_config_col.find_one({"workspace_id": DEFAULT_WORKSPACE_ID, "provider": item["provider"]})
        if not existing:
            await integrations_config_col.insert_one({
                "integration_id": str(uuid.uuid4()),
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "provider": item["provider"],
                "category": item["category"],
                "display_name": item["display_name"],
                "status": "disconnected",
                "last_sync_at": None,
                "config": {},
                "created_at": now,
                "updated_at": now,
            })
            repairs.append({
                "type": "provider_restored",
                "provider": item["provider"],
                "detail": f"Missing integration '{item['display_name']}' was restored automatically.",
            })
        else:
            patch = {}
            if not existing.get("category"):
                patch["category"] = item["category"]
            if not existing.get("display_name"):
                patch["display_name"] = item["display_name"]
            if not existing.get("workspace_id"):
                patch["workspace_id"] = DEFAULT_WORKSPACE_ID
            if patch:
                await integrations_config_col.update_one(
                    {"_id": existing["_id"]}, {"$set": patch}
                )
                repairs.append({
                    "type": "metadata_backfilled",
                    "provider": item["provider"],
                    "detail": f"Metadata repaired for '{existing.get('display_name') or item['display_name']}' ({', '.join(patch.keys())}).",
                })

    # Always log a check event (healthy = repairs is empty)
    await system_health_col.insert_one({
        "event_id": str(uuid.uuid4()),
        "scope": "integrations",
        "status": "repaired" if repairs else "healthy",
        "repairs": repairs,
        "repair_count": len(repairs),
        "checked_at": now,
    })
    # Keep only the latest 50 events to avoid unbounded growth
    old_events = await system_health_col.find({}, {"_id": 1}).sort("checked_at", -1).skip(50).to_list(1000)
    if old_events:
        await system_health_col.delete_many({"_id": {"$in": [e["_id"] for e in old_events]}})

# ─── Simulation Data Backfill (one-time, idempotent) ──────────────────
# Historically, `seed_database()` inserted demo records WITHOUT the
# `is_simulation` flag. To enforce strict Simulation vs Live isolation we
# retro-flag any legacy record missing this field as `is_simulation=True`.
# This runs on every startup and is a no-op once applied. Real records
# created by the user in Live Mode always set `is_simulation=False`
# explicitly, so they are never touched by this backfill.
BACKFILLED_COLLECTIONS = [
    "contacts",
    "inbox_items",
    "calendar_events",
    "agents",
    "activity_events",
    "content_items",
    "onboarding_tasks",
]


async def backfill_simulation_flag():
    """Mark legacy un-flagged operational records as simulation data.

    Only records where `is_simulation` does not exist are updated. Records
    that already have `is_simulation: True` or `is_simulation: False` are
    left untouched, so user-created live records remain in Live Mode."""
    repaired = {}
    for name in BACKFILLED_COLLECTIONS:
        col = db[name]
        res = await col.update_many(
            {"is_simulation": {"$exists": False}},
            {"$set": {"is_simulation": True}},
        )
        if res.modified_count:
            repaired[name] = res.modified_count
    if repaired:
        try:
            await system_health_col.insert_one({
                "event_id": str(uuid.uuid4()),
                "scope": "data_isolation",
                "status": "repaired",
                "repairs": [
                    {"type": "simulation_flag_backfilled", "provider": k, "detail": f"{v} legacy records tagged as simulation"}
                    for k, v in repaired.items()
                ],
                "repair_count": sum(repaired.values()),
                "checked_at": datetime.utcnow(),
            })
        except Exception:
            pass
    return repaired


# ─── Phase 7a: Workspace Scoping Backfill ─────────────────────────────
# All operational + config records must carry `workspace_id`. Legacy
# pre-Phase-7 data is tagged as belonging to DEFAULT_WORKSPACE_ID so the
# first authenticated user can claim it seamlessly.
WORKSPACE_SCOPED_COLLECTIONS = [
    "contacts", "inbox_items", "calendar_events", "agents",
    "activity_events", "content_items", "onboarding_tasks",
    "automation_policies", "escalation_rules", "content_templates",
    "integrations_config", "business_profile", "system_health_events",
]


async def backfill_workspace_scoping():
    """Idempotently tag legacy records with workspace_id=DEFAULT_WORKSPACE_ID."""
    for name in WORKSPACE_SCOPED_COLLECTIONS:
        col = db[name]
        await col.update_many(
            {"workspace_id": {"$exists": False}},
            {"$set": {"workspace_id": DEFAULT_WORKSPACE_ID}},
        )
    # Ensure the default business profile document exists with workspace_id.
    existing = await business_profile_col.find_one({"workspace_id": DEFAULT_WORKSPACE_ID})
    if not existing:
        # Promote the legacy {profile_id: "default"} doc (if any) to the default workspace.
        legacy = await business_profile_col.find_one({"profile_id": "default"})
        if legacy:
            await business_profile_col.update_one(
                {"_id": legacy["_id"]}, {"$set": {"workspace_id": DEFAULT_WORKSPACE_ID}}
            )
    # Ensure a pre-claim workspace shell exists so the first user can claim it.
    ws = await workspaces_col.find_one({"workspace_id": DEFAULT_WORKSPACE_ID})
    if not ws:
        await workspaces_col.insert_one({
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "name": "Personal Workspace",
            "owner_user_id": None,   # unclaimed
            "created_at": datetime.now(timezone.utc),
            "claimed": False,
        })

    # Safety net: every existing workspace must have its integrations catalog and business_profile.
    # This heals legacy/manually-inserted workspaces that may be missing config rows.
    all_workspaces = await workspaces_col.find({}, {"_id": 0, "workspace_id": 1}).to_list(1000)
    for w in all_workspaces:
        wid = w.get("workspace_id")
        if wid:
            await seed_workspace_config(wid)


async def seed_workspace_config(workspace_id: str, *, industry: str = "other", language: str = "es"):
    """Create the baseline business_profile + integrations_config + policies
    for a brand-new workspace. Idempotent: never overwrites existing configs."""
    now = datetime.now(timezone.utc)

    # Business profile
    bp = await business_profile_col.find_one({"workspace_id": workspace_id})
    if not bp:
        await business_profile_col.insert_one({
            "workspace_id": workspace_id,
            "profile_id": workspace_id,  # kept for backward compat
            "industry": industry,
            "use_case": "",
            "entity_labels": {
                "contacts": "Contacts",
                "team_members": "Team Members",
                "meetings": "Meetings",
                "events": "Events",
                "services": "Services",
            },
            "simulation_mode": False,
            "language": language,
            "created_at": now,
            "updated_at": now,
        })

    # Integrations catalog (one row per provider for this workspace)
    for item in DEFAULT_INTEGRATIONS_CATALOG:
        existing = await integrations_config_col.find_one({
            "workspace_id": workspace_id, "provider": item["provider"]
        })
        if not existing:
            await integrations_config_col.insert_one({
                "integration_id": str(uuid.uuid4()),
                "workspace_id": workspace_id,
                "provider": item["provider"],
                "category": item["category"],
                "display_name": item["display_name"],
                "status": "disconnected",
                "last_sync_at": None,
                "config": {},
                "created_at": now,
                "updated_at": now,
            })

    # Automation policies (default per-intent rules) — idempotent per intent.
    for p in DEFAULT_AUTOMATION_POLICIES:
        existing = await policies_col.find_one({"workspace_id": workspace_id, "intent": p["intent"]})
        if not existing:
            await policies_col.insert_one({
                "workspace_id": workspace_id,
                "policy_id": str(uuid.uuid4()),
                "intent": p["intent"],
                "action": p["action"],
                "confidence_threshold_high": p["confidence_threshold_high"],
                "confidence_threshold_medium": p["confidence_threshold_medium"],
                "high_action": p["high_action"],
                "medium_action": p["medium_action"],
                "low_action": p["low_action"],
                "enabled": True,
                "created_at": now,
            })

    # Escalation rules — idempotent per rule name.
    for r in DEFAULT_ESCALATION_RULES:
        existing = await escalation_col.find_one({"workspace_id": workspace_id, "name": r["name"]})
        if not existing:
            await escalation_col.insert_one({
                "workspace_id": workspace_id,
                "rule_id": str(uuid.uuid4()),
                "name": r["name"],
                "condition_type": r["condition_type"],
                "condition_value": r["condition_value"],
                "route_to": r["route_to"],
                "priority": r["priority"],
                "enabled": True,
                "created_at": now,
            })

    # Content templates — idempotent per template name.
    for tpl in DEFAULT_CONTENT_TEMPLATES:
        existing = await templates_col.find_one({"workspace_id": workspace_id, "name": tpl["name"]})
        if not existing:
            await templates_col.insert_one({
                "workspace_id": workspace_id,
                "template_id": str(uuid.uuid4()),
                "name": tpl["name"],
                "category": tpl["category"],
                "template_type": tpl["template_type"],
                "subject_template": tpl["subject_template"],
                "body_template": tpl["body_template"],
                "variables": tpl["variables"],
                "tags": tpl["tags"],
                "status": "active",
                "created_at": now,
                "created_by": "system",
            })


async def backfill_workspace_automations():
    """Startup safety net: any workspace that has zero automation policies
    (e.g. created before this seeding logic existed, or via an edge case
    that skipped seed_workspace_config) gets the default policies/rules/
    templates retro-fitted. Idempotent — safe to run on every startup."""
    cursor = workspaces_col.find({}, {"_id": 0, "workspace_id": 1})
    workspace_ids = [w["workspace_id"] async for w in cursor]
    backfilled = []
    for wid in workspace_ids:
        count = await policies_col.count_documents({"workspace_id": wid})
        if count == 0:
            await seed_workspace_config(wid)
            backfilled.append(wid)
    if backfilled:
        print(f"[startup] Backfilled default automations for {len(backfilled)} workspace(s): {backfilled}")
    return backfilled


async def claim_or_create_workspace_for_user(user_doc: dict) -> str:
    """On first login, give the user a workspace.

    - If the DEFAULT_WORKSPACE_ID is still unclaimed → user becomes its Owner
      (inherits all existing seeded data cleanly).
    - Otherwise → create a fresh personal workspace + seed its config.

    Always ensures a membership row exists. Returns the workspace_id the user
    should land in by default."""
    user_id = user_doc["user_id"]
    existing_member = await workspace_members_col.find_one({"user_id": user_id})
    if existing_member:
        return existing_member["workspace_id"]

    default_ws = await workspaces_col.find_one({"workspace_id": DEFAULT_WORKSPACE_ID})
    if default_ws and not default_ws.get("claimed"):
        # Claim the default workspace.
        await workspaces_col.update_one(
            {"workspace_id": DEFAULT_WORKSPACE_ID},
            {"$set": {
                "name": f"{user_doc.get('name') or 'My'} Workspace",
                "owner_user_id": user_id,
                "claimed": True,
                "claimed_at": datetime.now(timezone.utc),
            }},
        )
        await workspace_members_col.insert_one({
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "user_id": user_id,
            "role": "owner",
            "joined_at": datetime.now(timezone.utc),
        })
        await log_audit(
            "workspace.claimed",
            f"{user_doc.get('email')} claimed the default workspace",
            user_id=user_id, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        return DEFAULT_WORKSPACE_ID

    # Otherwise create a fresh personal workspace for this user.
    new_ws_id = f"ws_{uuid.uuid4().hex[:12]}"
    await workspaces_col.insert_one({
        "workspace_id": new_ws_id,
        "name": f"{user_doc.get('name') or 'My'} Workspace",
        "owner_user_id": user_id,
        "created_at": datetime.now(timezone.utc),
        "claimed": True,
        "claimed_at": datetime.now(timezone.utc),
    })
    await workspace_members_col.insert_one({
        "workspace_id": new_ws_id,
        "user_id": user_id,
        "role": "owner",
        "joined_at": datetime.now(timezone.utc),
    })
    await seed_workspace_config(new_ws_id)
    await log_audit(
        "workspace.created",
        f"{user_doc.get('email')} created a new personal workspace",
        user_id=user_id, workspace_id=new_ws_id,
    )
    return new_ws_id


async def reconcile_supabase_memberships_to_mongo(user_doc: dict) -> Optional[str]:
    """Phase 7c — Supabase-first workspace resolution.

    On every login, check whether this user already belongs to any org
    in Supabase ``org_members``. If so, mirror those memberships into
    the Mongo ``workspace_members`` collection (which is still the DB
    the runtime reads from by default), and return the primary
    ``workspace_id`` the user should land in.

    How each org is translated to a workspace_id (lookup order):
      1. A Mongo ``workspaces`` row already has ``org_id`` pointing at
         this Supabase org → use that workspace_id.
      2. The org is the configured default org
         (``QUANTRO_DEFAULT_ORG_ID``) → promote the ``DEFAULT_WORKSPACE_ID``
         Mongo row to carry that ``org_id`` and use it.
      3. No mapping exists → create a fresh Mongo workspace with
         ``org_id`` already set, then seed config.

    The user's role in Mongo is *always* synced to match Supabase — so
    role changes made through the Supabase-backed admin UI are reflected
    even while Mongo is the primary read source. Returns ``None`` if the
    user has no Supabase memberships (legacy flow continues).
    """
    user_id = user_doc.get("user_id")
    if not user_id:
        return None

    try:
        sb_rows = await supabase_admin.list_orgs_for_user(user_id)
    except Exception:  # noqa: BLE001 — best-effort, never block login
        sb_rows = []
    if not sb_rows:
        return None

    default_org_id = supabase_admin.resolve_default_org_id()
    primary_ws_id: Optional[str] = None

    for row in sb_rows:
        org_id = row.get("org_id")
        role = _normalize_role(row.get("role"))
        if not org_id:
            continue

        # 1) Prefer an existing workspaces row that already carries this
        #    org_id (covers per-workspace overrides + the one-off patch
        #    we apply to the default workspace).
        ws = await workspaces_col.find_one(
            {"org_id": org_id}, {"_id": 0, "workspace_id": 1}
        )

        # 2) Promote the DEFAULT_WORKSPACE_ID row if it's the default org
        #    but hasn't been tagged yet (one-time on first reconciliation).
        if not ws and default_org_id and org_id == default_org_id:
            await workspaces_col.update_one(
                {"workspace_id": DEFAULT_WORKSPACE_ID},
                {"$set": {"org_id": org_id}},
            )
            ws = await workspaces_col.find_one(
                {"workspace_id": DEFAULT_WORKSPACE_ID},
                {"_id": 0, "workspace_id": 1},
            )

        # 3) Still nothing → mint a new workspace for this org. Name it
        #    after the user as a safe default (owner can rename later).
        if not ws:
            new_ws_id = f"ws_{uuid.uuid4().hex[:12]}"
            await workspaces_col.insert_one({
                "workspace_id": new_ws_id,
                "name": f"{user_doc.get('name') or 'Workspace'}",
                "owner_user_id": user_id if role == "owner" else None,
                "org_id": org_id,
                "created_at": datetime.now(timezone.utc),
                "claimed": True,
                "claimed_at": datetime.now(timezone.utc),
            })
            await seed_workspace_config(new_ws_id)
            ws = {"workspace_id": new_ws_id}

        ws_id = ws["workspace_id"]

        # Upsert the membership in Mongo so the rest of the backend
        # (which still reads from workspace_members_col) can find it.
        # We always trust Supabase's role here — this is the whole point
        # of the reconciliation pass.
        now = datetime.now(timezone.utc)
        joined_iso = row.get("joined_at")
        try:
            joined_at = (
                datetime.fromisoformat(str(joined_iso).replace("Z", "+00:00"))
                if joined_iso
                else now
            )
        except Exception:  # noqa: BLE001
            joined_at = now
        await workspace_members_col.update_one(
            {"workspace_id": ws_id, "user_id": user_id},
            {
                "$set": {"role": role, "source": "supabase_sync"},
                "$setOnInsert": {"joined_at": joined_at},
            },
            upsert=True,
        )

        if primary_ws_id is None:
            primary_ws_id = ws_id

    return primary_ws_id


# ─── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_database()
    await ensure_integrations_seeded()
    await backfill_simulation_flag()
    await backfill_workspace_scoping()
    await migrate_legacy_role_names()
    await backfill_workspace_automations()
    # Phase 7e — Background sync scheduler. We launch a single asyncio
    # task that wakes up every PERIODIC_SYNC_INTERVAL_SECS and calls the
    # provider-specific sync helpers for every workspace whose
    # integration row doesn't have ``auto_sync_paused: True``. Using an
    # in-process task (instead of apscheduler/celery) is intentional:
    # one process per backend pod is enough for our scale today, and it
    # keeps the deploy story trivial. If we ever need multi-pod sync
    # we'll switch to a Mongo lock or move to a real worker.
    sync_task = asyncio.create_task(_periodic_provider_sync_loop())
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        client.close()


# ─── Periodic provider sync (Phase 7e) ────────────────────────────────
PERIODIC_SYNC_INTERVAL_SECS = int(
    os.environ.get("PERIODIC_SYNC_INTERVAL_SECS") or 15 * 60
)


async def _perform_google_sync_for_workspace(workspace_id: str) -> Dict[str, Any]:
    """Run the same sync logic as POST /api/integrations/google/sync but
    suitable to call from the scheduler (no Request/User context). The
    auth audit/trail is intentionally lighter here — we only log
    failures to keep the log readable."""
    creds, doc = await _load_google_credentials(workspace_id)
    if not creds or not doc:
        return {"workspace_id": workspace_id, "skipped": "not_connected"}
    if doc.get("auto_sync_paused"):
        return {"workspace_id": workspace_id, "skipped": "paused"}

    counts = {"emails": 0, "events": 0}
    now = datetime.now(timezone.utc)
    try:
        emails = goog.fetch_recent_gmail(creds, limit=50)
        for m in emails:
            await inbox_col.update_one(
                {"workspace_id": workspace_id, "gmail_id": m["gmail_id"]},
                {
                    "$set": {
                        "workspace_id": workspace_id, "source": "gmail",
                        "gmail_id": m["gmail_id"], "thread_id": m["thread_id"],
                        "from_name": m["from_name"], "from_address": m["from_address"],
                        "subject": m["subject"], "preview": m["snippet"],
                        "received_at": m["date_iso"], "label_ids": m["label_ids"],
                        "is_real": True, "is_simulation": False, "synced_at": now,
                    },
                    "$setOnInsert": {"id": str(uuid.uuid4()), "status": "new", "priority": "medium", "created_at": now},
                },
                upsert=True,
            )
            counts["emails"] += 1
        events = goog.fetch_upcoming_calendar(creds, days=30)
        for ev in events:
            await calendar_col.update_one(
                {"workspace_id": workspace_id, "gcal_id": ev["gcal_id"]},
                {
                    "$set": {
                        "workspace_id": workspace_id, "source": "google_calendar",
                        "gcal_id": ev["gcal_id"], "title": ev["title"],
                        "description": ev["description"], "location": ev["location"],
                        "start": ev["start_iso"], "end": ev["end_iso"],
                        "attendees": ev["attendees"], "html_link": ev["html_link"],
                        "status": ev["status"], "is_real": True, "is_simulation": False, "synced_at": now,
                    },
                    "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now},
                },
                upsert=True,
            )
            counts["events"] += 1
        await google_integrations_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"last_sync_at": now, "last_sync_error": None}},
        )
        return {"workspace_id": workspace_id, "ok": True, "counts": counts}
    except Exception as exc:  # noqa: BLE001
        await google_integrations_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"last_sync_error": str(exc)[:200], "last_sync_attempt_at": now}},
        )
        return {"workspace_id": workspace_id, "error": str(exc)[:200]}


async def _periodic_provider_sync_loop() -> None:
    """Forever loop. Wakes up every interval and dispatches sync for
    every connected, non-paused workspace across every provider."""
    # Small initial delay so the first tick happens AFTER startup
    # finishes (avoids contending with seed/backfill jobs).
    await asyncio.sleep(60)
    while True:
        try:
            # --- Google
            cursor = google_integrations_col.find(
                {"auto_sync_paused": {"$ne": True}},
                {"_id": 0, "workspace_id": 1},
            )
            async for row in cursor:
                wid = row.get("workspace_id")
                if not wid:
                    continue
                res = await _perform_google_sync_for_workspace(wid)
                if res.get("error"):
                    print(f"[sync:google] {wid} failed: {res['error']}")
            # --- Microsoft (registered only if module is loaded)
            ms_sync = globals().get("_perform_microsoft_sync_for_workspace")
            if ms_sync is not None:
                cursor_ms = microsoft_integrations_col.find(
                    {"auto_sync_paused": {"$ne": True}},
                    {"_id": 0, "workspace_id": 1},
                )
                async for row in cursor_ms:
                    wid = row.get("workspace_id")
                    if not wid:
                        continue
                    try:
                        res = await ms_sync(wid)
                        if res.get("error"):
                            print(f"[sync:microsoft] {wid} failed: {res['error']}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[sync:microsoft] {wid} crashed: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[sync] loop error: {exc}")
        await asyncio.sleep(PERIODIC_SYNC_INTERVAL_SECS)


async def migrate_legacy_role_names() -> None:
    """One-shot migration: rewrite legacy role names in
    workspace_members and workspace_invites to the canonical Quantro
    taxonomy (agent→viewer, operator→member, manager→accountant,
    admin→leader). Idempotent — runs every boot but only matches rows
    still on the old names."""
    pairs = [
        ("agent", "viewer"),
        ("operator", "member"),
        ("manager", "accountant"),
        ("admin", "leader"),
    ]
    total = 0
    for legacy, canonical in pairs:
        for col in (workspace_members_col, workspace_invites_col):
            try:
                res = await col.update_many({"role": legacy}, {"$set": {"role": canonical}})
                total += res.modified_count
            except Exception as e:
                # Log the error instead of silently swallowing it
                print(f"[role-migration] Warning: Failed to migrate {legacy} in {col.name}: {e}")
    if total:
        print(f"[role-migration] Migrated {total} rows to Quantro role taxonomy")

app = FastAPI(title="Quantro Flow | Business OS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # When allow_credentials=True, browsers refuse wildcard origins.
    # We echo back the caller's origin instead, which is safe because
    # auth is enforced by the session cookie, not by origin allowlisting.
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth Endpoints (Supabase-backed) ─────────────────────────────────
# Note: sign-in / sign-up / sign-out all happen on the frontend against
# Supabase directly (see /app/frontend/src/lib/supabaseClient.js). The
# backend only needs to:
#   • Verify the Supabase JWT on every request (see get_current_user).
#   • Expose /api/auth/me so the SPA can hydrate the user + workspaces.
#   • Allow users to list / create / switch workspaces (still MongoDB-backed).
# The legacy /api/auth/session and /api/auth/logout endpoints from the
# previous Emergent Google Auth flow have been intentionally removed.


@app.get("/api/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    """Return the authenticated user + their workspace memberships.

    The Supabase JWT is verified by ``get_current_user`` which also upserts
    the user into MongoDB and claims/creates a workspace on first login."""
    memberships = await workspace_members_col.find({"user_id": user.user_id}, {"_id": 0}).to_list(50)
    workspace_ids = [m["workspace_id"] for m in memberships]
    workspaces = []
    if workspace_ids:
        rows = await workspaces_col.find({"workspace_id": {"$in": workspace_ids}}, {"_id": 0}).to_list(50)
        role_map = {m["workspace_id"]: _normalize_role(m.get("role")) for m in memberships}
        for w in rows:
            workspaces.append({
                "workspace_id": w["workspace_id"],
                "name": w.get("name", "Workspace"),
                "role": role_map.get(w["workspace_id"], "viewer"),
                "is_current": w["workspace_id"] == user.current_workspace_id,
            })
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "current_workspace_id": user.current_workspace_id,
        "workspaces": workspaces,
    }


class CreateWorkspaceRequest(BaseModel):
    name: str


@app.post("/api/auth/workspaces")
async def create_workspace(req: CreateWorkspaceRequest, user: User = Depends(get_current_user)):
    """Create a new workspace (user becomes its Owner)."""
    new_ws_id = f"ws_{uuid.uuid4().hex[:12]}"
    await workspaces_col.insert_one({
        "workspace_id": new_ws_id,
        "name": req.name or f"{user.name} Workspace",
        "owner_user_id": user.user_id,
        "created_at": datetime.now(timezone.utc),
        "claimed": True,
        "claimed_at": datetime.now(timezone.utc),
    })
    await workspace_members_col.insert_one({
        "workspace_id": new_ws_id,
        "user_id": user.user_id,
        "role": "owner",
        "joined_at": datetime.now(timezone.utc),
    })
    await seed_workspace_config(new_ws_id)
    await log_audit("workspace.created", f"Created workspace '{req.name}'", user_id=user.user_id, workspace_id=new_ws_id)
    return {"workspace_id": new_ws_id, "name": req.name}


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: str


@app.post("/api/auth/workspaces/switch")
async def switch_workspace(req: SwitchWorkspaceRequest, user: User = Depends(get_current_user)):
    """Set the user's current active workspace."""
    member = await workspace_members_col.find_one({"user_id": user.user_id, "workspace_id": req.workspace_id})
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    await users_col.update_one(
        {"user_id": user.user_id},
        {"$set": {"current_workspace_id": req.workspace_id}},
    )
    await log_audit("workspace.switched", f"Switched to workspace {req.workspace_id}", user_id=user.user_id, workspace_id=req.workspace_id)
    return {"success": True, "workspace_id": req.workspace_id}


class UpdateWorkspaceRequest(BaseModel):
    name: str


@app.patch("/api/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    req: UpdateWorkspaceRequest,
    user: User = Depends(get_current_user),
):
    """Rename a workspace. Leader+ only.

    This is the primary way to customize the default workspace name
    (``Quantro``) once the customer takes ownership of their tenant.
    The audit trail records the previous and new names for traceability.
    """
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    new_name = (req.name or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="Workspace name cannot be empty")
    if len(new_name) > 80:
        raise HTTPException(status_code=422, detail="Workspace name is too long (max 80 chars)")

    ws = await workspaces_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    old_name = ws.get("name") or ""
    if old_name == new_name:
        return {"workspace_id": workspace_id, "name": new_name, "unchanged": True}

    await workspaces_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"name": new_name, "updated_at": datetime.now(timezone.utc)}},
    )
    await log_audit(
        "workspace.renamed",
        f"Renamed workspace '{old_name}' → '{new_name}'",
        user_id=user.user_id,
        workspace_id=workspace_id,
        metadata={"old_name": old_name, "new_name": new_name},
    )
    return {"workspace_id": workspace_id, "name": new_name, "unchanged": False}


# ─── RBAC (Phase 7b) ──────────────────────────────────────────────────
# Quantro role hierarchy (highest → lowest privilege).
# Matches the `org_members.role` column in Supabase.
#   owner       — Full control. One per workspace. Can transfer ownership and
#                 promote others to leader/owner.
#   leader      — Manage members, integrations, business profile, simulation
#                 mode. Cannot transfer ownership.
#   accountant  — Edit automation policies, escalation rules, content
#                 templates. Cannot manage members or settings.
#   member      — Day-to-day workspace usage: inbox actions, CRM/Schedule
#                 writes, content generation. Cannot edit governance.
#   viewer      — Read-only on most modules. Cannot write.
#
# Helpers:
#   ROLE_RANK[role] -> int
#   require_role(min_role) -> FastAPI dependency that 403s when the
#       caller's role in the active workspace is below `min_role`.
ROLE_RANK = {"viewer": 1, "member": 2, "accountant": 3, "leader": 4, "owner": 5}
VALID_ROLES = list(ROLE_RANK.keys())

# Legacy → Quantro role aliases. Used by `_normalize_role()` so any data
# still tagged with the previous taxonomy (agent/operator/manager/admin)
# is silently translated on read AND rewritten on write. Phase 7b-ext
# also runs a one-shot migration in lifespan to bring rows up to date.
ROLE_ALIASES = {
    "agent": "viewer",
    "operator": "member",
    "manager": "accountant",
    "admin": "leader",
    "owner": "owner",
    "viewer": "viewer",
    "member": "member",
    "accountant": "accountant",
    "leader": "leader",
}


def _normalize_role(role: Optional[str]) -> str:
    return ROLE_ALIASES.get((role or "").lower().strip(), "viewer")


# ─── Workspace ↔ Supabase Org mapping ───────────────────────────────
# Phase 7c is migrating Members/Invites/Onboarding/Audit to Supabase
# where the unit is `organizations.id` (uuid). MongoDB still uses the
# legacy `workspace_id` strings. This resolver translates between the
# two so we can dual-write without exposing the mapping to callers.
async def workspace_to_org_id(workspace_id: str) -> Optional[str]:
    """Translate a Mongo workspace_id to a Supabase organisation uuid.

    Lookup order:
      1. workspaces_col[workspace_id].org_id (per-workspace override)
      2. QUANTRO_DEFAULT_ORG_ID env var (only for the legacy
         DEFAULT_WORKSPACE_ID — every other workspace must opt-in)
    Returns ``None`` if no mapping is known, in which case the caller
    falls back to Mongo-only behavior.
    """
    if not workspace_id:
        return None
    try:
        ws = await workspaces_col.find_one(
            {"workspace_id": workspace_id}, {"_id": 0, "org_id": 1}
        )
        if ws and ws.get("org_id"):
            return str(ws["org_id"])
    except Exception:  # noqa: BLE001
        pass
    if workspace_id == DEFAULT_WORKSPACE_ID:
        return supabase_admin.resolve_default_org_id()
    return None

# Workspace invites: each invite is a single document (no email needed).
# A workspace admin generates an invite, gets a shareable URL, and any
# authenticated user that hits /api/invites/{token}/accept gets added to
# the workspace with the role specified on the invite.
# Note: workspace_invites_col is defined at the top with other collections


def role_rank(role: Optional[str]) -> int:
    return ROLE_RANK.get(_normalize_role(role), 0)


async def _membership_for(user_id: str, workspace_id: str) -> Optional[dict]:
    member = await workspace_members_col.find_one(
        {"user_id": user_id, "workspace_id": workspace_id}, {"_id": 0}
    )
    if member and member.get("role"):
        # Normalize on read so callers always see the canonical Quantro
        # role even if the row was written before the migration.
        member["role"] = _normalize_role(member["role"])
    return member


def require_role(min_role: str):
    """Build a FastAPI dependency that asserts the caller's role in the
    *active* workspace is at least ``min_role``. The active workspace is
    resolved by ``get_current_workspace_id`` (header → user.current →
    first membership), so this dep also doubles as a membership guard.

    Usage::

        @app.put("/api/business-profile")
        async def update_profile(
            req: BusinessProfileRequest,
            workspace_id: str = Depends(get_current_workspace_id),
            membership: dict = Depends(require_role("leader")),
        ):
            ...
    """
    if min_role not in VALID_ROLES:
        raise ValueError(f"Unknown role: {min_role}")

    async def _dep(
        user: User = Depends(get_current_user),
        workspace_id: str = Depends(get_current_workspace_id),
    ) -> dict:
        member = await _membership_for(user.user_id, workspace_id)
        if not member:
            raise HTTPException(status_code=403, detail="Not a workspace member")
        if role_rank(member.get("role")) < role_rank(min_role):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "rbac_forbidden",
                    "required_role": min_role,
                    "your_role": member.get("role"),
                },
            )
        return member

    return _dep


# ─── Workspace members + invites endpoints ────────────────────────────
class UpdateMemberRoleRequest(BaseModel):
    role: str


class CreateInviteRequest(BaseModel):
    role: str = "member"
    max_uses: Optional[int] = 1
    expires_in_days: Optional[int] = 7
    # Phase 7c: optional metadata for Supabase `invitations` parity.
    # `email` is required by the Supabase table; if blank we generate a
    # placeholder so legacy email-free links keep working.
    email: Optional[str] = None
    full_name: Optional[str] = None
    job_title: Optional[str] = None


def _serialize_member(member_doc: dict, user_doc: Optional[dict]) -> dict:
    return {
        "user_id": member_doc.get("user_id"),
        "role": _normalize_role(member_doc.get("role")),
        "joined_at": (
            member_doc.get("joined_at").isoformat()
            if isinstance(member_doc.get("joined_at"), datetime)
            else member_doc.get("joined_at")
        ),
        "email": (user_doc or {}).get("email"),
        "name": (user_doc or {}).get("name"),
        "picture": (user_doc or {}).get("picture"),
    }


def _serialize_invite(invite: dict, *, base_url: Optional[str] = None) -> dict:
    token = invite.get("token")
    return {
        "invite_id": invite.get("invite_id"),
        "workspace_id": invite.get("workspace_id"),
        "role": _normalize_role(invite.get("role")),
        "token": token,
        "url": f"{base_url}/join/{token}" if base_url and token else None,
        "max_uses": invite.get("max_uses"),
        "used_count": invite.get("used_count", 0),
        "expires_at": (
            invite.get("expires_at").isoformat()
            if isinstance(invite.get("expires_at"), datetime)
            else invite.get("expires_at")
        ),
        "created_by": invite.get("created_by"),
        "created_at": (
            invite.get("created_at").isoformat()
            if isinstance(invite.get("created_at"), datetime)
            else invite.get("created_at")
        ),
        "revoked": bool(invite.get("revoked", False)),
    }


@app.get("/api/workspaces/{workspace_id}/members")
async def list_members(
    workspace_id: str,
    user: User = Depends(get_current_user),
):
    """List all members of a workspace. Any member can view the roster
    (it surfaces ownership/role boundaries, not sensitive data).

    Phase 7c dual-read: when ``QUANTRO_DB_PRIMARY=supabase`` we read
    from the Supabase ``org_members`` table first. Otherwise we read
    from Mongo and silently shadow-validate against Supabase.
    """
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")

    org_id = await workspace_to_org_id(workspace_id)
    use_supabase = supabase_admin.is_supabase_primary() and bool(org_id)

    if use_supabase:
        rows = await supabase_admin.list_org_members(org_id, user.access_token or "")
        # If Supabase fails or returns empty for what should be a
        # populated workspace, fall back to Mongo so we never serve a
        # blank Members tab during the migration.
        if rows:
            user_ids = [r["user_id"] for r in rows if r.get("user_id")]
            user_rows = await users_col.find(
                {"user_id": {"$in": user_ids}},
                {"_id": 0, "user_id": 1, "email": 1, "name": 1, "picture": 1},
            ).to_list(200) if user_ids else []
            by_id = {u["user_id"]: u for u in user_rows}
            return {
                "workspace_id": workspace_id,
                "org_id": org_id,
                "source": "supabase",
                "your_role": _normalize_role(me.get("role")),
                "members": [
                    _serialize_member(
                        {"user_id": r.get("user_id"), "role": r.get("role"), "joined_at": r.get("joined_at")},
                        by_id.get(r.get("user_id")),
                    )
                    for r in rows
                ],
            }

    members = await workspace_members_col.find(
        {"workspace_id": workspace_id}, {"_id": 0}
    ).to_list(200)
    user_ids = [m["user_id"] for m in members]
    user_rows = await users_col.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "picture": 1},
    ).to_list(200)
    by_id = {u["user_id"]: u for u in user_rows}
    return {
        "workspace_id": workspace_id,
        "org_id": org_id,
        "source": "mongo",
        "your_role": _normalize_role(me.get("role")),
        "members": [_serialize_member(m, by_id.get(m["user_id"])) for m in members],
    }


@app.patch("/api/workspaces/{workspace_id}/members/{target_user_id}")
async def update_member_role(
    workspace_id: str,
    target_user_id: str,
    req: UpdateMemberRoleRequest,
    user: User = Depends(get_current_user),
):
    """Change a member's role. Rules:
      • Only Owner can promote to admin or owner (transfer ownership).
      • Admin can demote/promote anyone among agent/operator/manager.
      • Cannot demote yourself if you're the sole Owner.
    """
    new_role = (req.role or "").lower()
    if new_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {VALID_ROLES}")

    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    target = await _membership_for(target_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    target_role = _normalize_role(target.get("role"))

    # Only Owner can touch leader/owner roles (either side of the change).
    is_privileged_change = new_role in {"leader", "owner"} or target_role in {"leader", "owner"}
    if is_privileged_change and me.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the Owner can manage leader/owner roles")

    # Ownership transfer: demote previous owner to leader so workspace
    # always has exactly one Owner.
    if new_role == "owner":
        if user.user_id == target_user_id:
            raise HTTPException(status_code=400, detail="You're already the owner")
        await workspace_members_col.update_one(
            {"user_id": user.user_id, "workspace_id": workspace_id},
            {"$set": {"role": "leader"}},
        )
        await workspaces_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"owner_user_id": target_user_id}},
        )

    await workspace_members_col.update_one(
        {"user_id": target_user_id, "workspace_id": workspace_id},
        {"$set": {"role": new_role, "role_updated_at": datetime.now(timezone.utc)}},
    )

    # Phase 7c shadow-write: keep org_members in sync.
    org_id = await workspace_to_org_id(workspace_id)
    if org_id and supabase_admin.is_dual_write_enabled():
        try:
            await supabase_admin.update_member_role(
                org_id=org_id,
                member_user_id=target_user_id,
                new_role=new_role,
                access_token=user.access_token or "",
            )
        except Exception:  # noqa: BLE001
            pass

    await log_audit(
        "members.role_changed",
        f"{user.email} changed role of {target_user_id} to {new_role}",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=target_user_id,
        metadata={
            "target_user_id": target_user_id,
            "new_role": new_role,
            "previous_role": target_role,
            "old_role": target_role,
        },
    )
    return {"success": True, "user_id": target_user_id, "role": new_role}


@app.delete("/api/workspaces/{workspace_id}/members/{target_user_id}")
async def remove_member(
    workspace_id: str,
    target_user_id: str,
    user: User = Depends(get_current_user),
):
    """Remove a member. Owner cannot be removed; admins can only be
    removed by the Owner. Members can also remove themselves (leave)."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")

    target = await _membership_for(target_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    target_role = _normalize_role(target.get("role"))
    is_self = user.user_id == target_user_id

    if target_role == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot be removed. Transfer ownership first.")

    if not is_self:
        if role_rank(me.get("role")) < role_rank("leader"):
            raise HTTPException(status_code=403, detail="Requires leader role")
        if target_role == "leader" and me.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Only the Owner can remove a leader")

    await workspace_members_col.delete_one(
        {"user_id": target_user_id, "workspace_id": workspace_id}
    )
    # If the user was active in this workspace, clear their pointer so
    # /api/auth/me re-resolves on next login.
    await users_col.update_one(
        {"user_id": target_user_id, "current_workspace_id": workspace_id},
        {"$unset": {"current_workspace_id": ""}},
    )

    # Phase 7c shadow-write: also remove from Supabase.
    org_id = await workspace_to_org_id(workspace_id)
    if org_id and supabase_admin.is_dual_write_enabled():
        try:
            await supabase_admin.delete_member(
                org_id=org_id,
                member_user_id=target_user_id,
                access_token=user.access_token or "",
            )
        except Exception:  # noqa: BLE001
            pass

    await log_audit(
        "members.removed",
        f"{user.email} removed {target_user_id} from workspace",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=target_user_id,
        metadata={
            "target_user_id": target_user_id,
            "self_leave": is_self,
            "previous_role": target_role,
            "old_role": target_role,
        },
    )
    return {"success": True}


@app.post("/api/workspaces/{workspace_id}/invites")
async def create_invite(
    workspace_id: str,
    req: CreateInviteRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Generate a shareable invite link. Leader+ only."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    role = _normalize_role(req.role or "member")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {VALID_ROLES}")
    # Only the Owner can mint invites that grant leader/owner.
    if role in {"leader", "owner"} and me.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the Owner can invite leaders/owners")

    import secrets
    token = secrets.token_urlsafe(24)
    invite_id = f"inv_{uuid.uuid4().hex[:12]}"
    expires_in_days = max(1, min(int(req.expires_in_days or 7), 90))
    max_uses = max(1, min(int(req.max_uses or 1), 50))
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    invite_doc = {
        "invite_id": invite_id,
        "workspace_id": workspace_id,
        "token": token,
        "role": role,
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": expires_at,
        "revoked": False,
        "created_by": user.user_id,
        "created_at": datetime.now(timezone.utc),
        "accepted_by": [],
        "email": (req.email or None),
        "full_name": (req.full_name or None),
    }
    await workspace_invites_col.insert_one(invite_doc)

    # Phase 7c shadow-write: also create the invite in Supabase so the
    # rest of the org tooling (and the eventual primary read switch)
    # stays in sync. Best-effort — failures don't bubble up.
    org_id = await workspace_to_org_id(workspace_id)
    supabase_invite_id = None
    if org_id and supabase_admin.is_dual_write_enabled():
        try:
            sb_invite = await supabase_admin.insert_invitation(
                org_id=org_id,
                role=role,
                invited_by=user.user_id,
                access_token=user.access_token or "",
                email=req.email,
                full_name=req.full_name,
                job_title=req.job_title,
                expires_at=expires_at.isoformat(),
            )
            if sb_invite and sb_invite.get("id"):
                supabase_invite_id = sb_invite["id"]
                # Cross-link Mongo row → Supabase row id for later
                # revoke/accept dual-writes.
                await workspace_invites_col.update_one(
                    {"invite_id": invite_id},
                    {"$set": {
                        "supabase_invite_id": supabase_invite_id,
                        "supabase_token": sb_invite.get("token"),
                    }},
                )
        except Exception:  # noqa: BLE001
            pass

    await log_audit(
        "invites.created",
        f"{user.email} created invite for role={role}",
        user_id=user.user_id, workspace_id=workspace_id,
        metadata={
            "invite_id": invite_id,
            "role": role,
            "max_uses": max_uses,
            "supabase_invite_id": supabase_invite_id,
        },
    )
    base_url = (request.headers.get("origin") or "").rstrip("/")
    return _serialize_invite(invite_doc, base_url=base_url or None)


@app.get("/api/workspaces/{workspace_id}/invites")
async def list_invites(
    workspace_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """List active invites for a workspace. Leader+ only.

    Phase 7c: when QUANTRO_DB_PRIMARY=supabase, reads from the
    Supabase ``invitations`` table; otherwise reads Mongo and the
    Supabase rows are kept in sync via shadow-writes from
    ``create_invite`` / ``revoke_invite``."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    org_id = await workspace_to_org_id(workspace_id)
    base_url = (request.headers.get("origin") or "").rstrip("/")

    if supabase_admin.is_supabase_primary() and org_id:
        sb_rows = await supabase_admin.list_invitations(org_id, user.access_token or "")
        if sb_rows is not None:
            invites = []
            for r in sb_rows:
                token = r.get("token")
                invites.append({
                    "invite_id": r.get("id"),
                    "workspace_id": workspace_id,
                    "role": _normalize_role(r.get("role")),
                    "token": token,
                    "url": f"{base_url}/join/{token}" if base_url and token else None,
                    "max_uses": 1,
                    "used_count": 1 if r.get("accepted") else 0,
                    "expires_at": r.get("expires_at"),
                    "created_by": r.get("invited_by"),
                    "created_at": r.get("created_at"),
                    "revoked": False,
                    "email": r.get("email"),
                    "full_name": r.get("full_name"),
                    "source": "supabase",
                })
            return {"invites": invites, "source": "supabase"}

    rows = await workspace_invites_col.find({"workspace_id": workspace_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"invites": [_serialize_invite(r, base_url=base_url or None) for r in rows], "source": "mongo"}


@app.delete("/api/workspaces/{workspace_id}/invites/{invite_id}")
async def revoke_invite(
    workspace_id: str,
    invite_id: str,
    user: User = Depends(get_current_user),
):
    """Revoke a pending invite. Leader+ only."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")
    # Look up the row first so we have the supabase_invite_id (if any)
    # before flipping the revoked flag.
    invite_row = await workspace_invites_col.find_one(
        {"workspace_id": workspace_id, "invite_id": invite_id}, {"_id": 0}
    )
    result = await workspace_invites_col.update_one(
        {"workspace_id": workspace_id, "invite_id": invite_id},
        {"$set": {"revoked": True, "revoked_at": datetime.now(timezone.utc), "revoked_by": user.user_id}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Invite not found")

    # Phase 7c shadow-write: revoke in Supabase too. There's no
    # "revoked" column on `invitations`; we mark accepted=true so the
    # invite stops being valid (keeps schema clean even if it's not
    # the most semantic mapping). The Mongo row is still the source of
    # truth for the revoked-vs-used distinction during the migration.
    if invite_row and invite_row.get("supabase_invite_id") and supabase_admin.is_dual_write_enabled():
        try:
            await supabase_admin.update_invitation(
                invite_row["supabase_invite_id"],
                {"accepted": True},
                user.access_token or "",
            )
        except Exception:  # noqa: BLE001
            pass

    await log_audit(
        "invites.revoked",
        f"{user.email} revoked invite {invite_id}",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=invite_row.get("created_by") if invite_row else None,
        metadata={"invite_id": invite_id, "supabase_invite_id": (invite_row or {}).get("supabase_invite_id")},
    )
    return {"success": True}


@app.get("/api/invites/{token}")
async def peek_invite(token: str, user: User = Depends(get_current_user)):  # noqa: ARG001 — auth required
    """Public-ish endpoint (still requires Supabase auth so abuse is
    bounded) that shows the receiver what they're about to accept. Used
    by the /join/:token frontend page."""
    invite = await workspace_invites_col.find_one({"token": token}, {"_id": 0})
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired")
    if invite.get("revoked"):
        raise HTTPException(status_code=410, detail="This invite has been revoked")
    expires_at = invite.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This invite has expired")
    if invite.get("used_count", 0) >= invite.get("max_uses", 1):
        raise HTTPException(status_code=410, detail="This invite has reached its usage limit")
    workspace = await workspaces_col.find_one({"workspace_id": invite["workspace_id"]}, {"_id": 0})
    return {
        "workspace_id": invite["workspace_id"],
        "workspace_name": (workspace or {}).get("name", "Workspace"),
        "role": _normalize_role(invite.get("role")),
        "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at,
    }


@app.post("/api/invites/{token}/accept")
async def accept_invite(token: str, user: User = Depends(get_current_user)):
    """Accept an invite token. Adds the authenticated user to the
    workspace with the role specified on the invite. Idempotent: if the
    user is already a member, the existing membership is preserved
    (role is NOT downgraded)."""
    invite = await workspace_invites_col.find_one({"token": token}, {"_id": 0})
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.get("revoked"):
        raise HTTPException(status_code=410, detail="This invite has been revoked")
    expires_at = invite.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This invite has expired")
    if invite.get("used_count", 0) >= invite.get("max_uses", 1):
        raise HTTPException(status_code=410, detail="This invite has reached its usage limit")

    workspace_id = invite["workspace_id"]
    role = _normalize_role(invite.get("role") or "member")

    existing = await _membership_for(user.user_id, workspace_id)
    if existing:
        # Already a member — don't downgrade. Just point them at the
        # workspace and consider the invite redeemed.
        await users_col.update_one(
            {"user_id": user.user_id},
            {"$set": {"current_workspace_id": workspace_id}},
        )
        return {"success": True, "workspace_id": workspace_id, "role": existing.get("role"), "already_member": True}

    await workspace_members_col.insert_one({
        "workspace_id": workspace_id,
        "user_id": user.user_id,
        "role": role,
        "joined_at": datetime.now(timezone.utc),
        "joined_via_invite": invite.get("invite_id"),
    })
    await workspace_invites_col.update_one(
        {"token": token},
        {
            "$inc": {"used_count": 1},
            "$push": {"accepted_by": {"user_id": user.user_id, "at": datetime.now(timezone.utc)}},
        },
    )
    await users_col.update_one(
        {"user_id": user.user_id},
        {"$set": {"current_workspace_id": workspace_id}},
    )
    await log_audit(
        "invites.accepted",
        f"{user.email} joined workspace via invite as {role}",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=user.user_id,
        metadata={"invite_id": invite.get("invite_id"), "role": role},
    )


# ─── Onboarding + Audit (Phase 7b-ext) ────────────────────────────────
# `people_onboarding_steps_col` mirrors the Supabase table of the same
# shape (see `/app/supabase/migrations/20260426_people_onboarding_audit.sql`).
# We persist the same five canonical step keys per (workspace_id,
# member_user_id) so the UI can show progress + completed_at timestamps
# without recomputing on every render.
people_onboarding_col = db["people_onboarding_steps"]

ONBOARDING_STEPS = [
    "invitation_sent",
    "account_created",
    "companies_assigned",
    "role_configured",
    "first_login",
]


def _onboarding_status_overall(steps: List[dict]) -> str:
    """Compute the human-readable rollup status for a member's onboarding."""
    if not steps:
        return "pending"
    if any(s.get("status") == "blocked" for s in steps):
        return "blocked"
    completed = sum(1 for s in steps if s.get("status") == "completed")
    if completed == len(ONBOARDING_STEPS):
        return "completed"
    if completed > 0:
        return "in_progress"
    return "pending"


async def _hydrate_member_onboarding(
    workspace_id: str,
    member: dict,
    user_doc: Optional[dict],
    invite_for_member: Optional[dict] = None,
    business_profile: Optional[dict] = None,
    supabase_persisted: Optional[Dict[str, dict]] = None,
) -> dict:
    """Build the per-member onboarding payload by merging persisted
    `people_onboarding_steps` rows with derived signals from the rest of
    the system (auth, workspace_members, business_profile)."""
    user_id = member["user_id"]
    persisted_rows = await people_onboarding_col.find(
        {"workspace_id": workspace_id, "member_user_id": user_id},
        {"_id": 0},
    ).to_list(20)
    persisted = {r["step_key"]: r for r in persisted_rows}
    # Layer Supabase persisted on top — its rows are authoritative
    # once Phase 7c is rolled forward.
    if supabase_persisted:
        for k, v in supabase_persisted.items():
            persisted.setdefault(k, v)
            # If both exist, prefer the most recently completed.
            if k in persisted and v.get("status") == "completed" and persisted[k].get("status") != "completed":
                persisted[k] = v

    derived: Dict[str, dict] = {}

    # 1) invitation_sent — derived from workspace_invites_col rows whose
    #    accepted_by[].user_id == this user's id, or rows still pending
    #    that match the user's email (best-effort).
    inv = invite_for_member
    if inv:
        derived["invitation_sent"] = {
            "status": "completed",
            "completed_at": inv.get("created_at"),
            "metadata": {"invite_id": inv.get("invite_id")},
        }
    else:
        # No invite found means the user is the workspace owner
        # (claimed/created the workspace directly) — that counts as
        # already onboarded for this step.
        if member.get("role") == "owner":
            derived["invitation_sent"] = {
                "status": "completed",
                "completed_at": member.get("joined_at"),
                "metadata": {"source": "workspace_owner"},
            }

    # 2) account_created — true if there is any user_doc row.
    if user_doc and user_doc.get("user_id"):
        derived["account_created"] = {
            "status": "completed",
            "completed_at": user_doc.get("created_at") or user_doc.get("last_login_at"),
        }

    # 3) companies_assigned — workspace_members membership exists +
    #    business_profile completed for this workspace (proxy for "the
    #    workspace itself is configured to belong to a real company").
    if business_profile and business_profile.get("industry"):
        derived["companies_assigned"] = {
            "status": "completed",
            "completed_at": business_profile.get("updated_at") or member.get("joined_at"),
            "metadata": {"industry": business_profile.get("industry")},
        }

    # 4) role_configured — true once the member's role rank is >=
    #    member (i.e. moved off the default `viewer`).
    role = _normalize_role(member.get("role"))
    if role_rank(role) >= role_rank("member"):
        derived["role_configured"] = {
            "status": "completed",
            "completed_at": member.get("role_updated_at") or member.get("joined_at"),
            "metadata": {"role": role},
        }

    # 5) first_login — last_login_at on user_doc.
    if user_doc and user_doc.get("last_login_at"):
        derived["first_login"] = {
            "status": "completed",
            "completed_at": user_doc.get("last_login_at"),
        }

    # Merge: persisted values WIN over derived (user explicitly marked
    # something complete should not be re-reverted).
    steps = []
    for key in ONBOARDING_STEPS:
        if key in persisted:
            row = persisted[key]
            steps.append({
                "step_key": key,
                "status": row.get("status", "pending"),
                "completed_at": (
                    row["completed_at"].isoformat()
                    if isinstance(row.get("completed_at"), datetime)
                    else row.get("completed_at")
                ),
                "metadata": row.get("metadata") or {},
            })
            continue
        d = derived.get(key)
        if d:
            steps.append({
                "step_key": key,
                "status": d.get("status", "pending"),
                "completed_at": (
                    d["completed_at"].isoformat()
                    if isinstance(d.get("completed_at"), datetime)
                    else d.get("completed_at")
                ),
                "metadata": d.get("metadata") or {},
            })
        else:
            steps.append({"step_key": key, "status": "pending", "completed_at": None, "metadata": {}})

    completed = sum(1 for s in steps if s["status"] == "completed")
    return {
        "user_id": user_id,
        "name": (user_doc or {}).get("name"),
        "email": (user_doc or {}).get("email"),
        "picture": (user_doc or {}).get("picture"),
        "role": role,
        "status": _onboarding_status_overall(steps),
        "progress": {"completed": completed, "total": len(ONBOARDING_STEPS)},
        "steps": steps,
    }


@app.get("/api/workspaces/{workspace_id}/onboarding")
async def get_onboarding(workspace_id: str, user: User = Depends(get_current_user)):
    """Return per-member onboarding state for a workspace. Any member
    can view this (it's a productivity view, not sensitive data)."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")

    members = await workspace_members_col.find(
        {"workspace_id": workspace_id}, {"_id": 0}
    ).to_list(200)
    user_ids = [m["user_id"] for m in members]
    user_rows = await users_col.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "picture": 1, "last_login_at": 1, "created_at": 1},
    ).to_list(200)
    by_user = {u["user_id"]: u for u in user_rows}

    # Fetch invites once and map by accepted user_id (best-effort).
    invite_rows = await workspace_invites_col.find(
        {"workspace_id": workspace_id}, {"_id": 0}
    ).to_list(200)
    invite_by_user: Dict[str, dict] = {}
    for inv in invite_rows:
        for acc in inv.get("accepted_by") or []:
            uid = (acc or {}).get("user_id")
            if uid:
                invite_by_user.setdefault(uid, inv)

    # Business profile is workspace-scoped, fetch once.
    business_profile = await business_profile_col.find_one(
        {"workspace_id": workspace_id}, {"_id": 0}
    )

    # Phase 7c: pre-fetch Supabase onboarding steps for the whole org
    # so the per-member hydrator avoids N+1 round-trips.
    org_id = await workspace_to_org_id(workspace_id)
    supabase_steps_by_member: Dict[str, Dict[str, dict]] = {}
    if org_id and supabase_admin.is_dual_write_enabled():
        try:
            sb_rows = await supabase_admin.list_onboarding_steps(org_id, user.access_token or "")
            for r in sb_rows:
                mid = r.get("member_id")
                if not mid:
                    continue
                supabase_steps_by_member.setdefault(mid, {})[r["step_key"]] = r
        except Exception:  # noqa: BLE001
            pass

    cards = []
    for m in members:
        # Ensure role is canonical for downstream consumers.
        m["role"] = _normalize_role(m.get("role"))
        cards.append(await _hydrate_member_onboarding(
            workspace_id, m, by_user.get(m["user_id"]),
            invite_for_member=invite_by_user.get(m["user_id"]),
            business_profile=business_profile,
            supabase_persisted=supabase_steps_by_member.get(m["user_id"]),
        ))

    overall_completed = sum(1 for c in cards if c["status"] == "completed")
    return {
        "workspace_id": workspace_id,
        "members": cards,
        "summary": {
            "total_members": len(cards),
            "completed_onboarding": overall_completed,
        },
    }


class OnboardingStepUpdate(BaseModel):
    status: str = "completed"
    metadata: Optional[Dict[str, Any]] = None


@app.post("/api/workspaces/{workspace_id}/onboarding/{member_user_id}/steps/{step_key}")
async def upsert_onboarding_step(
    workspace_id: str,
    member_user_id: str,
    step_key: str,
    req: OnboardingStepUpdate,
    user: User = Depends(get_current_user),
):
    """Manually mark a single onboarding step. Leader+ or self only.

    Persists to `people_onboarding_steps` with unique(member, step_key)
    semantics so repeated calls just update the existing row."""
    if step_key not in ONBOARDING_STEPS:
        raise HTTPException(status_code=400, detail=f"Unknown step. Allowed: {ONBOARDING_STEPS}")
    new_status = (req.status or "completed").lower()
    if new_status not in {"pending", "completed", "blocked"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    is_self = user.user_id == member_user_id
    if not is_self and role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    target = await _membership_for(member_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    now = datetime.now(timezone.utc)
    update_doc = {
        "workspace_id": workspace_id,
        "member_user_id": member_user_id,
        "step_key": step_key,
        "status": new_status,
        "metadata": req.metadata or {},
        "updated_at": now,
    }
    if new_status == "completed":
        update_doc["completed_at"] = now
    else:
        update_doc["completed_at"] = None

    await people_onboarding_col.update_one(
        {"workspace_id": workspace_id, "member_user_id": member_user_id, "step_key": step_key},
        {"$set": update_doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    # Phase 7c shadow-write to Supabase people_onboarding_steps.
    org_id = await workspace_to_org_id(workspace_id)
    if org_id and supabase_admin.is_dual_write_enabled():
        try:
            await supabase_admin.upsert_onboarding_step(
                org_id=org_id,
                member_id=member_user_id,
                step_key=step_key,
                status=new_status,
                metadata=req.metadata or {},
                access_token=user.access_token or "",
                completed_at_iso=now.isoformat() if new_status == "completed" else None,
            )
        except Exception:  # noqa: BLE001
            pass

    await log_audit(
        "onboarding.step_updated",
        f"{user.email} marked {step_key}={new_status} for {member_user_id}",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=member_user_id,
        metadata={"step_key": step_key, "status": new_status},
    )
    return {"success": True, "step_key": step_key, "status": new_status}


@app.post("/api/workspaces/{workspace_id}/onboarding/{member_user_id}/complete")
async def mark_onboarding_complete(
    workspace_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
):
    """Force all 5 onboarding steps to `completed` for one member.
    Leader+ only — useful when you've onboarded someone outside the
    automatic flow."""
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")
    target = await _membership_for(member_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    now = datetime.now(timezone.utc)
    for key in ONBOARDING_STEPS:
        await people_onboarding_col.update_one(
            {"workspace_id": workspace_id, "member_user_id": member_user_id, "step_key": key},
            {
                "$set": {
                    "workspace_id": workspace_id,
                    "member_user_id": member_user_id,
                    "step_key": key,
                    "status": "completed",
                    "completed_at": now,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now, "metadata": {"forced_by": user.user_id}},
            },
            upsert=True,
        )
    await log_audit(
        "onboarding.completed",
        f"{user.email} marked onboarding complete for {member_user_id}",
        user_id=user.user_id, workspace_id=workspace_id,
        target_member_id=member_user_id,
    )
    return {"success": True}


@app.get("/api/workspaces/{workspace_id}/audit")
async def list_audit(
    workspace_id: str,
    user: User = Depends(get_current_user),
    limit: int = 100,
    member_user_id: Optional[str] = None,
):
    """Workspace audit timeline. Leader+ only. Returns rows newest-first,
    hydrated with actor + target user metadata.

    Phase 7c: when QUANTRO_DB_PRIMARY=supabase and a workspace→org
    mapping exists, reads from Supabase ``org_audit_logs``; otherwise
    reads from Mongo's ``audit_log`` collection.
    """
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    capped_limit = max(1, min(int(limit or 100), 500))
    org_id = await workspace_to_org_id(workspace_id)

    # Try Supabase first if it's the primary read source.
    if supabase_admin.is_supabase_primary() and org_id:
        sb_rows = await supabase_admin.list_audit_logs(
            org_id, user.access_token or "",
            limit=capped_limit,
            target_user_id=member_user_id,
        )
        if sb_rows:
            user_ids = list({r.get("actor_user_id") for r in sb_rows if r.get("actor_user_id")} |
                            {r.get("target_user_id") for r in sb_rows if r.get("target_user_id")})
            user_rows = await users_col.find(
                {"user_id": {"$in": user_ids}},
                {"_id": 0, "user_id": 1, "email": 1, "name": 1, "picture": 1},
            ).to_list(500) if user_ids else []
            by_id = {u["user_id"]: u for u in user_rows}
            events = []
            for r in sb_rows:
                actor = by_id.get(r.get("actor_user_id")) or {}
                target = by_id.get(r.get("target_user_id")) or {}
                events.append({
                    "event_id": r.get("id"),
                    "action": r.get("action"),
                    "description": (r.get("metadata") or {}).get("description"),
                    "timestamp": r.get("created_at"),
                    "actor": {
                        "user_id": r.get("actor_user_id"),
                        "email": actor.get("email"),
                        "name": actor.get("name"),
                        "picture": actor.get("picture"),
                    } if r.get("actor_user_id") else None,
                    "target": {
                        "user_id": r.get("target_user_id"),
                        "email": target.get("email"),
                        "name": target.get("name"),
                        "picture": target.get("picture"),
                    } if r.get("target_user_id") else None,
                    "metadata": {
                        **(r.get("metadata") or {}),
                        "old_role": r.get("old_role"),
                        "new_role": r.get("new_role"),
                    },
                })
            return {"workspace_id": workspace_id, "events": events, "total": len(events), "source": "supabase"}

    query: Dict[str, Any] = {"workspace_id": workspace_id}
    if member_user_id:
        query["target_member_id"] = member_user_id

    rows = await audit_log_col.find(query, {"_id": 0}).sort("timestamp", -1).limit(capped_limit).to_list(capped_limit)

    actor_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    target_ids = list({r.get("target_member_id") for r in rows if r.get("target_member_id")})
    all_ids = list({*actor_ids, *target_ids})
    user_rows = await users_col.find(
        {"user_id": {"$in": all_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "picture": 1},
    ).to_list(500) if all_ids else []
    by_id = {u["user_id"]: u for u in user_rows}

    events = []
    for r in rows:
        actor = by_id.get(r.get("user_id")) or {}
        target = by_id.get(r.get("target_member_id")) or {}
        events.append({
            "event_id": r.get("event_id"),
            "action": r.get("event_type"),
            "description": r.get("description"),
            "timestamp": (
                r["timestamp"].isoformat()
                if isinstance(r.get("timestamp"), datetime)
                else r.get("timestamp")
            ),
            "actor": {
                "user_id": r.get("user_id"),
                "email": actor.get("email"),
                "name": actor.get("name"),
                "picture": actor.get("picture"),
            } if r.get("user_id") else None,
            "target": {
                "user_id": r.get("target_member_id"),
                "email": target.get("email"),
                "name": target.get("name"),
                "picture": target.get("picture"),
            } if r.get("target_member_id") else None,
            "metadata": r.get("metadata") or {},
        })
    return {"workspace_id": workspace_id, "events": events, "total": len(events), "source": "mongo"}


# ─── Audit Export (Phase 7c) ──────────────────────────────────────────
def _parse_iso_date(raw: Optional[str]) -> Optional[datetime]:
    """Parse a YYYY-MM-DD or full ISO-8601 string into a timezone-aware
    datetime. Returns ``None`` on empty/invalid input so callers can
    treat the filter as "no bound" rather than raising."""
    if not raw:
        return None
    try:
        # Accept both bare dates ("2026-04-01") and ISO timestamps.
        if len(raw) == 10:
            dt = datetime.fromisoformat(raw + "T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


async def _collect_audit_events_for_export(
    workspace_id: str,
    access_token: str,
    *,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    action: Optional[str],
) -> tuple[List[Dict[str, Any]], str]:
    """Shared data-loader for the export endpoint.

    Returns ``(events, source)`` where ``source`` is ``"supabase"`` or
    ``"mongo"``. Events are the same shape as the list endpoint so the
    CSV/JSON output stays aligned with what the UI shows.
    """
    org_id = await workspace_to_org_id(workspace_id)

    # Try Supabase first when it's the active read source.
    if supabase_admin.is_supabase_primary() and org_id:
        # list_audit_logs doesn't accept all our filters — pull a
        # reasonably large window and filter in Python.
        sb_rows = await supabase_admin.list_audit_logs(
            org_id, access_token or "", limit=2000
        )
        if sb_rows:
            user_ids = list(
                {r.get("actor_user_id") for r in sb_rows if r.get("actor_user_id")}
                | {r.get("target_user_id") for r in sb_rows if r.get("target_user_id")}
            )
            user_rows = await users_col.find(
                {"user_id": {"$in": user_ids}},
                {"_id": 0, "user_id": 1, "email": 1, "name": 1},
            ).to_list(2000) if user_ids else []
            by_id = {u["user_id"]: u for u in user_rows}
            events: List[Dict[str, Any]] = []
            for r in sb_rows:
                ts_raw = r.get("created_at")
                ts_dt = _parse_iso_date(ts_raw) if ts_raw else None
                if start_date and ts_dt and ts_dt < start_date:
                    continue
                if end_date and ts_dt and ts_dt > end_date:
                    continue
                if action and r.get("action") != action:
                    continue
                actor = by_id.get(r.get("actor_user_id")) or {}
                target = by_id.get(r.get("target_user_id")) or {}
                events.append({
                    "event_id": r.get("id"),
                    "action": r.get("action"),
                    "description": (r.get("metadata") or {}).get("description"),
                    "timestamp": ts_raw,
                    "actor_user_id": r.get("actor_user_id"),
                    "actor_email": actor.get("email"),
                    "actor_name": actor.get("name"),
                    "target_user_id": r.get("target_user_id"),
                    "target_email": target.get("email"),
                    "target_name": target.get("name"),
                    "old_role": r.get("old_role"),
                    "new_role": r.get("new_role"),
                    "metadata": r.get("metadata") or {},
                })
            return events, "supabase"

    # Mongo fallback / primary.
    query: Dict[str, Any] = {"workspace_id": workspace_id}
    if action:
        query["event_type"] = action
    if start_date or end_date:
        ts_q: Dict[str, Any] = {}
        if start_date:
            ts_q["$gte"] = start_date
        if end_date:
            ts_q["$lte"] = end_date
        query["timestamp"] = ts_q
    rows = (
        await audit_log_col.find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(2000)
        .to_list(2000)
    )
    actor_ids = {r.get("user_id") for r in rows if r.get("user_id")}
    target_ids = {r.get("target_member_id") for r in rows if r.get("target_member_id")}
    all_ids = list(actor_ids | target_ids)
    user_rows = await users_col.find(
        {"user_id": {"$in": all_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1},
    ).to_list(2000) if all_ids else []
    by_id = {u["user_id"]: u for u in user_rows}
    events = []
    for r in rows:
        actor = by_id.get(r.get("user_id")) or {}
        target = by_id.get(r.get("target_member_id")) or {}
        events.append({
            "event_id": r.get("event_id"),
            "action": r.get("event_type"),
            "description": r.get("description"),
            "timestamp": (
                r["timestamp"].isoformat()
                if isinstance(r.get("timestamp"), datetime)
                else r.get("timestamp")
            ),
            "actor_user_id": r.get("user_id"),
            "actor_email": actor.get("email"),
            "actor_name": actor.get("name"),
            "target_user_id": r.get("target_member_id"),
            "target_email": target.get("email"),
            "target_name": target.get("name"),
            "old_role": (r.get("metadata") or {}).get("old_role") or (r.get("metadata") or {}).get("previous_role"),
            "new_role": (r.get("metadata") or {}).get("new_role"),
            "metadata": r.get("metadata") or {},
        })
    return events, "mongo"


@app.get("/api/workspaces/{workspace_id}/audit/export")
async def export_audit(
    workspace_id: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    action: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Download the workspace audit timeline as CSV or JSON.

    Query params:
      * ``format`` — ``csv`` (default) or ``json``
      * ``start_date`` — inclusive lower bound. Accepts ``YYYY-MM-DD``
        or full ISO-8601. Ignored if invalid/missing.
      * ``end_date`` — inclusive upper bound. Same format rules.
      * ``action`` — filter by action name (e.g. ``role_changed``,
        ``invitation_created``). Supports Supabase or Mongo vocabulary
        depending on which source serves the request.

    Auth: leader+ only. Compliance-ready: filename encodes workspace
    and timestamp so multiple exports coexist cleanly in a download
    folder.
    """
    me = await _membership_for(user.user_id, workspace_id)
    if not me:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    if role_rank(me.get("role")) < role_rank("leader"):
        raise HTTPException(status_code=403, detail="Requires leader role")

    start_dt = _parse_iso_date(start_date)
    end_dt = _parse_iso_date(end_date)
    # Normalize end_date to end-of-day when caller passed a bare date.
    if end_dt and end_date and len(end_date) == 10:
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    events, source = await _collect_audit_events_for_export(
        workspace_id,
        user.access_token or "",
        start_date=start_dt,
        end_date=end_dt,
        action=action or None,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    safe_ws = re.sub(r"[^A-Za-z0-9._-]+", "_", workspace_id)[:40] or "workspace"

    await log_audit(
        "audit.exported",
        f"Exported audit log ({format.upper()}, {len(events)} rows)",
        user_id=user.user_id,
        workspace_id=workspace_id,
        metadata={"format": format, "count": len(events), "source": source},
    )

    if format == "json":
        payload = {
            "workspace_id": workspace_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": user.user_id,
            "source": source,
            "filters": {
                "start_date": start_dt.isoformat() if start_dt else None,
                "end_date": end_dt.isoformat() if end_dt else None,
                "action": action or None,
            },
            "total": len(events),
            "events": events,
        }
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        filename = f"audit_{safe_ws}_{stamp}.json"
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "event_id",
        "timestamp",
        "action",
        "description",
        "actor_user_id",
        "actor_email",
        "actor_name",
        "target_user_id",
        "target_email",
        "target_name",
        "old_role",
        "new_role",
    ])
    for ev in events:
        writer.writerow([
            ev.get("event_id") or "",
            ev.get("timestamp") or "",
            ev.get("action") or "",
            (ev.get("description") or "").replace("\n", " ").strip(),
            ev.get("actor_user_id") or "",
            ev.get("actor_email") or "",
            ev.get("actor_name") or "",
            ev.get("target_user_id") or "",
            ev.get("target_email") or "",
            ev.get("target_name") or "",
            ev.get("old_role") or "",
            ev.get("new_role") or "",
        ])
    body_str = buf.getvalue()
    # Prepend UTF-8 BOM so Excel opens the file with the right encoding.
    csv_bytes = b"\xef\xbb\xbf" + body_str.encode("utf-8")
    filename = f"audit_{safe_ws}_{stamp}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )




# ─── Health ────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "running", "service": "Quantro Flow | Business OS", "timestamp": datetime.utcnow().isoformat()}

# ─── System Health / Self-Healing Surface ─────────────────────────────
@app.get("/api/system/health")
async def system_health(workspace_id: str = Depends(get_current_workspace_id)):
    """Surface the self-healing layer to the UI.

    Returns the current state of the Quantro OS integrity layer, including
    the most recent startup check, any repairs that were applied, and a
    rolling summary. Powers the "System Status: Healthy" trust banner and
    the Dashboard "System Health" card."""
    # Latest check (workspace-scoped)
    latest = await system_health_col.find_one(
        {"scope": "integrations", "workspace_id": {"$in": [workspace_id, DEFAULT_WORKSPACE_ID]}},
        sort=[("checked_at", -1)],
        projection={"_id": 0},
    )

    # Basic integrity count
    integrations_total = await integrations_config_col.count_documents({"workspace_id": workspace_id})
    integrations_expected = len(DEFAULT_INTEGRATIONS_CATALOG)
    integrations_ok = integrations_total >= integrations_expected

    # Business profile existence
    profile_exists = await business_profile_col.count_documents({"workspace_id": workspace_id}) > 0

    # Recent repairs (last 10)
    recent_repairs = await system_health_col.find(
        {"repair_count": {"$gt": 0}, "workspace_id": {"$in": [workspace_id, DEFAULT_WORKSPACE_ID]}},
        sort=[("checked_at", -1)],
        projection={"_id": 0},
    ).to_list(10)

    # Total repair events lifetime
    total_repair_events = await system_health_col.count_documents({"repair_count": {"$gt": 0}, "workspace_id": {"$in": [workspace_id, DEFAULT_WORKSPACE_ID]}})

    # Overall status — initialize defensively so static analyzers see a
    # value on every code path (the if/elif/else below already covers all
    # cases, but this guard prevents future refactors from regressing).
    overall = "healthy"
    if not integrations_ok or not profile_exists:
        overall = "degraded"
    elif latest and latest.get("repair_count", 0) > 0:
        overall = "repaired"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "tagline": "Quantro OS detects and fixes issues before you notice them.",
        "last_checked_at": (latest or {}).get("checked_at").isoformat() if latest and latest.get("checked_at") else None,
        "checks": [
            {
                "id": "integrations",
                "label": "Integrations stable",
                "ok": integrations_ok,
                "detail": (
                    f"{integrations_total}/{integrations_expected} providers registered"
                    if integrations_ok
                    else f"Missing providers ({integrations_expected - integrations_total})"
                ),
            },
            {
                "id": "data_consistency",
                "label": "Data consistency verified",
                "ok": profile_exists,
                "detail": "Business profile present" if profile_exists else "Business profile missing",
            },
            {
                "id": "issues",
                "label": "No issues detected" if overall != "degraded" else "Issues detected",
                "ok": overall != "degraded",
                "detail": (
                    f"{(latest or {}).get('repair_count', 0)} auto-repair(s) on last startup"
                    if latest and latest.get("repair_count", 0) > 0
                    else "All systems operational"
                ),
            },
            *(await _quantro_connect_health_checks(workspace_id)),
        ],
        "latest_check": serialize_doc(latest) if latest else None,
        "recent_repairs": [serialize_doc(r) for r in recent_repairs],
        "total_repair_events": total_repair_events,
    }


async def _quantro_connect_health_checks(workspace_id: str) -> List[Dict[str, Any]]:
    """Quantro Connect + Actions checks, additive to the pre-existing
    System Health checks above. Deliberately does NOT feed into
    `overall` (healthy/degraded/repaired) — an unconfigured *optional*
    provider (e.g. Microsoft OAuth not set up in this deployment, or no
    Facturapi connection yet) is informational, not a platform failure;
    per the task spec, a provider with insufficient scope is "limited",
    not a system failure either."""
    checks: List[Dict[str, Any]] = []

    providers = list_connect_providers()
    checks.append({
        "id": "provider_registry", "label": "Provider registry loaded",
        "ok": len(providers) > 0,
        "detail": f"{len(providers)} provider(s) registered: {', '.join(p.provider_id for p in providers)}",
    })

    all_actions = list_actions()
    checks.append({
        "id": "action_registry", "label": "Action registry loaded",
        "ok": len(all_actions) > 0,
        "detail": f"{len(all_actions)} action(s) registered across {len({a.provider for a in all_actions})} provider(s)",
    })

    checks.append({
        "id": "secret_encryption", "label": "Secret encryption configured",
        "ok": integration_secrets.is_encryption_configured(),
        "detail": (
            "Using a dedicated INTEGRATIONS_ENCRYPTION_KEY" if integration_secrets.using_dedicated_key()
            else "Falling back to GOOGLE_TOKENS_ENCRYPTION_KEY — set INTEGRATIONS_ENCRYPTION_KEY for production"
            if integration_secrets.is_encryption_configured()
            else "No encryption key configured — provider secrets cannot be stored"
        ),
    })

    checks.append({
        "id": "oauth_configuration", "label": "OAuth providers configured",
        "ok": goog.is_oauth_configured(),  # Google is the one existing users depend on today
        "detail": f"Google: {'configured' if goog.is_oauth_configured() else 'not configured'} · Microsoft: {'configured' if msoa.is_oauth_configured() else 'not configured'}",
    })

    facturapi_doc = await facturapi_connections_col.find_one({"workspace_id": workspace_id}, {"_id": 0, "status": 1, "last_error": 1, "environment": 1})
    checks.append({
        "id": "facturapi_connectivity", "label": "Facturapi connectivity",
        "ok": not facturapi_doc or facturapi_doc.get("status") != "error",
        "detail": (
            "Not connected for this workspace" if not facturapi_doc
            else f"Connected ({facturapi_doc.get('environment')})" if facturapi_doc.get("status") != "error"
            else f"Last check failed: {facturapi_doc.get('last_error') or 'unknown error'}"
        ),
    })

    limited: List[str] = []
    stale: List[str] = []
    for adapter in providers:
        if adapter.provider_id == "quantro_internal":
            continue
        status = await adapter.get_status(workspace_id)
        if status.status == ConnectionStatus.CONNECTED_LIMITED:
            limited.append(adapter.provider_id)
        if status.status == ConnectionStatus.CONNECTED and adapter.supports_sync:
            if not status.last_sync_at:
                stale.append(adapter.provider_id)
            else:
                try:
                    last_sync = datetime.fromisoformat(status.last_sync_at.replace("Z", "+00:00"))
                    if last_sync.tzinfo is None:
                        last_sync = last_sync.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - last_sync > timedelta(days=7):
                        stale.append(adapter.provider_id)
                except ValueError:
                    pass

    checks.append({
        "id": "missing_scopes", "label": "No providers missing required scopes",
        "ok": len(limited) == 0,
        "detail": "All connected providers have full scope" if not limited else f"Missing action scopes: {', '.join(limited)}",
    })
    checks.append({
        "id": "stale_connections", "label": "No stale connections",
        "ok": len(stale) == 0,
        "detail": "All syncs are recent" if not stale else f"No sync in 7+ days: {', '.join(stale)}",
    })

    recent_failed_webhooks = await facturapi_webhook_events_col.count_documents({
        "workspace_id": workspace_id, "signature_valid": False,
        "received_at": {"$gte": datetime.now(timezone.utc) - timedelta(hours=24)},
    })
    checks.append({
        "id": "webhook_failures", "label": "No recent webhook signature failures",
        "ok": recent_failed_webhooks == 0,
        "detail": "No failures in the last 24h" if recent_failed_webhooks == 0 else f"{recent_failed_webhooks} unverified webhook event(s) in the last 24h",
    })

    return checks

# ─── Plan & Usage ──────────────────────────────────────────────────────
# NOTE: /api/usage was removed (P5 cleanup) — it was dead code. The real
# Plan & Usage screen (frontend/src/pages/PlanAndUsage.js) reads billing
# and usage data directly from Supabase and never called this endpoint.




# ─── Dashboard ─────────────────────────────────────────────────────────
@app.get("/api/dashboard/metrics")
async def get_dashboard_metrics(workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    total_agents = await agents_col.count_documents(mode_filter)
    active_agents = await agents_col.count_documents(merge_query({"status": "active"}, mode_filter))
    total_contacts = await contacts_col.count_documents(mode_filter)
    total_inbox = await inbox_col.count_documents(mode_filter)
    unread_inbox = await inbox_col.count_documents(merge_query({"read": False}, mode_filter))
    today_events = await calendar_col.count_documents(mode_filter)
    synced_contacts = await contacts_col.count_documents(merge_query({"ghl_sync_status": "synced"}, mode_filter))
    total_content = await content_col.count_documents(mode_filter)

    return {
        "agents": {"total": total_agents, "active": active_agents},
        "contacts": {"total": total_contacts, "synced": synced_contacts},
        "inbox": {"total": total_inbox, "unread": unread_inbox},
        "events": {"today": today_events},
        "content": {"total": total_content},
        "system_status": "running",
        "last_sync": datetime.utcnow().isoformat(),
        "simulation_mode": await is_simulation_mode(workspace_id),
    }

@app.get("/api/dashboard/suggestions")
async def get_ai_suggestions(workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    unprocessed = await inbox_col.find(merge_query({"status": "new", "ai_intent": None}, mode_filter)).to_list(5)
    processed_pending = await inbox_col.find(merge_query({"status": "processed", "ai_intent": {"$ne": None}}, mode_filter)).to_list(5)
    suggestions = []
    for item in unprocessed:
        suggestions.append({
            "type": "analyze",
            "title": f"Analyze: {item['subject']}",
            "description": f"New message from {item['from_name']} needs AI analysis",
            "inbox_id": item["inbox_id"],
            "priority": "high" if "urgent" in item.get("subject", "").lower() else "normal"
        })
    for item in processed_pending:
        action_type = item["ai_suggested_action"]["type"] if item.get("ai_suggested_action") else "review"
        suggestions.append({
            "type": "action",
            "title": f"Action: {item['ai_suggested_action']['description']}" if item.get("ai_suggested_action") else f"Review: {item['subject']}",
            "description": f"AI suggests: {action_type} for {item['from_name']}",
            "inbox_id": item["inbox_id"],
            "priority": "normal"
        })
    return suggestions

# ─── Inbox ─────────────────────────────────────────────────────────────
@app.get("/api/inbox")
async def get_inbox(status: Optional[str] = None, workspace_id: str = Depends(get_current_workspace_id)):
    query = {}
    if status:
        query["status"] = status
    mode_filter = await get_mode_filter(workspace_id)
    items = await inbox_col.find(merge_query(query, mode_filter)).sort("received_at", -1).to_list(100)
    return [serialize_doc(item) for item in items]

@app.get("/api/inbox/{inbox_id}")
async def get_inbox_item(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    item = await inbox_col.find_one(merge_query({"inbox_id": inbox_id}, mode_filter))
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    return serialize_doc(item)

@app.post("/api/inbox/{inbox_id}/analyze")
async def analyze_inbox_item(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id), user: User = Depends(get_current_user)):
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    # Get business profile for context-aware prompts
    intent_prompt = await build_intent_prompt(workspace_id=workspace_id)
    language = await _workspace_language(workspace_id)

    message_text = f"From: {item['from_name']} ({item['from_email']})\nSubject: {item['subject']}\n\n{item['body']}"

    ai_response = await run_ai_request(
        user_id=user.user_id,
        email=user.email,
        access_token=user.access_token,
        system_prompt=intent_prompt,
        user_prompt=message_text,
        language=language,
    )
    ai_result = await parse_ai_json(ai_response["text"])
    
    if not ai_result:
        ai_result = {"intent": "needs_review", "confidence": 0.0, "summary": "AI could not parse this message", "entities": {}, "suggested_action": {"type": "flag_review", "description": "Manual review required"}}
    
    await inbox_col.update_one(
        {"inbox_id": inbox_id},
        {"$set": {
            "ai_intent": {"intent": ai_result["intent"], "confidence": ai_result["confidence"], "summary": ai_result["summary"], "entities": ai_result.get("entities", {})},
            "ai_suggested_action": ai_result.get("suggested_action"),
            "status": "processed",
            "read": True,
        }}
    )
    
    await log_activity("ai", "AI processed inbox", f"Intent: {ai_result['intent']} ({ai_result['confidence']:.0%}) - {ai_result['summary']}", inbox_id, "inbox")
    
    # Evaluate policy
    intent = ai_result["intent"]
    confidence = ai_result["confidence"]
    policy = await policies_col.find_one({"workspace_id": workspace_id, "intent": intent, "enabled": True})
    policy_action = "manual_review"
    escalation_info = None
    
    if policy:
        if confidence >= policy.get("confidence_threshold_high", 0.85):
            policy_action = policy.get("high_action", "auto_run")
        elif confidence >= policy.get("confidence_threshold_medium", 0.6):
            policy_action = policy.get("medium_action", "require_approval")
        else:
            policy_action = policy.get("low_action", "escalate")
    policy_action = _normalize_policy_action(policy_action)

    # Evaluate advanced escalation conditions (applies to all policy actions)
    updated_item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    escalation_info = await evaluate_advanced_escalation(updated_item, intent, confidence, policy_action)

    # If escalation triggered, override policy action
    if escalation_info:
        policy_action = "escalate"

    # Auto-execute if policy says auto_run and no escalation. The
    # `auto_executed` / `execution_results` locals are kept (even though
    # not used in this single-analyze response) because the caller
    # endpoint downstream surfaces them via the persisted inbox row.
    if policy_action == "auto_run" and not escalation_info:
        await execute_action_for_item(updated_item, source="single_analyze")
    
    await inbox_col.update_one(
        {"inbox_id": inbox_id},
        {"$set": {"policy_action": policy_action, "escalation": escalation_info}}
    )
    
    updated = await inbox_col.find_one({"inbox_id": inbox_id})
    return serialize_doc(updated)

@app.post("/api/inbox/{inbox_id}/approve")
async def approve_inbox_action(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not item.get("ai_suggested_action"):
        raise HTTPException(status_code=400, detail="No AI action to approve")
    
    action = item["ai_suggested_action"]
    action_type = action["type"]
    results = []
    sim_flag = bool(item.get("is_simulation", False))
    ws_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)
    
    # Execute action based on type
    if action_type == "schedule_meeting":
        entities = item.get("ai_intent", {}).get("entities", {})
        event = {
            "event_id": str(uuid.uuid4()),
            "title": f"Meeting - {item['from_name']}",
            "description": action["description"],
            "start_time": (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat(),
            "location": entities.get("property", "TBD"),
            "attendees": [item["from_name"]],
            "status": "pending",
            "source": "ai_action",
            "created_at": now_iso(),
            "contact_id": item.get("contact_id"),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await calendar_col.insert_one(event)
        await log_activity("calendar", "Meeting scheduled", f"Meeting with {item['from_name']} created from AI action", event["event_id"], "calendar")
        results.append({"type": "event_created", "event_id": event["event_id"]})
    
    elif action_type == "create_contact":
        entities = item.get("ai_intent", {}).get("entities", {})
        contact = {
            "contact_id": str(uuid.uuid4()),
            "name": entities.get("person_name", item["from_name"]),
            "email": entities.get("email", item["from_email"]),
            "phone": entities.get("phone", ""),
            "type": "lead",
            "lifecycle_stage": "new",
            "source": "inbox",
            "ghl_sync_status": "pending",
            "ghl_last_sync": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": item.get("ai_intent", {}).get("summary", ""),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await contacts_col.insert_one(contact)
        await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"contact_id": contact["contact_id"]}})
        await log_activity("crm", "Contact created", f"New contact {contact['name']} from inbox action", contact["contact_id"], "contact")
        results.append({"type": "contact_created", "contact_id": contact["contact_id"]})
    
    elif action_type == "start_onboarding":
        entities = item.get("ai_intent", {}).get("entities", {})
        agent = {
            "agent_id": str(uuid.uuid4()),
            "name": entities.get("person_name", item["from_name"]),
            "email": entities.get("email", item["from_email"]),
            "phone": entities.get("phone", ""),
            "role": "agent",
            "status": "onboarding",
            "start_date": datetime.utcnow().isoformat(),
            "photo_url": None,
            "created_at": now_iso(),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await agents_col.insert_one(agent)
        
        default_tasks = [
            "Complete compliance training",
            "Set up CRM profile",
            "Configure email signature",
            "Schedule orientation with team lead",
            "Access granted to listing portal",
        ]
        for i, task_title in enumerate(default_tasks):
            task = {
                "task_id": str(uuid.uuid4()),
                "agent_id": agent["agent_id"],
                "title": task_title,
                "description": f"Auto-generated onboarding step {i+1}",
                "status": "pending",
                "order": i + 1,
                "completed_at": None,
                "auto_generated": True,
                "is_simulation": sim_flag,
                "workspace_id": ws_id,
            }
            await onboarding_col.insert_one(task)
        
        await log_activity("onboarding", "Onboarding started", f"New agent {agent['name']} - onboarding initiated", agent["agent_id"], "agent")
        results.append({"type": "agent_created", "agent_id": agent["agent_id"]})
    
    elif action_type == "send_follow_up":
        await log_activity("inbox", "Follow-up queued", f"Follow-up action queued for {item['from_name']}", inbox_id, "inbox")
        results.append({"type": "follow_up_queued"})
    
    elif action_type == "flag_review":
        await log_activity("inbox", "Flagged for review", f"Message from {item['from_name']} flagged for manual review", inbox_id, "inbox")
        results.append({"type": "flagged"})
    
    else:
        await log_activity("inbox", "Action approved", f"Action '{action_type}' approved for {item['from_name']}", inbox_id, "inbox")
        results.append({"type": action_type})
    
    await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"status": "actioned"}})
    
    return {"success": True, "action_type": action_type, "results": results}

@app.post("/api/inbox/{inbox_id}/decline")
async def decline_inbox_action(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"status": "declined"}})
    await log_activity("inbox", "Action declined", f"AI suggestion for {item['from_name']} was declined", inbox_id, "inbox")
    return {"success": True}

# ─── Batch AI Triage ───────────────────────────────────────────────────
@app.post("/api/inbox/batch-analyze")
async def batch_analyze_inbox(req: BatchAnalyzeRequest, workspace_id: str = Depends(get_current_workspace_id), user: User = Depends(get_current_user)):
    """Process multiple inbox items with AI classification in sequence."""
    results = []
    
    # Get business profile once for all items
    intent_prompt = await build_intent_prompt(workspace_id=workspace_id)
    language = await _workspace_language(workspace_id)
    
    for inbox_id in req.inbox_ids:
        item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
        if not item:
            results.append({"inbox_id": inbox_id, "status": "error", "error": "Not found"})
            continue
        
        # Mark as processing
        await inbox_col.update_one(
            {"inbox_id": inbox_id},
            {"$set": {"status": "processing"}}
        )
        
        try:
            message_text = f"From: {item['from_name']} ({item['from_email']})\nSubject: {item['subject']}\n\n{item['body']}"
            ai_response = await run_ai_request(
                user_id=user.user_id,
                email=user.email,
                access_token=user.access_token,
                system_prompt=intent_prompt,
                user_prompt=message_text,
                language=language,
            )
            ai_result = await parse_ai_json(ai_response["text"])
            
            if not ai_result:
                ai_result = {"intent": "needs_review", "confidence": 0.0, "summary": "Could not analyze this message", "entities": {}, "suggested_action": {"type": "flag_review", "description": "Manual review required"}}
            
            await inbox_col.update_one(
                {"inbox_id": inbox_id},
                {"$set": {
                    "ai_intent": {"intent": ai_result["intent"], "confidence": ai_result["confidence"], "summary": ai_result["summary"], "entities": ai_result.get("entities", {})},
                    "ai_suggested_action": ai_result.get("suggested_action"),
                    "status": "processed",
                    "read": True,
                }}
            )
            
            await log_activity("ai", "Batch triage classified", f"{item['from_name']}: {ai_result['intent']} ({ai_result['confidence']:.0%})", inbox_id, "inbox")
            
            # Evaluate policy for this item
            intent = ai_result["intent"]
            confidence = ai_result["confidence"]
            policy = await policies_col.find_one({"workspace_id": workspace_id, "intent": intent, "enabled": True})
            policy_action = "manual_review"
            escalation_info = None
            
            if policy:
                if confidence >= policy.get("confidence_threshold_high", 0.85):
                    policy_action = policy.get("high_action", "auto_run")
                elif confidence >= policy.get("confidence_threshold_medium", 0.6):
                    policy_action = policy.get("medium_action", "require_approval")
                else:
                    policy_action = policy.get("low_action", "escalate")
            policy_action = _normalize_policy_action(policy_action)

            # Evaluate advanced escalation conditions (applies to all policy actions)
            updated_item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
            escalation_info = await evaluate_advanced_escalation(updated_item, intent, confidence, policy_action)
            
            # If escalation triggered, override policy action
            if escalation_info:
                policy_action = "escalate"
            
            # Auto-execute if policy says auto_run and no escalation
            auto_executed = False
            execution_results = None
            if policy_action == "auto_run" and not escalation_info:
                exec_result = await execute_action_for_item(updated_item, source="batch_analyze")
                auto_executed = exec_result.get("executed", False)
                execution_results = exec_result.get("results")
            
            # Store policy evaluation result on the item
            await inbox_col.update_one(
                {"inbox_id": inbox_id},
                {"$set": {
                    "policy_action": policy_action,
                    "escalation": escalation_info,
                }}
            )
            
            updated = await inbox_col.find_one({"inbox_id": inbox_id})
            result_data = {
                "inbox_id": inbox_id,
                "status": "classified",
                "data": serialize_doc(updated),
                "policy_action": policy_action,
                "escalation": escalation_info,
                "auto_executed": auto_executed,
            }
            if execution_results:
                result_data["execution_results"] = execution_results
            results.append(result_data)
            
        except HTTPException:
            # AI billing block / provider error → fail fast so the
            # whole batch surfaces a single 402/503 to the UI instead
            # of swallowing it as per-item "error".
            await inbox_col.update_one(
                {"inbox_id": inbox_id},
                {"$set": {"status": "new"}}
            )
            raise
        except Exception as e:
            await inbox_col.update_one(
                {"inbox_id": inbox_id},
                {"$set": {"status": "new"}}
            )
            results.append({"inbox_id": inbox_id, "status": "error", "error": str(e)})
    
    await log_activity("ai", "Batch triage complete", f"Processed {len(req.inbox_ids)} message(s), {sum(1 for r in results if r['status'] == 'classified')} classified", None, "inbox")
    
    return {"success": True, "results": results, "total": len(req.inbox_ids), "classified": sum(1 for r in results if r["status"] == "classified")}

@app.post("/api/inbox/batch-approve")
async def batch_approve_inbox(req: BatchAnalyzeRequest, workspace_id: str = Depends(get_current_workspace_id)):
    """Approve all AI-suggested actions for multiple inbox items."""
    results = []
    
    for inbox_id in req.inbox_ids:
        item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
        if not item or not item.get("ai_suggested_action"):
            results.append({"inbox_id": inbox_id, "status": "skipped", "reason": "No action available"})
            continue
        
        if item.get("status") in ["actioned", "declined"]:
            results.append({"inbox_id": inbox_id, "status": "skipped", "reason": f"Already {item['status']}"})
            continue
        
        try:
            # Reuse the existing approve logic
            action = item["ai_suggested_action"]
            action_type = action["type"]
            sim_flag = bool(item.get("is_simulation", False))
            ws_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)
            
            if action_type == "schedule_meeting":
                entities = item.get("ai_intent", {}).get("entities", {})
                event = {
                    "event_id": str(uuid.uuid4()),
                    "title": f"Meeting - {item['from_name']}",
                    "description": action["description"],
                    "start_time": (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat(),
                    "end_time": (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat(),
                    "location": entities.get("property", "TBD"),
                    "attendees": [item["from_name"]],
                    "status": "pending",
                    "source": "ai_batch",
                    "created_at": now_iso(),
                    "contact_id": item.get("contact_id"),
                    "is_simulation": sim_flag,
                    "workspace_id": ws_id,
                }
                await calendar_col.insert_one(event)
                await log_activity("calendar", "Meeting scheduled (batch)", f"Meeting with {item['from_name']}", event["event_id"], "calendar")
            
            elif action_type == "create_contact":
                entities = item.get("ai_intent", {}).get("entities", {})
                contact = {
                    "contact_id": str(uuid.uuid4()),
                    "name": entities.get("person_name", item["from_name"]),
                    "email": entities.get("email", item["from_email"]),
                    "phone": entities.get("phone", ""),
                    "type": "lead",
                    "lifecycle_stage": "new",
                    "source": "inbox_batch",
                    "ghl_sync_status": "pending",
                    "ghl_last_sync": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": item.get("ai_intent", {}).get("summary", ""),
                    "is_simulation": sim_flag,
                    "workspace_id": ws_id,
                }
                await contacts_col.insert_one(contact)
                await log_activity("crm", "Contact created (batch)", f"New contact {contact['name']}", contact["contact_id"], "contact")
            
            elif action_type == "send_follow_up":
                await log_activity("inbox", "Follow-up queued (batch)", f"For {item['from_name']}", inbox_id, "inbox")
            
            elif action_type == "start_onboarding":
                entities = item.get("ai_intent", {}).get("entities", {})
                agent = {
                    "agent_id": str(uuid.uuid4()),
                    "name": entities.get("person_name", item["from_name"]),
                    "email": entities.get("email", item["from_email"]),
                    "phone": entities.get("phone", ""),
                    "role": "agent",
                    "status": "onboarding",
                    "start_date": datetime.utcnow().isoformat(),
                    "photo_url": None,
                    "created_at": now_iso(),
                    "is_simulation": sim_flag,
                    "workspace_id": ws_id,
                }
                await agents_col.insert_one(agent)
                for idx, title in enumerate(["Complete compliance training", "Set up CRM profile", "Configure email signature", "Schedule orientation with team lead", "Access granted to listing portal"]):
                    await onboarding_col.insert_one({
                "workspace_id": workspace_id,"task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"], "title": title, "description": f"Auto-generated step {idx+1}", "status": "pending", "order": idx + 1, "completed_at": None, "auto_generated": True, "is_simulation": sim_flag})
                await log_activity("onboarding", "Onboarding started (batch)", f"Agent {agent['name']} onboarding initiated", agent["agent_id"], "agent")
            
            else:
                await log_activity("inbox", "Action approved (batch)", f"For {item['from_name']}", inbox_id, "inbox")
            
            await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"status": "actioned"}})
            results.append({"inbox_id": inbox_id, "status": "actioned", "action_type": action_type})
            
        except Exception as e:
            results.append({"inbox_id": inbox_id, "status": "error", "error": str(e)})
    
    actioned_count = sum(1 for r in results if r["status"] == "actioned")
    await log_activity("system", "Batch approval complete", f"{actioned_count}/{len(req.inbox_ids)} actions executed", None, "inbox")
    
    return {"success": True, "results": results, "total": len(req.inbox_ids), "actioned": actioned_count}

# ─── Manual Override (Edit Details) ────────────────────────────────────
@app.put("/api/inbox/{inbox_id}/details")
async def update_inbox_details(inbox_id: str, req: UpdateInboxDetailsRequest, workspace_id: str = Depends(get_current_workspace_id)):
    """Allow user to edit AI-extracted entities and suggested action before approving."""
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    update_fields = {}
    
    if req.entities is not None:
        current_intent = item.get("ai_intent", {})
        current_intent["entities"] = req.entities
        update_fields["ai_intent"] = current_intent
    
    if req.summary is not None:
        current_intent = item.get("ai_intent", {})
        current_intent["summary"] = req.summary
        update_fields["ai_intent"] = current_intent
    
    if req.suggested_action_type is not None or req.suggested_action_description is not None:
        current_action = item.get("ai_suggested_action", {}) or {}
        if req.suggested_action_type is not None:
            current_action["type"] = req.suggested_action_type
        if req.suggested_action_description is not None:
            current_action["description"] = req.suggested_action_description
        update_fields["ai_suggested_action"] = current_action
    
    if update_fields:
        await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": update_fields})
        await log_activity("inbox", "Details edited", f"Manual adjustments made to {item['from_name']}'s request", inbox_id, "inbox")
    
    updated = await inbox_col.find_one({"inbox_id": inbox_id})
    return serialize_doc(updated)

@app.post("/api/inbox/{inbox_id}/approve-with-overrides")
async def approve_with_overrides(inbox_id: str, req: ApproveWithOverridesRequest, workspace_id: str = Depends(get_current_workspace_id)):
    """Approve an action with optional manual overrides for details."""
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not item.get("ai_suggested_action"):
        raise HTTPException(status_code=400, detail="No action to approve")
    
    action = item["ai_suggested_action"]
    action_type = action["type"]
    entities = item.get("ai_intent", {}).get("entities", {})
    results = []
    sim_flag = bool(item.get("is_simulation", False))
    ws_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)
    
    if action_type == "schedule_meeting":
        event = {
            "event_id": str(uuid.uuid4()),
            "title": req.title or f"Meeting - {item['from_name']}",
            "description": req.description or action["description"],
            "start_time": req.start_time or (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat(),
            "end_time": req.end_time or (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat(),
            "location": req.location or entities.get("property", "TBD"),
            "attendees": req.attendees or [item["from_name"]],
            "status": "confirmed",
            "source": "ai_override",
            "created_at": now_iso(),
            "contact_id": item.get("contact_id"),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await calendar_col.insert_one(event)
        await log_activity("calendar", "Meeting scheduled", f"Meeting with {item['from_name']} (with adjustments)", event["event_id"], "calendar")
        results.append({"type": "event_created", "event_id": event["event_id"]})
    
    elif action_type == "create_contact":
        contact = {
            "contact_id": str(uuid.uuid4()),
            "name": req.contact_name or entities.get("person_name", item["from_name"]),
            "email": req.contact_email or entities.get("email", item["from_email"]),
            "phone": req.contact_phone or entities.get("phone", ""),
            "type": "lead",
            "lifecycle_stage": "new",
            "source": "inbox",
            "ghl_sync_status": "pending",
            "ghl_last_sync": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": item.get("ai_intent", {}).get("summary", ""),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await contacts_col.insert_one(contact)
        await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"contact_id": contact["contact_id"]}})
        await log_activity("crm", "Contact created", f"New contact {contact['name']} (with adjustments)", contact["contact_id"], "contact")
        results.append({"type": "contact_created", "contact_id": contact["contact_id"]})
    
    elif action_type == "start_onboarding":
        agent = {
            "agent_id": str(uuid.uuid4()),
            "name": req.contact_name or entities.get("person_name", item["from_name"]),
            "email": req.contact_email or entities.get("email", item["from_email"]),
            "phone": req.contact_phone or entities.get("phone", ""),
            "role": "agent",
            "status": "onboarding",
            "start_date": datetime.utcnow().isoformat(),
            "photo_url": None,
            "created_at": now_iso(),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await agents_col.insert_one(agent)
        for idx, title in enumerate(["Complete compliance training", "Set up CRM profile", "Configure email signature", "Schedule orientation with team lead", "Access granted to listing portal"]):
            await onboarding_col.insert_one({"workspace_id": ws_id, "task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"], "title": title, "description": f"Auto-generated step {idx+1}", "status": "pending", "order": idx + 1, "completed_at": None, "auto_generated": True, "is_simulation": sim_flag})
        await log_activity("onboarding", "Onboarding started", f"Agent {agent['name']} onboarding initiated (with adjustments)", agent["agent_id"], "agent")
        results.append({"type": "agent_created", "agent_id": agent["agent_id"]})
    
    elif action_type == "send_follow_up":
        await log_activity("inbox", "Follow-up queued", f"Follow-up for {item['from_name']}", inbox_id, "inbox")
        results.append({"type": "follow_up_queued"})
    
    else:
        await log_activity("inbox", "Action approved", f"For {item['from_name']}", inbox_id, "inbox")
        results.append({"type": action_type})
    
    await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"status": "actioned"}})
    
    return {"success": True, "action_type": action_type, "results": results}

# ─── Calendar ──────────────────────────────────────────────────────────
@app.get("/api/calendar")
async def get_calendar_events(workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    events = await calendar_col.find(mode_filter).sort("start_time", 1).to_list(100)
    return [serialize_doc(e) for e in events]

@app.post("/api/calendar", status_code=201)
async def create_calendar_event(req: CreateEventRequest, workspace_id: str = Depends(get_current_workspace_id)):
    event = {
        "event_id": str(uuid.uuid4()),
        "title": req.title,
        "description": req.description,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "location": req.location,
        "attendees": req.attendees,
        "status": "confirmed",
        "source": "manual",
        "created_at": now_iso(),
        "contact_id": req.contact_id,
        "is_simulation": await is_simulation_mode(workspace_id),
        "workspace_id": workspace_id,
    }
    await calendar_col.insert_one(event)
    await log_activity("calendar", "Event created", f"New event: {req.title}", event["event_id"], "calendar", workspace_id=workspace_id)
    return serialize_doc(event)

@app.delete("/api/calendar/{event_id}")
async def delete_calendar_event(event_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    result = await calendar_col.delete_one({"event_id": event_id, "workspace_id": workspace_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True}

# ─── Contacts / CRM ───────────────────────────────────────────────────
@app.get("/api/contacts")
async def get_contacts(lifecycle_stage: Optional[str] = None, workspace_id: str = Depends(get_current_workspace_id)):
    query = {}
    if lifecycle_stage:
        query["lifecycle_stage"] = lifecycle_stage
    mode_filter = await get_mode_filter(workspace_id)
    contacts = await contacts_col.find(merge_query(query, mode_filter)).sort("updated_at", -1).to_list(100)
    return [serialize_doc(c) for c in contacts]

@app.get("/api/contacts/{contact_id}")
async def get_contact(contact_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    contact = await contacts_col.find_one(merge_query({"contact_id": contact_id}, mode_filter))
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get related inbox items (mode-scoped to prevent cross-mode leakage)
    inbox_items = await inbox_col.find(merge_query({"contact_id": contact_id}, mode_filter)).sort("received_at", -1).to_list(10)
    events = await calendar_col.find(merge_query({"contact_id": contact_id}, mode_filter)).sort("start_time", -1).to_list(10)
    activities = await activity_col.find(merge_query({"related_id": contact_id}, mode_filter)).sort("timestamp", -1).to_list(20)

    result = serialize_doc(contact)
    result["inbox_items"] = [serialize_doc(i) for i in inbox_items]
    result["events"] = [serialize_doc(e) for e in events]
    result["activities"] = [serialize_doc(a) for a in activities]
    return result

@app.post("/api/contacts")
async def create_contact(req: CreateContactRequest, workspace_id: str = Depends(get_current_workspace_id)):
    contact = {
        "contact_id": str(uuid.uuid4()),
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "type": req.type,
        "lifecycle_stage": "new",
        "source": req.source,
        "ghl_sync_status": "pending",
        "ghl_last_sync": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "notes": req.notes,
        "is_simulation": await is_simulation_mode(workspace_id),
        "workspace_id": workspace_id,
    }
    await contacts_col.insert_one(contact)
    await log_activity("crm", "Contact created", f"New contact: {req.name}", contact["contact_id"], "contact", workspace_id=workspace_id)
    return serialize_doc(contact)

# ─── Agents ────────────────────────────────────────────────────────────
@app.get("/api/agents")
async def get_agents(workspace_id: str = Depends(get_current_workspace_id)):
    mode_filter = await get_mode_filter(workspace_id)
    agents = await agents_col.find(mode_filter).sort("created_at", -1).to_list(100)
    result = []
    for agent in agents:
        a = serialize_doc(agent)
        tasks = await onboarding_col.find({"agent_id": agent["agent_id"]}).sort("order", 1).to_list(20)
        a["onboarding_tasks"] = [serialize_doc(t) for t in tasks]
        total = len(tasks)
        completed = len([t for t in tasks if t["status"] == "completed"])
        a["onboarding_progress"] = (completed / total * 100) if total > 0 else 0
        result.append(a)
    return result

@app.post("/api/agents")
async def create_agent(req: CreateAgentRequest, workspace_id: str = Depends(get_current_workspace_id)):
    sim_flag = await is_simulation_mode(workspace_id)
    agent = {
        "agent_id": str(uuid.uuid4()),
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "role": req.role,
        "status": "onboarding",
        "start_date": datetime.utcnow().isoformat(),
        "photo_url": None,
        "created_at": now_iso(),
        "is_simulation": sim_flag,
        "workspace_id": workspace_id,
    }
    await agents_col.insert_one(agent)
    
    default_tasks = [
        ("Complete compliance training", "Review and sign all compliance documents"),
        ("Set up CRM profile", "Configure GoHighLevel profile and sync"),
        ("Configure email signature", "Set up branded email signature template"),
        ("Schedule orientation with team lead", "Book 1:1 orientation meeting"),
        ("Access granted to listing portal", "Get login credentials for MLS and listing tools"),
    ]
    for i, (title, desc) in enumerate(default_tasks):
        task = {
            "task_id": str(uuid.uuid4()),
            "agent_id": agent["agent_id"],
            "title": title,
            "description": desc,
            "status": "pending",
            "order": i + 1,
            "completed_at": None,
            "auto_generated": True,
            "is_simulation": sim_flag,
            "workspace_id": workspace_id,
        }
        await onboarding_col.insert_one(task)
    
    await log_activity("onboarding", "New agent added", f"{req.name} added to the team. Onboarding initiated.", agent["agent_id"], "agent")
    
    # Return with tasks
    tasks = await onboarding_col.find({"agent_id": agent["agent_id"]}).sort("order", 1).to_list(20)
    result = serialize_doc(agent)
    result["onboarding_tasks"] = [serialize_doc(t) for t in tasks]
    result["onboarding_progress"] = 0
    return result

# ─── Onboarding Tasks ─────────────────────────────────────────────────
@app.put("/api/onboarding/{task_id}")
async def update_onboarding_task(task_id: str, req: UpdateOnboardingTaskRequest, workspace_id: str = Depends(get_current_workspace_id)):
    update = {"status": req.status}
    if req.status == "completed":
        update["completed_at"] = datetime.utcnow().isoformat()
    
    result = await onboarding_col.update_one(
        {"task_id": task_id, "workspace_id": workspace_id}, {"$set": update}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = await onboarding_col.find_one({"task_id": task_id, "workspace_id": workspace_id})
    if task:
        await log_activity("onboarding", f"Task {req.status}", f"Onboarding task '{task['title']}' marked as {req.status}", task["agent_id"], "agent")
    
    return {"success": True}

# ─── Content Engine ────────────────────────────────────────────────────
@app.get("/api/content")
async def get_content(content_type: Optional[str] = None, workspace_id: str = Depends(get_current_workspace_id)):
    query = {}
    if content_type:
        query["type"] = content_type
    mode_filter = await get_mode_filter(workspace_id)
    items = await content_col.find(merge_query(query, mode_filter)).sort("created_at", -1).to_list(100)
    return [serialize_doc(i) for i in items]

@app.post("/api/content/generate")
async def generate_content(req: ContentGenerateRequest, workspace_id: str = Depends(get_current_workspace_id), user: User = Depends(get_current_user)):
    # Get business profile for context-aware content generation
    content_prompt = await build_content_prompt(workspace_id=workspace_id)
    language = await _workspace_language(workspace_id)

    ai_response = await run_ai_request(
        user_id=user.user_id,
        email=user.email,
        access_token=user.access_token,
        system_prompt=content_prompt,
        user_prompt=req.prompt,
        language=language,
    )
    ai_result = await parse_ai_json(ai_response["text"])
    
    if not ai_result:
        raise HTTPException(status_code=500, detail="AI failed to generate valid content")
    
    items_created = []
    sim_flag = await is_simulation_mode(workspace_id)
    
    if req.type in ["social_post", "both"] and "social_post" in ai_result:
        social_item = {
            "content_id": str(uuid.uuid4()),
            "type": "social_post",
            "title": req.prompt[:80],
            "content": ai_result["social_post"],
            "status": "draft",
            "created_at": now_iso(),
            "created_by": "ai",
            "is_simulation": sim_flag,
            "workspace_id": workspace_id,
        }
        await content_col.insert_one(social_item)
        items_created.append(serialize_doc(social_item))
    
    if req.type in ["email_draft", "both"] and "email_draft" in ai_result:
        email_item = {
            "content_id": str(uuid.uuid4()),
            "type": "email_draft",
            "title": ai_result["email_draft"].get("subject", req.prompt[:80]),
            "content": ai_result["email_draft"],
            "status": "draft",
            "created_at": now_iso(),
            "created_by": "ai",
            "is_simulation": sim_flag,
            "workspace_id": workspace_id,
        }
        await content_col.insert_one(email_item)
        items_created.append(serialize_doc(email_item))
    
    await log_activity("content", "Content generated", f"AI generated {len(items_created)} content item(s)", None, "content")
    
    return {"success": True, "items": items_created}

@app.delete("/api/content/{content_id}")
async def delete_content(content_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    result = await content_col.delete_one({"content_id": content_id, "workspace_id": workspace_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"success": True}

# ─── Activity Feed ─────────────────────────────────────────────────────
@app.get("/api/activity")
async def get_activity(limit: int = Query(default=20, le=100), event_type: Optional[str] = None, workspace_id: str = Depends(get_current_workspace_id)):
    query = {}
    if event_type:
        query["event_type"] = event_type
    mode_filter = await get_mode_filter(workspace_id)
    events = await activity_col.find(merge_query(query, mode_filter)).sort("timestamp", -1).to_list(limit)
    return [serialize_doc(e) for e in events]

# ─── Automation Policies ───────────────────────────────────────────────
@app.get("/api/policies")
async def get_policies(workspace_id: str = Depends(get_current_workspace_id)):
    policies = await policies_col.find({"workspace_id": workspace_id}).to_list(100)
    return [serialize_doc(p) for p in policies]

@app.post("/api/policies")
async def create_policy(req: AutomationPolicyRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    policy = {
        "policy_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "intent": req.intent,
        "action": _normalize_policy_action(req.action),
        "confidence_threshold_high": req.confidence_threshold_high,
        "confidence_threshold_medium": req.confidence_threshold_medium,
        "high_action": _normalize_policy_action(req.high_action),
        "medium_action": _normalize_policy_action(req.medium_action),
        "low_action": _normalize_policy_action(req.low_action),
        "enabled": req.enabled,
        "created_at": now_iso(),
    }
    await policies_col.insert_one(policy)
    await log_activity("system", "Policy created", f"New automation policy for '{req.intent}'", policy["policy_id"], "policy", workspace_id=workspace_id)
    await log_audit("policy.created", f"Created policy for intent '{req.intent}'", workspace_id=workspace_id)
    return serialize_doc(policy)

@app.delete("/api/policies/{policy_id}")
async def delete_policy(policy_id: str, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    result = await policies_col.delete_one({"workspace_id": workspace_id, "policy_id": policy_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await log_audit("policy.deleted", f"Deleted policy {policy_id}", workspace_id=workspace_id)
    return {"success": True}

@app.put("/api/policies/{policy_id}")
async def update_policy(policy_id: str, req: AutomationPolicyRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    update = {
        "intent": req.intent,
        "action": _normalize_policy_action(req.action),
        "confidence_threshold_high": req.confidence_threshold_high,
        "confidence_threshold_medium": req.confidence_threshold_medium,
        "high_action": _normalize_policy_action(req.high_action),
        "medium_action": _normalize_policy_action(req.medium_action),
        "low_action": _normalize_policy_action(req.low_action),
        "enabled": req.enabled,
        "updated_at": now_iso(),
    }
    result = await policies_col.update_one({"workspace_id": workspace_id, "policy_id": policy_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await log_activity("system", "Policy updated", f"Automation policy for '{req.intent}' updated", policy_id, "policy")
    updated = await policies_col.find_one({"workspace_id": workspace_id, "policy_id": policy_id})
    return serialize_doc(updated)

@app.get("/api/policies/evaluate/{inbox_id}")
async def evaluate_policy_for_item(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    """Evaluate what action a policy would take for a given inbox item."""
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item or not item.get("ai_intent"):
        return {"action": "manual_review", "reason": "No AI classification available", "escalation": None}
    
    intent = item["ai_intent"]["intent"]
    confidence = item["ai_intent"]["confidence"]
    
    policy = await policies_col.find_one({"workspace_id": workspace_id, "intent": intent, "enabled": True})
    if not policy:
        return {"action": "manual_review", "reason": f"No policy defined for '{intent}'", "escalation": None}
    
    # Initialize resolved_action
    resolved_action = "manual_review"
    
    # Determine action based on confidence thresholds
    if confidence >= policy.get("confidence_threshold_high", 0.85):
        resolved_action = policy.get("high_action", "auto_run")
    elif confidence >= policy.get("confidence_threshold_medium", 0.6):
        resolved_action = policy.get("medium_action", "require_approval")
    else:
        resolved_action = policy.get("low_action", "escalate")
    resolved_action = _normalize_policy_action(resolved_action)

    # Check escalation rules
    escalation = None
    if resolved_action == "escalate":
        rules = await escalation_col.find({"workspace_id": workspace_id, "enabled": True}).to_list(100)
        for rule in rules:
            if rule["condition_type"] == "intent" and rule["condition_value"] == intent:
                escalation = {"rule": rule["name"], "route_to": rule["route_to"], "priority": rule["priority"]}
                break
            elif rule["condition_type"] == "keyword":
                keywords = [k.strip().lower() for k in rule["condition_value"].split(",")]
                text = f"{item.get('subject', '')} {item.get('body', '')}".lower()
                if any(kw in text for kw in keywords):
                    escalation = {"rule": rule["name"], "route_to": rule["route_to"], "priority": rule["priority"]}
                    break
    
    return {
        "action": resolved_action,
        "reason": f"Policy '{intent}': confidence {confidence:.0%} → {resolved_action}",
        "policy_id": policy["policy_id"],
        "confidence_level": "high" if confidence >= policy.get("confidence_threshold_high", 0.85) else ("medium" if confidence >= policy.get("confidence_threshold_medium", 0.6) else "low"),
        "escalation": escalation,
    }

# ─── Escalation Rules ─────────────────────────────────────────────────
@app.get("/api/escalation-rules")
async def get_escalation_rules(workspace_id: str = Depends(get_current_workspace_id)):
    rules = await escalation_col.find({"workspace_id": workspace_id}).to_list(100)
    return [serialize_doc(r) for r in rules]

@app.post("/api/escalation-rules")
async def create_escalation_rule(req: EscalationRuleRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    rule = {
        "rule_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "name": req.name,
        "condition_type": req.condition_type,
        "condition_value": req.condition_value,
        "route_to": req.route_to,
        "priority": req.priority,
        "enabled": req.enabled,
        "created_at": now_iso(),
    }
    await escalation_col.insert_one(rule)
    await log_activity("system", "Escalation rule created", f"New rule: {req.name} → {req.route_to}", rule["rule_id"], "escalation", workspace_id=workspace_id)
    return serialize_doc(rule)

@app.put("/api/escalation-rules/{rule_id}")
async def update_escalation_rule(rule_id: str, req: EscalationRuleRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    update = {
        "name": req.name,
        "condition_type": req.condition_type,
        "condition_value": req.condition_value,
        "route_to": req.route_to,
        "priority": req.priority,
        "enabled": req.enabled,
        "updated_at": now_iso(),
    }
    result = await escalation_col.update_one({"workspace_id": workspace_id, "rule_id": rule_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    updated = await escalation_col.find_one({"workspace_id": workspace_id, "rule_id": rule_id})
    return serialize_doc(updated)

@app.delete("/api/escalation-rules/{rule_id}")
async def delete_escalation_rule(rule_id: str, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    result = await escalation_col.delete_one({"workspace_id": workspace_id, "rule_id": rule_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True}

# ─── Content Templates ─────────────────────────────────────────────────
@app.get("/api/templates")
async def get_templates(category: Optional[str] = None, workspace_id: str = Depends(get_current_workspace_id)):
    query = {}
    if category:
        query["category"] = category
    q = dict(query)
    q["workspace_id"] = workspace_id
    templates = await templates_col.find(q).sort("created_at", -1).to_list(100)
    return [serialize_doc(t) for t in templates]

@app.get("/api/templates/{template_id}")
async def get_template(template_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    template = await templates_col.find_one({"workspace_id": workspace_id, "template_id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return serialize_doc(template)

@app.post("/api/templates")
async def create_template(req: ContentTemplateRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    template = {
        "template_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "name": req.name,
        "category": req.category,
        "template_type": req.template_type,
        "subject_template": req.subject_template,
        "body_template": req.body_template,
        "variables": req.variables,
        "tags": req.tags,
        "status": "active",
        "created_at": now_iso(),
        "created_by": "user",
    }
    await templates_col.insert_one(template)
    await log_activity("content", "Template created", f"New template: {req.name}", template["template_id"], "template", workspace_id=workspace_id)
    return serialize_doc(template)

@app.put("/api/templates/{template_id}")
async def update_template(template_id: str, req: ContentTemplateRequest, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    update = {
        "name": req.name,
        "category": req.category,
        "template_type": req.template_type,
        "subject_template": req.subject_template,
        "body_template": req.body_template,
        "variables": req.variables,
        "tags": req.tags,
        "updated_at": now_iso(),
    }
    result = await templates_col.update_one({"workspace_id": workspace_id, "template_id": template_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    updated = await templates_col.find_one({"workspace_id": workspace_id, "template_id": template_id})
    return serialize_doc(updated)

@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: str, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("accountant"))):
    result = await templates_col.delete_one({"workspace_id": workspace_id, "template_id": template_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"success": True}

async def build_template_prompt(business_profile=None, workspace_id: str = DEFAULT_WORKSPACE_ID):
    """Build template enhancement prompt with business profile context."""
    if not business_profile:
        profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        business_profile = profile if profile else {"industry": "other"}
    
    industry = business_profile.get("industry", "other")
    language = business_profile.get("language", "es")
    
    industry_context = {
        "real_estate": "a premium real estate firm",
        "healthcare": "a professional healthcare organization",
        "consulting": "a trusted consulting firm",
        "ecommerce": "a modern e-commerce brand",
        "other": "a professional business"
    }.get(industry, "a professional business")
    
    return f"""You are a premium content writer for {industry_context}.
You will be given a template with variables marked as {{{{variable_name}}}} and context values.
Generate polished, professional content by filling in the template with the given context.
Also enhance the language to be engaging and natural while keeping the template structure.
{_lang_directive(language)}

Respond with ONLY valid JSON (no markdown fences):
{{
  "subject": "<filled subject if email, or null>",
  "body": "<filled and polished body text>",
  "enhanced": true
}}

Style: Professional, warm, trustworthy. On-brand for {industry_context}."""

@app.post("/api/templates/{template_id}/generate")
async def generate_from_template(template_id: str, req: GenerateFromTemplateRequest, workspace_id: str = Depends(get_current_workspace_id), user: User = Depends(get_current_user)):
    """Generate AI-enhanced content from a template with context variables."""
    template = await templates_col.find_one({"workspace_id": workspace_id, "template_id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Fill in variables manually first
    body = template["body_template"]
    subject = template.get("subject_template", "") or ""
    for key, value in req.context.items():
        body = body.replace(f"{{{{{key}}}}}", str(value))
        subject = subject.replace(f"{{{{{key}}}}}", str(value))
    
    # Use AI to enhance with business profile context
    template_prompt = await build_template_prompt(workspace_id=workspace_id)
    language = await _workspace_language(workspace_id)

    prompt = f"Template category: {template['category']}\nTemplate name: {template['name']}\n\nSubject (if email): {subject}\n\nBody:\n{body}\n\nContext: {json.dumps(req.context)}\n\nPlease enhance this content while keeping the overall structure and intent."

    ai_response = await run_ai_request(
        user_id=user.user_id,
        email=user.email,
        access_token=user.access_token,
        system_prompt=template_prompt,
        user_prompt=prompt,
        language=language,
    )
    ai_result = await parse_ai_json(ai_response["text"])
    
    if not ai_result:
        # Fallback to manual fill
        ai_result = {"subject": subject, "body": body, "enhanced": False}
    
    # Save as content item
    content_type = "email_draft" if template["template_type"] == "email" else "social_post"
    
    if content_type == "email_draft":
        content_data = {
            "subject": ai_result.get("subject") or subject,
            "body": ai_result.get("body") or body,
            "call_to_action": "Reply to this email",
        }
    else:
        content_data = {
            "text": ai_result.get("body") or body,
            "hashtags": [f"#{tag}" for tag in template.get("tags", [])],
            "platform": "instagram",
        }
    
    content_item = {
        "content_id": str(uuid.uuid4()),
        "type": content_type,
        "title": f"{template['name']} - {req.context.get('contact_name', 'Generated')}",
        "content": content_data,
        "status": "draft",
        "created_at": now_iso(),
        "created_by": "ai_template",
        "template_id": template_id,
    }
    await content_col.insert_one(content_item)
    await log_activity("content", "Content from template", f"Generated '{template['name']}' content", content_item["content_id"], "content")
    
    return {"success": True, "item": serialize_doc(content_item), "enhanced": ai_result.get("enhanced", False)}

# ─── System Status ─────────────────────────────────────────────────────
@app.get("/api/system/status")
async def get_system_status():
    return {
        "overall": "running",
        "services": {
            "gmail_sync": {"status": "running", "last_sync": (datetime.utcnow() - timedelta(minutes=2)).isoformat(), "messages_processed": 6},
            "google_calendar": {"status": "running", "last_sync": (datetime.utcnow() - timedelta(minutes=5)).isoformat(), "events_synced": 5},
            "ghl_crm": {"status": "running", "last_sync": (datetime.utcnow() - timedelta(minutes=1)).isoformat(), "contacts_synced": 6},
            "ai_engine": {"status": "running", "model": "gpt-4o", "requests_today": 12},
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── Business Profile ──────────────────────────────────────────────────
class BusinessProfileUpdate(BaseModel):
    industry: str
    use_case: str = ""
    entity_labels: dict
    simulation_mode: bool = False
    language: Optional[str] = None  # ISO 639-1 code: 'es' | 'en' (extensible)

@app.get("/api/business-profile")
async def get_business_profile(workspace_id: str = Depends(get_current_workspace_id)):
    """Get the current business profile configuration."""
    profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    if not profile:
        # Return default if not found
        return {
            "profile_id": "default",
            "industry": "other",
            "use_case": "",
            "entity_labels": {
                "contacts": "Contacts",
                "team_members": "Team Members",
                "meetings": "Meetings",
                "events": "Events",
                "services": "Services"
            },
            "language": "es",
        }
    return serialize_doc(profile)

@app.put("/api/business-profile")
async def update_business_profile(req: BusinessProfileUpdate, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("leader"))):
    """Update the business profile configuration."""
    # Get current profile to check if we need to generate simulation data
    current_profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    old_simulation_mode = current_profile.get("simulation_mode", False) if current_profile else False
    old_industry = current_profile.get("industry", "other") if current_profile else "other"
    
    update_data = {
        "industry": req.industry,
        "use_case": req.use_case,
        "entity_labels": req.entity_labels,
        "simulation_mode": req.simulation_mode,
        "updated_at": now_iso()
    }
    # Only persist `language` when explicitly provided — allows partial updates
    if req.language and req.language in ("es", "en"):
        update_data["language"] = req.language
    
    await business_profile_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": update_data},
        upsert=True
    )
    
    await log_activity("system", "Business Profile updated", f"Industry: {req.industry}, Simulation: {req.simulation_mode}", workspace_id, "profile")

    # Auto-generate simulation dataset when entering Simulation Mode if:
    #   (a) turning simulation ON and no simulation data exists yet, OR
    #   (b) simulation is ON and industry changed (new-industry sandbox).
    # Switching simulation OFF is *non-destructive*: the sandbox dataset
    # is preserved silently and will reappear the moment the user flips
    # Simulation back ON. This guarantees the promise: mode switching is
    # instant, safe, and never destroys data (real OR simulation).
    if req.simulation_mode:
        need_regenerate = False
        if not old_simulation_mode:
            # Entering Simulation Mode: seed sandbox if it's empty for this industry.
            existing_sim = await inbox_col.count_documents({"is_simulation": True, "workspace_id": workspace_id})
            if existing_sim == 0:
                need_regenerate = True
        elif req.industry != old_industry:
            # Industry changed while in Simulation: regenerate sandbox to match new industry.
            need_regenerate = True

        if need_regenerate:
            await generate_simulation_data(req.industry, workspace_id)
            await log_activity("system", "Simulation data auto-generated", f"Generated {req.industry} data", "simulation", "system")

    updated = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    return serialize_doc(updated)

# ─── Integrations Config ───────────────────────────────────────────────
class IntegrationUpdate(BaseModel):
    status: str
    config: dict = {}

@app.get("/api/integrations")
async def get_integrations(workspace_id: str = Depends(get_current_workspace_id)):
    """Get all integration configurations for the current workspace.

    SECURITY: `config` may hold an encrypted secret field (api_key,
    secret_key, ...) — see integrations/secrets.py. Every secret field
    is redacted to a `has_<field>: bool` flag before it leaves this
    endpoint; the encrypted value itself never reaches the browser.
    """
    integrations = await integrations_config_col.find({"workspace_id": workspace_id}, {"_id": 0}).to_list(100)
    out = []
    for i in integrations:
        doc = serialize_doc(i)
        doc["config"] = integration_secrets.redact_config(doc.get("config"))
        out.append(doc)
    return out

@app.get("/api/integrations/{provider}")
async def get_integration(provider: str, workspace_id: str = Depends(get_current_workspace_id)):
    """Get a specific integration configuration (secrets redacted — see get_integrations())."""
    integration = await integrations_config_col.find_one({"workspace_id": workspace_id, "provider": provider}, {"_id": 0})
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    doc = serialize_doc(integration)
    doc["config"] = integration_secrets.redact_config(doc.get("config"))
    return doc

OAUTH_ONLY_PROVIDERS = {"gmail", "google_calendar"}

@app.put("/api/integrations/{provider}")
async def update_integration(provider: str, req: IntegrationUpdate, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("leader"))):
    """Update an integration configuration.

    SECURITY: `config` is encrypted field-by-field before it's ever
    written to Mongo (integration_secrets.encrypt_config_secrets) — see
    the Phase 0 audit note in integrations/secrets.py's module
    docstring for why this matters (this endpoint used to persist and
    return API keys in plaintext).
    """
    if provider in OAUTH_ONLY_PROVIDERS and req.status == "connected":
        raise HTTPException(
            status_code=400,
            detail=f"'{provider}' requires real Google OAuth. Use GET /api/integrations/google/start instead of manually marking it as connected.",
        )
    # A blank secret field in the request means "leave it unchanged" (the
    # frontend never re-populates a secret input with the real value, so
    # an untouched field arrives here empty) — merge onto the existing
    # encrypted config instead of overwriting it with an empty string.
    existing_doc = await integrations_config_col.find_one({"workspace_id": workspace_id, "provider": provider}, {"_id": 0, "config": 1})
    existing_config = (existing_doc or {}).get("config") or {}
    incoming_config = dict(req.config)
    for secret_field in integration_secrets.SECRET_FIELD_NAMES:
        if secret_field in incoming_config and not incoming_config[secret_field]:
            incoming_config.pop(secret_field)
    merged_config = {**existing_config, **integration_secrets.encrypt_config_secrets(incoming_config)}

    update_data = {
        "status": req.status,
        "config": merged_config,
        "updated_at": now_iso()
    }

    if req.status == "connected":
        update_data["last_sync_at"] = now_iso()

    result = await integrations_config_col.update_one(
        {"workspace_id": workspace_id, "provider": provider},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Integration not found")

    await log_activity("system", f"{provider.title()} integration updated", f"Status: {req.status}", provider, "integration", workspace_id=workspace_id)
    await log_audit(f"integration.{req.status}", f"{provider} -> {req.status}", workspace_id=workspace_id, metadata={"provider": provider})

    updated = await integrations_config_col.find_one({"workspace_id": workspace_id, "provider": provider}, {"_id": 0})
    doc = serialize_doc(updated)
    doc["config"] = integration_secrets.redact_config(doc.get("config"))
    return doc

@app.post("/api/integrations/{provider}/test")
async def test_integration(provider: str, workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("leader"))):
    """Test an integration connection (simulated)."""
    integration = await integrations_config_col.find_one({"workspace_id": workspace_id, "provider": provider}, {"_id": 0})
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Simulate connection test
    if integration.get("status") == "connected":
        return {"success": True, "message": f"{provider.title()} connection is healthy"}
    else:
        return {"success": False, "message": f"{provider.title()} is not connected"}



# ─── Simulation Layer ──────────────────────────────────────────────────────
# Production-quality simulation system for industry validation

async def generate_simulation_data(industry: str, workspace_id: str):
    """Generate realistic operational data for the selected industry.

    CRITICAL: every record AND every clear/count operation here MUST be
    scoped to `workspace_id`. Without this, simulation data from one
    workspace leaks into (and can be wiped from) every other workspace —
    a full breakdown of multi-tenant isolation.
    """
    now = datetime.utcnow()
    
    # Clear existing simulation data — scoped to this workspace only.
    await inbox_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})
    await contacts_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})
    await calendar_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})
    await agents_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})
    await activity_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})
    
    simulation_data = {}
    
    if industry == "real_estate":
        # Real Estate operational data
        contacts = [
            {"contact_id": str(uuid.uuid4()), "name": "Sarah Johnson", "email": "sarah.j@email.com", "phone": "555-0101", "type": "buyer", "status": "active", "lifecycle_stage": "lead", "last_contact": now - timedelta(days=2), "notes": "Looking for 3BR in downtown area", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Michael Chen", "email": "mchen@email.com", "phone": "555-0102", "type": "seller", "status": "active", "lifecycle_stage": "client", "last_contact": now - timedelta(days=1), "notes": "Ready to list 2BR condo", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Emily Rodriguez", "email": "emily.r@email.com", "phone": "555-0103", "type": "buyer", "status": "active", "lifecycle_stage": "hot_lead", "last_contact": now - timedelta(hours=6), "notes": "Interested in viewing 456 Oak Ave", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "David Park", "email": "david.park@email.com", "phone": "555-0104", "type": "investor", "status": "nurturing", "lifecycle_stage": "lead", "last_contact": now - timedelta(days=5), "notes": "Looking for investment properties", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Lisa Thompson", "email": "lisa.t@email.com", "phone": "555-0105", "type": "buyer", "status": "active", "lifecycle_stage": "client", "last_contact": now - timedelta(hours=12), "notes": "First-time homebuyer, pre-approved", "is_simulation": True, "created_at": now},
        ]
        
        inbox_items = [
            {"inbox_id": str(uuid.uuid4()), "from_name": "Emily Rodriguez", "from_email": "emily.r@email.com", "subject": "Property viewing - 456 Oak Ave", "body": "Hi, I'm very interested in viewing the property at 456 Oak Avenue. Would Friday at 3pm work?", "received_at": now - timedelta(hours=2), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "gmail", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Michael Chen", "from_email": "mchen@email.com", "subject": "Ready to list my condo", "body": "I'd like to schedule a time to discuss listing my 2-bedroom condo. What's your availability this week?", "received_at": now - timedelta(hours=5), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "gmail", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Sarah Johnson", "from_email": "sarah.j@email.com", "subject": "Follow-up: Downtown properties", "body": "Thanks for sending those listings! I'd love to see the 3BR on Main Street. Can we schedule a viewing?", "received_at": now - timedelta(hours=8), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "gmail", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "New Lead", "from_email": "buyer.inquiry@web.com", "subject": "Interested in downtown properties", "body": "I'm relocating to the area and interested in 2-3 bedroom properties downtown. Budget around $500k. Can you help?", "received_at": now - timedelta(hours=12), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "website", "is_simulation": True},
        ]
        
        calendar_events = [
            {"event_id": str(uuid.uuid4()), "title": "Property viewing - 456 Oak Ave", "description": "Showing with Emily Rodriguez", "start_time": (now + timedelta(days=2, hours=3)).isoformat(), "end_time": (now + timedelta(days=2, hours=4)).isoformat(), "attendees": ["Emily Rodriguez"], "location": "456 Oak Avenue", "type": "viewing", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Open House - 123 Main St", "description": "Public open house event", "start_time": (now + timedelta(days=3, hours=10)).isoformat(), "end_time": (now + timedelta(days=3, hours=13)).isoformat(), "attendees": [], "location": "123 Main Street", "type": "open_house", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Listing consultation - Michael Chen", "description": "Discuss listing strategy for condo", "start_time": (now + timedelta(days=1, hours=14)).isoformat(), "end_time": (now + timedelta(days=1, hours=15)).isoformat(), "attendees": ["Michael Chen"], "location": "Office", "type": "consultation", "status": "confirmed", "is_simulation": True, "created_at": now},
        ]
        
        agents = [
            {"agent_id": str(uuid.uuid4()), "name": "Jessica Martinez", "email": "jmartinez@agency.com", "phone": "555-0201", "role": "agent", "status": "onboarding", "start_date": (now - timedelta(days=5)).isoformat(), "license_number": "RE-12345", "is_simulation": True, "created_at": now},
            {"agent_id": str(uuid.uuid4()), "name": "Robert Kim", "email": "rkim@agency.com", "phone": "555-0202", "role": "agent", "status": "active", "start_date": (now - timedelta(days=90)).isoformat(), "license_number": "RE-12346", "is_simulation": True, "created_at": now},
        ]
        
        activities = [
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New property inquiry", "description": "Emily Rodriguez interested in viewing", "related_id": None, "related_type": "inbox", "timestamp": now - timedelta(hours=2), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "calendar", "title": "Viewing scheduled", "description": "456 Oak Ave - Friday 3pm", "related_id": None, "related_type": "calendar", "timestamp": now - timedelta(hours=1), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "crm", "title": "Contact updated", "description": "Michael Chen marked as active client", "related_id": None, "related_type": "contact", "timestamp": now - timedelta(hours=5), "is_simulation": True},
        ]
        
        simulation_data = {"contacts": contacts, "inbox": inbox_items, "events": calendar_events, "agents": agents, "activities": activities}
    
    elif industry == "healthcare":
        # Healthcare operational data
        contacts = [
            {"contact_id": str(uuid.uuid4()), "name": "John Miller", "email": "john.m@email.com", "phone": "555-1101", "type": "patient", "status": "active", "lifecycle_stage": "active_patient", "last_contact": now - timedelta(days=1), "notes": "Annual checkup scheduled", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Maria Garcia", "email": "maria.g@email.com", "phone": "555-1102", "type": "patient", "status": "active", "lifecycle_stage": "new_patient", "last_contact": now - timedelta(hours=8), "notes": "New patient intake pending", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Robert Taylor", "email": "rtaylor@email.com", "phone": "555-1103", "type": "patient", "status": "active", "lifecycle_stage": "follow_up", "last_contact": now - timedelta(days=3), "notes": "Post-consultation follow-up needed", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Amanda White", "email": "amanda.w@email.com", "phone": "555-1104", "type": "patient", "status": "active", "lifecycle_stage": "active_patient", "last_contact": now - timedelta(hours=16), "notes": "Referred by Dr. Smith", "is_simulation": True, "created_at": now},
        ]
        
        inbox_items = [
            {"inbox_id": str(uuid.uuid4()), "from_name": "Maria Garcia", "from_email": "maria.g@email.com", "subject": "New patient appointment request", "body": "I'd like to schedule an initial consultation. I'm available Tuesday or Thursday afternoons. Thank you!", "received_at": now - timedelta(hours=3), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "patient_portal", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "John Miller", "from_email": "john.m@email.com", "subject": "Annual checkup confirmation", "body": "Just confirming my annual checkup appointment on Thursday at 10am. Looking forward to it.", "received_at": now - timedelta(hours=6), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Robert Taylor", "from_email": "rtaylor@email.com", "subject": "Follow-up question", "body": "I have a question about the treatment plan we discussed. Can I schedule a quick follow-up call?", "received_at": now - timedelta(hours=10), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
        ]
        
        calendar_events = [
            {"event_id": str(uuid.uuid4()), "title": "Consultation - Maria Garcia", "description": "New patient initial consultation", "start_time": (now + timedelta(days=2, hours=14)).isoformat(), "end_time": (now + timedelta(days=2, hours=15)).isoformat(), "attendees": ["Maria Garcia"], "location": "Exam Room 2", "type": "consultation", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Annual checkup - John Miller", "description": "Annual physical examination", "start_time": (now + timedelta(days=1, hours=10)).isoformat(), "end_time": (now + timedelta(days=1, hours=11)).isoformat(), "attendees": ["John Miller"], "location": "Exam Room 1", "type": "checkup", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Follow-up call - Robert Taylor", "description": "Post-treatment follow-up", "start_time": (now + timedelta(days=3, hours=9)).isoformat(), "end_time": (now + timedelta(days=3, hours=9, minutes=30)).isoformat(), "attendees": ["Robert Taylor"], "location": "Phone", "type": "follow_up", "status": "confirmed", "is_simulation": True, "created_at": now},
        ]
        
        agents = [
            {"agent_id": str(uuid.uuid4()), "name": "Dr. Lisa Wong", "email": "lwong@clinic.com", "phone": "555-1201", "role": "physician", "status": "active", "start_date": (now - timedelta(days=180)).isoformat(), "license_number": "MD-98765", "is_simulation": True, "created_at": now},
            {"agent_id": str(uuid.uuid4()), "name": "Nurse Sarah Davis", "email": "sdavis@clinic.com", "phone": "555-1202", "role": "nurse", "status": "onboarding", "start_date": (now - timedelta(days=7)).isoformat(), "license_number": "RN-45678", "is_simulation": True, "created_at": now},
        ]
        
        activities = [
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New appointment request", "description": "Maria Garcia - new patient", "related_id": None, "related_type": "inbox", "timestamp": now - timedelta(hours=3), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "calendar", "title": "Appointment confirmed", "description": "John Miller - annual checkup", "related_id": None, "related_type": "calendar", "timestamp": now - timedelta(hours=6), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "system", "title": "Intake form reviewed", "description": "New patient intake completed", "related_id": None, "related_type": "patient", "timestamp": now - timedelta(hours=8), "is_simulation": True},
        ]
        
        simulation_data = {"contacts": contacts, "inbox": inbox_items, "events": calendar_events, "agents": agents, "activities": activities}
    
    elif industry == "consulting":
        # Consulting operational data
        contacts = [
            {"contact_id": str(uuid.uuid4()), "name": "TechCorp Inc", "email": "contact@techcorp.com", "phone": "555-2101", "type": "lead", "status": "active", "lifecycle_stage": "qualified_lead", "last_contact": now - timedelta(hours=12), "notes": "Interested in digital transformation consulting", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Innovate Solutions", "email": "team@innovate.com", "phone": "555-2102", "type": "client", "status": "active", "lifecycle_stage": "active_client", "last_contact": now - timedelta(days=2), "notes": "Q2 strategy review scheduled", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "GrowthMax LLC", "email": "hello@growthmax.com", "phone": "555-2103", "type": "lead", "status": "nurturing", "lifecycle_stage": "discovery", "last_contact": now - timedelta(days=5), "notes": "Sent initial proposal, awaiting response", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Retail Dynamics", "email": "info@retaildynamics.com", "phone": "555-2104", "type": "client", "status": "active", "lifecycle_stage": "active_client", "last_contact": now - timedelta(hours=20), "notes": "Mid-project check-in next week", "is_simulation": True, "created_at": now},
        ]
        
        inbox_items = [
            {"inbox_id": str(uuid.uuid4()), "from_name": "TechCorp - Jane Smith", "from_email": "jane@techcorp.com", "subject": "Discovery call request", "body": "We're exploring digital transformation initiatives and would love to schedule a discovery call. Are you available this week?", "received_at": now - timedelta(hours=4), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Innovate Solutions", "from_email": "team@innovate.com", "subject": "Q2 strategy review", "body": "Looking forward to our strategy session next week. Can you send the prep materials beforehand?", "received_at": now - timedelta(hours=8), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "New Inquiry", "from_email": "founder@startup.io", "subject": "Growth strategy consulting", "body": "We're a Series A startup looking for help with growth strategy. Would you be open to an introductory call?", "received_at": now - timedelta(hours=15), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "website", "is_simulation": True},
        ]
        
        calendar_events = [
            {"event_id": str(uuid.uuid4()), "title": "Discovery call - TechCorp", "description": "Initial discovery call with Jane Smith", "start_time": (now + timedelta(days=1, hours=14)).isoformat(), "end_time": (now + timedelta(days=1, hours=15)).isoformat(), "attendees": ["Jane Smith - TechCorp"], "location": "Zoom", "type": "discovery_call", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Strategy review - Innovate Solutions", "description": "Q2 strategy session", "start_time": (now + timedelta(days=4, hours=10)).isoformat(), "end_time": (now + timedelta(days=4, hours=12)).isoformat(), "attendees": ["Innovate Solutions team"], "location": "Office - Conference Room A", "type": "strategy_session", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Check-in - Retail Dynamics", "description": "Mid-project status update", "start_time": (now + timedelta(days=6, hours=15)).isoformat(), "end_time": (now + timedelta(days=6, hours=16)).isoformat(), "attendees": ["Retail Dynamics"], "location": "Zoom", "type": "client_check_in", "status": "confirmed", "is_simulation": True, "created_at": now},
        ]
        
        agents = [
            {"agent_id": str(uuid.uuid4()), "name": "Alex Thompson", "email": "alex.t@consulting.com", "phone": "555-2201", "role": "senior_consultant", "status": "active", "start_date": (now - timedelta(days=365)).isoformat(), "license_number": None, "is_simulation": True, "created_at": now},
            {"agent_id": str(uuid.uuid4()), "name": "Maya Patel", "email": "maya.p@consulting.com", "phone": "555-2202", "role": "consultant", "status": "onboarding", "start_date": (now - timedelta(days=14)).isoformat(), "license_number": None, "is_simulation": True, "created_at": now},
        ]
        
        activities = [
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New lead inquiry", "description": "TechCorp discovery call request", "related_id": None, "related_type": "inbox", "timestamp": now - timedelta(hours=4), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "calendar", "title": "Discovery call scheduled", "description": "TechCorp - Friday 2pm", "related_id": None, "related_type": "calendar", "timestamp": now - timedelta(hours=2), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "crm", "title": "Proposal sent", "description": "GrowthMax LLC - awaiting response", "related_id": None, "related_type": "contact", "timestamp": now - timedelta(days=5), "is_simulation": True},
        ]
        
        simulation_data = {"contacts": contacts, "inbox": inbox_items, "events": calendar_events, "agents": agents, "activities": activities}
    
    elif industry == "ecommerce":
        # E-commerce operational data
        contacts = [
            {"contact_id": str(uuid.uuid4()), "name": "Emma Wilson", "email": "emma.w@email.com", "phone": "555-3101", "type": "customer", "status": "active", "lifecycle_stage": "active_customer", "last_contact": now - timedelta(hours=6), "notes": "VIP customer, recent order #1234", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "James Brown", "email": "jbrown@email.com", "phone": "555-3102", "type": "customer", "status": "active", "lifecycle_stage": "support_pending", "last_contact": now - timedelta(hours=3), "notes": "Refund request for order #1235", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Sophia Lee", "email": "sophia.l@email.com", "phone": "555-3103", "type": "customer", "status": "active", "lifecycle_stage": "active_customer", "last_contact": now - timedelta(days=1), "notes": "Interested in subscription plan", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Oliver Martinez", "email": "oliver.m@email.com", "phone": "555-3104", "type": "customer", "status": "at_risk", "lifecycle_stage": "support_escalation", "last_contact": now - timedelta(hours=12), "notes": "Order delayed, needs immediate attention", "is_simulation": True, "created_at": now},
        ]
        
        inbox_items = [
            {"inbox_id": str(uuid.uuid4()), "from_name": "James Brown", "from_email": "jbrown@email.com", "subject": "Refund request - Order #1235", "body": "I received the wrong item in my order. I'd like to request a refund or exchange. Order #1235.", "received_at": now - timedelta(hours=3), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "support_email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Oliver Martinez", "from_email": "oliver.m@email.com", "subject": "Urgent: Order delay", "body": "My order was supposed to arrive yesterday but tracking shows it's still in transit. This is urgent as it's a gift. Order #1236.", "received_at": now - timedelta(hours=5), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "support_email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Emma Wilson", "from_email": "emma.w@email.com", "subject": "Product inquiry", "body": "Do you have the blue version of SKU-789 in stock? I'd like to order 3 units.", "received_at": now - timedelta(hours=8), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "support_email", "is_simulation": True},
        ]
        
        calendar_events = [
            {"event_id": str(uuid.uuid4()), "title": "Customer call - Oliver Martinez", "description": "Resolve order delay issue", "start_time": (now + timedelta(hours=4)).isoformat(), "end_time": (now + timedelta(hours=4, minutes=30)).isoformat(), "attendees": ["Oliver Martinez"], "location": "Phone", "type": "support_call", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Campaign planning meeting", "description": "Q2 marketing campaign strategy", "start_time": (now + timedelta(days=2, hours=11)).isoformat(), "end_time": (now + timedelta(days=2, hours=12)).isoformat(), "attendees": ["Marketing team"], "location": "Office - Conference Room B", "type": "internal_meeting", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Operations review", "description": "Weekly ops and fulfillment review", "start_time": (now + timedelta(days=1, hours=9)).isoformat(), "end_time": (now + timedelta(days=1, hours=10)).isoformat(), "attendees": ["Ops team"], "location": "Zoom", "type": "ops_review", "status": "confirmed", "is_simulation": True, "created_at": now},
        ]
        
        agents = [
            {"agent_id": str(uuid.uuid4()), "name": "Customer Support - Katie Johnson", "email": "katie.j@support.com", "phone": "555-3201", "role": "support_specialist", "status": "active", "start_date": (now - timedelta(days=120)).isoformat(), "license_number": None, "is_simulation": True, "created_at": now},
            {"agent_id": str(uuid.uuid4()), "name": "Support - Tom Anderson", "email": "tom.a@support.com", "phone": "555-3202", "role": "support_specialist", "status": "onboarding", "start_date": (now - timedelta(days=10)).isoformat(), "license_number": None, "is_simulation": True, "created_at": now},
        ]
        
        activities = [
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "Support ticket received", "description": "James Brown - refund request", "related_id": None, "related_type": "inbox", "timestamp": now - timedelta(hours=3), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "Urgent issue flagged", "description": "Oliver Martinez - order delay escalation", "related_id": None, "related_type": "support", "timestamp": now - timedelta(hours=5), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "crm", "title": "Customer profile updated", "description": "Emma Wilson marked as VIP", "related_id": None, "related_type": "customer", "timestamp": now - timedelta(hours=6), "is_simulation": True},
        ]
        
        simulation_data = {"contacts": contacts, "inbox": inbox_items, "events": calendar_events, "agents": agents, "activities": activities}
    
    else:  # "other" - generic fallback
        # Generic business operational data
        contacts = [
            {"contact_id": str(uuid.uuid4()), "name": "Alex Morgan", "email": "alex.m@email.com", "phone": "555-4101", "type": "contact", "status": "active", "lifecycle_stage": "active", "last_contact": now - timedelta(days=1), "notes": "Regular business contact", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Jordan Smith", "email": "jordan.s@email.com", "phone": "555-4102", "type": "contact", "status": "active", "lifecycle_stage": "new", "last_contact": now - timedelta(hours=10), "notes": "New connection", "is_simulation": True, "created_at": now},
            {"contact_id": str(uuid.uuid4()), "name": "Casey Williams", "email": "casey.w@email.com", "phone": "555-4103", "type": "contact", "status": "nurturing", "lifecycle_stage": "follow_up", "last_contact": now - timedelta(days=3), "notes": "Follow-up needed", "is_simulation": True, "created_at": now},
        ]
        
        inbox_items = [
            {"inbox_id": str(uuid.uuid4()), "from_name": "Jordan Smith", "from_email": "jordan.s@email.com", "subject": "Meeting request", "body": "I'd like to schedule a meeting to discuss potential collaboration. Are you available this week?", "received_at": now - timedelta(hours=4), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
            {"inbox_id": str(uuid.uuid4()), "from_name": "Alex Morgan", "from_email": "alex.m@email.com", "subject": "Follow-up", "body": "Following up on our previous conversation. Let me know if you need any additional information.", "received_at": now - timedelta(hours=8), "read": False, "status": "new", "ai_intent": None, "contact_id": None, "source": "email", "is_simulation": True},
        ]
        
        calendar_events = [
            {"event_id": str(uuid.uuid4()), "title": "Team meeting", "description": "Weekly team sync", "start_time": (now + timedelta(days=1, hours=10)).isoformat(), "end_time": (now + timedelta(days=1, hours=11)).isoformat(), "attendees": ["Team"], "location": "Office", "type": "meeting", "status": "confirmed", "is_simulation": True, "created_at": now},
            {"event_id": str(uuid.uuid4()), "title": "Call - Jordan Smith", "description": "Collaboration discussion", "start_time": (now + timedelta(days=2, hours=14)).isoformat(), "end_time": (now + timedelta(days=2, hours=15)).isoformat(), "attendees": ["Jordan Smith"], "location": "Phone", "type": "call", "status": "confirmed", "is_simulation": True, "created_at": now},
        ]
        
        agents = [
            {"agent_id": str(uuid.uuid4()), "name": "Team Member - Sam Lee", "email": "sam.l@business.com", "phone": "555-4201", "role": "team_member", "status": "active", "start_date": (now - timedelta(days=60)).isoformat(), "license_number": None, "is_simulation": True, "created_at": now},
        ]
        
        activities = [
            {"event_id": str(uuid.uuid4()), "event_type": "inbox", "title": "New request received", "description": "Jordan Smith - meeting request", "related_id": None, "related_type": "inbox", "timestamp": now - timedelta(hours=4), "is_simulation": True},
            {"event_id": str(uuid.uuid4()), "event_type": "calendar", "title": "Meeting scheduled", "description": "Team meeting tomorrow", "related_id": None, "related_type": "calendar", "timestamp": now - timedelta(hours=2), "is_simulation": True},
        ]
        
        simulation_data = {"contacts": contacts, "inbox": inbox_items, "events": calendar_events, "agents": agents, "activities": activities}
    
    # Insert all simulation data into database — stamp workspace_id on
    # every record right before insert so no industry branch above can
    # accidentally omit it.
    for key, col in (
        ("contacts", contacts_col),
        ("inbox", inbox_col),
        ("events", calendar_col),
        ("agents", agents_col),
        ("activities", activity_col),
    ):
        items = simulation_data.get(key)
        if items:
            for item in items:
                item["workspace_id"] = workspace_id
            await col.insert_many(items)
    
    return {
        "success": True,
        "industry": industry,
        "data_generated": {
            "contacts": len(simulation_data.get("contacts", [])),
            "inbox": len(simulation_data.get("inbox", [])),
            "events": len(simulation_data.get("events", [])),
            "agents": len(simulation_data.get("agents", [])),
            "activities": len(simulation_data.get("activities", []))
        }
    }


@app.post("/api/simulation/generate")
async def generate_simulation(workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("leader"))):
    """Generate simulation data for the current industry."""
    profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    if not profile:
        raise HTTPException(status_code=404, detail="Business profile not found")
    
    if not profile.get("simulation_mode", False):
        raise HTTPException(status_code=400, detail="Simulation mode is not enabled")
    
    industry = profile.get("industry", "other")
    result = await generate_simulation_data(industry, workspace_id)
    
    await log_activity("system", "Simulation data generated", f"Generated {industry} operational data", "simulation", "system")
    
    return result


@app.post("/api/simulation/clear")
async def clear_simulation(workspace_id: str = Depends(get_current_workspace_id), _m: dict = Depends(require_role("leader"))):
    """Clear all simulation data — scoped to the current workspace only."""
    deleted_counts = {
        "contacts": (await contacts_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})).deleted_count,
        "inbox": (await inbox_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})).deleted_count,
        "events": (await calendar_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})).deleted_count,
        "agents": (await agents_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})).deleted_count,
        "activities": (await activity_col.delete_many({"is_simulation": True, "workspace_id": workspace_id})).deleted_count,
    }
    
    await log_activity("system", "Simulation data cleared", "All simulation data removed", "simulation", "system")
    
    return {"success": True, "deleted": deleted_counts}


@app.get("/api/simulation/status")
async def simulation_status(workspace_id: str = Depends(get_current_workspace_id)):
    """Get simulation mode status and data counts — scoped to the current workspace only."""
    profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    simulation_mode = profile.get("simulation_mode", False) if profile else False
    
    counts = {
        "contacts": await contacts_col.count_documents({"is_simulation": True, "workspace_id": workspace_id}),
        "inbox": await inbox_col.count_documents({"is_simulation": True, "workspace_id": workspace_id}),
        "events": await calendar_col.count_documents({"is_simulation": True, "workspace_id": workspace_id}),
        "agents": await agents_col.count_documents({"is_simulation": True, "workspace_id": workspace_id}),
        "activities": await activity_col.count_documents({"is_simulation": True, "workspace_id": workspace_id}),
    }
    
    return {
        "simulation_mode": simulation_mode,
        "industry": profile.get("industry", "other") if profile else "other",
        "data_counts": counts,
        "has_data": sum(counts.values()) > 0
    }


# ─── Google OAuth — Gmail + Calendar (Phase 7e) ───────────────────────
import google_oauth as goog


def _google_status_doc(workspace_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Tiny synchronous wrapper to compose a JSON-friendly status. The
    actual DB lookup happens in the route handler so we can stay
    awaitable."""
    return {"workspace_id": workspace_id, "user_id": user_id, "connected": False}


@app.get("/api/integrations/google/status")
async def google_integration_status(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Return whether the active workspace has a usable Google
    connection. The frontend uses this on the inbox/calendar steps to
    decide whether to render `Datos reales` or stay in demo mode.

    Also exposes a granular, secret-free config diagnostic
    (`client_id_configured`, `client_secret_configured`,
    `encryption_key_configured`, `backend_public_url_configured`,
    `redirect_uri_configured`) so an admin can tell exactly which piece
    is missing in a given deployment (preview vs. production commonly
    have different secrets set) — never the actual values."""
    diag = goog.config_status()
    if not goog.is_oauth_configured():
        return {"configured": False, "connected": False, **diag}
    doc = await google_integrations_col.find_one(
        {"workspace_id": workspace_id},
        {"_id": 0, "account_email": 1, "scopes": 1, "connected_at": 1,
         "last_sync_at": 1, "expires_at": 1, "auto_sync_paused": 1, "last_sync_error": 1,
         "connected": 1, "status": 1, "reauthorization_required": 1, "missing_scopes": 1},
    )
    if not doc:
        return {"configured": True, "connected": False, **diag}

    # Older docs (saved before scope verification existed) won't carry
    # these fields — re-derive them from the stored scopes so we never
    # regress an existing connection to "missing" on a code deploy.
    stored_scopes = doc.get("scopes") or []
    if "connected" in doc:
        is_connected = bool(doc.get("connected"))
        missing_scopes = doc.get("missing_scopes") or []
    else:
        missing_scopes = goog.missing_required_scopes(stored_scopes)
        is_connected = not missing_scopes
    status_value = doc.get("status") or ("ok" if is_connected else "permission_missing")
    reauthorization_required = doc.get("reauthorization_required")
    if reauthorization_required is None:
        reauthorization_required = not is_connected

    return {
        "configured": True,
        "connected": is_connected,
        "status": status_value,
        "reauthorization_required": bool(reauthorization_required),
        "missing_scopes": missing_scopes,
        "account_email": doc.get("account_email"),
        "scopes": stored_scopes,
        "connected_at": doc.get("connected_at"),
        "last_sync_at": doc.get("last_sync_at"),
        "auto_sync_paused": bool(doc.get("auto_sync_paused")),
        "last_sync_error": doc.get("last_sync_error"),
        **diag,
    }


@app.get("/api/integrations/google/start")
async def google_oauth_start(
    request: Request,
    return_to: Optional[str] = None,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Kick off the Authorization Code Flow.

    The frontend hits this with a Bearer token (so we know the
    workspace+user) and then sends the user's browser to ``auth_url``.
    We persist a short-lived state document tying the random ``state``
    to the user, so the callback can verify nothing was tampered with.
    """
    if not goog.is_oauth_configured():
        cfg = goog.config_status()
        missing = [
            name.replace("_configured", "")
            for name, ok in cfg.items()
            if name.endswith("_configured") and not ok and name in (
                "client_id_configured", "client_secret_configured", "encryption_key_configured",
            )
        ]
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth is not configured. Missing: "
                + (", ".join(missing) or "unknown")
                + ". Set the corresponding env var(s) in this deployment's secrets."
            ),
        )

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = goog.resolve_redirect_uri(base_url)
    state = uuid.uuid4().hex

    await google_oauth_state_col.insert_one(
        {
            "state": state,
            "user_id": user.user_id,
            "workspace_id": workspace_id,
            "return_to": _sanitize_return_to(return_to),
            "redirect_uri": redirect_uri,
            "created_at": datetime.now(timezone.utc),
            # State documents auto-expire after 10 min via TTL index
            # configured at startup (see google_oauth_state_col below).
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
    )

    auth_url = goog.build_authorization_url(state=state, redirect_uri=redirect_uri)
    return {"auth_url": auth_url, "state": state}


def _frontend_base_url() -> str:
    """Canonical frontend origin OAuth callbacks bounce the browser back
    to. This is the ONLY source of truth — do not add fallbacks here.

    SECURITY: this used to trust the incoming request's Origin/Referer
    headers, and fell back to REACT_APP_BACKEND_URL (the backend's own
    domain) if those were absent. Both are wrong:
      - Origin/Referer are fully attacker-controlled request headers —
        trusting them to build a redirect target is a textbook open
        redirect vulnerability (an attacker crafts a link that starts
        the OAuth dance with a forged Referer, and the victim's browser
        gets bounced to the attacker's domain with the auth result in
        the query string).
      - REACT_APP_BACKEND_URL is the backend's public URL, not the
        frontend's; using it as a "frontend fallback" silently redirects
        the user to the wrong app.

    FRONTEND_PUBLIC_URL must be set explicitly in every environment
    (preview and production). If it's missing, callers must fail closed
    (see the 500 response in the OAuth callbacks below) instead of
    guessing a domain.
    """
    return (os.environ.get("FRONTEND_PUBLIC_URL") or "").strip().rstrip("/")


# Only these paths may be used as the OAuth "return_to" destination.
# Keeps /start + the callback from ever building a redirect to an
# arbitrary attacker-supplied path (open redirect via ?return_to=).
ALLOWED_OAUTH_RETURN_PATHS = {"/welcome/inbox", "/welcome/calendar"}
DEFAULT_OAUTH_RETURN_PATH = "/welcome/inbox"


def _sanitize_return_to(value: Optional[str]) -> str:
    return value if value in ALLOWED_OAUTH_RETURN_PATHS else DEFAULT_OAUTH_RETURN_PATH


# Google (and Microsoft) can pass arbitrary strings through ?error= on
# the callback. Only forward the handful of well-known OAuth error codes
# to the frontend verbatim; anything else collapses to a generic code so
# we never reflect unsanitized provider input straight into a redirect URL.
_KNOWN_OAUTH_ERROR_CODES = {
    "access_denied", "invalid_scope", "server_error", "temporarily_unavailable",
    "invalid_request", "unauthorized_client", "consent_required",
}


def _safe_oauth_error_code(raw: Optional[str]) -> str:
    code = (raw or "").strip().lower()
    return code if code in _KNOWN_OAUTH_ERROR_CODES else "oauth_error"


@app.get("/api/integrations/google/callback")
async def google_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Google's redirect.

    On success we persist encrypted tokens + the user's Google email,
    then redirect the browser back to the frontend with
    ``?google_connected=success&account=<email>``. On any failure we
    redirect with ``?google_connected=error&reason=<short>`` so the UI
    can keep the user in demo mode without throwing.
    """
    fe = _frontend_base_url()
    if not fe:
        # Fail closed: never guess the frontend domain from client-controlled
        # headers. A misconfigured FRONTEND_PUBLIC_URL must be loud, not a
        # silent open redirect.
        print("[google_oauth_callback] FRONTEND_PUBLIC_URL is not set — cannot bounce back safely.")
        return PlainTextResponse(
            "OAuth misconfiguration: FRONTEND_PUBLIC_URL is not set on the backend. "
            "Contact the workspace administrator.",
            status_code=500,
        )
    base_redirect = fe
    return_path = DEFAULT_OAUTH_RETURN_PATH  # updated once we trust state_doc below

    def _bounce(qs: str) -> RedirectResponse:
        target = base_redirect + return_path + ("?" + qs if qs else "")
        return RedirectResponse(url=target, status_code=303)

    if error:
        return _bounce(f"google_connected=error&reason={_safe_oauth_error_code(error)}")
    if not code or not state:
        return _bounce("google_connected=error&reason=missing_code_or_state")

    state_doc = await google_oauth_state_col.find_one_and_delete({"state": state})
    if not state_doc:
        return _bounce("google_connected=error&reason=invalid_state")

    expires = state_doc.get("expires_at")
    if isinstance(expires, datetime) and expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return _bounce("google_connected=error&reason=state_expired")

    redirect_uri = state_doc.get("redirect_uri") or goog.resolve_redirect_uri(str(request.base_url))
    workspace_id = state_doc.get("workspace_id")
    user_id = state_doc.get("user_id")
    return_to = _sanitize_return_to(state_doc.get("return_to"))
    return_path = return_to  # now safe to use the real destination

    try:
        creds, profile = goog.exchange_code_for_tokens(code, redirect_uri)
    except Exception as exc:  # noqa: BLE001
        # Log the real exception server-side only — never put exception
        # text in a URL the browser will carry around (it can leak into
        # browser history, proxy logs, referrer headers of whatever page
        # loads next, etc.).
        print(f"[google_oauth_callback] token exchange failed for workspace={workspace_id}: {exc}")
        return _bounce("google_connected=error&reason=exchange_failed")

    expires_at = creds.expiry
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # Google only grants what the user actually approved on the consent
    # screen — if they unchecked a permission, ``creds.scopes`` will be
    # missing it even though we requested it. Compare against what we
    # require so we never mark a partial grant as fully connected.
    granted_scopes = list(creds.scopes or [])
    missing_scopes = goog.missing_required_scopes(granted_scopes)
    is_connected = not missing_scopes
    integration_status = "ok" if is_connected else "permission_missing"
    reauthorization_required = not is_connected

    # Google does not always return a fresh refresh_token on every grant
    # (e.g. some reconnect edge cases even with prompt=consent). Never let
    # a missing new token overwrite a previously valid encrypted one.
    existing_doc = await google_integrations_col.find_one(
        {"workspace_id": workspace_id}, {"_id": 0, "refresh_token": 1}
    )
    new_refresh_token = goog.encrypt_token(creds.refresh_token)
    refresh_token_to_store = new_refresh_token or (existing_doc or {}).get("refresh_token")

    await google_integrations_col.update_one(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "access_token": goog.encrypt_token(creds.token),
                "refresh_token": refresh_token_to_store,
                "expires_at": expires_at,
                "scopes": granted_scopes or goog.GOOGLE_SCOPES,
                "connected": is_connected,
                "status": integration_status,
                "reauthorization_required": reauthorization_required,
                "missing_scopes": missing_scopes,
                "account_email": (profile or {}).get("email"),
                "account_name": (profile or {}).get("name"),
                "google_user_id": (profile or {}).get("google_user_id"),
                "connected_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    try:
        await log_audit(
            "integration.google_connected",
            f"Google account connected ({(profile or {}).get('email') or 'unknown'})"
            if is_connected
            else f"Google account connected with missing scopes ({(profile or {}).get('email') or 'unknown'})",
            user_id=user_id,
            workspace_id=workspace_id,
            metadata={"scopes": granted_scopes[:8], "missing_scopes": missing_scopes},
        )
    except Exception:  # noqa: BLE001
        pass

    if not is_connected:
        qs = (
            f"google_connected=permission_missing&account={(profile or {}).get('email') or ''}"
            f"&missing_scopes={','.join(missing_scopes)}&return_to={return_to}"
        )
    else:
        qs = f"google_connected=success&account={(profile or {}).get('email') or ''}&return_to={return_to}"
    return _bounce(qs)


async def _load_google_credentials(workspace_id: str):
    """Decrypt + auto-refresh credentials for a workspace, persisting
    rotated tokens. Returns ``(creds, integration_doc)`` or
    ``(None, None)`` if the workspace isn't connected."""
    doc = await google_integrations_col.find_one({"workspace_id": workspace_id})
    if not doc:
        return None, None
    access_token = goog.decrypt_token(doc.get("access_token"))
    refresh_token = goog.decrypt_token(doc.get("refresh_token"))
    if not access_token:
        return None, None
    creds = goog.credentials_from_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=doc.get("expires_at"),
        scopes=doc.get("scopes"),
    )
    if goog.maybe_refresh(creds):
        # Persist the rotated access token + new expiry. Refresh tokens
        # rarely change but we still re-encrypt to be safe.
        new_expiry = creds.expiry
        if isinstance(new_expiry, datetime) and new_expiry.tzinfo is None:
            new_expiry = new_expiry.replace(tzinfo=timezone.utc)
        await google_integrations_col.update_one(
            {"workspace_id": workspace_id},
            {
                "$set": {
                    "access_token": goog.encrypt_token(creds.token),
                    "refresh_token": goog.encrypt_token(creds.refresh_token) or doc.get("refresh_token"),
                    "expires_at": new_expiry,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
    return creds, doc


@app.post("/api/integrations/google/sync")
async def google_oauth_sync(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Pull last 50 Gmail messages + next 30 days of Calendar events.

    We persist the rows alongside the simulation seed so existing
    inbox/calendar UIs work unmodified — but tag them ``is_real=True``
    so the rest of the app can hide simulation rows once real data
    lands."""
    creds, doc = await _load_google_credentials(workspace_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google not connected for this workspace")
    if doc and doc.get("reauthorization_required"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_missing",
                "reauthorization_required": True,
                "missing_scopes": doc.get("missing_scopes") or [],
            },
        )

    counts = {"emails": 0, "events": 0}

    try:
        emails = goog.fetch_recent_gmail(creds, limit=50)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Gmail fetch failed: {exc}") from exc

    now = datetime.now(timezone.utc)
    for m in emails:
        # Idempotent upsert keyed by gmail_id so repeat syncs don't
        # duplicate inbox rows.
        await inbox_col.update_one(
            {"workspace_id": workspace_id, "gmail_id": m["gmail_id"]},
            {
                "$set": {
                    "workspace_id": workspace_id,
                    "source": "gmail",
                    "gmail_id": m["gmail_id"],
                    "thread_id": m["thread_id"],
                    "from_name": m["from_name"],
                    "from_address": m["from_address"],
                    "subject": m["subject"],
                    "preview": m["snippet"],
                    "received_at": m["date_iso"],
                    "label_ids": m["label_ids"],
                    "is_real": True,
                    "is_simulation": False,
                    "synced_at": now,
                },
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "status": "new",
                    "priority": "medium",
                    "created_at": now,
                },
            },
            upsert=True,
        )
        counts["emails"] += 1

    try:
        events = goog.fetch_upcoming_calendar(creds, days=30)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Calendar fetch failed: {exc}") from exc

    for ev in events:
        await calendar_col.update_one(
            {"workspace_id": workspace_id, "gcal_id": ev["gcal_id"]},
            {
                "$set": {
                    "workspace_id": workspace_id,
                    "source": "google_calendar",
                    "gcal_id": ev["gcal_id"],
                    "title": ev["title"],
                    "description": ev["description"],
                    "location": ev["location"],
                    "start": ev["start_iso"],
                    "end": ev["end_iso"],
                    "attendees": ev["attendees"],
                    "html_link": ev["html_link"],
                    "status": ev["status"],
                    "is_real": True,
                    "is_simulation": False,
                    "synced_at": now,
                },
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "created_at": now,
                },
            },
            upsert=True,
        )
        counts["events"] += 1

    # Once we have real data, retire the demo seed for this workspace so
    # the UI never mixes the two. We mark them rather than deleting in
    # case the user wants to disconnect and roll back.
    await inbox_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$set": {"hidden_by_real": True}},
    )
    await calendar_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$set": {"hidden_by_real": True}},
    )

    # Flip simulation_mode off — we have real data now.
    await business_profile_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"simulation_mode": False, "updated_at": now_iso()}},
        upsert=True,
    )

    await google_integrations_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"last_sync_at": now}},
    )
    try:
        await log_audit(
            "integration.google_synced",
            f"Synced Google data ({counts['emails']} emails, {counts['events']} events)",
            user_id=user.user_id,
            workspace_id=workspace_id,
            metadata=counts,
        )
    except Exception:  # noqa: BLE001
        pass

    return {"success": True, "counts": counts, "synced_at": now.isoformat()}


async def _disconnect_google_workspace(workspace_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Revoke tokens at Google + delete locally + restore demo seed.

    Disconnecting un-hides the simulation rows so the workspace doesn't
    end up with an empty inbox/calendar, and re-enables simulation_mode
    so the UI returns to demo state cleanly.

    Extracted so both the legacy DELETE /api/integrations/google/disconnect
    route and the Quantro Connect GoogleAdapter call the exact same
    implementation — see integrations/providers/google.py.
    """
    doc = await google_integrations_col.find_one({"workspace_id": workspace_id})
    if not doc:
        return {"success": True, "already": "disconnected"}

    refresh = goog.decrypt_token(doc.get("refresh_token"))
    access = goog.decrypt_token(doc.get("access_token"))
    if refresh:
        goog.revoke_token(refresh)
    elif access:
        goog.revoke_token(access)

    await google_integrations_col.delete_one({"workspace_id": workspace_id})

    # Wipe any rows we synced from Google so the user doesn't see stale
    # data after disconnecting.
    await inbox_col.delete_many({"workspace_id": workspace_id, "is_real": True, "source": "gmail"})
    await calendar_col.delete_many({"workspace_id": workspace_id, "is_real": True, "source": "google_calendar"})

    # Bring the demo seed back online.
    await inbox_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$unset": {"hidden_by_real": ""}},
    )
    await calendar_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$unset": {"hidden_by_real": ""}},
    )
    await business_profile_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"simulation_mode": True, "updated_at": now_iso()}},
        upsert=True,
    )

    try:
        await log_audit(
            "integration.google_disconnected",
            f"Google disconnected ({(doc or {}).get('account_email') or 'unknown'})",
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except Exception:  # noqa: BLE001
        pass

    return {"success": True}


@app.delete("/api/integrations/google/disconnect")
async def google_oauth_disconnect(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    return await _disconnect_google_workspace(workspace_id, user.user_id)


# ─── Microsoft Outlook OAuth — Mail + Calendar (Phase 7e.2) ───────────
import microsoft_oauth as msoa


@app.get("/api/integrations/microsoft/status")
async def microsoft_integration_status(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    if not msoa.is_oauth_configured():
        return {"configured": False, "connected": False}
    doc = await microsoft_integrations_col.find_one(
        {"workspace_id": workspace_id},
        {"_id": 0, "account_email": 1, "scopes": 1, "connected_at": 1,
         "last_sync_at": 1, "auto_sync_paused": 1, "last_sync_error": 1},
    )
    if not doc:
        return {"configured": True, "connected": False}
    return {
        "configured": True,
        "connected": True,
        "account_email": doc.get("account_email"),
        "scopes": doc.get("scopes") or [],
        "connected_at": doc.get("connected_at"),
        "last_sync_at": doc.get("last_sync_at"),
        "auto_sync_paused": bool(doc.get("auto_sync_paused")),
        "last_sync_error": doc.get("last_sync_error"),
    }


@app.get("/api/integrations/microsoft/start")
async def microsoft_oauth_start(
    request: Request,
    return_to: Optional[str] = None,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    if not msoa.is_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Microsoft OAuth is not configured. Set MS_CLIENT_ID + MS_CLIENT_SECRET in backend/.env.",
        )
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = msoa.resolve_redirect_uri(base_url)
    state = uuid.uuid4().hex
    await microsoft_oauth_state_col.insert_one(
        {
            "state": state, "user_id": user.user_id, "workspace_id": workspace_id,
            "return_to": return_to or "/welcome/inbox", "redirect_uri": redirect_uri,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
    )
    auth_url = msoa.build_authorization_url(state=state, redirect_uri=redirect_uri)
    return {"auth_url": auth_url, "state": state}


@app.get("/api/integrations/microsoft/callback")
async def microsoft_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    # NOTE: Microsoft OAuth business logic (scopes, tokens, return_to
    # handling) is intentionally left untouched per this task's scope —
    # only the frontend URL resolution is swapped to the safe helper
    # since the old `_frontend_url_from` (Origin/Referer trust) no
    # longer exists.
    fe = _frontend_base_url() or ""
    base_redirect = (fe or "").rstrip("/")

    def _bounce(qs: str) -> RedirectResponse:
        target = (base_redirect or "") + "/welcome/inbox" + ("?" + qs if qs else "")
        return RedirectResponse(url=target, status_code=303)

    if error:
        return _bounce(f"microsoft_connected=error&reason={error}")
    if not code or not state:
        return _bounce("microsoft_connected=error&reason=missing_code_or_state")

    state_doc = await microsoft_oauth_state_col.find_one_and_delete({"state": state})
    if not state_doc:
        return _bounce("microsoft_connected=error&reason=invalid_state")
    expires = state_doc.get("expires_at")
    if isinstance(expires, datetime) and expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return _bounce("microsoft_connected=error&reason=state_expired")

    redirect_uri = state_doc.get("redirect_uri") or msoa.resolve_redirect_uri(str(request.base_url))
    workspace_id = state_doc.get("workspace_id")
    user_id = state_doc.get("user_id")
    return_to = state_doc.get("return_to") or "/welcome/inbox"

    try:
        token_payload, profile = msoa.exchange_code_for_tokens(code, redirect_uri)
    except Exception as exc:  # noqa: BLE001
        return _bounce(f"microsoft_connected=error&reason=exchange_failed&detail={str(exc)[:80]}")

    expires_in = int(token_payload.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    granted_scopes = (token_payload.get("scope") or "").split()

    await microsoft_integrations_col.update_one(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "workspace_id": workspace_id, "user_id": user_id,
                "access_token": msoa.encrypt_token(token_payload.get("access_token")),
                "refresh_token": msoa.encrypt_token(token_payload.get("refresh_token")),
                "expires_at": expires_at,
                "scopes": granted_scopes or msoa.MS_SCOPES,
                "account_email": (profile or {}).get("email"),
                "account_name": (profile or {}).get("name"),
                "ms_user_id": (profile or {}).get("ms_user_id"),
                "connected_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    try:
        await log_audit(
            "integration.microsoft_connected",
            f"Microsoft account connected ({(profile or {}).get('email') or 'unknown'})",
            user_id=user_id, workspace_id=workspace_id,
            metadata={"scopes": granted_scopes[:8]},
        )
    except Exception:  # noqa: BLE001
        pass

    qs = f"microsoft_connected=success&account={(profile or {}).get('email') or ''}&return_to={return_to}"
    return _bounce(qs)


async def _load_microsoft_credentials(workspace_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Decrypt + auto-refresh the Microsoft access token. Returns
    ``(access_token_plain, doc)`` or ``(None, None)`` if not connected
    or unrecoverable."""
    doc = await microsoft_integrations_col.find_one({"workspace_id": workspace_id})
    if not doc:
        return None, None
    access_plain = msoa.decrypt_token(doc.get("access_token"))
    refresh_plain = msoa.decrypt_token(doc.get("refresh_token"))
    if not access_plain:
        return None, None
    expires_at = doc.get("expires_at")
    needs_refresh = False
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        needs_refresh = datetime.now(timezone.utc) >= expires_at - timedelta(seconds=60)
    if needs_refresh and refresh_plain:
        try:
            fresh = msoa.refresh_access_token(refresh_plain)
            access_plain = fresh.get("access_token") or access_plain
            new_refresh = fresh.get("refresh_token") or refresh_plain
            new_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(fresh.get("expires_in") or 3600))
            await microsoft_integrations_col.update_one(
                {"workspace_id": workspace_id},
                {"$set": {
                    "access_token": msoa.encrypt_token(access_plain),
                    "refresh_token": msoa.encrypt_token(new_refresh),
                    "expires_at": new_expiry,
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
        except Exception:  # noqa: BLE001
            return None, doc
    return access_plain, doc


async def _perform_microsoft_sync_for_workspace(workspace_id: str) -> Dict[str, Any]:
    access, doc = await _load_microsoft_credentials(workspace_id)
    if not access or not doc:
        return {"workspace_id": workspace_id, "skipped": "not_connected"}
    if doc.get("auto_sync_paused"):
        return {"workspace_id": workspace_id, "skipped": "paused"}

    counts = {"emails": 0, "events": 0}
    now = datetime.now(timezone.utc)
    try:
        emails = msoa.fetch_recent_outlook(access, limit=50)
        for m in emails:
            await inbox_col.update_one(
                {"workspace_id": workspace_id, "ms_id": m["ms_id"]},
                {
                    "$set": {
                        "workspace_id": workspace_id, "source": "outlook",
                        "ms_id": m["ms_id"], "thread_id": m["thread_id"],
                        "from_name": m["from_name"], "from_address": m["from_address"],
                        "subject": m["subject"], "preview": m["snippet"],
                        "received_at": m["date_iso"], "categories": m["categories"],
                        "is_real": True, "is_simulation": False, "synced_at": now,
                    },
                    "$setOnInsert": {"id": str(uuid.uuid4()), "status": "new", "priority": "medium", "created_at": now},
                },
                upsert=True,
            )
            counts["emails"] += 1
        events = msoa.fetch_upcoming_outlook_events(access, days=30)
        for ev in events:
            await calendar_col.update_one(
                {"workspace_id": workspace_id, "ms_id": ev["ms_id"]},
                {
                    "$set": {
                        "workspace_id": workspace_id, "source": "outlook_calendar",
                        "ms_id": ev["ms_id"], "title": ev["title"],
                        "description": ev["description"], "location": ev["location"],
                        "start": ev["start_iso"], "end": ev["end_iso"],
                        "attendees": ev["attendees"], "html_link": ev["html_link"],
                        "status": ev["status"], "is_real": True, "is_simulation": False, "synced_at": now,
                    },
                    "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now},
                },
                upsert=True,
            )
            counts["events"] += 1
        await microsoft_integrations_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"last_sync_at": now, "last_sync_error": None}},
        )
        return {"workspace_id": workspace_id, "ok": True, "counts": counts}
    except Exception as exc:  # noqa: BLE001
        await microsoft_integrations_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"last_sync_error": str(exc)[:200], "last_sync_attempt_at": now}},
        )
        return {"workspace_id": workspace_id, "error": str(exc)[:200]}


@app.post("/api/integrations/microsoft/sync")
async def microsoft_oauth_sync(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    res = await _perform_microsoft_sync_for_workspace(workspace_id)
    if res.get("skipped") == "not_connected":
        raise HTTPException(status_code=400, detail="Microsoft not connected")
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])

    # First successful sync: hide simulation seed and flip mode off,
    # mirroring the Google branch.
    await inbox_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$set": {"hidden_by_real": True}},
    )
    await calendar_col.update_many(
        {"workspace_id": workspace_id, "is_simulation": True},
        {"$set": {"hidden_by_real": True}},
    )
    await business_profile_col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"simulation_mode": False, "updated_at": now_iso()}},
        upsert=True,
    )
    try:
        await log_audit(
            "integration.microsoft_synced",
            f"Synced Microsoft data ({res['counts']['emails']} emails, {res['counts']['events']} events)",
            user_id=user.user_id, workspace_id=workspace_id, metadata=res["counts"],
        )
    except Exception:  # noqa: BLE001
        pass
    return {"success": True, "counts": res["counts"], "synced_at": datetime.now(timezone.utc).isoformat()}


async def _disconnect_microsoft_workspace(workspace_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Same extraction rationale as _disconnect_google_workspace() —
    shared by the legacy route and integrations/providers/microsoft.py."""
    doc = await microsoft_integrations_col.find_one({"workspace_id": workspace_id})
    if not doc:
        return {"success": True, "already": "disconnected"}

    refresh = msoa.decrypt_token(doc.get("refresh_token"))
    access = msoa.decrypt_token(doc.get("access_token"))
    if refresh:
        msoa.revoke_token(refresh)
    elif access:
        msoa.revoke_token(access)

    await microsoft_integrations_col.delete_one({"workspace_id": workspace_id})
    await inbox_col.delete_many({"workspace_id": workspace_id, "is_real": True, "source": "outlook"})
    await calendar_col.delete_many({"workspace_id": workspace_id, "is_real": True, "source": "outlook_calendar"})

    # Only restore demo mode if there's no other real integration
    # (e.g. Google) keeping this workspace in real-data territory.
    other_real = await google_integrations_col.find_one({"workspace_id": workspace_id})
    if not other_real:
        await inbox_col.update_many(
            {"workspace_id": workspace_id, "is_simulation": True},
            {"$unset": {"hidden_by_real": ""}},
        )
        await calendar_col.update_many(
            {"workspace_id": workspace_id, "is_simulation": True},
            {"$unset": {"hidden_by_real": ""}},
        )
        await business_profile_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": {"simulation_mode": True, "updated_at": now_iso()}},
            upsert=True,
        )

    try:
        await log_audit(
            "integration.microsoft_disconnected",
            f"Microsoft disconnected ({(doc or {}).get('account_email') or 'unknown'})",
            user_id=user_id, workspace_id=workspace_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"success": True}


@app.delete("/api/integrations/microsoft/disconnect")
async def microsoft_oauth_disconnect(
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    return await _disconnect_microsoft_workspace(workspace_id, user.user_id)


# ─── Auto-sync controls (Phase 7e) ────────────────────────────────────
class AutoSyncToggleRequest(BaseModel):
    paused: bool


def _provider_collection(provider: str):
    """Map a provider slug to its mongo integration collection. Keeps
    the toggle endpoint generic so we add new providers in one line."""
    if provider == "google":
        return google_integrations_col
    if provider == "microsoft":
        return microsoft_integrations_col
    raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")


@app.post("/api/integrations/{provider}/auto-sync")
async def toggle_auto_sync(
    provider: str,
    req: AutoSyncToggleRequest,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Pause or resume the periodic sync for a connected integration.

    Pausing keeps the OAuth tokens intact but tells the scheduler to
    skip this workspace on its next tick. Resuming flips the flag back
    AND triggers an immediate sync so the user gets fresh data without
    having to wait up to 15 min for the next cycle.
    """
    col = _provider_collection(provider)
    doc = await col.find_one({"workspace_id": workspace_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{provider} not connected")

    await col.update_one(
        {"workspace_id": workspace_id},
        {"$set": {"auto_sync_paused": req.paused, "updated_at": datetime.now(timezone.utc)}},
    )
    try:
        await log_audit(
            f"integration.{provider}_auto_sync_{'paused' if req.paused else 'resumed'}",
            f"Auto-sync {'paused' if req.paused else 'resumed'} for {provider}",
            user_id=user.user_id,
            workspace_id=workspace_id,
        )
    except Exception:  # noqa: BLE001
        pass

    # If we're resuming, kick off a fresh sync right now so the user
    # gets their inbox up-to-date without waiting up to 15 minutes.
    if not req.paused:
        if provider == "google":
            asyncio.create_task(_perform_google_sync_for_workspace(workspace_id))
        elif provider == "microsoft":
            ms_sync = globals().get("_perform_microsoft_sync_for_workspace")
            if ms_sync is not None:
                asyncio.create_task(ms_sync(workspace_id))

    return {"success": True, "paused": req.paused}


# ─── Welcome onboarding (Phase 7d) ────────────────────────────────────
class WelcomeCompleteRequest(BaseModel):
    industry: Optional[str] = "other"
    start_choice: Optional[str] = None  # 'email' | 'tools' | 'explore'
    inbox_connected: bool = False
    calendar_connected: bool = False
    crm_connected: bool = False
    automations_connected: bool = False


@app.post("/api/onboarding/welcome/complete")
async def complete_welcome_onboarding(
    req: WelcomeCompleteRequest,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Activate the workspace at the end of the Welcome flow.

    What happens here:
      1. Persist the chosen industry and flip ``simulation_mode=True`` on
         the business profile so the rest of the app surfaces the demo
         dataset right away.
      2. Generate the simulation seed if it doesn't exist yet (so the
         counters returned below are real, not fake).
      3. Return high-level counters tailored to the Activación screen
         copy (conversations, opportunities, contacts, events).

    Auth: any authenticated user. We deliberately don't gate this on
    ``leader+`` because the welcome flow runs *before* role assignment
    on a brand-new tenant — the user is implicitly the owner of their
    own workspace at this point.
    """
    industry = (req.industry or "other").strip().lower() or "other"

    # 1) Update business profile (upsert, mirror what Settings does).
    now = now_iso()
    await business_profile_col.update_one(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "industry": industry,
                "simulation_mode": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "workspace_id": workspace_id,
                "use_case": "general",
                "created_at": now,
            },
        },
        upsert=True,
    )

    # 2) Seed the simulation dataset if empty. ``generate_simulation_data``
    #    is idempotent-ish — it short-circuits when seed rows already
    #    carry the same workspace_id + industry combo, so re-running this
    #    endpoint never duplicates data.
    try:
        existing = await contacts_col.count_documents(
            {"is_simulation": True, "workspace_id": workspace_id}
        )
        if existing == 0:
            try:
                await generate_simulation_data(industry, workspace_id)
            except Exception:  # noqa: BLE001
                # Seeding is best-effort — even with zero seeded rows the
                # rest of the activation screen still works (counters
                # just show 0). We never block onboarding on this.
                pass
    except Exception:  # noqa: BLE001
        pass

    # 3) Compute Activación counters. We map our internal collections to
    #    the user-facing labels in the brief: "conversaciones" = inbox
    #    items, "oportunidades" = inbox items flagged as opportunity OR
    #    high-priority, "contactos" = CRM contacts, "eventos" = upcoming
    #    calendar events.
    inbox_total = await inbox_col.count_documents(
        {"workspace_id": workspace_id, "is_simulation": True}
    )
    try:
        opportunities = await inbox_col.count_documents({
            "workspace_id": workspace_id,
            "is_simulation": True,
            "$or": [
                {"category": {"$in": ["opportunity", "lead", "sales"]}},
                {"priority": {"$in": ["high", "urgent"]}},
            ],
        })
    except Exception:  # noqa: BLE001
        opportunities = 0
    contacts_total = await contacts_col.count_documents(
        {"workspace_id": workspace_id, "is_simulation": True}
    )
    events_total = await calendar_col.count_documents(
        {"workspace_id": workspace_id, "is_simulation": True}
    )

    # Audit trail — owner-level event so the activation moment is
    # auditable end-to-end.
    try:
        await log_audit(
            "onboarding.welcome_completed",
            f"Welcome flow completed (start={req.start_choice}, industry={industry})",
            user_id=user.user_id,
            workspace_id=workspace_id,
            metadata={
                "start_choice": req.start_choice,
                "industry": industry,
                "inbox_connected": req.inbox_connected,
                "calendar_connected": req.calendar_connected,
                "crm_connected": req.crm_connected,
                "automations_connected": req.automations_connected,
            },
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "success": True,
        "workspace_id": workspace_id,
        "industry": industry,
        "simulation_mode": True,
        "counters": {
            "conversations": inbox_total,
            "opportunities": opportunities,
            "contacts": contacts_total,
            "events": events_total,
        },
    }


# ═════════════════════════════════════════════════════════════════════
# QUANTRO CONNECT + QUANTRO ACTIONS
# ═════════════════════════════════════════════════════════════════════
# Bootstrap: register every provider adapter and Action, then wire the
# two services (ConnectService, ActionExecutor) the endpoints below use.
# Placed at the bottom of the file (not in lifespan) because adapters
# need functions defined earlier in this module (e.g.
# _perform_google_sync_for_workspace, _disconnect_google_workspace) —
# by module-load time everything above has already executed, and
# Python resolves the free variables these closures capture (like
# `action_executor` inside execute_action_for_item, defined far above)
# at CALL time, not at function-definition time, so the forward
# reference here is safe.

def _backend_public_url() -> Optional[str]:
    return (os.environ.get("BACKEND_PUBLIC_URL") or "").strip() or None


google_adapter = GoogleAdapter(google_integrations_col, goog, _perform_google_sync_for_workspace, _disconnect_google_workspace)
microsoft_adapter = MicrosoftAdapter(microsoft_integrations_col, msoa, _perform_microsoft_sync_for_workspace, _disconnect_microsoft_workspace)
facturapi_adapter = FacturapiAdapter(facturapi_connections_col, facturapi_webhook_events_col, _backend_public_url, log_audit_fn=log_audit)
quantro_internal_adapter = QuantroInternalAdapter()

register_provider(google_adapter)
register_provider(microsoft_adapter)
register_provider(facturapi_adapter)
register_provider(quantro_internal_adapter)

connect_service = ConnectService()

register_all_actions()

policy_gate = PolicyGate(action_policies_col, action_executions_col, is_simulation_mode)

action_executor = ActionExecutor(
    action_executions_col, policy_gate, log_audit,
    deps={
        "contacts_col": contacts_col,
        "calendar_col": calendar_col,
        "agents_col": agents_col,
        "onboarding_col": onboarding_col,
        "log_activity": log_activity,
        "google_integrations_col": google_integrations_col,
        "microsoft_integrations_col": microsoft_integrations_col,
        "load_google_credentials": _load_google_credentials,
        "load_microsoft_credentials": _load_microsoft_credentials,
        "goog_module": goog,
        "msoa_module": msoa,
        "facturapi_adapter": facturapi_adapter,
    },
)


@app.exception_handler(QuantroError)
async def quantro_error_handler(request: Request, exc: QuantroError):
    """Every Connect/Actions endpoint below lets QuantroError propagate
    instead of catching it locally — this single handler is what turns
    it into the normalized {error, message, ...} JSON body with the
    right status code (see errors.py's ERROR_CODES)."""
    http_exc = exc.to_http_exception()
    return JSONResponse(status_code=http_exc.status_code, content=http_exc.detail)


# ─── Quantro Connect API ───────────────────────────────────────────────

@app.get("/api/connect/providers")
async def connect_list_providers(workspace_id: str = Depends(get_current_workspace_id)):
    return await connect_service.list_providers(workspace_id)


@app.get("/api/connect/connections")
async def connect_list_connections(workspace_id: str = Depends(get_current_workspace_id)):
    return await connect_service.list_connections(workspace_id)


@app.get("/api/connect/providers/{provider}")
async def connect_get_provider(provider: str, workspace_id: str = Depends(get_current_workspace_id)):
    return await connect_service.get_provider(workspace_id, provider)


@app.post("/api/connect/providers/{provider}/test")
async def connect_test_provider(
    provider: str, workspace_id: str = Depends(get_current_workspace_id),
    _m: dict = Depends(require_role("leader")),
):
    return await connect_service.test_connection(workspace_id, provider)


@app.post("/api/connect/providers/{provider}/sync")
async def connect_sync_provider(
    provider: str, workspace_id: str = Depends(get_current_workspace_id),
    _m: dict = Depends(require_role("leader")),
):
    return await connect_service.sync(workspace_id, provider)


@app.delete("/api/connect/providers/{provider}")
async def connect_disconnect_provider(
    provider: str, workspace_id: str = Depends(get_current_workspace_id),
    _m: dict = Depends(require_role("leader")),
):
    return await connect_service.disconnect(workspace_id, provider)


class FacturapiConnectRequest(BaseModel):
    secret_key: str


@app.post("/api/connect/providers/facturapi/connect")
async def connect_facturapi(
    req: FacturapiConnectRequest,
    workspace_id: str = Depends(get_current_workspace_id),
    _m: dict = Depends(require_role("leader")),
):
    """Connect Facturapi with a Test or Live secret key. The key is
    never persisted in plaintext and never returned — see
    integrations/providers/facturapi.py's connect()."""
    return await facturapi_adapter.connect(workspace_id, {"secret_key": req.secret_key})


@app.get("/api/connect/providers/google/request-permission")
async def connect_google_request_permission(
    request: Request,
    action_id: str,
    return_to: Optional[str] = None,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    """Incremental Google authorization for one Action's write scope —
    the "Grant permission" flow. Reuses the exact same state-doc +
    callback machinery as /api/integrations/google/start (the callback
    itself needs no changes: Google returns the FULL cumulative scope
    set once include_granted_scopes=true is used, so the existing
    callback naturally persists the broader grant)."""
    if not goog.is_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured.")
    scope = goog.ACTION_SCOPES.get(action_id)
    if not scope:
        raise HTTPException(status_code=400, detail=f"No additional Google scope is defined for action '{action_id}'")

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = goog.resolve_redirect_uri(base_url)
    state = uuid.uuid4().hex
    await google_oauth_state_col.insert_one({
        "state": state, "user_id": user.user_id, "workspace_id": workspace_id,
        "return_to": _sanitize_return_to(return_to), "redirect_uri": redirect_uri,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    })
    auth_url = goog.build_incremental_authorization_url(state=state, redirect_uri=redirect_uri, additional_scopes=[scope])
    return {"auth_url": auth_url, "state": state}


# ─── Facturapi webhook receiver ────────────────────────────────────────

@app.post("/api/webhooks/facturapi/{connection_id}/{webhook_token}")
async def facturapi_webhook_receiver(connection_id: str, webhook_token: str, request: Request):
    """No @app-level auth dependency — Facturapi calls this directly.
    Authenticity comes from the high-entropy webhook_token embedded in
    the URL path (generated per-connection, see
    FacturapiAdapter._register_webhook) plus, when available, the
    Facturapi-Signature header verified against Facturapi's own
    validate-signature endpoint. Unknown connection / bad token get a
    plain 404 (don't help an attacker distinguish "wrong token" from
    "no such endpoint"); everything else — including malformed/
    duplicate events, which ARE legitimate Facturapi traffic — gets a
    2xx so Facturapi doesn't retry-storm us."""
    raw_body = await request.body()
    signature = request.headers.get("Facturapi-Signature")
    result = await facturapi_adapter.handle_webhook(connection_id, webhook_token, raw_body, signature)
    if result.get("reason") in ("unknown_connection", "invalid_token"):
        raise HTTPException(status_code=404, detail="Not found")
    return result


# ─── Quantro Actions API ────────────────────────────────────────────────

class ExecuteActionRequest(BaseModel):
    input: Dict[str, Any] = {}
    idempotency_key: Optional[str] = None
    dry_run: bool = False
    source: str = "manual"


def _serialize_action_definition(d, connection_status: Optional[str]) -> Dict[str, Any]:
    return {
        "action_id": d.action_id,
        "provider": d.provider,
        "name": d.name,
        "description": d.description,
        "risk_level": d.risk_level.value,
        "input_schema": d.input_schema,
        "required_capabilities": d.required_capabilities,
        "required_scopes": d.required_scopes,
        "supports_dry_run": d.supports_dry_run,
        "idempotent": d.idempotent,
        "connection_status": connection_status,
    }


@app.get("/api/actions")
async def actions_list(
    provider: Optional[str] = None,
    connected: Optional[bool] = None,
    workspace_id: str = Depends(get_current_workspace_id),
):
    defs = list_actions(provider=provider)
    out = []
    for d in defs:
        adapter = get_connect_provider(d.provider)
        connection_status = (await adapter.get_status(workspace_id)).status.value if adapter else None
        if connected is not None:
            is_connected = connection_status in ("connected", "connected_limited")
            if is_connected != connected:
                continue
        out.append(_serialize_action_definition(d, connection_status))
    return out


@app.get("/api/actions/{action_id}")
async def actions_get(action_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    d = get_action(action_id)
    if not d:
        raise HTTPException(status_code=404, detail="Action not found")
    adapter = get_connect_provider(d.provider)
    connection_status = (await adapter.get_status(workspace_id)).status.value if adapter else None
    return _serialize_action_definition(d, connection_status)


@app.post("/api/actions/{action_id}/execute")
async def actions_execute(
    action_id: str, req: ExecuteActionRequest,
    workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
):
    return await action_executor.execute(
        workspace_id=workspace_id, action_id=action_id, input=req.input,
        requested_by=user.user_id, source=req.source,
        idempotency_key=req.idempotency_key, dry_run=req.dry_run,
    )


@app.get("/api/actions/executions")
async def actions_list_executions(
    workspace_id: str = Depends(get_current_workspace_id),
    action_id: Optional[str] = None,
    provider: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    query: Dict[str, Any] = {"workspace_id": workspace_id}
    if action_id:
        query["action_id"] = action_id
    if provider:
        query["provider"] = provider
    if status:
        query["status"] = status
    rows = await action_executions_col.find(query, {"_id": 0}).sort("started_at", -1).to_list(limit)
    return [serialize_doc(r) for r in rows]


@app.get("/api/actions/executions/{execution_id}")
async def actions_get_execution(execution_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    row = await action_executions_col.find_one({"execution_id": execution_id, "workspace_id": workspace_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Execution not found")
    return serialize_doc(row)


@app.post("/api/actions/executions/{execution_id}/approve")
async def actions_approve_execution(
    execution_id: str, workspace_id: str = Depends(get_current_workspace_id),
    user: User = Depends(get_current_user),
    _m: dict = Depends(require_role("leader")),
):
    return await action_executor.approve(workspace_id, execution_id, user.user_id)


@app.post("/api/actions/executions/{execution_id}/cancel")
async def actions_cancel_execution(
    execution_id: str, workspace_id: str = Depends(get_current_workspace_id),
    _m: dict = Depends(require_role("leader")),
):
    return await action_executor.cancel(workspace_id, execution_id)
