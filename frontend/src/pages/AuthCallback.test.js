const mockAuth = { refresh: jest.fn() };
jest.mock('../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});
jest.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: jest.fn(),
      updateUser: jest.fn(),
      onAuthStateChange: jest.fn(),
    },
  },
}));
jest.mock('../components/LanguageSwitcher', () => () => null);
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

/* eslint-disable import/first */
import React, { act } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { toast } from 'sonner';
import AuthCallback from './AuthCallback';
import { supabase } from '../lib/supabaseClient';
import {
  RECOVERY_MARKER_KEY,
  markRecoveryRequested,
  resetRecoveryStateForTests,
} from '../lib/passwordRecovery';
import { render, flush, settle, byTestId, createNavSpy } from '../test/render';
/* eslint-enable import/first */

let view;
let nav;
let authListener;

const session = (email) => ({ data: { session: { access_token: 't', user: { email } } }, error: null });

async function mount() {
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={['/auth/callback']}>
      <nav.Probe />
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="*" element={null} />
      </Routes>
    </MemoryRouter>,
  );
}

// AuthCallback waits 50 ms for supabase-js before reading the session.
async function waitForDecision() {
  await act(async () => {
    await new Promise((r) => { setTimeout(r, 80); });
  });
  await settle();
}

async function type(testId, value) {
  const el = byTestId(testId);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    byTestId('new-password-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  resetRecoveryStateForTests();
  mockAuth.refresh.mockResolvedValue(undefined);
  authListener = null;
  supabase.auth.onAuthStateChange.mockImplementation((cb) => {
    authListener = cb;
    return { data: { subscription: { unsubscribe: jest.fn() } } };
  });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

it('a signup confirmation still goes straight to the app', async () => {
  supabase.auth.getSession.mockResolvedValue(session('new@example.com'));
  await mount();
  await waitForDecision();
  expect(byTestId('new-password-screen')).toBeNull();
  expect(toast.success).toHaveBeenCalledWith('auth.account_confirmed');
  expect(nav.location.pathname).toBe('/');
});

it('a reset link asks for a new password (min 8, confirmed) and then continues', async () => {
  markRecoveryRequested('ana@example.com');
  supabase.auth.getSession.mockResolvedValue(session('ana@example.com'));
  supabase.auth.updateUser.mockResolvedValue({ data: { user: {} }, error: null });
  await mount();
  await waitForDecision();

  expect(byTestId('new-password-screen')).not.toBeNull();
  expect(nav.location.pathname).toBe('/auth/callback');
  expect(mockAuth.refresh).not.toHaveBeenCalled();

  await type('new-password-input', 'short');
  await type('confirm-password-input', 'short');
  await submit();
  expect(byTestId('new-password-error').textContent).toBe('auth.password_min');

  await type('new-password-input', 'longenough1');
  await type('confirm-password-input', 'longenough2');
  await submit();
  expect(byTestId('new-password-error').textContent).toBe('auth_help.password_mismatch');
  expect(supabase.auth.updateUser).not.toHaveBeenCalled();

  await type('confirm-password-input', 'longenough1');
  await submit();
  expect(supabase.auth.updateUser).toHaveBeenCalledWith({ password: 'longenough1' });
  expect(toast.success).toHaveBeenCalledWith('auth_help.password_updated');
  expect(window.localStorage.getItem(RECOVERY_MARKER_KEY)).toBeNull();
  expect(mockAuth.refresh).toHaveBeenCalled();
  expect(nav.location.pathname).toBe('/');
});

it('the PASSWORD_RECOVERY event is enough (e.g. no marker in storage)', async () => {
  supabase.auth.getSession.mockImplementation(async () => {
    authListener?.('PASSWORD_RECOVERY', {});
    return session('ana@example.com');
  });
  await mount();
  await waitForDecision();
  expect(byTestId('new-password-screen')).not.toBeNull();
});

it('shows Supabase\'s reason when the new password is rejected', async () => {
  markRecoveryRequested('ana@example.com');
  supabase.auth.getSession.mockResolvedValue(session('ana@example.com'));
  supabase.auth.updateUser.mockResolvedValue({
    data: null, error: { message: 'New password should be different from the old password.' },
  });
  await mount();
  await waitForDecision();
  await type('new-password-input', 'samepassword');
  await type('confirm-password-input', 'samepassword');
  await submit();
  expect(byTestId('new-password-error').textContent).toBe('New password should be different from the old password.');
  expect(toast.error).toHaveBeenCalledWith('auth_help.update_failed');
  expect(nav.location.pathname).toBe('/auth/callback');
  expect(byTestId('new-password-submit-btn').disabled).toBe(false);
});

it('an expired or other-browser reset link explains how to get a new one', async () => {
  markRecoveryRequested('ana@example.com');
  supabase.auth.getSession.mockResolvedValue({ data: { session: null }, error: null });
  await mount();
  await waitForDecision();
  expect(toast.error).toHaveBeenCalledWith('auth_help.link_invalid_title', { description: 'auth_help.link_invalid_desc' });
  expect(byTestId('new-password-screen')).toBeNull();
});
