import { apiErrorMessage } from './apiError';

describe('apiErrorMessage', () => {
  it('returns string details as-is', () => {
    expect(apiErrorMessage({ response: { data: { detail: 'Template not found' } } })).toBe('Template not found');
  });

  it('returns the localized message of an object detail (own OpenAI key errors)', () => {
    const err = {
      message: 'Request failed with status code 402',
      response: {
        data: {
          detail: {
            error: 'ai_own_key_error',
            reason: 'own_key_invalid',
            message: 'OpenAI rechazó la clave de este espacio de trabajo.',
          },
        },
      },
    };
    expect(apiErrorMessage(err)).toBe('OpenAI rechazó la clave de este espacio de trabajo.');
  });

  it('falls back to the error message, never to an object', () => {
    expect(apiErrorMessage({ message: 'Network Error' })).toBe('Network Error');
    expect(apiErrorMessage({ message: 'x', response: { data: { detail: { error: 'rbac_forbidden' } } } })).toBe('x');
  });
});
