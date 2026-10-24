import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Tag, RefreshCw, Loader2, Building2, ArrowRight } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { getInboxCategories } from '../../lib/api';

/**
 * Industry-aware inbox categories (UI side).
 *
 * The backend owns the lists (backend/inbox_categories.py) and serves only
 * the current workspace's one at GET /api/inbox/categories:
 *   { industry, has_industry, category_set, label_es, label_en,
 *     categories: [{ key, label_es, label_en, suggested_action }] }
 * so a store never sees real-estate categories in its chips or filter.
 */

export function useInboxCategories(industry) {
  const [catalog, setCatalog] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setCatalog(await getInboxCategories());
    } catch (err) {
      // Categories are an enhancement: the inbox keeps working without them.
      // eslint-disable-next-line no-console
      console.warn('[inbox] could not load categories:', err?.message || err);
    }
  }, []);

  // Re-fetch when the business profile's industry changes (new list).
  useEffect(() => {
    refresh();
  }, [refresh, industry]);

  return { catalog, refresh };
}

export function categoryLabel(catalog, key, lang) {
  const cat = (catalog?.categories || []).find((c) => c.key === key);
  if (!cat) return null;
  return lang === 'en' ? cat.label_en : cat.label_es;
}

/** The item's category, only when it belongs to the workspace's current list. */
export function InboxCategoryChip({ catalog, categoryKey, lang, className = '' }) {
  const label = categoryKey ? categoryLabel(catalog, categoryKey, lang) : null;
  if (!label) return null;
  return (
    <Badge
      data-testid="inbox-category-chip"
      data-category={categoryKey}
      className={`gap-1 border-transparent shadow-none bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.15)] ${className}`}
    >
      <Tag size={10} />
      {label}
    </Badge>
  );
}

/** Category filter built from the workspace's list (+ "Reclasificar"). */
export function InboxCategoryFilter({
  catalog, value, onChange, counts = {}, lang, t, onReclassify, reclassifying = false,
}) {
  const categories = catalog?.categories || [];
  if (categories.length === 0) return null;
  const setName = lang === 'en' ? catalog.label_en : catalog.label_es;

  const chip = (key, label, count) => (
    <Button
      key={key}
      type="button"
      data-testid={`inbox-category-filter-${key}`}
      aria-pressed={value === key}
      variant={value === key ? 'default' : 'secondary'}
      size="sm"
      className="h-7 text-xs"
      onClick={() => onChange(key)}
    >
      {label}
      {typeof count === 'number' && count > 0 && (
        <span className="ml-1.5 text-[10px] opacity-70">{count}</span>
      )}
    </Button>
  );

  return (
    <div data-testid="inbox-category-filter" className="flex flex-wrap items-center gap-2 mb-4">
      <span className="flex items-center gap-1 text-xs text-muted-foreground mr-1" title={t('inbox_categories.set_label', { industry: setName })}>
        <Tag size={12} /> {t('inbox_categories.filter_label')}
      </span>
      {chip('all', t('inbox_categories.filter_all'))}
      {categories.map((c) => chip(c.key, lang === 'en' ? c.label_en : c.label_es, counts[c.key]))}
      {onReclassify && (
        <Button
          type="button"
          data-testid="inbox-reclassify-button"
          variant="ghost"
          size="sm"
          className="h-7 text-xs ml-auto"
          onClick={onReclassify}
          disabled={reclassifying}
          title={t('inbox_categories.reclassify_hint')}
        >
          {reclassifying ? (
            <><Loader2 size={12} className="animate-spin mr-1" /> {t('inbox_categories.reclassifying')}</>
          ) : (
            <><RefreshCw size={12} className="mr-1" /> {t('inbox_categories.reclassify')}</>
          )}
        </Button>
      )}
    </div>
  );
}

/** Gentle nudge while the workspace has not chosen its line of business. */
export function IndustryCategoryHint({ catalog, t }) {
  if (!catalog || catalog.has_industry !== false) return null;
  return (
    <div
      data-testid="inbox-industry-hint"
      className="flex items-start gap-3 p-3 mb-4 rounded-xl border border-[hsl(var(--info)/0.2)] bg-[hsl(var(--info)/0.06)]"
    >
      <Building2 size={16} className="mt-0.5 shrink-0 text-[hsl(var(--info))]" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{t('inbox_categories.hint_title')}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{t('inbox_categories.hint_body')}</p>
      </div>
      <Link
        to="/settings/profile"
        data-testid="inbox-industry-hint-link"
        className="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-[hsl(var(--info))] hover:underline"
      >
        {t('inbox_categories.hint_cta')} <ArrowRight size={12} />
      </Link>
    </div>
  );
}
