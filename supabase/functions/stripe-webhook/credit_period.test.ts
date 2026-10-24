// Unit tests for credit_period.ts. Run with Node >= 22.18 (type stripping):
//   node --test supabase/functions/stripe-webhook/credit_period.test.ts
// backend/tests/test_ai_billing_credits.py runs this file when such a Node is
// on PATH. Not deployed: the function only bundles what index.ts imports.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startsNewCreditPeriod } from './credit_period.ts';

const CREATED = 'customer.subscription.created';
const UPDATED = 'customer.subscription.updated';
const PRO = 'price_pro';
const ESSENTIAL = 'price_essential';
const items = (id: string) => ({ items: { data: [{ price: { id } }] } });

test('created while live starts a bag; created incomplete does not', () => {
  assert.equal(startsNewCreditPeriod(CREATED, 'active', PRO, undefined), true);
  assert.equal(startsNewCreditPeriod(CREATED, 'trialing', PRO, null), true);
  assert.equal(startsNewCreditPeriod(CREATED, 'incomplete', PRO, undefined), false);
});

test('first payment confirmed (incomplete -> active/trialing) starts a bag', () => {
  assert.equal(startsNewCreditPeriod(UPDATED, 'active', PRO, { status: 'incomplete' }), true);
  assert.equal(startsNewCreditPeriod(UPDATED, 'trialing', PRO, { status: 'incomplete', latest_invoice: 'in_1' }), true);
});

test('renewal (period rolled over) and plan change start a bag while live', () => {
  assert.equal(startsNewCreditPeriod(UPDATED, 'active', PRO, { current_period_start: 1, current_period_end: 2 }), true);
  assert.equal(startsNewCreditPeriod(UPDATED, 'active', PRO, items(ESSENTIAL)), true);
  assert.equal(startsNewCreditPeriod(UPDATED, 'past_due', PRO, { current_period_start: 1 }), false);
});

test('other updates neither refill nor claw back', () => {
  for (const prev of [
    {},
    { cancel_at_period_end: false },
    { default_payment_method: 'pm_1' },
    { metadata: {} },
    items(PRO),                       // same price
    { status: 'past_due' },           // retried renewal paid
    { status: 'unpaid' },
    { status: 'trialing' },           // trial -> active without a period change
  ]) {
    assert.equal(startsNewCreditPeriod(UPDATED, 'active', PRO, prev), false, JSON.stringify(prev));
  }
  assert.equal(startsNewCreditPeriod(UPDATED, 'active', PRO, undefined), false);
});

test('never while not live, and never for other event types', () => {
  for (const status of ['incomplete', 'incomplete_expired', 'past_due', 'unpaid', 'canceled', 'paused', undefined]) {
    assert.equal(startsNewCreditPeriod(UPDATED, status, PRO, { status: 'incomplete', current_period_start: 1 }), false, String(status));
  }
  assert.equal(startsNewCreditPeriod('customer.subscription.deleted', 'active', PRO, { current_period_start: 1 }), false);
});
