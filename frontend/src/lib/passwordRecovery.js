/**
 * Password recovery + shared-account helpers (Supabase Auth, PKCE flow).
 *
 * Reset flow:
 *   1. LoginPage → "¿Olvidaste tu contraseña?" → requestPasswordReset(email)
 *      calls supabase.auth.resetPasswordForEmail with redirectTo
 *      `${origin}/auth/callback` — the same URL signup confirmation already
 *      uses, so no new Supabase redirect allow-list entry is needed (an
 *      exact entry does not match the URL once a query string is added).
 *   2. The email link lands on /auth/callback?code=…; supabase-js exchanges
 *      the code (detectSessionInUrl) and emits PASSWORD_RECOVERY.
 *   3. AuthCallback asks for a new password when isRecoveryCallback() says
 *      so → supabase.auth.updateUser({ password }).
 *
 * Why a local marker besides the event: supabase-js emits PASSWORD_RECOVERY
 * in a setTimeout after the exchange, so getSession() can resolve first and
 * the page would treat the recovery session as a normal sign-in. A PKCE
 * recovery link only works in the browser that asked for it (the verifier
 * lives in its localStorage), which is exactly where this marker lives, so
 * "marker present for this email" is a deterministic signal. `type=recovery`
 * in the URL (implicit flow / custom templates) is honoured as well.
 */

export const RECOVERY_MARKER_KEY = 'quantro-flow:password-recovery';
// Supabase's email link lifetime is 1 h by default and 24 h at most.
export const RECOVERY_MARKER_TTL_MS = 24 * 60 * 60 * 1000;
export const MIN_PASSWORD_LENGTH = 8;

let recoveryEventSeen = false;

export function notePasswordRecoveryEvent() {
  recoveryEventSeen = true;
}

export function resetRecoveryStateForTests() {
  recoveryEventSeen = false;
}

function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

function readMarker() {
  try {
    const raw = window.localStorage.getItem(RECOVERY_MARKER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

export function markRecoveryRequested(email, now = Date.now()) {
  try {
    window.localStorage.setItem(
      RECOVERY_MARKER_KEY,
      JSON.stringify({ email: normalizeEmail(email), at: now }),
    );
  } catch (_) {
    // Storage blocked (private mode): the PASSWORD_RECOVERY event still works.
  }
}

export function clearRecoveryState() {
  recoveryEventSeen = false;
  try {
    window.localStorage.removeItem(RECOVERY_MARKER_KEY);
  } catch (_) {
    // ignore
  }
}

/** True when the URL itself says this is a recovery redirect. */
export function urlSaysRecovery(search = '', hash = '') {
  const fromSearch = new URLSearchParams(search || '').get('type');
  const fromHash = new URLSearchParams(String(hash || '').replace(/^#/, '')).get('type');
  return fromSearch === 'recovery' || fromHash === 'recovery';
}

/** A reset was requested in this browser for `email` (any email if omitted) recently. */
export function hasFreshRecoveryMarker(email, now = Date.now()) {
  const marker = readMarker();
  if (!marker || typeof marker.at !== 'number') return false;
  if (now - marker.at > RECOVERY_MARKER_TTL_MS || now < marker.at) return false;
  if (email === undefined) return true;
  return marker.email === normalizeEmail(email);
}

/**
 * Should /auth/callback ask for a new password?
 * `sessionEmail` is the email of the session the callback produced.
 */
export function isRecoveryCallback({ search, hash, sessionEmail, now = Date.now() } = {}) {
  if (urlSaysRecovery(search, hash)) return true;
  if (recoveryEventSeen) return true;
  return Boolean(sessionEmail) && hasFreshRecoveryMarker(sessionEmail, now);
}

export function recoveryRedirectUrl(origin = window.location.origin) {
  return `${origin}/auth/callback`;
}

/**
 * Send the reset email. Resolves to { ok: true } whether or not an account
 * exists (Supabase answers the same for unknown emails — callers must show
 * a neutral message), or { ok: false, error } when the request itself failed
 * (rate limit, network).
 */
export async function requestPasswordReset(supabase, email, origin = window.location.origin) {
  const clean = String(email || '').trim();
  const { error } = await supabase.auth.resetPasswordForEmail(clean, {
    redirectTo: recoveryRedirectUrl(origin),
  });
  if (error) return { ok: false, error };
  markRecoveryRequested(clean);
  return { ok: true };
}

/**
 * Supabase answers signUp() for an email that already has a confirmed
 * account with a user whose `identities` array is empty — and sends no
 * email. Quantro OS and Flow share that account, so the right move is
 * "sign in instead", not "check your inbox".
 */
export function isExistingAccountSignup(result) {
  const identities = result?.user?.identities;
  return Array.isArray(identities) && identities.length === 0;
}
