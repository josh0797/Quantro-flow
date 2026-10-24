import {
  RECOVERY_MARKER_KEY,
  RECOVERY_MARKER_TTL_MS,
  clearRecoveryState,
  hasFreshRecoveryMarker,
  isExistingAccountSignup,
  isRecoveryCallback,
  markRecoveryRequested,
  notePasswordRecoveryEvent,
  recoveryRedirectUrl,
  requestPasswordReset,
  resetRecoveryStateForTests,
  urlSaysRecovery,
} from './passwordRecovery';

const NOW = 1_800_000_000_000;

beforeEach(() => {
  window.localStorage.clear();
  resetRecoveryStateForTests();
});

describe('isExistingAccountSignup', () => {
  it('is true only for the empty-identities user Supabase returns for a taken email', () => {
    expect(isExistingAccountSignup({ user: { id: 'u', identities: [] }, session: null })).toBe(true);
    expect(isExistingAccountSignup({ user: { id: 'u', identities: [{ id: 'i' }] }, session: null })).toBe(false);
    // Projects that do not expose identities: never guess "existing".
    expect(isExistingAccountSignup({ user: { id: 'u' }, session: null })).toBe(false);
    expect(isExistingAccountSignup(null)).toBe(false);
    expect(isExistingAccountSignup(undefined)).toBe(false);
  });
});

describe('recovery detection', () => {
  it('reads type=recovery from the query or the hash', () => {
    expect(urlSaysRecovery('?type=recovery', '')).toBe(true);
    expect(urlSaysRecovery('', '#access_token=x&type=recovery')).toBe(true);
    expect(urlSaysRecovery('?code=abc', '')).toBe(false);
    expect(urlSaysRecovery('?type=signup', '#type=magiclink')).toBe(false);
    expect(urlSaysRecovery()).toBe(false);
  });

  it('a reset requested in this browser marks the callback for that email only, for a limited time', () => {
    markRecoveryRequested('  Ana@Example.com ', NOW);
    expect(hasFreshRecoveryMarker('ana@example.com', NOW + 1000)).toBe(true);
    expect(hasFreshRecoveryMarker('other@example.com', NOW + 1000)).toBe(false);
    expect(hasFreshRecoveryMarker(undefined, NOW + 1000)).toBe(true);
    expect(hasFreshRecoveryMarker('ana@example.com', NOW + RECOVERY_MARKER_TTL_MS + 1)).toBe(false);

    expect(isRecoveryCallback({ search: '?code=c', hash: '', sessionEmail: 'ANA@example.com', now: NOW + 5 })).toBe(true);
    // A signup confirmation for someone else in the same browser is not a reset.
    expect(isRecoveryCallback({ search: '?code=c', hash: '', sessionEmail: 'bob@example.com', now: NOW + 5 })).toBe(false);
    expect(isRecoveryCallback({ search: '?code=c', hash: '', sessionEmail: null, now: NOW + 5 })).toBe(false);
  });

  it('the PASSWORD_RECOVERY event alone is enough, and clearing forgets everything', () => {
    expect(isRecoveryCallback({ search: '?code=c', sessionEmail: 'a@b.co' })).toBe(false);
    notePasswordRecoveryEvent();
    expect(isRecoveryCallback({ search: '?code=c', sessionEmail: 'a@b.co' })).toBe(true);

    markRecoveryRequested('a@b.co');
    clearRecoveryState();
    expect(window.localStorage.getItem(RECOVERY_MARKER_KEY)).toBeNull();
    expect(isRecoveryCallback({ search: '?code=c', sessionEmail: 'a@b.co' })).toBe(false);
  });

  it('ignores a corrupt marker', () => {
    window.localStorage.setItem(RECOVERY_MARKER_KEY, '{not json');
    expect(hasFreshRecoveryMarker('a@b.co')).toBe(false);
  });
});

describe('requestPasswordReset', () => {
  const client = (result) => ({ auth: { resetPasswordForEmail: jest.fn().mockResolvedValue(result) } });

  it('sends the link back to /auth/callback (the URL signup already uses) and remembers the request', async () => {
    const supabase = client({ data: {}, error: null });
    const res = await requestPasswordReset(supabase, ' ana@example.com ', 'https://www.quantroflow.cloud');
    expect(res).toEqual({ ok: true });
    expect(supabase.auth.resetPasswordForEmail).toHaveBeenCalledWith('ana@example.com', {
      redirectTo: 'https://www.quantroflow.cloud/auth/callback',
    });
    expect(recoveryRedirectUrl('https://x.test')).toBe('https://x.test/auth/callback');
    expect(hasFreshRecoveryMarker('ana@example.com')).toBe(true);
  });

  it('reports a failed request without remembering it', async () => {
    const error = { status: 429, message: 'For security purposes, you can only request this after 60 seconds.' };
    const res = await requestPasswordReset(client({ data: null, error }), 'ana@example.com', 'https://x.test');
    expect(res).toEqual({ ok: false, error });
    expect(hasFreshRecoveryMarker()).toBe(false);
  });
});
