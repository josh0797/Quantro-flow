import { LEGAL_URLS, PRIVACY_VERSION, TERMS_VERSION, buildConsentMetadata } from './legal';

describe('legal', () => {
  it('points at the canonical Quantro legal pages', () => {
    expect(LEGAL_URLS).toEqual({
      terms: 'https://www.quantro.technology/terms.html',
      privacy: 'https://www.quantro.technology/privacy.html',
      dpa: 'https://www.quantro.technology/dpa.html',
    });
  });

  it('records the accepted versions and the acceptance time', () => {
    const now = new Date('2026-09-30T15:04:05.678Z');
    expect(buildConsentMetadata(now)).toEqual({
      terms_version: '2026-09-30',
      privacy_version: '2026-09-30',
      terms_accepted_at: '2026-09-30T15:04:05.678Z',
    });
    expect(TERMS_VERSION).toBe('2026-09-30');
    expect(PRIVACY_VERSION).toBe('2026-09-30');
  });

  it('defaults the acceptance time to now', () => {
    const before = Date.now();
    const { terms_accepted_at: at } = buildConsentMetadata();
    expect(at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(Date.parse(at)).toBeGreaterThanOrEqual(before);
    expect(Date.parse(at)).toBeLessThanOrEqual(Date.now());
  });
});
