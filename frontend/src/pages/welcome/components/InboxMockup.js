import React from 'react';
import { Mail } from 'lucide-react';
import { useLanguage } from '../../../context/LanguageContext';

/**
 * InboxMockup — a non-interactive snapshot of what the Smart Inbox
 * looks like with realistic conversation rows. The data is intentionally
 * generic (no industry assumptions) and rendered with the same visual
 * language as the production inbox so users perceive it as a true peek.
 */
const ROWS = [
  { initials: 'AC', name: 'Andrea C.',     subject: 'preview_row1_subject', snippet: 'preview_row1_snippet', tag: 'tag_opportunity', time: '09:42' },
  { initials: 'DM', name: 'Diego M.',       subject: 'preview_row2_subject', snippet: 'preview_row2_snippet', tag: 'tag_no_reply',     time: '08:18' },
  { initials: 'LS', name: 'Laura S.',       subject: 'preview_row3_subject', snippet: 'preview_row3_snippet', tag: 'tag_for_today',    time: 'Ayer' },
];

const TAG_STYLES = {
  tag_opportunity: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.30)]',
  tag_no_reply:    'bg-[hsl(var(--destructive)/0.10)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.25)]',
  tag_for_today:   'bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))] border-[hsl(var(--accent)/0.30)]',
};

export default function InboxMockup() {
  const { t } = useLanguage();
  return (
    <div className="text-left" data-testid="inbox-mockup">
      <div className="flex items-center gap-2 mb-3 px-1">
        <Mail size={14} className="text-[hsl(var(--primary))]" />
        <span className="text-xs uppercase tracking-[0.16em] font-semibold text-muted-foreground">
          {t('welcome.inbox.preview_header')}
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">3 / 3</span>
      </div>
      <ul className="space-y-2">
        {ROWS.map((r, i) => (
          <li
            key={r.initials}
            className={[
              'flex items-start gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background)/0.6)] px-3 py-2.5',
              'transition-all duration-500 ease-out',
              'animate-in fade-in slide-in-from-bottom-1',
            ].join(' ')}
            style={{ animationDelay: `${i * 220}ms`, animationFillMode: 'both' }}
          >
            <div className="size-8 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] flex items-center justify-center text-[11px] font-semibold shrink-0">
              {r.initials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate">{r.name}</span>
                <span className="text-[10px] text-muted-foreground ml-auto shrink-0">{r.time}</span>
              </div>
              <p className="text-sm font-semibold tracking-tight truncate mt-0.5">
                {t(`welcome.inbox.${r.subject}`)}
              </p>
              <p className="text-xs text-muted-foreground truncate mt-0.5">
                {t(`welcome.inbox.${r.snippet}`)}
              </p>
            </div>
            <span
              className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] font-semibold ${TAG_STYLES[r.tag]}`}
            >
              {t(`welcome.inbox.${r.tag}`)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
