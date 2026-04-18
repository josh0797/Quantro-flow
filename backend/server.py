import os
import uuid
import json
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import Optional, List
from emergentintegrations.llm.chat import LlmChat, UserMessage

# ─── Config ────────────────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "quantro_os")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

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

# ─── AI Prompts ────────────────────────────────────────────────────────
INTENT_SYSTEM_PROMPT = """You are an AI assistant for Quantro One, a real estate operating system.
Analyze incoming messages and detect intent.

Respond with ONLY valid JSON (no markdown fences):
{
  "intent": "<booking|onboarding|follow_up|inquiry|escalation|spam|needs_review>",
  "confidence": <float 0.0-1.0>,
  "summary": "<1-sentence summary>",
  "entities": {
    "person_name": "<name or null>",
    "email": "<email or null>",
    "phone": "<phone or null>",
    "date_time": "<date/time or null>",
    "property": "<property or null>"
  },
  "suggested_action": {
    "type": "<schedule_meeting|create_contact|send_follow_up|start_onboarding|flag_review|ignore|none>",
    "description": "<what to do>"
  }
}"""

CONTENT_SYSTEM_PROMPT = """You are a premium content writer for a real estate team.
Generate professional, engaging content.

Respond with ONLY valid JSON (no markdown fences):
{
  "social_post": {
    "text": "<social media post, 1-3 sentences>",
    "hashtags": ["<hashtags>"],
    "platform": "instagram"
  },
  "email_draft": {
    "subject": "<subject line>",
    "body": "<2-4 paragraphs>",
    "call_to_action": "<CTA>"
  }
}

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

async def log_activity(event_type, title, description, related_id=None, related_type=None):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "title": title,
        "description": description,
        "related_id": related_id,
        "related_type": related_type,
        "timestamp": now_iso(),
    }
    await activity_col.insert_one(event)
    return event

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
        {"event_id": str(uuid.uuid4()), "event_type": "system", "title": "System initialized", "description": "Quantro One OS started successfully. All services running.", "related_id": None, "related_type": None, "timestamp": now - timedelta(hours=12)},
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

# ─── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_database()
    yield
    client.close()

app = FastAPI(title="Quantro One | Realty OS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Health ────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "running", "service": "Quantro One | Realty OS", "timestamp": datetime.utcnow().isoformat()}

# ─── Dashboard ─────────────────────────────────────────────────────────
@app.get("/api/dashboard/metrics")
async def get_dashboard_metrics():
    total_agents = await agents_col.count_documents({})
    active_agents = await agents_col.count_documents({"status": "active"})
    total_contacts = await contacts_col.count_documents({})
    total_inbox = await inbox_col.count_documents({})
    unread_inbox = await inbox_col.count_documents({"read": False})
    today_events = await calendar_col.count_documents({})
    synced_contacts = await contacts_col.count_documents({"ghl_sync_status": "synced"})
    total_content = await content_col.count_documents({})
    
    return {
        "agents": {"total": total_agents, "active": active_agents},
        "contacts": {"total": total_contacts, "synced": synced_contacts},
        "inbox": {"total": total_inbox, "unread": unread_inbox},
        "events": {"today": today_events},
        "content": {"total": total_content},
        "system_status": "running",
        "last_sync": datetime.utcnow().isoformat(),
    }

@app.get("/api/dashboard/suggestions")
async def get_ai_suggestions():
    unprocessed = await inbox_col.find({"status": "new", "ai_intent": None}).to_list(5)
    processed_pending = await inbox_col.find({"status": "processed", "ai_intent": {"$ne": None}}).to_list(5)
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
async def get_inbox(status: Optional[str] = None):
    query = {}
    if status:
        query["status"] = status
    items = await inbox_col.find(query).sort("received_at", -1).to_list(100)
    return [serialize_doc(item) for item in items]

@app.get("/api/inbox/{inbox_id}")
async def get_inbox_item(inbox_id: str):
    item = await inbox_col.find_one({"inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    return serialize_doc(item)

@app.post("/api/inbox/{inbox_id}/analyze")
async def analyze_inbox_item(inbox_id: str):
    item = await inbox_col.find_one({"inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"intent-{inbox_id}-{uuid.uuid4().hex[:6]}",
        system_message=INTENT_SYSTEM_PROMPT,
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
    
    updated = await inbox_col.find_one({"inbox_id": inbox_id})
    return serialize_doc(updated)

@app.post("/api/inbox/{inbox_id}/approve")
async def approve_inbox_action(inbox_id: str):
    item = await inbox_col.find_one({"inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not item.get("ai_suggested_action"):
        raise HTTPException(status_code=400, detail="No AI action to approve")
    
    action = item["ai_suggested_action"]
    action_type = action["type"]
    results = []
    
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
async def decline_inbox_action(inbox_id: str):
    item = await inbox_col.find_one({"inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    await inbox_col.update_one({"inbox_id": inbox_id}, {"$set": {"status": "declined"}})
    await log_activity("inbox", "Action declined", f"AI suggestion for {item['from_name']} was declined", inbox_id, "inbox")
    return {"success": True}

# ─── Batch AI Triage ───────────────────────────────────────────────────
@app.post("/api/inbox/batch-analyze")
async def batch_analyze_inbox(req: BatchAnalyzeRequest):
    """Process multiple inbox items with AI classification in sequence."""
    results = []
    
    for inbox_id in req.inbox_ids:
        item = await inbox_col.find_one({"inbox_id": inbox_id})
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
                system_message=INTENT_SYSTEM_PROMPT,
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
            
            updated = await inbox_col.find_one({"inbox_id": inbox_id})
            results.append({"inbox_id": inbox_id, "status": "classified", "data": serialize_doc(updated)})
            
        except Exception as e:
            await inbox_col.update_one(
                {"inbox_id": inbox_id},
                {"$set": {"status": "new"}}
            )
            results.append({"inbox_id": inbox_id, "status": "error", "error": str(e)})
    
    await log_activity("ai", "Batch triage complete", f"Processed {len(req.inbox_ids)} message(s), {sum(1 for r in results if r['status'] == 'classified')} classified", None, "inbox")
    
    return {"success": True, "results": results, "total": len(req.inbox_ids), "classified": sum(1 for r in results if r["status"] == "classified")}

@app.post("/api/inbox/batch-approve")
async def batch_approve_inbox(req: BatchAnalyzeRequest):
    """Approve all AI-suggested actions for multiple inbox items."""
    results = []
    
    for inbox_id in req.inbox_ids:
        item = await inbox_col.find_one({"inbox_id": inbox_id})
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
                }
                await agents_col.insert_one(agent)
                for idx, title in enumerate(["Complete compliance training", "Set up CRM profile", "Configure email signature", "Schedule orientation with team lead", "Access granted to listing portal"]):
                    await onboarding_col.insert_one({"task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"], "title": title, "description": f"Auto-generated step {idx+1}", "status": "pending", "order": idx + 1, "completed_at": None, "auto_generated": True})
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
async def update_inbox_details(inbox_id: str, req: UpdateInboxDetailsRequest):
    """Allow user to edit AI-extracted entities and suggested action before approving."""
    item = await inbox_col.find_one({"inbox_id": inbox_id})
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
async def approve_with_overrides(inbox_id: str, req: ApproveWithOverridesRequest):
    """Approve an action with optional manual overrides for details."""
    item = await inbox_col.find_one({"inbox_id": inbox_id})
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not item.get("ai_suggested_action"):
        raise HTTPException(status_code=400, detail="No action to approve")
    
    action = item["ai_suggested_action"]
    action_type = action["type"]
    entities = item.get("ai_intent", {}).get("entities", {})
    results = []
    
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
        }
        await agents_col.insert_one(agent)
        for idx, title in enumerate(["Complete compliance training", "Set up CRM profile", "Configure email signature", "Schedule orientation with team lead", "Access granted to listing portal"]):
            await onboarding_col.insert_one({"task_id": str(uuid.uuid4()), "agent_id": agent["agent_id"], "title": title, "description": f"Auto-generated step {idx+1}", "status": "pending", "order": idx + 1, "completed_at": None, "auto_generated": True})
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
async def get_calendar_events():
    events = await calendar_col.find({}).sort("start_time", 1).to_list(100)
    return [serialize_doc(e) for e in events]

@app.post("/api/calendar", status_code=201)
async def create_calendar_event(req: CreateEventRequest):
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
    }
    await calendar_col.insert_one(event)
    await log_activity("calendar", "Event created", f"New event: {req.title}", event["event_id"], "calendar")
    return serialize_doc(event)

@app.delete("/api/calendar/{event_id}")
async def delete_calendar_event(event_id: str):
    result = await calendar_col.delete_one({"event_id": event_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True}

# ─── Contacts / CRM ───────────────────────────────────────────────────
@app.get("/api/contacts")
async def get_contacts(lifecycle_stage: Optional[str] = None):
    query = {}
    if lifecycle_stage:
        query["lifecycle_stage"] = lifecycle_stage
    contacts = await contacts_col.find(query).sort("updated_at", -1).to_list(100)
    return [serialize_doc(c) for c in contacts]

@app.get("/api/contacts/{contact_id}")
async def get_contact(contact_id: str):
    contact = await contacts_col.find_one({"contact_id": contact_id})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Get related inbox items
    inbox_items = await inbox_col.find({"contact_id": contact_id}).sort("received_at", -1).to_list(10)
    # Get related events
    events = await calendar_col.find({"contact_id": contact_id}).sort("start_time", -1).to_list(10)
    # Get related activity
    activities = await activity_col.find({"related_id": contact_id}).sort("timestamp", -1).to_list(20)
    
    result = serialize_doc(contact)
    result["inbox_items"] = [serialize_doc(i) for i in inbox_items]
    result["events"] = [serialize_doc(e) for e in events]
    result["activities"] = [serialize_doc(a) for a in activities]
    return result

@app.post("/api/contacts")
async def create_contact(req: CreateContactRequest):
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
    }
    await contacts_col.insert_one(contact)
    await log_activity("crm", "Contact created", f"New contact: {req.name}", contact["contact_id"], "contact")
    return serialize_doc(contact)

# ─── Agents ────────────────────────────────────────────────────────────
@app.get("/api/agents")
async def get_agents():
    agents = await agents_col.find({}).sort("created_at", -1).to_list(100)
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
async def create_agent(req: CreateAgentRequest):
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
async def update_onboarding_task(task_id: str, req: UpdateOnboardingTaskRequest):
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
async def get_content(content_type: Optional[str] = None):
    query = {}
    if content_type:
        query["type"] = content_type
    items = await content_col.find(query).sort("created_at", -1).to_list(100)
    return [serialize_doc(i) for i in items]

@app.post("/api/content/generate")
async def generate_content(req: ContentGenerateRequest):
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"content-{uuid.uuid4().hex[:8]}",
        system_message=CONTENT_SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4o")
    
    response = await chat.send_message(UserMessage(text=req.prompt))
    ai_result = await parse_ai_json(response)
    
    if not ai_result:
        raise HTTPException(status_code=500, detail="AI failed to generate valid content")
    
    items_created = []
    
    if req.type in ["social_post", "both"] and "social_post" in ai_result:
        social_item = {
            "content_id": str(uuid.uuid4()),
            "type": "social_post",
            "title": req.prompt[:80],
            "content": ai_result["social_post"],
            "status": "draft",
            "created_at": now_iso(),
            "created_by": "ai",
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
        }
        await content_col.insert_one(email_item)
        items_created.append(serialize_doc(email_item))
    
    await log_activity("content", "Content generated", f"AI generated {len(items_created)} content item(s)", None, "content")
    
    return {"success": True, "items": items_created}

@app.delete("/api/content/{content_id}")
async def delete_content(content_id: str):
    result = await content_col.delete_one({"content_id": content_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"success": True}

# ─── Activity Feed ─────────────────────────────────────────────────────
@app.get("/api/activity")
async def get_activity(limit: int = Query(default=20, le=100), event_type: Optional[str] = None):
    query = {}
    if event_type:
        query["event_type"] = event_type
    events = await activity_col.find(query).sort("timestamp", -1).to_list(limit)
    return [serialize_doc(e) for e in events]

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
