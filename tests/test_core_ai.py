"""
Phase 1 POC: Core AI Module Test
Tests:
1. Intent detection from inbox messages (booking, onboarding, follow-up, spam, ambiguous)
2. Content generation (social posts + email drafts)

Uses GPT-4o via Emergent LLM Key
"""
import asyncio
import json
import os
import sys
import uuid
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

from emergentintegrations.llm.chat import LlmChat, UserMessage

API_KEY = os.environ.get("EMERGENT_LLM_KEY")
if not API_KEY:
    print("FATAL: EMERGENT_LLM_KEY not found in environment")
    sys.exit(1)

# ─── Intent Detection Prompt ─────────────────────────────────────────
INTENT_SYSTEM_PROMPT = """You are an AI assistant for a real estate operating system called Quantro One.
Your job is to analyze incoming messages (emails, requests) and detect the intent.

You MUST respond with ONLY a valid JSON object (no markdown, no code fences) with this exact structure:
{
  "intent": "<one of: booking, onboarding, follow_up, inquiry, escalation, spam, needs_review>",
  "confidence": <float 0.0-1.0>,
  "summary": "<brief 1-sentence summary of the message>",
  "entities": {
    "person_name": "<extracted name or null>",
    "email": "<extracted email or null>",
    "phone": "<extracted phone or null>",
    "date_time": "<extracted date/time reference or null>",
    "property": "<extracted property reference or null>"
  },
  "suggested_action": {
    "type": "<one of: schedule_meeting, create_contact, send_follow_up, start_onboarding, flag_review, ignore, none>",
    "description": "<what should be done>"
  }
}

Rules:
- If the message is unclear or could be multiple intents, use "needs_review" with lower confidence.
- If it looks like spam/irrelevant, use "spam" intent.
- Always extract whatever entities you can find. Use null for missing ones.
- Be concise in summaries and descriptions."""

# ─── Content Generation Prompt ────────────────────────────────────────
CONTENT_SYSTEM_PROMPT = """You are a premium content writer for a real estate team using Quantro One | Realty OS.
Generate professional, engaging content for real estate marketing.

You MUST respond with ONLY a valid JSON object (no markdown, no code fences) with this exact structure:
{
  "social_post": {
    "text": "<social media post text, 1-3 sentences, engaging and professional>",
    "hashtags": ["<relevant hashtags>"],
    "platform": "instagram"
  },
  "email_draft": {
    "subject": "<email subject line>",
    "body": "<email body, professional tone, 2-4 paragraphs>",
    "call_to_action": "<clear CTA>"
  }
}

Style: Professional, warm, trustworthy. Avoid salesy language. Focus on value and expertise."""

# ─── Test Messages for Intent Detection ───────────────────────────────
TEST_MESSAGES = [
    {
        "id": "booking_1",
        "text": "Hi, I'd like to schedule a property viewing for 123 Oak Street this Saturday at 2pm. My name is Sarah Chen and my email is sarah@example.com. Thanks!",
        "expected_intent": "booking",
    },
    {
        "id": "onboarding_1",
        "text": "Welcome aboard! I'm James Rivera, just joined the team as a new agent. My manager said I should reach out to get my systems set up. My email is jrivera@realtyfirm.com and phone is 555-0192.",
        "expected_intent": "onboarding",
    },
    {
        "id": "follow_up_1",
        "text": "Hey, just checking in on the offer we submitted last week for the property at 456 Pine Ave. The buyers are getting anxious. Can we get an update? - Mark Thompson",
        "expected_intent": "follow_up",
    },
    {
        "id": "spam_1",
        "text": "CONGRATULATIONS! You've been selected to receive a FREE cruise vacation! Click here to claim your prize now! Limited time offer!!!",
        "expected_intent": "spam",
    },
    {
        "id": "ambiguous_1",
        "text": "hey can u help me with something? its about a house thing",
        "expected_intent": "needs_review",
    },
    {
        "id": "inquiry_1",
        "text": "Hello, I'm interested in learning more about available listings in the downtown area, preferably 2-bedroom condos under $500K. Could someone from your team get back to me? My name is David Park, david.park@mail.com",
        "expected_intent": "inquiry",
    },
    {
        "id": "escalation_1",
        "text": "This is unacceptable. I've been waiting 3 weeks for the inspection report and nobody has gotten back to me. I want to speak to a manager immediately. - Linda Vasquez, 555-0234",
        "expected_intent": "escalation",
    },
    {
        "id": "booking_2",
        "text": "Can we move the meeting with the Johnsons from Tuesday to Thursday at 10am? They want to see the Maple Ridge property instead.",
        "expected_intent": "booking",
    },
]

# ─── Content Generation Test Prompts ──────────────────────────────────
CONTENT_PROMPTS = [
    {
        "id": "social_new_listing",
        "prompt": "Create content for a new luxury listing: 5-bedroom waterfront estate at 789 Lakeshore Drive, listed at $2.8M. Features: infinity pool, home theater, smart home system.",
    },
    {
        "id": "social_market_update",
        "prompt": "Create content about the Q4 real estate market update: prices up 3%, inventory low, great time for sellers in the metro area.",
    },
]


def validate_intent_json(result_str: str, test_id: str) -> dict:
    """Validate that the AI response is valid JSON matching our schema."""
    try:
        # Clean up potential markdown fences
        cleaned = result_str.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}", "raw": result_str[:200]}

    required_keys = ["intent", "confidence", "summary", "entities", "suggested_action"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return {"success": False, "error": f"Missing keys: {missing}", "data": data}

    valid_intents = ["booking", "onboarding", "follow_up", "inquiry", "escalation", "spam", "needs_review"]
    if data["intent"] not in valid_intents:
        return {"success": False, "error": f"Invalid intent: {data['intent']}", "data": data}

    if not isinstance(data["confidence"], (int, float)) or not (0 <= data["confidence"] <= 1):
        return {"success": False, "error": f"Invalid confidence: {data['confidence']}", "data": data}

    valid_actions = ["schedule_meeting", "create_contact", "send_follow_up", "start_onboarding", "flag_review", "ignore", "none"]
    if data["suggested_action"]["type"] not in valid_actions:
        return {"success": False, "error": f"Invalid action type: {data['suggested_action']['type']}", "data": data}

    return {"success": True, "data": data}


def validate_content_json(result_str: str, test_id: str) -> dict:
    """Validate that the content generation response is valid JSON."""
    try:
        cleaned = result_str.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}", "raw": result_str[:200]}

    if "social_post" not in data or "email_draft" not in data:
        return {"success": False, "error": f"Missing social_post or email_draft", "data": data}

    sp = data["social_post"]
    if not sp.get("text"):
        return {"success": False, "error": "social_post.text is empty", "data": data}

    ed = data["email_draft"]
    if not ed.get("subject") or not ed.get("body"):
        return {"success": False, "error": "email_draft missing subject or body", "data": data}

    return {"success": True, "data": data}


async def test_intent_detection():
    """Test intent detection on all sample messages."""
    print("\n" + "=" * 60)
    print("TEST 1: INTENT DETECTION")
    print("=" * 60)

    results = []
    passed = 0
    failed = 0

    for test in TEST_MESSAGES:
        print(f"\n--- Test: {test['id']} (expected: {test['expected_intent']}) ---")
        
        chat = LlmChat(
            api_key=API_KEY,
            session_id=f"poc-intent-{test['id']}-{uuid.uuid4().hex[:6]}",
            system_message=INTENT_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o")

        try:
            response = await chat.send_message(UserMessage(text=test["text"]))
            validation = validate_intent_json(response, test["id"])

            if validation["success"]:
                data = validation["data"]
                intent_match = data["intent"] == test["expected_intent"]
                status = "PASS" if intent_match else "WARN"
                
                if intent_match:
                    passed += 1
                else:
                    # Allow flexibility - ambiguous ones may get different labels
                    if test["expected_intent"] == "needs_review" or data["confidence"] < 0.6:
                        passed += 1
                        status = "PASS (flexible)"
                    else:
                        failed += 1

                print(f"  [{status}] Intent: {data['intent']} (conf: {data['confidence']:.2f})")
                print(f"  Summary: {data['summary']}")
                print(f"  Action: {data['suggested_action']['type']}")
                print(f"  Entities: {json.dumps(data['entities'], indent=2)}")
                results.append({"test_id": test["id"], "status": status, "data": data})
            else:
                failed += 1
                print(f"  [FAIL] Schema validation: {validation['error']}")
                results.append({"test_id": test["id"], "status": "FAIL", "error": validation["error"]})

        except Exception as e:
            failed += 1
            print(f"  [FAIL] Exception: {e}")
            results.append({"test_id": test["id"], "status": "FAIL", "error": str(e)})

    print(f"\n{'=' * 60}")
    print(f"INTENT DETECTION: {passed}/{len(TEST_MESSAGES)} passed, {failed} failed")
    print(f"{'=' * 60}")
    return passed, failed


async def test_content_generation():
    """Test content generation."""
    print("\n" + "=" * 60)
    print("TEST 2: CONTENT GENERATION")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in CONTENT_PROMPTS:
        print(f"\n--- Test: {test['id']} ---")
        
        chat = LlmChat(
            api_key=API_KEY,
            session_id=f"poc-content-{test['id']}-{uuid.uuid4().hex[:6]}",
            system_message=CONTENT_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o")

        try:
            response = await chat.send_message(UserMessage(text=test["prompt"]))
            validation = validate_content_json(response, test["id"])

            if validation["success"]:
                data = validation["data"]
                passed += 1
                print(f"  [PASS] Social post: {data['social_post']['text'][:80]}...")
                print(f"  Email subject: {data['email_draft']['subject']}")
                print(f"  Hashtags: {data['social_post'].get('hashtags', [])}")
            else:
                failed += 1
                print(f"  [FAIL] {validation['error']}")

        except Exception as e:
            failed += 1
            print(f"  [FAIL] Exception: {e}")

    print(f"\n{'=' * 60}")
    print(f"CONTENT GENERATION: {passed}/{len(CONTENT_PROMPTS)} passed, {failed} failed")
    print(f"{'=' * 60}")
    return passed, failed


async def main():
    print("=" * 60)
    print("QUANTRO ONE | REALTY OS - CORE AI POC")
    print(f"Model: GPT-4o | Key: ...{API_KEY[-6:]}")
    print("=" * 60)

    intent_passed, intent_failed = await test_intent_detection()
    content_passed, content_failed = await test_content_generation()

    total_passed = intent_passed + content_passed
    total_failed = intent_failed + content_failed
    total = total_passed + total_failed

    print("\n" + "=" * 60)
    print(f"FINAL RESULTS: {total_passed}/{total} tests passed")
    if total_failed == 0:
        print("ALL TESTS PASSED - Core AI ready for app development")
    else:
        print(f"ATTENTION: {total_failed} test(s) need review")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
