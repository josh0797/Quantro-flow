jest.mock('../../lib/supabaseClient', () => ({ supabase: { auth: { updateUser: jest.fn() } } }));
jest.mock('../../lib/api', () => ({
  syncGoogleData: jest.fn(),
  syncMicrosoftData: jest.fn(),
  startGoogleOAuth: jest.fn(),
  startMicrosoftOAuth: jest.fn(),
  getGoogleIntegrationStatus: jest.fn(),
  getMicrosoftIntegrationStatus: jest.fn(),
  getConnectProviders: jest.fn(),
  getBusinessProfile: jest.fn(),
}));
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn(), info: jest.fn() },
}));
// A brand-new signup going through the flow (tests switch users below).
const NEW_SIGNUP = { user_id: 'owner-1', name: 'Owner Test', needs_onboarding: true };
const mockAuth = { user: NEW_SIGNUP, signOut: jest.fn(), refresh: jest.fn() };
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
// Stable `t`, like the real memoized one (components key effects on it).
jest.mock('../../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});

/* eslint-disable import/first */
import React from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { toast } from 'sonner';
import OnboardingShell from './OnboardingShell';
import StepInbox from './StepInbox';
import StepCalendar from './StepCalendar';
import { supabase } from '../../lib/supabaseClient';
import { syncGoogleData, startGoogleOAuth, getMicrosoftIntegrationStatus } from '../../lib/api';
import { wasOnboardingCleared, clearNeedsOnboardingFlag, __resetOnboardingGateForTests } from '../../lib/onboardingGate';
import { progressKey, LEGACY_PROGRESS_KEY } from '../../lib/welcomeSession';
import { render, flush, click, byTestId, createNavSpy, deferred } from '../../test/render';
/* eslint-enable import/first */

const SUCCESS_RETURN =
  '/welcome/inbox?google_connected=success&account=owner%40example.com&return_to=/welcome/inbox';

let view;
let nav;

async function mount(path, { strict = false } = {}) {
  nav = createNavSpy();
  const tree = (
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path="/welcome" element={<OnboardingShell />}>
          <Route index element={<div data-testid="start-step" />} />
          <Route path="inbox" element={<StepInbox />} />
          <Route path="calendar" element={<StepCalendar />} />
          <Route path="crm" element={<div data-testid="crm-step" />} />
        </Route>
        <Route path="/dashboard" element={<div data-testid="dashboard-screen" />} />
        <Route path="/settings/*" element={<div data-testid="settings-screen" />} />
      </Routes>
    </MemoryRouter>
  );
  view = await render(strict ? <React.StrictMode>{tree}</React.StrictMode> : tree);
  await flush();
}

const savedProgress = (userId = NEW_SIGNUP.user_id) => JSON.parse(window.localStorage.getItem(progressKey(userId)));

beforeEach(() => {
  jest.clearAllMocks();
  __resetOnboardingGateForTests();
  window.localStorage.clear();
  mockAuth.user = NEW_SIGNUP;
  mockAuth.refresh = jest.fn().mockResolvedValue(undefined);
  supabase.auth.updateUser.mockResolvedValue({ data: {}, error: null });
  getMicrosoftIntegrationStatus.mockResolvedValue({ configured: false });
  startGoogleOAuth.mockResolvedValue({ auth_url: null });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('provider OAuth return', () => {
  it('moves to the next step immediately while the sync keeps running in the background', async () => {
    const sync = deferred();
    syncGoogleData.mockReturnValue(sync.promise);

    await mount(SUCCESS_RETURN, { strict: true });

    // Navigation happened although the sync has NOT resolved.
    expect(nav.location.pathname).toBe('/welcome/crm');
    expect(nav.location.search).toBe('');
    expect(byTestId('crm-step')).not.toBeNull();
    // One sync, even under StrictMode's double effects.
    expect(syncGoogleData).toHaveBeenCalledTimes(1);
    // Visible "Sincronizando tus correos…" state.
    const banner = byTestId('onboarding-sync-status');
    expect(banner).not.toBeNull();
    expect(banner.textContent).toContain('welcome.sync.in_progress');
    expect(toast.success).not.toHaveBeenCalled();

    sync.resolve({ counts: { emails: 12, events: 3 } });
    await flush();

    expect(byTestId('onboarding-sync-status')).toBeNull();
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith(
      'welcome.preview.real_connected_title_v2',
      expect.objectContaining({ description: 'welcome.preview.real_synced_desc' }),
    );
  });

  it('disables the connect buttons while the sync is in progress', async () => {
    const sync = deferred();
    syncGoogleData.mockReturnValue(sync.promise);
    await mount(SUCCESS_RETURN);

    // Owner goes back to the inbox step while the sync is still running.
    await nav.go('/welcome/inbox');
    await flush();
    const inboxBtn = byTestId('step-inbox-connect-btn');
    expect(inboxBtn.disabled).toBe(true);
    expect(inboxBtn.textContent).toContain('welcome.preview.sync_in_progress');
    await click(inboxBtn);
    await flush();
    expect(byTestId('provider-connect-modal')).toBeNull();
    expect(startGoogleOAuth).not.toHaveBeenCalled();

    await nav.go('/welcome/calendar');
    await flush();
    expect(byTestId('step-calendar-connect-btn').disabled).toBe(true);

    sync.resolve({ counts: { emails: 1, events: 0 } });
    await flush();
    expect(byTestId('step-calendar-connect-btn').disabled).toBe(false);
  });

  it('still treats the connection as real when the background sync fails', async () => {
    syncGoogleData.mockRejectedValue({ response: { data: { detail: 'quota' } } });
    await mount(SUCCESS_RETURN);

    expect(nav.location.pathname).toBe('/welcome/crm');
    expect(toast.warning).toHaveBeenCalledWith(
      'welcome.preview.real_connected_no_sync_title_v2',
      { description: 'quota' },
    );
    const saved = savedProgress();
    expect(saved.inbox_connection_mode).toBe('real');
    expect(saved.calendar_connection_mode).toBe('real');
    expect(byTestId('onboarding-sync-status')).toBeNull();
  });

  it('keeps the user on the step and cleans the URL when OAuth failed', async () => {
    await mount('/welcome/inbox?google_connected=error&reason=access_denied');

    expect(nav.location.pathname).toBe('/welcome/inbox');
    expect(nav.location.search).toBe('');
    expect(syncGoogleData).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      'welcome.connect_modal.google_failed_title',
      { description: 'access_denied' },
    );
    expect(byTestId('step-inbox-connect-btn').disabled).toBe(false);
  });
});

describe('provider OAuth return for a user who is NOT onboarding', () => {
  const RETURN = '?google_connected=success&account=owner%40example.com&return_to=/welcome/inbox';

  it.each([
    ['whose flag is off', () => { mockAuth.user = { ...NEW_SIGNUP, needs_onboarding: false }; }],
    ['who left the flow in this session', async () => { await clearNeedsOnboardingFlag(NEW_SIGNUP.user_id, () => Promise.resolve()); }],
  ])('sends an existing user %s to Settings → Integrations, never on to /welcome/crm', async (_label, arrange) => {
    await arrange();
    const sync = deferred();
    syncGoogleData.mockReturnValue(sync.promise);

    await mount(`/welcome/inbox${RETURN}`);

    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(nav.location.search).toBe(RETURN);
    expect(byTestId('settings-screen')).not.toBeNull();
    // Nothing of the onboarding follow-up ran.
    expect(syncGoogleData).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(savedProgress()?.inbox_connection_mode).not.toBe('real');
    expect(savedProgress()?.calendar_connection_mode).not.toBe('real');
  });

  it('forwards errors too, so the result is shown where the user manages connections', async () => {
    mockAuth.user = { ...NEW_SIGNUP, needs_onboarding: false };
    await mount('/welcome/inbox?google_connected=error&reason=access_denied');

    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(nav.location.search).toBe('?google_connected=error&reason=access_denied');
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe('Welcome progress is per user', () => {
  it('a user who skips never inherits another user\'s "real" connection on the same browser', async () => {
    // User A connects Google in the flow, then leaves with "Ir al panel".
    const sync = deferred();
    syncGoogleData.mockReturnValue(sync.promise);
    await mount(SUCCESS_RETURN);
    expect(savedProgress().inbox_connection_mode).toBe('real');
    await click(byTestId('onboarding-exit-dashboard'));
    await flush();
    await view.unmount();
    view = null;
    // Leaving the flow forgets A's progress.
    expect(window.localStorage.getItem(progressKey(NEW_SIGNUP.user_id))).toBeNull();

    // User B, a brand-new signup on the same browser, skips the inbox step.
    const userB = { user_id: 'user-B', name: 'User B', needs_onboarding: true };
    mockAuth.user = userB;
    await mount('/welcome/inbox');
    await click(byTestId('step-inbox-skip-btn'));
    await flush();

    const b = savedProgress('user-B');
    expect(b.inbox_connection_mode).toBe('demo');
    expect(b.inbox_connected).toBe(false);
  });

  it('ignores (and removes) the old progress key that every user of the browser shared', async () => {
    window.localStorage.setItem(LEGACY_PROGRESS_KEY, JSON.stringify({ inbox_connection_mode: 'real', inbox_connected: true }));
    await mount('/welcome/inbox');
    await click(byTestId('step-inbox-skip-btn'));
    await flush();

    expect(window.localStorage.getItem(LEGACY_PROGRESS_KEY)).toBeNull();
    expect(savedProgress().inbox_connection_mode).toBe('demo');
  });

  it('skipping after a real connection made by the same user in this flow keeps it real', async () => {
    const sync = deferred();
    syncGoogleData.mockReturnValue(sync.promise);
    await mount(SUCCESS_RETURN);
    await nav.go('/welcome/inbox');
    await flush();
    await click(byTestId('step-inbox-skip-btn'));
    await flush();

    expect(savedProgress().inbox_connection_mode).toBe('real');
    expect(nav.location.pathname).toBe('/welcome/calendar');
  });
});

describe('"Ir al panel" exit', () => {
  it('is always visible, clears needs_onboarding and opens the dashboard', async () => {
    await mount('/welcome/inbox');
    const exit = byTestId('onboarding-exit-dashboard');
    expect(exit).not.toBeNull();
    expect(exit.textContent).toContain('welcome.go_to_dashboard');

    await click(exit);
    await flush();

    expect(supabase.auth.updateUser).toHaveBeenCalledWith({ data: { needs_onboarding: false } });
    expect(wasOnboardingCleared('owner-1')).toBe(true);
    expect(nav.location.pathname).toBe('/dashboard');
  });

  it('never traps the user when the metadata write fails', async () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    supabase.auth.updateUser.mockResolvedValue({ data: null, error: new Error('offline') });
    await mount('/welcome');

    await click(byTestId('onboarding-exit-dashboard'));
    await flush();

    expect(nav.location.pathname).toBe('/dashboard');
    expect(wasOnboardingCleared('owner-1')).toBe(true);
    console.warn.mockRestore();
  });

  it('reaches the dashboard at once even when the metadata write or the auth refresh never settles', async () => {
    const hanging = deferred();
    supabase.auth.updateUser.mockReturnValue(hanging.promise);
    mockAuth.refresh = jest.fn(() => new Promise(() => {}));
    await mount('/welcome/inbox');

    await click(byTestId('onboarding-exit-dashboard'));
    await flush();

    expect(nav.location.pathname).toBe('/dashboard');
    expect(byTestId('dashboard-screen')).not.toBeNull();
    expect(wasOnboardingCleared('owner-1')).toBe(true);
    // The write was still sent; the refresh follows once it lands.
    expect(supabase.auth.updateUser).toHaveBeenCalledWith({ data: { needs_onboarding: false } });
    expect(mockAuth.refresh).not.toHaveBeenCalled();
    hanging.resolve({ data: {}, error: null });
    await flush();
    expect(mockAuth.refresh).toHaveBeenCalledTimes(1);
  });
});
