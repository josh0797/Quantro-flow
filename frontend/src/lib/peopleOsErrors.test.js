import { translations } from '../i18n/translations';
import { PEOPLE_OS_ERROR_CODES, PEOPLE_PERMISSION_NAMES, peopleOsErrorMessage } from './peopleOsErrors';

// The real resolver's behaviour (LanguageContext): dot path, {{var}}, key as last resort.
const tFor = (lang) => (key, vars) => {
  const value = key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), translations[lang]);
  if (typeof value !== 'string') return key;
  return value.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (m, name) => (vars && name in vars ? String(vars[name]) : m));
};

const apiError = (detail, message = 'Request failed with status code 409') => ({
  message,
  response: { data: { detail } },
});

describe('People OS error copy', () => {
  it.each(['es', 'en'])('has %s copy for every code and permission name', (lang) => {
    const t = tFor(lang);
    for (const code of PEOPLE_OS_ERROR_CODES) {
      expect(t(`people_os.errors.${code}`)).not.toBe(`people_os.errors.${code}`);
    }
    expect(t('people_os.errors.permission_required_named')).toContain('{{permission}}');
    for (const name of PEOPLE_PERMISSION_NAMES) {
      expect(t(`people_os.permission_names.${name}`)).not.toBe(`people_os.permission_names.${name}`);
    }
  });

  it('keeps Spanish and English in parity for the People OS and members keys', () => {
    const keys = (obj, prefix = '') => Object.entries(obj).flatMap(([k, v]) => (
      v && typeof v === 'object' ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]
    )).sort();
    for (const section of ['people_os', 'members', 'invite']) {
      expect(keys(translations.es[section])).toEqual(keys(translations.en[section]));
    }
  });

  it('translates a People OS refusal instead of showing the API text', () => {
    const t = tFor('es');
    const err = apiError({ error: 'seat_required', message: 'Every seat on the plan is taken.' });
    expect(peopleOsErrorMessage(err, t)).toBe(translations.es.people_os.errors.seat_required);
    expect(peopleOsErrorMessage(apiError({ error: 'ownership_transfer_disabled', message: 'x' }), tFor('en')))
      .toBe(translations.en.people_os.errors.ownership_transfer_disabled);
  });

  it('names the missing Quantro OS function', () => {
    const msg = peopleOsErrorMessage(
      apiError({ error: 'permission_required', permission: 'people.invite', message: 'x' }),
      tFor('es'),
    );
    expect(msg).toBe('Necesitas la función «Invitar personas» en Quantro OS; pídesela al dueño.');
    // An unknown key falls back to the generic sentence, never to the raw key.
    expect(peopleOsErrorMessage(apiError({ error: 'permission_required', permission: 'people.other' }), tFor('es')))
      .toBe(translations.es.people_os.errors.permission_required);
  });

  it('falls back to the generic API message for anything else', () => {
    const t = tFor('es');
    expect(peopleOsErrorMessage(apiError('Requires leader role'), t)).toBe('Requires leader role');
    expect(peopleOsErrorMessage(apiError({ error: 'rbac_forbidden', message: 'Nope' }), t)).toBe('Nope');
    expect(peopleOsErrorMessage({ message: 'Network Error' }, t)).toBe('Network Error');
  });
});
