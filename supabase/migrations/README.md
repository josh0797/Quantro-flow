# Supabase — Database migrations

> ⚠️ **Historical. Do not re-run anything in this directory.** Quantro Flow
> shares one Supabase project (`ukootpnechabpmwsmxsi`) with Quantro OS, and
> schema changes to that database now ship from the **Quantro OS** repo
> (`supabase/migrations/`). The script below was applied long ago (Quantro
> OS tracks the same file as `20260928000000_ai_credits_schema.sql`).
>
> Re-running `20260425_ai_credits_schema.sql` today (once Quantro OS's
> `20261022090000_ai_credits_integrity.sql` is live) would:
>
> * **make AI free on Quantro's OpenAI key.** It puts back the original
>   `decrement_ai_credits` body, which lacks the caller binding
>   (`20261021090000_rpc_caller_binding.sql`) and never sets
>   `quantro.ai_credits_write`. The profiles protect trigger then silently
>   reverts every charge Flow makes with the user's JWT. The RPC returns void
>   and still answers 2xx, so `backend/ai_billing.py` logs nothing, and
>   anyone with a positive `ai_credits_remaining` keeps it forever.
> * **not** re-grant credits when run as-is from the SQL editor: the protect
>   trigger reverts its one-time backfill. Run with the service-role key or
>   inside `begin; set local quantro.ai_credits_write = 'on'; ... commit;`,
>   the backfill WOULD grant $5 to every Essential profile whose total is 0,
>   and Essential no longer includes Quantro AI credits (only Pro $10 and
>   Enterprise $20 do — see `backend/ai_billing.py` `PLAN_CREDITS`).
>
> If `decrement_ai_credits` was ever replaced by accident, restore it by
> running section 3 of Quantro OS's `20261022090000_ai_credits_integrity.sql`
> (the function and its grants). The migration as a whole refuses to run
> over a body it has not reviewed.

What it originally did:

1. `20260425_ai_credits_schema.sql` — columns + ai_credit_usage table +
   atomic decrement RPC.

Do not deploy the Stripe webhook from this repo either: the live
`stripe-webhook` is Quantro OS's (see `../functions/README.md`).
