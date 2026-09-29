jest.mock('./supabaseClient', () => ({ supabase: { auth: { updateUser: jest.fn() } } }));
jest.mock('./api', () => ({ getConnectProviders: jest.fn(), getBusinessProfile: jest.fn() }));

/* eslint-disable import/first */
import {
  hasRealProviderConnection,
  hasCompletedBusinessProfile,
  workspaceHasExistingData,
  resolveOnboardingGate,
  wasOnboardingCleared,
  __resetOnboardingGateForTests,
} from './onboardingGate';
/* eslint-enable import/first */

// What GET /api/connect/providers returns for a brand-new workspace on a
// deployment where Facturación + Quantro Internal are always "connected".
const FRESH_PROVIDERS = [
  { provider_id: 'google', status: 'disconnected' },
  { provider_id: 'microsoft', status: 'configuration_missing' },
  { provider_id: 'quantro_invoicing', status: 'connected' },
  { provider_id: 'quantro_internal', status: 'connected' },
];
const SEEDED_PROFILE = { profile_id: 'ws_1', industry: 'other', use_case: '' };

const withGoogle = (status) => FRESH_PROVIDERS.map((p) => (p.provider_id === 'google' ? { ...p, status } : p));

function deps(overrides = {}) {
  return {
    fetchProviders: jest.fn(() => Promise.resolve(FRESH_PROVIDERS)),
    fetchBusinessProfile: jest.fn(() => Promise.resolve(SEEDED_PROFILE)),
    clearFlag: jest.fn(() => Promise.resolve()),
    ...overrides,
  };
}

beforeEach(() => {
  __resetOnboardingGateForTests();
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

describe('existing-data signals', () => {
  it('ignores always-on internal providers and not-connected mail providers', () => {
    expect(hasRealProviderConnection(FRESH_PROVIDERS)).toBe(false);
    expect(hasRealProviderConnection(null)).toBe(false);
  });

  it.each(['connected', 'connected_limited', 'reauthorization_required', 'error'])(
    'treats a Google connection in state %s as real data',
    (status) => {
      expect(hasRealProviderConnection(withGoogle(status))).toBe(true);
    },
  );

  it('treats a Microsoft connection as real data', () => {
    expect(hasRealProviderConnection([{ provider_id: 'microsoft', status: 'connected' }])).toBe(true);
  });

  it('only counts a business profile with a chosen industry as completed', () => {
    expect(hasCompletedBusinessProfile(SEEDED_PROFILE)).toBe(false);
    expect(hasCompletedBusinessProfile({ industry: '  Other ' })).toBe(false);
    expect(hasCompletedBusinessProfile(null)).toBe(false);
    expect(hasCompletedBusinessProfile({ industry: 'real_estate' })).toBe(true);
  });

  it('combines both signals', () => {
    expect(workspaceHasExistingData({ providers: FRESH_PROVIDERS, businessProfile: SEEDED_PROFILE })).toBe(false);
    expect(workspaceHasExistingData({ providers: withGoogle('connected'), businessProfile: null })).toBe(true);
    expect(workspaceHasExistingData({ providers: null, businessProfile: { industry: 'dental' } })).toBe(true);
  });
});

describe('resolveOnboardingGate', () => {
  it('lets users without the flag straight in, without any request', async () => {
    const d = deps();
    await expect(resolveOnboardingGate({ userId: 'u1', needsOnboarding: false, deps: d }))
      .resolves.toEqual({ decision: 'app', reason: 'no_flag' });
    expect(d.fetchProviders).not.toHaveBeenCalled();
  });

  it('sends a brand-new signup to the Welcome flow and keeps the flag', async () => {
    const d = deps();
    await expect(resolveOnboardingGate({ userId: 'u1', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'onboarding', reason: 'new_workspace' });
    expect(d.clearFlag).not.toHaveBeenCalled();
    expect(wasOnboardingCleared('u1')).toBe(false);
  });

  it('clears the flag once for an existing owner with Google connected', async () => {
    const d = deps({ fetchProviders: jest.fn(() => Promise.resolve(withGoogle('connected'))) });
    await expect(resolveOnboardingGate({ userId: 'owner', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'app', reason: 'existing_data' });
    expect(d.clearFlag).toHaveBeenCalledTimes(1);
    expect(wasOnboardingCleared('owner')).toBe(true);

    // Second check in the same session: no refetch, no second write.
    await expect(resolveOnboardingGate({ userId: 'owner', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'app', reason: 'cleared' });
    expect(d.fetchProviders).toHaveBeenCalledTimes(1);
    expect(d.clearFlag).toHaveBeenCalledTimes(1);
  });

  it('uses the business profile when the providers call fails', async () => {
    const d = deps({
      fetchProviders: jest.fn(() => Promise.reject(new Error('502'))),
      fetchBusinessProfile: jest.fn(() => Promise.resolve({ industry: 'consulting' })),
    });
    await expect(resolveOnboardingGate({ userId: 'u2', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'app', reason: 'existing_data' });
  });

  it('still lets an existing user in when the metadata write fails', async () => {
    const d = deps({
      fetchProviders: jest.fn(() => Promise.resolve(withGoogle('connected'))),
      clearFlag: jest.fn(() => Promise.reject(new Error('network'))),
    });
    await expect(resolveOnboardingGate({ userId: 'u3', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'app', reason: 'existing_data' });
    expect(wasOnboardingCleared('u3')).toBe(true);
  });

  it('falls back to the Welcome flow when every check fails or times out', async () => {
    const d = deps({
      fetchProviders: jest.fn(() => new Promise(() => {})),
      fetchBusinessProfile: jest.fn(() => Promise.reject(new Error('down'))),
    });
    await expect(resolveOnboardingGate({ userId: 'u4', needsOnboarding: true, deps: d, timeoutMs: 20 }))
      .resolves.toEqual({ decision: 'onboarding', reason: 'new_workspace' });
    expect(d.clearFlag).not.toHaveBeenCalled();
  });
});
