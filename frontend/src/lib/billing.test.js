// Essential includes no Quantro AI credits; Pro ($10) and Enterprise ($20)
// are unchanged. Kept in lock-step with backend/ai_billing.py (see
// backend/tests/test_ai_billing_credits.py).
import {
  OPENAI_DEFAULT_MODEL,
  PLAN_CREDITS,
  PLANS,
  TEST_USERS,
  TEST_USER_CREDITS,
  getCreditsState,
  planCreditsFeature,
  resolveOwnKeyModel,
} from './billing';

jest.mock('./supabaseClient', () => ({ supabase: {} }));

const featuresOf = (key) => PLANS.find((p) => p.key === key).features;

describe('PLAN_CREDITS', () => {
  it('gives Essential 0 and keeps Pro/Enterprise at $10/$20', () => {
    expect(PLAN_CREDITS).toEqual({ essential: 0, pro: 10, enterprise: 20 });
  });
});

describe('pricing cards', () => {
  it('marks AI credits as not included on Essential', () => {
    expect(planCreditsFeature('essential')).toEqual({
      label: 'Créditos IA no incluidos',
      included: false,
    });
    const essential = featuresOf('essential');
    expect(essential).toContainEqual({ label: 'Créditos IA no incluidos', included: false });
    // Never "$5 USD ..." nor "$0 USD en créditos IA / mes".
    const strings = essential.filter((f) => typeof f === 'string');
    expect(strings.some((f) => /USD en créditos IA/.test(f))).toBe(false);
  });

  it('keeps the Pro and Enterprise bullets exactly as before', () => {
    expect(featuresOf('pro')).toContain('$10 USD en créditos IA / mes');
    expect(featuresOf('enterprise')).toContain('$20 USD en créditos IA / mes');
  });
});

describe('getCreditsState', () => {
  const email = 'owner@example.com';

  it.each([
    [{ ai_credits_total: 0, ai_credits_used: 0, ai_credits_remaining: 0 }],
    [{ ai_credits_total: null, ai_credits_used: null, ai_credits_remaining: null }],
    [{}],
  ])('blocks Essential without a stored balance (%o)', (cols) => {
    const s = getCreditsState({ email, profile: { plan: 'essential', ...cols } });
    expect(s).toMatchObject({
      total: 0,
      remaining: 0,
      source: 'blocked',
      blocked: true,
      reason: 'plan_no_credits',
    });
  });

  it('still honours a balance already stored on an Essential profile', () => {
    const s = getCreditsState({
      email,
      profile: { plan: 'essential', ai_credits_total: 5, ai_credits_used: 1.8, ai_credits_remaining: 3.2 },
    });
    expect(s.source).toBe('quantro');
    expect(s.total).toBe(5);
    expect(s.remaining).toBeCloseTo(3.2);
  });

  it('keeps Pro/Enterprise display behaviour', () => {
    expect(getCreditsState({ email, profile: { plan: 'pro' } })).toMatchObject({
      total: 10, remaining: 10, source: 'quantro',
    });
    expect(getCreditsState({ email, profile: { plan: 'enterprise' } })).toMatchObject({
      total: 20, remaining: 20, source: 'quantro',
    });
    expect(
      getCreditsState({
        email,
        profile: { plan: 'pro', ai_credits_total: 0, ai_credits_used: 0, ai_credits_remaining: 0 },
      }),
    ).toMatchObject({ source: 'blocked', reason: 'no_credits_no_user_key' });
  });

  it('leaves internal test users alone', () => {
    const s = getCreditsState({ email: TEST_USERS[0], profile: { plan: 'essential' } });
    expect(s.total).toBe(TEST_USER_CREDITS);
    expect(s.source).toBe('quantro');
  });
});

describe('getCreditsState — workspace own OpenAI key', () => {
  const email = 'owner@example.com';

  it('routes to the workspace key even with Quantro credits left, without touching the bag', () => {
    const s = getCreditsState({
      email,
      profile: { plan: 'pro', ai_credits_total: 10, ai_credits_used: 2, ai_credits_remaining: 8 },
      workspaceOwnKey: true,
    });
    expect(s).toMatchObject({
      source: 'user_api', reason: 'workspace_openai_key', blocked: false, hasOwnApiKey: true, remaining: 8,
    });
  });

  it('unblocks Essential and exhausted plans', () => {
    expect(getCreditsState({ email, profile: { plan: 'essential' }, workspaceOwnKey: true }).blocked).toBe(false);
    expect(
      getCreditsState({
        email,
        profile: { plan: 'pro', ai_credits_total: 10, ai_credits_used: 10, ai_credits_remaining: 0 },
        workspaceOwnKey: true,
      }).source,
    ).toBe('user_api');
  });

  it('ignores the legacy profile key flags (never written by any code path)', () => {
    const s = getCreditsState({
      email,
      profile: { plan: 'essential', has_user_api_key: true, user_openai_api_key_encrypted: 'x' },
    });
    expect(s).toMatchObject({ source: 'blocked', reason: 'plan_no_credits', hasOwnApiKey: false });
  });
});

describe('resolveOwnKeyModel', () => {
  it('keeps allowlisted models and maps anything else to the default', () => {
    expect(resolveOwnKeyModel('gpt-4o')).toBe('gpt-4o');
    expect(resolveOwnKeyModel('gpt-4.1-mini')).toBe('gpt-4.1-mini');
    expect(resolveOwnKeyModel('gpt-4-turbo')).toBe(OPENAI_DEFAULT_MODEL);
    expect(resolveOwnKeyModel(undefined)).toBe(OPENAI_DEFAULT_MODEL);
  });
});
