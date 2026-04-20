import React from 'react';
import { Globe } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useLanguage } from '../context/LanguageContext';
import { toast } from 'sonner';

/**
 * LanguageSwitcher — drop-in Shadcn Select bound to the Language context.
 * Used in Sidebar (compact) and Settings (full label).
 *
 * Props:
 *   variant:  'compact' | 'full'  (default 'full')
 *   onChange: optional callback after language changes
 */
export default function LanguageSwitcher({ variant = 'full', onChange }) {
  const { lang, setLang, t, supported } = useLanguage();

  const handleChange = (next) => {
    if (next === lang) return;
    setLang(next);
    // Translate the toast in the NEW language immediately for better UX.
    const label =
      supported.find((l) => l.code === next)?.label ||
      (next === 'es' ? 'Español' : 'English');
    // Note: t() will already use the new language on the next render,
    // but we compose the message from the new translations for immediacy.
    toast.success(
      // read from translations directly to avoid waiting for re-render timing
      (next === 'es'
        ? `Idioma cambiado a ${label}`
        : `Language switched to ${label}`)
    );
    if (onChange) onChange(next);
  };

  if (variant === 'compact') {
    return (
      <Select value={lang} onValueChange={handleChange}>
        <SelectTrigger
          data-testid="language-switcher-compact"
          className="h-8 px-2 text-xs bg-[hsl(var(--muted)/0.4)] border-[hsl(var(--border))]"
          aria-label={t('language.label')}
        >
          <Globe size={12} className="mr-1.5 text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {supported.map((l) => (
            <SelectItem key={l.code} value={l.code} data-testid={`language-option-${l.code}`}>
              {l.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  return (
    <div className="space-y-1" data-testid="language-switcher">
      <label className="text-xs flex items-center gap-1.5 text-muted-foreground">
        <Globe size={12} /> {t('language.label')}
      </label>
      <Select value={lang} onValueChange={handleChange}>
        <SelectTrigger
          data-testid="language-switcher-trigger"
          className="bg-[hsl(var(--background))]"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {supported.map((l) => (
            <SelectItem key={l.code} value={l.code} data-testid={`language-option-${l.code}`}>
              {l.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
