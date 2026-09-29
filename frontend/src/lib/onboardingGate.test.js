jest.mock('./supabaseClient', () => ({ supabase: { auth: { updateUser: jest.fn() } } }));
jest.mock('./api', () => ({ getConnectProviders: jest.fn(), getBusinessProfile: jest.fn() }));

/* eslint-disable import/first */
import {
  hasRealProviderConnection,
  hasCompletedBusinessProfile,
  workspaceHasExistingData,
  resolveOnboardingGate,
  wasOnboardingCleared,
  needsWelcomeFlow,
  clearNeedsOnboardingFlag,
  __resetOnboardingGateForTests,
} from './onboardingGate';
import { isWelcomeActive, writeProgress, readProgress } from './welcomeSession';
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

const withGoogle = (status, extra = {}) => FRESH_PROVIDERS.map((p) => (
  p.provider_id === 'google' ? { ...p, status, ...extra } : p
));
const httpError = (status) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } });
// Real timers, tiny backoff: the retry path runs in a few ms.
const FAST = { retryDelaysMs: [1, 1], timeoutMs: 200 };

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
  window.localStorage.clear();
  window.sessionStorage.clear();
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

describe('existing-data signals', () => {
  it('ignores always-on internal providers and not-connected mail providers', () => {
    expect(hasRealProviderConnection(FRESH_PROVIDERS)).toBe(false);
    expect(hasRealProviderConnection(null)).toBe(false);
  });

  it.each(['connected', 'connected_limited'])(
    'treats a usable Google connection (%s) as real data',
    (status) => {
      expect(hasRealProviderConnection(withGoogle(status))).toBe(true);
    },
  );

  // A brand-new signup who unchecked Calendar on Google's consent screen
  // leaves a stored doc reported as reauthorization_required: that is not
  // an existing workspace (it never synced anything).
  it.each(['reauthorization_required', 'error'])(
    'does not treat a never-synced Google connection in state %s as real data',
    (status) => {
      expect(hasRealProviderConnection(withGoogle(status))).toBe(false);
      expect(hasRealProviderConnection(withGoogle(status, { last_sync_at: null }))).toBe(false);
    },
  );

  // …but an owner whose token later broke has synced before.
  it.each(['reauthorization_required', 'error'])(
    'treats a Google connection in state %s that already synced as real data',
    (status) => {
      expect(hasRealProviderConnection(withGoogle(status, { last_sync_at: '2026-09-01T10:00:00Z' }))).toBe(true);
    },
  );

  it('never counts disconnected / configuration_missing, even with an old last_sync_at', () => {
    const old = { last_sync_at: '2026-09-01T10:00:00Z' };
    expect(hasRealProviderConnection(withGoogle('disconnected', old))).toBe(false);
    expect(hasRealProviderConnection(withGoogle('configuration_missing', old))).toBe(false);
  });

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

  it('sends a brand-new signup to the Welcome flow, keeps the flag and marks the tab as in the flow', async () => {
    const d = deps();
    await expect(resolveOnboardingGate({ userId: 'u1', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'onboarding', reason: 'new_workspace' });
    expect(d.clearFlag).not.toHaveBeenCalled();
    expect(wasOnboardingCleared('u1')).toBe(false);
    expect(isWelcomeActive('u1')).toBe(true);
    expect(isWelcomeActive('someone-else')).toBe(false);
  });

  it('keeps a brand-new signup whose only Google attempt was a partial-scope grant in the Welcome flow', async () => {
    const d = deps({ fetchProviders: jest.fn(() => Promise.resolve(withGoogle('reauthorization_required'))) });
    await expect(resolveOnboardingGate({ userId: 'new-1', needsOnboarding: true, deps: d }))
      .resolves.toEqual({ decision: 'onboarding', reason: 'new_workspace' });
    expect(d.clearFlag).not.toHaveBeenCalled();
    expect(wasOnboardingCleared('new-1')).toBe(false);
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
    await expect(resolveOnboardingGate({ userId: 'u2', needsOnboarding: true, deps: d, ...FAST }))
      .resolves.toEqual({ decision: 'app', reason: 'existing_data' });
  });

  it('retries a transient 503 before deciding, so an existing owner is not sent to /welcome', async () => {
    const fetchProviders = jest.fn()
      .mockRejectedValueOnce(httpError(503))
      .mockResolvedValue(withGoogle('connected'));
    const d = deps({ fetchProviders });
    await expect(resolveOnboardingGate({ userId: 'owner-1', needsOnboarding: true, deps: d, ...FAST }))
      .resolves.toEqual({ decision: 'app', reason: 'existing_data' });
    expect(fetchProviders).toHaveBeenCalledTimes(2);
    expect(d.clearFlag).toHaveBeenCalledTimes(1);
  });

  it('does not retry client errors or timeouts', async () => {
    const fetchProviders = jest.fn(() => Promise.reject(httpError(403)));
    const fetchBusinessProfile = jest.fn(() => new Promise(() => {}));
    const d = deps({ fetchProviders, fetchBusinessProfile });
    await resolveOnboardingGate({ userId: 'u5', needsOnboarding: true, deps: d, retryDelaysMs: [1, 1], timeoutMs: 20 });
    expect(fetchProviders).toHaveBeenCalledTimes(1);
    expect(fetchBusinessProfile).toHaveBeenCalledTimes(1);
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

  it('lets the user in but keeps the flag when the checks keep failing or time out (unknown is not "new")', async () => {
    const d = deps({
      fetchProviders: jest.fn(() => new Promise(() => {})),
      fetchBusinessProfile: jest.fn(() => Promise.reject(httpError(503))),
    });
    await expect(resolveOnboardingGate({ userId: 'u4', needsOnboarding: true, deps: d, ...FAST, timeoutMs: 20 }))
      .resolves.toEqual({ decision: 'app', reason: 'unknown' });
    expect(d.fetchBusinessProfile).toHaveBeenCalledTimes(3); // first try + 2 retries
    expect(d.clearFlag).not.toHaveBeenCalled();
    expect(wasOnboardingCleared('u4')).toBe(false);
    expect(isWelcomeActive('u4')).toBe(false);
  });

  it('only sends to /welcome when BOTH checks answered: one failure with an empty answer is unknown', async () => {
    const d = deps({ fetchBusinessProfile: jest.fn(() => Promise.reject(httpError(500))) });
    await expect(resolveOnboardingGate({ userId: 'u6', needsOnboarding: true, deps: d, ...FAST }))
      .resolves.toEqual({ decision: 'app', reason: 'unknown' });
  });
});

describe('Welcome session bookkeeping', () => {
  it('needsWelcomeFlow is true only while the flag is set and not cleared this session', async () => {
    expect(needsWelcomeFlow(null)).toBe(false);
    expect(needsWelcomeFlow({ user_id: 'a', needs_onboarding: false })).toBe(false);
    expect(needsWelcomeFlow({ user_id: 'a', needs_onboarding: true })).toBe(true);
    await clearNeedsOnboardingFlag('a', jest.fn(() => Promise.resolve()));
    expect(needsWelcomeFlow({ user_id: 'a', needs_onboarding: true })).toBe(false);
  });

  it('clearing the flag forgets that user\'s Welcome progress and in-flow marker, not anyone else\'s', async () => {
    const d = deps();
    await resolveOnboardingGate({ userId: 'a', needsOnboarding: true, deps: d });
    writeProgress('a', { inbox_connection_mode: 'real' });
    writeProgress('b', { inbox_connection_mode: 'demo' });

    // Recorded synchronously, before the (possibly hanging) network write.
    const write = clearNeedsOnboardingFlag('a', () => new Promise(() => {}));
    expect(wasOnboardingCleared('a')).toBe(true);
    expect(isWelcomeActive('a')).toBe(false);
    expect(readProgress('a')).toBeNull();
    expect(readProgress('b')).toEqual({ inbox_connection_mode: 'demo' });
    expect(write).toBeInstanceOf(Promise);
  });
});
