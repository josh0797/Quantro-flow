"""
Registers every Action definition. Called once at server startup
(see server.py's lifespan). Risk levels follow the task spec's own
examples verbatim: read/list -> low, internal creates -> low, an
Action that reaches a real external system (send an email, create a
calendar event on Google/Microsoft) -> medium, issuing a CFDI -> high,
cancelling one -> critical.
"""
from __future__ import annotations

from .base import ActionDefinition, RiskLevel
from .handlers import quantro_invoicing as quantro_invoicing_handlers
from .handlers import google as google_handlers
from .handlers import microsoft as microsoft_handlers
from .handlers import quantro_internal as quantro_handlers
from .registry import register_action

_STR = {"type": "string"}
_STR_REQ = {"type": "string", "required": True}
_NUM_REQ = {"type": "number", "required": True}
_ARR_REQ = {"type": "array", "required": True}
_OBJ_REQ = {"required": True}  # customer/address can be either an object or an id string per Facturapi's API
_ANY = {}


def register_all_actions() -> None:
    # ── Quantro Internal ────────────────────────────────────────────
    register_action(ActionDefinition(
        action_id="quantro.calendar.event.create", provider="quantro_internal",
        name="Create calendar event", description="Create an event on Quantro's internal calendar.",
        input_schema={"title": _STR_REQ, "description": _STR, "start_time": _STR, "end_time": _STR,
                      "location": _STR, "attendees": {"type": "array"}, "contact_id": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.calendar_event_create, idempotent=True, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro.crm.contact.create", provider="quantro_internal",
        name="Create contact", description="Create a contact in Quantro's internal CRM.",
        input_schema={"name": _STR_REQ, "email": _STR, "phone": _STR, "notes": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.crm_contact_create, idempotent=True, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro.onboarding.start", provider="quantro_internal",
        name="Start onboarding", description="Create an agent and its default onboarding checklist.",
        input_schema={"name": _STR_REQ, "email": _STR, "phone": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.onboarding_start, idempotent=True, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro.followup.send", provider="quantro_internal",
        name="Queue follow-up", description="Queue a follow-up on an inbox item.",
        input_schema={"recipient_name": _STR, "related_id": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.followup_send, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro.review.flag", provider="quantro_internal",
        name="Flag for review", description="Flag an inbox item for manual review.",
        input_schema={"reason": _STR, "related_id": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.review_flag, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro.inbox.ignore", provider="quantro_internal",
        name="Ignore", description="Mark an inbox item as ignored (spam/irrelevant).",
        input_schema={"from_name": _STR, "related_id": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_handlers.inbox_ignore, minimum_role="member",
    ))

    # ── Google ───────────────────────────────────────────────────────
    register_action(ActionDefinition(
        action_id="google.gmail.send", provider="google",
        name="Send Gmail", description="Send an email through the connected Gmail account.",
        input_schema={"to": _STR_REQ, "subject": _STR_REQ, "body": _STR},
        risk_level=RiskLevel.MEDIUM, handler=google_handlers.gmail_send,
        required_scopes=["https://www.googleapis.com/auth/gmail.send"], idempotent=True, minimum_role="leader",
    ))
    register_action(ActionDefinition(
        action_id="google.calendar.event.create", provider="google",
        name="Create Google Calendar event", description="Create an event on the connected Google Calendar.",
        input_schema={"title": _STR_REQ, "start_time": _STR_REQ, "end_time": _STR_REQ,
                      "description": _STR, "location": _STR, "attendees": {"type": "array"}},
        risk_level=RiskLevel.MEDIUM, handler=google_handlers.calendar_event_create,
        required_scopes=["https://www.googleapis.com/auth/calendar.events"], idempotent=True, minimum_role="leader",
    ))

    # ── Microsoft ────────────────────────────────────────────────────
    register_action(ActionDefinition(
        action_id="microsoft.mail.send", provider="microsoft",
        name="Send Outlook mail", description="Send an email through the connected Microsoft account.",
        input_schema={"to": _STR_REQ, "subject": _STR_REQ, "body": _STR},
        risk_level=RiskLevel.MEDIUM, handler=microsoft_handlers.mail_send,
        required_scopes=["Mail.Send"], idempotent=True, minimum_role="leader",
    ))
    register_action(ActionDefinition(
        action_id="microsoft.calendar.event.create", provider="microsoft",
        name="Create Outlook Calendar event", description="Create an event on the connected Outlook Calendar.",
        input_schema={"title": _STR_REQ, "start_time": _STR_REQ, "end_time": _STR_REQ,
                      "description": _STR, "location": _STR, "attendees": {"type": "array"}},
        risk_level=RiskLevel.MEDIUM, handler=microsoft_handlers.calendar_event_create,
        required_scopes=["Calendars.ReadWrite"], idempotent=True, minimum_role="leader",
    ))

    # ── Facturación (Quantro OS) ──────────────────────────────────────
    # Flow queries invoices OS already processed; never creates CFDI here.
    register_action(ActionDefinition(
        action_id="quantro_invoicing.invoice.query", provider="quantro_invoicing",
        name="Query invoice", description="Locate an invoice already processed by Quantro OS.",
        input_schema={"q": _STR, "invoice_id": _STR, "limit": {"type": "number"}},
        risk_level=RiskLevel.LOW, handler=quantro_invoicing_handlers.invoice_query,
        idempotent=True, minimum_role="member",
    ))
    register_action(ActionDefinition(
        action_id="quantro_invoicing.invoice.prepare_reply", provider="quantro_invoicing",
        name="Prepare invoice email reply",
        description="Build a Gmail/Outlook reply payload from Quantro OS invoice metadata.",
        input_schema={"invoice_id": _STR, "q": _STR, "to": _STR, "channel": _STR},
        risk_level=RiskLevel.LOW, handler=quantro_invoicing_handlers.invoice_prepare_reply,
        idempotent=True, minimum_role="member",
    ))
