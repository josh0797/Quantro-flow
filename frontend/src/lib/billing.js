import { supabase } from './supabaseClient';

/**
 * Billing configuration — lives entirely on the frontend because the
 * price IDs are public info (they're visible to anyone who opens a
 * Stripe Checkout session). The STRIPE_SECRET_KEY and webhook secret
 * stay server-side on the Supabase Edge Functions.
 *
 * Plans mirror exactly what the marketing landing charges for, so the
 * Quantro ecosystem has a single pricing source of truth.
 */
export const PLANS = [
  {
    key: 'essential',
    name: 'Essential',
    tagline: 'Claridad + control',
    priceMonthly: 59,
    priceAnnual: 49,   // shown as /mes with annual billing (approx)
    annualTotal: 588,
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
    priceMonthly: 209,
    priceAnnual: 174,
    annualTotal: 2088,
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
    priceMonthly: 499,
    priceAnnual: 416,
    annualTotal: 4988,
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

export const PLAN_LIMITS = {
  essential: 1000,
  pro: 10000,
  enterprise: 50000,
};

export function getPlanByKey(key) {
  if (!key) return null;
  return PLANS.find((p) => p.key === String(key).toLowerCase()) || null;
}

/**
 * Subscription state derived purely from the profiles row in Supabase.
 * The webhook on the shared Edge Function keeps these columns in sync
 * with Stripe, so we only need to read them here.
 *
 *   - "active"   : paying customer with an active Stripe subscription
 *   - "trial"    : profiles.plan is set but no subscription id yet
 *                  (happens immediately after signup or during promo)
 *   - "none"     : no plan at all (brand-new account)
 *   - "past_due" : placeholder — surfaced if Stripe webhook flags it
 */
export function deriveSubscriptionState(profile) {
  if (!profile) return 'none';
  if (profile.subscription_status === 'past_due') return 'past_due';
  const hasSub = !!(profile.stripe_subscription_id || profile.paypal_subscription_id);
  if (profile.plan && hasSub) return 'active';
  if (profile.plan) return 'trial';
  return 'none';
}

/**
 * Kick off a Stripe Checkout flow by invoking the shared Supabase Edge
 * Function `create-checkout-session`. The edge function:
 *   1. Validates the incoming Supabase JWT
 *   2. Looks up or creates a Stripe Customer for that user
 *   3. Creates a checkout.session with the requested price_id
 *   4. Returns { url } — we just redirect the browser to it.
 *
 * @param {object} params
 * @param {string} params.priceId  — Stripe price id for the chosen plan/period
 * @param {string} params.planKey  — essential | pro | enterprise (for telemetry)
 * @param {'monthly'|'annual'} params.period
 */
export async function startCheckout({ priceId, planKey, period = 'monthly' }) {
  if (!priceId) throw new Error('Missing priceId');
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  // Send the parameters in BOTH camelCase and snake_case so we work with
  // whichever convention the deployed Edge Function uses. Stripe doesn't
  // care about the wrapper field names — only the values matter.
  const payload = {
    // camelCase (what the existing Quantro Edge Function expects)
    priceId,
    planKey,
    billingCycle: period,
    successUrl: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancelUrl: `${origin}/plan?checkout=cancelled`,
    // snake_case (what our hardened reference function expects)
    price_id: priceId,
    plan_key: planKey,
    billing_period: period,
    // The Edge Function will append the session id via {CHECKOUT_SESSION_ID}
    // if it wants to; for now we just pass our own redirect targets.
    success_url: `${origin}/plan?checkout=success&plan=${planKey}`,
    cancel_url: `${origin}/plan?checkout=cancelled`,
    mode: 'subscription',
  };
  // eslint-disable-next-line no-console
  console.log('[billing] invoking create-checkout-session', payload);
  const { data, error } = await supabase.functions.invoke('create-checkout-session', {
    body: payload,
  });
  if (error) {
    // supabase-js wraps non-2xx responses into a generic FunctionsHttpError
    // whose .message is just "Edge Function returned a non-2xx status code".
    // Read the real body so the UI + console show the actual cause.
    const detail = await readEdgeFnError(error);
    // eslint-disable-next-line no-console
    console.error('[startCheckout] edge function error', { error, detail, payload });
    throw new Error(detail || error.message || 'No se pudo iniciar el checkout.');
  }
  const url = data?.url || data?.checkout_url;
  if (!url) {
    throw new Error('Respuesta inválida del servidor de billing.');
  }
  window.location.assign(url);
}

/**
 * Open the Stripe Customer Portal by invoking the shared
 * `create-customer-portal-session` Edge Function. The portal lets users
 * update payment methods, download invoices, cancel/pause, and change
 * plans without us needing to rebuild any of that UI.
 */
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
  if (!url) {
    throw new Error('Respuesta inválida del servidor de billing.');
  }
  window.location.assign(url);
}

/**
 * Read the real response body from a FunctionsHttpError. supabase-js v2
 * exposes the original Response object under error.context, so we clone
 * it (the original body may already be consumed) and try JSON first,
 * falling back to plain text.
 */
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
