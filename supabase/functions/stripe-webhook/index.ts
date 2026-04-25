// stripe-webhook Edge Function
//
// Deno runtime. Receives Stripe events and keeps profiles.* in sync.
// Deploy with --no-verify-jwt so Stripe can call us without a Supabase JWT.
// Instead we verify the request using the Stripe-Signature header and
// STRIPE_WEBHOOK_SECRET.

// @ts-ignore
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
// @ts-ignore
import Stripe from 'https://esm.sh/stripe@17.5.0?target=deno';
// @ts-ignore
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.4';

// @ts-ignore
const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!, { apiVersion: '2024-11-20.acacia' });
// @ts-ignore
const webhookSecret = Deno.env.get('STRIPE_WEBHOOK_SECRET')!;
// @ts-ignore
const supabase = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);

// Maps Stripe price IDs → our plan keys. Keep in sync with
// /app/frontend/src/lib/billing.js.
const PRICE_TO_PLAN: Record<string, 'essential' | 'pro' | 'enterprise'> = {
  price_1TL8xMLJrc96wcWHzaaHtUOL: 'essential',
  price_1TPvV7LJrc96wcWHQskYMuGw: 'essential',
  price_1TL9BeLJrc96wcWHTspVOqBT: 'pro',
  price_1TL9BeLJrc96wcWHi8ajKg7L: 'pro',
  price_1TL9HOLJrc96wcWHvp7LTLS2: 'enterprise',
  price_1TL9HOLJrc96wcWHxt5fDHWe: 'enterprise',
};

serve(async (req: Request): Promise<Response> => {
  const signature = req.headers.get('stripe-signature');
  if (!signature) return new Response('Missing signature', { status: 400 });
  const raw = await req.text();

  let event: Stripe.Event;
  try {
    // Use async variant because Deno std crypto is promise-based.
    event = await stripe.webhooks.constructEventAsync(raw, signature, webhookSecret);
  } catch (err) {
    console.error('[stripe-webhook] invalid signature', err);
    return new Response('Invalid signature', { status: 400 });
  }

  try {
    switch (event.type) {
      case 'checkout.session.completed': {
        const s = event.data.object as Stripe.Checkout.Session;
        const userId = (s.metadata?.supabase_user_id || s.client_reference_id || '') as string;
        const priceId = (s.metadata?.plan_key ? null : null) as any;
        // When the session completes we may not know the final price yet
        // — fetch the subscription and rely on customer.subscription.updated
        // for the canonical state.
        if (s.customer && userId) {
          await supabase.from('profiles').update({
            stripe_customer_id: String(s.customer),
          }).eq('id', userId);
        }
        break;
      }
      case 'customer.subscription.created':
      case 'customer.subscription.updated': {
        const sub = event.data.object as Stripe.Subscription;
        const userId = sub.metadata?.supabase_user_id as string | undefined;
        const priceId = sub.items.data[0]?.price?.id;
        const plan = priceId ? PRICE_TO_PLAN[priceId] : undefined;
        const update: Record<string, any> = {
          stripe_customer_id: String(sub.customer),
          stripe_subscription_id: sub.id,
          subscription_status: sub.status,
          current_period_end: new Date(sub.current_period_end * 1000).toISOString(),
          plan_updated_at: new Date().toISOString(),
        };
        if (plan) update.plan = plan;
        if (userId) {
          await supabase.from('profiles').update(update).eq('id', userId);
        } else {
          // Fallback: look up by customer id.
          await supabase.from('profiles').update(update).eq('stripe_customer_id', String(sub.customer));
        }
        break;
      }
      case 'customer.subscription.deleted': {
        const sub = event.data.object as Stripe.Subscription;
        const userId = sub.metadata?.supabase_user_id as string | undefined;
        const update = {
          stripe_subscription_id: null,
          subscription_status: 'canceled',
          plan_updated_at: new Date().toISOString(),
        };
        if (userId) {
          await supabase.from('profiles').update(update).eq('id', userId);
        } else {
          await supabase.from('profiles').update(update).eq('stripe_customer_id', String(sub.customer));
        }
        break;
      }
      default:
        // Ignore unrelated events.
        break;
    }
  } catch (err) {
    console.error('[stripe-webhook] handler error', err);
    return new Response('Server error', { status: 500 });
  }

  return new Response('ok', { status: 200 });
});
