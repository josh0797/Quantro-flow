# Supabase Edge Functions — Quantro Billing

This directory contains the **shared** Supabase Edge Functions that power
Stripe billing for the entire Quantro ecosystem (landing + Quantro Flow
app). All functions live on the same Supabase project that both sites
trust; they are the single source of truth for:

* `profiles.plan`
* `profiles.stripe_customer_id`
* `profiles.stripe_subscription_id`
* `profiles.subscription_status`
* `profiles.current_period_end`

## Functions

| Function | Purpose |
|---|---|
| `create-checkout-session` | Creates a Stripe Checkout subscription session for the authenticated user and returns `{ url }`. |
| `create-customer-portal-session` | Returns a Stripe Customer Portal URL so the user can manage their subscription. |
| `stripe-webhook` | Receives Stripe events (`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`) and keeps `profiles.*` in sync. |

## Deploy

```bash
# Link project (once per machine)
supabase link --project-ref ukootpnechabpmwsmxsi

# Set secrets (only needs to happen once; can overwrite)
supabase secrets set \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  SUPABASE_SERVICE_ROLE_KEY=eyJ... \
  APP_URL=https://quantroflow.online

# Deploy functions
supabase functions deploy create-checkout-session
supabase functions deploy create-customer-portal-session
supabase functions deploy stripe-webhook --no-verify-jwt

# Configure Stripe webhook endpoint to point to:
#   https://ukootpnechabpmwsmxsi.supabase.co/functions/v1/stripe-webhook
# ...and select events: checkout.session.completed,
# customer.subscription.updated, customer.subscription.deleted
```

## Notes

* The webhook function ships with `--no-verify-jwt` because Stripe signs
  requests with its own HMAC, not a Supabase JWT.
* All other functions require a valid Supabase user JWT so we know which
  profile to attach the Stripe customer to.
* Use `SUPABASE_SERVICE_ROLE_KEY` inside the functions so we can update
  `profiles` rows regardless of RLS.
