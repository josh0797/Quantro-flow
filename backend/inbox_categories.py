"""Industry-aware inbox categories.

Every workspace classifies its incoming mail against ONE category list,
picked from its business profile's ``industry``: a real-estate agency gets
"Agendar visita", "Oferta o negociación"…, a store gets "Estado de pedido",
"Devolución o reembolso"…, and never the other's categories. Industries we
have no list for (or none chosen yet) use the GENERIC list.

This module is the single source of truth for those lists:

* ``build_prompt_block`` — the text the triage prompt embeds (only the
  workspace's own list, keys + descriptions for the model);
* ``category_fields`` — validates the model's answer (a key outside the
  list becomes ``otro``) and builds the fields stored on the inbox item;
* ``public_payload`` — what ``GET /api/inbox/categories`` serves the UI
  (keys + ES/EN labels, no model descriptions).

Keys are stable identifiers stored on inbox rows (``ai_category``): rename a
label freely, never a key. Every list ends with ``spam_promocion`` and
``otro`` (the fallback).

``suggested_action`` is the usual Flow action type for the category (one of
the types the analyze prompt already knows: schedule_meeting, create_contact,
send_follow_up, start_onboarding, flag_review, ignore) or ``None``. It is
only a hint in the prompt; the model's own ``suggested_action`` still drives
policies and auto-execution exactly as before.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

GENERIC = "generic"
FALLBACK_CATEGORY = "otro"

# Industry values that mean "not chosen yet" (new workspaces are seeded with
# "other"; see onboardingGate.js on the frontend).
_UNSET_INDUSTRIES = frozenset({"", "other", "otro", "none", "unknown", "n_a"})

# Action types the analyze prompt can suggest (see build_intent_prompt).
ACTION_TYPES = frozenset({
    "schedule_meeting", "create_contact", "send_follow_up",
    "start_onboarding", "flag_review", "ignore",
})


def _cat(key: str, label_es: str, label_en: str, description: str,
         suggested_action: Optional[str] = None) -> Dict[str, Any]:
    if suggested_action is not None and suggested_action not in ACTION_TYPES:
        raise ValueError(f"unknown action type {suggested_action!r} for category {key!r}")
    return {
        "key": key,
        "label_es": label_es,
        "label_en": label_en,
        "description": description,
        "suggested_action": suggested_action,
    }


# Shared tail of every list.
_SPAM = _cat(
    "spam_promocion", "Spam / promoción", "Spam / promotion",
    "Unsolicited marketing, promotions, cold sales pitches, phishing or spam.",
    "ignore",
)
_OTHER = _cat(
    FALLBACK_CATEGORY, "Otro", "Other",
    "Anything that does not clearly fit any category above.",
)

CATEGORY_SETS: Dict[str, Dict[str, Any]] = {
    "real_estate": {
        "label_es": "Bienes raíces",
        "label_en": "Real estate",
        "business_context": "real estate (property sales, rentals and brokerage)",
        "asset_hint": "property address or listing",
        "categories": [
            _cat("agendar_visita", "Agendar visita", "Schedule a viewing",
                 "The sender wants to schedule, confirm, reschedule or cancel a visit, viewing "
                 "or showing of a property (house, apartment, land, office) or an open house.",
                 "schedule_meeting"),
            _cat("info_propiedad", "Información de propiedad", "Property inquiry",
                 "Asks for details about a property or listing: price, availability, features, "
                 "location, photos, or similar properties.",
                 "create_contact"),
            _cat("captar_propiedad", "Vender o rentar su propiedad", "List a property",
                 "An owner wants the agency to sell or rent out their property "
                 "(listing request, valuation, commission).",
                 "schedule_meeting"),
            _cat("oferta_negociacion", "Oferta o negociación", "Offer / negotiation",
                 "Makes, counters, follows up on or negotiates an offer or the terms of a "
                 "purchase or lease.",
                 "send_follow_up"),
            _cat("credito_documentacion", "Crédito hipotecario / documentación", "Mortgage / paperwork",
                 "Mortgage or home loan (bank, Infonavit, Fovissste), appraisal, notary, deeds "
                 "or documents required for a property transaction.",
                 "send_follow_up"),
            _cat("renta_mantenimiento", "Renta y mantenimiento", "Rental & maintenance",
                 "Tenants or landlords about an active lease: rent payment, renewal, deposit, "
                 "repairs or maintenance requests.",
                 "flag_review"),
            _cat("postventa", "Seguimiento postventa", "After-sale follow-up",
                 "Follow-up after a closed sale or signed lease: key handover, post-sale issues, "
                 "referrals or feedback.",
                 "send_follow_up"),
            _SPAM,
            _OTHER,
        ],
    },
    "retail": {
        "label_es": "Comercio / e-commerce",
        "label_en": "Retail / e-commerce",
        "business_context": "retail and e-commerce (a store selling products online and/or in person)",
        "asset_hint": "order number or product",
        "categories": [
            _cat("estado_pedido", "Estado de pedido", "Order status",
                 "Asks where an order is, for tracking, about a shipping delay or the delivery date.",
                 "send_follow_up"),
            _cat("pedido_entregado", "Pedido entregado / confirmación", "Order delivered / confirmation",
                 "Order, shipping or delivery confirmations and notifications, or the customer "
                 "confirming they received the order."),
            _cat("devolucion_reembolso", "Devolución o reembolso", "Return or refund",
                 "Wants to return a product or get a refund, or asks about the return policy or "
                 "the status of a refund.",
                 "flag_review"),
            _cat("cambio_producto", "Cambio de producto", "Exchange",
                 "Wants to exchange a product for another size, color or model, or received the "
                 "wrong item.",
                 "flag_review"),
            _cat("reclamo_garantia", "Reclamo o garantía", "Complaint / warranty",
                 "Complaint about a damaged, defective or missing product or about the service, "
                 "or a warranty claim.",
                 "flag_review"),
            _cat("pago_factura", "Pago o factura", "Payment / invoice",
                 "Payment problems, charges, payment confirmations or invoice (factura / CFDI) "
                 "requests.",
                 "send_follow_up"),
            _cat("disponibilidad_producto", "Disponibilidad de producto", "Product availability",
                 "Asks whether a product, size, color or quantity is in stock, about prices, or "
                 "wants to place a new or wholesale order.",
                 "create_contact"),
            _SPAM,
            _OTHER,
        ],
    },
    "hospitality": {
        "label_es": "Restaurantes / hospitalidad",
        "label_en": "Restaurants / hospitality",
        "business_context": "restaurants and hospitality (restaurant, café, bar or hotel)",
        "asset_hint": "reservation date and party size, or order",
        "categories": [
            _cat("reservacion", "Reservación", "Reservation",
                 "Wants to book, confirm, change or cancel a table, room or stay reservation.",
                 "schedule_meeting"),
            _cat("pedido_domicilio", "Pedido a domicilio / para llevar", "Delivery / takeout order",
                 "Places or asks about a delivery or takeout order, the menu or an order's status.",
                 "send_follow_up"),
            _cat("evento_catering", "Evento o catering", "Event / catering",
                 "Asks for a quote or information for a private event, group booking, banquet "
                 "or catering.",
                 "create_contact"),
            _cat("queja", "Queja", "Complaint",
                 "Complaint about the food, the service, a stay or a bad experience.",
                 "flag_review"),
            _cat("factura_pago", "Factura o pago", "Invoice / payment",
                 "Invoice (factura / CFDI) requests for a consumption, or payment and charge "
                 "questions.",
                 "send_follow_up"),
            _SPAM,
            _OTHER,
        ],
    },
    "professional_services": {
        "label_es": "Servicios profesionales / agencia",
        "label_en": "Professional services / agency",
        "business_context": "professional services (consulting, agency, legal, accounting or similar)",
        "asset_hint": "project or service",
        "categories": [
            _cat("solicitud_cotizacion", "Solicitud de cotización", "Quote request",
                 "A prospect asks for a quote, proposal, pricing or scope for a service or project.",
                 "create_contact"),
            _cat("agendar_reunion", "Agendar reunión", "Schedule a meeting",
                 "Wants to schedule, confirm, move or cancel a call or meeting (discovery call, "
                 "consultation, review).",
                 "schedule_meeting"),
            _cat("seguimiento_proyecto", "Seguimiento de proyecto", "Project follow-up",
                 "An existing client asks about the progress, deliverables, feedback, changes or "
                 "deadlines of an ongoing project or engagement.",
                 "send_follow_up"),
            _cat("facturacion_cobranza", "Facturación / cobranza", "Billing / collections",
                 "Invoices, payments, outstanding balances, payment reminders or billing questions.",
                 "send_follow_up"),
            _SPAM,
            _OTHER,
        ],
    },
    "healthcare": {
        "label_es": "Salud / clínica",
        "label_en": "Healthcare / clinic",
        "business_context": "healthcare (clinic, medical or dental practice)",
        "asset_hint": "appointment or service",
        "categories": [
            _cat("agendar_cita", "Agendar cita", "Book an appointment",
                 "A patient wants to book a new appointment or consultation.",
                 "schedule_meeting"),
            _cat("cambio_cita", "Cambiar o cancelar cita", "Reschedule / cancel appointment",
                 "Wants to confirm, reschedule or cancel an existing appointment.",
                 "flag_review"),
            _cat("resultados_estudios", "Resultados / estudios", "Results / tests",
                 "Asks for or sends lab results, imaging, studies, prescriptions or medical reports.",
                 "flag_review"),
            _cat("seguros_facturacion", "Seguros / facturación", "Insurance / billing",
                 "Insurance coverage, pre-authorizations, payments or invoices.",
                 "send_follow_up"),
            _SPAM,
            _OTHER,
        ],
    },
    "education": {
        "label_es": "Educación",
        "label_en": "Education",
        "business_context": "education (school, university, academy or training center)",
        "asset_hint": "program, course or student",
        "categories": [
            _cat("inscripcion_admisiones", "Inscripción / admisiones", "Enrollment / admissions",
                 "A prospective student or parent asks about admissions, enrollment, programs, "
                 "requirements, campus tours or scholarships.",
                 "create_contact"),
            _cat("pagos_colegiaturas", "Pagos / colegiaturas", "Payments / tuition",
                 "Tuition, fees, payment plans, receipts or invoices.",
                 "send_follow_up"),
            _cat("seguimiento_academico", "Seguimiento académico", "Academic follow-up",
                 "Grades, attendance, a student's progress, or a request to meet a teacher.",
                 "schedule_meeting"),
            _cat("calendario_avisos", "Calendario / avisos", "Calendar / notices",
                 "School calendar, schedules, events, closures, announcements or general notices."),
            _SPAM,
            _OTHER,
        ],
    },
    "manufacturing": {
        "label_es": "Manufactura / distribución B2B",
        "label_en": "Manufacturing / B2B distribution",
        "business_context": "manufacturing and B2B distribution (selling to other businesses)",
        "asset_hint": "product, SKU or order number",
        "categories": [
            _cat("solicitud_cotizacion", "Solicitud de cotización", "Quote request",
                 "A business customer asks for a quote, price list, samples or lead times.",
                 "create_contact"),
            _cat("orden_compra", "Orden de compra", "Purchase order",
                 "A customer sends, confirms or changes a purchase order (PO) or places an order.",
                 "flag_review"),
            _cat("estado_envio", "Estado de envío / logística", "Shipping / logistics",
                 "Shipment status, tracking, delivery schedules, freight or logistics coordination.",
                 "send_follow_up"),
            _cat("cuentas_cobrar_pagar", "Cuentas por cobrar / pagar", "Receivables / payables",
                 "Invoices, payments, account statements, credit terms, collections or remittances.",
                 "send_follow_up"),
            _cat("proveedor", "Proveedor", "Supplier",
                 "Messages from suppliers or vendors: raw materials, their quotes, price changes "
                 "or their deliveries.",
                 "flag_review"),
            _SPAM,
            _OTHER,
        ],
    },
    "software": {
        "label_es": "Software / SaaS",
        "label_en": "Software / SaaS",
        "business_context": "software and SaaS (a technology product sold by subscription or license)",
        "asset_hint": "product, plan or account",
        "categories": [
            _cat("soporte_tecnico", "Soporte técnico", "Technical support",
                 "A user reports a bug, error or outage, or asks how to use the product.",
                 "flag_review"),
            _cat("solicitud_demo", "Solicitud de demo", "Demo request",
                 "A prospect asks for a demo, a trial, pricing or a sales call.",
                 "schedule_meeting"),
            _cat("facturacion_suscripcion", "Facturación / suscripción", "Billing / subscription",
                 "Invoices, charges, plan changes, upgrades, renewals or payment-method issues.",
                 "send_follow_up"),
            _cat("cancelacion", "Cancelación", "Cancellation",
                 "Wants to cancel, downgrade or not renew a subscription, or asks to delete "
                 "their account.",
                 "flag_review"),
            _SPAM,
            _OTHER,
        ],
    },
    GENERIC: {
        "label_es": "General",
        "label_en": "General",
        "business_context": "general business operations",
        "asset_hint": "product or service",
        "categories": [
            _cat("nuevo_cliente", "Nuevo cliente / venta", "New customer / sale",
                 "A potential customer asks about products or services or prices, or wants to "
                 "buy or hire.",
                 "create_contact"),
            _cat("agendar_reunion", "Agendar reunión", "Schedule a meeting",
                 "Wants to schedule, confirm, move or cancel a call, meeting or appointment.",
                 "schedule_meeting"),
            _cat("soporte_cliente", "Soporte a cliente", "Customer support",
                 "An existing customer needs help or has a problem, complaint or question.",
                 "flag_review"),
            _cat("facturacion_pagos", "Facturación / pagos", "Billing / payments",
                 "Invoices, payments, charges, receipts or collections.",
                 "send_follow_up"),
            _cat("proveedor", "Proveedor", "Supplier",
                 "Messages from suppliers or vendors: their quotes, orders, deliveries or invoices.",
                 "flag_review"),
            _cat("interno_equipo", "Interno / equipo", "Internal / team",
                 "Messages from colleagues or about internal operations, HR or team coordination."),
            _cat("newsletter", "Newsletter / notificaciones", "Newsletter / notifications",
                 "Newsletters, automated notifications and updates from services the business "
                 "subscribed to.",
                 "ignore"),
            _SPAM,
            _OTHER,
        ],
    },
}

# Industry values the UI stores (Settings → Business Profile, the Welcome
# flow, onboarding_lite's list) plus common free-text spellings, normalised
# by ``_norm`` → the category list they use. Anything else → GENERIC.
_ALIASES: Dict[str, Tuple[str, ...]] = {
    "real_estate": (
        "real_estate", "realestate", "bienes_raices", "inmobiliaria", "inmobiliario",
        "inmobiliarias", "property", "properties", "realty", "brokerage",
    ),
    "retail": (
        "retail", "ecommerce", "e_commerce", "commerce", "comercio", "comercio_minorista",
        "comercio_electronico", "tienda", "tienda_en_linea", "store", "shop", "online_store",
    ),
    "hospitality": (
        "hospitality", "hospitalidad", "hospitalidad_restaurantes", "restaurant", "restaurants",
        "restaurante", "restaurantes", "hotel", "hotels", "hoteles", "food_and_beverage",
        "food_beverage", "alimentos_y_bebidas",
    ),
    "professional_services": (
        "professional_services", "servicios_profesionales", "consulting", "consultoria",
        "consultancy", "agency", "agencia", "marketing", "marketing_agencia", "legal", "law",
        "despacho", "finance", "finanzas", "finanzas_seguros", "insurance", "seguros",
        "accounting", "contabilidad", "construction", "construccion",
    ),
    "healthcare": (
        "healthcare", "health", "health_care", "salud", "salud_clinicas", "clinic", "clinica",
        "clinicas", "medical", "medico", "dental", "hospital",
    ),
    "education": (
        "education", "educacion", "school", "escuela", "colegio", "university", "universidad",
        "academy", "academia", "training", "capacitacion",
    ),
    "manufacturing": (
        "manufacturing", "manufactura", "distribution", "distribucion", "distributor",
        "distribuidora", "wholesale", "mayoreo", "logistics", "logistica", "b2b", "industrial",
        "agriculture", "agricultura",
    ),
    "software": (
        "software", "saas", "technology", "tecnologia", "tecnologia_software", "tech", "it",
    ),
}
INDUSTRY_ALIASES: Dict[str, str] = {
    alias: set_key for set_key, aliases in _ALIASES.items() for alias in aliases
}


def _norm(value: Any) -> str:
    """'Bienes Raíces' / 'real-estate' / ' REAL_ESTATE ' → 'bienes_raices' / 'real_estate'."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def has_industry(industry: Any) -> bool:
    """False while the workspace has not chosen its line of business."""
    return _norm(industry) not in _UNSET_INDUSTRIES


def resolve_category_set(industry: Any) -> str:
    """The category-list key a business-profile ``industry`` value uses."""
    return INDUSTRY_ALIASES.get(_norm(industry), GENERIC)


def get_category_set(industry: Any) -> Dict[str, Any]:
    return CATEGORY_SETS[resolve_category_set(industry)]


def categories_for(industry: Any) -> List[Dict[str, Any]]:
    return get_category_set(industry)["categories"]


def allowed_keys(industry: Any) -> List[str]:
    return [c["key"] for c in categories_for(industry)]


def build_prompt_block(industry: Any) -> str:
    """Category instructions for the triage prompt — this industry's list only."""
    lines = []
    for c in categories_for(industry):
        hint = f" (usual action: {c['suggested_action']})" if c["suggested_action"] else ""
        lines.append(f"- {c['key']}: {c['description']}{hint}")
    return (
        "Also assign the message exactly ONE category from this business's own list below. "
        "These keys are the only valid categories for this business; copy the key exactly as "
        f'written (never translate it). If none fits, use "{FALLBACK_CATEGORY}".\n'
        "Categories:\n" + "\n".join(lines)
    )


def category_json_hint(industry: Any) -> str:
    """The ``"category"`` placeholder for the prompt's JSON template."""
    return "|".join(allowed_keys(industry))


def normalize_category(value: Any, industry: Any) -> Tuple[str, bool]:
    """(key, valid) for the model's answer. Unknown values → ('otro', False).

    Accepts the key itself in any case/spacing, or one of the category's
    labels (models sometimes answer with the label instead of the key).
    """
    raw = _norm(value)
    if not raw:
        return FALLBACK_CATEGORY, False
    for c in categories_for(industry):
        if raw in (c["key"], _norm(c["label_es"]), _norm(c["label_en"])):
            return c["key"], True
    return FALLBACK_CATEGORY, False


def _confidence(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(min(max(f, 0.0), 1.0), 3)


def category_fields(ai_result: Any, industry: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Inbox-item fields for the model's answer (validated against the list).

    ``ai_category_confidence`` is the model's ``category_confidence``
    (falls back to the intent ``confidence``), and 0.0 when the category
    had to be replaced by ``otro``.
    """
    result = ai_result if isinstance(ai_result, Mapping) else {}
    key, valid = normalize_category(result.get("category"), industry)
    confidence = 0.0
    if valid:
        confidence = _confidence(result.get("category_confidence"))
        if confidence is None:
            confidence = _confidence(result.get("confidence"))
        if confidence is None:
            confidence = 0.0
    return {
        "ai_category": key,
        "ai_category_confidence": confidence,
        "ai_category_set": resolve_category_set(industry),
        "ai_categorized_at": now or datetime.utcnow(),
    }


def public_payload(industry: Any) -> Dict[str, Any]:
    """What the inbox UI needs: this workspace's list with ES/EN labels."""
    set_key = resolve_category_set(industry)
    spec = CATEGORY_SETS[set_key]
    return {
        "industry": industry if isinstance(industry, str) else None,
        "has_industry": has_industry(industry),
        "category_set": set_key,
        "label_es": spec["label_es"],
        "label_en": spec["label_en"],
        "categories": [
            {
                "key": c["key"],
                "label_es": c["label_es"],
                "label_en": c["label_en"],
                "suggested_action": c["suggested_action"],
            }
            for c in spec["categories"]
        ],
    }
