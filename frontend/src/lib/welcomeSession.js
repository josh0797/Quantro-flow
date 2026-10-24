/**
 * welcomeSession — what the browser remembers about the Welcome flow,
 * always scoped to ONE user so nothing leaks between accounts that share
 * a browser.
 *
 *   • progress (localStorage, per user) — OnboardingContext's step state
 *     (start choice, industry, which steps are real/demo), so a user who
 *     closes the tab mid-flow can resume. Dropped as soon as the user's
 *     `needs_onboarding` flag is cleared (flow finished, "Ir al panel",
 *     or the gate found an existing workspace): after that it only
 *     misleads (e.g. a stale "real" inbox shown as "Datos reales").
 *
 *   • active marker (sessionStorage, per tab) — set when the onboarding
 *     gate positively decided "brand-new workspace → /welcome" for this
 *     user. It survives reloads and the provider OAuth round trip (same
 *     tab), so a new signup who connected Google is not bounced out of
 *     the flow on the way back, while an existing owner (never marked)
 *     who opens /welcome from a bookmark or an old tab is sent to the app.
 *
 * Every storage access is wrapped: private mode / blocked storage only
 * loses persistence, never breaks the flow.
 */

export const LEGACY_PROGRESS_KEY = 'quantro:onboarding:state:v1';
const PROGRESS_PREFIX = 'quantro:onboarding:state:v2:';
const ACTIVE_KEY = 'quantro:welcome:active-user';

// In-memory mirror so the marker still works when sessionStorage throws.
const activeUsers = new Set();

export function progressKey(userId) {
  return userId ? `${PROGRESS_PREFIX}${userId}` : null;
}

export function readProgress(userId) {
  const key = progressKey(userId);
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function writeProgress(userId, state) {
  const key = progressKey(userId);
  if (!key) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(state));
  } catch {
    /* private mode / quota — the flow still works in memory */
  }
}

/** The pre-scoping key was shared by every user of the browser: drop it. */
export function dropLegacyProgress() {
  try {
    window.localStorage.removeItem(LEGACY_PROGRESS_KEY);
  } catch {
    /* ignore */
  }
}

export function markWelcomeActive(userId) {
  if (!userId) return;
  activeUsers.add(userId);
  try {
    window.sessionStorage.setItem(ACTIVE_KEY, userId);
  } catch {
    /* ignore — the in-memory mirror covers this page session */
  }
}

export function isWelcomeActive(userId) {
  if (!userId) return false;
  if (activeUsers.has(userId)) return true;
  try {
    return window.sessionStorage.getItem(ACTIVE_KEY) === userId;
  } catch {
    return false;
  }
}

/** Forget both the progress and the active marker of `userId`. */
export function endWelcomeSession(userId) {
  if (!userId) return;
  activeUsers.delete(userId);
  try {
    if (window.sessionStorage.getItem(ACTIVE_KEY) === userId) {
      window.sessionStorage.removeItem(ACTIVE_KEY);
    }
  } catch {
    /* ignore */
  }
  try {
    window.localStorage.removeItem(progressKey(userId));
  } catch {
    /* ignore */
  }
}

// Test-only: forget the active marker between test cases.
export function __resetWelcomeSessionForTests() {
  activeUsers.clear();
  try {
    window.sessionStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* ignore */
  }
}
