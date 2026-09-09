# Supabase Edge Functions — Quantro Billing

> ⚠️ **DO NOT DEPLOY FROM THIS DIRECTORY.** The files below are a stale
> snapshot kept for reference only. The functions that are actually live
> on the shared project (`ukootpnechabpmwsmxsi`) today are the hardened
> versions maintained in the **Quantro OS** repo
> (`supabase/functions/{create-checkout-session,create-portal-session,stripe-webhook}`),
> which verify the caller's own JWT server-side before touching Stripe —
> this repo's copies predate that fix and accepted an unverified caller
> identity. Running `supabase functions deploy` from here would silently
> reintroduce that hole on the live project both apps depend on.
>
> Also note the **name**: the live function is `create-portal-session`,
> not `create-customer-portal-session`. This repo's frontend
> (`frontend/src/lib/billing.js`) called the name below for a while, which
> 404'd on every "Gestionar suscripción" click — fixed to call
> `create-portal-session` instead. If you ever need to change billing
> behavior, edit the Quantro OS copies and redeploy from there, then pull
> the change back into this directory for reference.

This directory contains a **historical reference copy** of the Supabase
Edge Functions that power Stripe billing for the entire Quantro ecosystem
(landing + Quantro Flow app). All functions live on the same Supabase
project that both sites trust; they are the single source of truth for:

* `profiles.plan`
* `profiles.stripe_customer_id`
* `profiles.stripe_subscription_id`
* `profiles.subscription_status`
* `profiles.current_period_end`

## Functions (canonical names, as actually deployed)

| Function | Purpose |
|---|---|
| `create-checkout-session` | Creates a Stripe Checkout subscription session for the authenticated user and returns `{ url }`. |
| `create-portal-session` | Returns a Stripe Customer Portal URL so the user can manage their subscription. (This directory's own copy is named `create-customer-portal-session` — stale, do not deploy it.) |
| `stripe-webhook` | Receives Stripe events (`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`) and keeps `profiles.*` in sync. |

## Deploy

Deploy from the Quantro OS repo, not from here — see the warning above.

## Notes

* The webhook function ships with `--no-verify-jwt` because Stripe signs
  requests with its own HMAC, not a Supabase JWT.
* All other functions require a valid Supabase user JWT so we know which
  profile to attach the Stripe customer to.
* Use `SUPABASE_SERVICE_ROLE_KEY` inside the functions so we can update
  `profiles` rows regardless of RLS.
