import React from 'react';
import { Users2 } from 'lucide-react';
import { useLanguage } from '../../../context/LanguageContext';

/**
 * CRMMockup — a four-column pipeline preview. The columns are stacked
 * on mobile and arranged horizontally on ≥ sm. Each card is a single
 * deal with a soft accent border, mirroring the future production CRM.
 */
const COLUMNS = [
  { key: 'lead',          count: 4, deals: ['deal_lead_1', 'deal_lead_2'] },
  { key: 'qualified',     count: 3, deals: ['deal_qual_1', 'deal_qual_2'] },
  { key: 'negotiation',   count: 1, deals: ['deal_neg_1'] },
  { key: 'closed',        count: 1, deals: ['deal_closed_1'] },
];

const COLUMN_ACCENT = {
  lead:        'border-[hsl(var(--muted-foreground)/0.30)] text-muted-foreground',
  qualified:   'border-[hsl(var(--accent)/0.30)] text-[hsl(var(--accent))]',
  negotiation: 'border-[hsl(var(--primary)/0.30)] text-[hsl(var(--primary))]',
  closed:      'border-emerald-500/30 text-emerald-400',
};

export default function CRMMockup() {
  const { t } = useLanguage();
  return (
    <div className="text-left" data-testid="crm-mockup">
      <div className="flex items-center gap-2 mb-3 px-1">
        <Users2 size={14} className="text-[hsl(var(--primary))]" />
        <span className="text-xs uppercase tracking-[0.16em] font-semibold text-muted-foreground">
          {t('welcome.crm.preview_header')}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {COLUMNS.map((c, i) => (
          <div
            key={c.key}
            className={[
              'rounded-xl border bg-[hsl(var(--background)/0.6)] p-2.5 min-h-[120px]',
              'transition-all duration-500 ease-out animate-in fade-in slide-in-from-bottom-1',
              COLUMN_ACCENT[c.key],
            ].join(' ')}
            style={{ animationDelay: `${i * 180}ms`, animationFillMode: 'both' }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] uppercase tracking-[0.14em] font-semibold">
                {t(`welcome.crm.col_${c.key}`)}
              </span>
              <span className="text-[10px] tabular-nums opacity-80">{c.count}</span>
            </div>
            <ul className="space-y-1.5">
              {c.deals.map((d) => (
                <li
                  key={d}
                  className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1.5 text-[11px] font-medium text-foreground/90 truncate"
                >
                  {t(`welcome.crm.${d}`)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
