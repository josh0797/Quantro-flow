// src/components/LearnLink.js
// Contextual "Learn" link to the Product Hub page of the current module.
// Always opens in a new tab; the URL comes from lib/productHub (never inline).

import React from 'react';
import { BookOpen } from 'lucide-react';
import { buildLearnUrl, FLOW_ROUTE_CAPABILITY, trackHelp } from '../lib/productHub';
import { useLanguage } from '../context/LanguageContext';

/**
 * @param {{ route: keyof typeof FLOW_ROUTE_CAPABILITY, className?: string, compact?: boolean }} props
 */
export default function LearnLink({ route, className = '', compact = false }) {
  const { t } = useLanguage();
  const capabilityId = FLOW_ROUTE_CAPABILITY[route];
  if (!capabilityId) return null;
  const href = buildLearnUrl(capabilityId);
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      data-testid={`learn-link-${route}`}
      title={t('help.learn_about_module')}
      onClick={() => trackHelp('help_link_opened', { source: 'page_header', capability: capabilityId })}
      className={`inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-[hsl(var(--primary))] transition-colors ${className}`}
    >
      <BookOpen size={14} />
      {!compact && <span>{t('help.learn')}</span>}
    </a>
  );
}
