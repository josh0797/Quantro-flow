import React from 'react';
import { ExternalLink } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { useLanguage } from '../context/LanguageContext';
import { LEGAL_URLS } from '../lib/legal';

const PRIVACY_EMAIL = 'privacidad@quantroos.com';

/**
 * Settings → Espacio de Trabajo: the legal documents the account accepted
 * at signup, plus the privacy contact (account deletion is still manual,
 * per the privacy notice §6).
 */
export default function LegalSettingsCard() {
  const { t } = useLanguage();
  const links = [
    { key: 'terms', href: LEGAL_URLS.terms, label: t('legal.settings_terms') },
    { key: 'privacy', href: LEGAL_URLS.privacy, label: t('legal.settings_privacy') },
    { key: 'dpa', href: LEGAL_URLS.dpa, label: t('legal.settings_dpa') },
  ];
  const languageNote = t('legal.docs_language_note');

  return (
    <Card
      data-testid="settings-legal-card"
      className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]"
    >
      <h3 className="text-lg font-semibold text-foreground mb-1">{t('legal.settings_heading')}</h3>
      <p className="text-sm text-muted-foreground mb-4">{t('legal.settings_description')}</p>
      <ul className="space-y-2">
        {links.map(({ key, href, label }) => (
          <li key={key}>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`settings-legal-${key}`}
              className="inline-flex items-center gap-1.5 text-sm text-[hsl(var(--primary))] hover:underline"
            >
              {label}
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
      {languageNote && <p className="text-xs text-muted-foreground mt-3">{languageNote}</p>}
      <p className="text-xs text-muted-foreground mt-4 pt-4 border-t border-[hsl(var(--border))]">
        {t('legal.settings_contact')}{' '}
        <a
          href={`mailto:${PRIVACY_EMAIL}`}
          data-testid="settings-legal-contact"
          className="text-[hsl(var(--primary))] hover:underline"
        >
          {PRIVACY_EMAIL}
        </a>
        .
      </p>
    </Card>
  );
}
