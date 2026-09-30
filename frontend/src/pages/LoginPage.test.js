const mockAuth = { user: null, loading: false, signIn: jest.fn(), signUp: jest.fn() };
jest.mock('../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});
jest.mock('../lib/supabaseClient', () => ({ supabase: { auth: { resetPasswordForEmail: jest.fn() } } }));
jest.mock('../components/LanguageSwitcher', () => () => null);
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

/* eslint-disable import/first */
import React, { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { toast } from 'sonner';
import LoginPage from './LoginPage';
import { supabase } from '../lib/supabaseClient';
import { hasFreshRecoveryMarker, resetRecoveryStateForTests } from '../lib/passwordRecovery';
import { render, flush, click, byTestId } from '../test/render';
/* eslint-enable import/first */

let view;

async function mount() {
  view = await render(
    <MemoryRouter initialEntries={['/login']}>
      <LoginPage />
    </MemoryRouter>,
  );
  await flush();
}

async function type(testId, value) {
  const el = byTestId(testId);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submit(testId) {
  await act(async () => {
    byTestId(testId).dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function fillSignup() {
  await click(byTestId('login-mode-toggle'));
  await type('login-full-name-input', 'Ana Pérez');
  await type('login-email-input', 'ana@example.com');
  await type('login-password-input', 'supersecret1');
  await click(byTestId('login-accept-terms')); // required since the legal-consent checkbox
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  resetRecoveryStateForTests();
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

it('an email that already has a Quantro account switches to sign-in instead of "check your email"', async () => {
  mockAuth.signUp.mockResolvedValue({ user: { id: 'fake', identities: [] }, session: null });
  await mount();
  await fillSignup();
  await submit('login-form');

  expect(mockAuth.signUp).toHaveBeenCalledTimes(1);
  expect(byTestId('login-notice').textContent).toContain('auth_help.existing_account_title');
  expect(byTestId('login-notice').textContent).toContain('auth_help.existing_account_desc');
  expect(byTestId('login-full-name-input')).toBeNull();          // back in sign-in mode
  expect(byTestId('login-email-input').value).toBe('ana@example.com');
  expect(byTestId('login-password-input').value).toBe('');
  expect(toast.success).not.toHaveBeenCalledWith('auth.signup_success_title', expect.anything());
});

it('a new email still gets the confirmation message', async () => {
  mockAuth.signUp.mockResolvedValue({ user: { id: 'u1', identities: [{ id: 'i1' }] }, session: null });
  await mount();
  await fillSignup();
  await submit('login-form');

  expect(byTestId('login-notice')).toBeNull();
  expect(toast.success).toHaveBeenCalledWith('auth.signup_success_title', { description: 'auth.signup_success_desc' });
});

it('forgot password sends the reset link and answers neutrally', async () => {
  supabase.auth.resetPasswordForEmail.mockResolvedValue({ data: {}, error: null });
  await mount();
  await type('login-email-input', 'ana@example.com');
  await click(byTestId('login-forgot-password'));

  expect(byTestId('forgot-password-screen')).not.toBeNull();
  expect(byTestId('forgot-password-email-input').value).toBe('ana@example.com');
  await submit('forgot-password-form');

  expect(supabase.auth.resetPasswordForEmail).toHaveBeenCalledWith('ana@example.com', {
    redirectTo: `${window.location.origin}/auth/callback`,
  });
  expect(byTestId('forgot-password-sent').textContent).toContain('auth_help.link_sent_desc');
  expect(hasFreshRecoveryMarker('ana@example.com')).toBe(true);

  await click(byTestId('forgot-password-back'));
  expect(byTestId('login-form')).not.toBeNull();
});

it('forgot password shows a retry message when the request fails', async () => {
  supabase.auth.resetPasswordForEmail.mockResolvedValue({ data: null, error: { status: 429, message: 'rate limited' } });
  await mount();
  await click(byTestId('login-forgot-password'));
  await submit('forgot-password-form');
  expect(byTestId('forgot-password-error').textContent).toBe('auth_help.email_required');
  expect(supabase.auth.resetPasswordForEmail).not.toHaveBeenCalled();

  await type('forgot-password-email-input', 'ana@example.com');
  await submit('forgot-password-form');
  expect(byTestId('forgot-password-error').textContent).toBe('auth_help.send_failed');
  expect(byTestId('forgot-password-sent')).toBeNull();
});
