const mockSignUp = jest.fn();
const mockSignIn = jest.fn();
jest.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, loading: false, signIn: mockSignIn, signUp: mockSignUp }),
}));
// Stable `t` that echoes the key, like the other page tests.
jest.mock('../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});
jest.mock('../components/LanguageSwitcher', () => function LanguageSwitcherStub() { return null; });
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn(), info: jest.fn() },
}));

/* eslint-disable import/first */
import React, { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import LoginPage from './LoginPage';
import { render, flush, click, byTestId } from '../test/render';
/* eslint-enable import/first */

let view;

async function type(testId, value) {
  const el = byTestId(testId);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

// Dispatch submit directly so the test exercises the JS guard, not the
// browser's native `required` validation.
async function submit() {
  await act(async () => {
    byTestId('login-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function openSignupAndFill() {
  await click(byTestId('login-mode-toggle'));
  await type('login-full-name-input', 'Ana López');
  await type('login-email-input', 'ana@example.com');
  await type('login-password-input', 'supersecret1');
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockSignUp.mockResolvedValue({ session: null });
  view = await render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('LoginPage legal consent', () => {
  it('shows Privacy and Terms links in the footer, opening in a new tab', () => {
    const privacy = byTestId('legal-link-privacy');
    const terms = byTestId('legal-link-terms');
    expect(privacy.getAttribute('href')).toBe('https://www.quantro.technology/privacy.html');
    expect(terms.getAttribute('href')).toBe('https://www.quantro.technology/terms.html');
    for (const a of [privacy, terms]) {
      expect(a.getAttribute('target')).toBe('_blank');
      expect(a.getAttribute('rel')).toBe('noopener noreferrer');
    }
  });

  it('only asks for consent in signup mode', async () => {
    expect(byTestId('login-accept-terms')).toBeNull();
    await click(byTestId('login-mode-toggle'));
    const box = byTestId('login-accept-terms');
    expect(box).not.toBeNull();
    expect(box.checked).toBe(false);
    expect(box.required).toBe(true);
    expect(byTestId('login-terms-link').getAttribute('href')).toBe('https://www.quantro.technology/terms.html');
    expect(byTestId('login-privacy-link').getAttribute('href')).toBe('https://www.quantro.technology/privacy.html');
    expect(byTestId('login-terms-link').getAttribute('target')).toBe('_blank');
    expect(byTestId('login-privacy-link').getAttribute('target')).toBe('_blank');
  });

  it('blocks signup until the Terms and Privacy Notice are accepted', async () => {
    await openSignupAndFill();
    await submit();
    expect(mockSignUp).not.toHaveBeenCalled();
    expect(byTestId('login-error').textContent).toBe('legal.terms_required');
  });

  it('stores the accepted versions and time in the signup metadata', async () => {
    await openSignupAndFill();
    await click(byTestId('login-accept-terms'));
    expect(byTestId('login-accept-terms').checked).toBe(true);
    const before = Date.now();
    await submit();

    expect(mockSignUp).toHaveBeenCalledTimes(1);
    const [email, password, metadata] = mockSignUp.mock.calls[0];
    expect(email).toBe('ana@example.com');
    expect(password).toBe('supersecret1');
    expect(metadata).toEqual({
      full_name: 'Ana López',
      name: 'Ana López',
      needs_onboarding: true,
      terms_version: '2026-09-30',
      privacy_version: '2026-09-30',
      terms_accepted_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/),
    });
    expect(Date.parse(metadata.terms_accepted_at)).toBeGreaterThanOrEqual(before);
  });

  it('does not ask for consent on sign-in', async () => {
    mockSignIn.mockResolvedValue({});
    await type('login-email-input', 'ana@example.com');
    await type('login-password-input', 'supersecret1');
    await submit();
    expect(mockSignIn).toHaveBeenCalledWith('ana@example.com', 'supersecret1');
    expect(byTestId('login-error')).toBeNull();
  });
});
