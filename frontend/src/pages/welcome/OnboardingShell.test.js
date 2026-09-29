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
jest.mock('../../contexts/AuthContext', () => {
  const auth = { user: { user_id: 'owner-1', name: 'Owner Test' }, signOut: jest.fn(), refresh: jest.fn() };
  return { useAuth: () => auth };
});
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
import { wasOnboardingCleared, __resetOnboardingGateForTests } from '../../lib/onboardingGate';
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
      </Routes>
    </MemoryRouter>
  );
  view = await render(strict ? <React.StrictMode>{tree}</React.StrictMode> : tree);
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  __resetOnboardingGateForTests();
  window.localStorage.clear();
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
    const saved = JSON.parse(window.localStorage.getItem('quantro:onboarding:state:v1'));
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
});
