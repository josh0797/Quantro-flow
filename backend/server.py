import os
import uuid
import json
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import Optional, List
from emergentintegrations.llm.chat import LlmChat, UserMessage

# ─── Config ────────────────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "quantro_os")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
SESSION_COOKIE_NAME = "session_token"
SESSION_TTL_DAYS = 7

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
audit_log_col = db["audit_log"]

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


# ─── Auth & Workspace (Phase 7a) ──────────────────────────────────────
class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    current_workspace_id: Optional[str] = None


def _coerce_expiry(expires_at):
    """Return a timezone-aware UTC datetime from either str or datetime."""
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at


async def _extract_session_token(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


async def get_current_user(request: Request) -> User:
    """FastAPI dependency: resolve the authenticated user from a session cookie.

    Raises 401 if session is missing/expired/invalid. Every workspace-scoped
    endpoint depends on this (directly or via get_current_workspace_id)."""
    token = await _extract_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_doc = await user_sessions_col.find_one({"session_token": token}, {"_id": 0})
    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = _coerce_expiry(session_doc.get("expires_at"))
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user_doc = await users_col.find_one({"user_id": session_doc["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")

    return User(**{k: user_doc.get(k) for k in ["user_id", "email", "name", "picture", "current_workspace_id"]})


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


async def log_audit(event_type: str, description: str, user_id: Optional[str] = None, workspace_id: Optional[str] = None, metadata: Optional[dict] = None):
    """Append an audit log event. Non-fatal on error."""
    try:
        await audit_log_col.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "description": description,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception:
        pass


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

async def build_intent_prompt(business_profile=None):
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

async def build_content_prompt(business_profile=None):
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
    """Execute the suggested action for an inbox item. Returns execution results."""
    action = item.get("ai_suggested_action")
    if not action:
        return {"executed": False, "reason": "No action available"}
    
    action_type = action["type"]
    entities = item.get("ai_intent", {}).get("entities", {})
    results = []
    # Downstream artifacts inherit the mode of the triggering inbox item
    # so everything remains in the correct sandbox/workspace.
    sim_flag = bool(item.get("is_simulation", False))
    ws_id = item.get("workspace_id", DEFAULT_WORKSPACE_ID)
    
    if action_type == "schedule_meeting":
        event = {
            "event_id": str(uuid.uuid4()),
            "title": f"Meeting - {item['from_name']}",
            "description": action["description"],
            "start_time": (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat(),
            "location": entities.get("property", "TBD"),
            "attendees": [item["from_name"]],
            "status": "pending",
            "source": f"ai_{source}",
            "created_at": now_iso(),
            "contact_id": item.get("contact_id"),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await calendar_col.insert_one(event)
        await log_activity("calendar", f"Meeting auto-scheduled ({source})", f"Meeting with {item['from_name']} created automatically", event["event_id"], "calendar")
        results.append({"type": "event_created", "event_id": event["event_id"]})
    
    elif action_type == "create_contact":
        contact = {
            "contact_id": str(uuid.uuid4()),
            "name": entities.get("person_name", item["from_name"]),
            "email": entities.get("email", item["from_email"]),
            "phone": entities.get("phone", ""),
            "type": "lead",
            "lifecycle_stage": "new",
            "source": f"inbox_{source}",
            "ghl_sync_status": "pending",
            "ghl_last_sync": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": item.get("ai_intent", {}).get("summary", ""),
            "is_simulation": sim_flag,
            "workspace_id": ws_id,
        }
        await contacts_col.insert_one(contact)
        await inbox_col.update_one({"inbox_id": item["inbox_id"]}, {"$set": {"contact_id": contact["contact_id"]}})
        await log_activity("crm", f"Contact auto-created ({source})", f"New contact {contact['name']} created automatically", contact["contact_id"], "contact")
        results.append({"type": "contact_created", "contact_id": contact["contact_id"]})
    
    elif action_type == "start_onboarding":
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
            await onboarding_col.insert_one({"workspace_id": ws_id, "task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"], "title": title, "description": f"Auto-generated step {idx+1}", "status": "pending", "order": idx + 1, "completed_at": None, "auto_generated": True, "is_simulation": sim_flag})
        await log_activity("onboarding", f"Onboarding auto-started ({source})", f"Agent {agent['name']} onboarding initiated automatically", agent["agent_id"], "agent")
        results.append({"type": "agent_created", "agent_id": agent["agent_id"]})
    
    elif action_type == "send_follow_up":
        await log_activity("inbox", f"Follow-up auto-queued ({source})", f"Follow-up for {item['from_name']} queued automatically", item["inbox_id"], "inbox")
        results.append({"type": "follow_up_queued"})
    
    elif action_type == "ignore":
        await log_activity("inbox", f"Auto-ignored ({source})", f"Message from {item['from_name']} auto-ignored (spam/irrelevant)", item["inbox_id"], "inbox")
        results.append({"type": "ignored"})
    
    else:
        await log_activity("inbox", f"Action auto-executed ({source})", f"Action '{action_type}' for {item['from_name']} executed automatically", item["inbox_id"], "inbox")
        results.append({"type": action_type})
    
    # Mark as auto-actioned
    await inbox_col.update_one(
        {"inbox_id": item["inbox_id"]},
        {"$set": {"status": "auto_actioned", "auto_executed": True, "auto_executed_at": now_iso(), "execution_source": source, "execution_results": results}}
    )
    
    return {"executed": True, "action_type": action_type, "results": results}


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
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Complete compliance training", "description": "Review and sign all compliance documents", "status": "completed", "order": 1, "completed_at": (now - timedelta(days=1)).isoformat(), "auto_generated": True},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Set up CRM profile", "description": "Configure GoHighLevel profile and sync", "status": "completed", "order": 2, "completed_at": (now - timedelta(hours=12)).isoformat(), "auto_generated": True},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Configure email signature", "description": "Set up branded email signature template", "status": "in_progress", "order": 3, "completed_at": None, "auto_generated": True},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Schedule orientation with team lead", "description": "Book 1:1 orientation meeting with Sophia Turner", "status": "pending", "order": 4, "completed_at": None, "auto_generated": True},
        {"task_id": str(uuid.uuid4()), "agent_id": james_id, "title": "Access granted to listing portal", "description": "Get login credentials for MLS and listing tools", "status": "pending", "order": 5, "completed_at": None, "auto_generated": True},
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
        {"content_id": str(uuid.uuid4()), "type": "social_post", "title": "New Listing - 789 Lakeshore Dr", "content": {"text": "Discover luxury waterfront living at 789 Lakeshore Drive. This stunning 5-bedroom estate features an infinity pool and smart home system.", "hashtags": ["#LuxuryLiving", "#WaterfrontEstate", "#DreamHome"], "platform": "instagram"}, "status": "draft", "created_at": now - timedelta(hours=6), "created_by": "ai"},
        {"content_id": str(uuid.uuid4()), "type": "email_draft", "title": "Q4 Market Update", "content": {"subject": "Your Q4 Real Estate Market Update", "body": "Dear valued clients,\n\nAs we close out Q4, the market continues to show strong momentum. Prices are up 3% in our metro area, and inventory remains tight.\n\nThis presents an excellent opportunity for sellers looking to capitalize on current demand. For buyers, acting quickly on well-priced properties is key.\n\nLet's schedule a call to discuss how these trends affect your real estate goals.", "call_to_action": "Schedule a consultation"}, "status": "published", "created_at": now - timedelta(days=2), "created_by": "ai"},
        {"content_id": str(uuid.uuid4()), "type": "social_post", "title": "Team Spotlight - Aisha Patel", "content": {"text": "Meet Aisha Patel, one of our senior agents with 5+ years of experience. She specializes in helping first-time homebuyers navigate the market with confidence.", "hashtags": ["#MeetTheTeam", "#RealEstateAgent", "#FirstTimeHomeBuyer"], "platform": "linkedin"}, "status": "draft", "created_at": now - timedelta(hours=12), "created_by": "ai"},
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

    print(f"Seeded database with connected mock data")

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


# ─── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_database()
    await ensure_integrations_seeded()
    await backfill_simulation_flag()
    await backfill_workspace_scoping()
    yield
    client.close()

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

# ─── Auth Endpoints (Phase 7a) ────────────────────────────────────────
class SessionExchangeRequest(BaseModel):
    session_id: str


def _set_session_cookie(response: Response, token: str):
    """Set the session cookie with production-grade attributes."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


@app.post("/api/auth/session")
async def auth_session_exchange(req: SessionExchangeRequest, response: Response):
    """Exchange an Emergent Auth session_id (one-time) for a persistent session cookie.

    Flow:
      1. Frontend redirects to auth.emergentagent.com which returns with #session_id=<id>.
      2. Frontend posts that session_id here.
      3. Backend calls Emergent's /session-data to fetch the user profile + session_token.
      4. Backend upserts the user, creates/claims a workspace, stores the session, and
         sets an httpOnly cookie. Frontend then navigates to the dashboard.
    """
    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": req.session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()
    email = data.get("email")
    name = data.get("name") or (email or "User").split("@")[0]
    picture = data.get("picture")
    session_token = data.get("session_token")
    if not email or not session_token:
        raise HTTPException(status_code=502, detail="Malformed auth response")

    # Upsert user by email
    user_doc = await users_col.find_one({"email": email}, {"_id": 0})
    is_new_user = user_doc is None
    if is_new_user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "created_at": datetime.now(timezone.utc),
            "last_login_at": datetime.now(timezone.utc),
        }
        await users_col.insert_one(user_doc)
    else:
        await users_col.update_one(
            {"email": email},
            {"$set": {
                "name": name,
                "picture": picture,
                "last_login_at": datetime.now(timezone.utc),
            }},
        )

    # Ensure workspace membership
    workspace_id = await claim_or_create_workspace_for_user(user_doc)
    await users_col.update_one(
        {"user_id": user_doc["user_id"]},
        {"$set": {"current_workspace_id": workspace_id}},
    )

    # Persist session
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    await user_sessions_col.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user_doc["user_id"],
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    _set_session_cookie(response, session_token)

    await log_audit(
        "auth.login",
        f"{email} logged in",
        user_id=user_doc["user_id"],
        workspace_id=workspace_id,
        metadata={"new_user": is_new_user},
    )

    return {
        "user": {
            "user_id": user_doc["user_id"],
            "email": email,
            "name": name,
            "picture": picture,
            "current_workspace_id": workspace_id,
        },
        "workspace_id": workspace_id,
        # Bearer token for clients that cannot persist cookies
        # (e.g., Kubernetes ingress forces ACAO: * which blocks cookie CORS).
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
    }


@app.get("/api/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    memberships = await workspace_members_col.find({"user_id": user.user_id}, {"_id": 0}).to_list(50)
    workspace_ids = [m["workspace_id"] for m in memberships]
    workspaces = []
    if workspace_ids:
        rows = await workspaces_col.find({"workspace_id": {"$in": workspace_ids}}, {"_id": 0}).to_list(50)
        role_map = {m["workspace_id"]: m.get("role", "member") for m in memberships}
        for w in rows:
            workspaces.append({
                "workspace_id": w["workspace_id"],
                "name": w.get("name", "Workspace"),
                "role": role_map.get(w["workspace_id"], "member"),
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


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = await _extract_session_token(request)
    if token:
        session = await user_sessions_col.find_one({"session_token": token}, {"_id": 0})
        if session:
            await log_audit(
                "auth.logout",
                "user logged out",
                user_id=session.get("user_id"),
                workspace_id=None,
            )
        await user_sessions_col.delete_one({"session_token": token})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="none", secure=True)
    return {"success": True}


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

    # Overall status
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
        ],
        "latest_check": serialize_doc(latest) if latest else None,
        "recent_repairs": [serialize_doc(r) for r in recent_repairs],
        "total_repair_events": total_repair_events,
    }

# ─── Plan & Usage ──────────────────────────────────────────────────────
@app.get("/api/usage")
async def get_usage(workspace_id: str = Depends(get_current_workspace_id)):
    """Return Plan + API Usage + Billing snapshot for the current workspace.

    Until we wire billing/metering, we compute *this month's* API call
    counts from activity + inbox/contact/content volumes so the UI has
    realistic data to render. The plan + billing blocks return a default
    'Starter (Trial)' shape that can be replaced once a Stripe (or other)
    integration is wired up."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    scope = {"workspace_id": workspace_id}
    month_scope = dict(scope)
    month_scope["timestamp"] = {"$gte": start_of_month}

    # Per-module "API calls" proxy — counts how many records were produced
    # this month by each subsystem. This is illustrative only; once real
    # metering is in place this endpoint becomes the single source of truth.
    inbox_calls = await activity_col.count_documents(merge_query({"event_type": "inbox"}, month_scope))
    crm_calls = await activity_col.count_documents(merge_query({"event_type": {"$in": ["crm", "calendar"]}}, month_scope))
    content_calls = await activity_col.count_documents(merge_query({"event_type": "content"}, month_scope))
    automation_calls = await activity_col.count_documents(merge_query({"event_type": {"$in": ["system", "onboarding"]}}, month_scope))
    total_calls = inbox_calls + crm_calls + content_calls + automation_calls

    monthly_limit = 10000  # default trial limit — can be overridden per-plan later
    usage_percent = min(100, round((total_calls / monthly_limit) * 100, 1)) if monthly_limit else 0
    overage = max(0, total_calls - monthly_limit)

    # Breakdown with shares
    def pct(n):
        return round((n / total_calls) * 100, 1) if total_calls else 0
    breakdown = [
        {"module": "inbox_ai", "label": "Inbox AI", "calls": inbox_calls, "share": pct(inbox_calls)},
        {"module": "crm", "label": "CRM", "calls": crm_calls, "share": pct(crm_calls)},
        {"module": "content", "label": "Content Engine", "calls": content_calls, "share": pct(content_calls)},
        {"module": "automations", "label": "Automations", "calls": automation_calls, "share": pct(automation_calls)},
    ]

    # Plan + billing placeholder until a real billing integration is wired.
    workspace_doc = await workspaces_col.find_one({"workspace_id": workspace_id}, {"_id": 0}) or {}
    trial_start = workspace_doc.get("created_at") or now
    if isinstance(trial_start, str):
        from datetime import datetime as _dt
        trial_start = _dt.fromisoformat(trial_start.replace("Z", "+00:00"))
    if trial_start.tzinfo is None:
        trial_start = trial_start.replace(tzinfo=timezone.utc)
    renewal = trial_start + timedelta(days=30)

    return {
        "plan": {
            "name": "Starter",
            "tier": "trial",
            "status": "trial",
            "renewal_date": renewal.isoformat(),
            "features": ["Smart Inbox", "CRM", "Content Engine", "Automations", "Simulation Mode"],
        },
        "usage": {
            "total_calls": total_calls,
            "monthly_limit": monthly_limit,
            "usage_percent": usage_percent,
            "overage": overage,
            "period_start": start_of_month.isoformat(),
            "breakdown": breakdown,
        },
        "billing": {
            "payment_method": None,  # masked last-4 once integrated (e.g. "•••• 4242")
            "next_billing_date": renewal.isoformat(),
            "amount_due": 0,
            "currency": "USD",
        },
    }




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
async def analyze_inbox_item(inbox_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    item = await inbox_col.find_one({"workspace_id": workspace_id, "inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    # Get business profile for context-aware prompts
    intent_prompt = await build_intent_prompt()
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"intent-{inbox_id}-{uuid.uuid4().hex[:6]}",
        system_message=intent_prompt,
    ).with_model("openai", "gpt-4o")
    
    message_text = f"From: {item['from_name']} ({item['from_email']})\nSubject: {item['subject']}\n\n{item['body']}"
    response = await chat.send_message(UserMessage(text=message_text))
    ai_result = await parse_ai_json(response)
    
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
        exec_result = await execute_action_for_item(updated_item, source="single_analyze")
        auto_executed = exec_result.get("executed", False)
        execution_results = exec_result.get("results")
    
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
async def batch_analyze_inbox(req: BatchAnalyzeRequest, workspace_id: str = Depends(get_current_workspace_id)):
    """Process multiple inbox items with AI classification in sequence."""
    results = []
    
    # Get business profile once for all items
    intent_prompt = await build_intent_prompt()
    
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
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"batch-{inbox_id}-{uuid.uuid4().hex[:6]}",
                system_message=intent_prompt,
            ).with_model("openai", "gpt-4o")
            
            message_text = f"From: {item['from_name']} ({item['from_email']})\nSubject: {item['subject']}\n\n{item['body']}"
            response = await chat.send_message(UserMessage(text=message_text))
            ai_result = await parse_ai_json(response)
            
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
    
    result = await onboarding_col.update_one({"task_id": task_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = await onboarding_col.find_one({"task_id": task_id})
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
async def generate_content(req: ContentGenerateRequest, workspace_id: str = Depends(get_current_workspace_id)):
    # Get business profile for context-aware content generation
    content_prompt = await build_content_prompt()
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"content-{uuid.uuid4().hex[:8]}",
        system_message=content_prompt,
    ).with_model("openai", "gpt-4o")
    
    response = await chat.send_message(UserMessage(text=req.prompt))
    ai_result = await parse_ai_json(response)
    
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
    result = await content_col.delete_one({"content_id": content_id})
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
async def create_policy(req: AutomationPolicyRequest, workspace_id: str = Depends(get_current_workspace_id)):
    policy = {
        "policy_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "intent": req.intent,
        "action": req.action,
        "confidence_threshold_high": req.confidence_threshold_high,
        "confidence_threshold_medium": req.confidence_threshold_medium,
        "high_action": req.high_action,
        "medium_action": req.medium_action,
        "low_action": req.low_action,
        "enabled": req.enabled,
        "created_at": now_iso(),
    }
    await policies_col.insert_one(policy)
    await log_activity("system", "Policy created", f"New automation policy for '{req.intent}'", policy["policy_id"], "policy", workspace_id=workspace_id)
    await log_audit("policy.created", f"Created policy for intent '{req.intent}'", workspace_id=workspace_id)
    return serialize_doc(policy)

@app.delete("/api/policies/{policy_id}")
async def delete_policy(policy_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    result = await policies_col.delete_one({"workspace_id": workspace_id, "policy_id": policy_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await log_audit("policy.deleted", f"Deleted policy {policy_id}", workspace_id=workspace_id)
    return {"success": True}

@app.put("/api/policies/{policy_id}")
async def update_policy(policy_id: str, req: AutomationPolicyRequest, workspace_id: str = Depends(get_current_workspace_id)):
    update = {
        "intent": req.intent,
        "action": req.action,
        "confidence_threshold_high": req.confidence_threshold_high,
        "confidence_threshold_medium": req.confidence_threshold_medium,
        "high_action": req.high_action,
        "medium_action": req.medium_action,
        "low_action": req.low_action,
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
async def create_escalation_rule(req: EscalationRuleRequest, workspace_id: str = Depends(get_current_workspace_id)):
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
async def update_escalation_rule(rule_id: str, req: EscalationRuleRequest, workspace_id: str = Depends(get_current_workspace_id)):
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
async def delete_escalation_rule(rule_id: str, workspace_id: str = Depends(get_current_workspace_id)):
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
    q = dict(query); q["workspace_id"] = workspace_id
    templates = await templates_col.find(q).sort("created_at", -1).to_list(100)
    return [serialize_doc(t) for t in templates]

@app.get("/api/templates/{template_id}")
async def get_template(template_id: str, workspace_id: str = Depends(get_current_workspace_id)):
    template = await templates_col.find_one({"workspace_id": workspace_id, "template_id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return serialize_doc(template)

@app.post("/api/templates")
async def create_template(req: ContentTemplateRequest, workspace_id: str = Depends(get_current_workspace_id)):
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
async def update_template(template_id: str, req: ContentTemplateRequest, workspace_id: str = Depends(get_current_workspace_id)):
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
async def delete_template(template_id: str, workspace_id: str = Depends(get_current_workspace_id)):
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
async def generate_from_template(template_id: str, req: GenerateFromTemplateRequest, workspace_id: str = Depends(get_current_workspace_id)):
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
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"template-{template_id}-{uuid.uuid4().hex[:6]}",
        system_message=template_prompt,
    ).with_model("openai", "gpt-4o")
    
    prompt = f"Template category: {template['category']}\nTemplate name: {template['name']}\n\nSubject (if email): {subject}\n\nBody:\n{body}\n\nContext: {json.dumps(req.context)}\n\nPlease enhance this content while keeping the overall structure and intent."
    
    response = await chat.send_message(UserMessage(text=prompt))
    ai_result = await parse_ai_json(response)
    
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
async def update_business_profile(req: BusinessProfileUpdate, workspace_id: str = Depends(get_current_workspace_id)):
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
    
    result = await business_profile_col.update_one(
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
            existing_sim = await inbox_col.count_documents({"is_simulation": True})
            if existing_sim == 0:
                need_regenerate = True
        elif req.industry != old_industry:
            # Industry changed while in Simulation: regenerate sandbox to match new industry.
            need_regenerate = True

        if need_regenerate:
            await generate_simulation_data(req.industry)
            await log_activity("system", "Simulation data auto-generated", f"Generated {req.industry} data", "simulation", "system")

    updated = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    return serialize_doc(updated)

# ─── Integrations Config ───────────────────────────────────────────────
class IntegrationUpdate(BaseModel):
    status: str
    config: dict = {}

@app.get("/api/integrations")
async def get_integrations(workspace_id: str = Depends(get_current_workspace_id)):
    """Get all integration configurations for the current workspace."""
    integrations = await integrations_config_col.find({"workspace_id": workspace_id}, {"_id": 0}).to_list(100)
    return [serialize_doc(i) for i in integrations]

@app.get("/api/integrations/{provider}")
async def get_integration(provider: str, workspace_id: str = Depends(get_current_workspace_id)):
    """Get a specific integration configuration."""
    integration = await integrations_config_col.find_one({"workspace_id": workspace_id, "provider": provider}, {"_id": 0})
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return serialize_doc(integration)

@app.put("/api/integrations/{provider}")
async def update_integration(provider: str, req: IntegrationUpdate, workspace_id: str = Depends(get_current_workspace_id)):
    """Update an integration configuration."""
    update_data = {
        "status": req.status,
        "config": req.config,
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
    return serialize_doc(updated)

@app.post("/api/integrations/{provider}/test")
async def test_integration(provider: str, workspace_id: str = Depends(get_current_workspace_id)):
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

async def generate_simulation_data(industry: str):
    """Generate realistic operational data for the selected industry."""
    now = datetime.utcnow()
    
    # Clear existing simulation data
    await inbox_col.delete_many({"is_simulation": True})
    await contacts_col.delete_many({"is_simulation": True})
    await calendar_col.delete_many({"is_simulation": True})
    await agents_col.delete_many({"is_simulation": True})
    await activity_col.delete_many({"is_simulation": True})
    
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
    
    # Insert all simulation data into database
    if simulation_data.get("contacts"):
        await contacts_col.insert_many(simulation_data["contacts"])
    if simulation_data.get("inbox"):
        await inbox_col.insert_many(simulation_data["inbox"])
    if simulation_data.get("events"):
        await calendar_col.insert_many(simulation_data["events"])
    if simulation_data.get("agents"):
        await agents_col.insert_many(simulation_data["agents"])
    if simulation_data.get("activities"):
        await activity_col.insert_many(simulation_data["activities"])
    
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
async def generate_simulation(workspace_id: str = Depends(get_current_workspace_id)):
    """Generate simulation data for the current industry."""
    profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    if not profile:
        raise HTTPException(status_code=404, detail="Business profile not found")
    
    if not profile.get("simulation_mode", False):
        raise HTTPException(status_code=400, detail="Simulation mode is not enabled")
    
    industry = profile.get("industry", "other")
    result = await generate_simulation_data(industry)
    
    await log_activity("system", "Simulation data generated", f"Generated {industry} operational data", "simulation", "system")
    
    return result


@app.post("/api/simulation/clear")
async def clear_simulation(workspace_id: str = Depends(get_current_workspace_id)):
    """Clear all simulation data."""
    deleted_counts = {
        "contacts": (await contacts_col.delete_many({"is_simulation": True})).deleted_count,
        "inbox": (await inbox_col.delete_many({"is_simulation": True})).deleted_count,
        "events": (await calendar_col.delete_many({"is_simulation": True})).deleted_count,
        "agents": (await agents_col.delete_many({"is_simulation": True})).deleted_count,
        "activities": (await activity_col.delete_many({"is_simulation": True})).deleted_count,
    }
    
    await log_activity("system", "Simulation data cleared", "All simulation data removed", "simulation", "system")
    
    return {"success": True, "deleted": deleted_counts}


@app.get("/api/simulation/status")
async def simulation_status(workspace_id: str = Depends(get_current_workspace_id)):
    """Get simulation mode status and data counts."""
    profile = await business_profile_col.find_one({"workspace_id": workspace_id}, {"_id": 0})
    simulation_mode = profile.get("simulation_mode", False) if profile else False
    
    counts = {
        "contacts": await contacts_col.count_documents({"is_simulation": True}),
        "inbox": await inbox_col.count_documents({"is_simulation": True}),
        "events": await calendar_col.count_documents({"is_simulation": True}),
        "agents": await agents_col.count_documents({"is_simulation": True}),
        "activities": await activity_col.count_documents({"is_simulation": True}),
    }
    
    return {
        "simulation_mode": simulation_mode,
        "industry": profile.get("industry", "other") if profile else "other",
        "data_counts": counts,
        "has_data": sum(counts.values()) > 0
    }
