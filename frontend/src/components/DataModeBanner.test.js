// date-fns v3+ ships ESM that Jest 27 can't transform — stub what the banner imports.
jest.mock('date-fns', () => ({ formatDistanceToNow: () => 'hace 5 min', parseISO: (s) => new Date(s) }));
jest.mock('date-fns/locale', () => ({ es: {}, enUS: {} }));
jest.mock('../lib/api', () => ({
  getGoogleIntegrationStatus: jest.fn(),
  getMicrosoftIntegrationStatus: jest.fn(),
  syncGoogleData: jest.fn(),
  syncMicrosoftData: jest.fn(),
}));
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn(), info: jest.fn() },
}));
// Stable `t`, like the real memoized one.
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es', language: 'es' };
  return { useLanguage: () => lang };
});

/* eslint-disable import/first */
import React from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import DataModeBanner from './DataModeBanner';
import { getGoogleIntegrationStatus, getMicrosoftIntegrationStatus } from '../lib/api';
import { render, flush, click, byTestId, createNavSpy } from '../test/render';
/* eslint-enable import/first */

let view;
let nav;

async function mount(module) {
  nav = createNavSpy();
  const path = module === 'schedule' ? '/schedule' : '/inbox';
  view = await render(
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path={path} element={<DataModeBanner module={module} />} />
        <Route path="/settings/*" element={<div data-testid="settings-screen" />} />
        <Route path="/welcome/*" element={<div data-testid="welcome-screen" />} />
      </Routes>
    </MemoryRouter>,
  );
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  // Existing workspace whose Google needs re-auth: the status endpoint says
  // "not connected", so the banner is in demo mode and offers "Conectar".
  getGoogleIntegrationStatus.mockResolvedValue({ configured: true, connected: false, reauthorization_required: true });
  getMicrosoftIntegrationStatus.mockResolvedValue({ configured: false, connected: false });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('DataModeBanner "Conectar"', () => {
  it.each(['inbox', 'schedule'])(
    'in %s opens Settings → Integrations, never the Welcome onboarding flow',
    async (module) => {
      await mount(module);
      expect(byTestId('data-mode-banner-demo')).not.toBeNull();

      await click(byTestId('data-mode-banner-connect-btn'));
      await flush();

      expect(nav.location.pathname).toBe('/settings/integrations');
      expect(byTestId('settings-screen')).not.toBeNull();
      expect(byTestId('welcome-screen')).toBeNull();
    },
  );

  it('shows the real-data state (no connect CTA) when a provider is connected', async () => {
    getGoogleIntegrationStatus.mockResolvedValue({
      configured: true, connected: true, account_email: 'owner@example.com', last_sync_at: '2026-09-29T10:00:00Z',
    });
    await mount('inbox');

    expect(byTestId('data-mode-banner-real')).not.toBeNull();
    expect(byTestId('data-mode-banner-connect-btn')).toBeNull();
  });
});
