import {
  readProviderCallback,
  stripProviderCallbackParams,
  nextStepAfterProviderConnect,
} from './providerCallback';
import { translations } from '../i18n/translations';

describe('readProviderCallback', () => {
  it('parses a Google success return', () => {
    const params = new URLSearchParams('google_connected=success&account=a%40b.com&return_to=/settings');
    expect(readProviderCallback(params)).toEqual({
      provider: 'google', status: 'success', account: 'a@b.com', reason: '', missingScopes: [],
    });
  });

  it('parses a Microsoft permission error', () => {
    const params = new URLSearchParams('microsoft_connected=error&reason=permission_missing&missing_scopes=Mail.Send,Calendars.ReadWrite');
    expect(readProviderCallback(params)).toMatchObject({
      provider: 'microsoft', status: 'error', reason: 'permission_missing',
      missingScopes: ['Mail.Send', 'Calendars.ReadWrite'],
    });
  });

  it('returns null without a callback', () => {
    expect(readProviderCallback(new URLSearchParams('tab=permissions'))).toBeNull();
  });

  it('strips only the callback params', () => {
    const params = new URLSearchParams('google_connected=success&account=x&return_to=/connect&tab=permissions');
    expect(stripProviderCallbackParams(params).toString()).toBe('tab=permissions');
  });
});

describe('nextStepAfterProviderConnect', () => {
  it.each(['/welcome', '/welcome/', '/welcome/inbox', '/welcome/calendar'])('%s → CRM step', (path) => {
    expect(nextStepAfterProviderConnect(path)).toBe('/welcome/crm');
  });

  it('leaves other screens alone', () => {
    expect(nextStepAfterProviderConnect('/welcome/ready')).toBeNull();
    expect(nextStepAfterProviderConnect('/settings')).toBeNull();
  });
});

describe('new UI strings are bilingual', () => {
  const resolve = (tree, key) => key.split('.').reduce((node, part) => (node ? node[part] : undefined), tree);
  it.each([
    'welcome.go_to_dashboard',
    'welcome.sync.in_progress',
    'welcome.sync.in_progress_hint',
    'welcome.preview.sync_in_progress',
    'connect.drawer.reconnect',
    'connect.toasts.connect_failed',
    'connect.toasts.permission_missing',
    'settings.tabs.integrations',
  ])('%s exists in es and en', (key) => {
    expect(typeof resolve(translations.es, key)).toBe('string');
    expect(typeof resolve(translations.en, key)).toBe('string');
  });

  it('uses the owner-facing Spanish copy', () => {
    expect(translations.es.welcome.go_to_dashboard).toBe('Ir al panel');
    expect(translations.es.welcome.sync.in_progress).toBe('Sincronizando tus correos…');
    expect(translations.en.welcome.go_to_dashboard).toBe('Go to dashboard');
  });
});
