import { supabase } from './supabaseClient';

/**
 * Billing configuration — single source of truth for prices, Stripe price
 * IDs and AI usage limits across Quantro Flow.
 *
 * Source-of-truth principles:
 *   • The numbers below MIRROR exactly what Stripe charges (no math).
 *     If Stripe says $2090/year, this file says $2090/year.
 *   • Limits below MIRROR what the backend enforces (see
 *     /app/backend/billing_limits.py). Keep both files in lock-step.
 */

// ---------- Plan-level pricing (exact Stripe values) ----------
export const PLAN_PRICES = {
  essential: {
    monthly: 59,
    annualTotal: 590,            // exact Stripe annual price
    annualMonthlyDisplay: 49,    // for the "$49 / mo" headline on annual
  },
  pro: {
    monthly: 209,
    annualTotal: 2090,
    annualMonthlyDisplay: 174,
  },
  enterprise: {
    monthly: 499,
    annualTotal: 4990,
    annualMonthlyDisplay: 416,
  },
};

// ---------- AI usage limits (kept in sync with backend) ----------
export const PLAN_LIMITS = {
  essential: 1000,
  pro: 3000,
  enterprise: 15000,
};

// Hard-coded fallback used when no plan applies and the user is not paying.
export const INACTIVE_LIMIT = 0;
// Reduced limit applied when the customer redeemed a coupon / discount.
export const COUPON_LIMIT = 500;
// Internal QA accounts always get the top tier regardless of subscription.
export const TEST_USERS = [
  'josias.martin@hotmail.com',
  'josias.martin90@hotmail.com',
];
export const TEST_USER_LIMIT = 15000;

// ---------- Plans (consumed by PlanSelectorDialog) ----------
export const PLANS = [
  {
    key: 'essential',
    name: 'Essential',
    tagline: 'Claridad + control',
    currency: 'USD',
    priceIds: {
      monthly: 'price_1TL8xMLJrc96wcWHzaaHtUOL',
      annual: 'price_1TPvV7LJrc96wcWHQskYMuGw',
    },
    features: [
      'Quantro OS + Flow + Intelligence incluidos',
      'Inventory Intelligence (NEW)',
      'Dashboard en tiempo real',
      'Scorecard semanal inteligente',
      'To-Dos + seguimiento básico',
      'CRM + Inbox con ejecución automática',
      'AI Coach (limitado)',
      'Automatizaciones básicas',
      'Contabilidad básica',
      'CFDI 4.0',
    ],
    seats: 1,
  },
  {
    key: 'pro',
    name: 'Pro',
    tagline: 'Ejecución + inteligencia',
    currency: 'USD',
    popular: true,
    priceIds: {
      monthly: 'price_1TL9BeLJrc96wcWHTspVOqBT',
      annual: 'price_1TL9BeLJrc96wcWHi8ajKg7L',
    },
    features: [
      'Todo Essential',
      'Agentes IA ejecutando tareas',
      'Quantro Intelligence (análisis continuo)',
      'AI Coach (ilimitado)',
      'Decisiones + plan de acción',
      'Automatizaciones avanzadas',
      'Multiusuario (3 asientos)',
      'Contabilidad avanzada',
    ],
    seats: 3,
  },
  {
    key: 'enterprise',
    name: 'Enterprise',
    tagline: 'Autonomía real',
    currency: 'USD',
    priceIds: {
      monthly: 'price_1TL9HOLJrc96wcWHvp7LTLS2',
      annual: 'price_1TL9HOLJrc96wcWHxt5fDHWe',
    },
    features: [
      'Todo Pro',
      'Motor de decisiones avanzado',
      'Multiusuario (10 asientos)',
      'Lean Management completo',
      'Quantro Revenue',
      'Onboarding dedicado',
      'Soporte prioritario',
      'Agentes personalizados (próximamente)',
      'Integraciones avanzadas (próximamente)',
    ],
    seats: 10,
  },
];

export function getPlanByKey(key) {
  if (!key) return null;
  return PLANS.find((p) => p.key === String(key).toLowerCase()) || null;
}

/**
 * Returns the per-plan price card data merged with the requested billing
 * period. The values come straight from PLAN_PRICES so the UI never
 * computes percentages on its own.
 */
export function getPriceForPlan(planKey, period = 'monthly') {
  const k = String(planKey || '').toLowerCase();
  const plan = PLANS.find((p) => p.key === k);
  const prices = PLAN_PRICES[k];
  if (!plan || !prices) return null;
  return {
    plan,
    period,
    priceId: plan.priceIds[period],
    displayPrice: period === 'annual' ? prices.annualMonthlyDisplay : prices.monthly,
    monthlyPrice: prices.monthly,
    annualMonthlyDisplay: prices.annualMonthlyDisplay,
    annualTotal: prices.annualTotal,
  };
}

/**
 * Subscription state derived purely from the profiles row in Supabase.
 * Drives the CTA wording on PlanAndUsage and the badge colours.
 *
 *   - "active"   : has plan + active stripe subscription
 *   - "trial"    : has plan, no subscription id (post-signup grace period)
 *   - "none"     : brand-new account, no plan
 *   - "past_due" : Stripe webhook flagged the subscription as past_due
 */
export function deriveSubscriptionState(profile) {
  if (!profile) return 'none';
  if (profile.subscription_status === 'past_due') return 'past_due';
  if (profile.subscription_status === 'canceled') return 'none';
  const hasSub = !!(profile.stripe_subscription_id || profile.paypal_subscription_id);
  if (profile.plan && (hasSub || profile.subscription_status === 'active' || profile.subscription_status === 'trialing')) {
    return 'active';
  }
  if (profile.plan) return 'trial';
  return 'none';
}

/**
 * Centralised AI usage limit resolver. Mirrors the backend implementation
 * at /app/backend/billing_limits.py exactly so the UI never advertises a
 * different cap than what the API enforces.
 *
 * Priority (top wins):
 *   1. Email is in TEST_USERS                     → TEST_USER_LIMIT (15000)
 *   2. Subscription not active and not trialing   → INACTIVE_LIMIT (0)
 *   3. profiles.has_coupon === true               → COUPON_LIMIT (500)
 *   4. PLAN_LIMITS[profiles.plan]                 → plan default
 *
 * Returns:
 *   { limit: number, reason: string, blocked: boolean }
 */
export function getOpenAIUsageLimit({ email, profile }) {
  const lcEmail = String(email || '').toLowerCase();
  if (lcEmail && TEST_USERS.includes(lcEmail)) {
    return { limit: TEST_USER_LIMIT, reason: 'test_user', blocked: false };
  }
  const status = profile?.subscription_status;
  const hasActiveStatus = status === 'active' || status === 'trialing';
  const planKey = (profile?.plan || '').toLowerCase();
  // Treat "plan present + no status info yet" as trial-like to avoid
  // accidentally blocking users while Stripe webhook is propagating.
  const planLooksActive = !!planKey && (hasActiveStatus || (!status && !!profile?.stripe_customer_id));

  if (!planLooksActive && !hasActiveStatus) {
    return { limit: INACTIVE_LIMIT, reason: 'no_active_subscription', blocked: true };
  }
  if (profile?.has_coupon === true) {
    return { limit: COUPON_LIMIT, reason: 'coupon_applied', blocked: false };
  }
  if (planKey in PLAN_LIMITS) {
    return { limit: PLAN_LIMITS[planKey], reason: `plan:${planKey}`, blocked: false };
  }
  return { limit: PLAN_LIMITS.essential, reason: 'fallback_essential', blocked: false };
}

// ---------- Edge Function helpers ----------

export async function startCheckout({ priceId, planKey, period = 'monthly' }) {
  if (!priceId) throw new Error('Missing priceId');
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  // Send the parameters in BOTH camelCase and snake_case so we work with
  // whichever convention the deployed Edge Function uses.
  const payload = {
    priceId,
    planKey,
    billingCycle: period,
    successUrl: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancelUrl: `${origin}/plan?checkout=cancelled`,
    price_id: priceId,
    plan_key: planKey,
    billing_period: period,
    success_url: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancel_url: `${origin}/plan?checkout=cancelled`,
    mode: 'subscription',
  };
  // eslint-disable-next-line no-console
  console.log('[billing] invoking create-checkout-session', payload);
  const { data, error } = await supabase.functions.invoke('create-checkout-session', { body: payload });
  if (error) {
    const detail = await readEdgeFnError(error);
    // eslint-disable-next-line no-console
    console.error('[startCheckout] edge function error', { error, detail, payload });
    throw new Error(detail || error.message || 'No se pudo iniciar el checkout.');
  }
  const url = data?.url || data?.checkout_url;
  if (!url) throw new Error('Respuesta inválida del servidor de billing.');
  window.location.assign(url);
}

export async function openCustomerPortal() {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const { data, error } = await supabase.functions.invoke('create-customer-portal-session', {
    body: {
      returnUrl: `${origin}/plan`,
      return_url: `${origin}/plan`,
    },
  });
  if (error) {
    const detail = await readEdgeFnError(error);
    // eslint-disable-next-line no-console
    console.error('[openCustomerPortal] edge function error', { error, detail });
    throw new Error(detail || error.message || 'No se pudo abrir el portal de cliente.');
  }
  const url = data?.url || data?.portal_url;
  if (!url) throw new Error('Respuesta inválida del servidor de billing.');
  window.location.assign(url);
}

async function readEdgeFnError(error) {
  try {
    const resp = error?.context?.response || error?.response || error?.context;
    if (!resp || typeof resp.clone !== 'function') return null;
    const cloned = resp.clone();
    const text = await cloned.text();
    if (!text) return null;
    try {
      const parsed = JSON.parse(text);
      return parsed?.error || parsed?.message || parsed?.detail || text;
    } catch (_) {
      return text;
    }
  } catch (_) {
    return null;
  }
}
