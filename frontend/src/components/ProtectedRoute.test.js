jest.mock('../contexts/AuthContext', () => ({ useAuth: jest.fn() }));
// Stable `t`, like the real memoized one (components key effects on it).
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});
jest.mock('../lib/supabaseClient', () => ({ supabase: { auth: { updateUser: jest.fn() } } }));
jest.mock('../lib/api', () => ({ getConnectProviders: jest.fn(), getBusinessProfile: jest.fn() }));

/* eslint-disable import/first */
import React from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import ProtectedRoute from './ProtectedRoute';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabaseClient';
import { getConnectProviders, getBusinessProfile } from '../lib/api';
import { __resetOnboardingGateForTests } from '../lib/onboardingGate';
import { render, flush, byTestId, createNavSpy, deferred } from '../test/render';
/* eslint-enable import/first */

const FRESH_PROVIDERS = [
  { provider_id: 'google', status: 'disconnected' },
  { provider_id: 'microsoft', status: 'disconnected' },
  { provider_id: 'quantro_invoicing', status: 'connected' },
  { provider_id: 'quantro_internal', status: 'connected' },
];
const OWNER_PROVIDERS = FRESH_PROVIDERS.map((p) => (p.provider_id === 'google' ? { ...p, status: 'connected' } : p));
const SEEDED_PROFILE = { industry: 'other', use_case: '' };

let view;
let nav;

async function mount(path, user) {
  useAuth.mockReturnValue({ user, loading: false });
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path="/login" element={<div data-testid="login-screen" />} />
        <Route path="/welcome/*" element={<div data-testid="welcome-screen" />} />
        <Route
          path="/*"
          element={(
            <ProtectedRoute>
              <div data-testid="app-screen" />
            </ProtectedRoute>
          )}
        />
      </Routes>
    </MemoryRouter>,
  );
  await flush();
}

beforeEach(() => {
  __resetOnboardingGateForTests();
  jest.clearAllMocks();
  supabase.auth.updateUser.mockResolvedValue({ data: {}, error: null });
  getConnectProviders.mockResolvedValue(FRESH_PROVIDERS);
  getBusinessProfile.mockResolvedValue(SEEDED_PROFILE);
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('ProtectedRoute onboarding decision', () => {
  it('sends an existing owner (Google connected) to the app and clears needs_onboarding once', async () => {
    getConnectProviders.mockResolvedValue(OWNER_PROVIDERS);
    await mount('/dashboard', { user_id: 'owner', needs_onboarding: true });

    expect(byTestId('app-screen')).not.toBeNull();
    expect(byTestId('welcome-screen')).toBeNull();
    expect(nav.location.pathname).toBe('/dashboard');
    expect(supabase.auth.updateUser).toHaveBeenCalledTimes(1);
    expect(supabase.auth.updateUser).toHaveBeenCalledWith({ data: { needs_onboarding: false } });

    // Moving around the app never re-checks nor re-writes (the metadata
    // refresh may still be in flight).
    await nav.go('/inbox');
    await flush();
    expect(byTestId('app-screen')).not.toBeNull();
    expect(getConnectProviders).toHaveBeenCalledTimes(1);
    expect(supabase.auth.updateUser).toHaveBeenCalledTimes(1);
  });

  it('keeps a brand-new signup in the Welcome flow and does not touch the flag', async () => {
    await mount('/', { user_id: 'new', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/welcome');
    expect(byTestId('welcome-screen')).not.toBeNull();
    expect(byTestId('app-screen')).toBeNull();
    expect(supabase.auth.updateUser).not.toHaveBeenCalled();
  });

  it('treats a completed business profile as an existing workspace', async () => {
    getBusinessProfile.mockResolvedValue({ industry: 'real_estate', use_case: '' });
    await mount('/dashboard', { user_id: 'u-profile', needs_onboarding: true });

    expect(byTestId('app-screen')).not.toBeNull();
    expect(supabase.auth.updateUser).toHaveBeenCalledTimes(1);
  });

  it('shows the loader while deciding, never the Welcome flow first', async () => {
    const pending = deferred();
    getConnectProviders.mockReturnValue(pending.promise);
    await mount('/dashboard', { user_id: 'owner', needs_onboarding: true });

    expect(byTestId('auth-loading')).not.toBeNull();
    expect(byTestId('welcome-screen')).toBeNull();
    expect(byTestId('app-screen')).toBeNull();

    pending.resolve(OWNER_PROVIDERS);
    await flush();
    expect(byTestId('app-screen')).not.toBeNull();
  });

  it('falls back to the Welcome flow when the backend checks fail', async () => {
    getConnectProviders.mockRejectedValue(new Error('502'));
    getBusinessProfile.mockRejectedValue(new Error('502'));
    await mount('/dashboard', { user_id: 'u-down', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/welcome');
    expect(supabase.auth.updateUser).not.toHaveBeenCalled();
  });

  it('never checks users without the flag', async () => {
    await mount('/dashboard', { user_id: 'regular', needs_onboarding: false });

    expect(byTestId('app-screen')).not.toBeNull();
    expect(getConnectProviders).not.toHaveBeenCalled();
    expect(getBusinessProfile).not.toHaveBeenCalled();
  });

  it('redirects signed-out visitors to /login', async () => {
    await mount('/dashboard', null);
    expect(nav.location.pathname).toBe('/login');
  });
});
