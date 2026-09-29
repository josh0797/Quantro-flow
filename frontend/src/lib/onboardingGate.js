import { useEffect, useState } from 'react';
import { supabase } from './supabaseClient';
import { getConnectProviders, getBusinessProfile } from './api';

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
 *       - a Google or Microsoft connection exists (any state other than
 *         disconnected / configuration_missing — same rule as
 *         GET /api/connect/connections), or
 *       - the business profile has a chosen industry (new workspaces are
 *         seeded with industry "other"; the Welcome flow only writes the
 *         industry on its final screen, which also clears the flag)
 *   • otherwise (brand-new signup, or the checks failed/timed out)
 *                                        → /welcome (unchanged behaviour)
 */

export const REAL_DATA_PROVIDERS = ['google', 'microsoft'];
const NOT_CONNECTED_STATUSES = new Set(['disconnected', 'configuration_missing']);
export const GATE_TIMEOUT_MS = 8000;

// user_ids whose flag was cleared (or deliberately dismissed) during this
// page session, so a slow metadata refresh can never bounce them back.
const clearedUsers = new Set();

export function hasRealProviderConnection(providers) {
  if (!Array.isArray(providers)) return false;
  return providers.some(
    (p) =>
      p
      && REAL_DATA_PROVIDERS.includes(p.provider_id)
      && typeof p.status === 'string'
      && !NOT_CONNECTED_STATUSES.has(p.status),
  );
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
 * it for this session. The local memory is recorded even when the network
 * call fails so the user is never trapped in /welcome; the caller decides
 * whether to surface the error.
 */
export async function clearNeedsOnboardingFlag(userId, clearFlag = defaultDeps.clearFlag) {
  if (userId) clearedUsers.add(userId);
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

/**
 * Resolve the gate. Returns `{ decision: 'app' | 'onboarding', reason }`.
 * Never throws: any failure falls back to the Welcome flow, which always
 * offers a "Go to dashboard" exit.
 */
export async function resolveOnboardingGate({
  userId,
  needsOnboarding,
  deps = defaultDeps,
  timeoutMs = GATE_TIMEOUT_MS,
} = {}) {
  if (!needsOnboarding) return { decision: 'app', reason: 'no_flag' };
  if (wasOnboardingCleared(userId)) return { decision: 'app', reason: 'cleared' };

  const [providersRes, profileRes] = await Promise.allSettled([
    withTimeout(deps.fetchProviders, timeoutMs),
    withTimeout(deps.fetchBusinessProfile, timeoutMs),
  ]);
  const existing = workspaceHasExistingData({
    providers: providersRes.status === 'fulfilled' ? providersRes.value : null,
    businessProfile: profileRes.status === 'fulfilled' ? profileRes.value : null,
  });
  if (!existing) return { decision: 'onboarding', reason: 'new_workspace' };

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

/**
 * React binding used by ProtectedRoute. Returns 'checking' | 'app' |
 * 'onboarding'. When `enabled` is false (flag not set, or route bypasses
 * the gate) it returns 'app' without any network call.
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

// Test-only: forget per-session memory between test cases.
export function __resetOnboardingGateForTests() {
  clearedUsers.clear();
}
