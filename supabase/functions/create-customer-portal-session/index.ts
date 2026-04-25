// create-customer-portal-session Edge Function — HARDENED v2
//
// Returns a Stripe Billing Portal URL for the authenticated user.

// @ts-ignore
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
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

function env(key: string): string | undefined {
  // @ts-ignore
  return Deno.env.get(key);
}

serve(async (req: Request): Promise<Response> => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);

  const stripeKey = env('STRIPE_SECRET_KEY');
  const supabaseUrl = env('SUPABASE_URL');
  const serviceRole = env('SUPABASE_SERVICE_ROLE_KEY');
  const missing: string[] = [];
  if (!stripeKey) missing.push('STRIPE_SECRET_KEY');
  if (!supabaseUrl) missing.push('SUPABASE_URL');
  if (!serviceRole) missing.push('SUPABASE_SERVICE_ROLE_KEY');
  if (missing.length) {
    console.error('[portal-session] missing env:', missing);
    return json({ error: `Edge Function env missing: ${missing.join(', ')}` }, 500);
  }

  try {
    const body = await req.json().catch(() => ({}));
    const return_url = body?.return_url ?? body?.returnUrl;

    const authHeader = req.headers.get('Authorization') || '';
    const jwt = authHeader.replace(/^Bearer\s+/i, '').trim();
    if (!jwt) return json({ error: 'Not authenticated (missing Authorization header)' }, 401);

    const supabase = createClient(supabaseUrl!, serviceRole!);
    const { data: userData, error: userErr } = await supabase.auth.getUser(jwt);
    if (userErr || !userData?.user) {
      console.error('[portal-session] getUser error', userErr);
      return json({ error: `Invalid token: ${userErr?.message || 'no user'}` }, 401);
    }
    const user = userData.user;

    // Look up profile defensively.
    let profile: Record<string, any> | null = null;
    try {
      const { data } = await supabase.from('profiles').select('*').eq('id', user.id).maybeSingle();
      profile = data || null;
    } catch (e) {
      console.warn('[portal-session] profile fetch failed', e);
    }

    const stripe = new Stripe(stripeKey!);
    let customerId = (profile?.stripe_customer_id as string) || null;
    if (!customerId) {
      console.log('[portal-session] creating lazy Stripe customer');
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
        console.warn('[portal-session] could not persist stripe_customer_id', e);
      }
    }

    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: return_url || 'https://quantroflow.online/plan',
    });
    console.log('[portal-session] created', session.id);
    return json({ url: session.url });
  } catch (err: any) {
    const safe = {
      name: err?.name, type: err?.type, code: err?.code,
      statusCode: err?.statusCode, message: err?.message, raw: err?.raw?.message,
    };
    console.error('[portal-session] CAUGHT:', safe);
    return json({ error: err?.message || 'Unknown error', detail: safe }, 500);
  }
});
