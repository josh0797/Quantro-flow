import React from 'react';
import { useLanguage } from '../context/LanguageContext';
import { LEGAL_URLS } from '../lib/legal';

/**
 * "Privacidad · Términos" — links to Quantro's canonical legal pages,
 * opened in a new tab. Used in the login footer.
 */
export default function LegalLinks({ className = '' }) {
  const { t } = useLanguage();
  const linkClass = 'hover:text-foreground hover:underline';
  return (
    <div
      data-testid="legal-links"
      className={`flex items-center gap-2 text-xs text-muted-foreground ${className}`}
    >
      <a
        href={LEGAL_URLS.privacy}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="legal-link-privacy"
        className={linkClass}
      >
        {t('legal.privacy')}
      </a>
      <span aria-hidden="true">·</span>
      <a
        href={LEGAL_URLS.terms}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="legal-link-terms"
        className={linkClass}
      >
        {t('legal.terms')}
      </a>
    </div>
  );
}
