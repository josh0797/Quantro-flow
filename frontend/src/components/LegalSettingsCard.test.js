const mockLang = { current: 'es' };
jest.mock('../context/LanguageContext', () => {
  // eslint-disable-next-line global-require
  const { translations } = require('../i18n/translations');
  const resolve = (tree, key) => key.split('.').reduce((node, part) => (node == null ? node : node[part]), tree);
  return {
    useLanguage: () => ({
      lang: mockLang.current,
      t: (k) => {
        const v = resolve(translations[mockLang.current], k);
        return typeof v === 'string' ? v : k;
      },
    }),
  };
});

/* eslint-disable import/first */
import React from 'react';
import LegalSettingsCard from './LegalSettingsCard';
import { render, byTestId } from '../test/render';
/* eslint-enable import/first */

let view;

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('LegalSettingsCard', () => {
  it('links the three legal documents in a new tab and the privacy contact (ES)', async () => {
    mockLang.current = 'es';
    view = await render(<LegalSettingsCard />);
    const expected = {
      terms: ['https://www.quantro.technology/terms.html', 'Términos de Servicio'],
      privacy: ['https://www.quantro.technology/privacy.html', 'Aviso de Privacidad'],
      dpa: ['https://www.quantro.technology/dpa.html', 'Acuerdo de Procesamiento de Datos'],
    };
    Object.entries(expected).forEach(([key, [href, label]]) => {
      const a = byTestId(`settings-legal-${key}`);
      expect(a.getAttribute('href')).toBe(href);
      expect(a.getAttribute('target')).toBe('_blank');
      expect(a.getAttribute('rel')).toBe('noopener noreferrer');
      expect(a.textContent).toBe(label);
    });
    expect(byTestId('settings-legal-contact').getAttribute('href')).toBe('mailto:privacidad@quantroos.com');
    expect(byTestId('settings-legal-card').textContent).toContain('Privacidad y legal');
    // ES has no "documents are in Spanish" note.
    expect(byTestId('settings-legal-card').textContent).not.toContain('available in Spanish');
  });

  it('renders English labels and says the documents are in Spanish (EN)', async () => {
    mockLang.current = 'en';
    view = await render(<LegalSettingsCard />);
    expect(byTestId('settings-legal-terms').textContent).toBe('Terms of Service');
    expect(byTestId('settings-legal-privacy').textContent).toBe('Privacy Notice');
    expect(byTestId('settings-legal-card').textContent).toContain('These documents are available in Spanish.');
  });
});
