// create-checkout-session Edge Function — HARDENED v2
//
// Creates a Stripe Checkout session for the authenticated Supabase user
// and returns { url } so the browser can redirect to it.
//
// Hardening vs. v1:
//   • Verbose logging at every step so failures are visible in
//     `supabase functions logs create-checkout-session`.
//   • Explicit env var validation (fails fast with a helpful message).
//   • Defensive profiles lookup that never crashes on missing columns.
//   • CORS headers on every response, including errors.
//   • Uses Stripe account default API version (no hard-coded version).
//   • Never returns 500 with an empty body — always JSON with `error`.

// @ts-ignore — Deno std
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
// @ts-ignore
import Stripe from 'https://esm.sh/stripe@17.5.0?target=deno';
// @ts-ignore
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.4';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

function env(key: string): string | undefined {
  // @ts-ignore Deno.env
  return Deno.env.get(key);
}

serve(async (req: Request): Promise<Response> => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);

  // 1. Env var validation — surface missing secrets loudly.
  const stripeKey = env('STRIPE_SECRET_KEY');
  const supabaseUrl = env('SUPABASE_URL');
  const serviceRole = env('SUPABASE_SERVICE_ROLE_KEY');
  const missing: string[] = [];
  if (!stripeKey) missing.push('STRIPE_SECRET_KEY');
  if (!supabaseUrl) missing.push('SUPABASE_URL');
  if (!serviceRole) missing.push('SUPABASE_SERVICE_ROLE_KEY');
  if (missing.length) {
    console.error('[create-checkout-session] missing env:', missing);
    return json({ error: `Edge Function env missing: ${missing.join(', ')}` }, 500);
  }

  try {
    // 2. Parse body early so we can log what we received.
    const body = await req.json().catch(() => ({}));
    console.log('[create-checkout-session] incoming body:', body);
    // Accept BOTH camelCase and snake_case so the function is forward-
    // and backward-compatible with every Quantro client (landing + app).
    const price_id = body?.price_id ?? body?.priceId;
    const plan_key = body?.plan_key ?? body?.planKey;
    const billing_period = body?.billing_period ?? body?.billingCycle;
    const success_url = body?.success_url ?? body?.successUrl;
    const cancel_url = body?.cancel_url ?? body?.cancelUrl;
    const mode = body?.mode ?? 'subscription';
    if (!price_id) return json({ error: 'priceId requerido' }, 400);
    if (!success_url || !cancel_url) return json({ error: 'success_url and cancel_url are required' }, 400);

    // 3. Authenticate the user via the Supabase JWT in the Authorization header.
    const authHeader = req.headers.get('Authorization') || '';
    const jwt = authHeader.replace(/^Bearer\s+/i, '').trim();
    if (!jwt) return json({ error: 'Not authenticated (missing Authorization header)' }, 401);
    console.log('[create-checkout-session] got JWT (len):', jwt.length);

    const supabase = createClient(supabaseUrl!, serviceRole!);
    const { data: userData, error: userErr } = await supabase.auth.getUser(jwt);
    if (userErr || !userData?.user) {
      console.error('[create-checkout-session] getUser error', userErr);
      return json({ error: `Invalid token: ${userErr?.message || 'no user'}` }, 401);
    }
    const user = userData.user;
    console.log('[create-checkout-session] user:', user.id, user.email);

    // 4. Fetch existing profile (best-effort: don't break if columns differ).
    let profile: Record<string, any> | null = null;
    try {
      const { data, error } = await supabase.from('profiles').select('*').eq('id', user.id).maybeSingle();
      if (error) console.warn('[create-checkout-session] profiles select warning', error);
      profile = data || null;
    } catch (e) {
      console.warn('[create-checkout-session] profiles select failed', e);
    }

    // 5. Resolve or create Stripe customer, persist customer_id on profile.
    const stripe = new Stripe(stripeKey!);
    let customerId: string | null = (profile?.stripe_customer_id as string) || null;
    if (!customerId) {
      console.log('[create-checkout-session] creating new Stripe customer for', user.email);
      const customer = await stripe.customers.create({
        email: user.email,
        name: (profile?.full_name as string) || (user.user_metadata?.full_name as string) || undefined,
        metadata: { supabase_user_id: user.id },
      });
      customerId = customer.id;
      try {
        await supabase.from('profiles').upsert(
          { id: user.id, stripe_customer_id: customerId },
          { onConflict: 'id' },
        );
      } catch (e) {
        console.warn('[create-checkout-session] could not persist stripe_customer_id', e);
      }
    }
    console.log('[create-checkout-session] using stripe customer', customerId);

    // 6. Create the Checkout Session.
    const session = await stripe.checkout.sessions.create({
      mode,
      customer: customerId,
      line_items: [{ price: price_id, quantity: 1 }],
      success_url,
      cancel_url,
      allow_promotion_codes: true,
      client_reference_id: user.id,
      subscription_data: mode === 'subscription' ? {
        metadata: {
          supabase_user_id: user.id,
          plan_key: plan_key || '',
          billing_period: billing_period || 'monthly',
        },
      } : undefined,
      metadata: {
        supabase_user_id: user.id,
        plan_key: plan_key || '',
        billing_period: billing_period || 'monthly',
      },
    });

    console.log('[create-checkout-session] created session', session.id);
    return json({ url: session.url, session_id: session.id });
  } catch (err: any) {
    // Stripe errors carry a .message + .type + .code — log all of them.
    const safe = {
      name: err?.name,
      type: err?.type,
      code: err?.code,
      statusCode: err?.statusCode,
      message: err?.message,
      raw: err?.raw?.message,
    };
    console.error('[create-checkout-session] CAUGHT:', safe);
    return json({ error: err?.message || 'Unknown error', detail: safe }, 500);
  }
});
