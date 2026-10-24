// When a customer.subscription.* event starts a NEW monthly bag of AI credits.
//
// Pure (no Deno or Stripe imports) so it can be unit-tested with Node:
// credit_period.test.ts.
//
// A new bag starts only while the subscription is live (active or trialing)
// and one of these happened in THIS event:
//   * the subscription was just created;
//   * its billing period rolled over (renewal): current_period_start changed;
//   * its price changed (plan change);
//   * its first payment just went through: status moved from 'incomplete'
//     (SCA / 3-D Secure, async payment methods, payment_behavior
//     default_incomplete) to live. customer.subscription.created arrived with
//     status 'incomplete' and allocated nothing, and this update carries no
//     period or price change.
// Any other update (cancel/resume toggles, payment method, metadata, discount)
// neither refills the bag nor, now that Essential includes 0, claws back a
// balance already granted for the current period. past_due/unpaid -> active
// does not start one either: the rollover event normally arrives while the
// subscription is still active and already started that period's bag.
//
// Known limit, and why a LIVE allocator (Quantro OS's stripe-webhook) should
// use invoice.paid with billing_reason in ('subscription_create',
// 'subscription_cycle', 'subscription_update') instead: if a period rolls over
// while the subscription is already past_due or unpaid, no bag starts until
// the next renewal. invoice.paid fires once per paid period, after SCA, and
// after a renewal that only succeeded on retry.

type Prev = Record<string, unknown> & {
  status?: string;
  items?: { data?: Array<{ price?: { id?: string } }> };
};

const LIVE = new Set(['active', 'trialing']);

export function startsNewCreditPeriod(
  eventType: string,
  status: string | undefined,
  priceId: string | undefined,
  previousAttributes: Prev | null | undefined,
): boolean {
  if (!status || !LIVE.has(status)) return false;
  if (eventType === 'customer.subscription.created') return true;
  if (eventType !== 'customer.subscription.updated') return false;
  const prev: Prev = previousAttributes ?? {};
  if ('current_period_start' in prev) return true;
  const prevPriceId = prev.items?.data?.[0]?.price?.id;
  if (!!prevPriceId && prevPriceId !== priceId) return true;
  if (prev.status === 'incomplete') return true;
  return false;
}
