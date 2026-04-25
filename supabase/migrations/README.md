# Supabase — Database migrations

This directory contains idempotent SQL scripts you should run in the
Supabase SQL Editor (or via `supabase db push`) to bring the database
in sync with Quantro Flow's billing/credit system.

Apply order:

1. `20260425_ai_credits_schema.sql` — columns + ai_credit_usage table +
   atomic decrement RPC.

After applying, redeploy the Stripe webhook so it can populate the new
columns:

```bash
supabase functions deploy stripe-webhook --no-verify-jwt
```
