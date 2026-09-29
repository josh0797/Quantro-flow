// Stable `t`, like the real memoized one (components key effects on it).
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});
jest.mock('../contexts/BusinessProfileContext', () => ({
  useBusinessProfile: () => ({ profile: null, updateProfile: jest.fn(), refetch: jest.fn() }),
}));
jest.mock('../components/LanguageSwitcher', () => () => null);
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
// The real panels hit the backend; stub them and record what they see.
jest.mock('../components/IntegrationsPanel', () => ({ children }) => (
  <div data-testid="integrations-panel-stub">{children}</div>
));
jest.mock('../components/ConnectPanel', () => {
  const { useLocation } = jest.requireActual('react-router-dom');
  return function ConnectPanelStub() {
    const location = useLocation();
    return <div data-testid="connect-panel-stub" data-search={location.search} />;
  };
});

/* eslint-disable import/first */
import React from 'react';
import { act } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Settings from '../pages/Settings';
import { legacyRedirectRoutes, CONNECT_NEW_HOME } from './legacyRedirects';
import { render, flush, byTestId, createNavSpy } from '../test/render';
/* eslint-enable import/first */

let view;
let nav;

// Same declarations App.js uses inside the authenticated AppShell.
async function mount(path) {
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path="/settings/:tab?" element={<Settings />} />
        {legacyRedirectRoutes.map((r) => (
          <Route key={r.path} path={r.path} element={r.element} />
        ))}
      </Routes>
    </MemoryRouter>,
  );
  await flush();
}

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('old Quantro Connect URLs', () => {
  it('/connect lands on Settings → Integrations with the Connect catalog', async () => {
    await mount('/connect');
    expect(CONNECT_NEW_HOME).toBe('/settings/integrations');
    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(byTestId('integrations-panel-stub')).not.toBeNull();
    expect(byTestId('connect-panel-stub')).not.toBeNull();
  });

  it('keeps the OAuth callback query string so the result is still handled', async () => {
    const qs = '?google_connected=success&account=owner%40example.com&return_to=/connect';
    await mount(`/connect${qs}`);
    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(nav.location.search).toBe(qs);
    expect(byTestId('connect-panel-stub').getAttribute('data-search')).toBe(qs);
  });

  it('redirects any /connect/* sub-path, preserving query and hash', async () => {
    await mount('/connect/google?tab=permissions#scopes');
    expect(nav.location.pathname).toBe('/settings/integrations');
    expect(nav.location.search).toBe('?tab=permissions');
    expect(nav.location.hash).toBe('#scopes');
  });
});

describe('Settings tabs', () => {
  it('opens Integrations for /settings (the backend OAuth return path)', async () => {
    await mount('/settings?microsoft_connected=success');
    expect(nav.location.pathname).toBe('/settings');
    expect(byTestId('connect-panel-stub').getAttribute('data-search')).toBe('?microsoft_connected=success');
  });

  it('opens the tab named in the URL and falls back to Integrations for unknown ones', async () => {
    await mount('/settings/workspace');
    expect(byTestId('workspace-name-input')).not.toBeNull();
    expect(byTestId('connect-panel-stub')).toBeNull();

    await nav.go('/settings/not-a-tab');
    await flush();
    expect(byTestId('connect-panel-stub')).not.toBeNull();
  });

  it('writes the selected tab to the URL', async () => {
    await mount('/settings');
    const trigger = view.container.querySelector('[role="tab"][id$="-trigger-profile"]');
    expect(trigger).not.toBeNull();
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
    });
    await flush();
    expect(nav.location.pathname).toBe('/settings/profile');
    expect(byTestId('industry-selector')).not.toBeNull();
  });
});
