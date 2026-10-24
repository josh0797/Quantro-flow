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
import {
  wasOnboardingCleared,
  __resetOnboardingGateForTests,
  __setOnboardingGateTimingForTests,
} from '../lib/onboardingGate';
import { isWelcomeActive, __resetWelcomeSessionForTests } from '../lib/welcomeSession';
import { render, flush, settle, byTestId, createNavSpy, deferred } from '../test/render';
/* eslint-enable import/first */

const FRESH_PROVIDERS = [
  { provider_id: 'google', status: 'disconnected' },
  { provider_id: 'microsoft', status: 'disconnected' },
  { provider_id: 'quantro_invoicing', status: 'connected' },
  { provider_id: 'quantro_internal', status: 'connected' },
];
const OWNER_PROVIDERS = FRESH_PROVIDERS.map((p) => (p.provider_id === 'google' ? { ...p, status: 'connected' } : p));
const SEEDED_PROFILE = { industry: 'other', use_case: '' };
const http = (status) => Object.assign(new Error(`status ${status}`), { response: { status } });

let view;
let nav;

// Same wiring as App.js: /welcome is its own ProtectedRoute (welcomeFlow),
// everything else goes through the app ProtectedRoute.
async function mount(path, user) {
  useAuth.mockReturnValue({ user, loading: false });
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path="/login" element={<div data-testid="login-screen" />} />
        <Route
          path="/welcome/*"
          element={(
            <ProtectedRoute welcomeFlow>
              <div data-testid="welcome-screen" />
            </ProtectedRoute>
          )}
        />
        <Route path="/settings/*" element={<div data-testid="settings-screen" />} />
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
  await settle();
}

beforeEach(() => {
  __resetOnboardingGateForTests();
  __setOnboardingGateTimingForTests({ retryDelaysMs: [0, 0] });
  window.sessionStorage.clear();
  jest.clearAllMocks();
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  supabase.auth.updateUser.mockResolvedValue({ data: {}, error: null });
  getConnectProviders.mockResolvedValue(FRESH_PROVIDERS);
  getBusinessProfile.mockResolvedValue(SEEDED_PROFILE);
});

afterEach(async () => {
  await view?.unmount();
  view = null;
  console.warn.mockRestore();
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
    // The /welcome route trusts the gate's answer: no second round of checks.
    expect(getConnectProviders).toHaveBeenCalledTimes(1);
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

  it('lets the user in without clearing the flag when the backend checks keep failing', async () => {
    getConnectProviders.mockRejectedValue(http(502));
    getBusinessProfile.mockRejectedValue(http(502));
    await mount('/dashboard', { user_id: 'u-down', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/dashboard');
    expect(byTestId('app-screen')).not.toBeNull();
    expect(supabase.auth.updateUser).not.toHaveBeenCalled();
    expect(wasOnboardingCleared('u-down')).toBe(false);
  });

  it('does not send an existing owner to /welcome because of one transient 503', async () => {
    getConnectProviders.mockRejectedValueOnce(http(503)).mockResolvedValue(OWNER_PROVIDERS);
    await mount('/', { user_id: 'owner', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/');
    expect(byTestId('app-screen')).not.toBeNull();
    expect(getConnectProviders).toHaveBeenCalledTimes(2);
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

describe('opening /welcome directly (bookmark, restored tab, OAuth return)', () => {
  it('sends an existing owner whose flag is still set to the dashboard and clears the flag', async () => {
    getConnectProviders.mockResolvedValue(OWNER_PROVIDERS);
    await mount('/welcome/inbox', { user_id: 'owner', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/dashboard');
    expect(byTestId('welcome-screen')).toBeNull();
    expect(byTestId('app-screen')).not.toBeNull();
    expect(supabase.auth.updateUser).toHaveBeenCalledTimes(1);
    expect(getConnectProviders).toHaveBeenCalledTimes(1);
  });

  it('sends users without the flag to the dashboard without any request', async () => {
    await mount('/welcome/ready', { user_id: 'regular', needs_onboarding: false });

    expect(nav.location.pathname).toBe('/dashboard');
    expect(getConnectProviders).not.toHaveBeenCalled();
  });

  it('confirms an OAuth return of a user who is not onboarding in Settings → Integrations, not in the flow', async () => {
    const search = '?google_connected=success&account=owner%40example.com&return_to=/welcome/inbox';
    await mount(`/welcome/inbox${search}`, { user_id: 'regular', needs_onboarding: false });

    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(nav.location.search).toBe(search);
    expect(byTestId('settings-screen')).not.toBeNull();
  });

  it('keeps a brand-new signup who opens /welcome in the flow', async () => {
    await mount('/welcome', { user_id: 'new', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/welcome');
    expect(byTestId('welcome-screen')).not.toBeNull();
    expect(isWelcomeActive('new')).toBe(true);
  });

  it('keeps an in-flow signup in the flow after the OAuth round trip, although Google is now connected', async () => {
    // Login → gate says brand-new → /welcome (this tab is now in the flow).
    await mount('/', { user_id: 'new', needs_onboarding: true });
    expect(nav.location.pathname).toBe('/welcome');
    await view.unmount();
    view = null;
    simulatePageLoad();

    // Full-page return from Google (fresh JS, same tab's sessionStorage).
    getConnectProviders.mockResolvedValue(OWNER_PROVIDERS);
    await mount('/welcome/inbox?google_connected=success&account=new%40example.com', { user_id: 'new', needs_onboarding: true });

    expect(nav.location.pathname).toBe('/welcome/inbox');
    expect(byTestId('welcome-screen')).not.toBeNull();
    expect(getConnectProviders).toHaveBeenCalledTimes(1); // only the login check
    expect(supabase.auth.updateUser).not.toHaveBeenCalled();
  });

  it('decides once on entry: finishing the flow (flag cleared) does not yank the user off the last screen', async () => {
    await mount('/', { user_id: 'new', needs_onboarding: true });
    expect(nav.location.pathname).toBe('/welcome');

    // StepReady clears the flag; the auth context re-renders with it off.
    useAuth.mockReturnValue({ user: { user_id: 'new', needs_onboarding: false }, loading: false });
    await nav.go('/welcome/ready');
    await settle();

    expect(nav.location.pathname).toBe('/welcome/ready');
    expect(byTestId('welcome-screen')).not.toBeNull();
  });
});

// A full page load: module memory is gone, the tab's sessionStorage stays.
function simulatePageLoad() {
  const saved = Object.fromEntries(
    Array.from({ length: window.sessionStorage.length }, (_, i) => {
      const key = window.sessionStorage.key(i);
      return [key, window.sessionStorage.getItem(key)];
    }),
  );
  __resetWelcomeSessionForTests();
  Object.entries(saved).forEach(([k, v]) => window.sessionStorage.setItem(k, v));
}
