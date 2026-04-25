import { supabase } from './supabaseClient';

/**
 * Billing configuration — single source of truth for prices, Stripe price
 * IDs, AI usage limits AND AI credits across Quantro Flow.
 *
 * Source-of-truth principles:
 *   • Numbers below MIRROR exactly what Stripe charges (no math).
 *   • Credits + pricing constants are kept in lock-step with the backend
 *     (/app/backend/ai_billing.py and /app/backend/billing_limits.py).
 */

// ---------- Plan-level pricing (exact Stripe values) ----------
export const PLAN_PRICES = {
  essential: { monthly: 59,  annualTotal: 590,  annualMonthlyDisplay: 49 },
  pro:       { monthly: 209, annualTotal: 2090, annualMonthlyDisplay: 174 },
  enterprise:{ monthly: 499, annualTotal: 4990, annualMonthlyDisplay: 416 },
};

// ---------- Legacy AI call limits (still used as fallback) ----------
export const PLAN_LIMITS = {
  essential: 1000,
  pro: 3000,
  enterprise: 15000,
};
export const INACTIVE_LIMIT = 0;
export const COUPON_LIMIT = 500;
export const TEST_USERS = [
  'josias.martin@hotmail.com',
  'josias.martin90@hotmail.com',
];
export const TEST_USER_LIMIT = 15000;

// ---------- AI CREDITS (USD-based, real cost per request) ----------
// Each plan ships with a fixed monthly bag of "credits" measured in USD.
// Every request consumes its real Stripe-grade cost based on the model's
// per-token pricing. When the user's bag hits 0 we fall back to the
// user-supplied OpenAI API key (if configured); otherwise smart features
// are blocked.
export const PLAN_CREDITS = {
  essential: 5,    // $5 USD / month
  pro: 10,         // $10 USD / month
  enterprise: 20,  // $20 USD / month
};

// Internal QA accounts always get the top tier in credits + calls.
export const TEST_USER_CREDITS = 20;

// Per-1M-tokens pricing for every model we route through Quantro's key.
// When the user runs on Quantro credits we ALWAYS force gpt-4o-mini so
// costs stay predictable. The other entries exist only so the helper
// can also be reused for the user's own key when we let them pick a
// model in the future.
export const MODEL_PRICING = {
  'gpt-4o-mini':   { inputPer1M: 0.15, outputPer1M: 0.60 },
  // For visibility — not used while consuming Quantro credits.
  'gpt-4o':        { inputPer1M: 2.50, outputPer1M: 10.00 },
  'gpt-4.1-mini':  { inputPer1M: 0.40, outputPer1M: 1.60 },
};

// The model the backend forces when using Quantro's API key.
export const QUANTRO_FORCED_MODEL = 'gpt-4o-mini';

/**
 * Compute the real USD cost of an OpenAI request from its token usage.
 * Throws on unknown models so we never silently under-charge a customer.
 */
export function calculateOpenAICost({ model, inputTokens, outputTokens }) {
  const pricing = MODEL_PRICING[model];
  if (!pricing) {
    throw new Error(`Modelo no soportado para billing: ${model}`);
  }
  return (
    (Number(inputTokens || 0) / 1_000_000) * pricing.inputPer1M +
    (Number(outputTokens || 0) / 1_000_000) * pricing.outputPer1M
  );
}

/**
 * Format a (potentially fractional) USD amount for the UI. We keep more
 * precision when the value is below $1 so users can see the cents being
 * consumed by individual requests.
 */
export function formatUsd(amount) {
  const n = Number(amount || 0);
  if (Math.abs(n) < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

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
      `$${PLAN_CREDITS.essential} USD en créditos IA / mes`,
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
      `$${PLAN_CREDITS.pro} USD en créditos IA / mes`,
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
      `$${PLAN_CREDITS.enterprise} USD en créditos IA / mes`,
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
 * Resolve the AI usage limit (call-count based — legacy). Kept for
 * backwards compatibility with the existing PlanAndUsage call card while
 * we migrate the UI to USD credits.
 */
export function getOpenAIUsageLimit({ email, profile }) {
  const lcEmail = String(email || '').toLowerCase();
  if (lcEmail && TEST_USERS.includes(lcEmail)) {
    return { limit: TEST_USER_LIMIT, reason: 'test_user', blocked: false };
  }
  const status = profile?.subscription_status;
  const hasActiveStatus = status === 'active' || status === 'trialing';
  const planKey = (profile?.plan || '').toLowerCase();
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

/**
 * Resolve the user's AI credit state based on profiles + email overrides.
 *
 * Returns:
 *   {
 *     total: number,        // monthly bag in USD
 *     used: number,         // consumed so far this cycle
 *     remaining: number,    // total - used (server is the authority)
 *     percent: 0..100,      // for the Progress bar
 *     hasOwnApiKey: bool,   // whether the user has supplied their own key
 *     source: 'quantro' | 'user_api' | 'blocked',
 *     blocked: bool,        // true ⇒ cannot use smart features
 *     reason: string,
 *   }
 */
export function getCreditsState({ email, profile }) {
  const lcEmail = String(email || '').toLowerCase();
  const isTestUser = lcEmail && TEST_USERS.includes(lcEmail);
  const planKey = (profile?.plan || '').toLowerCase();
  const baseTotal = isTestUser
    ? TEST_USER_CREDITS
    : (planKey in PLAN_CREDITS ? PLAN_CREDITS[planKey] : 0);

  // Source-of-truth values from the profiles row (kept in sync by Stripe webhook).
  const total = Number(profile?.ai_credits_total ?? baseTotal) || 0;
  const used = Math.max(0, Number(profile?.ai_credits_used ?? 0));
  const remainingRaw = profile?.ai_credits_remaining;
  const remaining = Math.max(0, Number(remainingRaw ?? (total - used)) || 0);
  const percent = total > 0 ? Math.min(100, Math.round((used / total) * 1000) / 10) : 0;
  const hasOwnApiKey = !!profile?.user_openai_api_key_encrypted || !!profile?.has_user_api_key;

  let source;
  let blocked = false;
  let reason;
  if (remaining > 0) {
    source = 'quantro';
    reason = 'using_quantro_credits';
  } else if (hasOwnApiKey) {
    source = 'user_api';
    reason = 'using_user_api_key';
  } else {
    source = 'blocked';
    blocked = true;
    reason = 'no_credits_no_user_key';
  }

  return { total, used, remaining, percent, hasOwnApiKey, source, blocked, reason };
}

// ---------- Edge Function helpers ----------

export async function startCheckout({ priceId, planKey, period = 'monthly' }) {
  if (!priceId) throw new Error('Missing priceId');
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const payload = {
    priceId, planKey, billingCycle: period,
    successUrl: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancelUrl:  `${origin}/plan?checkout=cancelled`,
    price_id: priceId, plan_key: planKey, billing_period: period,
    success_url: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancel_url:  `${origin}/plan?checkout=cancelled`,
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
    body: { returnUrl: `${origin}/plan`, return_url: `${origin}/plan` },
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
