/**
 * Legal documents + the consent record stored at signup.
 *
 * Flow uses the same Quantro account and plans, so it shares Quantro's
 * legal texts. The canonical pages are served by the Quantro OS app
 * (konta repo: public/terms.html, public/privacy.html, public/dpa.html);
 * the privacy notice covers Flow in its §3.2.
 *
 * TERMS_VERSION / PRIVACY_VERSION are the "Última actualización" dates
 * of those pages. Bump them in the same release as any change to the
 * pages, so each account records the version it actually accepted.
 */
export const LEGAL_URLS = {
  terms: 'https://www.quantro.technology/terms.html',
  privacy: 'https://www.quantro.technology/privacy.html',
  dpa: 'https://www.quantro.technology/dpa.html',
};

export const TERMS_VERSION = '2026-09-30';
export const PRIVACY_VERSION = '2026-09-30';

/**
 * Fields merged into supabase.auth.signUp `options.data` (they land in
 * auth.users.raw_user_meta_data) once the user ticks the signup checkbox.
 */
export function buildConsentMetadata(now = new Date()) {
  return {
    terms_version: TERMS_VERSION,
    privacy_version: PRIVACY_VERSION,
    terms_accepted_at: now.toISOString(),
  };
}
