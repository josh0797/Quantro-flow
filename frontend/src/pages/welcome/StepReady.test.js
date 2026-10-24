jest.mock('../../lib/supabaseClient', () => ({ supabase: { auth: { updateUser: jest.fn() } } }));
jest.mock('../../lib/api', () => ({
  completeWelcomeOnboarding: jest.fn(),
  getConnectProviders: jest.fn(),
  getBusinessProfile: jest.fn(),
}));
const mockAuth = { user: { user_id: 'new-1', name: 'Ana Pérez', needs_onboarding: true }, refresh: jest.fn() };
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
// Stable `t`, like the real memoized one.
jest.mock('../../context/LanguageContext', () => {
  const lang = { t: (k) => k, lang: 'es' };
  return { useLanguage: () => lang };
});

/* eslint-disable import/first */
import React from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import StepReady from './StepReady';
import { OnboardingProvider } from './OnboardingContext';
import { supabase } from '../../lib/supabaseClient';
import { completeWelcomeOnboarding } from '../../lib/api';
import { wasOnboardingCleared, __resetOnboardingGateForTests } from '../../lib/onboardingGate';
import { render, flush, byTestId, deferred } from '../../test/render';
/* eslint-enable import/first */

let view;

async function mount() {
  view = await render(
    <MemoryRouter initialEntries={['/welcome/ready']}>
      <OnboardingProvider>
        <Routes>
          <Route path="/welcome/ready" element={<StepReady />} />
        </Routes>
      </OnboardingProvider>
    </MemoryRouter>,
  );
  await flush(5);
}

beforeEach(() => {
  jest.clearAllMocks();
  __resetOnboardingGateForTests();
  window.localStorage.clear();
  supabase.auth.updateUser.mockResolvedValue({ data: {}, error: null });
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  await view?.unmount();
  view = null;
  console.warn.mockRestore();
});

describe('StepReady completes the flow', () => {
  it('clears needs_onboarding and shows the counters', async () => {
    completeWelcomeOnboarding.mockResolvedValue({ counters: { conversations: 4, opportunities: 2, contacts: 3, events: 1 } });
    await mount();

    expect(supabase.auth.updateUser).toHaveBeenCalledWith({ data: { needs_onboarding: false } });
    expect(wasOnboardingCleared('new-1')).toBe(true);
    expect(byTestId('step-ready-metric-conversations').textContent).toContain('4');
  });

  it('still clears needs_onboarding when /onboarding/welcome/complete fails, so the user is not sent back to /welcome', async () => {
    completeWelcomeOnboarding.mockRejectedValue(Object.assign(new Error('502'), { response: { status: 502 } }));
    await mount();

    expect(supabase.auth.updateUser).toHaveBeenCalledWith({ data: { needs_onboarding: false } });
    expect(wasOnboardingCleared('new-1')).toBe(true);
    expect(byTestId('step-ready-page')).not.toBeNull();
    expect(byTestId('step-ready-metric-conversations').textContent).toContain('0');
  });

  it('does not keep the loader up while the metadata write hangs', async () => {
    completeWelcomeOnboarding.mockResolvedValue({ counters: {} });
    supabase.auth.updateUser.mockReturnValue(deferred().promise);
    await mount();

    expect(byTestId('step-ready-loading')).toBeNull();
    expect(byTestId('step-ready-page')).not.toBeNull();
    expect(wasOnboardingCleared('new-1')).toBe(true);
  });
});
