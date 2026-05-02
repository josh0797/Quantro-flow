import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

/**
 * OnboardingContext — drives the multi-step Welcome flow.
 *
 * Persisted to localStorage so a user who closes the tab mid-flow can
 * resume where they left off, but cleared as soon as the flow is
 * marked complete. The FINAL completion bit (Supabase user_metadata
 * `needs_onboarding=false`) is what gates the rest of the app — this
 * client-side state is purely cosmetic / progress-tracking.
 */
const STORAGE_KEY = 'quantro:onboarding:state:v1';

const defaultState = {
  start_choice: null,           // 'email' | 'tools' | 'explore'
  inbox_connected: false,
  inbox_connection_mode: null,  // 'simulated' | 'real'
  calendar_connected: false,
  calendar_connection_mode: null,
  crm_connected: false,
  crm_skipped: false,
  automations_connected: false,
  automations_skipped: false,
  // Industry chosen during onboarding for the simulation seed.
  industry: 'other',
};

const OnboardingContext = createContext({
  state: defaultState,
  setStartChoice: () => {},
  markStepConnected: () => {},
  markStepSkipped: () => {},
  setIndustry: () => {},
  reset: () => {},
});

export function OnboardingProvider({ children }) {
  const [state, setState] = useState(() => {
    if (typeof window === 'undefined') return defaultState;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? { ...defaultState, ...JSON.parse(raw) } : defaultState;
    } catch {
      return defaultState;
    }
  });

  // Persist on every change — but throttle nothing because writes are
  // tiny and infrequent (one per click).
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* private mode / quota — ignore, flow still works in-memory */
    }
  }, [state]);

  const setStartChoice = useCallback((choice) => {
    setState((s) => ({ ...s, start_choice: choice }));
  }, []);

  const markStepConnected = useCallback((step, mode = 'demo') => {
    // mode: 'demo' (preview only, no real OAuth) | 'real' (OAuth completed)
    setState((s) => ({
      ...s,
      [`${step}_connected`]: mode === 'real',
      [`${step}_skipped`]: false,
      [`${step}_connection_mode`]: mode,
    }));
  }, []);

  const markStepSkipped = useCallback((step) => {
    setState((s) => ({
      ...s,
      [`${step}_connected`]: false,
      [`${step}_skipped`]: true,
    }));
  }, []);

  const setIndustry = useCallback((industry) => {
    setState((s) => ({ ...s, industry }));
  }, []);

  const reset = useCallback(() => {
    setState(defaultState);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <OnboardingContext.Provider value={{ state, setStartChoice, markStepConnected, markStepSkipped, setIndustry, reset }}>
      {children}
    </OnboardingContext.Provider>
  );
}

export const useOnboarding = () => useContext(OnboardingContext);
