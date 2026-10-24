import { useEffect, useState } from 'react';
import { supabase } from './supabaseClient';
import { getConnectProviders, getBusinessProfile } from './api';
import {
  markWelcomeActive, isWelcomeActive, endWelcomeSession, __resetWelcomeSessionForTests,
} from './welcomeSession';

/**
 * onboardingGate — the ONE place that decides whether a signed-in user
 * with Supabase `user_metadata.needs_onboarding === true` must go through
 * the /welcome activation flow or straight into the app.
 *
 * Why this exists: the flag is set at signup and historically was only
 * cleared by the last Welcome screen (StepReady). Owners who connected
 * Google and used Flow for weeks without ever reaching that screen were
 * sent back to /welcome on every login. Rule now:
 *
 *   • flag false                         → app
 *   • flag already cleared this session  → app
 *   • workspace already has real data    → clear the flag once, then app
 *       - a usable Google or Microsoft connection (connected /
 *         connected_limited), or one in any other stored state that has
 *         already synced (last_sync_at) — a brand-new signup whose only
 *         attempt was a partial-scope grant is NOT existing data, or
 *       - the business profile has a chosen industry (new workspaces are
 *         seeded with industry "other"; the Welcome flow only writes the
 *         industry on its final screen, which also clears the flag)
 *   • both checks answered and neither shows data → /welcome (brand-new
 *     signup), and the tab remembers it is in the flow (welcomeSession)
 *   • a check still failed after retrying, or timed out → app, flag KEPT
 *     (unknown is not "new": only a positive answer sends someone to
 *     /welcome; the next login asks again)
 *
 * `useWelcomeEntryGate` applies the same rule when /welcome itself is
 * opened (bookmark, restored tab, OAuth return), so an existing owner is
 * never kept in the flow.
 */

export const REAL_DATA_PROVIDERS = ['google', 'microsoft'];
const NOT_CONNECTED_STATUSES = new Set(['disconnected', 'configuration_missing']);
const USABLE_STATUSES = new Set(['connected', 'connected_limited']);
export const GATE_TIMEOUT_MS = 8000;
// Backoff before each retry of a check that failed fast (network error,
// 429, 5xx such as a 503 storage_unavailable). Timeouts are not retried.
export const GATE_RETRY_DELAYS_MS = [400, 1200];
// Defaults used by the React hooks; tests shorten them.
const timing = { timeoutMs: GATE_TIMEOUT_MS, retryDelaysMs: GATE_RETRY_DELAYS_MS };

// user_ids whose flag was cleared (or deliberately dismissed) during this
// page session, so a slow metadata refresh can never bounce them back.
const clearedUsers = new Set();

export function hasRealProviderConnection(providers) {
  if (!Array.isArray(providers)) return false;
  return providers.some((p) => {
    if (!p || !REAL_DATA_PROVIDERS.includes(p.provider_id) || typeof p.status !== 'string') return false;
    if (USABLE_STATUSES.has(p.status)) return true;
    // reauthorization_required / error: real only if it was ever used.
    return !NOT_CONNECTED_STATUSES.has(p.status) && !!p.last_sync_at;
  });
}

export function hasCompletedBusinessProfile(profile) {
  if (!profile || typeof profile !== 'object') return false;
  const industry = String(profile.industry || '').trim().toLowerCase();
  return industry !== '' && industry !== 'other';
}

export function workspaceHasExistingData({ providers, businessProfile } = {}) {
  return hasRealProviderConnection(providers) || hasCompletedBusinessProfile(businessProfile);
}

export function wasOnboardingCleared(userId) {
  return !!userId && clearedUsers.has(userId);
}

/**
 * True while `user` still belongs in the Welcome flow: the flag is set and
 * was not cleared/dismissed in this page session.
 */
export function needsWelcomeFlow(user) {
  return !!user && user.needs_onboarding === true && !wasOnboardingCleared(user.user_id);
}

async function defaultClearFlag() {
  const { error } = await supabase.auth.updateUser({ data: { needs_onboarding: false } });
  if (error) throw error;
}

const defaultDeps = {
  fetchProviders: getConnectProviders,
  fetchBusinessProfile: getBusinessProfile,
  clearFlag: defaultClearFlag,
};

/**
 * Flip `needs_onboarding` to false in Supabase user_metadata and remember
 * it for this session. The local memory is recorded synchronously, before
 * any network call, and even when that call fails, so the user is never
 * trapped in /welcome; the caller decides whether to surface the error.
 * The Welcome progress/marker of this user is forgotten at the same time.
 */
export async function clearNeedsOnboardingFlag(userId, clearFlag = defaultDeps.clearFlag) {
  if (userId) {
    clearedUsers.add(userId);
    endWelcomeSession(userId);
  }
  await clearFlag();
}

function withTimeout(promiseFactory, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    Promise.resolve()
      .then(promiseFactory)
      .then(
        (value) => { clearTimeout(timer); resolve(value); },
        (err) => { clearTimeout(timer); reject(err); },
      );
  });
}

function isRetryable(err) {
  if (!err || err.message === 'timeout') return false;
  const status = err.response?.status;
  return status === undefined || status === 429 || status >= 500;
}

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

async function fetchWithRetry(fetchFn, timeoutMs, retryDelaysMs) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop
      return await withTimeout(fetchFn, timeoutMs);
    } catch (err) {
      if (attempt >= retryDelaysMs.length || !isRetryable(err)) throw err;
      // eslint-disable-next-line no-await-in-loop
      await sleep(retryDelaysMs[attempt]);
    }
  }
}

/**
 * Resolve the gate. Returns `{ decision: 'app' | 'onboarding', reason }`
 * with reason one of no_flag | cleared | existing_data | new_workspace |
 * unknown. Never throws.
 */
export async function resolveOnboardingGate({
  userId,
  needsOnboarding,
  deps = defaultDeps,
  timeoutMs = timing.timeoutMs,
  retryDelaysMs = timing.retryDelaysMs,
} = {}) {
  if (!needsOnboarding) return { decision: 'app', reason: 'no_flag' };
  if (wasOnboardingCleared(userId)) return { decision: 'app', reason: 'cleared' };

  const [providersRes, profileRes] = await Promise.allSettled([
    fetchWithRetry(deps.fetchProviders, timeoutMs, retryDelaysMs),
    fetchWithRetry(deps.fetchBusinessProfile, timeoutMs, retryDelaysMs),
  ]);
  const existing = workspaceHasExistingData({
    providers: providersRes.status === 'fulfilled' ? providersRes.value : null,
    businessProfile: profileRes.status === 'fulfilled' ? profileRes.value : null,
  });

  if (existing) {
    try {
      await clearNeedsOnboardingFlag(userId, deps.clearFlag);
    } catch (err) {
      // Still let them in for this session; the next login re-runs the
      // same check and retries the clear.
      // eslint-disable-next-line no-console
      console.warn('[onboarding-gate] could not clear needs_onboarding:', err?.message || err);
    }
    return { decision: 'app', reason: 'existing_data' };
  }

  if (providersRes.status === 'fulfilled' && profileRes.status === 'fulfilled') {
    markWelcomeActive(userId);
    return { decision: 'onboarding', reason: 'new_workspace' };
  }

  // eslint-disable-next-line no-console
  console.warn('[onboarding-gate] workspace checks failed; letting the user in and keeping needs_onboarding');
  return { decision: 'app', reason: 'unknown' };
}

/**
 * React binding used by ProtectedRoute on app routes. Returns
 * 'checking' | 'app' | 'onboarding'. When `enabled` is false (flag not
 * set, or route bypasses the gate) it returns 'app' without any request.
 */
export function useOnboardingGate(user, enabled, deps = defaultDeps) {
  const userId = user?.user_id || null;
  const [state, setState] = useState({ userId: null, decision: null });

  useEffect(() => {
    if (!enabled || !userId) return undefined;
    let cancelled = false;
    resolveOnboardingGate({ userId, needsOnboarding: true, deps }).then(({ decision }) => {
      if (!cancelled) setState({ userId, decision });
    });
    return () => { cancelled = true; };
  // deps is a stable module object in production; tests pass their own.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, userId]);

  if (!enabled) return 'app';
  if (wasOnboardingCleared(userId)) return 'app';
  if (state.userId === userId && state.decision) return state.decision;
  return 'checking';
}

// Decision that needs no request: null means "ask the gate".
function immediateWelcomeDecision(user) {
  if (!needsWelcomeFlow(user)) return 'app';
  if (isWelcomeActive(user.user_id)) return 'welcome';
  return null;
}

/**
 * React binding used by ProtectedRoute on the /welcome route. Returns
 * 'checking' | 'welcome' | 'app', decided ONCE per mount and user: the
 * flow itself clears the flag on its last screen (and "Ir al panel"
 * does too), which must not yank the user out mid-screen.
 *
 *   • flag false / cleared this session → 'app'
 *   • this tab was sent to /welcome by the gate → 'welcome' (no request)
 *   • otherwise (bookmark, restored tab, old OAuth return) → same gate
 *     as the app routes: brand-new → 'welcome', anything else → 'app'
 */
export function useWelcomeEntryGate(user, enabled, deps = defaultDeps) {
  const userId = user?.user_id || null;
  const [entry, setEntry] = useState(() => (
    enabled && userId ? { userId, decision: immediateWelcomeDecision(user) } : null
  ));
  const decision = entry && entry.userId === userId ? entry.decision : null;

  useEffect(() => {
    if (!enabled || !userId || decision) return undefined;
    const immediate = immediateWelcomeDecision(user);
    if (immediate) {
      setEntry({ userId, decision: immediate });
      return undefined;
    }
    let cancelled = false;
    resolveOnboardingGate({ userId, needsOnboarding: true, deps }).then((res) => {
      if (!cancelled) setEntry({ userId, decision: res.decision === 'onboarding' ? 'welcome' : 'app' });
    });
    return () => { cancelled = true; };
  // `user` is read only to take the first decision for this userId.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, userId, decision]);

  if (!enabled) return 'app';
  return decision || 'checking';
}

// Test-only: forget per-session memory between test cases.
export function __resetOnboardingGateForTests() {
  clearedUsers.clear();
  __resetWelcomeSessionForTests();
  timing.timeoutMs = GATE_TIMEOUT_MS;
  timing.retryDelaysMs = GATE_RETRY_DELAYS_MS;
}

// Test-only: shorten the hooks' timeout / retry backoff.
export function __setOnboardingGateTimingForTests({ timeoutMs, retryDelaysMs } = {}) {
  if (timeoutMs !== undefined) timing.timeoutMs = timeoutMs;
  if (retryDelaysMs !== undefined) timing.retryDelaysMs = retryDelaysMs;
}
