import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import {
  readProgress, writeProgress, dropLegacyProgress, endWelcomeSession,
} from '../../lib/welcomeSession';

/**
 * OnboardingContext — drives the multi-step Welcome flow.
 *
 * Persisted to localStorage PER USER (lib/welcomeSession) so a user who
 * closes the tab mid-flow can resume where they left off, and so another
 * account on the same browser never inherits it (e.g. a stale "real"
 * inbox). Dropped as soon as the flow is complete or dismissed. The FINAL
 * completion bit (Supabase user_metadata `needs_onboarding=false`) is
 * what gates the rest of the app — this client-side state is purely
 * cosmetic / progress-tracking.
 *
 * `providerSync` is deliberately NOT persisted: it tracks the mailbox /
 * calendar sync that runs in the background after a provider OAuth
 * return, so a reload can never leave the UI stuck in "syncing".
 */

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

const idleSync = { status: 'idle', provider: null }; // status: idle | syncing | done | error

const OnboardingContext = createContext({
  state: defaultState,
  setStartChoice: () => {},
  markStepConnected: () => {},
  markStepSkipped: () => {},
  setIndustry: () => {},
  reset: () => {},
  providerSync: idleSync,
  syncInProgress: false,
  runProviderSync: () => Promise.resolve({ ok: false }),
});

// Mount with `key={user_id}` (OnboardingShell does) so a different user
// never sees — or overwrites — someone else's progress.
export function OnboardingProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.user_id || null;
  const [state, setState] = useState(() => {
    if (typeof window === 'undefined') return defaultState;
    dropLegacyProgress();
    const saved = readProgress(userId);
    return saved ? { ...defaultState, ...saved } : defaultState;
  });

  // Persist on every change — but throttle nothing because writes are
  // tiny and infrequent (one per click).
  useEffect(() => {
    writeProgress(userId, state);
  // userId is fixed for the lifetime of this provider (see key above).
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
    endWelcomeSession(userId);
  }, [userId]);

  const [providerSync, setProviderSync] = useState(idleSync);
  const syncRunRef = useRef(null);

  /**
   * Run a provider sync in the background. Returns a promise that always
   * resolves to `{ ok, result?, error? }`. A second call while one is in
   * flight returns the same promise, so a double click (or React
   * StrictMode's double effect) can never start two syncs.
   */
  const runProviderSync = useCallback((provider, syncFn) => {
    if (syncRunRef.current) return syncRunRef.current;
    setProviderSync({ status: 'syncing', provider });
    const run = Promise.resolve()
      .then(syncFn)
      .then(
        (result) => {
          setProviderSync({ status: 'done', provider });
          return { ok: true, result };
        },
        (error) => {
          setProviderSync({ status: 'error', provider });
          return { ok: false, error };
        },
      )
      .finally(() => {
        syncRunRef.current = null;
      });
    syncRunRef.current = run;
    return run;
  }, []);

  const syncInProgress = providerSync.status === 'syncing';

  return (
    <OnboardingContext.Provider
      value={{
        state, setStartChoice, markStepConnected, markStepSkipped, setIndustry, reset,
        providerSync, syncInProgress, runProviderSync,
      }}
    >
      {children}
    </OnboardingContext.Provider>
  );
}

export const useOnboarding = () => useContext(OnboardingContext);
