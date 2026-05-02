import React from 'react';
import { CalendarDays, MapPin } from 'lucide-react';
import { useLanguage } from '../../../context/LanguageContext';

/**
 * CalendarMockup — today's timeline with two events plus an explicit
 * availability gap rendered as a soft cyan band. The intent is to
 * communicate "Quantro detects free time, not just blocks the calendar".
 */
const BLOCKS = [
  { type: 'event',        time: '09:30', duration: '45 min', title_key: 'event1_title', detail_key: 'event1_detail' },
  { type: 'availability', time: '11:00', duration: '60 min' },
  { type: 'event',        time: '14:00', duration: '30 min', title_key: 'event2_title', detail_key: 'event2_detail' },
  { type: 'event',        time: '16:30', duration: '20 min', title_key: 'event3_title', detail_key: 'event3_detail' },
];

export default function CalendarMockup() {
  const { t } = useLanguage();
  return (
    <div className="text-left" data-testid="calendar-mockup">
      <div className="flex items-center gap-2 mb-3 px-1">
        <CalendarDays size={14} className="text-[hsl(var(--primary))]" />
        <span className="text-xs uppercase tracking-[0.16em] font-semibold text-muted-foreground">
          {t('welcome.calendar.preview_header')}
        </span>
      </div>
      <ul className="space-y-2">
        {BLOCKS.map((b, i) => (
          <li
            key={`${b.time}-${b.type}`}
            className={[
              'flex items-stretch gap-3 rounded-xl border px-3 py-2.5',
              'transition-all duration-500 ease-out animate-in fade-in slide-in-from-bottom-1',
              b.type === 'availability'
                ? 'border-[hsl(var(--primary)/0.30)] bg-[hsl(var(--primary)/0.05)]'
                : 'border-[hsl(var(--border))] bg-[hsl(var(--background)/0.6)]',
            ].join(' ')}
            style={{ animationDelay: `${i * 200}ms`, animationFillMode: 'both' }}
          >
            <div className="flex flex-col items-end shrink-0 w-14">
              <span className="text-sm font-semibold tabular-nums">{b.time}</span>
              <span className="text-[10px] text-muted-foreground">{b.duration}</span>
            </div>
            <div className="w-px bg-[hsl(var(--border))]" />
            {b.type === 'availability' ? (
              <div className="flex-1 min-w-0 flex items-center">
                <span className="text-sm font-medium text-[hsl(var(--primary))]">
                  {t('welcome.calendar.gap_label')}
                </span>
              </div>
            ) : (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold tracking-tight truncate">
                  {t(`welcome.calendar.${b.title_key}`)}
                </p>
                <p className="text-xs text-muted-foreground truncate flex items-center gap-1 mt-0.5">
                  <MapPin size={10} />
                  {t(`welcome.calendar.${b.detail_key}`)}
                </p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
