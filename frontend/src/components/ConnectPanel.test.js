jest.mock('../lib/api', () => ({
  getConnectProviders: jest.fn(),
  testConnection: jest.fn(),
  syncConnection: jest.fn(),
  disconnectProvider: jest.fn(),
  requestGooglePermission: jest.fn(),
  requestMicrosoftPermission: jest.fn(),
  getActions: jest.fn(),
  getActionExecutions: jest.fn(),
  startGoogleOAuth: jest.fn(),
  startMicrosoftOAuth: jest.fn(),
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() } }));
// The active workspace's role decides which drawer buttons show (leader+).
const mockAuth = { workspaces: [], currentWorkspaceId: 'ws_a' };
jest.mock('../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
// Stable `t`, like the real memoized one (components key effects on it).
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});

/* eslint-disable import/first */
import React, { act } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { toast } from 'sonner';
import ConnectPanel, { CONNECT_OAUTH_RETURN_PATH, canManageConnections } from './ConnectPanel';
import {
  getConnectProviders, getActions, getActionExecutions, startGoogleOAuth, syncConnection,
} from '../lib/api';
import { render, flush, click, byTestId, createNavSpy, deferred } from '../test/render';
/* eslint-enable import/first */

const provider = (id, status, extra = {}) => ({
  provider_id: id,
  name: id,
  category: 'productivity',
  status,
  supports_sync: id === 'google' || id === 'microsoft',
  actions_available: [],
  capabilities: [],
  missing_scopes: [],
  ...extra,
});

let view;
let nav;

async function mount(path) {
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={[path]}>
      <nav.Probe />
      <Routes>
        <Route path="/settings/:tab?" element={<ConnectPanel />} />
      </Routes>
    </MemoryRouter>,
  );
  await flush();
}

// Radix Tabs switch on mousedown (primary button), not click.
const openTab = async (testId) => {
  await act(async () => {
    byTestId(testId).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
  });
  await flush();
};

const asRole = (role) => {
  mockAuth.workspaces = [{ workspace_id: 'ws_a', name: 'A', role, is_current: true }];
};

beforeEach(() => {
  jest.clearAllMocks();
  asRole('owner');
  getActions.mockResolvedValue([]);
  getActionExecutions.mockResolvedValue([]);
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

it('returns OAuth to /settings, which the backend allowlists and Settings opens on Integrations', () => {
  expect(CONNECT_OAUTH_RETURN_PATH).toBe('/settings');
});

it('confirms a provider OAuth return, cleans the URL and reloads the providers', async () => {
  getConnectProviders.mockResolvedValue([provider('google', 'connected')]);
  await mount('/settings/integrations?google_connected=success&account=owner%40example.com&return_to=/settings');

  expect(nav.location.pathname).toBe('/settings/integrations');
  expect(nav.location.search).toBe('');
  expect(toast.success).toHaveBeenCalledWith('connect.toasts.connected', { description: 'owner@example.com' });
  expect(getConnectProviders).toHaveBeenCalledTimes(2);
});

it('warns (not errors) when Microsoft comes back with missing permissions', async () => {
  getConnectProviders.mockResolvedValue([]);
  await mount('/settings?microsoft_connected=error&reason=permission_missing&missing_scopes=Mail.Send');
  expect(toast.warning).toHaveBeenCalledWith('connect.toasts.permission_missing');
  expect(toast.error).not.toHaveBeenCalled();
});

it('connects Google from the drawer with return_to=/settings and blocks a second click', async () => {
  getConnectProviders.mockResolvedValue([provider('google', 'disconnected')]);
  const oauth = deferred();
  startGoogleOAuth.mockReturnValue(oauth.promise);
  await mount('/settings/integrations');

  await click(byTestId('connect-provider-card-google'));
  await flush();
  const connectBtn = byTestId('drawer-connect-button');
  expect(connectBtn).not.toBeNull();

  await click(connectBtn);
  await click(connectBtn);
  expect(startGoogleOAuth).toHaveBeenCalledTimes(1);
  expect(startGoogleOAuth).toHaveBeenCalledWith('/settings');
  expect(byTestId('drawer-connect-button').disabled).toBe(true);

  oauth.reject(new Error('503'));
  await flush();
  expect(toast.error).toHaveBeenCalled();
  expect(byTestId('drawer-connect-button').disabled).toBe(false);
});

it('keeps sync, disconnect and adds reconnect for an existing Google connection', async () => {
  getConnectProviders.mockResolvedValue([provider('google', 'reauthorization_required')]);
  syncConnection.mockResolvedValue({});
  await mount('/settings/integrations');

  await click(byTestId('connect-provider-card-google'));
  await flush();
  expect(byTestId('drawer-reconnect-button')).not.toBeNull();
  expect(byTestId('drawer-sync-button')).not.toBeNull();
  expect(byTestId('drawer-disconnect-button')).not.toBeNull();
  expect(byTestId('drawer-tab-permissions')).not.toBeNull();
  expect(byTestId('drawer-tab-actions')).not.toBeNull();

  await click(byTestId('drawer-sync-button'));
  await flush();
  expect(syncConnection).toHaveBeenCalledWith('google');
});

it('only leader and owner manage connections (unknown role defers to the backend)', () => {
  expect(canManageConnections('owner')).toBe(true);
  expect(canManageConnections('leader')).toBe(true);
  expect(canManageConnections('accountant')).toBe(false);
  expect(canManageConnections('member')).toBe(false);
  expect(canManageConnections('viewer')).toBe(false);
  expect(canManageConnections('mystery')).toBe(false);
  expect(canManageConnections(undefined)).toBe(true);
});

it.each(['viewer', 'member', 'accountant'])(
  'hides connect / sync / disconnect / grant for a %s and explains why',
  async (role) => {
    asRole(role);
    getActions.mockResolvedValue([{ action_id: 'google.gmail.send', required_scopes: ['gmail.send'] }]);
    getConnectProviders.mockResolvedValue([
      provider('google', 'connected_limited', { missing_scopes: ['gmail.send'] }),
      provider('microsoft', 'disconnected'),
    ]);
    await mount('/settings/integrations');

    await click(byTestId('connect-provider-card-google'));
    await flush();
    expect(byTestId('drawer-leader-only')).not.toBeNull();
    for (const id of ['drawer-reconnect-button', 'drawer-test-button', 'drawer-sync-button',
      'drawer-disconnect-button']) {
      expect(byTestId(id)).toBeNull();
    }
    await openTab('drawer-tab-permissions');
    expect(document.body.textContent).toContain('gmail.send');
    expect(byTestId('drawer-grant-permission-button')).toBeNull();
  },
);

it('a leader gets every management button, grant permission included', async () => {
  asRole('leader');
  getActions.mockResolvedValue([{ action_id: 'google.gmail.send', required_scopes: ['gmail.send'] }]);
  getConnectProviders.mockResolvedValue([provider('google', 'connected_limited', { missing_scopes: ['gmail.send'] })]);
  await mount('/settings/integrations');

  await click(byTestId('connect-provider-card-google'));
  await flush();
  expect(byTestId('drawer-leader-only')).toBeNull();
  for (const id of ['drawer-reconnect-button', 'drawer-test-button', 'drawer-sync-button', 'drawer-disconnect-button']) {
    expect(byTestId(id)).not.toBeNull();
  }
  await openTab('drawer-tab-permissions');
  expect(byTestId('drawer-grant-permission-button')).not.toBeNull();
});

it('shows the leader-only explanation when the backend answers rbac_forbidden', async () => {
  asRole(undefined);   // role unknown → buttons shown, backend decides
  getConnectProviders.mockResolvedValue([provider('google', 'disconnected')]);
  startGoogleOAuth.mockRejectedValue({
    response: { status: 403, data: { detail: { error: 'rbac_forbidden', required_role: 'leader', your_role: 'viewer' } } },
  });
  await mount('/settings/integrations');

  await click(byTestId('connect-provider-card-google'));
  await flush();
  expect(byTestId('drawer-leader-only')).toBeNull();
  await click(byTestId('drawer-connect-button'));
  await flush();
  expect(toast.error).toHaveBeenCalledWith('connect.toasts.action_failed', { description: 'connect.toasts.leader_only' });
});
