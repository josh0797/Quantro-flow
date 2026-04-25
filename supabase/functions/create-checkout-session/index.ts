// create-checkout-session Edge Function
//
// Deno runtime. Creates a Stripe Checkout session for the authenticated
// Supabase user and returns { url } for the browser to redirect to.
//
// Expected body:
//   {
//     price_id: string,              // Stripe Price id
//     plan_key?: 'essential'|'pro'|'enterprise',
//     billing_period?: 'monthly'|'annual',
//     success_url: string,
//     cancel_url: string,
//     mode?: 'subscription'|'payment', // default: subscription
//   }

// @ts-ignore — deno std imports resolved at runtime
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
// @ts-ignore
import Stripe from 'https://esm.sh/stripe@17.5.0?target=deno';
// @ts-ignore
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.4';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

serve(async (req: Request): Promise<Response> => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    // @ts-ignore Deno.env
    const stripeKey = Deno.env.get('STRIPE_SECRET_KEY')!;
    // @ts-ignore
    const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
    // @ts-ignore
    const serviceRole = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
    const stripe = new Stripe(stripeKey, { apiVersion: '2024-11-20.acacia' });

    // Identify the user from the JWT in the Authorization header.
    const authHeader = req.headers.get('Authorization') || '';
    const jwt = authHeader.replace(/^Bearer\s+/i, '');
    if (!jwt) return json({ error: 'Not authenticated' }, 401);

    const supabase = createClient(supabaseUrl, serviceRole, {
      global: { headers: { Authorization: `Bearer ${jwt}` } },
    });
    const { data: userData, error: userErr } = await supabase.auth.getUser(jwt);
    if (userErr || !userData?.user) {
      return json({ error: 'Invalid token' }, 401);
    }
    const user = userData.user;

    const body = await req.json();
    const { price_id, success_url, cancel_url, plan_key, billing_period, mode = 'subscription' } = body;
    if (!price_id || !success_url || !cancel_url) {
      return json({ error: 'price_id, success_url and cancel_url are required' }, 400);
    }

    // Look up or create a Stripe Customer, persisted on profiles.
    const { data: profile } = await supabase
      .from('profiles')
      .select('id, email, stripe_customer_id, full_name')
      .eq('id', user.id)
      .maybeSingle();

    let customerId: string | null = profile?.stripe_customer_id ?? null;
    if (!customerId) {
      const customer = await stripe.customers.create({
        email: user.email,
        name: profile?.full_name || user.user_metadata?.full_name || undefined,
        metadata: { supabase_user_id: user.id },
      });
      customerId = customer.id;
      await supabase.from('profiles').upsert({
        id: user.id,
        email: user.email,
        stripe_customer_id: customerId,
      }, { onConflict: 'id' });
    }

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

    return json({ url: session.url });
  } catch (err) {
    console.error('[create-checkout-session]', err);
    return json({ error: err?.message || 'Unknown error' }, 500);
  }
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}
