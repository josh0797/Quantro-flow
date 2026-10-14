-- Quantro — AI Credits + Stripe billing schema migration
--
-- Run this in the Supabase SQL Editor (or via `supabase db push`) to add
-- the columns + table the new credit system depends on.
--
-- Idempotent: every statement uses IF NOT EXISTS so re-running is safe.

-- 1. Profile-level billing fields ------------------------------------------
alter table public.profiles
  add column if not exists subscription_status text,
  add column if not exists current_period_end timestamptz,
  add column if not exists has_coupon boolean default false,
  add column if not exists coupon_id text,
  add column if not exists ai_credits_total numeric(10,2) default 0,
  add column if not exists ai_credits_used numeric(10,6) default 0,
  add column if not exists ai_credits_remaining numeric(10,6) default 0,
  add column if not exists user_openai_api_key_encrypted text,
  add column if not exists has_user_api_key boolean default false;

-- 2. ai_credit_usage — per-request audit trail ----------------------------
create table if not exists public.ai_credit_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  model text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cost_usd numeric(10,6) not null,
  provider text not null default 'openai',
  source text not null check (source in ('quantro_api', 'user_api')),
  created_at timestamptz default now()
);

create index if not exists ai_credit_usage_user_idx
  on public.ai_credit_usage (user_id, created_at desc);

alter table public.ai_credit_usage enable row level security;

-- Users can read their own usage history.
drop policy if exists "users_read_own_credit_usage" on public.ai_credit_usage;
create policy "users_read_own_credit_usage"
  on public.ai_credit_usage for select
  using (auth.uid() = user_id);

-- Only service_role can insert (the backend / Edge Function).
drop policy if exists "service_role_insert_credit_usage" on public.ai_credit_usage;
create policy "service_role_insert_credit_usage"
  on public.ai_credit_usage for insert
  with check (auth.role() = 'service_role');

-- 3. Atomic credit decrement RPC ------------------------------------------
-- Postgres function that updates `ai_credits_used` and recomputes
-- `ai_credits_remaining` in a single transaction so concurrent requests
-- don't race. Called by the backend after every OpenAI request.
create or replace function public.decrement_ai_credits(p_user_id uuid, p_amount numeric)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.profiles
  set ai_credits_used = coalesce(ai_credits_used, 0) + greatest(0, p_amount),
      ai_credits_remaining = greatest(
        0,
        coalesce(ai_credits_total, 0) - (coalesce(ai_credits_used, 0) + greatest(0, p_amount))
      )
  where id = p_user_id;
end;
$$;

revoke all on function public.decrement_ai_credits(uuid, numeric) from public;
grant execute on function public.decrement_ai_credits(uuid, numeric) to authenticated, service_role;

-- 4. (Optional) backfill defaults for existing rows ------------------------
-- For every existing user that already has a plan but no credits row,
-- prime the bag using PLAN_CREDITS so they don't get blocked.
update public.profiles
set ai_credits_total = case lower(coalesce(plan, ''))
      when 'essential' then 5
      when 'pro' then 10
      when 'enterprise' then 20
      else 0
    end,
    ai_credits_used = 0,
    ai_credits_remaining = case lower(coalesce(plan, ''))
      when 'essential' then 5
      when 'pro' then 10
      when 'enterprise' then 20
      else 0
    end
where ai_credits_total is null or ai_credits_total = 0;
